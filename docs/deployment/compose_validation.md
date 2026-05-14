# Docker Compose Validation Note

The deployment risk is not that one developer machine lacks Docker. The real risk is lack of reproducible evidence that the stack can boot in a standard container environment.

This project validates that risk through a GitHub Actions Compose smoke test and can also be verified on any Linux VM with Docker installed.

## Local / VM Command

```bash
cp .env.example .env
docker compose up -d --build
```

## Smoke Checks

```bash
docker compose ps
curl -f http://localhost:8000/healthz
curl -f http://localhost:8000/readyz
curl -f http://localhost:8000/api/v1/health/integrations
curl -f http://localhost:3000
```

## Services

| Service | Purpose | Health |
| --- | --- | --- |
| `postgres` | PostgreSQL + pgvector persistence | `pg_isready` |
| `redis` | cache / ARQ task infra | `redis-cli ping` |
| `redpanda` | Kafka-compatible event bus | process started |
| `mock-integration` | mock ERP/MES/APS server | `/health` |
| `backend` | FastAPI app | `/healthz` |
| `worker` | ARQ background task worker | process started |
| `frontend` | Nginx static frontend | HTTP `/` |

## CI Evidence

The workflow `.github/workflows/ci.yml` includes `compose-smoke`:

```text
docker compose up -d --build
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/readyz
curl -fsS http://localhost:8000/api/v1/health/integrations
curl -fsS http://localhost:3000
docker compose down -v
```

This is the minimum acceptable evidence for MVP standardized deployment. It does not claim Kubernetes readiness, autoscaling, blue/green release, or production-grade observability.

## Manual Evidence To Capture

For demo or customer PoC acceptance, capture:

- `docker compose ps` output.
- `/healthz` and `/readyz` responses.
- `/api/v1/health/integrations` response showing mock/customer adapters.
- Browser screenshot of `http://localhost:3000`.
- Restart test showing PostgreSQL volume persistence.
- `docker compose logs --tail=200` with no fatal startup errors.

补充：如果 local Mac cannot run Docker, use GitHub Actions logs or a temporary Linux VM. The acceptance target is reproducibility, not local-machine purity.
