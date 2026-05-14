# Shadow Mode Validation Plan

## Purpose

Shadow mode lets ReOrch generate recommendations without changing customer operations. The goal is to compare system recommendations against planner decisions while carrying no production writeback risk.

## Scope

In scope:

- Read-only data ingestion.
- Incident intake.
- Impact analysis.
- Strategy recommendation.
- Candidate plan generation.
- Evaluation and explanation.
- Planner comparison and feedback capture.

Out of scope:

- Automatic writeback.
- Production schedule mutation.
- Unapproved dispatch changes.

## Evaluation Design

For each incident, capture:

| Dimension | Human baseline | ReOrch shadow output |
| --- | --- | --- |
| Response time | Time from incident to planner decision | Time from incident to candidate plans |
| Feasibility | Whether human plan executed successfully | Constraint validation result |
| Delivery risk | Actual or expected delay | Predicted delay and due-date risk |
| Perturbation | Number of changed operations/orders | Number of changed operations/orders |
| Resource impact | Machines affected by human plan | Machines affected by ReOrch plans |
| Planner acceptance | Accepted/rejected/manual change | Recommendation rank and rationale |

## Metrics

Minimum metrics:

- `time_to_recommendation_seconds`
- `affected_order_count`
- `affected_operation_count`
- `predicted_delay_min`
- `schedule_perturbation`
- `resource_switch_count`
- `constraint_violation_count`
- `planner_acceptance`
- `override_reason`

## Case Capture

Each shadow-mode case should store:

- Incident payload.
- Schedule snapshot id.
- Impact report.
- Strategy selected by rules.
- Candidate plans.
- Evaluation matrix.
- AI explanation text.
- Planner decision or override.
- Execution outcome when available.

## Exit Criteria

Shadow mode is successful when:

- Recommendations are generated for representative incidents.
- Candidate plans are feasible under current modeled constraints.
- Planner can understand why the recommended plan was selected.
- Feedback identifies missing constraints or mapping issues.
- Customer agrees which writeback object can be tested in staging.

## Critical Rule

Shadow-mode recommendations are advisory only. They must not mutate MES, APS, ERP, dispatch boards, or operator assignments.
