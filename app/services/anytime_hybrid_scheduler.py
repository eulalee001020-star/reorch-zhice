"""Heuristic-first anytime portfolio for bounded production recovery problems."""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.core.config import settings
from app.models.enums import StrategyType
from app.models.impact import ImpactReport
from app.models.schedule import ScheduleDetail, ScheduleSnapshot
from app.services.constraint_aware_ssgs import (
    ConstraintAwareSsgsScheduler,
    HeuristicScheduleResult,
)
from app.services.cp_sat_scheduler import CpSatFjspScheduler, CpSatScheduleResult
from app.services.infeasibility_classifier import InfeasibilityClassifier
from app.services.operational_constraint_validator import OperationalConstraintValidator
from app.services.schedule_objective import evaluate_schedule


@dataclass(frozen=True)
class _ValidatedCandidate:
    source: str
    result: CpSatScheduleResult


class AnytimeHybridScheduler:
    """Return the best independently validated incumbent before the deadline."""

    def __init__(
        self,
        *,
        cp_sat_scheduler: CpSatFjspScheduler | None = None,
        heuristic_scheduler: ConstraintAwareSsgsScheduler | None = None,
        validator: OperationalConstraintValidator | None = None,
        max_alns_iterations: int | None = None,
    ) -> None:
        self._cp_sat = cp_sat_scheduler or CpSatFjspScheduler()
        self._validator = validator or OperationalConstraintValidator()
        self._heuristic = heuristic_scheduler or ConstraintAwareSsgsScheduler(
            self._validator
        )
        self._max_alns_iterations = max(
            0,
            settings.solver.max_alns_iterations
            if max_alns_iterations is None
            else max_alns_iterations,
        )

    def solve(
        self,
        *,
        snapshot: ScheduleSnapshot,
        impact_report: ImpactReport,
        strategy_type: StrategyType,
        affected_op_ids: list[str],
        frozen_operation_ids: list[str],
        timeout_seconds: float,
        candidate_index: int = 0,
        initial_solution: ScheduleDetail | None = None,
        goal_mode: str = "balanced",
        enable_alns: bool = True,
    ) -> CpSatScheduleResult:
        started = time.perf_counter()
        deadline = started + max(0.01, timeout_seconds)
        algorithm_path = ["constraint_aware_ssgs"]
        candidates: list[_ValidatedCandidate] = []
        failures: list[str] = []
        first_feasible_ms: float | None = None
        heuristic_budget = min(
            settings.solver.heuristic_max_seconds,
            max(
                0.05,
                timeout_seconds * settings.solver.heuristic_budget_ratio,
            ),
        )

        heuristic = self._heuristic.solve(
            snapshot=snapshot,
            impact_report=impact_report,
            strategy_type=strategy_type,
            affected_op_ids=affected_op_ids,
            frozen_operation_ids=frozen_operation_ids,
            goal_mode=goal_mode,
            timeout_seconds=heuristic_budget,
        )
        if heuristic.is_feasible and heuristic.schedule_detail is not None:
            candidates.append(
                _ValidatedCandidate(
                    "constraint_aware_ssgs",
                    _heuristic_as_solver_result(heuristic),
                )
            )
            first_feasible_ms = (time.perf_counter() - started) * 1000
        else:
            failures.extend(heuristic.blockers or [heuristic.status_name])

        warm_start = (
            initial_solution
            or (heuristic.schedule_detail if heuristic.is_feasible else None)
        )
        remaining = deadline - time.perf_counter()
        direct_result: CpSatScheduleResult | None = None
        if remaining > 0.02:
            reserve_for_alns = bool(enable_alns and warm_start and self._max_alns_iterations)
            direct_budget = remaining * (
                settings.solver.initial_cp_sat_budget_ratio
                if reserve_for_alns
                else 1.0
            )
            direct_result = self._cp_sat.solve(
                snapshot=snapshot,
                impact_report=impact_report,
                strategy_type=strategy_type,
                affected_op_ids=affected_op_ids,
                frozen_operation_ids=frozen_operation_ids,
                timeout_seconds=max(0.1, direct_budget),
                candidate_index=candidate_index,
                initial_solution=warm_start,
                goal_mode=goal_mode,
            )
            algorithm_path.append("cp_sat_warm_start" if warm_start else "cp_sat")
            if self._validated(
                direct_result,
                snapshot,
                frozen_operation_ids,
            ):
                candidates.append(_ValidatedCandidate("cp_sat", direct_result))
                if first_feasible_ms is None:
                    first_feasible_ms = (time.perf_counter() - started) * 1000
            else:
                failures.extend(_result_failures(direct_result))

        if enable_alns and candidates and time.perf_counter() < deadline:
            algorithm_path.append("alns_cp_sat_repair")
            incumbent = _best_candidate(candidates, snapshot, goal_mode)
            neighborhoods = _build_neighborhoods(
                snapshot,
                affected_op_ids,
                self._max_alns_iterations,
            )
            zero_delay_impact = impact_report.model_copy(
                update={"affected_operations": []}, deep=True
            )
            alns_attempts = 0
            alns_accepted = 0
            for index, neighborhood in enumerate(neighborhoods):
                remaining = deadline - time.perf_counter()
                if remaining <= 0.05:
                    break
                incumbent_schedule = incumbent.result.schedule_detail
                if incumbent_schedule is None:
                    break
                incumbent_snapshot = snapshot.model_copy(
                    update={
                        "work_orders": [
                            work_order.model_copy(deep=True)
                            for work_order in incumbent_schedule.work_orders
                        ]
                    },
                    deep=True,
                )
                iteration_budget = max(
                    0.1,
                    remaining / max(1, len(neighborhoods) - index),
                )
                repaired = self._cp_sat.solve(
                    snapshot=incumbent_snapshot,
                    impact_report=zero_delay_impact,
                    strategy_type=StrategyType.LOCAL_REPAIR,
                    affected_op_ids=neighborhood,
                    frozen_operation_ids=frozen_operation_ids,
                    timeout_seconds=iteration_budget,
                    candidate_index=0,
                    initial_solution=incumbent_schedule,
                    goal_mode=goal_mode,
                )
                alns_attempts += 1
                previously_mutable = _changed_operation_ids(
                    incumbent_schedule,
                    snapshot,
                )
                if not self._validated(
                    repaired,
                    snapshot,
                    frozen_operation_ids,
                    previously_mutable_operation_ids=previously_mutable,
                ):
                    failures.extend(_result_failures(repaired))
                    continue
                candidate = _ValidatedCandidate("alns_cp_sat_repair", repaired)
                if not _contains_schedule(candidates, repaired.schedule_detail):
                    candidates.append(candidate)
                if _candidate_key(candidate, snapshot, goal_mode) < _candidate_key(
                    incumbent, snapshot, goal_mode
                ):
                    incumbent = candidate
                    alns_accepted += 1
            alns_metadata = {
                "alns_attempts": alns_attempts,
                "alns_accepted": alns_accepted,
                "alns_neighborhood_count": len(neighborhoods),
            }
        else:
            alns_metadata = {
                "alns_attempts": 0,
                "alns_accepted": 0,
                "alns_neighborhood_count": 0,
            }

        algorithm_path.append("independent_constraint_validation")
        if not candidates:
            failure_log = {
                "heuristic_status": heuristic.status_name,
                "cp_sat_status": direct_result.status_name if direct_result else None,
                "failures": sorted(set(failures)),
            }
            classification = InfeasibilityClassifier.classify(
                status_name="NO_VALIDATED_INCUMBENT",
                is_feasible=False,
                solver_log=failure_log,
            )
            return CpSatScheduleResult(
                schedule_detail=None,
                status_name="NO_VALIDATED_INCUMBENT",
                is_feasible=False,
                wall_time_seconds=time.perf_counter() - started,
                solver_log={
                    "algorithm_path": algorithm_path,
                    "heuristic_status": heuristic.status_name,
                    "cp_sat_status": direct_result.status_name if direct_result else None,
                    "validated_incumbent": False,
                    "failures": sorted(set(failures)),
                    "failure_classification": classification.model_dump(mode="json"),
                    "recovery_required": True,
                    "restoration_endpoint": (
                        "/api/v1/runtime/feasibility-restoration/evaluate"
                    ),
                    "writeback_allowed": False,
                    **alns_metadata,
                },
            )

        pareto_front = _pareto_front(candidates, snapshot)
        best = _best_candidate(pareto_front, snapshot, goal_mode)
        schedule = best.result.schedule_detail
        assert schedule is not None
        score = evaluate_schedule(schedule, snapshot)
        backend_objective = best.result.objective_value
        best.result.objective_value = score.scalar_value()
        best.result.wall_time_seconds = time.perf_counter() - started
        best.result.status_name = (
            "HEURISTIC_FEASIBLE"
            if best.source == "constraint_aware_ssgs"
            else best.result.status_name
        )
        best.result.solver_log = {
            **best.result.solver_log,
            "algorithm_path": algorithm_path,
            "heuristic_status": heuristic.status_name,
            "cp_sat_status": direct_result.status_name if direct_result else None,
            "cp_sat_hint_applied": (
                direct_result.hint_applied if direct_result else False
            ),
            "cp_sat_hinted_operation_count": (
                direct_result.hinted_operation_count if direct_result else 0
            ),
            "cp_sat_best_objective_bound": (
                direct_result.best_objective_bound if direct_result else None
            ),
            "cp_sat_relative_gap": (
                direct_result.relative_gap if direct_result else None
            ),
            "validated_incumbent": True,
            "incumbent_source": best.source,
            "time_to_first_feasible_ms": round(first_feasible_ms or 0.0, 3),
            "validated_candidate_count": len(candidates),
            "pareto_front_size": len(pareto_front),
            "pareto_front": [
                {
                    "source": candidate.source,
                    **evaluate_schedule(
                        candidate.result.schedule_detail,
                        snapshot,
                    ).__dict__,
                }
                for candidate in pareto_front
                if candidate.result.schedule_detail is not None
            ],
            "portfolio_objective": score.__dict__,
            "backend_objective_value": backend_objective,
            "failures": sorted(set(failures)),
            **alns_metadata,
        }
        return best.result

    def _validated(
        self,
        result: CpSatScheduleResult,
        snapshot: ScheduleSnapshot,
        frozen_operation_ids: list[str],
        previously_mutable_operation_ids: set[str] | None = None,
    ) -> bool:
        if not result.is_feasible or result.schedule_detail is None:
            return False
        all_operation_ids = {
            operation.operation_id
            for work_order in snapshot.work_orders
            for operation in work_order.operations
        }
        mutable_operation_ids = set(result.variable_operation_ids) | set(
            previously_mutable_operation_ids or set()
        )
        effective_frozen = set(frozen_operation_ids) | (
            all_operation_ids - mutable_operation_ids
        )
        report = self._validator.validate(
            result.schedule_detail,
            snapshot,
            frozen_operation_ids=sorted(effective_frozen),
        )
        if report.is_feasible:
            result.solver_log = {
                **result.solver_log,
                "independent_validation": "feasible",
                "checked_constraints": report.checked_constraints,
            }
            return True
        result.solver_log = {
            **result.solver_log,
            "independent_validation": "infeasible",
            "independent_violations": [
                violation.model_dump(mode="json") for violation in report.violations
            ],
        }
        return False


