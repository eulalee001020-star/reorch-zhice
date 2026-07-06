# Large FJSP Public Pack Run - 2026-07-06

## Input Pack

Path used locally:

`/Users/lishuangjiang/Downloads/reorch_large_fjsp_public_anomaly_pack_v0_1.zip`

Pack contents include:

- `resources_anon.csv`: 60 anonymized resources.
- `work_orders_anon.csv`: 80 anonymized work orders.
- `operations_anon_sample.csv`: 517 operations with flexible eligible machines.
- `current_schedule_snapshot_anon.csv`: 517 baseline schedule rows.
- `historical_anomaly_cases_30.csv`: 30 injected anomaly cases.
- `policy_portfolio_matrix.csv`: policy portfolio reference.
- `data_readiness_report_large_fjsp.csv`: source-side readiness notes.

Important boundary from the pack README: it is a public benchmark-derived,
anonymized dynamic anomaly injection pack. It must not be described as real
enterprise MES/APS traction or ROI evidence unless the customer separately
provides verifiable provenance.

## System Fixes Made Before Rerun

The first raw run exposed integration issues that were valid product gaps:

1. Pipe-delimited alternatives such as `M46|M56|M06` were not parsed as lists.
2. Machine status `degraded` was rejected although it is a normal industrial state.
3. Rebuilt schedule snapshots dropped operation-level eligible resource lists.
4. P0 readiness scoring over-penalized repeated warning codes in large packs.

Fixes:

- `app/adapters/mapping_schema.py` now parses `,`, `|`, and `;` list separators.
- `app/adapters/mapping_validator.py` now accepts `degraded` machine status.
- `build_schedule_snapshot()` now preserves `eligible_resources` under
  `snapshot.raw_data["work_orders"][...]["operations"]`, so the CP-SAT FJSP
  backend can use alternative machines.
- `app/services/reality_harness.py` now deducts warning penalties by unique
  warning code instead of by row count; blockers still hard-stop permission.

## Rerun Results

After normalizing timestamps with timezone and mapping detailed incident labels
to ReOrch incident categories, the pack produced:

| Check | Result |
| --- | --- |
| P0 permission | `shadow_ready` for read-only replay/shadow data gates |
| P0 readiness score | `0.90` |
| Canonical mapping | 687 / 687 records valid |
| Rebuilt snapshot | 80 work orders, 517 operations |
| Alternative resources preserved | yes, first op has `M46, M56, M06, M16, M36` |
| Flexible context | 60 resources, 80 work orders, 517 operations |
| Frozen operations | 119 |
| WIP-like active/released items sampled | 100 |
| Large FJSP constraint compile | `partial`, no blockers |
| Operation modes | 1,836 |
| Decomposition solve route | `feasible_plan_route` |
| Decomposition subproblems | incident neighborhood + bottleneck group + 3 rolling windows |
| Strategy candidates | 139 |
| Counterfactual replay cases | 30 cases, 100 policy results |
| Strategy matrix | 42 cells, all low confidence |
| Synthetic routing/gating P95 proxy | routing 25.81 ms, gate 29.31 ms |
| CP-SAT local repair sample | feasible, `OPTIMAL`, 517-operation snapshot, 0.0238 s wall time |

## Multi-Strategy Rescheduling Rerun

The follow-up run added a reusable large-FJSP replay service and API:

`POST /api/v1/planning/flexible-shop/large-fjsp/replay`

The service accepts the same class of anonymized large-FJSP packs and runs
each incident through multiple solver-backed policies. It uses the P0 Reality
Harness, reconstructed schedule snapshot, preserved eligible resources, frozen
operation gates, and the CP-SAT FJSP backend.

Final rerun on all 30 incidents:

| Metric | Result |
| --- | --- |
| Incidents attempted | 30 |
| Incidents with at least one feasible executable option | 30 |
| Feasible solver-backed options | 71 |
| Infeasible options retained as evidence | 43 |
| Recommended local repair | 11 |
| Recommended controlled frozen-zone release | 11 |
| Recommended controlled global reschedule | 3 |
| Recommended keep-plan warning | 1 |
| Recommended alternative-machine repair | 1 |
| Recommended wait-and-shift | 1 |
| Recommended partial reassignment | 1 |
| Recommended priority swap | 1 |

The first direct run solved 19 / 30 incidents. The remaining 11 failed because
hard frozen operations made downstream precedence infeasible after the affected
operation was delayed. The implementation now adds an explicit
`controlled_frozen_zone_release` policy: it relaxes frozen operations only within
the affected work order and reports frozen changes in the KPI. This is not an
autonomous-writeback path; it is an approval-gated planner option.

## Strategy Trade-Offs

| Strategy | Strength | Weakness / Gate |
| --- | --- | --- |
| `wait_and_shift` | Lowest conceptual change; simple to audit | Often infeasible when downstream frozen operations cannot move |
| `local_repair` | Bounded blast radius; fast enough for review | May miss global optimum or leave wider bottlenecks unresolved |
| `alternative_machine_repair` | Uses flexible-resource redundancy | Requires reliable eligible-machine and setup/transport data |
| `partial_reassignment` | Useful for capacity degradation | Can leave downstream bottleneck or skill constraints unresolved |
| `priority_swap` | Makes rush-order displacement explicit | Requires planner/customer-service approval |
| `controlled_global_reschedule` | Broadest feasible search | High perturbation and many resource switches; stricter review |
| `controlled_frozen_zone_release` | Recovers cases blocked by frozen downstream operations | Requires explicit approval; no autonomous writeback |

## BP Task Judgment

This run supports the BP claim that ReOrch can generate multiple recovery
options for large flexible job-shop anomalies and compare their trade-offs
under hard constraints.

It still does not complete the investment-proof loop by itself. The remaining
evidence needed is:

- Real planner accept / adjust / reject decisions.
- Actual execution outcomes after the selected policy.
- Customer-confirmed due dates, frozen-zone rules, quality holds, material,
  tooling, skill, and outsourcing constraints.
- Sandbox writeback rehearsal with approval, rollback, compensation, permission,
  and audit.

With those fields, the same API can be used for a second similar customer pack:
load rows, run P0 readiness, reconstruct snapshot, solve each incident across
the policy portfolio, and accumulate the strategy-effect matrix.

## Remaining Gaps

The system correctly stays conservative:

- `writeback_safety` remains blocked because sandbox writeback, approval roles,
  rollback, compensation, and audit evidence are not present.
- `Recovery Policy Graph` confidence remains low because the pack does not
  include real planner decisions, overrides, or execution outcomes.
- Constraint compilation is partial because quality-hold / outsourcing /
  customer-specific material, tooling, and skill calibration are still placeholders.
- Some due dates are earlier than scheduled operation completion; this is useful
  as stress-test data but needs customer confirmation before ROI claims.

## Investor/Customer-Safe Claim

Safe wording:

> ReOrch has run a 60-resource, 80-work-order, 517-operation large FJSP
> benchmark-derived anomaly pack through data readiness, snapshot reconstruction,
> flexible-resource constraint compilation, decomposition planning,
> counterfactual replay, and a CP-SAT local repair sample. The run demonstrates
> engineering readiness for read-only replay and shadow preparation, while
> writeback and ROI evidence still require real planner decisions and execution
> outcomes.

Unsafe wording:

- Do not call this customer production deployment.
- Do not claim ROI improvement.
- Do not claim autonomous writeback readiness.
- Do not claim high-confidence Recovery Policy Graph from this pack alone.
