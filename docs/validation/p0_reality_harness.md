# P0 Reality Harness

## Purpose

The next ReOrch engineering stage is not a broad APS rebuild. It is a
read-only validation harness that proves customer data can be mapped,
checked, reconstructed, and safely routed into historical replay or shadow
mode.

The harness answers five questions before any candidate plan is trusted:

1. Can customer ERP/MES/APS rows become canonical ReOrch objects?
2. Are required fields, timestamps, machine crosswalks, and references valid?
3. Can a `ScheduleSnapshot` be reconstructed from the canonical data?
4. Is the data allowed to enter historical replay or shadow mode?
5. Is production writeback still disabled?

## Implemented Scope

| Item | Implementation |
| --- | --- |
| Canonical schema files | `schemas/canonical/*.schema.json` |
| P0 sample data pack | `datasets/p0_reality_pack/` |
| Harness models | `app/models/reality_harness.py` |
| Harness service | `app/services/reality_harness.py` |
| API endpoints | `POST /api/v1/planning/reality-harness/assess`, `POST /api/v1/planning/reality-harness/sample-pack` |
| Frontend entry | `Data Readiness -> 运行 P0 样例包` |
| Tests | `app/tests/test_reality_harness.py` |

## Permission Levels

| Level | Meaning | Allowed |
| --- | --- | --- |
| `stop` | Blocking mapping or snapshot-readiness errors exist | Data repair only |
| `repair_only` | Readiness below 0.70 | Mapping repair and customer field confirmation |
| `replay_only` | Readiness supports replay, but not shadow mode | Historical replay only |
| `shadow_ready` | Readiness >= 0.85 and no blockers | Historical replay and read-only shadow mode |

`allow_writeback` is always `false` in P0. Writeback requires a separate
sandbox dry-run, human confirmation, idempotency, rollback, and audit scope.

## Validation

Run:

```bash
pytest app/tests/test_reality_harness.py app/tests/test_mapping_validation.py app/tests/test_adapter_contract.py -q
```

Expected P0 sample-pack outcome:

```text
permission.level = shadow_ready
allow_historical_replay = true
allow_shadow_mode = true
allow_writeback = false
```

## Claim Boundary

This harness proves that a customer-like data pack can pass mapping,
reference, and readiness gates. It does not prove production ROI, customer
planner adoption, or safe production writeback. Those require historical
replay, shadow mode, sandbox writeback, and field acceptance.