def _heuristic_as_solver_result(
    result: HeuristicScheduleResult,
) -> CpSatScheduleResult:
    return CpSatScheduleResult(
        schedule_detail=result.schedule_detail,
        status_name=result.status_name,
        is_feasible=result.is_feasible,
        objective_value=result.objective_value,
        wall_time_seconds=result.wall_time_seconds,
        variable_operation_ids=result.variable_operation_ids,
        solver_log={
            "backend": "constraint_aware_ssgs",
            "checked_constraints": result.checked_constraints,
        },
    )


def _best_candidate(
    candidates: list[_ValidatedCandidate],
    baseline: ScheduleSnapshot,
    goal_mode: str,
) -> _ValidatedCandidate:
    return min(candidates, key=lambda item: _candidate_key(item, baseline, goal_mode))


def _candidate_key(
    candidate: _ValidatedCandidate,
    baseline: ScheduleSnapshot,
    goal_mode: str,
) -> tuple[float, ...]:
    schedule = candidate.result.schedule_detail
    assert schedule is not None
    source_rank = {
        "alns_cp_sat_repair": 0.0,
        "cp_sat": 1.0,
        "constraint_aware_ssgs": 2.0,
    }.get(candidate.source, 3.0)
    return (*evaluate_schedule(schedule, baseline).ranking_key(goal_mode), source_rank)


