"""BOM, MRP netting, kit check, readiness, supplier scoring and shortage events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder
from app.models.supply import (
    BomLine,
    ComponentIssuePoint,
    DeliveryRecord,
    InventoryRecord,
    ItemPlanningParams,
    MaterialShortageEvent,
    OperationRequirement,
    ReadinessGap,
    SubstituteRule,
    Supplier,
    SupplyOrderLine,
    SupplySnapshot,
    WorkOrderDemand,
)
from app.services.supply.bom import BomCycleError, explode, low_level_codes
from app.services.supply.kitting import check_kits, material_availability_rows
from app.services.supply.mrp import lot_size, run_mrp
from app.services.supply.readiness import readiness_report
from app.services.supply.shortage import ShortageEventError, apply_event, assess
from app.services.supply.supplier_scorecard import score_supplier, score_suppliers

T0 = datetime(2026, 5, 14, 8, 0, tzinfo=UTC)


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def _operation(op_id: str, wo_id: str, start: float, hours: float, capability: str) -> Operation:
    return Operation(
        operation_id=op_id,
        work_order_id=wo_id,
        resource_id="M-01",
        required_capabilities=[capability],
        start_time=at(start),
        end_time=at(start + hours),
    )


def _schedule() -> ScheduleSnapshot:
    return ScheduleSnapshot(
        captured_at=T0,
        workshop_id="W1",
        work_orders=[
            WorkOrder(
                work_order_id="WO-1",
                product_name="Pump A",
                due_date=at(10),
                priority=2,
                operations=[
                    _operation("WO-1-10", "WO-1", 1, 1, "CUT"),
                    _operation("WO-1-20", "WO-1", 3, 1, "ASSEMBLY"),
                ],
            ),
            WorkOrder(
                work_order_id="WO-2",
                product_name="Pump A",
                due_date=at(12),
                priority=1,
                operations=[
                    _operation("WO-2-10", "WO-2", 2, 1, "CUT"),
                    _operation("WO-2-20", "WO-2", 5, 1, "ASSEMBLY"),
                ],
            ),
        ],
    )


def _supply(**overrides) -> SupplySnapshot:
    base = {
        "captured_at": T0,
        "bom": [
            BomLine(parent_item_id="PUMP-A", component_item_id="BAR", quantity_per=1),
            BomLine(parent_item_id="PUMP-A", component_item_id="BRG", quantity_per=2),
        ],
        "issue_points": [
            ComponentIssuePoint(
                parent_item_id="PUMP-A", component_item_id="BRG", capability="ASSEMBLY"
            )
        ],
        "inventory": [
            InventoryRecord(item_id="BAR", on_hand=100),
            InventoryRecord(item_id="BRG", on_hand=30, allocated=5, quality_hold=5),
        ],
        "supply_orders": [
            SupplyOrderLine(
                order_id="PO-1", item_id="BRG", supplier_id="S1", quantity=40, promised_at=at(4)
            )
        ],
        "work_order_demands": [
            WorkOrderDemand(work_order_id="WO-1", item_id="PUMP-A", quantity=10),
            WorkOrderDemand(work_order_id="WO-2", item_id="PUMP-A", quantity=20),
        ],
    }
    base.update(overrides)
    return SupplySnapshot(**base)


# ── BOM ─────────────────────────────────────────────────────────────


def test_low_level_code_is_the_deepest_position() -> None:
    bom = [
        BomLine(parent_item_id="A", component_item_id="B", quantity_per=1),
        BomLine(parent_item_id="A", component_item_id="C", quantity_per=1),
        BomLine(parent_item_id="B", component_item_id="C", quantity_per=1),
    ]
    assert low_level_codes(bom) == {"A": 0, "B": 1, "C": 2}


def test_bom_cycle_is_rejected() -> None:
    bom = [
        BomLine(parent_item_id="A", component_item_id="B", quantity_per=1),
        BomLine(parent_item_id="B", component_item_id="A", quantity_per=1),
    ]
    with pytest.raises(BomCycleError):
        low_level_codes(bom)


def test_explode_multiplies_levels_and_inflates_for_scrap() -> None:
    bom = [
        BomLine(parent_item_id="A", component_item_id="B", quantity_per=2),
        BomLine(parent_item_id="B", component_item_id="C", quantity_per=3, scrap_rate=0.25),
    ]
    assert explode(bom, "A", 10) == {"B": 20.0, "C": 80.0}


# ── MRP ─────────────────────────────────────────────────────────────


def test_lot_size_applies_minimum_then_multiple() -> None:
    params = ItemPlanningParams(item_id="X", minimum_order_quantity=30, lot_multiple=25)
    assert lot_size(0, params) == 0
    assert lot_size(10, params) == 50
    assert lot_size(51, params) == 75
    assert lot_size(7, None) == 7


def test_mrp_record_matches_hand_calculation() -> None:
    """Three levels, daily buckets, worked out by hand.

    X: opening 20, lead 1 day, lot-for-lot. Gross 30 on day 1 and 40 on day 3,
       scheduled receipt 5 on day 1.
       day 1: 20 + 5 - 30 = -5  -> receive 5, release day 0
       day 3: 0 - 40           -> receive 40, release day 2
    Y: 2 per X. Opening 50, safety 10, lead 2 days, lots of 25.
       gross = 10 on day 0, 80 on day 2
       day 0: 50 - 10 = 40
       day 2: 40 - 80 = -40    -> net 50, receive 50, release day 0
    Z: 1 per Y with 20 % scrap. No stock, lead 1 day.
       gross day 0 = 50 / 0.8 = 62.5 -> receive 62.5, release is past due
    """
    supply = SupplySnapshot(
        captured_at=T0,
        bom=[
            BomLine(parent_item_id="X", component_item_id="Y", quantity_per=2),
            BomLine(parent_item_id="Y", component_item_id="Z", quantity_per=1, scrap_rate=0.2),
        ],
        inventory=[
            InventoryRecord(item_id="X", on_hand=20),
            InventoryRecord(item_id="Y", on_hand=50, safety_stock=10),
        ],
        supply_orders=[
            SupplyOrderLine(order_id="PO-X", item_id="X", quantity=5, promised_at=at(24 + 2))
        ],
        planning_params=[
            ItemPlanningParams(item_id="X", lead_time_minutes=1440),
            ItemPlanningParams(item_id="Y", lead_time_minutes=2880, lot_multiple=25),
            ItemPlanningParams(item_id="Z", lead_time_minutes=1440),
        ],
    )
    result = run_mrp(
        supply,
        [("X", 30, at(24 + 1)), ("X", 40, at(72 + 1))],
        bucket_minutes=1440,
        bucket_count=6,
    )
    records = {record.item_id: record for record in result.records}

    x = records["X"]
    assert [b.projected_available for b in x.buckets] == [20, 0, 0, 0, 0, 0]
    assert [b.planned_order_receipt for b in x.buckets] == [0, 5, 0, 40, 0, 0]
    assert [b.planned_order_release for b in x.buckets] == [5, 0, 40, 0, 0, 0]

    y = records["Y"]
    assert y.low_level_code == 1
    assert [b.gross_requirement for b in y.buckets] == [10, 0, 80, 0, 0, 0]
    assert [b.projected_available for b in y.buckets] == [40, 40, 10, 10, 10, 10]
    assert [b.planned_order_release for b in y.buckets] == [50, 0, 0, 0, 0, 0]

    z = records["Z"]
    assert z.buckets[0].gross_requirement == 62.5
    assert z.buckets[0].planned_order_receipt == 62.5
    assert z.past_due_release == 62.5


# ── Kit check ───────────────────────────────────────────────────────


def test_kit_pegs_supply_in_need_date_order() -> None:
    report = check_kits(_supply(), _schedule())
    kits = {kit.operation_id: kit for kit in report.operations}

    # Bars are in stock, so both cutting operations are kitted on time.
    assert kits["WO-1-10"].wait_minutes == 0
    assert kits["WO-2-10"].wait_minutes == 0
    # Usable bearings: 30 - 5 - 5 = 20, exactly WO-1's assembly need.
    assert kits["WO-1-20"].requirements[0].sources == ["stock"]
    assert kits["WO-1-20"].wait_minutes == 0
    # WO-2 needs 40 and gets them from PO-1 at hour 4, an hour before it starts.
    assert kits["WO-2-20"].requirements[0].sources == ["PO-1/1"]
    assert kits["WO-2-20"].ready_at == at(4)
    assert report.kit_rate == 1.0
    assert report.on_time_kit_rate == 1.0


def test_late_supply_makes_the_operation_wait() -> None:
    supply = _supply()
    supply.supply_orders[0].promised_at = at(8)
    report = check_kits(supply, _schedule())
    kit = next(k for k in report.operations if k.operation_id == "WO-2-20")
    assert kit.is_complete
    assert kit.wait_minutes == 180
    assert report.late_operation_ids == ["WO-2-20"]
    assert report.on_time_kit_rate == 0.75


def test_missing_supply_is_unresolved_not_late() -> None:
    supply = _supply(supply_orders=[])
    report = check_kits(supply, _schedule())
    kit = next(k for k in report.operations if k.operation_id == "WO-2-20")
    assert not kit.is_complete
    assert kit.ready_at is None
    assert kit.requirements[0].shortage == 40
    assert report.unresolved_operation_ids == ["WO-2-20"]
    assert report.kit_rate == 0.75


def test_arrived_line_with_open_gap_is_not_usable_until_the_gap_closes() -> None:
    supply = _supply()
    line = supply.supply_orders[0]
    line.status = "received"
    line.received_at = at(-2)
    line.gaps = [ReadinessGap(gap_id="G1", description="材质证明未到", owner="采购", due_at=at(7))]
    report = check_kits(supply, _schedule())
    kit = next(k for k in report.operations if k.operation_id == "WO-2-20")
    assert kit.ready_at == at(7)
    assert kit.wait_minutes == 120


def test_gap_without_due_time_leaves_the_kit_unresolved() -> None:
    supply = _supply()
    line = supply.supply_orders[0]
    line.status = "received"
    line.received_at = at(-2)
    line.gaps = [ReadinessGap(gap_id="G1", description="待检")]
    report = check_kits(supply, _schedule())
    kit = next(k for k in report.operations if k.operation_id == "WO-2-20")
    assert not kit.is_complete
    assert "pending:PO-1/1" in kit.requirements[0].sources


def test_overdue_promise_is_not_trusted() -> None:
    supply = _supply()
    supply.supply_orders[0].promised_at = at(-3)
    report = check_kits(supply, _schedule())
    assert "WO-2-20" in report.unresolved_operation_ids


def test_explicit_operation_requirement_is_added() -> None:
    supply = _supply(
        operation_requirements=[
            OperationRequirement(
                work_order_id="WO-1", operation_id="WO-1-10", item_id="COOLANT", quantity=3
            )
        ]
    )
    report = check_kits(supply, _schedule())
    assert "WO-1-10" in report.unresolved_operation_ids


def test_approved_substitute_lifts_a_shortage_only_when_allowed() -> None:
    supply = _supply(
        supply_orders=[],
        inventory=[
            InventoryRecord(item_id="BAR", on_hand=100),
            InventoryRecord(item_id="BRG", on_hand=20),
            InventoryRecord(item_id="BRG-ALT", on_hand=60),
        ],
        substitutes=[
            SubstituteRule(
                primary_item_id="BRG",
                substitute_item_id="BRG-ALT",
                approved=True,
                approved_by="quality",
                source_ref="ECN-17",
            )
        ],
    )
    assert check_kits(supply, _schedule()).unresolved_operation_ids == ["WO-2-20"]
    report = check_kits(supply, _schedule(), allow_substitutes=True)
    kit = next(k for k in report.operations if k.operation_id == "WO-2-20")
    assert kit.is_complete
    assert kit.requirements[0].sources[0] == "substitute:BRG-ALT"


def test_unapproved_substitute_is_ignored() -> None:
    supply = _supply(
        supply_orders=[],
        inventory=[
            InventoryRecord(item_id="BAR", on_hand=100),
            InventoryRecord(item_id="BRG", on_hand=20),
            InventoryRecord(item_id="BRG-ALT", on_hand=60),
        ],
        substitutes=[SubstituteRule(primary_item_id="BRG", substitute_item_id="BRG-ALT")],
    )
    report = check_kits(supply, _schedule(), allow_substitutes=True)
    assert report.unresolved_operation_ids == ["WO-2-20"]


def test_started_operations_are_not_checked() -> None:
    report = check_kits(_supply(), _schedule(), reference_time=at(2.5))
    checked = {kit.operation_id for kit in report.operations}
    assert checked == {"WO-1-20", "WO-2-20"}


def test_material_rows_use_the_scheduler_format() -> None:
    supply = _supply()
    supply.supply_orders[0].promised_at = at(8)
    rows = material_availability_rows(check_kits(supply, _schedule()))
    row = next(r for r in rows if r["operation_ids"] == ["WO-2-20"])
    assert row["material_id"] == "BRG"
    assert row["available_quantity"] == row["required_quantity"] == 40
    assert row["available_at"] == at(8).isoformat()
    assert row["source_ref"].startswith("kit:")


# ── Readiness ───────────────────────────────────────────────────────


def test_readiness_separates_arrived_from_usable() -> None:
    supply = _supply(
        supply_orders=[
            SupplyOrderLine(
                order_id="PO-1",
                item_id="BRG",
                quantity=40,
                promised_at=at(-5),
                status="received",
                received_at=at(-4),
                gaps=[
                    ReadinessGap(
                        gap_id="G1", description="材质证明未到", owner="采购", due_at=at(-1)
                    ),
                    ReadinessGap(gap_id="G2", description="来料检验", due_at=at(3)),
                ],
            ),
            SupplyOrderLine(
                order_id="PO-2",
                item_id="BAR",
                quantity=10,
                promised_at=at(-8),
                status="released",
                received_at=at(-7),
                released_at=at(-6),
            ),
            SupplyOrderLine(order_id="PO-3", item_id="BAR", quantity=10, promised_at=at(20)),
        ]
    )
    report = readiness_report(supply, reference_time=T0)
    assert report.arrived_count == 2
    assert report.usable_count == 1
    assert report.arrived_not_usable_count == 1
    assert report.open_gap_count == 2
    assert report.overdue_gap_count == 1
    assert report.unowned_gap_count == 1
    blocked = next(line for line in report.lines if line.order_key == "PO-1/1")
    assert blocked.arrived and not blocked.usable
    assert blocked.usable_at == at(3)
    assert blocked.overdue_gap_ids == ["G1"]


# ── Supplier scoring ────────────────────────────────────────────────


def _delivery(late_hours: float, rejected: float = 0, response: float | None = 4) -> DeliveryRecord:
    return DeliveryRecord(
        supplier_id="S1",
        item_id="BRG",
        promised_at=T0,
        received_at=T0 + timedelta(hours=late_hours),
        quantity=100,
        rejected_quantity=rejected,
        response_hours=response,
    )


def test_supplier_score_matches_the_documented_formula() -> None:
    records = [_delivery(0), _delivery(0), _delivery(0), _delivery(12), _delivery(36, rejected=10)]
    score = score_supplier("S1", "轴承供应商", records)
    assert score.on_time_rate == 0.6
    assert score.average_late_hours == 24.0
    assert score.reject_rate == 0.02
    assert score.late_p80_minutes == 720
    # 0.40*0.6 + 0.30*(1-0.02/0.05) + 0.20*(1-24/48) + 0.10*(1-4/24) = 0.6033
    assert score.score == 60.3
    assert score.tier == "C"


def test_supplier_with_few_deliveries_is_unrated() -> None:
    score = score_supplier("S1", "新供应商", [_delivery(0), _delivery(0)])
    assert score.tier == "unrated"
    assert score.score == 98.3


def test_score_suppliers_includes_suppliers_without_history() -> None:
    supply = _supply(
        suppliers=[Supplier(supplier_id="S1", name="甲"), Supplier(supplier_id="S2", name="乙")],
        delivery_history=[_delivery(0), _delivery(0), _delivery(0)],
    )
    scores = {item.supplier_id: item for item in score_suppliers(supply)}
    assert scores["S1"].tier == "A"
    assert scores["S2"].tier == "unrated"
    assert scores["S2"].notes == ["no delivery history"]


def test_risk_adjusted_kit_adds_the_supplier_lateness_buffer() -> None:
    supply = _supply(
        suppliers=[Supplier(supplier_id="S1", name="甲")],
        delivery_history=[_delivery(0), _delivery(0), _delivery(2), _delivery(2), _delivery(2)],
    )
    scores = {item.supplier_id: item for item in score_suppliers(supply)}
    assert scores["S1"].late_p80_minutes == 120
    plain = check_kits(supply, _schedule())
    adjusted = check_kits(supply, _schedule(), supplier_scores=scores, risk_adjusted=True)
    assert plain.late_operation_ids == []
    kit = next(k for k in adjusted.operations if k.operation_id == "WO-2-20")
    assert kit.ready_at == at(6)
    assert kit.wait_minutes == 60


# ── Shortage events ─────────────────────────────────────────────────


def test_eta_slip_moves_the_promise_and_is_measured() -> None:
    event = MaterialShortageEvent(item_id="BRG", kind="eta_slip", new_promised_at=at(9))
    impact, updated = assess(_supply(), _schedule(), event)
    assert impact.affected_order_keys == ["PO-1/1"]
    assert impact.before.late_operation_ids == []
    assert impact.newly_late_operation_ids == ["WO-2-20"]
    assert updated.supply_orders[0].promised_at == at(9)


def test_quantity_short_on_a_line_leaves_a_shortage() -> None:
    event = MaterialShortageEvent(item_id="BRG", kind="quantity_short", short_quantity=15)
    impact, updated = assess(_supply(), _schedule(), event)
    assert updated.supply_orders[0].quantity == 25
    assert impact.newly_unresolved_operation_ids == ["WO-2-20"]


def test_quantity_short_without_a_line_reduces_stock() -> None:
    supply = _supply(supply_orders=[])
    event = MaterialShortageEvent(item_id="BAR", kind="quantity_short", short_quantity=85)
    updated, touched = apply_event(supply, event)
    assert touched == ["stock:BAR"]
    assert next(s for s in updated.inventory if s.item_id == "BAR").on_hand == 15


def test_rejected_lot_is_replaced_only_when_a_date_is_given() -> None:
    event = MaterialShortageEvent(item_id="BRG", kind="lot_rejected")
    impact, _ = assess(_supply(), _schedule(), event)
    assert impact.newly_unresolved_operation_ids == ["WO-2-20"]

    replaced = MaterialShortageEvent(item_id="BRG", kind="lot_rejected", new_promised_at=at(30))
    impact, updated = assess(_supply(), _schedule(), replaced)
    assert impact.newly_late_operation_ids == ["WO-2-20"]
    assert [line.key for line in updated.supply_orders if line.status == "open"] == ["PO-1/1-R"]


def test_event_that_cannot_be_applied_is_an_error() -> None:
    with pytest.raises(ShortageEventError):
        apply_event(_supply(), MaterialShortageEvent(item_id="BRG", kind="eta_slip"))
    with pytest.raises(ShortageEventError):
        apply_event(
            _supply(),
            MaterialShortageEvent(item_id="NOPE", kind="eta_slip", new_promised_at=at(9)),
        )


def test_original_snapshot_is_not_mutated() -> None:
    supply = _supply()
    apply_event(
        supply, MaterialShortageEvent(item_id="BRG", kind="eta_slip", new_promised_at=at(9))
    )
    assert supply.supply_orders[0].promised_at == at(4)
