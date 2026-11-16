"""Deterministic schedule scoring shared by anytime solver components."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.schedule import ScheduleDetail, ScheduleSnapshot


@dataclass(frozen=True)
class ScheduleObjective:
    """Lexicographic business metrics; every field is lower-is-better."""

    critical_tardiness_minutes: float
    delayed_order_count: int
    total_tardiness_minutes: float
    max_tardiness_minutes: float
    total_start_shift_minutes: float
    changed_operation_count: int
    makespan_minutes: float

    def ranking_key(self, goal_mode: str = "balanced") -> tuple[float, ...]:
        if goal_mode == "delivery_priority":
            return (
                self.critical_tardiness_minutes,
                float(self.delayed_order_count),
                self.total_tardiness_minutes,
                self.max_tardiness_minutes,
                self.total_start_shift_minutes,
                self.makespan_minutes,
            )
        if goal_mode == "stability_priority":
            return (
                self.critical_tardiness_minutes,
                self.total_start_shift_minutes,
                float(self.changed_operation_count),
                float(self.delayed_order_count),
                self.total_tardiness_minutes,
                self.makespan_minutes,
            )
        if goal_mode == "bottleneck_priority":
            return (
                self.critical_tardiness_minutes,
                self.makespan_minutes,
                float(self.delayed_order_count),
                self.total_tardiness_minutes,
                self.total_start_shift_minutes,
            )
        return (
            self.critical_tardiness_minutes,
            float(self.delayed_order_count),
            self.total_tardiness_minutes,
            self.total_start_shift_minutes,
            self.makespan_minutes,
        )

    def scalar_value(self) -> float:
        """Stable audit value, not a proof of Pareto dominance."""
        return round(
            self.critical_tardiness_minutes * 100_000
            + self.delayed_order_count * 10_000
            + self.total_tardiness_minutes * 100
            + self.total_start_shift_minutes
            + self.makespan_minutes / 10_000,
            4,
        )


def evaluate_schedule(
    schedule: ScheduleDetail,
    baseline: ScheduleSnapshot,
) -> ScheduleObjective:
    baseline_ops = {
        op.operation_id: op for wo in baseline.work_orders for op in wo.operations
    }
    starts = [op.start_time for wo in schedule.work_orders for op in wo.operations]
    ends = [op.end_time for wo in schedule.work_orders for op in wo.operations]
    origin = min(starts) if starts else baseline.captured_at
    makespan = (
        max(0.0, (max(ends) - origin).total_seconds() / 60.0) if ends else 0.0
    )

    delayed_count = 0
    critical_tardiness = 0.0
    total_tardiness = 0.0
    max_tardiness = 0.0
    total_shift = 0.0
    changed = 0

    for work_order in schedule.work_orders:
        if work_order.operations:
            completion = max(op.end_time for op in work_order.operations)
            tardiness = max(
                0.0, (completion - work_order.due_date).total_seconds() / 60.0
            )
            if tardiness > 0:
                delayed_count += 1
            total_tardiness += tardiness
            max_tardiness = max(max_tardiness, tardiness)
            if work_order.priority > 0:
                critical_tardiness += tardiness * max(1, work_order.priority)

        for operation in work_order.operations:
            baseline_operation = baseline_ops.get(operation.operation_id)
            if baseline_operation is None:
                changed += 1
                continue
            shift = abs(
                (operation.start_time - baseline_operation.start_time).total_seconds()
                / 60.0
            )
            total_shift += shift
            if (
                shift > 0
                or operation.end_time != baseline_operation.end_time
                or operation.resource_id != baseline_operation.resource_id
            ):
                changed += 1

    return ScheduleObjective(
        critical_tardiness_minutes=round(critical_tardiness, 4),
        delayed_order_count=delayed_count,
        total_tardiness_minutes=round(total_tardiness, 4),
        max_tardiness_minutes=round(max_tardiness, 4),
        total_start_shift_minutes=round(total_shift, 4),
        changed_operation_count=changed,
        makespan_minutes=round(makespan, 4),
    )