def _build_neighborhoods(
    snapshot: ScheduleSnapshot,
    affected_operation_ids: list[str],
    limit: int,
) -> list[list[str]]:
    if limit <= 0:
        return []
    operations = {
        op.operation_id: op for work_order in snapshot.work_orders for op in work_order.operations
    }
    affected = {operation_id for operation_id in affected_operation_ids if operation_id in operations}
    if not affected:
        return []
    downstream = set(affected)
    changed = True
    while changed:
        changed = False
        for operation in operations.values():
            if operation.operation_id not in downstream and downstream.intersection(
                operation.predecessor_ids
            ):
                downstream.add(operation.operation_id)
                changed = True
    resources = {operations[operation_id].resource_id for operation_id in affected}
    resource_peers = {
        operation.operation_id
        for operation in operations.values()
        if operation.resource_id in resources
    }
    work_order_ids = {operations[operation_id].work_order_id for operation_id in affected}
    work_order_peers = {
        operation.operation_id
        for operation in operations.values()
        if operation.work_order_id in work_order_ids
    }
    raw_candidates = [
        affected,
        downstream,
        affected | resource_peers,
        downstream | work_order_peers,
    ]
    result: list[list[str]] = []
    signatures: set[tuple[str, ...]] = set()
    for candidate in raw_candidates:
        signature = tuple(sorted(candidate))
        if not signature or signature in signatures:
            continue
        signatures.add(signature)
        result.append(list(signature))
        if len(result) >= limit:
            break
    return result


