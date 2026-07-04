# Replay and Shadow Validation

## Purpose

Replacing or sitting above an enterprise scheduling system requires evidence
that ReOrch recommendations are comparable with real planner decisions. This
module evaluates generated candidate plans against a historical
planner-accepted schedule before shadow mode.

It answers:

1. Did any Top-N candidate pass the operational quality gate?
2. Did the candidate cover the same operations as the accepted schedule?
3. Did it keep the same resource assignments within tolerance?
4. Did start/end times stay inside the configured deviation envelope?
5. Is the result strong enough for read-only shadow comparison?

## Implemented Scope

| Item | Implementation |
| --- | --- |
| Replay models | `app/models/replay_validation.py` |
| Replay service | `app/services/replay_validation.py` |
| API endpoint | `POST /api/v1/planning/replay-validation/evaluate` |
| Frontend API/types | `frontend/src/api/planning.ts`, `frontend/src/types/models.ts` |
| Tests | `app/tests/test_replay_validation.py` |

## Metrics

| Metric | Meaning |
| --- | --- |
| `top_n_hit` | A Top-N candidate passed quality gate and met the acceptance threshold |
| `resource_match_rate` | Share of historical operations assigned to the same resource |
| `within_time_tolerance_rate` | Share of operations whose start/end deviations are within tolerance |
| `schedule_similarity_score` | Weighted score: resource 40%, time 40%, operation coverage 20% |
| `shadow_readiness_level` | `blocked`, `watch_only`, `candidate_shadow`, or `shadow_comparable` |

## Safety Rules

- A candidate with perfect similarity is still rejected if the quality gate
  fails.
- No candidate plan means `do_not_enter_shadow_mode`.
- A replay hit only allows read-only shadow comparison. It does not allow
  production writeback.

## Validation

Run:

```bash
pytest app/tests/test_replay_validation.py -q
python -m ruff check app/models/replay_validation.py app/services/replay_validation.py app/tests/test_replay_validation.py app/api/planning.py
```

Expected outcome:

```text
3 passed
All checks passed
```

## Claim Boundary

This module creates measurable evidence for historical replay and shadow-mode
screening. It does not prove full customer rollout readiness by itself. A
production pilot still requires a larger historical sample, calibrated
constraints, planner override analysis, sandbox writeback rehearsal, audit
export, and operational sign-off.
