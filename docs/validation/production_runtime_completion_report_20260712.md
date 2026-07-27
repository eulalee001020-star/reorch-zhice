# ReOrch Production Runtime Completion Report

## Overall Decision

| Layer | Status | Decision |
| --- | --- | --- |
| Code path | complete for the eight runtime tracks plus integration governance | APIs, persistence, migration, tests and UI are connected |
| Digital-twin rehearsal | pass | 10/10 integrated gates passed |
| Customer production acceptance | open | no real customer cases, live shadow, customer IdP/HA/DR or realized ROI |

Current objective score:

| Dimension | Score | Basis |
| --- | ---: | --- |
| Market pain | 7.5/10 | unchanged; real workshop loss still required |
| Product positioning | 8.0/10 | exception recovery layer, not APS replacement |
| Engineering MVP | 8.6/10 | production runtime and integration-control paths now have executable gates, migrations and tests |
| Real production usability | 5.8/10 | controlled onboarding-ready, but customer Connector/Shadow/IdP/HA/ROI acceptance remains absent |

## 1. Decomposition And Parallel Solve

- **Technical status:** complete.
- Incident conflict graph groups incidents sharing an operation, work order or resource.
- Bounded subgraphs include predecessor release and successor deadline boundaries.
- Independent groups execute in parallel; shared groups solve jointly.
- Results merge into the full snapshot and pass an independent global constraint gate.
- Merge conflicts trigger deterministic serial repair; failed repair blocks the run.
- Completed subproblems can be reused from checkpoints.
- **Digital-twin result:** pass; observed parallelism 2, global violations 0.
- **External gate:** calibrate subgraph size and worker count on customer hardware/data.

## 2. 1k/5k/10k And Multi-Incident Load

Five repetitions per target:

| Operations | P50 | P95 | Result |
| ---: | ---: | ---: | --- |
| 1,000 | 115.818 ms | 142.198 ms | pass |
| 5,000 | 637.528 ms | 653.035 ms | pass |
| 10,000 | 1,354.780 ms | 1,426.779 ms | pass |

- Each run used five incidents; one shared-work-order pair was solved jointly.
- The result means bounded affected-subgraph solve plus full-snapshot validation.
- It does not mean 10,000 free variables in one globally optimal model.
- **External gate:** rerun with customer operation density, constraints and concurrency.

## 3. Operational Constraints

- **Technical status:** complete for the requested families.
- Transport/AMR: predecessor lag and lane cumulative capacity.
- Buffer: WIP occupancy interval, current WIP and capacity.
- Outsourcing: approval, approver, source reference, validity, lead time and daily capacity.
- Substitute material: shortage recovery only with approved, evidenced and available substitute.
- Batch genealogy: parent and rework precedence plus lot quality-state propagation.
- QMS: release status, required approvals, certificate, source reference and release time.
- An independent validator recomputes all families after schedule merge.
- Pending QMS and over-capacity buffer scenarios fail closed.
- **External gate:** customer process/quality owners sign the constraint catalog.

## 4. CDC And As-Of Consistency

- **Technical status:** complete.
- Event id/checksum idempotency, source sequence uniqueness and gap buffering.
- Contiguous checkpoint advancement and restart resume.
- Per-source watermark and ERP/MES/QMS as-of materialization.
- Missing/stale source, sequence gap or excessive skew blocks solving.
- **Digital-twin result:** sequence 2 buffered; sequence 1 advanced checkpoint to 2; as-of pass.
- **External gate:** validate source clocks, retention, schema evolution and CDC connectors.

## 5. Queue, Quota, HA, SSO And Restore

- **Technical status:** complete for application runtime.
- Relational durable queue supports priority, idempotency and tenant operation/queued/running quotas.
- Worker leases, heartbeats, exclusive claim, expired-lease recovery, cancel and checkpoint resume.
- PostgreSQL is the staging/production backend; SQLite is local-only.
- OIDC verifies signature, algorithm, issuer, audience, expiry, role and tenant claims.
- Runtime backup has SHA-256 manifest, empty-store restore and state hash verification.
- **External gate:** customer JWKS, multi-node PostgreSQL, PITR, object storage and node failover drill.

## 6. Read-Only Shadow And MES Closure

