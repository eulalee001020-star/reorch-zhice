# Comparative Recovery Experiment - 2026-07-07

## Purpose

This experiment is designed to answer one question:

> Under the same historical factory anomalies, does ReOrch produce faster,
> safer, more explainable, and more reusable recovery decisions than the
> planner's original handling and the customer's existing ERP/MES/APS workflow?

The comparison must not claim that ReOrch is generally better than SAP,
Siemens, DELMIA, Kingdee, Yonyou, or any APS/MOM system. The claim is narrower:
ReOrch should be tested as an anomaly-recovery decision layer on top of the
customer's existing systems.

## Experiment Design

### Unit Of Evaluation

One historical anomaly case from the same plant or workshop.

Each case should include:

- Incident description and timestamp.
- Baseline schedule snapshot before the incident.
- Affected work orders and operations.
- Material availability.
- Quality holds.
- Tooling calendar.
- Labor skill capacity.
- Urgent order constraints.
- Planner's original decision and reason.
- Existing ERP/MES/APS action, if available.
- Execution result and any secondary anomaly.

### Sample Size

Minimum acceptable first-pass sample:

- 10-30 anonymized historical anomalies per customer.

Better validation sample:

- 50+ anomalies across at least 3 anomaly families.

### Comparison Arms

| Arm | Meaning | Evidence Source |
| --- | --- | --- |
| A. Planner original handling | What the planner actually did historically | Planner log, meeting note, schedule version diff, execution feedback |
| B. Existing ERP/MES/APS workflow | What the customer's current system or standard process produced | APS/MES simulation log, Gantt version, what-if export, planner screenshot |
| C. ReOrch replay | ReOrch candidate generation under the same frozen historical state | ReOrch replay output, gate report, Top-N candidates, explanation |

### Protocol

1. Freeze the pre-incident state as `T0`.
2. Normalize all input rows into ReOrch canonical tables.
3. Run data readiness checks and record blockers.
4. Reconstruct the pre-incident schedule snapshot.
5. Replay each incident through all three arms.
6. For ReOrch, generate Top-N recovery options under hard gates.
7. Compare candidates against historical planner choice and execution outcome.
8. Capture planner review: accept, adjust, reject, or reference-only.
9. Record final metrics by incident and by anomaly family.

## Metrics

| Metric | Definition | Winner Direction |
| --- | --- | --- |
| time-to-first-feasible-option | Minutes from incident timestamp to first executable recovery option | Lower is better |
| Top-N coverage rate | Whether ReOrch Top-N contains or dominates the planner's final choice | Higher is better |
| hard-constraint violation rate | Material, quality, tooling, labor, freeze-zone, or routing violations | Lower is better |
| planner adoption / adjustment rate | Planner accepts or edits a ReOrch option instead of rejecting it | Higher is better |
| changed operation count | Number of operations changed by the recovery plan | Lower for same service level |
| execution feedback captured | Whether execution result is attached to the decision record | Higher is better |
| repeat incident improvement | Similar anomaly second-pass decision time / quality improvement | Higher is better |

## Current Rehearsal Result From Existing Project Data

Current available evidence uses the public-source-derived three-industry
synthetic-realistic replay pack. It is a rehearsal result, not customer
production evidence.

| Result Item | Value |
| --- | ---: |
| Total anomaly replay cases | 90 |
| Planner decision rows | 90 |
| Execution feedback rows | 90 |
| Average ReOrch candidate generation time | 6.60 min |
| Average manual baseline decision time | 57.24 min |
| Average decision time saved proxy | 50.64 min |
| Average delay reduction proxy | 106.79 min |
| Average planner trial reduction proxy | 4.06 trials |
| Planner accept-or-tweak proxy | 71.11% |
| Audit complete rate | 100.00% |
| Secondary anomaly proxy | 11.11% |
| Synthetic readiness score | 0.86 |

Large-FJSP public benchmark-derived technical sample:

| Result Item | Value |
| --- | ---: |
| Resources | 60 |
| Work orders | 80 |
| Operations | 517 |
| Historical anomaly cases | 30 |
| Incidents with at least one feasible executable option | 30 / 30 |
| Solver-backed feasible options | 71 |
| Production readiness gate | replay_ready |

## Current Final Judgment

Current result:

> ReOrch has passed a rehearsal-level anomaly recovery comparison against a
> synthetic manual baseline and has solver-backed replay evidence on a
> large-FJSP benchmark-derived pack.

What this supports:

- ReOrch can structure anomaly replay evidence.
- ReOrch can produce fast Top-N recovery candidates in rehearsal data.
- ReOrch can record planner decision and execution-feedback style evidence.
- ReOrch has a concrete metric system for customer-side comparison.

What this does not yet prove:

- It does not prove superiority over a real customer's ERP/MES/APS workflow.
- It does not prove real customer ROI.
- It does not prove production writeback readiness.
- It does not prove high-confidence Recovery Policy Graph learning from real
  planner behavior.

## Customer Experiment Pass Criteria

For a real design-partner experiment, ReOrch should be considered promising
only if all hard gates pass and at least four of the following five outcome
criteria are met:

| Criterion | Minimum Pass Threshold |
| --- | --- |
| Hard-constraint violation rate | 0 critical violations |
| Top-N coverage rate | >= 70% of historical planner choices covered or improved |
| Time-to-first-feasible-option | >= 50% faster than current process |
| Planner accept-or-adjust rate | >= 60% |
| Execution feedback capture | >= 90% of replayed cases |

Stronger customer proof requires:

- Repeat incident improvement visible in the second similar anomaly family.
- Controlled shadow-mode review over 2-4 weeks.
- Sandbox writeback dry run with approval, rollback, idempotency, and audit.

## BP-Safe Wording

Safe:

> ReOrch has designed a comparative recovery experiment that benchmarks
> planner historical handling, the customer's existing ERP/MES/APS workflow,
> and ReOrch replay on the same anonymized anomaly cases. In current
> synthetic-realistic rehearsal data, ReOrch shows strong proxy improvements in
> candidate generation time, decision-time saving, audit completeness, and
> recovery replay coverage. Real superiority claims require design-partner
> historical anomalies and current-system logs.

Unsafe:

- ReOrch has proven it is better than Siemens, DELMIA, SAP, Kingdee, or Yonyou.
- ReOrch has proven real customer ROI.
- ReOrch has completed production writeback validation.
- ReOrch has replaced APS.
