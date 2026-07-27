"""Executable decomposition and joint-incident recovery service."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

from app.models.enums import DeliveryRiskLevel, StrategyType
from app.models.impact import AffectedOperation, AffectedWorkOrder, ImpactReport
from app.models.production_runtime import (
    DecompositionExecutionRequest,
    DecompositionExecutionResponse,
    RuntimeIncident,
    SubproblemExecutionResult,
)
from app.models.schedule import Operation, Resource, ScheduleDetail, ScheduleSnapshot, WorkOrder
from app.services.anytime_hybrid_scheduler import AnytimeHybridScheduler
from app.services.cp_sat_scheduler import CpSatFjspScheduler
from app.services.operational_constraint_validator import OperationalConstraintValidator


CancelCheck = Callable[[], bool]
CheckpointCallback = Callable[[SubproblemExecutionResult], None]


@dataclass(frozen=True)
class _Subproblem:
    subproblem_id: str
    incident_ids: list[str]
    operation_ids: list[str]


class DecompositionExecutor:
    """Solve bounded incident neighborhoods and merge them behind a global gate."""

    def __init__(
        self,
        scheduler_factory: Callable[[], CpSatFjspScheduler | AnytimeHybridScheduler]
        | None = None,
        validator: OperationalConstraintValidator | None = None,
    ) -> None:
        self._scheduler_factory = scheduler_factory or AnytimeHybridScheduler
        self._validator = validator or OperationalConstraintValidator()

    def execute(
        self,
        request: DecompositionExecutionRequest,
        *,
        cancel_check: CancelCheck | None = None,
        checkpoint_results: dict[str, SubproblemExecutionResult] | None = None,
        checkpoint_callback: CheckpointCallback | None = None,
    ) -> DecompositionExecutionResponse:
        started = time.perf_counter()
        cancel_check = cancel_check or (lambda: False)
        checkpoint_results = checkpoint_results or {}
        blockers = self._input_blockers(request)
        operation_count = sum(len(wo.operations) for wo in request.snapshot.work_orders)
        if blockers:
            return self._blocked_response(request, operation_count, blockers, started)

        groups = self._joint_incident_groups(request)
        subproblems, planning_blockers = self._build_subproblems(request, groups)
        if planning_blockers:
            return self._blocked_response(
                request, operation_count, planning_blockers, started, groups
            )

        if cancel_check():
            return self._cancelled_response(
                request, operation_count, groups, [], started, "cancelled_before_solve"
            )

        active = 0
        observed_parallelism = 0
        active_lock = threading.Lock()

        def run_one(problem: _Subproblem) -> SubproblemExecutionResult:
            nonlocal active, observed_parallelism
            if problem.subproblem_id in checkpoint_results:
                cached = checkpoint_results[problem.subproblem_id].model_copy(deep=True)
                cached.status = "checkpoint_reused"
                return cached
            if cancel_check():
                return self._cancelled_subproblem(problem, "cancelled_before_subproblem")
            with active_lock:
                active += 1
                observed_parallelism = max(observed_parallelism, active)
            try:
                result = self._solve_subproblem(request, problem, request.snapshot)
            finally:
                with active_lock:
                    active -= 1
            if cancel_check() and result.status == "feasible":
                return result.model_copy(
                    update={"status": "cancelled", "blockers": ["cancel_requested"]}
                )
            if checkpoint_callback is not None:
                checkpoint_callback(result)
            return result

        results: list[SubproblemExecutionResult] = []
        workers = min(request.max_parallelism, len(subproblems))
        with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="reorch-solve") as pool:
            future_map = {pool.submit(run_one, item): item for item in subproblems}
            for future in as_completed(future_map):
                problem = future_map[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(
                        SubproblemExecutionResult(
                            subproblem_id=problem.subproblem_id,
                            incident_ids=problem.incident_ids,
                            operation_ids=problem.operation_ids,
                            status="failed",
                            solver_status="UNHANDLED_SUBPROBLEM_ERROR",
                            elapsed_ms=0.0,
                            worker_name="executor",
                            blockers=[f"{type(exc).__name__}:{exc}"],
                            evidence_fingerprint=_fingerprint(
                                {"subproblem_id": problem.subproblem_id, "error": str(exc)}
                            ),
                        )
                    )
        results.sort(key=lambda item: item.subproblem_id)

        if cancel_check() or any(item.status == "cancelled" for item in results):
            return self._cancelled_response(
                request, operation_count, groups, results, started, "cancel_requested"
            )
        failed = [item for item in results if item.status not in {"feasible", "checkpoint_reused"}]
        if failed:
            blockers = [
                f"subproblem_not_feasible:{item.subproblem_id}:{item.solver_status}"
                for item in failed
            ]
            return self._final_response(
                request=request,
                operation_count=operation_count,
                groups=groups,
                results=results,
                status="blocked",
                observed_parallelism=observed_parallelism,
                final_schedule=None,
                checked_constraints=[],
                violations=[],
                blockers=blockers,
                merge_conflicts=0,
                serial_repairs=0,
                started=started,
            )

        merged = _baseline_schedule(request.snapshot)
        for result in results:
            if result.schedule_detail is not None:
                merged = _merge_schedule(merged, result.schedule_detail, set(result.operation_ids))
        report = self._validator.validate(merged, request.snapshot)
        merge_conflicts = len(report.violations)
        serial_repairs = 0

        if report.violations:
            conflicted_ops = {violation.operation_id for violation in report.violations}
            ordered = [
                problem
                for problem in subproblems
                if conflicted_ops.intersection(problem.operation_ids)
            ]
            for problem in ordered:
                if cancel_check():
                    return self._cancelled_response(
                        request, operation_count, groups, results, started, "cancelled_during_repair"
                    )
                current_snapshot = request.snapshot.model_copy(
                    update={"work_orders": merged.work_orders}, deep=True
                )
                repaired = self._solve_subproblem(request, problem, current_snapshot)
                serial_repairs += 1
                if repaired.status != "feasible" or repaired.schedule_detail is None:
                    break
                merged = _merge_schedule(
                    merged, repaired.schedule_detail, set(repaired.operation_ids)
                )
                results = [
                    repaired if item.subproblem_id == repaired.subproblem_id else item
                    for item in results
                ]
            report = self._validator.validate(merged, request.snapshot)

        final_status = "feasible" if report.is_feasible else "blocked"
        blockers = [] if report.is_feasible else ["global_constraint_gate_failed_after_merge"]
        return self._final_response(
            request=request,
            operation_count=operation_count,
            groups=groups,
            results=results,
            status=final_status,
            observed_parallelism=observed_parallelism,
            final_schedule=merged if report.is_feasible else None,
            checked_constraints=report.checked_constraints,
            violations=[item.model_dump(mode="json") for item in report.violations],
            blockers=blockers,
            merge_conflicts=merge_conflicts,
            serial_repairs=serial_repairs,
            started=started,
        )

    @staticmethod
    def _input_blockers(request: DecompositionExecutionRequest) -> list[str]:
        op_ids = {
            op.operation_id for wo in request.snapshot.work_orders for op in wo.operations
        }
        blockers: list[str] = []
        if not op_ids:
            blockers.append("missing_operations")
        if not (request.snapshot.raw_data or {}).get("resources"):
            blockers.append("missing_resources")
        for incident in request.incidents:
            missing = sorted(set(incident.affected_operation_ids) - op_ids)
            if missing and request.fail_on_unmapped_incident:
                blockers.append(
                    f"incident_unmapped_operations:{incident.incident_id}:{','.join(missing)}"
                )
        return blockers

    @staticmethod
    def _joint_incident_groups(
        request: DecompositionExecutionRequest,
    ) -> list[list[RuntimeIncident]]:
        incidents = list(request.incidents)
        parent = list(range(len(incidents)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        op_to_wo, op_to_resource = _operation_dimensions(request.snapshot)
        for left in range(len(incidents)):
            left_ops = set(incidents[left].affected_operation_ids)
            left_wos = {op_to_wo.get(op_id) for op_id in left_ops}
            left_resources = {op_to_resource.get(op_id) for op_id in left_ops}
            if incidents[left].work_order_id:
                left_wos.add(incidents[left].work_order_id)
            if incidents[left].resource_id:
                left_resources.add(incidents[left].resource_id)
            for right in range(left + 1, len(incidents)):
                right_ops = set(incidents[right].affected_operation_ids)
                right_wos = {op_to_wo.get(op_id) for op_id in right_ops}
                right_resources = {op_to_resource.get(op_id) for op_id in right_ops}
                if incidents[right].work_order_id:
                    right_wos.add(incidents[right].work_order_id)
                if incidents[right].resource_id:
                    right_resources.add(incidents[right].resource_id)
                if (
                    left_ops & right_ops
                    or _nonempty_intersection(left_wos, right_wos)
                    or _nonempty_intersection(left_resources, right_resources)
                ):
                    union(left, right)

        groups: dict[int, list[RuntimeIncident]] = {}
        for index, incident in enumerate(incidents):
            groups.setdefault(find(index), []).append(incident)
        return sorted(groups.values(), key=lambda group: group[0].incident_id)

    def _build_subproblems(
        self,
        request: DecompositionExecutionRequest,
        groups: list[list[RuntimeIncident]],
    ) -> tuple[list[_Subproblem], list[str]]:
        adjacency = _operation_adjacency(request.snapshot)
        successors = _successor_map(request.snapshot)
        op_map = _operation_map(request.snapshot)
        by_resource = _operations_by_resource(request.snapshot)
        used: set[str] = set()
        problems: list[_Subproblem] = []
        blockers: list[str] = []
        protected_by_group: list[set[str]] = []
        for group in groups:
            group_seeds = sorted(
                {
                    op_id
                    for incident in group
                    for op_id in incident.affected_operation_ids
                    if op_id in op_map
                }
            )
            protected_by_group.append(
                _bounded_downstream_closure(
                    group_seeds, successors, request.max_subproblem_operations
                )
            )
        for index, group in enumerate(groups):
            seeds = sorted(
                {
                    op_id
                    for incident in group
                    for op_id in incident.affected_operation_ids
                    if op_id in op_map
                }
            )
            if len(seeds) > request.max_subproblem_operations:
                blockers.append(
                    f"incident_scope_exceeds_limit:{','.join(i.incident_id for i in group)}"
                )
                continue
            distances = _bounded_distances(seeds, adjacency, request.neighborhood_hops)
            candidates = set(distances)
            candidates.update(
                _bounded_downstream_closure(
                    seeds,
                    successors,
                    request.max_subproblem_operations,
                )
            )
            for seed in seeds:
                resource_id = op_map[seed].resource_id
                peers = by_resource.get(resource_id, [])
                try:
                    position = peers.index(seed)
                except ValueError:
                    continue
                radius = max(1, request.neighborhood_hops)
                candidates.update(peers[max(0, position - radius) : position + radius + 1])
            protected_elsewhere = set().union(
                *[
                    protected
                    for other_index, protected in enumerate(protected_by_group)
                    if other_index != index
                ]
            )
            candidates -= protected_elsewhere
            candidates -= used
            candidates.update(seeds)
            ordered = sorted(
                candidates,
                key=lambda op_id: (
                    distances.get(op_id, request.neighborhood_hops + 2),
                    op_map[op_id].start_time,
                    op_id,
                ),
            )
            selected = ordered[: request.max_subproblem_operations]
            if not set(seeds).issubset(selected):
                blockers.append(
                    f"unable_to_preserve_joint_incident_seeds:{','.join(i.incident_id for i in group)}"
                )
                continue
            used.update(selected)
            incident_ids = sorted(incident.incident_id for incident in group)
            token = _fingerprint({"incidents": incident_ids, "operations": selected})[:12]
            problems.append(
                _Subproblem(
                    subproblem_id=f"sp-{index + 1:03d}-{token}",
                    incident_ids=incident_ids,
                    operation_ids=selected,
                )
            )
        return problems, blockers

    def _solve_subproblem(
        self,
        request: DecompositionExecutionRequest,
        problem: _Subproblem,
        baseline_snapshot: ScheduleSnapshot,
    ) -> SubproblemExecutionResult:
        started = time.perf_counter()
        projected = _project_snapshot(baseline_snapshot, set(problem.operation_ids))
        incidents = [
            incident
            for incident in request.incidents
            if incident.incident_id in set(problem.incident_ids)
        ]
        impact = _impact_report(projected, incidents)
        frozen = _frozen_ids(projected)
        result = self._scheduler_factory().solve(
            snapshot=projected,
            impact_report=impact,
            strategy_type=StrategyType.GLOBAL_RESCHEDULE,
            affected_op_ids=[
                op_id
                for incident in incidents
                for op_id in incident.affected_operation_ids
                if op_id in set(problem.operation_ids)
            ],
            frozen_operation_ids=frozen,
            timeout_seconds=max(0.1, request.timeout_seconds / max(1, len(request.incidents))),
            goal_mode=request.goal_mode,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        status = "feasible" if result.is_feasible else "infeasible"
        adjusted = 0
        if result.schedule_detail:
            adjusted = sum(
                int(op.is_adjusted)
                for wo in result.schedule_detail.work_orders
                for op in wo.operations
            )
        payload = {
            "subproblem_id": problem.subproblem_id,
            "incident_ids": problem.incident_ids,
            "operation_ids": problem.operation_ids,
            "status": status,
            "solver_status": result.status_name,
            "schedule": (
                result.schedule_detail.model_dump(mode="json")
                if result.schedule_detail
                else None
            ),
            "solver_metadata": {
                **result.solver_log,
                "best_objective_bound": result.best_objective_bound,
                "relative_gap": result.relative_gap,
                "hint_applied": result.hint_applied,
                "hinted_operation_count": result.hinted_operation_count,
            },
        }
        return SubproblemExecutionResult(
            subproblem_id=problem.subproblem_id,
            incident_ids=problem.incident_ids,
            operation_ids=problem.operation_ids,
            status=status,
            solver_status=result.status_name,
            elapsed_ms=elapsed_ms,
            worker_name=threading.current_thread().name,
            adjusted_operation_count=adjusted,
            objective_value=result.objective_value,
            schedule_detail=result.schedule_detail,
            blockers=list(result.solver_log.get("blockers", [])),
            solver_metadata={
                **result.solver_log,
                "best_objective_bound": result.best_objective_bound,
                "relative_gap": result.relative_gap,
                "hint_applied": result.hint_applied,
                "hinted_operation_count": result.hinted_operation_count,
            },
            evidence_fingerprint=_fingerprint(payload),
        )

    @staticmethod
    def _cancelled_subproblem(
        problem: _Subproblem, reason: str
    ) -> SubproblemExecutionResult:
        return SubproblemExecutionResult(
            subproblem_id=problem.subproblem_id,
            incident_ids=problem.incident_ids,
            operation_ids=problem.operation_ids,
            status="cancelled",
            solver_status="CANCELLED",
            elapsed_ms=0.0,
            worker_name=threading.current_thread().name,
            blockers=[reason],
            evidence_fingerprint=_fingerprint(
                {"subproblem_id": problem.subproblem_id, "status": "cancelled"}
            ),
        )

    def _blocked_response(
        self,
        request: DecompositionExecutionRequest,
        operation_count: int,
        blockers: list[str],
        started: float,
        groups: list[list[RuntimeIncident]] | None = None,
    ) -> DecompositionExecutionResponse:
        return self._final_response(
            request=request,
            operation_count=operation_count,
            groups=groups or [],
            results=[],
            status="blocked",
            observed_parallelism=0,
            final_schedule=None,
            checked_constraints=[],
            violations=[],
            blockers=blockers,
            merge_conflicts=0,
            serial_repairs=0,
            started=started,
        )

    def _cancelled_response(
        self,
        request: DecompositionExecutionRequest,
        operation_count: int,
        groups: list[list[RuntimeIncident]],
        results: list[SubproblemExecutionResult],
        started: float,
        reason: str,
    ) -> DecompositionExecutionResponse:
        return self._final_response(
            request=request,
            operation_count=operation_count,
            groups=groups,
            results=results,
            status="cancelled",
            observed_parallelism=0,
            final_schedule=None,
            checked_constraints=[],
            violations=[],
            blockers=[reason],
            merge_conflicts=0,
            serial_repairs=0,
            started=started,
        )

    @staticmethod
    def _final_response(
        *,
        request: DecompositionExecutionRequest,
        operation_count: int,
        groups: list[list[RuntimeIncident]],
        results: list[SubproblemExecutionResult],
        status: str,
        observed_parallelism: int,
        final_schedule: ScheduleDetail | None,
        checked_constraints: list[str],
        violations: list[dict[str, Any]],
        blockers: list[str],
        merge_conflicts: int,
        serial_repairs: int,
        started: float,
    ) -> DecompositionExecutionResponse:
        payload = {
            "tenant_id": request.tenant_id,
            "snapshot_id": str(request.snapshot.snapshot_id),
            "incidents": [item.model_dump(mode="json") for item in request.incidents],
            "subproblems": [item.evidence_fingerprint for item in results],
            "status": status,
            "violations": violations,
        }
        return DecompositionExecutionResponse(
            tenant_id=request.tenant_id,
            status=status,
            operation_count=operation_count,
            incident_count=len(request.incidents),
            subproblem_results=results,
            joint_incident_groups=[
                sorted(incident.incident_id for incident in group) for group in groups
            ],
            requested_parallelism=request.max_parallelism,
            observed_parallelism=observed_parallelism,
            merge_conflicts_detected=merge_conflicts,
            serial_repairs_run=serial_repairs,
            final_schedule=final_schedule,
            checked_constraints=checked_constraints,
            violations=violations,
            blockers=blockers,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            evidence_fingerprint=_fingerprint(payload),
            claim_boundary=(
                "Executable bounded-subgraph result validated against the full supplied "
                "snapshot. Digital-twin feasibility is not customer production evidence."
            ),
        )


def _operation_map(snapshot: ScheduleSnapshot) -> dict[str, Operation]:
    return {op.operation_id: op for wo in snapshot.work_orders for op in wo.operations}


def _operation_dimensions(
    snapshot: ScheduleSnapshot,
) -> tuple[dict[str, str], dict[str, str]]:
    op_to_wo: dict[str, str] = {}
    op_to_resource: dict[str, str] = {}
    for wo in snapshot.work_orders:
        for op in wo.operations:
            op_to_wo[op.operation_id] = wo.work_order_id
            op_to_resource[op.operation_id] = op.resource_id
    return op_to_wo, op_to_resource


def _operation_adjacency(snapshot: ScheduleSnapshot) -> dict[str, set[str]]:
    adjacency = {op_id: set() for op_id in _operation_map(snapshot)}
    for wo in snapshot.work_orders:
        for op in wo.operations:
            for other in [*op.predecessor_ids, *op.successor_ids]:
                if other in adjacency:
                    adjacency[op.operation_id].add(other)
                    adjacency[other].add(op.operation_id)
    return adjacency


def _successor_map(snapshot: ScheduleSnapshot) -> dict[str, set[str]]:
    result = {op_id: set() for op_id in _operation_map(snapshot)}
    for wo in snapshot.work_orders:
        for op in wo.operations:
            result[op.operation_id].update(
                succ_id for succ_id in op.successor_ids if succ_id in result
            )
            for predecessor_id in op.predecessor_ids:
                if predecessor_id in result:
                    result[predecessor_id].add(op.operation_id)
    return result


def _bounded_downstream_closure(
    seeds: list[str],
    successors: dict[str, set[str]],
    limit: int,
) -> set[str]:
    selected = set(seeds)
    frontier = list(seeds)
    while frontier and len(selected) < limit:
        current = frontier.pop(0)
        for successor in sorted(successors.get(current, set())):
            if successor in selected:
                continue
            selected.add(successor)
            frontier.append(successor)
            if len(selected) >= limit:
                break
    return selected


def _operations_by_resource(snapshot: ScheduleSnapshot) -> dict[str, list[str]]:
    groups: dict[str, list[Operation]] = {}
    for op in _operation_map(snapshot).values():
        groups.setdefault(op.resource_id, []).append(op)
    return {
        resource_id: [op.operation_id for op in sorted(ops, key=lambda item: item.start_time)]
        for resource_id, ops in groups.items()
    }


def _bounded_distances(
    seeds: list[str], adjacency: dict[str, set[str]], max_hops: int
) -> dict[str, int]:
    distances = {seed: 0 for seed in seeds}
    frontier = list(seeds)
    while frontier:
        current = frontier.pop(0)
        distance = distances[current]
        if distance >= max_hops:
            continue
        for neighbor in sorted(adjacency.get(current, set())):
            if neighbor not in distances:
                distances[neighbor] = distance + 1
                frontier.append(neighbor)
    return distances


def _project_snapshot(snapshot: ScheduleSnapshot, operation_ids: set[str]) -> ScheduleSnapshot:
    op_map = _operation_map(snapshot)
    selected_resources = {
        op_map[op_id].resource_id for op_id in operation_ids if op_id in op_map
    }
    raw = dict(snapshot.raw_data or {})
    raw_work_orders = []
    raw_by_op: dict[str, dict[str, Any]] = {}
    for raw_wo in raw.get("work_orders", []) or []:
        for raw_op in raw_wo.get("operations", []) or []:
            if raw_op.get("operation_id"):
                raw_by_op[str(raw_op["operation_id"])] = raw_op
    release_constraints: list[dict[str, Any]] = []
    deadline_constraints: list[dict[str, Any]] = []
    projected_work_orders: list[WorkOrder] = []
    for wo in snapshot.work_orders:
        projected_ops: list[Operation] = []
        projected_raw_ops: list[dict[str, Any]] = []
        for op in wo.operations:
            if op.operation_id not in operation_ids:
                continue
            copied = op.model_copy(deep=True)
            missing_predecessors = [
                pred_id for pred_id in copied.predecessor_ids if pred_id not in operation_ids
            ]
            for pred_id in missing_predecessors:
                predecessor = op_map.get(pred_id)
                if predecessor:
                    release_constraints.append(
                        {
                            "operation_id": copied.operation_id,
                            "release_at": predecessor.end_time.isoformat(),
                            "boundary_predecessor_id": pred_id,
                        }
                    )
            missing_successors = [
                succ_id for succ_id in copied.successor_ids if succ_id not in operation_ids
            ]
            for succ_id in missing_successors:
                successor = op_map.get(succ_id)
                if successor:
                    deadline_constraints.append(
                        {
                            "operation_id": copied.operation_id,
                            "deadline_at": successor.start_time.isoformat(),
                            "boundary_successor_id": succ_id,
                        }
                    )
            copied.predecessor_ids = [
                pred_id for pred_id in copied.predecessor_ids if pred_id in operation_ids
            ]
            copied.successor_ids = [
                succ_id for succ_id in copied.successor_ids if succ_id in operation_ids
            ]
            projected_ops.append(copied)
            raw_op = dict(raw_by_op.get(op.operation_id, {}))
            raw_op.setdefault("operation_id", op.operation_id)
            raw_op.setdefault("eligible_resources", [op.resource_id])
            projected_raw_ops.append(raw_op)
            selected_resources.update(str(item) for item in raw_op.get("eligible_resources", []) or [])
        if projected_ops:
            copied_wo = wo.model_copy(update={"operations": projected_ops}, deep=True)
            projected_work_orders.append(copied_wo)
            raw_work_orders.append(
                {
                    "work_order_id": wo.work_order_id,
                    "product_family": wo.product_name,
                    "operations": projected_raw_ops,
                }
            )

    excluded_by_resource: dict[str, list[tuple[datetime, datetime]]] = {}
    for op in op_map.values():
        if op.operation_id not in operation_ids and op.resource_id in selected_resources:
            excluded_by_resource.setdefault(op.resource_id, []).append(
                (op.start_time, op.end_time)
            )
    boundary_calendar = []
    for resource_id, intervals in excluded_by_resource.items():
        for index, (start, end) in enumerate(_merge_intervals(intervals)):
            boundary_calendar.append(
                {
                    "resource_id": resource_id,
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "availability_type": "unavailable",
                    "source": f"decomposition_boundary:{index}",
                }
            )

    raw["work_orders"] = raw_work_orders
    raw["resources"] = [
        row
        for row in raw.get("resources", []) or []
        if str(row.get("resource_id", "")) in selected_resources
    ]
    raw["resource_calendar"] = [
        *[
            row
            for row in raw.get("resource_calendar", []) or []
            if str(row.get("resource_id", "")) in selected_resources
        ],
        *boundary_calendar,
    ]
    raw["operation_release_constraints"] = [
        *raw.get("operation_release_constraints", []),
        *release_constraints,
    ]
    raw["operation_deadline_constraints"] = [
        *raw.get("operation_deadline_constraints", []),
        *deadline_constraints,
    ]
    _filter_operational_rows(raw, operation_ids)
    return snapshot.model_copy(
        update={"work_orders": projected_work_orders, "raw_data": raw}, deep=True
    )


def _filter_operational_rows(raw: dict[str, Any], operation_ids: set[str]) -> None:
    list_fields = {
        "material_availability": "operation_ids",
        "substitute_material_approvals": "operation_ids",
        "quality_holds": "blocked_operation_ids",
        "tooling_calendar": "operation_ids",
        "labor_skill_capacity": "operation_ids",
        "outsourcing_approvals": "operation_ids",
        "batch_genealogy": "operation_ids",
        "qms_release_gates": "operation_ids",
    }
    for table, field in list_fields.items():
        filtered = []
        for row in raw.get(table, []) or []:
            copied = dict(row)
            values = [str(item) for item in copied.get(field, []) or []]
            kept = [item for item in values if item in operation_ids]
            if kept:
                copied[field] = kept
                if table == "batch_genealogy":
                    copied["parent_operation_ids"] = [
                        str(item)
                        for item in copied.get("parent_operation_ids", []) or []
                        if str(item) in operation_ids
                    ]
                filtered.append(copied)
        raw[table] = filtered
    for table in ("transport_lanes", "buffer_flows"):
        raw[table] = [
            row
            for row in raw.get(table, []) or []
            if str(row.get("predecessor_operation_id", "")) in operation_ids
            and str(row.get("successor_operation_id", "")) in operation_ids
        ]


def _merge_intervals(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    merged: list[list[datetime]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(item[0], item[1]) for item in merged]


def _impact_report(
    snapshot: ScheduleSnapshot, incidents: list[RuntimeIncident]
) -> ImpactReport:
    op_map = _operation_map(snapshot)
    affected: dict[str, AffectedOperation] = {}
    for incident in incidents:
        for op_id in incident.affected_operation_ids:
            op = op_map.get(op_id)
            if op is None:
                continue
            current = affected.get(op_id)
            delay = max(
                incident.delay_minutes,
                int(current.estimated_delay_minutes) if current else 0,
            )
            affected[op_id] = AffectedOperation(
                operation_id=op_id,
                work_order_id=op.work_order_id,
                resource_id=op.resource_id,
                is_direct=True,
                estimated_delay_minutes=delay,
            )
    by_wo: dict[str, list[AffectedOperation]] = {}
    for item in affected.values():
        by_wo.setdefault(item.work_order_id, []).append(item)
    wo_map = {wo.work_order_id: wo for wo in snapshot.work_orders}
    affected_wos = [
        AffectedWorkOrder(
            work_order_id=work_order_id,
            product_name=wo_map[work_order_id].product_name,
            due_date=wo_map[work_order_id].due_date,
            delivery_risk_level=DeliveryRiskLevel.WARNING,
            remaining_buffer_minutes=0,
            affected_operations=items,
        )
        for work_order_id, items in by_wo.items()
    ]
    incident_token = "|".join(sorted(item.incident_id for item in incidents))
    return ImpactReport(
        incident_id=uuid5(NAMESPACE_URL, incident_token),
        schedule_snapshot_id=snapshot.snapshot_id,
        analysis_reference_time=snapshot.captured_at,
        affected_work_orders=affected_wos,
        affected_operations=list(affected.values()),
        affected_resource_ids=sorted({item.resource_id for item in affected.values()}),
        delivery_risk_distribution={DeliveryRiskLevel.WARNING: len(affected_wos)},
        estimated_total_delay_minutes=sum(
            item.estimated_delay_minutes for item in affected.values()
        ),
    )


def _frozen_ids(snapshot: ScheduleSnapshot) -> list[str]:
    raw = snapshot.raw_data or {}
    frozen = {str(item) for item in raw.get("frozen_operation_ids", []) or []}
    return sorted(frozen)


def _baseline_schedule(snapshot: ScheduleSnapshot) -> ScheduleDetail:
    resources: list[Resource] = []
    for row in (snapshot.raw_data or {}).get("resources", []) or []:
        try:
            resources.append(Resource.model_validate(row))
        except Exception:
            resource_id = row.get("resource_id")
            if resource_id:
                resources.append(
                    Resource(
                        resource_id=str(resource_id),
                        name=str(row.get("name") or resource_id),
                        capabilities=[str(item) for item in row.get("capabilities", []) or []],
                    )
                )
    return ScheduleDetail(
        work_orders=[wo.model_copy(deep=True) for wo in snapshot.work_orders],
        resources=resources,
    )


def _merge_schedule(
    baseline: ScheduleDetail,
    update: ScheduleDetail,
    operation_ids: set[str],
) -> ScheduleDetail:
    updated_ops = {
        op.operation_id: op
        for wo in update.work_orders
        for op in wo.operations
        if op.operation_id in operation_ids
    }
    work_orders: list[WorkOrder] = []
    for wo in baseline.work_orders:
        operations = [
            updated_ops.get(op.operation_id, op).model_copy(deep=True)
            for op in wo.operations
        ]
        work_orders.append(wo.model_copy(update={"operations": operations}, deep=True))
    resources = {resource.resource_id: resource for resource in baseline.resources}
    resources.update({resource.resource_id: resource for resource in update.resources})
    return ScheduleDetail(work_orders=work_orders, resources=list(resources.values()))


def _nonempty_intersection(left: set[str | None], right: set[str | None]) -> bool:
    return bool((left - {None}) & (right - {None}))


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()
