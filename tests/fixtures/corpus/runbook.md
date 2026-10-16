# Runbook: PostgreSQL Replica Lag High

| Field | Value |
|---|---|
| **Alert name** | `PostgresReplicaLagHigh` / `PostgresReplicaLagCritical` |
| **Service** | `orders-db` (Postgres 16, primary + 3 streaming replicas) |
| **Owning team** | Data Platform (`#data-platform`, PagerDuty: `dp-primary`) |
| **Severity** | SEV3 at warning, SEV2 at critical |
| **Last reviewed** | 2026-09-14 by @mkhan |

> **TL;DR:** Figure out whether the replica can't *receive* WAL (network/primary), can't *replay* WAL (I/O, conflicts, long queries), or the primary is *generating* WAL faster than normal (bulk job). Pull the lagging replica out of the read pool first if lag > 60s, then fix the cause.

---

## Alert Definition

```promql
# warning: > 30s for 5m
max by (instance) (pg_replication_lag_seconds{cluster="orders-db"}) > 30

# critical: > 300s for 5m, or replica disconnected
max by (instance) (pg_replication_lag_seconds{cluster="orders-db"}) > 300
  or pg_stat_replication_connected{cluster="orders-db"} == 0
```

Note: `pg_replication_lag_seconds` is computed on the replica as `now() - pg_last_xact_replay_timestamp()`. On a quiet primary this **overstates** lag because there are no new transactions to replay. If writes are near zero (e.g. 03:00 UTC on a Sunday), check byte lag before panicking.

## Symptoms

