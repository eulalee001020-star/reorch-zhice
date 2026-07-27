# Enterprise Deployment Demo Checklist

## Purpose

This checklist converts deployment boundaries into demonstrable evidence.
It is not a production certificate. It is a review artifact for customer IT,
operations, quality, and production stakeholders.

## Checklist

| Area | Demo evidence | Pass condition | Status |
| --- | --- | --- | --- |
| Permission | RBAC role map for planner, production manager, admin, auditor | High-risk actions require planner + production manager approval | To verify with customer |
| Audit | Exportable incident, candidate, confirmation, override, writeback, module-version logs | Each decision has actor, timestamp, source refs, result | Demo-ready in system boundary |
| Sandbox writeback | Dry-run target, idempotency key, request/response, no production endpoint | Repeated dry-run is idempotent and auditable | Customer sandbox required |
| Logs | Trace id across intake, solver, gate, confirmation, writeback | Failure can be traced to module and input evidence | Demo-ready in system boundary |
| Backup | Backup schedule, restore command, restore evidence | Restore drill meets agreed RPO/RTO | Customer environment required |
| Failure recovery | Solver timeout, adapter failure, partial writeback, rollback, compensation | No silent partial production change | Customer sandbox required |
| Data desensitization | Field inventory, ID mapping, removed sensitive fields, sample pack | No direct PII or confidential customer identifiers in replay pack | Customer approval required |
| Human confirmation | Quality gate + planner confirmation + production manager approval | No unattended production writeback path | Demo-ready in system boundary |
| Security | Secret handling, SSO/RBAC plan, retention/deletion plan | Customer security review has no blockers | Customer review required |
| Performance | 1k/5k/10k operation latency report, concurrent incident test | P95 solver <= 60s or scoped fallback defined; P95 gate <= 1s | Customer-like workload required |

## Machine Gate Mapping

Use:

```text
POST /api/v1/planning/production-readiness/evaluate
```

Expected level by evidence:

| Evidence level | Expected decision |
| --- | --- |
| Public benchmark only | `replay_ready` |
| Customer desensitized data + planner decisions, no writeback | `shadow_ready` |
| Customer sandbox + approval + rollback + audit | `controlled_pilot_ready` |
| Security, backup, performance, execution feedback all passed | `production_ready` |

## Demo Script

1. Show data source and desensitization notes.
2. Run data readiness and snapshot reconstruction.
3. Run replay and show Top-N candidates.
4. Open gate report and explain blockers/warnings.
5. Record planner confirmation or rejection.
6. Show audit export for the decision.
7. Run production readiness gate.
8. Confirm blocked actions are still blocked.

## Stop Rules

- No customer provenance note: do not call it customer evidence.
- No planner decision: do not claim adoption.
- No execution outcome: do not claim ROI or production improvement.
- No sandbox dry-run: do not claim writeback readiness.
- No security/backup review: do not claim production readiness.
