---
title: Deployment Guide
owner: platform-team
---

# Deployment Guide

This guide explains how to deploy the **Orders** service to the staging
environment. It covers prerequisites, configuration, and rollback.

> [!NOTE]
> You need access to the `staging` cluster before you start.

## Prerequisites

Before you begin, make sure that you have:

- Docker 24.0 or later
- `kubectl` configured for the staging cluster
- Read access to the [config repository](https://example.com/config)
  - Write access is *not* required.

## Configuration

The service reads its settings from `config.yaml`. The table below lists the
most important keys:

| Key | Default | Description |
|---|---|---|
| `port` | `8080` | The port that the server listens on. |
| `timeout` | 30 s | Request timeout, e.g. for slow clients. |
| `log_level` | info | One of `debug`, `info`, or `warn`. |

```yaml
port: 8080
timeout: 30
log_level: info
```

## Deploy the service

1. Build the image:

   ```bash
   docker build -t orders:1.4.2 .
   ```

2. Push the image to the registry.
3. Apply the manifest. The rollout should be complete in about 2 minutes;
   if it isn't, check the pod logs.
4. Verify the deployment:
   - Open the health endpoint.
   - Confirm that the version is `1.4.2`.

> [!WARNING]
> Do not deploy on Friday afternoons.
>
> The on-call engineer will not be available to help.

## Rollback

If something goes wrong, you can roll back with a single command:

    kubectl rollout undo deployment/orders

The previous version is restored automatically. See ![rollback diagram](rollback.png)
for details.

<details>
<summary>Advanced options</summary>

These options are rarely needed.

</details>

## FAQ

**Q: Can I deploy to production with this guide?**\
No. Production deployments are handled by the release team.

---

*Last updated by the platform team.*
