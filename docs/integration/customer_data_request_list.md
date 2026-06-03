# Customer Data Request List

## Purpose

This list defines the minimum data needed to validate ReOrch against a real customer system without requesting full production access.

The request should be scoped as a sample data pack or sandbox API access first. Production writeback is explicitly out of scope until read-only and shadow-mode validation pass.

Data readiness stop rules are defined in [data_readiness_stop_rules.md](data_readiness_stop_rules.md). If the minimum pack has blocking errors, ReOrch only provides a readiness gap report and must not promise replanning, ROI, or planner adoption metrics.

## Minimum Viable Data Pack

| Data object | Source | Required | Use |
| --- | --- | --- | --- |
| WorkOrder | ERP/MES | yes | Production tasks, quantity, due time, priority |
| Operation | MES/APS | yes | Routing steps and processing times |
| Routing / precedence | MES/PLM | yes | Operation order and constraints |
| Machine / Resource | MES/APS | yes | Resource eligibility and status |
| Current Schedule | APS/MES | yes | Baseline schedule reconstruction |
| Incident | MES/SCADA/manual | yes | Re-decision trigger |
| Execution Feedback | MES | yes | Outcome validation after recommendation |

## Second-Phase Data

| Data object | Source | Reason |
| --- | --- | --- |
| Material / Batch | ERP/WMS/MES | Material availability and batch constraints |
| Machine Calendar | MES/APS | Shifts, downtime, maintenance windows |
| Operator skill matrix | MES/HR | Human resource feasibility |
| Tooling / fixture availability | MES/tooling system | Fixture constraints |
| Changeover matrix | MES/process engineering | Setup time realism |
| Quality hold / rework | QMS/MES | Quality-driven replanning |

## Requested Formats

Acceptable first-pass formats:

- CSV files.
- JSON files.
- Excel exports converted to CSV.
- Sandbox REST API.

Required properties:

- All timestamps must be ISO8601 with timezone where possible.
- IDs must be stable across files and API endpoints.
- Sample data should include at least one abnormal event and the affected baseline schedule.
- Data should include enough operations to show precedence and alternative resource selection.

## Minimum File Set

```text
work_orders.csv
operations.csv
machines.csv
current_schedule.json or operations.csv with start/end times
incidents.csv
execution_feedback.csv
```

## Customer Questions

Ask these before integration:

- Which system is authoritative for work orders?
- Which system is authoritative for operation routing?
- Which system is authoritative for the current schedule?
- Are machine ids consistent across MES, APS, and SCADA?
- Which fields are safe to read from sandbox/staging?
- Which writeback object is allowed: schedule plan, dispatch order, operation assignment, or recommendation only?
- Who must approve writeback?
- Can staging writeback be repeated safely with an idempotency key?
- What audit logs must be returned to customer IT or planners?
