"""Apply a supply disruption to a supply snapshot and measure what it breaks.

Three kinds of event are supported:

``eta_slip``
    An inbound line will arrive later than promised.
``quantity_short``
    An inbound line will deliver less, or stock on hand is less than booked.
``lot_rejected``
    A lot failed incoming inspection and goes back. A replacement date may be
    given; without one the quantity is simply gone.

The effect is measured by running the kit check before and after.
"""

from __future__ import annotations

from datetime import datetime

from app.models.schedule import ScheduleSnapshot
from app.models.supply import (
    MaterialImpact,
    MaterialShortageEvent,
    SupplyOrderLine,
    SupplySnapshot,
)
from app.services.supply.kitting import check_kits


class ShortageEventError(ValueError):
    """The event cannot be applied to this snapshot."""


def _target_lines(supply: SupplySnapshot, event: MaterialShortageEvent) -> list[SupplyOrderLine]:
    candidates = [
        line
        for line in supply.supply_orders
        if line.item_id == event.item_id and line.status not in {"released", "cancelled"}
    ]
    if event.order_id is not None:
        candidates = [line for line in candidates if line.order_id == event.order_id]
        if event.line_id is not None:
            candidates = [line for line in candidates if line.line_id == event.line_id]
        return candidates
    candidates.sort(key=lambda line: (line.promised_at, line.key))
    return candidates[:1]


def apply_event(
    supply: SupplySnapshot, event: MaterialShortageEvent
) -> tuple[SupplySnapshot, list[str]]:
    """Return a copy of ``supply`` with the event applied, and the lines it touched."""
    updated = supply.model_copy(deep=True)
    targets = _target_lines(updated, event)
    touched = [line.key for line in targets]

    if event.kind == "eta_slip":
        if event.new_promised_at is None:
            raise ShortageEventError("eta_slip needs new_promised_at")
        if not targets:
            raise ShortageEventError(f"no open inbound line for item {event.item_id}")
        for line in targets:
            line.promised_at = event.new_promised_at
            if line.status == "received":
                line.status = "open"
                line.received_at = None
        return updated, touched

    if event.kind == "quantity_short":
        if event.short_quantity is None:
            raise ShortageEventError("quantity_short needs short_quantity")
        if targets:
            line = targets[0]
            remaining = line.quantity - event.short_quantity
            if remaining <= 0:
                line.status = "cancelled"
            else:
                line.quantity = remaining
            return updated, touched[:1]
        for stock in updated.inventory:
            if stock.item_id == event.item_id:
                stock.on_hand = max(0.0, stock.on_hand - event.short_quantity)
                return updated, [f"stock:{event.item_id}"]
        raise ShortageEventError(f"item {event.item_id} has no inbound line and no stock record")

    if not targets:
        raise ShortageEventError(f"no inbound line to reject for item {event.item_id}")
    for line in targets:
        if event.new_promised_at is not None:
            updated.supply_orders.append(
                SupplyOrderLine(
                    order_id=line.order_id,
                    line_id=f"{line.line_id}-R",
                    item_id=line.item_id,
                    supplier_id=line.supplier_id,
                    quantity=line.quantity,
                    promised_at=event.new_promised_at,
                )
            )
        line.status = "cancelled"
    return updated, touched


def assess(
    supply: SupplySnapshot,
    schedule: ScheduleSnapshot,
    event: MaterialShortageEvent,
    *,
    reference_time: datetime | None = None,
) -> tuple[MaterialImpact, SupplySnapshot]:
    """Measure the event's effect on kit status. Returns the impact and the new supply."""
    before = check_kits(supply, schedule, reference_time=reference_time)
    updated, touched = apply_event(supply, event)
    after = check_kits(updated, schedule, reference_time=reference_time)
    late_before = set(before.late_operation_ids)
    unresolved_before = set(before.unresolved_operation_ids)
    approved = [
        rule
        for rule in supply.substitutes
        if rule.primary_item_id == event.item_id
        and rule.approved
        and rule.approved_by
        and rule.source_ref
    ]
    impact = MaterialImpact(
        event=event,
        affected_order_keys=touched,
        before=before,
        after=after,
        newly_late_operation_ids=[op for op in after.late_operation_ids if op not in late_before],
        newly_unresolved_operation_ids=[
            op for op in after.unresolved_operation_ids if op not in unresolved_before
        ],
        approved_substitutes=approved,
    )
    return impact, updated
