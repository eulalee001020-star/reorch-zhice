"""Opt-in tests against actual isolated Odoo 18, never a recorded transport."""

from __future__ import annotations

import os
from datetime import timedelta
from uuid import uuid4

import pytest

from app.adapters.mapping_schema import RescheduleWritebackPlan
from app.adapters.odoo_adapter import OdooAdapter, OdooClient, format_odoo_datetime

pytestmark = pytest.mark.skipif(
    not os.getenv("ODOO_TEST_URL"), reason="isolated Odoo not configured"
)


def adapter(*, writeback=False):
    assert os.environ["ODOO_TEST_DATABASE"] == "reorch_odoo_test"
    client = OdooClient(
        os.environ["ODOO_TEST_URL"],
        database=os.environ["ODOO_TEST_DATABASE"],
        login=os.environ["ODOO_TEST_LOGIN"],
        api_key=os.environ["ODOO_TEST_PASSWORD"],
        protocol="jsonrpc",
    )
    return OdooAdapter(client, allow_writeback=writeback), client


@pytest.mark.asyncio
async def test_real_odoo_manufacturing_supply_and_writeback():
    source, client = adapter(writeback=True)
    schedule = await source.fetch_current_schedule(workshop_id="odoo-sandbox")
    assert len(schedule.work_orders) == 1
    work_order = schedule.work_orders[0]
    assert (await source.fetch_work_orders())[0].quantity == 5
    assert len(work_order.operations) == 1
    operation = work_order.operations[0]
    assert operation.resource_id == "REORCH-TEST-WC"
    supply = await source.fetch_supply_snapshot(schedule)
    assert len(supply.bom) == 1 and supply.bom[0].quantity_per == 2
    assert sum(record.on_hand for record in supply.inventory) == 100
    assert sum(line.quantity for line in supply.supply_orders) == 20
    assert sum(line.quantity for line in supply.operation_requirements) == 10

    start, finish = operation.start_time, operation.end_time
    plan = RescheduleWritebackPlan(
        plan_id=str(uuid4()),
        idempotency_key="isolated-live-test",
        instructions=[
            {
                "operation_id": operation.operation_id,
                "machine_id": operation.resource_id,
                "start_time": (start + timedelta(minutes=30)).isoformat(),
                "end_time": (finish + timedelta(minutes=30)).isoformat(),
            }
        ],
    )
    try:
        result = await source.writeback_reschedule_plan(plan)
        assert result.accepted, result.message
        rows = await client.search_read("mrp.workorder", [], ["date_start", "date_finished"])
        assert rows[0]["date_start"] == format_odoo_datetime(start + timedelta(minutes=30))
        assert rows[0]["date_finished"] == format_odoo_datetime(finish + timedelta(minutes=30))
    finally:
        plan.instructions[0].update(start_time=start.isoformat(), end_time=finish.isoformat())
        restored = await source.writeback_reschedule_plan(plan)
        assert restored.accepted


@pytest.mark.asyncio
async def test_real_odoo_default_writeback_is_dry_run():
    source, client = adapter()
    operations = await source.fetch_operations()
    await source.fetch_machines()
    before = await client.search_read("mrp.workorder", [], ["date_start", "date_finished"])
    result = await source.writeback_reschedule_plan(
        RescheduleWritebackPlan(
            plan_id=str(uuid4()),
            idempotency_key="isolated-dry-run",
            instructions=[
                {
                    "operation_id": operations[0].operation_id,
                    "start_time": "2026-11-21T10:00:00+00:00",
                    "end_time": "2026-11-21T12:00:00+00:00",
                }
            ],
        )
    )
    assert result.status == "dry_run" and not result.accepted
    assert await client.search_read("mrp.workorder", [], ["date_start", "date_finished"]) == before
