"""Rolling-window and frozen-zone planner for dynamic rescheduling."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.models.schedule import ScheduleSnapshot


@dataclass(frozen=True)
class RollingWindowPlan:
    reference_time: datetime
    frozen_until: datetime
    detailed_until: datetime
    frozen_operation_ids: list[str] = field(default_factory=list)
    detailed_operation_ids: list[str] = field(default_factory=list)
    coarse_operation_ids: list[str] = field(default_factory=list)


class RollingWindowPlanner:
    """Classifies operations into frozen, detailed, and coarse windows."""

    def __init__(self, frozen_hours: int = 4, detailed_hours: int = 24) -> None:
        self.frozen_hours = frozen_hours
        self.detailed_hours = detailed_hours

    def plan(
        self,
        snapshot: ScheduleSnapshot,
        reference_time: datetime | None = None,
    ) -> RollingWindowPlan:
        ref = reference_time or snapshot.captured_at
        frozen_until = ref + timedelta(hours=self.frozen_hours)
        detailed_until = ref + timedelta(hours=self.detailed_hours)

        frozen: list[str] = []
        detailed: list[str] = []
        coarse: list[str] = []

        for wo in snapshot.work_orders:
            for op in wo.operations:
                if getattr(op, "is_adjusted", False):
                    detailed.append(op.operation_id)
                elif op.start_time < frozen_until:
                    frozen.append(op.operation_id)
                elif op.start_time < detailed_until:
                    detailed.append(op.operation_id)
                else:
                    coarse.append(op.operation_id)

        return RollingWindowPlan(
            reference_time=ref,
            frozen_until=frozen_until,
            detailed_until=detailed_until,
            frozen_operation_ids=frozen,
            detailed_operation_ids=detailed,
            coarse_operation_ids=coarse,
        )

