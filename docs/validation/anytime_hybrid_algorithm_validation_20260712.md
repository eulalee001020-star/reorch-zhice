# Anytime Hybrid Algorithm Validation - 2026-07-12

## Scope

This run validates the implemented heuristic-first recovery algorithm against
deterministic digital-twin snapshots. It is technical evidence only and does
not establish customer production performance or realized ROI.

## Verified algorithm path

- Constraint-aware SSGS first incumbent with an independent deadline.
- OR-Tools CP-SAT warm start from the SSGS incumbent.
- Bounded LNS/CP-SAT neighborhood repair.
- Pareto non-dominated candidate retention.
- Incident-subgraph decomposition, parallel execution, merge, and full-snapshot
  independent validation.
- Fail-closed behavior when no validated incumbent exists.

## Results

Five repetitions were run for each deterministic scale target.

| Snapshot operations | First feasible P95 | End-to-end P95 | Global violations |
| ---: | ---: | ---: | ---: |
| 1,000 | 0.952 ms | 183.265 ms | 0 |
| 5,000 | 8.117 ms | 749.291 ms | 0 |
| 10,000 | 13.390 ms | 1,581.297 ms | 0 |

All scales verified:

- every returned incumbent passed independent validation;
- CP-SAT solution hints were applied;
- LNS repair attempts executed;
- a non-empty Pareto front was retained;
- joint incidents and parallel subproblem execution were exercised.

The machine-readable artifact is
`output/production_anytime_algorithm_validation_20260712.json`, with fingerprint
`a53e79c280cae93d182e2459d9257936acd64a1aeeacc01072a41ef40c0fc41b`.

## Open production gates

- Real customer historical anomalies and planner baselines are still required.
- MES execution outcomes must be collected in read-only shadow mode.
- Customer constraint completeness and data contracts must pass onsite review.
- Customer infrastructure, HA, SSO, connector, and writeback certification remain
  external acceptance gates.
