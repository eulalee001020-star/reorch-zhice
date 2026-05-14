"""CP-SAT backend for flexible job shop rescheduling.

This module provides the first production-grade detailed scheduling backend.
It models:
- operation precedence
- unary resource no-overlap
- flexible eligible resources through optional intervals
- frozen operations and strategy-specific repair scope
- simple delay lower bounds for directly impacted operations

It is intentionally scoped as a backend service so HybridSolver can keep a
portfolio/fallback structure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ortools.sat.python import cp_model

from app.models.enums import StrategyType
from app.models.impact import ImpactReport
from app.models.schedule import Operation, Resource, ScheduleDetail, ScheduleSnapshot, WorkOrder

logger = logging.getLogger(__name__)


@dataclass
class CpSatScheduleResult:
    """Result payload returned by the CP-SAT scheduler backend."""

    schedule_detail: ScheduleDetail | None
    status_name: str
    is_feasible: bool
    objective_value: float | None = None
    wall_time_seconds: float = 0.0
    branches: int = 0
    conflicts: int = 0
    variable_operation_ids: list[str] = field(default_factory=list)
    solver_log: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _OperationRef:
    work_order: WorkOrder
    operation: Operation
    original_start: int
    duration: int
    eligible_resources: list[str]


class CpSatFjspScheduler:
    """Detailed FJSP rescheduler using OR-Tools CP-SAT."""

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
    ) -> CpSatScheduleResult:
        if not snapshot.work_orders:
            return CpSatScheduleResult(
                schedule_detail=None,
                status_name="NO_SNAPSHOT_WORK_ORDERS",
                is_feasible=False,
            )

        origin = self._time_origin(snapshot)
        operation_refs = self._collect_operation_refs(snapshot, origin)
        if not operation_refs:
            return CpSatScheduleResult(
                schedule_detail=None,
                status_name="NO_OPERATIONS",
                is_feasible=False,
            )

        affected_set = set(affected_op_ids)
        variable_ids = self._repair_scope(snapshot, strategy_type, affected_set)
        variable_ids -= set(frozen_operation_ids)
        frozen_ids = set(frozen_operation_ids)
        delay_by_op = self._delay_by_operation(impact_report)
        material_available_by_op = self._material_available_offsets(snapshot, origin)

        horizon = self._horizon_minutes(snapshot, origin, delay_by_op)
        model = cp_model.CpModel()

        starts: dict[str, cp_model.IntVar] = {}
        ends: dict[str, cp_model.IntVar] = {}
        presences: dict[tuple[str, str], cp_model.IntVar] = {}
        intervals_by_resource: dict[str, list[cp_model.IntervalVar]] = {}
        resource_choices: dict[str, list[str]] = {}
        start_offsets: dict[str, int] = {}

        for ref in operation_refs:
            op = ref.operation
            op_id = op.operation_id
            is_variable = op_id in variable_ids and op_id not in frozen_ids
            resources = ref.eligible_resources if is_variable else [op.resource_id]
            resources = resources or [op.resource_id]
            resource_choices[op_id] = resources
            start_offsets[op_id] = ref.original_start

            start = model.NewIntVar(0, horizon, f"start_{op_id}")
            end = model.NewIntVar(0, horizon, f"end_{op_id}")
            starts[op_id] = start
            ends[op_id] = end
            model.Add(end == start + ref.duration)

            if is_variable:
                lower_bound = ref.original_start
                if op_id in affected_set:
                    lower_bound += delay_by_op.get(op_id, 0)
                lower_bound = max(lower_bound, material_available_by_op.get(op_id, 0))
                model.Add(start >= lower_bound + candidate_index * 5)
            else:
                model.Add(start == ref.original_start)

            presence_vars: list[cp_model.IntVar] = []
            for resource_id in resources:
                presence = model.NewBoolVar(f"use_{op_id}_{resource_id}")
                interval = model.NewOptionalIntervalVar(
                    start,
                    ref.duration,
                    end,
                    presence,
                    f"interval_{op_id}_{resource_id}",
                )
                presences[(op_id, resource_id)] = presence
                presence_vars.append(presence)
                intervals_by_resource.setdefault(resource_id, []).append(interval)

            model.AddExactlyOne(presence_vars)
            if not is_variable:
                model.Add(presence_vars[0] == 1)

        self._add_precedence_constraints(snapshot, model, starts, ends)
        self._add_calendar_blocks(
            snapshot,
            model,
            origin,
            horizon,
            intervals_by_resource,
        )
        self._add_changeover_constraints(
            snapshot=snapshot,
            model=model,
            starts=starts,
            ends=ends,
            presences=presences,
            resource_choices=resource_choices,
        )

        for intervals in intervals_by_resource.values():
            if intervals:
                model.AddNoOverlap(intervals)

        objective_terms: list[cp_model.LinearExpr] = []
        for op_id in variable_ids:
            if op_id in starts:
                shift = model.NewIntVar(0, horizon, f"shift_{op_id}")
                model.Add(shift == starts[op_id] - start_offsets[op_id])
                objective_terms.append(shift)

        makespan = model.NewIntVar(0, horizon, "makespan")
        model.AddMaxEquality(makespan, list(ends.values()))
        objective_terms.append(makespan)

        for wo in snapshot.work_orders:
            wo_end_vars = [
                ends[op.operation_id]
                for op in wo.operations
                if op.operation_id in ends
            ]
            if not wo_end_vars:
                continue
            completion = model.NewIntVar(0, horizon, f"completion_{wo.work_order_id}")
            model.AddMaxEquality(completion, wo_end_vars)
            due_offset = max(0, int((wo.due_date - origin).total_seconds() // 60))
            tardiness = model.NewIntVar(0, horizon, f"tardiness_{wo.work_order_id}")
            model.Add(tardiness >= completion - due_offset)
            model.Add(tardiness >= 0)
            priority_weight = max(1, wo.priority + 1)
            objective_terms.append(tardiness * priority_weight * 10)

        model.Minimize(sum(objective_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(0.1, min(timeout_seconds, 30.0))
        solver.parameters.num_search_workers = 8
        solver.parameters.random_seed = 17 + candidate_index
        status = solver.Solve(model)
        status_name = solver.StatusName(status)
        is_feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        if not is_feasible:
            logger.info("CP-SAT returned %s for snapshot %s", status_name, snapshot.snapshot_id)
            return CpSatScheduleResult(
                schedule_detail=None,
                status_name=status_name,
                is_feasible=False,
                wall_time_seconds=solver.WallTime(),
                branches=solver.NumBranches(),
                conflicts=solver.NumConflicts(),
                variable_operation_ids=sorted(variable_ids),
            )

        schedule_detail = self._build_schedule_detail(
            snapshot=snapshot,
            origin=origin,
            operation_refs=operation_refs,
            starts=starts,
            ends=ends,
            presences=presences,
            resource_choices=resource_choices,
            variable_ids=variable_ids,
            affected_set=affected_set,
            solver=solver,
        )

        return CpSatScheduleResult(
            schedule_detail=schedule_detail,
            status_name=status_name,
            is_feasible=True,
            objective_value=solver.ObjectiveValue(),
            wall_time_seconds=solver.WallTime(),
            branches=solver.NumBranches(),
            conflicts=solver.NumConflicts(),
            variable_operation_ids=sorted(variable_ids),
            solver_log={
                "horizon_minutes": horizon,
                "operation_count": len(operation_refs),
                "resource_count": len(intervals_by_resource),
                "candidate_index": candidate_index,
            },
        )

    # ── Model preparation ──────────────────────────────────────────

    @staticmethod
    def _time_origin(snapshot: ScheduleSnapshot) -> datetime:
        starts = [
            op.start_time
            for wo in snapshot.work_orders
            for op in wo.operations
        ]
        starts.append(snapshot.captured_at)
        return min(starts)

    def _collect_operation_refs(
        self, snapshot: ScheduleSnapshot, origin: datetime
    ) -> list[_OperationRef]:
        eligible_by_op = self._eligible_resources_from_raw(snapshot)
        refs: list[_OperationRef] = []
        for wo in snapshot.work_orders:
            for op in wo.operations:
                start = int((op.start_time - origin).total_seconds() // 60)
                duration = max(1, int((op.end_time - op.start_time).total_seconds() // 60))
                eligible = eligible_by_op.get(op.operation_id)
                if not eligible:
                    eligible = self._eligible_by_capability(snapshot, op)
                if op.resource_id not in eligible:
                    eligible.insert(0, op.resource_id)
                refs.append(
                    _OperationRef(
                        work_order=wo,
                        operation=op,
                        original_start=start,
                        duration=duration,
                        eligible_resources=list(dict.fromkeys(eligible)),
                    )
                )
        return refs

    @staticmethod
    def _eligible_resources_from_raw(snapshot: ScheduleSnapshot) -> dict[str, list[str]]:
        raw = snapshot.raw_data or {}
        result: dict[str, list[str]] = {}
        for wo in raw.get("work_orders", []):
            for op in wo.get("operations", []):
                op_id = op.get("operation_id")
                eligible = op.get("eligible_resources")
                if op_id and isinstance(eligible, list):
                    result[op_id] = [str(r) for r in eligible]
        return result

    @staticmethod
    def _eligible_by_capability(snapshot: ScheduleSnapshot, op: Operation) -> list[str]:
        raw = snapshot.raw_data or {}
        resources = raw.get("resources", [])
        if not resources or not op.required_capabilities:
            return [op.resource_id]
        required = set(op.required_capabilities)
        eligible: list[str] = []
        for res in resources:
            capabilities = set(res.get("capabilities", []))
            if required.issubset(capabilities):
                resource_id = res.get("resource_id")
                if resource_id:
                    eligible.append(str(resource_id))
        return eligible or [op.resource_id]

    @staticmethod
    def _delay_by_operation(impact_report: ImpactReport) -> dict[str, int]:
        delays: dict[str, int] = {}
        for affected in impact_report.affected_operations:
            delays[affected.operation_id] = max(
                delays.get(affected.operation_id, 0),
                int(round(affected.estimated_delay_minutes)),
            )
        return delays

    @staticmethod
    def _material_available_offsets(
        snapshot: ScheduleSnapshot,
        origin: datetime,
    ) -> dict[str, int]:
        raw = snapshot.raw_data or {}
        result: dict[str, int] = {}
        for wo in raw.get("work_orders", []):
            for op in wo.get("operations", []):
                op_id = op.get("operation_id")
                if not op_id:
                    continue
                latest = 0
                for mat in op.get("material_requirements", []) or []:
                    available_at = mat.get("available_at")
                    if not available_at:
                        continue
                    try:
                        if isinstance(available_at, datetime):
                            dt = available_at
                        else:
                            dt = datetime.fromisoformat(str(available_at).replace("Z", "+00:00"))
                        latest = max(latest, int((dt - origin).total_seconds() // 60))
                    except Exception:
                        continue
                if latest > 0:
                    result[str(op_id)] = latest
        return result

    @staticmethod
    def _horizon_minutes(
        snapshot: ScheduleSnapshot, origin: datetime, delay_by_op: dict[str, int]
    ) -> int:
        max_end = max(
            op.end_time
            for wo in snapshot.work_orders
            for op in wo.operations
        )
        baseline = int((max_end - origin).total_seconds() // 60)
        total_duration = sum(
            max(1, int((op.end_time - op.start_time).total_seconds() // 60))
            for wo in snapshot.work_orders
            for op in wo.operations
        )
        return max(baseline + sum(delay_by_op.values()) + 240, total_duration * 2 + 240)

    @staticmethod
    def _repair_scope(
        snapshot: ScheduleSnapshot,
        strategy_type: StrategyType,
        affected_set: set[str],
    ) -> set[str]:
        if strategy_type == StrategyType.GLOBAL_RESCHEDULE:
            return {
                op.operation_id
                for wo in snapshot.work_orders
                for op in wo.operations
            }

        if strategy_type == StrategyType.WAIT_AND_REPAIR:
            scope = set(affected_set)
            for wo in snapshot.work_orders:
                for op in wo.operations:
                    if affected_set & set(op.predecessor_ids):
                        scope.add(op.operation_id)
            return scope

        scope = set(affected_set)
        changed = True
        while changed:
            changed = False
            for wo in snapshot.work_orders:
                for op in wo.operations:
                    if op.operation_id in scope:
                        continue
                    if scope & set(op.predecessor_ids):
                        scope.add(op.operation_id)
                        changed = True
        return scope

    @staticmethod
    def _add_precedence_constraints(
        snapshot: ScheduleSnapshot,
        model: cp_model.CpModel,
        starts: dict[str, cp_model.IntVar],
        ends: dict[str, cp_model.IntVar],
    ) -> None:
        for wo in snapshot.work_orders:
            for op in wo.operations:
                if op.operation_id not in starts:
                    continue
                for pred_id in op.predecessor_ids:
                    if pred_id in ends:
                        model.Add(ends[pred_id] <= starts[op.operation_id])

    @staticmethod
    def _add_calendar_blocks(
        snapshot: ScheduleSnapshot,
        model: cp_model.CpModel,
        origin: datetime,
        horizon: int,
        intervals_by_resource: dict[str, list[cp_model.IntervalVar]],
    ) -> None:
        raw = snapshot.raw_data or {}
        for idx, window in enumerate(raw.get("resource_calendar", []) or []):
            if window.get("availability_type", "unavailable") != "unavailable":
                continue
            resource_id = str(window.get("resource_id", ""))
            try:
                start_dt = datetime.fromisoformat(str(window["window_start"]).replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(str(window["window_end"]).replace("Z", "+00:00"))
            except Exception:
                continue
            start = max(0, int((start_dt - origin).total_seconds() // 60))
            end = min(horizon, max(start, int((end_dt - origin).total_seconds() // 60)))
            duration = end - start
            if not resource_id or duration <= 0:
                continue
            intervals_by_resource.setdefault(resource_id, []).append(
                model.NewFixedSizeIntervalVar(
                    start,
                    duration,
                    f"calendar_block_{resource_id}_{idx}",
                )
            )

    @staticmethod
    def _add_changeover_constraints(
        *,
        snapshot: ScheduleSnapshot,
        model: cp_model.CpModel,
        starts: dict[str, cp_model.IntVar],
        ends: dict[str, cp_model.IntVar],
        presences: dict[tuple[str, str], cp_model.IntVar],
        resource_choices: dict[str, list[str]],
    ) -> None:
        setup_lookup = CpSatFjspScheduler._changeover_setup_lookup(snapshot)
        if not setup_lookup:
            return
        family_by_op = CpSatFjspScheduler._operation_family_from_raw(snapshot)
        resource_ids = sorted({rid for resources in resource_choices.values() for rid in resources})

        for resource_id in resource_ids:
            op_ids = [
                op_id
                for op_id, resources in resource_choices.items()
                if resource_id in resources and (op_id, resource_id) in presences
            ]
            if len(op_ids) <= 1:
                continue

            arcs: list[list] = []
            assigned = [presences[(op_id, resource_id)] for op_id in op_ids]
            empty = model.NewBoolVar(f"resched_changeover_empty_{resource_id}")
            model.Add(sum(assigned) == 0).OnlyEnforceIf(empty)
            model.Add(sum(assigned) >= 1).OnlyEnforceIf(empty.Not())
            arcs.append([0, 0, empty])

            node_by_op = {op_id: idx + 1 for idx, op_id in enumerate(op_ids)}
            for op_id, node in node_by_op.items():
                presence = presences[(op_id, resource_id)]
                arcs.append([node, node, presence.Not()])
                arcs.append([0, node, model.NewBoolVar(f"resched_start_{resource_id}_{op_id}")])
                arcs.append([node, 0, model.NewBoolVar(f"resched_end_{resource_id}_{op_id}")])

            for left_id, left_node in node_by_op.items():
                for right_id, right_node in node_by_op.items():
                    if left_id == right_id:
                        continue
                    arc = model.NewBoolVar(f"resched_changeover_{resource_id}_{left_id}_{right_id}")
                    arcs.append([left_node, right_node, arc])
                    setup = CpSatFjspScheduler._setup_minutes(
                        setup_lookup,
                        resource_id,
                        family_by_op.get(left_id, "unknown"),
                        family_by_op.get(right_id, "unknown"),
                    )
                    if setup:
                        model.Add(starts[right_id] >= ends[left_id] + setup).OnlyEnforceIf(arc)

            model.AddCircuit(arcs)

    @staticmethod
    def _changeover_setup_lookup(
        snapshot: ScheduleSnapshot,
    ) -> dict[tuple[str | None, str, str], int]:
        raw = snapshot.raw_data or {}
        result: dict[tuple[str | None, str, str], int] = {}
        for rule in raw.get("changeover_rules", []) or []:
            from_family = str(rule.get("from_product_family", ""))
            to_family = str(rule.get("to_product_family", ""))
            if not from_family or not to_family or from_family == to_family:
                continue
            resource_id_raw = rule.get("resource_id")
            resource_id = str(resource_id_raw) if resource_id_raw else None
            setup = int(rule.get("setup_minutes", 0) or 0)
            key = (resource_id, from_family, to_family)
            result[key] = max(result.get(key, 0), setup)
        return result

    @staticmethod
    def _operation_family_from_raw(snapshot: ScheduleSnapshot) -> dict[str, str]:
        raw = snapshot.raw_data or {}
        result: dict[str, str] = {}
        for wo in raw.get("work_orders", []) or []:
            wo_family = str(wo.get("product_family", "unknown"))
            for op in wo.get("operations", []) or []:
                op_id = op.get("operation_id")
                if op_id:
                    result[str(op_id)] = str(op.get("product_family", wo_family))
        return result

    @staticmethod
    def _setup_minutes(
        lookup: dict[tuple[str | None, str, str], int],
        resource_id: str,
        from_family: str,
        to_family: str,
    ) -> int:
        if from_family == to_family:
            return 0
        return lookup.get(
            (resource_id, from_family, to_family),
            lookup.get((None, from_family, to_family), 0),
        )

    @staticmethod
    def _build_schedule_detail(
        *,
        snapshot: ScheduleSnapshot,
        origin: datetime,
        operation_refs: list[_OperationRef],
        starts: dict[str, cp_model.IntVar],
        ends: dict[str, cp_model.IntVar],
        presences: dict[tuple[str, str], cp_model.IntVar],
        resource_choices: dict[str, list[str]],
        variable_ids: set[str],
        affected_set: set[str],
        solver: cp_model.CpSolver,
    ) -> ScheduleDetail:
        refs_by_id = {ref.operation.operation_id: ref for ref in operation_refs}
        new_work_orders: list[WorkOrder] = []
        for wo in snapshot.work_orders:
            new_ops: list[Operation] = []
            for op in wo.operations:
                ref = refs_by_id[op.operation_id]
                start_minutes = solver.Value(starts[op.operation_id])
                end_minutes = solver.Value(ends[op.operation_id])
                selected_resource = op.resource_id
                for resource_id in resource_choices[op.operation_id]:
                    presence = presences.get((op.operation_id, resource_id))
                    if presence is not None and solver.Value(presence) == 1:
                        selected_resource = resource_id
                        break
                new_op = op.model_copy(deep=True)
                new_op.resource_id = selected_resource
                new_op.start_time = origin + timedelta(minutes=start_minutes)
                new_op.end_time = origin + timedelta(minutes=end_minutes)
                new_op.is_affected = op.operation_id in affected_set
                new_op.is_adjusted = (
                    op.operation_id in variable_ids
                    and (
                        selected_resource != op.resource_id
                        or new_op.start_time != op.start_time
                        or new_op.end_time != op.end_time
                    )
                )
                # Preserve positive durations even if input had rounding issues.
                if new_op.end_time <= new_op.start_time:
                    new_op.end_time = new_op.start_time + timedelta(minutes=ref.duration)
                new_ops.append(new_op)
            new_wo = wo.model_copy(deep=True)
            new_wo.operations = new_ops
            new_work_orders.append(new_wo)

        resources = CpSatFjspScheduler._resources_from_raw(snapshot)
        return ScheduleDetail(work_orders=new_work_orders, resources=resources)

    @staticmethod
    def _resources_from_raw(snapshot: ScheduleSnapshot) -> list[Resource]:
        raw = snapshot.raw_data or {}
        resources: list[Resource] = []
        for res in raw.get("resources", []):
            try:
                resources.append(Resource.model_validate(res))
            except Exception:
                continue
        return resources
