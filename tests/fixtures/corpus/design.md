# RFC-0142: Event-Driven Order Processing

| Field        | Value                                      |
|--------------|--------------------------------------------|
| Author       | Priya Raman (Commerce Platform)            |
| Reviewers    | Dmitri Volkov, Hannah Okafor, Luis Ortega  |
| Status       | **Draft** — open for comments              |
| Created      | 2026-09-21                                 |
| Last updated | 2026-10-06                                 |
| Tracking     | PLAT-3381                                  |

## Summary

Today, placing an order at Brightcart triggers a synchronous chain of five REST
calls (`order-api` → `inventory` → `payments` → `fulfillment` → `notifications`).
Any slow or unavailable downstream service fails or stalls the whole checkout.
This RFC proposes replacing the chain with an event-driven flow: `order-api`
persists the order and publishes an `OrderPlaced` event; downstream services
consume events and publish their own outcomes. Checkout latency is decoupled
from fulfillment and notification, and each service can fail and recover
independently.

## Context

### Current architecture

```
client ──► order-api ──► inventory ──► payments ──► fulfillment ──► notifications
              │             (reserve)     (charge)     (create shipment)  (email/SMS)
              ▼
          orders DB
```

Each hop is a blocking HTTP call with its own timeout and retry policy. The
`order-api` request handler holds the client connection open until the entire
chain returns.

### What's going wrong

Over the last two quarters we've seen the following:

- **Cascading failures.** The 2026-07-14 incident (INC-2207) started with a
  degraded SMTP provider in `notifications`. Because retries stacked at every
  hop, p99 checkout latency climbed to 41s and we dropped ~6% of orders over
  48 minutes.
- **Tail latency.** Checkout p99 is 2.8s on a normal day; roughly 60% of that is
  spent in `fulfillment` and `notifications`, neither of which the customer
  needs to wait for.
- **Retry amplification.** With 3 retries at each of 4 hops, a single client
  request can fan out to as many as 81 calls to `notifications` in the worst
  case.
- **Coupled deploys.** Changes to request/response contracts require
  coordinated releases across teams. We had three rollbacks in Q2 caused by
  contract drift.
- **Partial-failure ambiguity.** When `fulfillment` times out after `payments`
  succeeded, we have no reliable record of what happened. Support resolves
  these by hand (~40 tickets/week).

## Goals

1. Return a checkout response to the client once the order is durably accepted
   and payment is authorized — not after fulfillment and notification.
2. Isolate failures so that an outage in a non-critical service (fulfillment,
   notifications, analytics) does not affect order acceptance.
3. Make every order's state transitions explicit, durable, and replayable.
4. Let teams evolve and deploy their services independently, with versioned
   event schemas instead of synchronous contracts.
5. Reduce checkout p99 to under 800ms.

## Non-goals

- Rewriting `payments` internals or changing payment providers.
- Migrating the orders database off PostgreSQL.
- Event sourcing as the system of record. Events are an integration mechanism;
  each service keeps its own database as the source of truth.
- Changing the public checkout API shape (clients see the same endpoint; only
  latency and some status semantics change).
- Multi-region active-active. That's tracked separately in RFC-0128.

## Proposed design

### Overview

```
client ──► order-api ──► orders DB + outbox
                              │
                       outbox relay
                              ▼
                     ┌──── message broker ────┐
                     │  topic: orders.events  │
                     └──┬──────┬──────┬───────┘
                        ▼      ▼      ▼
                 inventory  payments  fulfillment ──► notifications
```

Payment authorization stays on the synchronous path because the customer must
know whether their card was accepted before leaving the page. Everything after
authorization becomes asynchronous.

### Event flow

1. `order-api` validates the cart and calls `payments` synchronously to
   **authorize** (not capture) the charge.
2. In a single database transaction, `order-api` writes the order row with
   status `ACCEPTED` and inserts an `OrderPlaced` row into the `outbox` table.
