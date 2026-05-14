# Read-Only Integration Checklist

## Goal

Validate that ReOrch can reconstruct the customer site's current planning state from customer data without writing anything back.

## Preconditions

- Customer data request list is agreed.
- Field mapping template has an owner for each required field.
- Sandbox API or offline data pack is available.
- No writeback credentials are configured for this phase.

## Checklist

| Step | Check | Pass criteria |
| --- | --- | --- |
| 1 | Connectivity | Sandbox/API or data pack can be accessed from integration environment |
| 2 | Authentication | Read credentials work and are scoped to read-only access |
| 3 | Work orders | Required work orders are ingested and ids are stable |
| 4 | Operations | Operations reference existing work orders |
| 5 | Machines | Machine ids and capabilities are available |
| 6 | Current schedule | Baseline schedule can be reconstructed |
| 7 | Incidents | Incident events can be mapped to canonical incident types |
| 8 | Validation report | Mapping validator reports zero blocking errors |
| 9 | Audit trace | Request timestamp, source system, and payload batch id are recorded |
| 10 | Failure handling | Timeout, 4xx, 5xx, malformed data, and empty payload cases are logged |

## Required Validation Output

```text
total_records
valid_records
invalid_records
missing_required_fields
enum_errors
time_parse_errors
reference_integrity_errors
blocking_errors
warnings
```

## Exit Criteria

Read-only integration is complete when:

- ReOrch can build a `ScheduleSnapshot`.
- The snapshot reflects the customer baseline schedule.
- Mapping validation has no blocking errors.
- No writeback path is invoked.
- Customer stakeholders agree the reconstructed state is materially accurate.

## Stop Conditions

Stop read-only validation and return to mapping if:

- Machine ids differ between MES/APS/SCADA without a crosswalk.
- Operation ids are unstable or regenerated per query.
- Current schedule cannot be tied back to work orders and operations.
- Required timestamps are ambiguous or timezone-free in production data.
