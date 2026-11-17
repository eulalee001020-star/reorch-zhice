"""Kit check: can every operation get all its components by its start time?

The check pegs supply to requirements in need-date order. For each item it
builds the list of lots that are or will become usable, then walks the
requirements from the earliest planned start and consumes lots in the order
they become usable. An operation's kit is ready when its last component is.

The result is turned into ``material_availability`` rows, which the scheduler
already understands as release times for operations.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder
from app.models.supply import (
    ComponentIssuePoint,
    ItemPlanningParams,
    KitReport,
    OperationKit,
    RequirementCoverage,
    SupplierScore,
    SupplyLot,
    SupplyOrderLine,
    SupplySnapshot,
)
from app.services.supply.bom import children_by_parent, gross_quantity

EPSILON = 1e-9
Requirement = tuple[WorkOrder, Operation, str, float]


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------


def _issue_operation(work_order: WorkOrder, point: ComponentIssuePoint | None) -> Operation | None:
    operations = sorted(work_order.operations, key=lambda op: (op.start_time, op.operation_id))
    if not operations:
        return None
    if point is not None and point.capability:
        for operation in operations:
            if point.capability in operation.required_capabilities:
                return operation
    if point is not None and point.position and point.position <= len(operations):
        return operations[point.position - 1]
    return operations[0]


def collect_requirements(supply: SupplySnapshot, schedule: ScheduleSnapshot) -> list[Requirement]:
    """Component requirements of every scheduled operation.

    BOM components of a work order's item are issued at the operation named by
    the issue point, or at the first operation. Explicit operation
    requirements are added on top. Work orders unknown to the schedule are
    ignored: there is nothing to release.
    """
    work_orders = {wo.work_order_id: wo for wo in schedule.work_orders}
    operations = {op.operation_id: (wo, op) for wo in schedule.work_orders for op in wo.operations}
    children = children_by_parent(supply.bom)
    issue_points = {
        (point.parent_item_id, point.component_item_id): point for point in supply.issue_points
    }
    merged: dict[tuple[str, str], float] = defaultdict(float)

    for demand in supply.work_order_demands:
        work_order = work_orders.get(demand.work_order_id)
        if work_order is None:
            continue
        for line in children.get(demand.item_id, []):
            point = issue_points.get((demand.item_id, line.component_item_id))
            operation = _issue_operation(work_order, point)
            if operation is None:
                continue
            merged[(operation.operation_id, line.component_item_id)] += gross_quantity(
                line, demand.quantity
            )
    for requirement in supply.operation_requirements:
        if requirement.operation_id in operations:
            merged[(requirement.operation_id, requirement.item_id)] += requirement.quantity

    result: list[Requirement] = []
    for (operation_id, item_id), quantity in merged.items():
        work_order, operation = operations[operation_id]
        result.append((work_order, operation, item_id, quantity))
    result.sort(key=lambda row: (row[1].start_time, -row[0].priority, row[1].operation_id, row[2]))
    return result


# ---------------------------------------------------------------------------
# Supply lots
# ---------------------------------------------------------------------------


def _line_usable_at(
    line: SupplyOrderLine,
    reference_time: datetime,
    params: ItemPlanningParams | None,
    risk_minutes: int,
) -> datetime | None:
    """When an inbound line becomes usable, or ``None`` when nobody can say."""
    inspection = timedelta(minutes=params.inspection_minutes if params else 0)
    open_gaps = [gap for gap in line.gaps if gap.is_open]
    if any(gap.due_at is None for gap in open_gaps):
        return None
    gap_clear = max((gap.due_at for gap in open_gaps), default=None)

    if line.status == "received":
        arrived = max(line.received_at or reference_time, reference_time)
        base = arrived if open_gaps else arrived + inspection
    else:
        if line.promised_at < reference_time:
            # Overdue with no new promise: the date on file is already wrong.
            return None
        base = line.promised_at + timedelta(minutes=risk_minutes) + inspection
    if gap_clear is not None:
        base = max(base, gap_clear)
    return max(base, reference_time)


def supply_lots(
    supply: SupplySnapshot,
    *,
    reference_time: datetime,
    supplier_scores: dict[str, SupplierScore] | None = None,
    risk_adjusted: bool = False,
    respect_safety_stock: bool = False,
) -> dict[str, list[SupplyLot]]:
    """Usable and incoming quantity per item, earliest first.

    Released lines are assumed to be in stock already and are skipped.
    With ``risk_adjusted`` a promised date is pushed out by the supplier's
    80th-percentile lateness.
    """
    params = {row.item_id: row for row in supply.planning_params}
    lots: dict[str, list[SupplyLot]] = defaultdict(list)
    for stock in supply.inventory:
        quantity = stock.usable - (stock.safety_stock if respect_safety_stock else 0.0)
        if quantity > EPSILON:
            lots[stock.item_id].append(
                SupplyLot(
                    item_id=stock.item_id,
                    quantity=quantity,
                    usable_at=reference_time,
                    source="stock",
                    confidence="on_hand",
                )
            )
    for line in supply.supply_orders:
        if line.status in {"released", "cancelled"}:
            continue
        risk_minutes = 0
        if risk_adjusted and supplier_scores and line.supplier_id in supplier_scores:
            risk_minutes = supplier_scores[line.supplier_id].late_p80_minutes
        usable_at = _line_usable_at(line, reference_time, params.get(line.item_id), risk_minutes)
        lots[line.item_id].append(
            SupplyLot(
                item_id=line.item_id,
                quantity=line.quantity,
                usable_at=usable_at,
                source=line.key,
                confidence="arrived_pending" if line.status == "received" else "promised",
                open_gap_ids=[gap.gap_id for gap in line.gaps if gap.is_open],
            )
        )
    far_future = datetime.max.replace(tzinfo=reference_time.tzinfo)
    for item_lots in lots.values():
        item_lots.sort(key=lambda lot: (lot.usable_at or far_future, lot.source))
    return dict(lots)


# ---------------------------------------------------------------------------
# Pegging
# ---------------------------------------------------------------------------


def _consume(
    pool: list[list], quantity: float
) -> tuple[float, datetime | None, list[str], list[str]]:
    """Take ``quantity`` from ``pool`` in order.

    ``pool`` holds mutable ``[remaining, lot]`` pairs. Returns the covered
    quantity, the time the last needed lot becomes usable, the sources used,
    and the sources that exist but have no known time.
    """
    covered = 0.0
    ready_at: datetime | None = None
    sources: list[str] = []
    pending: list[str] = []
    for entry in pool:
        remaining, lot = entry
        if remaining <= EPSILON:
            continue
        if lot.usable_at is None:
            pending.append(lot.source)
            continue
        if covered >= quantity - EPSILON:
            break
        take = min(remaining, quantity - covered)
        entry[0] = remaining - take
        covered += take
        ready_at = lot.usable_at if ready_at is None else max(ready_at, lot.usable_at)
        sources.append(lot.source)
    return covered, ready_at, sources, pending


def check_kits(
    supply: SupplySnapshot,
    schedule: ScheduleSnapshot,
    *,
    reference_time: datetime | None = None,
    supplier_scores: dict[str, SupplierScore] | None = None,
    risk_adjusted: bool = False,
    respect_safety_stock: bool = False,
    allow_substitutes: bool = False,
) -> KitReport:
    """Peg supply to every operation's requirements and report kit status.

    Only operations that have not started at the reference time are checked.
    When a substitute is used, the primary quantity already pegged to that
    requirement is not handed back to later requirements, which keeps the
    result on the cautious side.
    """
    reference = reference_time or schedule.captured_at
    lots = supply_lots(
        supply,
        reference_time=reference,
        supplier_scores=supplier_scores,
        risk_adjusted=risk_adjusted,
        respect_safety_stock=respect_safety_stock,
    )
    pools: dict[str, list[list]] = {
        item: [[lot.quantity, lot] for lot in item_lots] for item, item_lots in lots.items()
    }
    # Work that started before the reference time has already drawn its
    # material; stock on hand is net of it.
    requirements = [
        row for row in collect_requirements(supply, schedule) if row[1].start_time >= reference
    ]

    coverage: list[tuple[WorkOrder, Operation, RequirementCoverage]] = []
    for work_order, operation, item_id, quantity in requirements:
        covered, ready_at, sources, pending = _consume(pools.get(item_id, []), quantity)
        complete = covered >= quantity - EPSILON
        coverage.append(
            (
                work_order,
                operation,
                RequirementCoverage(
                    work_order_id=work_order.work_order_id,
                    operation_id=operation.operation_id,
                    item_id=item_id,
                    required_quantity=round(quantity, 6),
                    covered_quantity=round(min(covered, quantity), 6),
                    ready_at=ready_at if complete else None,
                    sources=sources + [f"pending:{source}" for source in pending],
                ),
            )
        )

    if allow_substitutes:
        approved: dict[str, list[str]] = defaultdict(list)
        for rule in supply.substitutes:
            if rule.approved and rule.approved_by and rule.source_ref:
                approved[rule.primary_item_id].append(rule.substitute_item_id)
        for _work_order, operation, row in coverage:
            on_time = row.ready_at is not None and row.ready_at <= operation.start_time
            if on_time:
                continue
            best: tuple[datetime, str, list[str]] | None = None
            for substitute in approved.get(row.item_id, []):
                trial = [[entry[0], entry[1]] for entry in pools.get(substitute, [])]
                covered, ready_at, sources, _pending = _consume(trial, row.required_quantity)
                if covered < row.required_quantity - EPSILON or ready_at is None:
                    continue
                if row.ready_at is not None and ready_at >= row.ready_at:
                    continue
                if best is None or ready_at < best[0]:
                    best = (ready_at, substitute, sources)
            if best is None:
                continue
            ready_at, substitute, sources = best
            _consume(pools[substitute], row.required_quantity)
            row.covered_quantity = row.required_quantity
            row.ready_at = ready_at
            row.sources = [f"substitute:{substitute}", *sources]

    by_operation: dict[str, list[RequirementCoverage]] = defaultdict(list)
    operation_index: dict[str, tuple[WorkOrder, Operation]] = {}
    for work_order, operation, row in coverage:
        by_operation[operation.operation_id].append(row)
        operation_index[operation.operation_id] = (work_order, operation)

    kits: list[OperationKit] = []
    for operation_id, rows in by_operation.items():
        work_order, operation = operation_index[operation_id]
        complete = all(row.ready_at is not None for row in rows)
        ready_at = max(row.ready_at for row in rows) if complete else None  # type: ignore[type-var]
        wait = 0.0
        if ready_at is not None and ready_at > operation.start_time:
            wait = (ready_at - operation.start_time).total_seconds() / 60.0
        kits.append(
            OperationKit(
                work_order_id=work_order.work_order_id,
                operation_id=operation_id,
                planned_start=operation.start_time,
                is_complete=complete,
                ready_at=ready_at,
                wait_minutes=round(wait, 2),
                requirements=rows,
            )
        )
    kits.sort(key=lambda kit: (kit.planned_start, kit.operation_id))

    total = len(kits)
    complete_count = sum(1 for kit in kits if kit.is_complete)
    on_time = sum(1 for kit in kits if kit.is_complete and kit.wait_minutes <= EPSILON)
    return KitReport(
        supply_snapshot_id=supply.supply_snapshot_id,
        reference_time=reference,
        operations=kits,
        kit_rate=round(complete_count / total, 4) if total else 1.0,
        on_time_kit_rate=round(on_time / total, 4) if total else 1.0,
        late_operation_ids=[
            kit.operation_id for kit in kits if kit.is_complete and kit.wait_minutes > EPSILON
        ],
        unresolved_operation_ids=[kit.operation_id for kit in kits if not kit.is_complete],
    )


# ---------------------------------------------------------------------------
# Scheduler rows
# ---------------------------------------------------------------------------


def material_availability_rows(report: KitReport) -> list[dict]:
    """Rows in the scheduler's ``material_availability`` format.

    A covered requirement becomes a release time. An uncovered one is written
    with ``available_quantity`` below ``required_quantity``, which the
    scheduler treats as a shortage that only an approved substitute can lift.
    """
    rows: list[dict] = []
    for kit in report.operations:
        for requirement in kit.requirements:
            rows.append(
                {
                    "material_id": requirement.item_id,
                    "operation_ids": [kit.operation_id],
                    "work_order_ids": [kit.work_order_id],
                    "available_quantity": requirement.covered_quantity,
                    "required_quantity": requirement.required_quantity,
                    "available_at": (
                        requirement.ready_at.isoformat() if requirement.ready_at else None
                    ),
                    "source_ref": f"kit:{report.supply_snapshot_id}",
                }
            )
    return rows
