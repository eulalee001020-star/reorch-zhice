# Deployment Readiness Note

## Current Readiness Level

ReOrch is deployment-ready for internal PoC validation and controlled demo environments.

It is not yet production-ready for unattended customer plant operation. The production boundary depends on customer identity integration, secret management, backup/recovery, real adapter validation, and writeback governance.

## Minimum Demo Deployment Criteria

| Criterion | Current status |
| --- | --- |
| One-command Compose startup | Validated in CI |
| Backend health checks | Validated |
| Frontend serving | Validated |
| PostgreSQL dependency | Configured |
| Redis dependency | Configured |
| Mock integration service | Configured |
| Environment template | Present |
| CI smoke test | Present and passing |

## Customer Pilot Criteria

Before using the system in a customer pilot, complete:

- Customer data request package.
- Field mapping template for customer ERP/MES/APS data.
- Mapping validation report on sample or sandbox data.
- Read-only ingestion check.
- Shadow-mode comparison against planner decisions.
- Human-approved writeback dry run in staging.
- Audit export for incident, plan, decision, writeback, and feedback records.

## Deployment Positioning

Use this wording externally:

```text
The current prototype has completed internal PoC validation, including backend tests, frontend build, and CI-based Compose smoke testing. The next engineering stage is customer integration readiness: canonical data mapping, read-only adapter validation, shadow-mode evaluation, and human-approved writeback.
```
