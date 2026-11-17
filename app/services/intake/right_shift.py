"""Right-shift baseline: what happens if nothing is re-planned.

Every operation keeps its machine and its place in that machine's queue and is
only pushed later as far as it must be. This is the planner's reference point:
a recovery plan is worth adopting only if it beats waiting.

An operation is pushed by whichever of these binds last:

* the decision time, for work that was interrupted;
* the end of its predecessors;
* the operation before it on the same machine;
* its material release time;
* an unavailability window on its machine.

Work that started before the decision time and was not interrupted is history
and does not move.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.models.schedule import ScheduleSnapshot

Cause = Literal[
    "none",
    "history",
    "interrupted",
    "resource_window",
    "material",
    "unresolved_material",
    "predecessor",
    "resource_queue",
]
DIRECT_CAUSES: frozenset[str] = frozenset(
    {"interrupted", "resource_window", "material", "unresolved_material"}
)


@dataclass(frozen=True)
class ShiftedOperation:
    operation_id: str
    work_order_id: str
    resource_id: str
    planned_start: datetime
    planned_end: datetime
    new_start: datetime
    new_end: datetime
    cause: Cause

    @property
    def delay_minutes(self) -> float:
        return max(0.0, (self.new_start - self.planned_start).total_seconds() / 60.0)

    @property
    def is_direct(self) -> bool:
        return self.cause in DIRECT_CAUSES


def right_shift(
    snapshot: ScheduleSnapshot,
    *,
    decision_time: datetime,
    resource_windows: dict[str, list[tuple[datetime, datetime]]],
    material_release: dict[str, datetime | None],
    frozen_operation_ids: set[str],
) -> dict[str, ShiftedOperation]:
    """Push every operation as little as the disruption forces it to move.

    ``material_release`` maps an operation to the time its kit is complete;
    ``None`` means the material is short with no date, in which case the
    operation is placed at the end of the current plan and marked unresolved.
    """
    operations = [op for wo in snapshot.work_orders for op in wo.operations]
    if not operations:
        return {}
    plan_end = max(op.end_time for op in operations)
    ordered = sorted(operations, key=lambda op: (op.start_time, op.operation_id))
    planned_end = {op.operation_id: op.end_time for op in operations}

    result: dict[str, ShiftedOperation] = {}
    resource_free: dict[str, datetime] = {}
    for op in ordered:
        duration = op.end_time - op.start_time
        if op.operation_id in frozen_operation_ids:
            start, cause = op.start_time, "history"
        else:
            start, cause = op.start_time, "none"
            if start < decision_time:
                start, cause = decision_time, "interrupted"
            for predecessor in op.predecessor_ids:
                done = result[predecessor].new_end if predecessor in result else None
                done = done or planned_end.get(predecessor)
                if done is not None and done > start:
                    start, cause = done, "predecessor"
            queue_free = resource_free.get(op.resource_id)
            if queue_free is not None and queue_free > start:
                start, cause = queue_free, "resource_queue"
            if op.operation_id in material_release:
                release = material_release[op.operation_id]
                if release is None:
                    start, cause = max(start, plan_end), "unresolved_material"
                elif release > start:
                    start, cause = release, "material"
            moved = True
            while moved:
                moved = False
                for window_start, window_end in resource_windows.get(op.resource_id, []):
                    if start < window_end and start + duration > window_start:
                        start, cause, moved = window_end, "resource_window", True
        end = start + duration
        resource_free[op.resource_id] = max(resource_free.get(op.resource_id, end), end)
        result[op.operation_id] = ShiftedOperation(
            operation_id=op.operation_id,
            work_order_id=op.work_order_id,
            resource_id=op.resource_id,
            planned_start=op.start_time,
            planned_end=op.end_time,
            new_start=start,
            new_end=end,
            cause=cause,  # type: ignore[arg-type]
        )
    return result
