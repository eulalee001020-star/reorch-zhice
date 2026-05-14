# Compose Smoke Evidence

## Purpose

This document records what the Compose smoke test proves and what it does not prove.

## Current Evidence

| Item | Status |
| --- | --- |
| Compose build | Passed in CI |
| Backend health | Passed |
| Backend readiness | Passed |
| Integration health | Passed |
| Frontend availability | Passed |
| Exited service check | Passed |
| Tear down | Passed |

CI evidence:

```text
Run: https://github.com/eulalee001020-star/reorch-zhice/actions/runs/25852548883
Job: compose-smoke
Commit: d58b6c5
Result: success
```

## Interpreted Result

The stack can be built and started in a standard Linux CI environment using `docker compose up -d --build`. Backend, frontend, database, Redis, Redpanda, worker, and mock integration services can start sufficiently for health checks and smoke verification.

## Not Claimed

- This is not a production load test.
- This is not a Kubernetes or Helm validation.
- This is not a real customer adapter validation.
- This is not a local Docker validation on the developer machine.

## Next Evidence To Capture

Before customer demo or pilot deployment, capture:

- `docker compose ps` output after all services are healthy.
- `/healthz`, `/readyz`, and `/api/v1/health/integrations` response bodies.
- A frontend screenshot from the deployed stack.
- One restart test showing database volume persistence.
- A short log excerpt showing no fatal startup errors.
