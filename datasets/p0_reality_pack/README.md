# P0 Reality Harness Sample Pack

This pack is a public-safe customer-data substitute for the next ReOrch stage:

```text
ERP work orders -> MES operations -> APS resources -> MES downtime events
-> canonical mapping -> readiness gate -> replay/shadow permission
```

It is intentionally small. Its purpose is to verify data contracts, reference
integrity, timezone coverage, and machine crosswalk before any customer PoC.

## Files

| File | Meaning |
| --- | --- |
| `erp_work_orders.csv` | Customer order / work-order facts |
| `mes_operations.csv` | Routing operations and baseline time windows |
| `aps_resources.csv` | Machine/resource master data and capabilities |
| `mes_downtime_events.csv` | Historical machine-down events for replay entry |

## Expected Gate

The checked-in pack should pass mapping validation and return
`permission.level = shadow_ready`. Production writeback remains disabled.

