# Production Readiness Gap

## Position

The current system is an internally validated PoC. It has a deployable Compose stack and passing CI, but production use in a customer plant requires additional controls.

## Gap Table

| Category | Current state | Production requirement |
| --- | --- | --- |
| Secret management | `.env.example` and environment variables | Vault, cloud secret manager, or customer-managed secret store |
| Database backup | PostgreSQL volume configured | Scheduled backups, restore drill, retention policy |
| Migration rollback | Alembic migrations present | Versioned rollback plan and pre-deploy backup |
| Identity | Login/API key/RBAC present | Enterprise SSO/OIDC/LDAP integration |
| Audit | Decision/writeback records exist | Exportable audit package for customer IT and QA |
| Rate limit | Basic API rate limiter exists | Customer-specific traffic policy and abuse protection |
| Observability | Health endpoints and logs | Metrics dashboards, alerts, trace correlation |
| Adapter security | Configurable adapters | Per-customer credentials, network allowlist, least privilege |
| Writeback safety | Human confirmation workflow | Staging dry run, idempotency proof, manual recovery process |
| Data retention | Persistent DB | Customer-approved retention and deletion policy |

## Non-Goals For Current Stage

Do not add these until customer pilot requirements justify them:

- Kubernetes.
- Helm charts.
- Multi-region deployment.
- Complex autoscaling.
- Full observability stack.

## Required Before Production Pilot

- Real customer read-only adapter validation.
- Shadow-mode comparison report.
- Staging writeback dry run.
- Backup and restore evidence.
- Customer-approved RBAC mapping.
- Incident and writeback audit export.
- Operational runbook for failed writeback and manual override.
