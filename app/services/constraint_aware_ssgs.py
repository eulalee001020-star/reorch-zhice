"""Constraint-aware serial schedule generation for fast feasible incumbents."""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.models.enums import StrategyType
from app.models.impact import ImpactReport
from app.models.schedule import Operation, ScheduleDetail, ScheduleSnapshot, WorkOrder
from app.services.cp_sat_scheduler import CpSatFjspScheduler
from app.services.operational_constraint_validator import OperationalConstraintValidator
from app.services.schedule_objective import evaluate_schedule


@dataclass(frozen=True)
class HeuristicScheduleResult:
    schedule_detail: ScheduleDetail | None
    status_name: str
    is_feasible: bool
    wall_time_seconds: float = 0.0
    objective_value: float | None = None
    variable_operation_ids: list[str] = field(default_factory=list)
    checked_constraints: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Interval:
    start: int
    end: int
    operation_id: str
    family: str | None = None


class ConstraintAwareSsgsScheduler:
    """Build a deterministic incumbent without invoking an optimization solver."""

    def __init__(
        self,
        validator: OperationalConstraintValidator | None = None,
    ) -> None:
        self._validator = validator or OperationalConstraintValidator()

    def solve(
        self,
        *,
        snapshot: ScheduleSnapshot,
        impact_report: ImpactReport,
        strategy_type: StrategyType,
        affected_op_ids: list[str],
        frozen_operation_ids: list[str],
        goal_mode: str = "balanced",
        timeout_seconds: float | None = None,
    ) -> HeuristicScheduleResult:
        started = time.perf_counter()
        deadline = (
            started + max(0.01, timeout_seconds)
            if timeout_seconds is not None
            else None
        )
        if not snapshot.work_orders:
            return self._failure("HEURISTIC_NO_OPERATIONS", ["missing_operations"], started)

        parser = CpSatFjspScheduler()
        origin = parser._time_origin(snapshot)
        refs = parser._collect_operation_refs(snapshot, origin)
        governance_blockers = parser._strict_governance_blockers(snapshot, refs)
        if governance_blockers:
            return self._failure(
                "HEURISTIC_GOVERNANCE_BLOCKED", governance_blockers, started
            )

        refs_by_id = {ref.operation.operation_id: ref for ref in refs}
        operations = {
            op.operation_id: op for wo in snapshot.work_orders for op in wo.operations
        }
        work_orders = {wo.work_order_id: wo for wo in snapshot.work_orders}
        affected = set(affected_op_ids)
        quality_frozen = parser._quality_frozen_operation_ids(snapshot)
        frozen = set(frozen_operation_ids) | quality_frozen
        variable = parser._repair_scope(snapshot, strategy_type, affected) - frozen
        variable &= set(operations)
        delay_by_op = parser._delay_by_operation(impact_report)
        material_release = parser._material_available_offsets(snapshot, origin)
        quality_release = parser._quality_release_offsets(snapshot, origin)
        tooling_by_op = parser._tooling_requirements(snapshot)
        skill_by_op = parser._skill_requirements(snapshot)
        urgent = parser._urgent_constraint_by_work_order(snapshot, origin)
        horizon = parser._horizon_minutes(snapshot, origin, delay_by_op)
        raw = snapshot.raw_data or {}

        release_by_op = _time_constraint_map(
            raw.get("operation_release_constraints", []), "release_at", origin, max
        )
        deadline_by_op = _time_constraint_map(
            raw.get("operation_deadline_constraints", []), "deadline_at", origin, min
        )
        transport_in, transport_out = _transport_maps(raw)
        buffer_in = _buffer_map(raw)
        setup_lookup = parser._changeover_setup_lookup(snapshot)
        family_by_op = parser._operation_family_from_raw(snapshot)
        resource_caps = _resource_capabilities(snapshot)
        tooling_capacity, tooling_blocks = _tooling_capacity(raw, origin, horizon)
        skill_capacity, skill_blocks = _skill_capacity(raw, origin, horizon)
        outsource_capacity = _outsourcing_capacity(raw)

        machine_intervals: dict[str, list[_Interval]] = {}
        secondary_intervals: dict[str, list[tuple[int, int, int]]] = {}
        lane_intervals: dict[str, list[tuple[int, int, int]]] = {}
        buffer_intervals: dict[str, list[tuple[int, int, int]]] = {}
        outsource_usage: dict[str, int] = {}
        scheduled: dict[str, Operation] = {}

        for operation_id, operation in operations.items():
            if operation_id in variable:
                continue
            scheduled[operation_id] = operation.model_copy(deep=True)
            start = _offset(origin, operation.start_time)
            end = _offset(origin, operation.end_time)
            machine_intervals.setdefault(operation.resource_id, []).append(
                _Interval(
                    start,
                    end,
                    operation_id,
                    family_by_op.get(operation_id),
                )
            )
            for tooling_id in tooling_by_op.get(operation_id, []):
                secondary_intervals.setdefault(f"tool:{tooling_id}", []).append(
                    (start, end, 1)
                )
            for skill_code in skill_by_op.get(operation_id, []):
                secondary_intervals.setdefault(f"skill:{skill_code}", []).append(
                    (start, end, 1)
                )
            if operation.resource_id.startswith("OUTSOURCE:"):
                outsource_usage[operation.resource_id] = (
                    outsource_usage.get(operation.resource_id, 0) + 1
                )

        for resource_id, windows in _resource_calendar(raw, origin, horizon).items():
            for index, (start, end) in enumerate(windows):
                machine_intervals.setdefault(resource_id, []).append(
                    _Interval(start, end, f"calendar:{resource_id}:{index}")
                )
        for tooling_id, intervals in tooling_blocks.items():
            secondary_intervals.setdefault(f"tool:{tooling_id}", []).extend(intervals)
        for skill_code, intervals in skill_blocks.items():
            secondary_intervals.setdefault(f"skill:{skill_code}", []).extend(intervals)

        _reserve_fixed_transports(
            operations=scheduled,
            transport_out=transport_out,
            origin=origin,
            lane_intervals=lane_intervals,
        )
        _reserve_fixed_buffers(
            operations=scheduled,
            raw=raw,
            origin=origin,
            buffer_intervals=buffer_intervals,
        )

        predecessors, successors = _precedence_graph(snapshot, variable)
        ready, indegree = _ready_queue(
            variable, predecessors, operations, work_orders, urgent, goal_mode
        )
        scheduled_variable_count = 0

        while ready:
            if deadline is not None and time.perf_counter() >= deadline:
                return self._failure(
                    "HEURISTIC_TIMEOUT",
                    ["heuristic_time_budget_exhausted"],
                    started,
                    variable,
                )
            _, operation_id = heapq.heappop(ready)
            ref = refs_by_id[operation_id]
            operation = operations[operation_id]
            work_order = work_orders[operation.work_order_id]
            earliest = 0 if operation.work_order_id in urgent else ref.original_start
            if operation_id in affected:
                earliest += delay_by_op.get(operation_id, 0)
            earliest = max(
                earliest,
                material_release.get(operation_id, 0),
                quality_release.get(operation_id, 0),
                release_by_op.get(operation_id, 0),
            )
            if earliest >= 1_000_000:
                return self._failure(
                    "HEURISTIC_MATERIAL_BLOCKED",
                    [f"material_unavailable:{operation_id}"],
                    started,
                    variable,
                )

            for predecessor_id in predecessors.get(operation_id, set()):
                predecessor = scheduled.get(predecessor_id)
                if predecessor is None:
                    return self._failure(
                        "HEURISTIC_PRECEDENCE_BLOCKED",
                        [f"unscheduled_predecessor:{operation_id}:{predecessor_id}"],
                        started,
                        variable,
                    )
                lag = max(
                    [
                        int(row.get("eta_minutes", 0) or 0)
                        for row in transport_in.get(operation_id, [])
                        if str(row.get("predecessor_operation_id")) == predecessor_id
                    ]
                    or [0]
                )
                earliest = max(earliest, _offset(origin, predecessor.end_time) + lag)

            latest_end = deadline_by_op.get(operation_id, horizon)
            for successor_id in successors.get(operation_id, set()):
                if successor_id in variable:
                    continue
                successor = scheduled.get(successor_id)
                if successor is not None:
                    latest_end = min(latest_end, _offset(origin, successor.start_time))

            candidates: list[tuple[tuple[int, int, int], str, int, int]] = []
            for resource_id in ref.eligible_resources:
                known_caps = resource_caps.get(resource_id)
                required_caps = set(operation.required_capabilities)
                if required_caps and known_caps is not None and not required_caps.issubset(known_caps):
                    continue
                if resource_id.startswith("OUTSOURCE:") and (
                    outsource_usage.get(resource_id, 0)
                    >= outsource_capacity.get(resource_id, 0)
                ):
                    continue
                duration = ref.duration_by_resource.get(resource_id, ref.duration)
                slot = self._find_slot(
                    operation_id=operation_id,
                    resource_id=resource_id,
                    family=family_by_op.get(operation_id, work_order.product_name),
                    earliest=earliest,
                    latest_end=latest_end,
                    duration=duration,
                    horizon=horizon,
                    machine_intervals=machine_intervals,
                    setup_lookup=setup_lookup,
                    tooling_ids=tooling_by_op.get(operation_id, []),
                    skill_codes=skill_by_op.get(operation_id, []),
                    secondary_intervals=secondary_intervals,
                    tooling_capacity=tooling_capacity,
                    skill_capacity=skill_capacity,
                    outgoing_transports=transport_out.get(operation_id, []),
                    lane_intervals=lane_intervals,
                    incoming_buffers=buffer_in.get(operation_id, []),
                    scheduled=scheduled,
                    origin=origin,
                    buffer_intervals=buffer_intervals,
                    deadline=deadline,
                )
                if slot is None:
                    continue
                start, end = slot
                candidates.append(
                    (
                        (
                            end,
                            int(resource_id != operation.resource_id),
                            len(machine_intervals.get(resource_id, [])),
                        ),
                        resource_id,
                        start,
                        end,
                    )
                )

            if not candidates:
                if deadline is not None and time.perf_counter() >= deadline:
                    return self._failure(
                        "HEURISTIC_TIMEOUT",
                        ["heuristic_time_budget_exhausted"],
                        started,
                        variable,
                    )
                return self._failure(
                    "HEURISTIC_NO_FEASIBLE_INSERTION",
                    [f"no_feasible_insertion:{operation_id}"],
                    started,
                    variable,
                )

            _, resource_id, start, end = min(candidates, key=lambda item: item[0])
            scheduled_operation = operation.model_copy(deep=True)
            scheduled_operation.resource_id = resource_id
            scheduled_operation.start_time = origin + timedelta(minutes=start)
            scheduled_operation.end_time = origin + timedelta(minutes=end)
            scheduled_operation.is_affected = operation_id in affected
            scheduled_operation.is_adjusted = (
                resource_id != operation.resource_id
                or scheduled_operation.start_time != operation.start_time
                or scheduled_operation.end_time != operation.end_time
            )
            scheduled[operation_id] = scheduled_operation
            machine_intervals.setdefault(resource_id, []).append(
                _Interval(start, end, operation_id, family_by_op.get(operation_id))
            )
            for tooling_id in tooling_by_op.get(operation_id, []):
                secondary_intervals.setdefault(f"tool:{tooling_id}", []).append(
                    (start, end, 1)
                )
            for skill_code in skill_by_op.get(operation_id, []):
                secondary_intervals.setdefault(f"skill:{skill_code}", []).append(
                    (start, end, 1)
                )
            _reserve_operation_transports(
                operation_id, end, transport_out, lane_intervals
            )
            _reserve_operation_buffers(
                operation_id,
                start,
                buffer_in,
                scheduled,
                origin,
                buffer_intervals,
            )
            if resource_id.startswith("OUTSOURCE:"):
                outsource_usage[resource_id] = outsource_usage.get(resource_id, 0) + 1

            scheduled_variable_count += 1
            for successor_id in successors.get(operation_id, set()):
                if successor_id not in indegree:
                    continue
                indegree[successor_id] -= 1
                if indegree[successor_id] == 0:
                    heapq.heappush(
                        ready,
                        (
                            _dispatch_key(
                                successor_id,
                                operations,
                                work_orders,
                                urgent,
                                goal_mode,
                            ),
                            successor_id,
                        ),
                    )

        if scheduled_variable_count != len(variable):
            remaining = sorted(variable - set(scheduled))
            return self._failure(
                "HEURISTIC_PRECEDENCE_CYCLE",
                [f"precedence_cycle_or_unresolved:{','.join(remaining)}"],
                started,
                variable,
            )

        detail = _build_schedule(snapshot, scheduled, parser)
        report = self._validator.validate(
            detail,
            snapshot,
            frozen_operation_ids=sorted(frozen | (set(operations) - variable)),
        )
        if not report.is_feasible:
            return HeuristicScheduleResult(
                schedule_detail=None,
                status_name="HEURISTIC_VALIDATION_FAILED",
                is_feasible=False,
                wall_time_seconds=time.perf_counter() - started,
                variable_operation_ids=sorted(variable),
                checked_constraints=report.checked_constraints,
                blockers=[
                    f"{violation.constraint_type}:{violation.operation_id}"
                    for violation in report.violations
                ],
            )
        objective = evaluate_schedule(detail, snapshot)
        return HeuristicScheduleResult(
            schedule_detail=detail,
            status_name="HEURISTIC_FEASIBLE",
            is_feasible=True,
            wall_time_seconds=time.perf_counter() - started,
            objective_value=objective.scalar_value(),
            variable_operation_ids=sorted(variable),
            checked_constraints=report.checked_constraints,
        )

    @staticmethod
    def _find_slot(
        *,
        operation_id: str,
        resource_id: str,
        family: str,
        earliest: int,
        latest_end: int,
        duration: int,
        horizon: int,
        machine_intervals: dict[str, list[_Interval]],
        setup_lookup: dict[tuple[str | None, str, str], int],
        tooling_ids: list[str],
        skill_codes: list[str],
        secondary_intervals: dict[str, list[tuple[int, int, int]]],
        tooling_capacity: dict[str, int],
        skill_capacity: dict[str, int],
        outgoing_transports: list[dict[str, Any]],
        lane_intervals: dict[str, list[tuple[int, int, int]]],
        incoming_buffers: list[dict[str, Any]],
        scheduled: dict[str, Operation],
        origin: datetime,
        buffer_intervals: dict[str, list[tuple[int, int, int]]],
        deadline: float | None,
    ) -> tuple[int, int] | None:
        candidate = max(0, earliest)
        hard_end = min(horizon, latest_end)
        while candidate + duration <= hard_end:
            if deadline is not None and time.perf_counter() >= deadline:
                return None
            candidate = _machine_slot(
                candidate,
                duration,
                resource_id,
                family,
                machine_intervals.get(resource_id, []),
                setup_lookup,
            )
            end = candidate + duration
            if end > hard_end:
                return None
            if not all(
                _has_capacity(
                    secondary_intervals.get(f"tool:{tooling_id}", []),
                    tooling_capacity.get(tooling_id, 1),
                    candidate,
                    end,
                )
                for tooling_id in tooling_ids
            ):
                candidate += 1
                continue
            if not all(
                _has_capacity(
                    secondary_intervals.get(f"skill:{skill_code}", []),
                    skill_capacity.get(skill_code, 1),
                    candidate,
                    end,
                )
                for skill_code in skill_codes
            ):
                candidate += 1
                continue
            if not _transport_capacity_available(
                outgoing_transports, end, lane_intervals
            ):
                candidate += 1
                continue
            if not _buffer_capacity_available(
                incoming_buffers,
                candidate,
                scheduled,
                origin,
                buffer_intervals,
            ):
                return None
            return candidate, end
        return None

    @staticmethod
    def _failure(
        status: str,
        blockers: list[str],
        started: float,
        variable: set[str] | None = None,
    ) -> HeuristicScheduleResult:
        return HeuristicScheduleResult(
            schedule_detail=None,
            status_name=status,
            is_feasible=False,
            wall_time_seconds=time.perf_counter() - started,
            variable_operation_ids=sorted(variable or set()),
            blockers=blockers,
        )


