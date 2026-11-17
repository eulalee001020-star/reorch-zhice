"""Odoo adapter against recorded request and response shapes for both protocols."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.adapters.mapping_schema import RescheduleWritebackPlan
from app.adapters.odoo_adapter import (
    OdooAdapter,
    OdooClient,
    OdooConnectionSettings,
    OdooError,
    OdooFieldNames,
    format_odoo_datetime,
    many2one_id,
    parse_odoo_datetime,
)
from app.services.supply.kitting import check_kits

WORKCENTERS = [
    {"id": 1, "name": "Cutting", "code": "CUT", "active": True, "alternative_workcenter_ids": []},
    {
        "id": 2,
        "name": "Assembly 1",
        "code": "ASM1",
        "active": True,
        "alternative_workcenter_ids": [3],
    },
    {
        "id": 3,
        "name": "Assembly 2",
        "code": False,
        "active": True,
        "alternative_workcenter_ids": [2],
    },
]
PRODUCTIONS = [
    {
        "id": 10,
        "name": "WH/MO/00010",
        "product_id": [501, "[PUMP-A] Pump A"],
        "product_qty": 20.0,
        "priority": "1",
        "state": "confirmed",
        "date_start": "2026-05-14 00:00:00",
        "date_deadline": "2026-05-14 12:00:00",
        "date_finished": "2026-05-14 08:00:00",
    },
    {
        "id": 11,
        "name": "WH/MO/00011",
        "product_id": [502, "[PUMP-B] Pump B"],
        "product_qty": 5.0,
        "priority": "0",
        "state": "confirmed",
        "date_start": "2026-05-14 02:00:00",
        "date_deadline": False,
        "date_finished": False,
    },
]
WORKORDERS = [
    {
        "id": 100,
        "name": "Cut",
        "production_id": [10, "WH/MO/00010"],
        "workcenter_id": [1, "Cutting"],
        "duration_expected": 59.5,
        "state": "ready",
        "sequence": 10,
        "date_start": "2026-05-14 01:00:00",
        "date_finished": "2026-05-14 02:00:00",
        "blocked_by_workorder_ids": [],
    },
    {
        "id": 101,
        "name": "Assemble",
        "production_id": [10, "WH/MO/00010"],
        "workcenter_id": [2, "Assembly 1"],
        "duration_expected": 120.0,
        "state": "pending",
        "sequence": 20,
        "date_start": "2026-05-14 04:00:00",
        "date_finished": "2026-05-14 06:00:00",
        "blocked_by_workorder_ids": [100],
    },
]
MOVES = [
    {
        "id": 1,
        "product_id": [601, "Bar"],
        "product_uom_qty": 20.0,
        "raw_material_production_id": [10, "WH/MO/00010"],
        "workorder_id": False,
    },
    {
        "id": 2,
        "product_id": [602, "Bearing"],
        "product_uom_qty": 40.0,
        "raw_material_production_id": [10, "WH/MO/00010"],
        "workorder_id": [101, "Assemble"],
    },
]
QUANTS = [
    {"id": 1, "product_id": [601, "Bar"], "quantity": 100.0, "reserved_quantity": 0.0},
    {"id": 2, "product_id": [602, "Bearing"], "quantity": 10.0, "reserved_quantity": 0.0},
    {"id": 3, "product_id": [602, "Bearing"], "quantity": 5.0, "reserved_quantity": 5.0},
]
PURCHASE_LINES = [
    {
        "id": 900,
        "order_id": [70, "P00070"],
        "product_id": [602, "Bearing"],
        "product_qty": 50.0,
        "qty_received": 10.0,
        "date_planned": "2026-05-14 05:00:00",
        "partner_id": [33, "Bearing Co"],
    }
]
BOMS = [
    {"id": 7, "product_id": [501, "Pump A"], "product_tmpl_id": [401, "Pump A"], "product_qty": 1.0}
]
BOM_LINES = [
    {"id": 71, "bom_id": [7, "Pump A"], "product_id": [602, "Bearing"], "product_qty": 2.0}
]

DATA: dict[str, list[dict[str, Any]]] = {
    "mrp.workcenter": WORKCENTERS,
    "mrp.production": PRODUCTIONS,
    "mrp.workorder": WORKORDERS,
    "stock.move": MOVES,
    "stock.quant": QUANTS,
    "purchase.order.line": PURCHASE_LINES,
    "mrp.bom": BOMS,
    "mrp.bom.line": BOM_LINES,
}


class FakeOdoo:
    """Answers both protocols from the same data and records every call."""

    def __init__(self, *, fail_write_on: int | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.writes: list[tuple[str, list[int], dict[str, Any]]] = []
        self.fail_write_on = fail_write_on

    def _run(self, model: str, method: str, args: dict[str, Any]) -> Any:
        self.calls.append((model, method, args))
        if method == "search_read":
            return [
                {key: row[key] for key in ["id", *args["fields"]] if key in row}
                for row in DATA[model]
            ]
        if method == "write":
            if self.fail_write_on is not None and args["ids"] == [self.fail_write_on]:
                raise PermissionError("You are not allowed to modify work orders")
            self.writes.append((model, args["ids"], args["vals"]))
            return True
        raise AssertionError(f"unexpected method {method}")

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        if request.url.path.startswith("/json/2/"):
            if request.headers.get("authorization") != "bearer key-123":
                return httpx.Response(401, json={"name": "AccessDenied", "message": "bad key"})
            assert request.headers["x-odoo-database"] == "prod"
            _, _, _, model, method = request.url.path.split("/")
            try:
                return httpx.Response(200, json=self._run(model, method, body))
            except PermissionError as exc:
                return httpx.Response(403, json={"name": "AccessError", "message": str(exc)})
        assert request.url.path == "/jsonrpc"
        params = body["params"]
        if params["service"] == "common":
            _db, login, password, _ = params["args"]
            ok = login == "planner" and password == "key-123"
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": body["id"], "result": 7 if ok else False}
            )
        db, uid, password, model, method, args, kwargs = params["args"]
        assert (db, uid, password) == ("prod", 7, "key-123")
        named = (
            {"domain": args[0], **kwargs}
            if method == "search_read"
            else {"ids": args[0], "vals": args[1]}
        )
        try:
            result = self._run(model, method, named)
        except PermissionError as exc:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {"message": "Odoo Server Error", "data": {"message": str(exc)}},
                },
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})


def _adapter(
    fake: FakeOdoo,
    *,
    protocol: str = "json2",
    allow_writeback: bool = False,
    api_key: str = "key-123",
) -> OdooAdapter:
    client = OdooClient(
        "https://erp.example.test/",
        database="prod",
        api_key=api_key,
        login="planner" if protocol == "jsonrpc" else None,
        protocol=protocol,  # type: ignore[arg-type]
        transport=httpx.MockTransport(fake.handler),
    )
    return OdooAdapter(client, allow_writeback=allow_writeback)


# ── value helpers ───────────────────────────────────────────────────


def test_odoo_datetimes_are_naive_utc() -> None:
    moment = parse_odoo_datetime("2026-05-14 05:00:00")
    assert moment == datetime(2026, 5, 14, 5, 0, tzinfo=UTC)
    assert parse_odoo_datetime(False) is None
    assert format_odoo_datetime("2026-05-14T13:00:00+08:00") == "2026-05-14 05:00:00"


def test_many2one_handles_false_and_pairs() -> None:
    assert many2one_id([5, "x"]) == 5
    assert many2one_id(False) is None
    assert many2one_id(9) == 9


def test_client_requires_the_credentials_its_protocol_needs() -> None:
    with pytest.raises(ValueError):
        OdooClient("https://x", database="d", protocol="json2")
    with pytest.raises(ValueError):
        OdooClient("https://x", database="d", api_key="k", protocol="jsonrpc")


# ── reading ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["json2", "jsonrpc"])
async def test_schedule_is_read_the_same_over_both_protocols(protocol: str) -> None:
    adapter = _adapter(FakeOdoo(), protocol=protocol)
    snapshot = await adapter.fetch_current_schedule(workshop_id="PLANT-1")

    # The order with no deadline is left out rather than given an invented date.
    assert [wo.work_order_id for wo in snapshot.work_orders] == ["WH/MO/00010"]
    order = snapshot.work_orders[0]
    assert order.due_date == datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    cut, assemble = sorted(order.operations, key=lambda op: op.start_time)
    assert cut.operation_id == "WH/MO/00010/100"
    assert cut.resource_id == "CUT"
    assert (cut.end_time - cut.start_time).total_seconds() == 3600
    assert assemble.predecessor_ids == ["WH/MO/00010/100"]
    assert assemble.resource_id == "ASM1"


@pytest.mark.asyncio
async def test_workcenter_without_code_and_alternatives() -> None:
    adapter = _adapter(FakeOdoo())
    machines = {machine.machine_id for machine in await adapter.fetch_machines()}
    assert machines == {"CUT", "ASM1", "WC-3"}
    operations = {op.operation_id: op for op in await adapter.fetch_operations()}
    assert operations["WH/MO/00010/101"].eligible_machine_ids == ["ASM1", "WC-3"]


@pytest.mark.asyncio
async def test_older_versions_chain_operations_by_sequence() -> None:
    fake = FakeOdoo()
    client = OdooClient(
        "https://erp.example.test",
        database="prod",
        api_key="key-123",
        transport=httpx.MockTransport(fake.handler),
    )
    adapter = OdooAdapter(
        client, fields=OdooFieldNames(workorder_predecessors=None, workcenter_alternatives=None)
    )
    operations = {op.operation_id: op for op in await adapter.fetch_operations()}
    assert operations["WH/MO/00010/101"].predecessors == ["WH/MO/00010/100"]
    requested = next(args["fields"] for model, _, args in fake.calls if model == "mrp.workorder")
    assert "blocked_by_workorder_ids" not in requested


@pytest.mark.asyncio
async def test_supply_snapshot_feeds_the_kit_check() -> None:
    adapter = _adapter(FakeOdoo())
    schedule = await adapter.fetch_current_schedule()
    supply = await adapter.fetch_supply_snapshot(schedule)

    requirements = {(r.operation_id, r.item_id): r.quantity for r in supply.operation_requirements}
    # The move with no work order is issued at the first operation.
    assert requirements == {("WH/MO/00010/100", "601"): 20.0, ("WH/MO/00010/101", "602"): 40.0}
    bearing = next(row for row in supply.inventory if row.item_id == "602")
    assert (bearing.on_hand, bearing.allocated, bearing.usable) == (15.0, 5.0, 10.0)
    assert supply.supply_orders[0].quantity == 40.0
    assert supply.bom[0].quantity_per == 2.0

    report = check_kits(supply, schedule, reference_time=datetime(2026, 5, 14, 0, 0, tzinfo=UTC))
    assemble = next(kit for kit in report.operations if kit.operation_id == "WH/MO/00010/101")
    # 10 from stock plus 30 of the 40 inbound at 05:00; planned start is 04:00.
    assert assemble.is_complete
    assert assemble.wait_minutes == 60


@pytest.mark.asyncio
async def test_bad_key_is_reported_not_swallowed() -> None:
    adapter = _adapter(FakeOdoo(), api_key="wrong")
    with pytest.raises(OdooError, match="401"):
        await adapter.fetch_work_orders()
    health = await adapter.health_check()
    assert health["available"] is False


@pytest.mark.asyncio
async def test_health_check_reads_a_manufacturing_model() -> None:
    health = await _adapter(FakeOdoo()).health_check()
    assert health["available"] is True
    assert health["mode"] == "json2"
    assert health["writeback_enabled"] is False


# ── writeback ───────────────────────────────────────────────────────


def _plan(*operation_ids: str) -> RescheduleWritebackPlan:
    return RescheduleWritebackPlan(
        plan_id="plan-1",
        idempotency_key="idem-1",
        confirmed_by="planner",
        instructions=[
            {
                "operation_id": operation_id,
                "resource_id": "WC-3",
                "start_time": "2026-05-14T13:00:00+08:00",
                "end_time": "2026-05-14T15:00:00+08:00",
            }
            for operation_id in operation_ids
        ],
    )


@pytest.mark.asyncio
async def test_writeback_is_a_dry_run_unless_enabled() -> None:
    fake = FakeOdoo()
    adapter = _adapter(fake)
    await adapter.fetch_machines()
    await adapter.fetch_operations()
    result = await adapter.writeback_reschedule_plan(_plan("WH/MO/00010/101"))
    assert result.status == "dry_run"
    assert not result.accepted
    assert fake.writes == []
    assert result.raw_response["writes"] == [
        {
            "model": "mrp.workorder",
            "id": 101,
            "values": {
                "date_start": "2026-05-14 05:00:00",
                "date_finished": "2026-05-14 07:00:00",
                "workcenter_id": 3,
            },
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["json2", "jsonrpc"])
async def test_enabled_writeback_sends_dates_and_workcenter(protocol: str) -> None:
    fake = FakeOdoo()
    adapter = _adapter(fake, protocol=protocol, allow_writeback=True)
    await adapter.fetch_machines()
    await adapter.fetch_operations()
    result = await adapter.writeback_reschedule_plan(_plan("WH/MO/00010/101"))
    assert result.accepted
    assert fake.writes == [
        (
            "mrp.workorder",
            [101],
            {
                "date_start": "2026-05-14 05:00:00",
                "date_finished": "2026-05-14 07:00:00",
                "workcenter_id": 3,
            },
        )
    ]


@pytest.mark.asyncio
async def test_unknown_operation_rejects_the_plan_before_any_write() -> None:
    fake = FakeOdoo()
    adapter = _adapter(fake, allow_writeback=True)
    await adapter.fetch_machines()
    await adapter.fetch_operations()
    result = await adapter.writeback_reschedule_plan(_plan("WH/MO/00010/101", "NOPE/1"))
    assert result.status == "rejected"
    assert fake.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["json2", "jsonrpc"])
async def test_failed_write_is_reported_as_partial(protocol: str) -> None:
    fake = FakeOdoo(fail_write_on=101)
    adapter = _adapter(fake, protocol=protocol, allow_writeback=True)
    await adapter.fetch_machines()
    await adapter.fetch_operations()
    result = await adapter.writeback_reschedule_plan(_plan("WH/MO/00010/100", "WH/MO/00010/101"))
    assert result.status == "partial"
    assert not result.accepted
    assert result.raw_response["written_ids"] == [100]
    assert "not allowed" in (result.message or "")


def test_settings_hide_the_key_and_build_an_adapter() -> None:
    settings = OdooConnectionSettings(
        base_url="https://erp.example.test", database="prod", api_key="key-123"
    )
    assert "key-123" not in repr(settings)
    adapter = settings.build_adapter()
    assert adapter.capabilities.can_writeback is False
