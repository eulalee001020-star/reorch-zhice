"""Supply API routes and the CSV loader, exercised on the demo data."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
import pytest_asyncio

from app.main import app
from app.services.supply.csv_loader import load_supply_snapshot
from app.services.validation.local_demo import (
    DEMO_DATA_DIR,
    _seed_schedule,
    _seed_supply,
    reset_in_memory_state,
    seed_material,
)

NOON = datetime.fromisoformat("2026-05-14T12:30:00+08:00")


@pytest.fixture(autouse=True)
def _isolated_state():
    reset_in_memory_state()
    yield
    reset_in_memory_state()


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://supply-test",
        headers={"X-API-Key": "planner-key-001"},
        timeout=120,
    ) as http:
        yield http


def test_loader_reads_every_file_and_attaches_gaps() -> None:
    supply = load_supply_snapshot(
        DEMO_DATA_DIR / "supply",
        captured_at=NOON,
        work_orders_csv=DEMO_DATA_DIR / "work_orders.csv",
    )
    assert len(supply.work_order_demands) == 12
    assert len(supply.bom) == 19
    seal = next(line for line in supply.supply_orders if line.order_id == "PO-7790")
    assert seal.status == "received"
    assert [gap.gap_id for gap in seal.gaps] == ["GAP-01"]
    gasket = next(line for line in supply.supply_orders if line.order_id == "PO-7795")
    assert [gap.is_open for gap in gasket.gaps] == [True, False]
    approved = [rule for rule in supply.substitutes if rule.approved]
    assert [rule.substitute_item_id for rule in approved] == ["BRG-6205-ALT"]


def test_loader_tolerates_a_missing_directory(tmp_path) -> None:
    supply = load_supply_snapshot(tmp_path / "nope", captured_at=NOON)
    assert supply.bom == [] and supply.supply_orders == []


@pytest.mark.asyncio
async def test_supply_routes_need_data_first(client) -> None:
    response = await client.get("/api/v1/supply/suppliers")
    assert response.status_code == 404
    await _seed_supply(client, DEMO_DATA_DIR, NOON)
    response = await client.get("/api/v1/supply/kit-report")
    assert response.status_code == 404  # supply is there, schedule is not


@pytest.mark.asyncio
async def test_kit_report_readiness_suppliers_and_mrp(client) -> None:
    await _seed_schedule(client, DEMO_DATA_DIR, NOON)
    await _seed_supply(client, DEMO_DATA_DIR, NOON)

    kit = (await client.get("/api/v1/supply/kit-report")).json()
    assert kit["kit_rate"] == 1.0
    assert kit["on_time_kit_rate"] == 1.0
    assert len(kit["operations"]) == 7

    # With the bearing supplier's lateness buffer the promise is 10 hours
    # later, which the shaft assembly cannot absorb.
    risky = (await client.get("/api/v1/supply/kit-report?risk_adjusted=true")).json()
    assert risky["late_operation_ids"] == ["OP-DEMO-006-30"]

    readiness = (await client.get("/api/v1/supply/readiness")).json()
    assert readiness["arrived_count"] == 3
    assert readiness["usable_count"] == 1
    assert readiness["arrived_not_usable_count"] == 2
    assert readiness["open_gap_count"] == 2
    assert readiness["unowned_gap_count"] == 1

    suppliers = (await client.get("/api/v1/supply/suppliers")).json()
    tiers = {row["supplier_id"]: row["tier"] for row in suppliers}
    assert tiers == {"S-SEAL": "A", "S-FAST": "B", "S-BRG": "C", "S-STEEL": "unrated"}

    mrp = (await client.get("/api/v1/supply/mrp?bucket_count=3")).json()
    records = {record["item_id"]: record for record in mrp["records"]}
    bearing = records["BRG-6205"]
    assert bearing["buckets"][0]["gross_requirement"] == 260
    assert bearing["buckets"][0]["scheduled_receipt"] == 200
    assert bearing["buckets"][0]["projected_available"] == 120


@pytest.mark.asyncio
async def test_bom_cycle_is_rejected_on_import(client) -> None:
    response = await client.post(
        "/api/v1/supply/snapshots",
        json={
            "captured_at": NOON.isoformat(),
            "bom": [
                {"parent_item_id": "A", "component_item_id": "B", "quantity_per": 1},
                {"parent_item_id": "B", "component_item_id": "A", "quantity_per": 1},
            ],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["message"] == "BOM contains a cycle"


@pytest.mark.asyncio
async def test_material_impact_route(client) -> None:
    incident_id = await seed_material(client)
    impact = (await client.get(f"/api/v1/incidents/{incident_id}/material-impact")).json()
    assert impact["affected_order_keys"] == ["PO-7781/1"]
    assert impact["newly_late_operation_ids"] == ["OP-DEMO-006-30"]
    assert impact["newly_unresolved_operation_ids"] == []
    assert [rule["substitute_item_id"] for rule in impact["approved_substitutes"]] == [
        "BRG-6205-ALT"
    ]


@pytest.mark.asyncio
async def test_unappliable_supply_event_is_reported_as_422(client) -> None:
    await _seed_schedule(client, DEMO_DATA_DIR, NOON)
    await _seed_supply(client, DEMO_DATA_DIR, NOON)
    created = await client.post(
        "/api/v1/incidents",
        json={
            "incident_type": "material_shortage",
            "occurred_at": NOON.isoformat(),
            "resource_id": "NO-SUCH-ITEM",
            "report_source": "manual",
            "raw_payload": {"kind": "eta_slip", "new_promised_at": "2026-05-15T09:00:00+08:00"},
        },
    )
    incident_id = created.json()["incident_id"]
    response = await client.get(f"/api/v1/incidents/{incident_id}/impact-report")
    assert response.status_code == 422
    assert "NO-SUCH-ITEM" in response.json()["detail"]
