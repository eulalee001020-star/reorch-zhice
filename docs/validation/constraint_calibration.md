# Constraint Calibration

## Purpose

After the P0 Reality Harness proves that customer data can be mapped and
reconstructed, ReOrch needs a second gate: convert site-specific constraints
into scheduler-ready inputs without letting unverified AI output become active
production logic.

This module compiles only human-approved constraints into:

- `resource_capabilities`
- `resource_calendar`
- `changeover_rules`
- `freeze_windows`
- an optional patched `InitialScheduleRequest`

## Implemented Scope

| Item | Implementation |
| --- | --- |
| Calibration models | `app/models/constraint_calibration.py` |
| Compile service | `app/services/constraint_calibration.py` |
| API endpoint | `POST /api/v1/planning/constraint-calibration/compile` |
| Frontend API/types | `frontend/src/api/planning.ts`, `frontend/src/types/models.ts` |
| Tests | `app/tests/test_constraint_calibration.py` |

## Safety Rules

1. Direct calibration entries are active only when `approval_status=approved`
   and `approved_by` is present.
2. AI or planner-feedback rule candidates are active only when
   `review_status=published_readonly` and `replay_passed=true`.
3. Invalid time windows, unknown resources in a base request, and conflicting
   changeover minutes create blockers.
4. Blocked calibration results do not return a patched `InitialScheduleRequest`.
5. This module does not enable production writeback.

## Validation

Run:

```bash
pytest app/tests/test_constraint_calibration.py -q
python -m ruff check app/models/constraint_calibration.py app/services/constraint_calibration.py app/api/planning.py app/tests/test_constraint_calibration.py
```

Expected outcome:

```text
4 passed
All checks passed
```

## Claim Boundary

Constraint calibration proves that confirmed site rules can be converted into
inputs already understood by the scheduler. It does not prove those rules are
complete enough to replace a customer's APS. Replacement requires broader
coverage: full routing/BOM calendars, capacity models, material constraints,
scenario replay, shadow-mode acceptance, writeback dry runs, and planner
operational sign-off.
