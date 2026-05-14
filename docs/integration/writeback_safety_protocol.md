# Writeback Safety Protocol

## Principle

Writeback is allowed only after human confirmation. ReOrch must remain a controllable decision assistant, not an autonomous system that changes plant schedules without approval.

```text
Recommendation -> Planner confirmation -> WritebackCommand -> Adapter writeback -> Execution feedback
```

## Preconditions

- Read-only integration has passed.
- Shadow mode has produced representative accepted cases.
- Customer has confirmed the allowed writeback target.
- Staging or sandbox writeback endpoint is available.
- Human confirmation and RBAC are enabled.
- Audit logging is enabled.

## Required Writeback Fields

| Field | Required | Reason |
| --- | --- | --- |
| `plan_id` | yes | Links writeback to confirmed plan |
| `decision_record_id` | yes | Links writeback to human decision |
| `idempotency_key` | yes | Prevents duplicate application |
| `instructions` | yes | Concrete schedule changes |
| `confirmed_by` | yes | Human accountability |
| `confirmed_at` | yes | Audit timestamp |
| `target_system` | yes | MES/APS/ERP target |

## Safety Rules

- No writeback before confirmation.
- No writeback from rejected or infeasible plans.
- Duplicate idempotency keys must not apply changes twice.
- Partial failures must be recorded instruction by instruction.
- Retry must preserve the same idempotency key.
- The system must expose writeback status to the planner.
- Manual intervention is required after repeated failure.

## Status Model

```text
pending
accepted
success
partial_success
failed
duplicate_ignored
manual_review_required
```

## Failure Handling

| Failure | Required handling |
| --- | --- |
| Network timeout | Retry with same idempotency key |
| 4xx validation error | Stop, record customer error payload, require mapping fix |
| 401/403 | Stop, escalate credential/RBAC issue |
| 5xx upstream error | Retry with backoff, then manual review |
| Partial instruction failure | Continue safe instructions, mark partial success, expose failed instructions |
| Duplicate command | Return previous result or `duplicate_ignored` |

## Audit Record

Each writeback attempt must retain:

- Request timestamp.
- Target system.
- Planner identity.
- Decision record id.
- Plan id.
- Idempotency key.
- Request payload or payload hash.
- Response payload or response hash.
- Attempt count.
- Final status.

## Production Boundary

Production writeback should start with a limited scope:

- One line/workshop.
- One incident category.
- One planner group.
- Staging validation already passed.
- Rollback/manual override path documented.
