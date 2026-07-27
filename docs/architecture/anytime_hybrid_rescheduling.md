# Anytime Hybrid Rescheduling

When this portfolio proves infeasibility or cannot return a validated incumbent,
the governed follow-on path is documented in
[feasibility_restoration.md](feasibility_restoration.md). Timeout/`UNKNOWN` is
kept separate from proven infeasibility and does not authorize relaxation.

## Purpose

ReOrch uses a heuristic-first anytime portfolio for anomaly recovery. It does
not run a full-workshop exact model by default and does not treat an unvalidated
heuristic schedule as executable.

## Runtime path

1. DataGate and the scenario readiness manifest fail closed before production
   solving.
2. Constraint-aware SSGS builds the first incumbent within a bounded budget.
3. The incumbent is supplied to OR-Tools CP-SAT as a solution hint.
4. CP-SAT repairs and improves bounded neighborhoods under hard constraints.
5. LNS neighborhoods cover affected operations, downstream precedence,
   contended resources, and affected work orders.
6. Non-dominated candidates are retained in a Pareto archive and the active
   goal mode selects the incumbent.
7. Every candidate returned to the workflow passes the independent operational
   constraint validator.
8. Large snapshots are decomposed into incident-conflict subgraphs, solved in
   parallel, merged, and validated against the full supplied snapshot.

## Hard constraints

The shared validation path covers schedule integrity, precedence, resource
eligibility and capability, frozen operations, calendars, release/deadline
boundaries, changeovers, material/substitute approvals, quality holds, tooling,
labor skills, transport/AMR, buffers, outsourcing, batch genealogy, and QMS
release evidence.

## Time-budget behavior

- SSGS has an independent deadline and cannot consume the entire solve budget.
- CP-SAT receives the remaining initial optimization budget.
- LNS repair uses only the residual budget.
- A validated incumbent can be returned when optimization times out.
- If no candidate passes independent validation, the result is blocked; there
  is no rule-based bypass.

The defaults are configured with `SOLVER_HEURISTIC_BUDGET_RATIO`,
`SOLVER_HEURISTIC_MAX_SECONDS`, `SOLVER_INITIAL_CP_SAT_BUDGET_RATIO`, and
`SOLVER_MAX_ALNS_ITERATIONS`.

## Evidence boundary

`OPTIMAL` proves optimality only for the encoded bounded model. `FEASIBLE`
proves feasibility only for the encoded constraints and supplied state. Digital
twin scale results are engineering evidence, not customer production or ROI
evidence. Customer acceptance still requires historical replay, read-only
shadow operation, planner review, and execution receipts.
