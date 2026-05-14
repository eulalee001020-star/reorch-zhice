# Customer Demo Walkthrough

## 1. Demo Objective

Show a complete abnormal-event re-decision workflow using representative
sandbox data:

```text
machine down -> impact analysis -> candidate plans -> recommendation
-> planner confirmation -> controlled writeback -> audit/case deposition
```

The demo is designed for customer pre-sales or early discovery. It does not
claim completed integration with a specific customer's ERP/MES/APS.

## 2. Factory Context

The demo line produces mixed mechanical components with shared CNC capacity.
`M-03` is a critical CNC cell. `M-02` and `M-04` can process the same CNC
operations, but they already carry active work.

Demo data:

| Object | Count |
| --- | ---: |
| Work orders | 12 |
| Operations | 48 |
| Machines | 8 |
| Core incident | 1 |

## 3. Incident Scenario

```text
M-03 unexpectedly goes down at 2026-05-14 13:10 +08:00.
Maintenance estimates four hours of downtime.
Urgent and high-priority orders are at risk.
```

## 4. Data Objects Involved

- Work orders from ERP/MES.
- Operation routing and processing times from MES/APS.
- Machine capability and status from MES/APS.
- Current schedule from APS/MES.
- Incident from MES/SCADA/manual intake.
- Execution feedback from MES.

## 5. End-to-End Flow

1. Login as planner.
2. Open the decision workbench.
3. Use natural-language intake or select the demo incident.
4. Review incident severity and affected machine.
5. Review impact analysis: affected operations, affected orders, delay risk.
6. Review strategy recommendation: wait and repair, local repair, global reschedule.
7. Generate or view Top-3 candidate plans.
8. Compare plans by delivery risk, perturbation, makespan, and feasibility.
9. Review explanation: why the recommended plan balances urgency and execution risk.
10. Planner confirms the recommended plan.
11. System performs controlled mock MES/APS writeback.
12. Review decision record, writeback status, and case library entry.

## 6. Decision Metrics

Use business language in the recording:

| Metric | Customer-facing meaning |
| --- | --- |
| Delay risk | Which orders may miss delivery |
| Perturbation | How much of the plan changes |
| Resource switch count | How many operations move to other machines |
| Feasibility | Whether constraints still hold |
| Confidence | How strongly the system recommends the plan |

Avoid presenting the demo as an optimizer benchmark. The customer story is
controlled decision speed, schedule stability, and auditability.

## 7. Writeback Safety

Say this explicitly:

```text
The system does not write back automatically. It recommends a plan, the planner
confirms it, and only then a controlled writeback command is issued.
```

Demo writeback uses mock/sandbox integration. Real customer rollout starts with
read-only integration and shadow mode.

## 8. Audit Trail

Show:

- Selected incident.
- Impact summary.
- Candidate plans.
- Recommended plan id.
- Planner confirmation.
- Writeback status.
- Decision record.
- Case library entry or case deposition explanation.

## 9. Extension To Real ERP/MES/APS

Use this transition:

```text
Different customers have different ERP/MES/APS fields. ReOrch does not ask the
customer to change their systems. We map customer fields into a canonical data
model, validate the mapping, run read-only integration first, compare decisions
in shadow mode, and only then enable human-approved writeback.
```

## 10. Demo Close

Close with:

```text
This sandbox demo proves the end-to-end decision loop and integration contract.
The next step with a real customer is not rebuilding the product; it is mapping
their data, validating read-only ingestion, and running shadow-mode comparison.
```