def _result_failures(result: CpSatScheduleResult) -> list[str]:
    failures = [result.status_name]
    failures.extend(str(item) for item in result.solver_log.get("blockers", []))
    if result.solver_log.get("independent_validation") == "infeasible":
        failures.append("independent_constraint_validation_failed")
    return failures


def _pareto_front(
    candidates: list[_ValidatedCandidate],
    baseline: ScheduleSnapshot,
) -> list[_ValidatedCandidate]:
    front: list[_ValidatedCandidate] = []
    for candidate in candidates:
        schedule = candidate.result.schedule_detail
        if schedule is None or _contains_schedule(front, schedule):
            continue
        candidate_vector = _dominance_vector(schedule, baseline)
        if any(
            _dominates(
                _dominance_vector(existing.result.schedule_detail, baseline),
                candidate_vector,
            )
            for existing in front
            if existing.result.schedule_detail is not None
        ):
            continue
        front = [
            existing
            for existing in front
            if existing.result.schedule_detail is None
            or not _dominates(
                candidate_vector,
                _dominance_vector(existing.result.schedule_detail, baseline),
            )
        ]
        front.append(candidate)
    return front or candidates[:1]


def _dominance_vector(
    schedule: ScheduleDetail,
    baseline: ScheduleSnapshot,
) -> tuple[float, ...]:
    objective = evaluate_schedule(schedule, baseline)
    return (
        objective.critical_tardiness_minutes,
        float(objective.delayed_order_count),
        objective.total_tardiness_minutes,
        objective.max_tardiness_minutes,
        objective.total_start_shift_minutes,
        float(objective.changed_operation_count),
        objective.makespan_minutes,
    )


def _dominates(left: tuple[float, ...], right: tuple[float, ...]) -> bool:
    return all(a <= b for a, b in zip(left, right)) and any(
        a < b for a, b in zip(left, right)
    )


def _contains_schedule(
    candidates: list[_ValidatedCandidate],
    schedule: ScheduleDetail | None,
) -> bool:
    if schedule is None:
        return False
    signature = _schedule_signature(schedule)
    return any(
        candidate.result.schedule_detail is not None
        and _schedule_signature(candidate.result.schedule_detail) == signature
        for candidate in candidates
    )


def _schedule_signature(schedule: ScheduleDetail) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        sorted(
            (
                operation.operation_id,
                operation.resource_id,
                operation.start_time.isoformat(),
                operation.end_time.isoformat(),
            )
            for work_order in schedule.work_orders
            for operation in work_order.operations
        )
    )


def _changed_operation_ids(
    schedule: ScheduleDetail,
    baseline: ScheduleSnapshot,
) -> set[str]:
    baseline_operations = {
        operation.operation_id: operation
        for work_order in baseline.work_orders
        for operation in work_order.operations
    }
    result: set[str] = set()
    for work_order in schedule.work_orders:
        for operation in work_order.operations:
            original = baseline_operations.get(operation.operation_id)
            if original is None or (
                operation.start_time != original.start_time
                or operation.end_time != original.end_time
                or operation.resource_id != original.resource_id
            ):
                result.add(operation.operation_id)
    return result