def _build_schedule(
    snapshot: ScheduleSnapshot,
    scheduled: dict[str, Operation],
    parser: CpSatFjspScheduler,
) -> ScheduleDetail:
    work_orders: list[WorkOrder] = []
    for work_order in snapshot.work_orders:
        copied = work_order.model_copy(deep=True)
        copied.operations = [
            scheduled[operation.operation_id].model_copy(deep=True)
            for operation in work_order.operations
        ]
        work_orders.append(copied)
    return ScheduleDetail(
        work_orders=work_orders,
        resources=parser._resources_from_raw(snapshot),
    )


def _precedence_graph(
    snapshot: ScheduleSnapshot,
    variable: set[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    operations = {
        op.operation_id: op for wo in snapshot.work_orders for op in wo.operations
    }
    predecessors = {
        operation_id: set(operations[operation_id].predecessor_ids)
        for operation_id in operations
    }
    successors: dict[str, set[str]] = {
        operation_id: set() for operation_id in operations
    }
    for operation_id, predecessor_ids in predecessors.items():
        for predecessor_id in predecessor_ids:
            if predecessor_id in successors:
                successors[predecessor_id].add(operation_id)
    for row in (snapshot.raw_data or {}).get("batch_genealogy", []) or []:
        children = [str(item) for item in row.get("operation_ids", []) or []]
        parents = [str(item) for item in row.get("parent_operation_ids", []) or []]
        if row.get("rework_required") and row.get("rework_operation_id"):
            parents.append(str(row["rework_operation_id"]))
        for child in children:
            if child not in predecessors:
                continue
            for parent in parents:
                if parent in operations and parent != child:
                    predecessors[child].add(parent)
                    successors[parent].add(child)
    return predecessors, successors


def _ready_queue(
    variable: set[str],
    predecessors: dict[str, set[str]],
    operations: dict[str, Operation],
    work_orders: dict[str, WorkOrder],
    urgent: dict[str, tuple[int, int, int]],
    goal_mode: str,
) -> tuple[list[tuple[tuple[Any, ...], str]], dict[str, int]]:
    indegree = {
        operation_id: len(predecessors.get(operation_id, set()) & variable)
        for operation_id in variable
    }
    ready = [
        (
            _dispatch_key(operation_id, operations, work_orders, urgent, goal_mode),
            operation_id,
        )
        for operation_id, degree in indegree.items()
        if degree == 0
    ]
    heapq.heapify(ready)
    return ready, indegree


def _dispatch_key(
    operation_id: str,
    operations: dict[str, Operation],
    work_orders: dict[str, WorkOrder],
    urgent: dict[str, tuple[int, int, int]],
    goal_mode: str,
) -> tuple[Any, ...]:
    operation = operations[operation_id]
    work_order = work_orders[operation.work_order_id]
    urgent_rank = 0 if operation.work_order_id in urgent else 1
    stability_rank = operation.start_time if goal_mode == "stability_priority" else work_order.due_date
    return (
        urgent_rank,
        stability_rank,
        -work_order.priority,
        operation.start_time,
        operation_id,
    )


def _machine_slot(
    earliest: int,
    duration: int,
    resource_id: str,
    family: str,
    intervals: list[_Interval],
    setup_lookup: dict[tuple[str | None, str, str], int],
) -> int:
    ordered = sorted(intervals, key=lambda item: (item.start, item.end))
    candidate = earliest
    previous: _Interval | None = None
    for interval in ordered:
        before = (
            CpSatFjspScheduler._setup_minutes(
                setup_lookup, resource_id, previous.family, family
            )
            if previous and previous.family
            else 0
        )
        candidate = max(candidate, (previous.end + before) if previous else candidate)
        after = (
            CpSatFjspScheduler._setup_minutes(
                setup_lookup, resource_id, family, interval.family
            )
            if interval.family
            else 0
        )
        if candidate + duration + after <= interval.start:
            return candidate
        if candidate < interval.end:
            previous = interval
            continue
        previous = interval
    if previous:
        setup = (
            CpSatFjspScheduler._setup_minutes(
                setup_lookup, resource_id, previous.family, family
            )
            if previous.family
            else 0
        )
        candidate = max(candidate, previous.end + setup)
    return candidate


def _has_capacity(
    intervals: list[tuple[int, int, int]],
    capacity: int,
    start: int,
    end: int,
    demand: int = 1,
    base_usage: int = 0,
) -> bool:
    if capacity <= 0:
        return False
    points: list[tuple[int, int, int]] = [(start, 1, demand), (end, 0, -demand)]
    for interval_start, interval_end, interval_demand in intervals:
        if interval_end <= start or interval_start >= end:
            continue
        points.append((max(start, interval_start), 1, interval_demand))
        points.append((min(end, interval_end), 0, -interval_demand))
    usage = base_usage
    for _, _, delta in sorted(points, key=lambda item: (item[0], item[1])):
        usage += delta
        if usage > capacity:
            return False
    return True


def _resource_calendar(
    raw: dict[str, Any], origin: datetime, horizon: int
) -> dict[str, list[tuple[int, int]]]:
    result: dict[str, list[tuple[int, int]]] = {}
    for row in raw.get("resource_calendar", []) or []:
        if row.get("availability_type", "unavailable") != "unavailable":
            continue
        start = _datetime_offset(row.get("window_start"), origin)
        end = _datetime_offset(row.get("window_end"), origin)
        resource_id = str(row.get("resource_id", ""))
        if resource_id and end > start:
            result.setdefault(resource_id, []).append((start, min(end, horizon)))
    return result


def _tooling_capacity(
    raw: dict[str, Any], origin: datetime, horizon: int
) -> tuple[dict[str, int], dict[str, list[tuple[int, int, int]]]]:
    capacity: dict[str, int] = {}
    blocks: dict[str, list[tuple[int, int, int]]] = {}
    for row in raw.get("tooling_calendar", []) or []:
        tooling_id = str(row.get("tooling_id", ""))
        if not tooling_id:
            continue
        quantity = max(0, int(row.get("quantity", 1) or 0))
        capacity[tooling_id] = max(capacity.get(tooling_id, 1), quantity)
        start = _datetime_offset(row.get("unavailable_start"), origin)
        end = _datetime_offset(row.get("unavailable_end"), origin)
        if end > start and capacity[tooling_id] > 0:
            blocks.setdefault(tooling_id, []).append(
                (start, min(end, horizon), capacity[tooling_id])
            )
    return capacity, blocks


def _skill_capacity(
    raw: dict[str, Any], origin: datetime, horizon: int
) -> tuple[dict[str, int], dict[str, list[tuple[int, int, int]]]]:
    rows_by_skill: dict[str, list[tuple[int, int, int]]] = {}
    capacity: dict[str, int] = {}
    for row in raw.get("labor_skill_capacity", []) or []:
        skill = str(row.get("skill_code", ""))
        if not skill:
            continue
        available = max(0, int(row.get("available_headcount", 0) or 0))
        capacity[skill] = max(capacity.get(skill, 1), available)
        start = _datetime_offset(row.get("window_start"), origin)
        end = _datetime_offset(row.get("window_end"), origin)
        if end > start:
            rows_by_skill.setdefault(skill, []).append((start, min(end, horizon), available))
    blocks: dict[str, list[tuple[int, int, int]]] = {}
    for skill, windows in rows_by_skill.items():
        maximum = capacity[skill]
        blocks[skill] = [
            (start, end, maximum - available)
            for start, end, available in windows
            if maximum > available
        ]
    return capacity, blocks


def _resource_capabilities(snapshot: ScheduleSnapshot) -> dict[str, set[str]]:
    result = {
        str(row.get("resource_id")): {
            str(item) for item in row.get("capabilities", []) or []
        }
        for row in (snapshot.raw_data or {}).get("resources", []) or []
        if row.get("resource_id")
    }
    for resource in CpSatFjspScheduler._resources_from_raw(snapshot):
        result[resource.resource_id] = set(resource.capabilities)
    return result


def _outsourcing_capacity(raw: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in raw.get("outsourcing_approvals", []) or []:
        if str(row.get("approval_status", "pending")).lower() != "approved":
            continue
        if not row.get("approved_by") or not row.get("source_ref"):
            continue
        resource_id = str(
            row.get("resource_id") or f"OUTSOURCE:{row.get('vendor_id', '')}"
        )
        value = max(1, int(row.get("capacity_per_day", 1) or 1))
        result[resource_id] = min(result.get(resource_id, value), value)
    return result


def _transport_maps(
    raw: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    incoming: dict[str, list[dict[str, Any]]] = {}
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for row in raw.get("transport_lanes", []) or []:
        predecessor = str(row.get("predecessor_operation_id", ""))
        successor = str(row.get("successor_operation_id", ""))
        if predecessor and successor:
            outgoing.setdefault(predecessor, []).append(row)
            incoming.setdefault(successor, []).append(row)
    return incoming, outgoing


def _buffer_map(raw: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    incoming: dict[str, list[dict[str, Any]]] = {}
    for row in raw.get("buffer_flows", []) or []:
        successor = str(row.get("successor_operation_id", ""))
        if successor:
            incoming.setdefault(successor, []).append(row)
    return incoming


def _reserve_fixed_transports(
    *,
    operations: dict[str, Operation],
    transport_out: dict[str, list[dict[str, Any]]],
    origin: datetime,
    lane_intervals: dict[str, list[tuple[int, int, int]]],
) -> None:
    for operation_id, operation in operations.items():
        _reserve_operation_transports(
            operation_id,
            _offset(origin, operation.end_time),
            transport_out,
            lane_intervals,
        )


def _reserve_operation_transports(
    operation_id: str,
    operation_end: int,
    transport_out: dict[str, list[dict[str, Any]]],
    lane_intervals: dict[str, list[tuple[int, int, int]]],
) -> None:
    for row in transport_out.get(operation_id, []):
        eta = max(0, int(row.get("eta_minutes", 0) or 0))
        if eta <= 0:
            continue
        lane_id = str(row.get("lane_id", "unmapped"))
        lane_intervals.setdefault(lane_id, []).append(
            (operation_end, operation_end + eta, 1)
        )


def _transport_capacity_available(
    rows: list[dict[str, Any]],
    operation_end: int,
    lane_intervals: dict[str, list[tuple[int, int, int]]],
) -> bool:
    for row in rows:
        eta = max(0, int(row.get("eta_minutes", 0) or 0))
        if eta <= 0:
            continue
        lane_id = str(row.get("lane_id", "unmapped"))
        capacity = max(1, int(row.get("capacity", 1) or 1))
        if not _has_capacity(
            lane_intervals.get(lane_id, []),
            capacity,
            operation_end,
            operation_end + eta,
        ):
            return False
    return True


def _reserve_fixed_buffers(
    *,
    operations: dict[str, Operation],
    raw: dict[str, Any],
    origin: datetime,
    buffer_intervals: dict[str, list[tuple[int, int, int]]],
) -> None:
    for row in raw.get("buffer_flows", []) or []:
        predecessor = operations.get(str(row.get("predecessor_operation_id", "")))
        successor = operations.get(str(row.get("successor_operation_id", "")))
        if predecessor is None or successor is None:
            continue
        start = _offset(origin, predecessor.end_time)
        end = _offset(origin, successor.start_time)
        if end > start:
            buffer_id = str(row.get("buffer_id", "unmapped"))
            demand = max(1, int(row.get("occupancy_quantity", 1) or 1))
            buffer_intervals.setdefault(buffer_id, []).append((start, end, demand))


def _reserve_operation_buffers(
    operation_id: str,
    operation_start: int,
    buffer_in: dict[str, list[dict[str, Any]]],
    scheduled: dict[str, Operation],
    origin: datetime,
    buffer_intervals: dict[str, list[tuple[int, int, int]]],
) -> None:
    for row in buffer_in.get(operation_id, []):
        predecessor = scheduled.get(str(row.get("predecessor_operation_id", "")))
        if predecessor is None:
            continue
        start = _offset(origin, predecessor.end_time)
        if operation_start > start:
            buffer_id = str(row.get("buffer_id", "unmapped"))
            demand = max(1, int(row.get("occupancy_quantity", 1) or 1))
            buffer_intervals.setdefault(buffer_id, []).append(
                (start, operation_start, demand)
            )


def _buffer_capacity_available(
    rows: list[dict[str, Any]],
    operation_start: int,
    scheduled: dict[str, Operation],
    origin: datetime,
    buffer_intervals: dict[str, list[tuple[int, int, int]]],
) -> bool:
    for row in rows:
        predecessor = scheduled.get(str(row.get("predecessor_operation_id", "")))
        if predecessor is None:
            continue
        start = _offset(origin, predecessor.end_time)
        if operation_start <= start:
            continue
        capacity = max(1, int(row.get("capacity", 1) or 1))
        current_wip = max(0, int(row.get("current_wip", 0) or 0))
        demand = max(1, int(row.get("occupancy_quantity", 1) or 1))
        buffer_id = str(row.get("buffer_id", "unmapped"))
        if not _has_capacity(
            buffer_intervals.get(buffer_id, []),
            capacity,
            start,
            operation_start,
            demand=demand,
            base_usage=current_wip,
        ):
            return False
    return True


def _time_constraint_map(
    rows: list[dict[str, Any]],
    field: str,
    origin: datetime,
    reducer,
) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows or []:
        operation_id = str(row.get("operation_id", ""))
        if not operation_id:
            continue
        value = _datetime_offset(row.get(field), origin)
        if operation_id in result:
            result[operation_id] = reducer(result[operation_id], value)
        else:
            result[operation_id] = value
    return result


def _datetime_offset(value: Any, origin: datetime) -> int:
    if not value:
        return 0
    if isinstance(value, datetime):
        return max(0, _offset(origin, value))
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return 0
    return max(0, _offset(origin, parsed))


def _offset(origin: datetime, value: datetime) -> int:
    return int((value - origin).total_seconds() // 60)
