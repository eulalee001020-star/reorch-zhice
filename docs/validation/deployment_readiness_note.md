# Deployment Readiness Note

## Current Readiness Level

ReOrch has completed MVP development and is ready for controlled lab-trial validation and demo environments.

It is not yet production-ready for unattended customer plant operation. The production boundary depends on customer identity integration, secret management, backup/recovery, real adapter validation, writeback governance, and field acceptance.

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
- Digital-twin replay/shadow proxy report, followed by shadow-mode comparison against planner decisions.
- Human-approved writeback dry run in staging.
- Audit export for incident, plan, decision, writeback, and feedback records.

## Deployment Positioning

Use this wording externally:

```text
The current MVP is in controlled lab-trial validation. Backend tests, frontend build, CI-based Compose smoke checks, and digital-twin validation evidence are available. The next engineering stage is customer integration readiness: canonical data mapping, read-only adapter validation, planner shadow-mode evaluation, and human-approved writeback.
```
