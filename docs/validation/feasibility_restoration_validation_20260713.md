# Feasibility Restoration Validation - 2026-07-13

## Scope

This run validates deterministic backend behavior for infeasibility
classification, conflict refinement, minimum-loss recovery search, approval
gating, large-snapshot decomposition, independent validation, and certificate
issuance. All scenarios use synthetic or deterministic digital-twin data.

## Automated verification

- Full backend suite: `869 passed, 1 warning`.
- Focused restoration suite: `14 passed`.
- Targeted solver/runtime regression: `51 passed` before full-suite execution.
- Ruff on all touched Python files: passed.
- Targeted mypy with skipped external imports: passed.
- `python -m compileall -q app`: passed.
- Runtime OpenAPI contains
  `/api/v1/runtime/feasibility-restoration/evaluate`.

The remaining warning is the existing FastAPI deprecation warning for
`HTTP_422_UNPROCESSABLE_ENTITY`.

## Failure-injection matrix

| Scenario | Expected result | Observed |
|---|---|---|
| CP-SAT `UNKNOWN` / timeout | Preserve baseline; no relaxation search | Passed |
| Proven release-duration-deadline contradiction | Minimum correction pack | Passed |
| Deadline pack without approvals | Preview only; no certificate | Passed |
| Signed multi-role deadline approvals | Re-solve, validate, certificate | Passed |
| Material shortage with pending substitute | Substitute what-if; pending approval | Passed |
| Planned frozen incident operation | Explicit freeze-release approval | Passed |
| Pending QMS gate | Blocked; no relaxation search | Passed |
| Two independent deadline conflicts | Two-action minimum correction set | Passed |
| Missing customer policy in production | HTTP 409 | Passed |
| Unsigned production approvals | No certificate | Passed |
| 25-operation forced decomposition | Global validated schedule | Passed |
| 25-operation material conflict in decomposition | Recovery search entered and found substitute pack | Passed |
| API response contract | Structured gate and writeback false | Passed |
| Constraint registry | QMS direct relaxation forbidden | Passed |

## Integrated production digital-twin run

Artifact:
`output/production_digital_twin_validation_20260713.json`

Artifact fingerprint:
`d617fa20d2a8211ba07803d8765dc7b59760f4986e29f49e5a70083b5d6c6157`

The integrated `feasibility_restoration` check passed with:

- one pending pack exposing no executable schedule;
- approved certificate fingerprint
  `certificate-5b20d1679c9ded6f864cbfad`;
- approved hard-constraint violation count `0`;
- certificate writeback authorization `false`;
- pending QMS status `blocked`;
- QMS relaxation search entered `false`.

## Scale regression

The scale test uses full snapshot sizes with bounded incident subgraphs. It is
not a claim that all 10,000 operations were globally optimized as one CP-SAT
model.

| Snapshot operations | First feasible P95 | End-to-end P95 | Max global violations |
|---:|---:|---:|---:|
| 1,000 | 0.986 ms | 170.368 ms | 0 |
| 5,000 | 7.426 ms | 711.867 ms | 0 |
| 10,000 | 12.997 ms | 1,515.204 ms | 0 |

Warm start, independently validated incumbents, non-empty Pareto archive, and
bounded neighborhood repair checks all passed.

## Acceptance boundary

`all_digital_twin_checks_passed=true`, while
`customer_evidence_gate_passed=false`.

Open customer-evidence blockers remain:

- `real_customer_cases_required`;
- `planner_baseline_and_mes_outcomes_must_come_from_customer_systems`.

This evidence supports a production-runtime engineering claim, not an autonomous
factory deployment claim. Customer-owned recovery policies, signed customer
identities, real source authority, historical exceptions, planner decisions,
MES receipts, and realized cost coefficients still require on-site acceptance.
