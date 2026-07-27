# ReOrch Production Runtime Digital-Twin Validation

## Evidence

- Artifact: `output/production_digital_twin_validation_20260712.json`
- Content fingerprint: `0d7d21493a170f95de19b861f9feb5b7561707004fb158c970faf35e97af1362`
- JSON file SHA-256: `9646bda9cb252e3950c4949b8aefdd2adf254dc1b94a0ea8e3a63b402bd73cc0`
- Repetitions per scale target: 5
- Evidence scope: `digital_twin`
- Technical checks: 10/10 pass
- Customer evidence gate: not passed

## Scale Gate

| Snapshot operations | P50 | P95 | Observed parallelism | Global violations |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 115.818 ms | 142.198 ms | 2 | 0 |
| 5,000 | 637.528 ms | 653.035 ms | 2 | 0 |
| 10,000 | 1,354.780 ms | 1,426.779 ms | 2 | 0 |

The execution path builds an incident conflict graph, solves bounded affected
subgraphs, merges results, and validates the complete supplied snapshot. The
10,000-operation result is not a claim that all 10,000 operations were free
decision variables in one globally optimal CP-SAT model.

## Capability Results

| Gate | Result | Evidence |
| --- | --- | --- |
| Decomposition and joint incidents | pass | Shared work-order incidents grouped; independent groups ran in parallel |
| Operational constraints | pass | Transport/AMR, buffer, outsource, substitute, batch/rework and QMS gates; pending QMS failed closed |
| CDC and as-of consistency | pass | Gap buffering, contiguous resume, duplicate handling and ERP/MES/QMS as-of cut |
| Queue, quota and HA lease | pass | Idempotent submit, tenant quotas, exclusive lease, expiry recovery, checkpoint reuse and cancel |
| SSO/RBAC code path | pass | Signed token, issuer/audience, role and tenant mapping; invalid audience rejected |
| Read-only shadow | pass | Planner decision plus MES terminal receipts; writeback invocation count remained zero |
| Rule Candidate replay | pass | Three server-executed results with fingerprints; count-only request rejected |
| Enterprise integration control | pass | Six versioned assets, Connector conformance, deterministic DataGate, breaking-schema quarantine and sandbox writeback certification |
| Evidence and ROI ledger | pass | 30 cases across seven incident types; planner baseline and execution proxy present |
| Runtime backup/restore | pass | Checksummed export, empty-store restore and state hash verification |

## Remaining External Gates

1. Replace digital-twin cases with 10-30 customer cases and confirmed provenance.
2. Confirm the customer Source Authority Matrix and activate one Scenario Data Contract.
3. Run Connector conformance and schema-drift quarantine against the customer Sandbox.
4. Run read-only shadow against customer ERP/MES/QMS CDC events.
5. Validate the customer's OIDC/JWKS, role claims and tenant mapping.
6. Run PostgreSQL, object storage and infrastructure failover/restore onsite.
7. Certify the writeback adapter in Sandbox and rehearse reconciliation/compensation.
8. Measure planner baseline and realized loss from finance/MES records.
9. Complete customer security, retention and operational acceptance.

## Claim Boundary

This artifact supports `digital-twin production-runtime rehearsal passed`. It
does not support `production-ready`, `customer ROI validated`, `customer HA
accepted`, or unattended production dispatch.
