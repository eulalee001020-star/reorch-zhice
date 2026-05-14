# Canonical Data Model

## Purpose

The canonical model is the stable ReOrch-side contract between customer systems and the decision engine. ERP/MES/APS payloads may use customer-specific fields, but adapters must normalize them before data enters incident intake, impact analysis, solving, evaluation, confirmation, or writeback.

Core rule:

```text
Customer payload -> adapter mapping -> canonical model -> ReOrch workflow
```

Solvers and workflow services must not depend on vendor-specific field names.

## Current Implementation Files

| Area | File |
| --- | --- |
| Adapter interface | `app/adapters/base_adapter.py` |
| Canonical adapter models | `app/adapters/mapping_schema.py` |
| Mapping validation | `app/adapters/mapping_validator.py` |
| Internal schedule model | `app/models/schedule.py` |
| Incident model | `app/models/incident.py` |
| Decision model | `app/models/decision.py` |
| Candidate plan model | `app/models/solver.py` |

## WorkOrder

| Field | Type | Required | Meaning | Null handling | Source |
| --- | --- | --- | --- | --- | --- |
| `work_order_id` | string | yes | Stable production order id | reject | ERP/MES |
| `product_id` | string | no | Product/SKU id | keep null | ERP/MES/PLM |
| `product_name` | string | yes | Product display name | fallback to product id if mapped | ERP/MES |
| `quantity` | number | yes | Planned quantity | default 1 only for demo data | ERP/MES |
| `priority` | int | yes | Normalized priority, higher is more urgent | default 0 if unmapped | ERP/MES/APS |
| `due_time` | datetime | yes | Delivery or committed finish time | reject | ERP/APS |
| `status` | enum | yes | `released`, `planned`, `in_progress`, `completed`, `cancelled`, `on_hold` | reject unknown | ERP/MES |

## Operation

| Field | Type | Required | Meaning | Null handling | Source |
| --- | --- | --- | --- | --- | --- |
| `operation_id` | string | yes | Stable operation/routing step id | reject | MES/APS |
| `work_order_id` | string | yes | Parent work order id | reject | MES/APS |
| `sequence` | int | yes | Routing order | default 0 only for unordered demo data | MES/PLM |
| `required_capability` | string | no | Primary machine capability | derive list when present | MES/PLM |
| `required_capabilities` | list[string] | recommended | Eligible capability set | warn if empty | MES/PLM |
| `processing_time_min` | int | yes | Processing duration in minutes | reject non-positive | MES/APS |
| `machine_id` | string | no | Current assigned machine | validate if present | APS/MES |
| `eligible_machine_ids` | list[string] | recommended | Alternative machines | warn or validate references | APS/MES |
| `start_time` | datetime | no | Current scheduled start | validate timezone if present | APS/MES |
| `end_time` | datetime | no | Current scheduled end | validate range if present | APS/MES |
| `predecessors` | list[string] | no | Precedence dependencies | validate references | MES/PLM |
| `successors` | list[string] | no | Downstream dependencies | validate references | MES/PLM |

## Resource / Machine

| Field | Type | Required | Meaning | Null handling | Source |
| --- | --- | --- | --- | --- | --- |
| `machine_id` | string | yes | Stable equipment/resource id | reject | MES/APS/SCADA |
| `name` | string | no | Display name | fallback to id | MES |
| `capabilities` | list[string] | recommended | Process capabilities | warn if empty | MES/PLM |
| `status` | enum | yes | `available`, `busy`, `down`, `maintenance`, `offline`, `unavailable` | reject unknown | MES/SCADA |
| `calendar` | list[object] | no | Shift, downtime, maintenance windows | default empty | MES/APS |
| `is_bottleneck` | bool | no | Bottleneck flag | default false | APS/domain config |
| `has_redundancy` | bool | no | Alternative resource exists | default false | APS/domain config |
| `criticality` | string | no | Business criticality class | default `general` | domain config |

## Incident

| Field | Type | Required | Meaning | Null handling | Source |
| --- | --- | --- | --- | --- | --- |
| `incident_id` | string | yes | External or generated event id | reject | MES/SCADA/manual |
| `incident_type` | enum | yes | `machine_down`, `material_shortage`, `urgent_order_insert`, `capacity_degradation`, `equipment_failure` | reject unknown | MES/manual |
| `machine_id` | string | yes for equipment events | Affected machine/resource | reject when required | MES/SCADA |
| `start_time` | datetime | yes | Event occurrence time | reject | MES/SCADA/manual |
| `severity` | enum | yes | `P1-Critical`, `P2-High`, `P3-Medium`, `P4-Low` | default P3 only for manual draft | MES/manual |
| `description` | string | no | Free-text incident details | keep null | manual/MES |

## ScheduleSnapshot

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `snapshot_id` | UUID | yes | Immutable snapshot identity |
| `captured_at` | datetime | yes | Snapshot capture time |
| `workshop_id` | string | yes | Workshop or line id |
| `source_system` | string | no | Adapter/source label |
| `work_orders` | list[WorkOrder] | yes | Baseline schedule content |
| `raw_data` | object | no | Auditable source payload excerpt |

## DecisionRecord

Decision records capture planner confirmation, override reason, selected plan, solver chain, and module versions. They are the audit anchor for writeback.

Required downstream properties:

- `incident_id`
- `recommended_plan_id`
- `confirmed_plan_id`
- `confirmed_by`
- `confirmed_at`
- `is_override`
- `override_reason` when applicable
- solver and policy module versions

## WritebackCommand

At the adapter boundary this is represented by `RescheduleWritebackPlan`.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `plan_id` | string | yes | Confirmed plan id |
| `decision_record_id` | string | recommended | Audit record id |
| `idempotency_key` | string | yes | Duplicate protection key |
| `instructions` | list[object] | yes | Schedule-change instructions |
| `confirmed_by` | string | recommended | Planner/operator who approved |

Writeback commands must only be produced after human confirmation.

## ExecutionFeedback

Execution feedback is not yet fully canonicalized as a strict Pydantic model. For integration readiness, customer feedback payloads should at minimum include:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `work_order_id` | string | yes | Executed work order |
| `operation_id` | string | recommended | Executed operation |
| `machine_id` | string | recommended | Actual machine/resource |
| `status` | enum | yes | Execution status |
| `actual_start` | datetime | no | Actual start time |
| `actual_end` | datetime | no | Actual finish time |
| `completion_pct` | number | no | Completion ratio |
| `deviation_reason` | string | no | Reason for deviation |

## Validation Rules

The mapping validator checks:

- Required canonical fields.
- Duplicate ids.
- Unknown enum values.
- Datetime timezone and parse failures.
- Operation to work order references.
- Operation predecessor/successor references.
- Operation to machine references.
- Incident to machine references.
- Machine capability mismatch.
- Non-positive quantity or processing time.
- Due time earlier than scheduled operation end.