- Grafana dashboard **Orders DB / Replication** shows one or more replicas diverging from the primary.
- Users report "I placed an order but it's not in my order history" — classic read-after-write inconsistency, since `order-history-api` reads from replicas.
- `reporting-worker` jobs time out or return stale aggregates.
- Possibly in replica logs:
  - `canceling statement due to conflict with recovery`
  - `could not receive data from WAL stream`
  - `requested WAL segment ... has already been removed` (bad — see [Replica fell off WAL](#replica-fell-off-wal))

## Impact

| Lag | Impact |
|---|---|
| < 30s | Generally invisible. No action beyond watching. |
| 30s – 5m | Stale reads in order history and the merchant dashboard. Support tickets start trickling in. |
| > 5m | Reporting is wrong; pgbouncer may route reads to a badly stale node. If the primary fails now, failover to this replica **loses data** or delays promotion. |
| Disconnected | Replica is useless; reduced read capacity and failover headroom. Primary may accumulate WAL in replication slots and fill its disk. |

The last point is the one that turns a SEV3 into a SEV1. Keep an eye on primary disk.

---

## Diagnosis

### 1. Confirm scope

Is it one replica or all of them?

- **One replica** → something local to that host (disk, CPU, long query, network to that AZ).
- **All replicas** → something on the primary (WAL burst, primary I/O, network egress).

### 2. Check replication state on the primary

```bash
psql -h orders-db-primary.internal -U sre_ro -d orders
```

```sql
SELECT application_name,
       client_addr,
       state,
       sync_state,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn))   AS send_lag,
       pg_size_pretty(pg_wal_lsn_diff(sent_lsn, flush_lsn))              AS flush_lag,
       pg_size_pretty(pg_wal_lsn_diff(flush_lsn, replay_lsn))            AS replay_lag,
       write_lag, flush_lag AS flush_lag_time, replay_lag AS replay_lag_time
FROM pg_stat_replication
ORDER BY application_name;
```

How to read this:

- **Replica missing from the output** → it's disconnected. Go to step 5.
- **`send_lag` large** → primary can't push WAL fast enough. Network or primary saturation.
- **`flush_lag` large** → replica is receiving but slow to write to disk. Replica I/O.
- **`replay_lag` large, others small** → WAL is on the replica's disk but isn't being applied. Usually a long-running query blocking replay, or replay is CPU/I/O-bound. Go to step 3.

### 3. Check for replay being blocked on the replica

```sql
-- on the lagging replica
SELECT pg_is_in_recovery(),
       pg_is_wal_replay_paused(),
       now() - pg_last_xact_replay_timestamp() AS replay_delay;

SELECT pid, usename, application_name, state,
       now() - xact_start AS xact_age,
       wait_event_type, wait_event,
       left(query, 120) AS query
FROM pg_stat_activity
WHERE backend_type = 'client backend'
  AND xact_start IS NOT NULL
ORDER BY xact_start
LIMIT 10;
```

- If `pg_is_wal_replay_paused()` is `true`, someone paused it. Find out who in `#data-platform` before resuming.
- We run with `hot_standby_feedback = on` and `max_standby_streaming_delay = 60s`. A long query on a replica can therefore delay replay up to 60s per conflict, and those add up. Anything from `reporting-worker` older than ~10 minutes is the usual suspect.

### 4. Check WAL generation rate on the primary

```sql
-- run twice, ~60s apart, and diff
SELECT now(), pg_current_wal_lsn();
```

Or just look at the **WAL bytes/sec** panel. Normal for `orders-db` is 5–15 MB/s. If you see 80+ MB/s, something is writing heavily:

```sql
SELECT pid, usename, application_name,
       now() - query_start AS runtime,
       left(query, 120) AS query
FROM pg_stat_activity
WHERE state = 'active' AND backend_type = 'client backend'
ORDER BY query_start
LIMIT 10;
```

Common culprits: backfill migrations, `VACUUM FULL`, bulk `UPDATE` from the `nightly-reconcile` job, index rebuilds.

### 5. Check the replica host

```bash
ssh orders-db-replica-2.internal

# Is postgres even running and streaming?
sudo systemctl status postgresql@16-main
sudo -u postgres psql -c "SELECT status, sender_host, last_msg_receipt_time FROM pg_stat_wal_receiver;"

# Disk and I/O
df -h /var/lib/postgresql
iostat -xz 5 3

# Recent errors
sudo journalctl -u postgresql@16-main --since "30 min ago" | grep -Ei 'error|fatal|wal'
```

Look for `%util` pinned near 100 on the data volume, or `await` well above baseline (~2ms on our gp3 volumes).

### 6. Check replication slots on the primary

```sql
SELECT slot_name, active,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal
FROM pg_replication_slots;
```

Retained WAL over ~50 GB on an inactive slot is a disk-full risk on the primary. Primary data volume is 1 TB; alert fires at 80%.

---

## Mitigation

Work top-down. Don't skip step 1 if lag is user-visible.

### 1. Take the lagging replica out of the read pool

If lag > 60s and only a subset of replicas is affected:

```bash
# Drains reads from the replica via pgbouncer config + reload
./ops/db/drain-replica.sh orders-db-replica-2
```

Verify in the **pgbouncer / backends** panel that connections to that host drop to zero. If **all** replicas are lagging, don't drain them all — instead flip `order-history-api` to read-from-primary:

```bash
featurectl set order-history-api.read_from_primary true --reason "INC-XXXX replica lag"
```

The primary can absorb this for a few hours at normal traffic. It cannot absorb `reporting-worker` too — pause that:

```bash
kubectl -n reporting scale deploy/reporting-worker --replicas=0
```

### 2. Remove the cause

| Cause | Action |
|---|---|
| Long query blocking replay | `SELECT pg_cancel_backend(<pid>);` If it ignores the cancel after 30s, `pg_terminate_backend(<pid>)`. Note the query in the incident channel. |
| Bulk write job on primary | Ask the owner to pause or throttle. If unreachable and lag > 5m, cancel it — the job should be idempotent; if it isn't, that's a follow-up. |
| Replay paused | `SELECT pg_wal_replay_resume();` — only after confirming nobody paused it on purpose. |
| Replica disk I/O saturated | Check for a runaway query or `autovacuum` on the replica side; otherwise this replica may need a larger volume. Leave it drained and escalate. |
| Network | Check the AZ status page and VPC flow logs. If an AZ is degraded, leave the replica drained and wait it out. |

### 3. Watch it recover

Lag should start falling within a few minutes of removing the cause. Rough rule: a healthy replica catches up at 3–5x the normal WAL rate. If lag isn't trending down after 15 minutes, escalate.

Once lag < 10s for 10 minutes, undo step 1 in reverse:

```bash
./ops/db/undrain-replica.sh orders-db-replica-2
featurectl set order-history-api.read_from_primary false
kubectl -n reporting scale deploy/reporting-worker --replicas=4
```

### Replica fell off WAL

If the replica log says `requested WAL segment ... has already been removed`, it cannot catch up by streaming. It needs a rebuild from the base backup:

```bash
./ops/db/rebuild-replica.sh orders-db-replica-2 --from-backup latest
```

This takes ~2–3 hours for the current dataset size. Leave the replica drained throughout. **Do not** drop its replication slot on the primary unless the primary disk is above 90% — check with Data Platform first.

---

## Escalation

| When | Who |
|---|---|
| Lag > 5m and not trending down after 15 min of mitigation | Page Data Platform secondary (`dp-secondary`) |
| Primary disk > 85%, or more than one replica disconnected | Page Data Platform secondary **and** declare SEV2 in `#incidents` |
| Primary itself unhealthy, or failover being considered | SEV1. Page the Data Platform lead and the Incident Commander rotation. **Do not** promote a replica on your own. |
| Bulk job owner unreachable and job must be stopped | Owning team's on-call via PagerDuty; cc their manager in the incident channel |

When paging, include: which replicas, current lag (seconds and bytes), what you've already tried, and a link to the dashboard.

---

## Post-Incident

- [ ] Write up the incident in the template within 2 business days if SEV2 or above; a short note in `#data-platform` is fine for SEV3.
- [ ] Record the root cause category (long query / WAL burst / I/O / network / other) in the incident tracker — we use this to decide whether to tune `max_standby_streaming_delay`.
- [ ] If a batch job caused it, file a ticket against the owning team to add throttling or move it to a maintenance window.
- [ ] If a `reporting-worker` query caused it, check whether it should move to the analytics replica (`orders-db-analytics`), which has `hot_standby_feedback = off` and a relaxed delay.
- [ ] If the alert was noisy (e.g. quiet-hour false positive), propose a threshold change in a PR to `alerts/postgres.yaml`.
- [ ] Update this runbook with anything that was missing or wrong. Bump the "Last reviewed" date.

## Related

- Dashboard: Grafana → **Orders DB / Replication**
- [Postgres failover runbook](./postgres-failover.md)
- [Replica rebuild procedure](./postgres-replica-rebuild.md)
- PostgreSQL docs: *Hot Standby — Handling Query Conflicts* (section 26.4.2)