3. The outbox relay publishes pending outbox rows to `orders.events` and marks
   them sent.
4. `inventory` consumes `OrderPlaced`, reserves stock, and emits either
   `InventoryReserved` or `InventoryReservationFailed`.
5. On `InventoryReserved`, `payments` captures the charge and emits
   `PaymentCaptured`. On `InventoryReservationFailed`, it voids the
   authorization and emits `PaymentVoided`.
6. `fulfillment` consumes `PaymentCaptured`, creates the shipment, and emits
   `ShipmentCreated`.
7. `notifications` consumes the customer-facing events and sends messages.
8. `order-api` consumes all of the above to keep the order's status current
   for the `GET /orders/{id}` endpoint.

### Why an outbox

Writing to the database and publishing to the broker are two separate systems,
so doing both in the request handler can leave them inconsistent (order saved,
event lost, or vice versa). The transactional outbox gives us atomicity on the
write side; the relay delivers **at least once**.

### Event envelope

All events share a common envelope:

```json
{
  "event_id": "01J9ZK3Q8X7M2V4T6R5N0PBCDE",
  "event_type": "OrderPlaced",
  "schema_version": 2,
  "occurred_at": "2026-10-06T14:22:31.481Z",
  "order_id": "ord_7f3a9c21",
  "correlation_id": "chk_b81e44d0",
  "producer": "order-api",
  "payload": { }
}
```

- `event_id` is a ULID and serves as the idempotency key for consumers.
- `order_id` is the partition key, which preserves per-order ordering.
- Schemas live in the `brightcart-events` repo and are checked in CI for
  backward compatibility. Breaking changes require a new `event_type`.

### Consumer requirements

Every consumer must:

- Be **idempotent**, recording processed `event_id`s in its own database within
  the same transaction as its side effects.
- Tolerate out-of-order events *across* orders (ordering is only guaranteed
  per `order_id`).
- Route messages that fail after 5 attempts to a per-consumer dead-letter
  topic, and page the owning team when DLQ depth exceeds a threshold.
- Emit consumer lag as a metric, broken down by partition.

### Broker choice