- **Technical status:** complete.
- Shadow solve is advisory-only and has no writeback adapter invocation.
- Planner baseline and accept/adjust/reject decision are stored before execution comparison.
- MES receipts are idempotent and tenant/case scoped.
- A case closes only after all expected operations have terminal receipts.
- Execution metrics include completion, deviation, resource adherence and blocked/rework outcomes.
- **Digital-twin result:** 12 terminal receipts, execution closed, writeback count 0.
- **External gate:** run 2-4 weeks against customer live read-only events.

## 7. Rule Candidate Replay Evidence

- **Technical status:** complete.
- Caller-provided `scenario_count` is deprecated and ignored.
- Backend executes scenario facts, computes observed outcome and emits one SHA-256 result per scenario.
- At least three unique executed results are required; any failed scenario blocks publication.
- Publication remains read-only and does not modify solver/customer configuration.
- **Digital-twin result:** 3/3 pass; a count-only request with 999 reported 0 and failed.
- **External gate:** replace digital-twin scenario refs with customer replay/shadow evidence.

## 8. 10-30 Cases And ROI Ledger

- **Technical status:** complete.
- Thirty deterministic cases cover seven incident types.
- Every case binds incident, planner baseline proxy, system plan, planner decision, execution proxy and cost assumptions.
- Aggregate proxy: baseline loss CNY 8,400; actual loss CNY 7,910; gross benefit CNY 2,948.75.
- The ledger explicitly sets `roi_is_proxy=true` and customer evidence gate false.
- Customer import requires 10-30 cases, confirmed planner baseline provenance, baseline/actual loss and MES/QMS event ids.
- A complete 10-case customer-shaped test pack passes; missing provenance blocks.
- **External gate:** import real cases and reconcile finance/MES figures.

## 9. Enterprise Integration Control Plane

- **Technical status:** complete for the six requested reusable assets.
- Source Authority Matrix and Scenario Data Contract versions are immutable and require named IT_Admin activation.
- Connector SDK conformance executes health, schema, idempotent snapshot, lineage, UTC, cursor resume, source-sequence and capability checks.
- Breaking schema is quarantined before CDC checkpoint mutation; release requires compatibility with the active manifest.
- Hard constraints require compiler, validator and at least three unique executed replay results before activation.
- Decision Readiness is scenario-scoped and checks authority, type, coverage, freshness, deterministic quality rules, Connector version and active constraint evidence.
- Solve submission and Worker execution both re-check the manifest, preventing stale queued work from running.
- Writeback certification executes CAS, duplicate idempotency, transient retry/single apply, receipt, reconciliation and compensation checks.
- Certification remains separate from human second approval and the short-lived signed execution permit.
- Alembic revision `004` owns CDC, runtime and integration-control tables for production upgrades.
- **Digital-twin result:** 8/8 control-plane checks and 15/15 writeback certification checks passed; customer writeback certification remains false.
- **External gate:** customer authority sign-off, real Connector conformance, Sandbox writeback certification and customer security acceptance.

## Verification

- Backend: `846 passed`, one existing FastAPI deprecation warning.
- Frontend: TypeScript and Vite production build passed.
- Static checks: `ruff` and `git diff --check` passed.
- Browser: desktop and 390x844 mobile passed; no global mobile overflow.
- Rule lifecycle: compile -> review -> 3-result replay -> read-only publish passed.
- Runtime page: 10/10, scale, 30-case ledger and audit fingerprint views passed.
- Integration page: six assets, readiness checks, version registry, quarantine and audit views passed.

Evidence artifact:

`output/production_digital_twin_validation_20260712.json`

Content fingerprint:

`0d7d21493a170f95de19b861f9feb5b7561707004fb158c970faf35e97af1362`

JSON file SHA-256:

`9646bda9cb252e3950c4949b8aefdd2adf254dc1b94a0ea8e3a63b402bd73cc0`

Integration-control artifact:

`output/integration_control_validation_20260712.json`

Content fingerprint:

`d2cdac7411264798d97daf477cc6110cdb9ad259b123fa0d7f7a06750ef1499c`

JSON file SHA-256:

`20160ccdbda0cf664c5591034718bb9cbe968ba30ca0ee40ad3005180b858810`

## Next Deployment Gate

The next valid step is not production writeback. It is a real Design Partner
read-only deployment: import 10-30 historical incidents, pass CDC/as-of and
constraint ownership, replay against the planner baseline, then run 2-4 weeks
of live shadow. Only after customer security, HA/DR and realized ROI pass should
the project move to sandbox writeback and a paid controlled pilot.
