"""Tests for customer adapter contract, mapping, and mock/sandbox adapters."""

from __future__ import annotations

import json

import httpx
import pytest

from app.adapters.csv_adapter import CSVAdapter
from app.adapters.mapping_schema import (
    AdapterMappingProfile,
    FieldMapping,
    RescheduleWritebackPlan,
    map_work_order,
)
from app.adapters.mock_adapter import MockAdapter
from app.adapters.rest_adapter import RESTAdapter


def test_field_mapping_normalizes_customer_work_order_names():
    profile = AdapterMappingProfile(
        source_system="customer_x",
        field_mapping=FieldMapping(
            work_order={
                "work_order_id": "orderNo",
                "product_id": "sku",
                "product_name": "skuName",
                "quantity": "qty",
                "priority": "priorityCode",
                "due_time": "dueAt",
                "status": "state",
            }
        ),
    )

    work_order = map_work_order(
        {
            "orderNo": "WO-001",
            "sku": "P001",
            "skuName": "PCR Kit",
            "qty": "100",
            "priorityCode": "HIGH",
            "dueAt": "2026-05-15T18:00:00+08:00",
            "state": "released",
        },
        profile,
    )

    assert work_order.work_order_id == "WO-001"
    assert work_order.product_id == "P001"
    assert work_order.priority == 3


@pytest.mark.asyncio
async def test_mock_adapter_builds_snapshot_and_enforces_idempotency():
    adapter = MockAdapter()

    snapshot = await adapter.fetch_current_schedule(workshop_id="WS-01")
    assert snapshot.workshop_id == "WS-01"
    assert len(snapshot.work_orders) >= 1
    assert snapshot.work_orders[0].operations[0].resource_id

    plan = RescheduleWritebackPlan(
        plan_id="PLAN-001",
        decision_record_id="DEC-001",
        idempotency_key="PLAN-001:DEC-001",
        instructions=[{"operation_id": "OP-001"}],
        confirmed_by="planner-1",
    )
    first = await adapter.writeback_reschedule_plan(plan)
    second = await adapter.writeback_reschedule_plan(plan)

    assert first.accepted is True
    assert first.status == "accepted"
    assert second.status == "duplicate_ignored"


@pytest.mark.asyncio
async def test_csv_adapter_reads_offline_customer_dataset(tmp_path):
    (tmp_path / "work_orders.csv").write_text(
        "work_order_id,product_name,quantity,priority,due_time,status\n"
        "WO-001,PCR Kit,100,HIGH,2026-05-15T18:00:00+00:00,released\n",
        encoding="utf-8",
    )
    (tmp_path / "operations.csv").write_text(
        "operation_id,work_order_id,sequence,required_capability,processing_time_min,machine_id,start_time,end_time\n"
        "OP-001,WO-001,10,PCR,45,M-PCR-01,2026-05-14T10:00:00+00:00,2026-05-14T10:45:00+00:00\n",
        encoding="utf-8",
    )
    (tmp_path / "machines.csv").write_text(
        "machine_id,name,capabilities,status,is_bottleneck,criticality\n"
        "M-PCR-01,PCR Line 01,PCR,available,true,critical\n",
        encoding="utf-8",
    )

    adapter = CSVAdapter(tmp_path)
    snapshot = await adapter.fetch_current_schedule(workshop_id="WS-CSV")

    assert snapshot.workshop_id == "WS-CSV"
    assert snapshot.work_orders[0].work_order_id == "WO-001"
    assert snapshot.work_orders[0].operations[0].resource_id == "M-PCR-01"
    assert (await adapter.health_check())["available"] is True


@pytest.mark.asyncio
async def test_rest_adapter_maps_sandbox_api_and_writeback():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/work-orders":
            return _json_response(
                {
                    "work_orders": [
                        {
                            "work_order_id": "WO-REST",
                            "product_name": "REST Product",
                            "quantity": 1,
                            "priority": 1,
                            "due_time": "2026-05-16T18:00:00+00:00",
                            "status": "released",
                        }
                    ]
                }
            )
        if path == "/api/operations":
            return _json_response(
                {
                    "operations": [
                        {
                            "operation_id": "OP-REST",
                            "work_order_id": "WO-REST",
                            "processing_time_min": 30,
                            "machine_id": "M-REST",
                            "start_time": "2026-05-14T10:00:00+00:00",
                            "end_time": "2026-05-14T10:30:00+00:00",
                        }
                    ]
                }
            )
        if path == "/api/machines":
            return _json_response({"machines": [{"machine_id": "M-REST", "capabilities": ["PCR"]}]})
        if path == "/api/incidents":
            return _json_response({"incidents": []})
        if path == "/api/reschedule-plan":
            assert request.headers["Idempotency-Key"] == "idem-1"
            return _json_response({"accepted": True, "status": "accepted"})
        if path == "/health":
            return _json_response({"status": "ok"})
        return httpx.Response(404)

    adapter = RESTAdapter(
        "http://sandbox.test",
        transport=httpx.MockTransport(handler),
    )

    snapshot = await adapter.fetch_current_schedule(workshop_id="WS-REST")
    assert snapshot.work_orders[0].work_order_id == "WO-REST"

    result = await adapter.writeback_reschedule_plan(
        RescheduleWritebackPlan(
            plan_id="PLAN-REST",
            idempotency_key="idem-1",
            instructions=[{"operation_id": "OP-REST"}],
        )
    )
    health = await adapter.health_check()

    assert result.accepted is True
    assert result.status == "accepted"
    assert health["available"] is True


def _json_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        content=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
