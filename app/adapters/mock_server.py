"""Standalone mock ERP/MES/APS server for adapter contract testing.

Run locally:
    uvicorn app.adapters.mock_server:app --host 0.0.0.0 --port 8010
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Response, status

from app.adapters.mapping_schema import RescheduleWritebackPlan
from app.adapters.mock_adapter import MockAdapter

app = FastAPI(title="ReOrch Mock ERP/MES/APS Server", version="0.1.0")
_adapter = MockAdapter()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "system": "mock_erp_mes_aps"}


@app.get("/api/work-orders")
async def work_orders() -> dict[str, list[dict[str, Any]]]:
    items = await _adapter.fetch_work_orders()
    return {"work_orders": [item.model_dump(mode="json") for item in items]}


@app.get("/api/operations")
async def operations() -> dict[str, list[dict[str, Any]]]:
    items = await _adapter.fetch_operations()
    return {"operations": [item.model_dump(mode="json") for item in items]}


@app.get("/api/machines")
@app.get("/api/resources")
async def machines() -> dict[str, list[dict[str, Any]]]:
    items = await _adapter.fetch_machines()
    payload = [item.model_dump(mode="json") for item in items]
    return {"machines": payload, "resources": payload}


@app.get("/api/incidents")
async def incidents() -> dict[str, list[dict[str, Any]]]:
    items = await _adapter.fetch_incidents()
    return {"incidents": [item.model_dump(mode="json") for item in items]}


@app.get("/api/current-schedule")
@app.get("/api/schedule/snapshot")
async def current_schedule(workshop_id: str = "WS-01") -> dict[str, Any]:
    snapshot = await _adapter.fetch_current_schedule(workshop_id=workshop_id)
    return snapshot.model_dump(mode="json")


@app.post("/api/reschedule-plan")
@app.post("/api/schedule/writeback")
async def writeback(
    payload: dict[str, Any],
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    plan = _coerce_writeback_plan(payload, idempotency_key)
    result = await _adapter.writeback_reschedule_plan(plan)
    if result.status == "duplicate_ignored":
        response.status_code = status.HTTP_200_OK
    return result.model_dump(mode="json")


@app.get("/api/execution-feedback")
async def execution_feedback() -> dict[str, list[dict[str, Any]]]:
    return {"execution_feedback": await _adapter.fetch_execution_feedback()}


def _coerce_writeback_plan(
    payload: dict[str, Any],
    idempotency_key: str | None,
) -> RescheduleWritebackPlan:
    if "plan_id" in payload and "instructions" in payload:
        data = dict(payload)
        data.setdefault("idempotency_key", idempotency_key or payload.get("plan_id", "mock-plan"))
        return RescheduleWritebackPlan.model_validate(data)
    instruction_id = str(payload.get("id") or payload.get("InstructionRef") or payload.get("ref") or "instruction")
    return RescheduleWritebackPlan(
        plan_id=str(payload.get("plan_id") or instruction_id),
        decision_record_id=None,
        idempotency_key=idempotency_key or instruction_id,
        instructions=[payload],
        confirmed_by=str(payload.get("confirmed_by") or "mock"),
    )
