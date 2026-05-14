# ERP/MES/APS Adapter Contract

ReOrch adapters follow a contract-first integration model:

```text
Customer ERP/MES/APS payload
    -> field mapping profile
    -> canonical adapter model
    -> ReOrch ScheduleSnapshot / Incident / WritebackInstruction
```

The core rule is strict: external systems may have customer-specific fields, but data entering ReOrch must become canonical objects first. Solvers and decision services must not depend on SAP, Kingdee, Yonyou, MES vendor, or APS vendor field names directly.

## Canonical Objects

### WorkOrder

```json
{
  "work_order_id": "WO-20260514-001",
  "product_id": "P001",
  "product_name": "PCR Kit A",
  "quantity": 100,
  "priority": 3,
  "due_time": "2026-05-15T18:00:00+08:00",
  "status": "released"
}
```

### Operation

```json
{
  "operation_id": "OP-001",
  "work_order_id": "WO-20260514-001",
  "sequence": 10,
  "required_capability": "PCR",
  "required_capabilities": ["PCR"],
  "processing_time_min": 45,
  "machine_id": "M-PCR-01",
  "eligible_machine_ids": ["M-PCR-01", "M-PCR-02"],
  "predecessors": []
}
```

### Machine

```json
{
  "machine_id": "M-PCR-01",
  "name": "PCR Line 01",
  "capabilities": ["PCR"],
  "status": "available",
  "calendar": [],
  "is_bottleneck": true,
  "criticality": "critical"
}
```

### Incident

```json
{
  "incident_id": "INC-20260514-001",
  "incident_type": "machine_down",
  "machine_id": "M-PCR-01",
  "start_time": "2026-05-14T10:30:00+08:00",
  "severity": "P1-Critical"
}
```

## Adapter Interface

Every customer adapter must implement:

```python
fetch_work_orders()
fetch_operations()
fetch_machines()
fetch_current_schedule()
fetch_incidents()
writeback_reschedule_plan(plan)
fetch_execution_feedback()
health_check()
```

Current implementations:

| Adapter | Purpose | Writeback |
| --- | --- | --- |
| `MockAdapter` | Demo, CI, sandbox contract tests | Yes, idempotent |
| `CSVAdapter` | Offline historical/customer static data import | No |
| `RESTAdapter` | Generic customer sandbox/staging API | Yes |
| `MESAdapter` | MES schedule-change instruction writeback | Yes |
| `ERPAdapter` | ERP/APS snapshot and master-data import | Read only |
| `IoTAdapter` | Equipment/event intake | Read only |

## Mock Server

Run a standalone mock ERP/MES/APS server:

```bash
uvicorn app.adapters.mock_server:app --host 0.0.0.0 --port 8010
```

Endpoints:

```text
GET  /health
GET  /api/work-orders
GET  /api/operations
GET  /api/machines
GET  /api/resources
GET  /api/current-schedule
GET  /api/schedule/snapshot
GET  /api/incidents
POST /api/reschedule-plan
POST /api/schedule/writeback
GET  /api/execution-feedback
```

The mock server is intentionally contract-level, not vendor-specific. Its job is to test field completeness, timing, idempotency, writeback result shape, and health reporting before real customer sandbox access exists.

## Writeback Rules

Writeback must follow:

```text
System recommendation -> Human confirmation -> Adapter writeback
```

Required writeback properties:

- Human confirmation is mandatory before writeback.
- Each writeback carries an `idempotency_key`.
- Duplicate idempotency keys must be ignored or returned as duplicates, not applied twice.
- Request and response payloads must be logged or versioned for audit.
- Writeback failure must enter retry/manual handling; the adapter must not silently drop instructions.

## Customer Sandbox Sequence

Use this rollout order:

```text
1. Mock server contract test
2. CSV historical data import
3. REST sandbox read-only integration
4. Shadow-mode recommendation comparison
5. Human-confirmed writeback in staging
6. Limited production writeback
```

补充：生产客户现场不要直接从 mock 切到写回。必须先证明 ReOrch 读到的数据能还原真实现场状态，再进入影子模式，最后才允许人工确认后写回。
