"""Digital-twin-style simulation sandbox for candidate plan risk checks."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.schedule import ScheduleSnapshot
from app.models.solver import CandidatePlan


@dataclass(frozen=True)
class SimulationResult:
    plan_id: str
    execution_risk_score: float
    total_time_shift_minutes: float
    resource_switch_count: int
    frozen_violation_count: int
    bottleneck_queue_risk: float
    risk_flags: list[str] = field(default_factory=list)


class SimulationSandbox:
    """Runs lightweight deterministic execution simulation before recommendation."""

    def simulate(
        self,
        plan: CandidatePlan,
        snapshot: ScheduleSnapshot,
        frozen_operation_ids: list[str] | None = None,
    ) -> SimulationResult:
        frozen = set(frozen_operation_ids or [])
        baseline = {
            op.operation_id: op
            for wo in snapshot.work_orders
            for op in wo.operations
        }
        total_shift = 0.0
        resource_switches = 0
        frozen_violations = 0
        resource_load: dict[str, float] = {}

        for wo in plan.schedule_detail.work_orders:
            for op in wo.operations:
                base = baseline.get(op.operation_id)
                duration = max(0.0, (op.end_time - op.start_time).total_seconds() / 60)
                resource_load[op.resource_id] = resource_load.get(op.resource_id, 0.0) + duration
                if base is None:
                    continue
                shift = abs((op.start_time - base.start_time).total_seconds() / 60)
                total_shift += shift
                if op.resource_id != base.resource_id:
                    resource_switches += 1
                if op.operation_id in frozen and (
                    op.start_time != base.start_time
                    or op.end_time != base.end_time
                    or op.resource_id != base.resource_id
                ):
                    frozen_violations += 1

        max_load = max(resource_load.values(), default=0.0)
        avg_load = sum(resource_load.values()) / max(1, len(resource_load))
        bottleneck_queue_risk = max(0.0, (max_load - avg_load) / max(max_load, 1.0))
        risk_score = min(
            1.0,
            total_shift / 1440 * 0.4
            + resource_switches * 0.05
            + frozen_violations * 0.25
            + bottleneck_queue_risk * 0.3,
        )
        flags: list[str] = []
        if frozen_violations:
            flags.append("frozen_window_violation")
        if resource_switches >= 3:
            flags.append("high_resource_switch_count")
        if bottleneck_queue_risk >= 0.5:
            flags.append("bottleneck_queue_risk")
        if total_shift >= 240:
            flags.append("large_schedule_perturbation")
        return SimulationResult(
            plan_id=str(plan.plan_id),
            execution_risk_score=round(risk_score, 4),
            total_time_shift_minutes=round(total_shift, 2),
            resource_switch_count=resource_switches,
            frozen_violation_count=frozen_violations,
            bottleneck_queue_risk=round(bottleneck_queue_risk, 4),
            risk_flags=flags,
        )