We propose Kafka, run on our existing managed cluster that already serves the
analytics pipeline. Per-key ordering, replay from offset, and long retention
are all useful here, and the platform team already operates it. See
[Alternatives](#alternatives-considered) for what else we looked at.

### Order status model

| Status        | Set when                                 | Customer-visible as |
|---------------|------------------------------------------|---------------------|
| `ACCEPTED`    | Order written, payment authorized        | "Order received"    |
| `CONFIRMED`   | `PaymentCaptured` received               | "Order confirmed"   |
| `SHIPPED`     | `ShipmentCreated` received               | "Shipped"           |
| `CANCELLED`   | `PaymentVoided` received                 | "Cancelled"         |
| `NEEDS_REVIEW`| Any step dead-lettered                   | "Processing"        |

The `ACCEPTED` → `CANCELLED` path is the main user-facing behavior change;
today an out-of-stock item fails the checkout request itself.

## Alternatives considered

### A. Keep REST, add circuit breakers and bulkheads

Cheapest option. It would contain INC-2207-style cascades, but doesn't remove
fulfillment and notifications from the latency path, and it does nothing about
partial-failure ambiguity. We'd recommend doing this anyway as a stopgap
(already in progress under PLAT-3290).

### B. Orchestrated saga via a workflow engine

A central orchestrator (e.g. Temporal) would drive each step and own
compensation logic. This gives better visibility into a single order's
progress and makes compensation explicit. We rejected it for now because it
reintroduces a central coordinator owned by one team, and we have no
operational experience with a workflow engine. Worth revisiting if
choreography becomes hard to reason about (see Open questions).

### C. Managed queue (SQS/SNS-style) instead of Kafka

Simpler to operate per-queue, but we'd lose replay and would need to build
per-order ordering ourselves. Since we already run Kafka, the operational
argument doesn't favor switching.

### D. Publish directly from the request handler (no outbox)

Rejected due to the dual-write problem described above.

## Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Duplicate side effects (double capture, double email) | Medium | High | Idempotency keys enforced in every consumer; payments additionally dedupes on provider idempotency key |
| Customers see "Cancelled" after a successful checkout | Medium | Medium | Inventory pre-check stays in `order-api` as a best-effort read; track cancellation rate as a launch metric |
| Event flow is harder to debug than a call stack | High | Medium | `correlation_id` propagated into traces; per-order timeline view in the admin tool |
| Consumer lag delays fulfillment | Low | Medium | Lag alerts per consumer group; autoscale on lag |
| Schema drift breaks consumers | Medium | High | Schema registry + CI compatibility checks |
| Outbox relay becomes a bottleneck | Low | High | Relay is horizontally sharded by `order_id` hash; load-tested to 5× peak |

> **Note:** Authorization holds expire. If `InventoryReserved` is delayed long
> enough, capture can fail. Our provider's hold window is far longer than any
> expected lag, but `payments` must handle `AuthorizationExpired` explicitly
> rather than treating it as a generic error.

## Rollout plan

The migration is staged so that at every step we can return to the
synchronous path with a feature flag.

**Phase 0 — Foundations (weeks 1–3)**
- [ ] Create `orders.events` topic and per-consumer DLQs
- [ ] Ship outbox table and relay in `order-api`
- [ ] Publish schemas to `brightcart-events`; wire CI checks
- [ ] Build the per-order timeline view

**Phase 1 — Shadow mode (weeks 4–6)**
- `order-api` publishes events in addition to the existing REST chain.
- Consumers process events in **dry-run** mode: they log the action they
  *would* take and compare against what the REST path actually did.
- Exit criteria: < 0.01% divergence over 7 consecutive days.

**Phase 2 — Notifications and fulfillment (weeks 7–9)**
- Cut over the two non-critical consumers first, behind the
  `orders.async_tail` flag.
- Ramp 1% → 10% → 50% → 100% of traffic, holding each step for at least
  48 hours.

**Phase 3 — Inventory and capture (weeks 10–13)**
- Move inventory reservation and payment capture to events.
- Ramp by the same schedule, excluding the two weeks around the November sale.

**Phase 4 — Cleanup (weeks 14–16)**
- Remove the synchronous chain and the flags.
- Delete the old REST endpoints once traffic has been zero for 30 days.

### Rollback

Up to and including Phase 3, flipping the flag routes new orders back through
the REST chain. Orders already in flight on the event path complete on that
path; consumers keep running until their lag drains to zero.

### Success metrics

- Checkout p99 < 800ms (currently 2.8s)
- Orders lost or stuck in `NEEDS_REVIEW` < 0.005%
- Manual "partial failure" support tickets reduced by 80%
- Zero checkout impact from a simulated `notifications` outage (game day in
  Phase 2)

## Open questions

1. **Inventory pre-check.** Is a best-effort stock read in `order-api` enough,
   or do we need a short-lived soft reservation on the sync path to keep the
   cancellation rate acceptable? Need input from Merchandising.
2. **Choreography vs. orchestration.** At five steps, choreography is
   manageable. If we add returns and split shipments, should we move to an
   orchestrator (Alternative B)?
3. **Retention.** How long should `orders.events` be retained? Seven days
   covers replay for incident recovery; finance has asked about 90 days for
   audit, but that may belong in the warehouse instead.
4. **Ownership of the timeline view.** Commerce Platform or Customer Support
   Tools?
5. **Customer messaging.** What does the customer see when an `ACCEPTED` order
   is later cancelled for stock? Product and Support need to sign off on copy.

## Appendix: Glossary

- **Outbox** — a table written in the same transaction as business data, from
  which events are reliably published.
- **DLQ** — dead-letter queue; where messages go after exhausting retries.
- **Choreography** — services react to each other's events with no central
  coordinator.
