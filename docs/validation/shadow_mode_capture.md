# Shadow Mode Capture

## Purpose

Shadow mode is read-only comparison against planner decisions. It must record
what the system recommended, what the planner did, and why, without creating
writeback commands or changing production schedules.

## Implemented Scope

| Item | Implementation |
| --- | --- |
| Shadow models | `app/models/shadow_mode.py` |
| Shadow service | `app/services/shadow_mode.py` |
| API endpoint | `POST /api/v1/planning/shadow-mode/capture` |
| Frontend API/types | `frontend/src/api/planning.ts`, `frontend/src/types/models.ts` |
| Tests | `app/tests/test_shadow_observability.py` |

## Safety Rules

1. Every captured case is `advisory_only=true`.
2. `writeback_blocked=true` is always returned.
3. The audit bundle records `writeback_command_created=false`.
4. Planner rejection or tweak with a reason can recommend a pending rule
   candidate, but does not publish a hard constraint.
5. Missing incident, snapshot, candidate, source refs, or override reason
   prevents the case from being marked feedback-complete.

## Validation

Run:

```bash
pytest app/tests/test_shadow_observability.py -q
```

Expected outcome:

```text
3 passed
```

## Claim Boundary

This module proves that shadow feedback can be captured safely and audited. It
does not prove production ROI, planner adoption, or writeback readiness. Those
require enough representative shadow cases, execution outcomes, and sandbox
writeback rehearsal.
