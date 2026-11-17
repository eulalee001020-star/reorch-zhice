"""Two-layer status of inbound material: arrived, and usable.

"The goods are here" and "we can start" are different facts. A received line
can still be waiting on inspection, a certificate or a missing accessory.
Counting it as stock hides the risk until the operation is due to start.

Each blocker is a gap with an owner and a due time. This module reports, per
inbound line, whether it has arrived, whether it is usable, when it will be,
and which gaps are open, overdue or unowned.
"""

from __future__ import annotations

from datetime import datetime

from app.models.supply import ReadinessLine, ReadinessReport, SupplySnapshot
from app.services.supply.kitting import _line_usable_at


def readiness_report(supply: SupplySnapshot, *, reference_time: datetime) -> ReadinessReport:
    params = {row.item_id: row for row in supply.planning_params}
    lines: list[ReadinessLine] = []
    for line in supply.supply_orders:
        if line.status == "cancelled":
            continue
        arrived = line.status in {"received", "released"}
        usable = line.status == "released"
        open_gaps = [gap for gap in line.gaps if gap.is_open]
        if usable:
            usable_at = line.released_at or reference_time
        else:
            usable_at = _line_usable_at(line, reference_time, params.get(line.item_id), 0)
        lines.append(
            ReadinessLine(
                order_key=line.key,
                item_id=line.item_id,
                supplier_id=line.supplier_id,
                quantity=line.quantity,
                arrived=arrived,
                usable=usable,
                arrived_at=line.received_at if arrived else None,
                usable_at=usable_at,
                open_gaps=open_gaps,
                overdue_gap_ids=[
                    gap.gap_id
                    for gap in open_gaps
                    if gap.due_at is not None and gap.due_at < reference_time
                ],
            )
        )
    lines.sort(key=lambda row: (row.usable, not row.arrived, row.order_key))
    open_gaps = [gap for row in lines for gap in row.open_gaps]
    return ReadinessReport(
        reference_time=reference_time,
        lines=lines,
        arrived_count=sum(1 for row in lines if row.arrived),
        usable_count=sum(1 for row in lines if row.usable),
        arrived_not_usable_count=sum(1 for row in lines if row.arrived and not row.usable),
        open_gap_count=len(open_gaps),
        overdue_gap_count=sum(len(row.overdue_gap_ids) for row in lines),
        unowned_gap_count=sum(1 for gap in open_gaps if not gap.owner),
    )
