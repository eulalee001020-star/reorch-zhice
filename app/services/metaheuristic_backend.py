"""Hybrid metaheuristic backend for large-neighborhood exploration.

The implementation uses deterministic GA/Tabu-inspired neighborhood sampling
and delegates each local repair to CP-SAT. This gives us a production-safe
hybrid path today while leaving room for richer GA/Tabu/Memetic operators.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import settings
from app.models.enums import NeighborhoodType, StrategyType
from app.models.impact import ImpactReport
from app.models.schedule import ScheduleSnapshot
from app.services.constraint_aware_ssgs import ConstraintAwareSsgsScheduler
from app.services.cp_sat_scheduler import CpSatFjspScheduler, CpSatScheduleResult
from app.services.machine_rank_service import MachineRank
from app.services.operational_constraint_validator import OperationalConstraintValidator


@dataclass(frozen=True)
class NeighborhoodCandidate:
    neighborhood_type: NeighborhoodType
    target_operation_ids: list[str]
    reasoning: str


@dataclass(frozen=True)
class MetaheuristicResult:
    schedules: list[CpSatScheduleResult]
    explored_neighborhoods: list[str] = field(default_factory=list)


class MetaheuristicBackend:
    """Explores diverse neighborhoods and calls CP-SAT for local refinement."""

    def __init__(self, cp_sat_scheduler: CpSatFjspScheduler | None = None) -> None:
        self._cp_sat = cp_sat_scheduler or CpSatFjspScheduler()
        self._validator = OperationalConstraintValidator()
        self._heuristic = ConstraintAwareSsgsScheduler(self._validator)

    def solve(
        self,
        *,
        snapshot: ScheduleSnapshot,
        impact_report: ImpactReport,
        strategy_type: StrategyType,
        affected_op_ids: list[str],
        frozen_operation_ids: list[str],
        machine_ranks: list[MachineRank],
        timeout_seconds: float,
        candidate_count: int,
    ) -> MetaheuristicResult:
        neighborhoods = self._build_neighborhoods(
            snapshot=snapshot,
            impact_report=impact_report,
            affected_op_ids=affected_op_ids,
            machine_ranks=machine_ranks,
        )
        schedules: list[CpSatScheduleResult] = []
        explored: list[str] = []
        heuristic = self._heuristic.solve(
            snapshot=snapshot,
            impact_report=impact_report,
            strategy_type=strategy_type,
            affected_op_ids=affected_op_ids,
            frozen_operation_ids=frozen_operation_ids,
            timeout_seconds=min(
                settings.solver.heuristic_max_seconds,
                max(
                    0.05,
                    timeout_seconds * settings.solver.heuristic_budget_ratio,
                ),
            ),
        )
        initial_solution = heuristic.schedule_detail if heuristic.is_feasible else None
        if initial_solution is not None:
            schedules.append(
                CpSatScheduleResult(
                    schedule_detail=initial_solution,
                    status_name=heuristic.status_name,
                    is_feasible=True,
                    objective_value=heuristic.objective_value,
                    wall_time_seconds=heuristic.wall_time_seconds,
                    variable_operation_ids=heuristic.variable_operation_ids,
                    solver_log={
                        "backend": "constraint_aware_ssgs",
                        "checked_constraints": heuristic.checked_constraints,
                    },
                )
            )
        remaining_budget = max(0.1, timeout_seconds - heuristic.wall_time_seconds)
        per_neighborhood_timeout = max(
            0.2,
            remaining_budget / max(1, min(candidate_count, len(neighborhoods))),
        )

        seen_signatures = {
            self._signature(result)
            for result in schedules
            if result.schedule_detail is not None
        }
        for idx, neighborhood in enumerate(neighborhoods):
            if len(schedules) >= candidate_count:
                break
            result = self._cp_sat.solve(
                snapshot=snapshot,
                impact_report=impact_report,
                strategy_type=(
                    StrategyType.LOCAL_REPAIR
                    if strategy_type == StrategyType.GLOBAL_RESCHEDULE
                    else strategy_type
                ),
                affected_op_ids=neighborhood.target_operation_ids,
                frozen_operation_ids=frozen_operation_ids,
                timeout_seconds=per_neighborhood_timeout,
                candidate_index=idx,
                initial_solution=initial_solution,
            )
            explored.append(neighborhood.neighborhood_type.value)
            if self._is_validated(
                result,
                snapshot,
                frozen_operation_ids,
            ):
                signature = self._signature(result)
                if signature not in seen_signatures:
                    seen_signatures.add(signature)
                    schedules.append(result)

        return MetaheuristicResult(
            schedules=schedules,
            explored_neighborhoods=explored,
        )

    def _is_validated(
        self,
        result: CpSatScheduleResult,
        snapshot: ScheduleSnapshot,
        frozen_operation_ids: list[str],
    ) -> bool:
        if not result.is_feasible or result.schedule_detail is None:
            return False
        all_operation_ids = {
            operation.operation_id
            for work_order in snapshot.work_orders
            for operation in work_order.operations
        }
        effective_frozen = set(frozen_operation_ids) | (
            all_operation_ids - set(result.variable_operation_ids)
        )
        report = self._validator.validate(
            result.schedule_detail,
            snapshot,
            frozen_operation_ids=sorted(effective_frozen),
        )
        result.solver_log = {
            **result.solver_log,
            "independent_validation": (
                "feasible" if report.is_feasible else "infeasible"
            ),
        }
        return report.is_feasible

    @staticmethod
    def _build_neighborhoods(
        *,
        snapshot: ScheduleSnapshot,
        impact_report: ImpactReport,
        affected_op_ids: list[str],
        machine_ranks: list[MachineRank],
    ) -> list[NeighborhoodCandidate]:
        affected = set(affected_op_ids)
        downstream = set(affected)
        changed = True
        while changed:
            changed = False
            for wo in snapshot.work_orders:
                for op in wo.operations:
                    if op.operation_id not in downstream and downstream & set(op.predecessor_ids):
                        downstream.add(op.operation_id)
                        changed = True

        delayed_orders = {
            wo.work_order_id
            for wo in impact_report.affected_work_orders
            if str(wo.delivery_risk_level) in {"warning", "breach"}
        }
        delayed_ops = [
            op.operation_id
            for wo in snapshot.work_orders
            for op in wo.operations
            if wo.work_order_id in delayed_orders
        ]
        top_machines = {rank.resource_id for rank in machine_ranks[:2]}
        bottleneck_ops = [
            op.operation_id
            for wo in snapshot.work_orders
            for op in wo.operations
            if op.resource_id in top_machines
        ]

        all_ops = [
            op.operation_id
            for wo in snapshot.work_orders
            for op in wo.operations
        ]
        candidates = [
            NeighborhoodCandidate(
                NeighborhoodType.DELAYED_ORDER,
                sorted(set(delayed_ops) or affected),
                "delayed_order_neighborhood",
            ),
            NeighborhoodCandidate(
                NeighborhoodType.CRITICAL_PATH,
                sorted(downstream),
                "affected_downstream_neighborhood",
            ),
            NeighborhoodCandidate(
                NeighborhoodType.BOTTLENECK_DEVICE,
                sorted(set(bottleneck_ops) or affected),
                "machine_rank_bottleneck_neighborhood",
            ),
            NeighborhoodCandidate(
                NeighborhoodType.SAME_DEVICE_SWAP,
                sorted(affected),
                "same_device_swap_neighborhood",
            ),
            NeighborhoodCandidate(
                NeighborhoodType.DEVICE_REASSIGNMENT,
                sorted(downstream),
                "device_reassignment_neighborhood",
            ),
            NeighborhoodCandidate(
                NeighborhoodType.OPERATION_INSERT,
                sorted(set(all_ops) if len(all_ops) <= 80 else downstream),
                "operation_insert_large_neighborhood",
            ),
        ]
        return [c for c in candidates if c.target_operation_ids]

    @staticmethod
    def _signature(result: CpSatScheduleResult) -> str:
        assert result.schedule_detail is not None
        parts: list[str] = []
        for wo in result.schedule_detail.work_orders:
            for op in wo.operations:
                parts.append(
                    f"{op.operation_id}:{op.resource_id}:{op.start_time.isoformat()}:{op.end_time.isoformat()}"
                )
        return "|".join(sorted(parts))
