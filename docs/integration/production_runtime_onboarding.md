# Production Runtime Onboarding

## 1. Local Rehearsal

```bash
pytest -q
cd frontend && npm run build
cd ..
python tools/run_production_validation.py \
  --scale-repetitions 5 \
  --output output/production_digital_twin_validation.json
```

Required result:

- `all_digital_twin_checks_passed=true`;
- all 9 checks are `pass`;
- `customer_evidence_gate_passed=false` until customer evidence is imported.

## 2. Customer Read-Only Setup

1. Configure PostgreSQL with `RUNTIME_DATABASE_URL`.
2. Configure `AUTH_MODE=oidc`, issuer, audience, JWKS, role claim and tenant claim.
3. Import the canonical master/schedule snapshot and constraint pack.
4. Send ERP/MES/QMS CDC events with monotonic per-partition sequences.
5. Request an as-of snapshot; do not solve while it is blocked.
6. Submit a solve job and run at least two workers against the shared database.
7. Keep shadow runs advisory-only and record planner decisions.
8. Ingest MES terminal receipts until the shadow case is `execution_closed`.
9. Import 10-30 historical/customer shadow cases and validate the evidence ledger.

## 3. Runtime API

| Path | Purpose |
| --- | --- |
| `POST /api/v1/runtime/cdc/events` | Idempotent gap-aware source ingestion |
| `POST /api/v1/runtime/cdc/as-of` | Cross-source consistent state cut |
| `POST /api/v1/runtime/decomposition/execute` | Synchronous bounded-subgraph execution |
| `POST /api/v1/runtime/solve-jobs` | Durable queued execution |
| `POST /api/v1/runtime/solve-workers/{id}/run-once` | Leased worker execution |
| `POST /api/v1/runtime/shadow-runs` | Read-only recommendation |
| `POST /api/v1/runtime/shadow-runs/{id}/planner-decision` | Planner baseline/decision |
| `POST /api/v1/runtime/shadow-runs/{id}/execution-receipts` | MES outcome closure |
| `POST /api/v1/runtime/evidence/customer-ledger` | 10-30 case evidence/ROI gate |
| `POST /api/v1/runtime/validation/digital-twin` | Full technical rehearsal |

## 4. Fail-Closed Conditions

- CDC sequence gap, stale/missing watermark or excessive source skew;
- unknown incident operation id;
- QMS pending/rejected, missing approval, certificate or source reference;
- unavailable primary material without approved available substitute;
- unapproved/expired outsourcing route;
- buffer already over capacity or final global constraint violation;
- tenant mismatch, invalid OIDC signature/audience/issuer or unmapped role;
- expired/mismatched solve lease;
- Rule Candidate without at least three server-executed replay results;
- customer evidence without planner baseline provenance or MES/QMS outcome ids.

## 5. External Acceptance

The runtime backup drill covers ReOrch operational tables. Before a paid pilot,
customer IT must separately run PostgreSQL/PITR, object storage, secrets, node
failover, network isolation and observability drills. Customer operations must
sign the constraint catalog, shadow KPI definition and escalation procedure.
