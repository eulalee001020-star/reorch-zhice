# Demo Validation Report

## Dataset

| Item | Count |
| --- | ---: |
| Work orders | 12 |
| Operations | 48 |
| Machines | 8 |
| Incidents | 1 |
| Execution feedback rows | 3 |
| Affected operations in scenario window | 4 |
| Affected work orders in scenario window | 4 |

## Adapter-Level Validation

| Check | Result |
| --- | ---: |
| Total records | 69 |
| Valid records | 69 |
| Invalid records | 0 |
| Missing required fields | 0 |
| Enum errors | 0 |
| Time parse errors | 0 |
| Reference integrity errors | 0 |
| Blocking errors | 0 |
| Warnings | 0 |

## Result

```text
blocking_errors: 0
warnings: 0
status: PASS
```

## Issues

- No validation issues.

## Interpretation

The sandbox dataset is suitable for a representative customer demo when
`blocking_errors` is 0. This proves adapter-level data consistency for the
demo data only. It does not prove real customer ERP/MES/APS integration.
