"""CP-SAT backend for flexible job shop rescheduling.

This module provides the first solver-backed detailed scheduling backend.
It models:
- operation precedence
- unary resource no-overlap
- flexible eligible resources through optional intervals
- frozen operations and strategy-specific repair scope
- simple delay lower bounds for directly impacted operations

It is intentionally scoped as a backend service so HybridSolver can keep a
portfolio/fallback structure. Production readiness still depends on customer
constraint coverage, customer-like load tests, and operational acceptance.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ortools.sat.python import cp_model

from app.core.config import settings
from app.models.enums import StrategyType
from app.models.impact import ImpactReport
from app.models.schedule import (
    Operation,
    Resource,
    ScheduleDetail,
    ScheduleSnapshot,
    WorkOrder,
)

logger = logging.getLogger(__name__)
_SOLVER_CAPACITY = threading.BoundedSemaphore(settings.solver.max_concurrent_jobs)

_OBJECTIVE_WEIGHTS: dict[str, dict[str, int]] = {
    "balanced": {
        "shift": 1,
        "makespan": 1,
        "tardiness": 10,
        "urgent_tardiness": 25,
        "urgent_displacement": 1,
    },
    "delivery_priority": {
        "shift": 1,
        "makespan": 2,
        "tardiness": 20,
        "urgent_tardiness": 50,
        "urgent_displacement": 1,
    },
    "stability_priority": {
        "shift": 8,
        "makespan": 1,
        "tardiness": 8,
        "urgent_tardiness": 25,
        "urgent_displacement": 4,
    },
    "bottleneck_priority": {
        "shift": 2,
        "makespan": 5,
        "tardiness": 10,
        "urgent_tardiness": 30,
        "urgent_displacement": 2,
    },
    "cost_priority": {
        "shift": 4,
        "makespan": 2,
        "tardiness": 10,
        "urgent_tardiness": 25,
        "urgent_displacement": 5,
    },
}


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
    best_objective_bound: float | None = None
    relative_gap: float | None = None
    hint_applied: bool = False
    hinted_operation_count: int = 0


@dataclass(frozen=True)
class _OperationRef:
    work_order: WorkOrder
    operation: Operation
    original_start: int
    duration: int
    eligible_resources: list[str]
    duration_by_resource: dict[str, int]


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
        initial_solution: ScheduleDetail | None = None,
        goal_mode: str = "balanced",
    ) -> CpSatScheduleResult:
        acquired = _SOLVER_CAPACITY.acquire(
            timeout=min(
                timeout_seconds,
                settings.solver.queue_timeout_seconds,
            )
        )
        if not acquired:
            return CpSatScheduleResult(
                schedule_detail=None,
                status_name="SOLVER_CAPACITY_EXHAUSTED",
                is_feasible=False,
                solver_log={
                    "max_concurrent_jobs": settings.solver.max_concurrent_jobs,
                    "queue_timeout_seconds": settings.solver.queue_timeout_seconds,
                },
            )
        try:
            return self._solve_with_capacity(
                snapshot=snapshot,
                impact_report=impact_report,
                strategy_type=strategy_type,
                affected_op_ids=affected_op_ids,
                frozen_operation_ids=frozen_operation_ids,
                timeout_seconds=timeout_seconds,
                candidate_index=candidate_index,
                initial_solution=initial_solution,
                goal_mode=goal_mode,
            )
        finally:
            _SOLVER_CAPACITY.release()

    def _solve_with_capacity(
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
        if len(operation_refs) > settings.solver.max_model_operations:
            return CpSatScheduleResult(
                schedule_detail=None,
                status_name="INSTANCE_REQUIRES_DECOMPOSITION",
                is_feasible=False,
                solver_log={
                    "operation_count": len(operation_refs),
                    "max_model_operations": settings.solver.max_model_operations,
                    "required_action": "run_bounded_subgraph_or_decomposition_solver",
                },
            )

        governance_blockers = self._strict_governance_blockers(snapshot, operation_refs)
        if governance_blockers:
            return CpSatScheduleResult(
                schedule_detail=None,
                status_name="GOVERNANCE_CONSTRAINT_BLOCKED",
                is_feasible=False,
                solver_log={
                    "blockers": governance_blockers,
                    "constraint_families": [
                        "qms_release",
                        "batch_genealogy",
                        "buffer_capacity",
                    ],
                },
            )

        affected_set = set(affected_op_ids)
        variable_ids = self._repair_scope(snapshot, strategy_type, affected_set)
        quality_frozen_ids = self._quality_frozen_operation_ids(snapshot)
        variable_ids -= set(frozen_operation_ids) | quality_frozen_ids
        frozen_ids = set(frozen_operation_ids) | quality_frozen_ids
        delay_by_op = self._delay_by_operation(impact_report)
        material_available_by_op = self._material_available_offsets(snapshot, origin)
        quality_release_by_op = self._quality_release_offsets(snapshot, origin)
        tooling_by_op = self._tooling_requirements(snapshot)
        skill_by_op = self._skill_requirements(snapshot)
        urgent_by_work_order = self._urgent_constraint_by_work_order(snapshot, origin)
        urgent_work_order_ids = set(urgent_by_work_order)
        objective_weights = _OBJECTIVE_WEIGHTS.get(
            goal_mode, _OBJECTIVE_WEIGHTS["balanced"]
        )

        horizon = self._horizon_minutes(snapshot, origin, delay_by_op)
        model = cp_model.CpModel()

        starts: dict[str, cp_model.IntVar] = {}
        ends: dict[str, cp_model.IntVar] = {}
        presences: dict[tuple[str, str], cp_model.IntVar] = {}
        intervals_by_resource: dict[str, list[cp_model.IntervalVar]] = {}
        intervals_by_tooling: dict[str, list[cp_model.IntervalVar]] = {}
        intervals_by_skill: dict[str, list[cp_model.IntervalVar]] = {}
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
            if is_variable:
                lower_bound = (
                    0
                    if op.work_order_id in urgent_work_order_ids
                    else ref.original_start
                )
                if op_id in affected_set:
                    lower_bound += delay_by_op.get(op_id, 0)
                lower_bound = max(lower_bound, material_available_by_op.get(op_id, 0))
                lower_bound = max(lower_bound, quality_release_by_op.get(op_id, 0))
                model.Add(start >= lower_bound + candidate_index * 5)
            else:
                model.Add(start == ref.original_start)

            presence_vars: list[cp_model.IntVar] = []
            for resource_id in resources:
                duration = ref.duration_by_resource.get(resource_id, ref.duration)
                presence = model.NewBoolVar(f"use_{op_id}_{resource_id}")
                model.Add(end == start + duration).OnlyEnforceIf(presence)
                interval = model.NewOptionalIntervalVar(
                    start,
                    duration,
                    end,
                    presence,
                    f"interval_{op_id}_{resource_id}",
                )
                presences[(op_id, resource_id)] = presence
                presence_vars.append(presence)
                intervals_by_resource.setdefault(resource_id, []).append(interval)
                if not resource_id.startswith("OUTSOURCE:"):
                    for tooling_id in tooling_by_op.get(op_id, []):
                        intervals_by_tooling.setdefault(tooling_id, []).append(
                            model.NewOptionalIntervalVar(
                                start,
                                duration,
                                end,
                                presence,
                                f"tooling_{op_id}_{resource_id}_{tooling_id}",
                            )
                        )
                    for skill_code in skill_by_op.get(op_id, []):
                        intervals_by_skill.setdefault(skill_code, []).append(
                            model.NewOptionalIntervalVar(
                                start,
                                duration,
                                end,
                                presence,
                                f"skill_{op_id}_{resource_id}_{skill_code}",
                            )
                        )

            model.AddExactlyOne(presence_vars)
            if not is_variable:
                model.Add(presence_vars[0] == 1)

        self._add_precedence_constraints(snapshot, model, starts, ends)
        self._add_operation_release_constraints(snapshot, model, origin, starts)
        self._add_operation_deadline_constraints(snapshot, model, origin, ends)
        self._add_transport_constraints(snapshot, model, starts, ends)
        self._add_buffer_capacity_constraints(snapshot, model, horizon, starts, ends)
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
        self._add_tooling_capacity_constraints(
            snapshot,
            model,
            origin,
            horizon,
            intervals_by_tooling,
        )
        self._add_labor_skill_capacity_constraints(
            snapshot,
            model,
            origin,
            horizon,
            intervals_by_skill,
        )
        self._add_outsourcing_capacity_constraints(snapshot, model, presences)

        for intervals in intervals_by_resource.values():
            if intervals:
                model.AddNoOverlap(intervals)

        objective_terms: list[cp_model.LinearExpr] = []
        for op_id in variable_ids:
            if op_id in starts:
                shift = model.NewIntVar(0, horizon, f"shift_{op_id}")
                model.AddAbsEquality(shift, starts[op_id] - start_offsets[op_id])
                objective_terms.append(shift * objective_weights["shift"])

        makespan = model.NewIntVar(0, horizon, "makespan")
        model.AddMaxEquality(makespan, list(ends.values()))
        objective_terms.append(makespan * objective_weights["makespan"])

        for wo in snapshot.work_orders:
            wo_end_vars = [
                ends[op.operation_id] for op in wo.operations if op.operation_id in ends
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
            objective_terms.append(
                tardiness * priority_weight * objective_weights["tardiness"]
            )
            urgent = urgent_by_work_order.get(wo.work_order_id)
            if urgent:
                urgent_due, priority_boost, displacement_cost = urgent
                urgent_tardiness = model.NewIntVar(
                    0,
                    horizon,
                    f"urgent_tardiness_{wo.work_order_id}",
                )
                model.Add(urgent_tardiness >= completion - urgent_due)
                model.Add(urgent_tardiness >= 0)
                objective_terms.append(
                    urgent_tardiness
                    * max(1, priority_boost)
                    * objective_weights["urgent_tardiness"]
                )
                for op in wo.operations:
                    if op.operation_id in starts and op.operation_id in variable_ids:
                        displacement = model.NewIntVar(
                            0,
                            horizon,
                            f"urgent_displacement_{op.operation_id}",
                        )
                        model.Add(
                            displacement
                            >= starts[op.operation_id] - start_offsets[op.operation_id]
                        )
                        model.Add(displacement >= 0)
                        objective_terms.append(
                            displacement
                            * max(0, displacement_cost)
                            * objective_weights["urgent_displacement"]
                        )

        model.Minimize(sum(objective_terms))

        hinted_operation_count = self._apply_solution_hint(
            model=model,
            initial_solution=initial_solution,
            origin=origin,
            horizon=horizon,
            starts=starts,
            ends=ends,
            presences=presences,
            resource_choices=resource_choices,
        )

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(0.1, min(timeout_seconds, 30.0))
        solver.parameters.num_search_workers = settings.solver.cp_sat_workers
        solver.parameters.random_seed = 17 + candidate_index
        status = solver.Solve(model)
        status_name = solver.StatusName(status)
        is_feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        if not is_feasible:
            logger.info(
                "CP-SAT returned %s for snapshot %s", status_name, snapshot.snapshot_id
            )
            return CpSatScheduleResult(
                schedule_detail=None,
                status_name=status_name,
                is_feasible=False,
                wall_time_seconds=solver.WallTime(),
                branches=solver.NumBranches(),
                conflicts=solver.NumConflicts(),
                variable_operation_ids=sorted(variable_ids),
                best_objective_bound=solver.BestObjectiveBound(),
                hint_applied=hinted_operation_count > 0,
                hinted_operation_count=hinted_operation_count,
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

        objective_value = solver.ObjectiveValue()
        best_objective_bound = solver.BestObjectiveBound()
        relative_gap = abs(objective_value - best_objective_bound) / max(
            1.0, abs(objective_value)
        )
        return CpSatScheduleResult(
            schedule_detail=schedule_detail,
            status_name=status_name,
            is_feasible=True,
            objective_value=objective_value,
            wall_time_seconds=solver.WallTime(),
            branches=solver.NumBranches(),
            conflicts=solver.NumConflicts(),
            variable_operation_ids=sorted(variable_ids),
            best_objective_bound=best_objective_bound,
            relative_gap=relative_gap,
            hint_applied=hinted_operation_count > 0,
            hinted_operation_count=hinted_operation_count,
            solver_log={
                "horizon_minutes": horizon,
                "operation_count": len(operation_refs),
                "resource_count": len(intervals_by_resource),
                "candidate_index": candidate_index,
                "goal_mode": goal_mode,
                "objective_weights": objective_weights,
                "hint_applied": hinted_operation_count > 0,
                "hinted_operation_count": hinted_operation_count,
                "best_objective_bound": best_objective_bound,
                "relative_gap": relative_gap,
                "constraint_families": self._modeled_constraint_families(snapshot),
                "selected_outsource_operations": [
                    op.operation_id
                    for wo in schedule_detail.work_orders
                    for op in wo.operations
                    if op.resource_id.startswith("OUTSOURCE:")
                ],
                "approved_substitute_operations": sorted(
                    self._approved_substitute_operation_ids(snapshot)
                ),
            },
        )

    @staticmethod
    def _apply_solution_hint(
        *,
        model: cp_model.CpModel,
        initial_solution: ScheduleDetail | None,
        origin: datetime,
        horizon: int,
        starts: dict[str, cp_model.IntVar],
        ends: dict[str, cp_model.IntVar],
        presences: dict[tuple[str, str], cp_model.IntVar],
        resource_choices: dict[str, list[str]],
    ) -> int:
        if initial_solution is None:
            return 0
        hinted = 0
        for work_order in initial_solution.work_orders:
            for operation in work_order.operations:
                operation_id = operation.operation_id
                if operation_id not in starts or operation_id not in ends:
                    continue
                choices = resource_choices.get(operation_id, [])
                if operation.resource_id not in choices:
                    continue
                start = int((operation.start_time - origin).total_seconds() // 60)
                end = int((operation.end_time - origin).total_seconds() // 60)
                if start < 0 or end <= start or end > horizon:
                    continue
                model.add_hint(starts[operation_id], start)
                model.add_hint(ends[operation_id], end)
                for resource_id in choices:
                    presence = presences.get((operation_id, resource_id))
                    if presence is not None:
                        model.add_hint(
                            presence,
                            int(resource_id == operation.resource_id),
                        )
                hinted += 1
        return hinted

    # ── Model preparation ──────────────────────────────────────────

    @staticmethod
    def _time_origin(snapshot: ScheduleSnapshot) -> datetime:
        starts = [op.start_time for wo in snapshot.work_orders for op in wo.operations]
        starts.append(snapshot.captured_at)
        return min(starts)

    def _collect_operation_refs(
        self, snapshot: ScheduleSnapshot, origin: datetime
    ) -> list[_OperationRef]:
        eligible_by_op = self._eligible_resources_from_raw(snapshot)
        outsource_duration_by_op = self._approved_outsourcing_durations(snapshot)
        refs: list[_OperationRef] = []
        for wo in snapshot.work_orders:
            for op in wo.operations:
                start = int((op.start_time - origin).total_seconds() // 60)
                duration = max(
                    1, int((op.end_time - op.start_time).total_seconds() // 60)
                )
                eligible = eligible_by_op.get(op.operation_id)
                if not eligible:
                    eligible = self._eligible_by_capability(snapshot, op)
                if op.resource_id not in eligible:
                    eligible.insert(0, op.resource_id)
                duration_by_resource = {resource_id: duration for resource_id in eligible}
                for resource_id, outsource_duration in outsource_duration_by_op.get(
                    op.operation_id, {}
                ).items():
                    if resource_id not in eligible:
                        eligible.append(resource_id)
                    duration_by_resource[resource_id] = outsource_duration
                refs.append(
                    _OperationRef(
                        work_order=wo,
                        operation=op,
                        original_start=start,
                        duration=duration,
                        eligible_resources=list(dict.fromkeys(eligible)),
                        duration_by_resource=duration_by_resource,
                    )
                )
        return refs

    @staticmethod
    def _eligible_resources_from_raw(
        snapshot: ScheduleSnapshot,
    ) -> dict[str, list[str]]:
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
    def _approved_outsourcing_durations(
        snapshot: ScheduleSnapshot,
    ) -> dict[str, dict[str, int]]:
        raw = snapshot.raw_data or {}
        result: dict[str, dict[str, int]] = {}
        for row in raw.get("outsourcing_approvals", []) or []:
            if str(row.get("approval_status", "pending")).lower() != "approved":
                continue
            if not row.get("approved_by") or not row.get("source_ref"):
                continue
            valid_until = row.get("valid_until")
            if valid_until:
                try:
                    expiry = (
                        valid_until
                        if isinstance(valid_until, datetime)
                        else datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
                    )
                    if expiry < snapshot.captured_at:
                        continue
                except Exception:
                    continue
            vendor_id = str(row.get("vendor_id", ""))
            if not vendor_id:
                continue
            resource_id = str(row.get("resource_id") or f"OUTSOURCE:{vendor_id}")
            lead_time = max(1, int(row.get("lead_time_minutes", 0) or 0))
            for op_id in row.get("operation_ids", []) or []:
                result.setdefault(str(op_id), {})[resource_id] = lead_time
        return result

    @staticmethod
    def _approved_substitute_operation_ids(snapshot: ScheduleSnapshot) -> set[str]:
        raw = snapshot.raw_data or {}
        result: set[str] = set()
        for row in raw.get("substitute_material_approvals", []) or []:
            if str(row.get("approval_status", "pending")).lower() != "approved":
                continue
            if not row.get("approved_by") or not row.get("source_ref"):
                continue
            if float(row.get("available_quantity", 0) or 0) < float(
                row.get("required_quantity", 1) or 1
            ):
                continue
            result.update(str(item) for item in row.get("operation_ids", []) or [])
        return result

    @staticmethod
    def _strict_governance_blockers(
        snapshot: ScheduleSnapshot,
        operation_refs: list[_OperationRef],
    ) -> list[str]:
        raw = snapshot.raw_data or {}
        relevant_ids = {ref.operation.operation_id for ref in operation_refs}
        blockers: list[str] = []

        batch_ops: dict[str, set[str]] = {}
        for row in raw.get("batch_genealogy", []) or []:
            batch_id = str(row.get("batch_id", ""))
            operation_ids = {
                str(item) for item in row.get("operation_ids", []) or []
            } & relevant_ids
            if batch_id:
                batch_ops[batch_id] = operation_ids
            quality_state = str(row.get("quality_state", "released")).lower()
            if operation_ids and quality_state not in {"released", "cleared", "closed"}:
                blockers.append(f"batch_not_released:{batch_id or 'unknown'}")
            if row.get("rework_required") and not row.get("rework_operation_id"):
                blockers.append(f"missing_rework_operation:{batch_id or 'unknown'}")

        for row in raw.get("qms_release_gates", []) or []:
            operation_ids = {
                str(item) for item in row.get("operation_ids", []) or []
            }
            for batch_id in row.get("batch_ids", []) or []:
                operation_ids.update(batch_ops.get(str(batch_id), set()))
            if not (operation_ids & relevant_ids):
                continue
            gate_id = str(row.get("gate_id", "unknown"))
            status = str(row.get("status", "pending")).lower()
            if status not in {"released", "cleared", "closed"}:
                blockers.append(f"qms_gate_not_released:{gate_id}")
                continue
            required = {str(item) for item in row.get("required_approvals", []) or []}
            approvals = {str(item) for item in row.get("approvals", []) or []}
            if not required.issubset(approvals):
                blockers.append(f"qms_approval_missing:{gate_id}")
            if not row.get("certificate_ref") or not row.get("source_ref"):
                blockers.append(f"qms_evidence_missing:{gate_id}")

        for row in raw.get("buffer_flows", []) or []:
            if int(row.get("current_wip", 0) or 0) > int(row.get("capacity", 0) or 0):
                blockers.append(f"buffer_already_over_capacity:{row.get('buffer_id', 'unknown')}")
        return sorted(set(blockers))

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
        approved_substitutes: dict[str, list[dict[str, Any]]] = {}
        for row in raw.get("substitute_material_approvals", []) or []:
            if str(row.get("approval_status", "pending")).lower() != "approved":
                continue
            if not row.get("approved_by") or not row.get("source_ref"):
                continue
            for op_id in row.get("operation_ids", []) or []:
                approved_substitutes.setdefault(str(op_id), []).append(row)
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
                            dt = datetime.fromisoformat(
                                str(available_at).replace("Z", "+00:00")
                            )
                        latest = max(latest, int((dt - origin).total_seconds() // 60))
                    except Exception:
                        continue
                if latest > 0:
                    result[str(op_id)] = latest
        for row in raw.get("material_availability", []) or []:
            operation_ids = [str(item) for item in row.get("operation_ids", []) or []]
            if not operation_ids:
                continue
            shortage = float(row.get("available_quantity", 0) or 0) < float(
                row.get("required_quantity", 1) or 1
            )
            for op_id in operation_ids:
                if shortage:
                    substitutes = [
                        item
                        for item in approved_substitutes.get(op_id, [])
                        if float(item.get("available_quantity", 0) or 0)
                        >= float(item.get("required_quantity", 1) or 1)
                    ]
                    offset = (
                        min(
                            _datetime_offset_minutes(item.get("available_at"), origin)
                            for item in substitutes
                        )
                        if substitutes
                        else 1_000_000
                    )
                else:
                    offset = _datetime_offset_minutes(row.get("available_at"), origin)
                result[op_id] = max(result.get(op_id, 0), offset)
        return result

    @staticmethod
    def _quality_frozen_operation_ids(snapshot: ScheduleSnapshot) -> set[str]:
        raw = snapshot.raw_data or {}
        frozen: set[str] = set()
        for row in raw.get("quality_holds", []) or []:
            status = str(row.get("status", "held")).lower()
            if status in {"released", "cleared", "closed"}:
                continue
            frozen.update(
                str(item) for item in row.get("blocked_operation_ids", []) or []
            )
        return frozen

    @staticmethod
    def _quality_release_offsets(
        snapshot: ScheduleSnapshot,
        origin: datetime,
    ) -> dict[str, int]:
        raw = snapshot.raw_data or {}
        result: dict[str, int] = {}
        for row in raw.get("quality_holds", []) or []:
            status = str(row.get("status", "held")).lower()
            if status not in {"released", "cleared", "closed"}:
                continue
            offset = _datetime_offset_minutes(row.get("release_at"), origin)
            for op_id in row.get("blocked_operation_ids", []) or []:
                result[str(op_id)] = max(result.get(str(op_id), 0), offset)
        for row in raw.get("qms_release_gates", []) or []:
            if str(row.get("status", "pending")).lower() not in {
                "released",
                "cleared",
                "closed",
            }:
                continue
            offset = _datetime_offset_minutes(row.get("release_at"), origin)
            for op_id in row.get("operation_ids", []) or []:
                result[str(op_id)] = max(result.get(str(op_id), 0), offset)
        for row in raw.get("batch_genealogy", []) or []:
            if str(row.get("quality_state", "released")).lower() not in {
                "released",
                "cleared",
                "closed",
            }:
                continue
            offset = _datetime_offset_minutes(row.get("release_at"), origin)
            for op_id in row.get("operation_ids", []) or []:
                result[str(op_id)] = max(result.get(str(op_id), 0), offset)
        return result

    @staticmethod
    def _tooling_requirements(snapshot: ScheduleSnapshot) -> dict[str, list[str]]:
        raw = snapshot.raw_data or {}
        result: dict[str, list[str]] = {}
        for wo in raw.get("work_orders", []) or []:
            for op in wo.get("operations", []) or []:
                op_id = op.get("operation_id")
                if not op_id:
                    continue
                payload = op.get("raw_payload", {}) or {}
                tooling = (
                    payload.get("required_tooling_ids")
                    or payload.get("tooling_ids")
                    or []
                )
                values = _as_list(tooling)
                if values:
                    result[str(op_id)] = values
        for row in raw.get("tooling_calendar", []) or []:
            tooling_id = str(row.get("tooling_id", ""))
            if not tooling_id:
                continue
            for op_id in row.get("operation_ids", []) or []:
                result.setdefault(str(op_id), [])
                if tooling_id not in result[str(op_id)]:
                    result[str(op_id)].append(tooling_id)
        return result

    @staticmethod
    def _skill_requirements(snapshot: ScheduleSnapshot) -> dict[str, list[str]]:
        raw = snapshot.raw_data or {}
        result: dict[str, list[str]] = {}
        for wo in raw.get("work_orders", []) or []:
            for op in wo.get("operations", []) or []:
                op_id = op.get("operation_id")
                if not op_id:
                    continue
                payload = op.get("raw_payload", {}) or {}
                skills = (
                    payload.get("required_skill_codes")
                    or payload.get("skill_codes")
                    or []
                )
                values = _as_list(skills)
                if values:
                    result[str(op_id)] = values
        for row in raw.get("labor_skill_capacity", []) or []:
            skill_code = str(row.get("skill_code", ""))
            if not skill_code:
                continue
            for op_id in row.get("operation_ids", []) or []:
                result.setdefault(str(op_id), [])
                if skill_code not in result[str(op_id)]:
                    result[str(op_id)].append(skill_code)
        return result

    @staticmethod
    def _horizon_minutes(
        snapshot: ScheduleSnapshot, origin: datetime, delay_by_op: dict[str, int]
    ) -> int:
        max_end = max(
            op.end_time for wo in snapshot.work_orders for op in wo.operations
        )
        baseline = int((max_end - origin).total_seconds() // 60)
        total_duration = sum(
            max(1, int((op.end_time - op.start_time).total_seconds() // 60))
            for wo in snapshot.work_orders
            for op in wo.operations
        )
        raw = snapshot.raw_data or {}
        outsource_lead = max(
            [
                int(row.get("lead_time_minutes", 0) or 0)
                for row in raw.get("outsourcing_approvals", []) or []
            ]
            or [0]
        )
        transport_lag = sum(
            int(row.get("eta_minutes", 0) or 0)
            for row in raw.get("transport_lanes", []) or []
        )
        return max(
            baseline + sum(delay_by_op.values()) + outsource_lead + transport_lag + 240,
            total_duration * 2 + outsource_lead + transport_lag + 240,
        )

    @staticmethod
    def _repair_scope(
        snapshot: ScheduleSnapshot,
        strategy_type: StrategyType,
        affected_set: set[str],
    ) -> set[str]:
        if strategy_type == StrategyType.GLOBAL_RESCHEDULE:
            return {
                op.operation_id for wo in snapshot.work_orders for op in wo.operations
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
        raw = snapshot.raw_data or {}
        for row in raw.get("batch_genealogy", []) or []:
            child_ids = [
                str(item) for item in row.get("operation_ids", []) or [] if str(item) in starts
            ]
            parent_ids = [
                str(item)
                for item in row.get("parent_operation_ids", []) or []
                if str(item) in ends
            ]
            rework_id = row.get("rework_operation_id")
            if row.get("rework_required") and rework_id and str(rework_id) in ends:
                parent_ids.append(str(rework_id))
            for child_id in child_ids:
                for parent_id in parent_ids:
                    if child_id != parent_id:
                        model.Add(ends[parent_id] <= starts[child_id])

    @staticmethod
    def _add_operation_release_constraints(
        snapshot: ScheduleSnapshot,
        model: cp_model.CpModel,
        origin: datetime,
        starts: dict[str, cp_model.IntVar],
    ) -> None:
        raw = snapshot.raw_data or {}
        for row in raw.get("operation_release_constraints", []) or []:
            op_id = str(row.get("operation_id", ""))
            if op_id in starts:
                model.Add(
                    starts[op_id]
                    >= _datetime_offset_minutes(row.get("release_at"), origin)
                )

    @staticmethod
    def _add_operation_deadline_constraints(
        snapshot: ScheduleSnapshot,
        model: cp_model.CpModel,
        origin: datetime,
        ends: dict[str, cp_model.IntVar],
    ) -> None:
        raw = snapshot.raw_data or {}
        for row in raw.get("operation_deadline_constraints", []) or []:
            op_id = str(row.get("operation_id", ""))
            if op_id in ends:
                model.Add(
                    ends[op_id]
                    <= _datetime_offset_minutes(row.get("deadline_at"), origin)
                )

    @staticmethod
    def _add_transport_constraints(
        snapshot: ScheduleSnapshot,
        model: cp_model.CpModel,
        starts: dict[str, cp_model.IntVar],
        ends: dict[str, cp_model.IntVar],
    ) -> None:
        raw = snapshot.raw_data or {}
        intervals_by_lane: dict[str, list[cp_model.IntervalVar]] = {}
        capacity_by_lane: dict[str, int] = {}
        for idx, row in enumerate(raw.get("transport_lanes", []) or []):
            pred_id = str(row.get("predecessor_operation_id", ""))
            succ_id = str(row.get("successor_operation_id", ""))
            if pred_id not in ends or succ_id not in starts:
                continue
            lane_id = str(row.get("lane_id", "unmapped"))
            eta = max(0, int(row.get("eta_minutes", 0) or 0))
            capacity_by_lane[lane_id] = max(1, int(row.get("capacity", 1) or 1))
            if eta == 0:
                model.Add(starts[succ_id] >= ends[pred_id])
                continue
            transport_end = model.NewIntVar(0, 10_000_000, f"transport_end_{idx}")
            model.Add(transport_end == ends[pred_id] + eta)
            model.Add(starts[succ_id] >= transport_end)
            intervals_by_lane.setdefault(lane_id, []).append(
                model.NewIntervalVar(
                    ends[pred_id],
                    eta,
                    transport_end,
                    f"transport_{lane_id}_{idx}",
                )
            )
        for lane_id, intervals in intervals_by_lane.items():
            model.AddCumulative(
                intervals,
                [1 for _ in intervals],
                capacity_by_lane[lane_id],
            )

    @staticmethod
    def _add_buffer_capacity_constraints(
        snapshot: ScheduleSnapshot,
        model: cp_model.CpModel,
        horizon: int,
        starts: dict[str, cp_model.IntVar],
        ends: dict[str, cp_model.IntVar],
    ) -> None:
        raw = snapshot.raw_data or {}
        grouped: dict[str, dict[str, Any]] = {}
        for idx, row in enumerate(raw.get("buffer_flows", []) or []):
            pred_id = str(row.get("predecessor_operation_id", ""))
            succ_id = str(row.get("successor_operation_id", ""))
            if pred_id not in ends or succ_id not in starts:
                continue
            buffer_id = str(row.get("buffer_id", "unmapped"))
            capacity = max(1, int(row.get("capacity", 1) or 1))
            current_wip = max(0, int(row.get("current_wip", 0) or 0))
            occupancy = max(1, int(row.get("occupancy_quantity", 1) or 1))
            record = grouped.setdefault(
                buffer_id,
                {
                    "capacity": capacity,
                    "current_wip": current_wip,
                    "intervals": [],
                    "demands": [],
                },
            )
            record["capacity"] = min(record["capacity"], capacity)
            record["current_wip"] = max(record["current_wip"], current_wip)
            occupancy_duration = model.NewIntVar(0, horizon, f"buffer_wait_{idx}")
            model.Add(occupancy_duration == starts[succ_id] - ends[pred_id])
            record["intervals"].append(
                model.NewIntervalVar(
                    ends[pred_id],
                    occupancy_duration,
                    starts[succ_id],
                    f"buffer_{buffer_id}_{idx}",
                )
            )
            record["demands"].append(occupancy)

        for buffer_id, record in grouped.items():
            intervals = list(record["intervals"])
            demands = list(record["demands"])
            current_wip = int(record["current_wip"])
            if current_wip:
                intervals.append(
                    model.NewFixedSizeIntervalVar(
                        0,
                        horizon,
                        f"buffer_existing_wip_{buffer_id}",
                    )
                )
                demands.append(current_wip)
            model.AddCumulative(intervals, demands, int(record["capacity"]))

    @staticmethod
    def _add_outsourcing_capacity_constraints(
        snapshot: ScheduleSnapshot,
        model: cp_model.CpModel,
        presences: dict[tuple[str, str], cp_model.IntVar],
    ) -> None:
        raw = snapshot.raw_data or {}
        by_resource: dict[str, dict[str, Any]] = {}
        for row in raw.get("outsourcing_approvals", []) or []:
            if str(row.get("approval_status", "pending")).lower() != "approved":
                continue
            if not row.get("approved_by") or not row.get("source_ref"):
                continue
            resource_id = str(
                row.get("resource_id") or f"OUTSOURCE:{row.get('vendor_id', '')}"
            )
            item = by_resource.setdefault(
                resource_id,
                {"capacity": int(row.get("capacity_per_day", 1) or 1), "ops": set()},
            )
            item["capacity"] = min(
                int(item["capacity"]), int(row.get("capacity_per_day", 1) or 1)
            )
            item["ops"].update(str(op_id) for op_id in row.get("operation_ids", []) or [])
        for resource_id, item in by_resource.items():
            usage = [
                presences[(op_id, resource_id)]
                for op_id in item["ops"]
                if (op_id, resource_id) in presences
            ]
            if usage:
                model.Add(sum(usage) <= max(1, int(item["capacity"])))

    @staticmethod
    def _modeled_constraint_families(snapshot: ScheduleSnapshot) -> list[str]:
        raw = snapshot.raw_data or {}
        mapping = {
            "material_availability": "material_availability",
            "substitute_material_approvals": "substitute_material_approval",
            "quality_holds": "quality_hold",
            "qms_release_gates": "qms_release",
            "batch_genealogy": "batch_genealogy",
            "tooling_calendar": "tooling_capacity",
            "labor_skill_capacity": "labor_skill_capacity",
            "transport_lanes": "transport_amr_capacity",
            "buffer_flows": "buffer_capacity",
            "outsourcing_approvals": "outsourcing_approval_capacity",
            "changeover_rules": "changeover",
            "urgent_order_constraints": "urgent_order",
            "resource_calendar": "resource_calendar",
        }
        families = ["precedence", "resource_no_overlap"]
        families.extend(value for key, value in mapping.items() if raw.get(key))
        return families

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
                start_dt = datetime.fromisoformat(
                    str(window["window_start"]).replace("Z", "+00:00")
                )
                end_dt = datetime.fromisoformat(
                    str(window["window_end"]).replace("Z", "+00:00")
                )
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
        resource_ids = sorted(
            {rid for resources in resource_choices.values() for rid in resources}
        )

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
                arcs.append(
                    [0, node, model.NewBoolVar(f"resched_start_{resource_id}_{op_id}")]
                )
                arcs.append(
                    [node, 0, model.NewBoolVar(f"resched_end_{resource_id}_{op_id}")]
                )

            for left_id, left_node in node_by_op.items():
                for right_id, right_node in node_by_op.items():
                    if left_id == right_id:
                        continue
                    arc = model.NewBoolVar(
                        f"resched_changeover_{resource_id}_{left_id}_{right_id}"
                    )
                    arcs.append([left_node, right_node, arc])
                    setup = CpSatFjspScheduler._setup_minutes(
                        setup_lookup,
                        resource_id,
                        family_by_op.get(left_id, "unknown"),
                        family_by_op.get(right_id, "unknown"),
                    )
                    if setup:
                        model.Add(
                            starts[right_id] >= ends[left_id] + setup
                        ).OnlyEnforceIf(arc)

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
    def _add_tooling_capacity_constraints(
        snapshot: ScheduleSnapshot,
        model: cp_model.CpModel,
        origin: datetime,
        horizon: int,
        intervals_by_tooling: dict[str, list[cp_model.IntervalVar]],
    ) -> None:
        if not intervals_by_tooling:
            return
        raw = snapshot.raw_data or {}
        quantity_by_tooling: dict[str, int] = {
            tooling_id: 1 for tooling_id in intervals_by_tooling
        }
        unavailable: dict[str, list[tuple[int, int]]] = {}
        for row in raw.get("tooling_calendar", []) or []:
            tooling_id = str(row.get("tooling_id", ""))
            if not tooling_id:
                continue
            quantity_by_tooling[tooling_id] = max(
                quantity_by_tooling.get(tooling_id, 1),
                int(row.get("quantity", 1) or 0),
            )
            start = _datetime_offset_minutes(row.get("unavailable_start"), origin)
            end = _datetime_offset_minutes(row.get("unavailable_end"), origin)
            if end > start:
                unavailable.setdefault(tooling_id, []).append(
                    (start, min(end, horizon))
                )

        for tooling_id, intervals in intervals_by_tooling.items():
            capacity = max(0, quantity_by_tooling.get(tooling_id, 1))
            demands = [1 for _ in intervals]
            all_intervals = list(intervals)
            all_demands = list(demands)
            for idx, (start, end) in enumerate(unavailable.get(tooling_id, [])):
                duration = end - start
                if duration <= 0 or capacity <= 0:
                    continue
                all_intervals.append(
                    model.NewFixedSizeIntervalVar(
                        max(0, start),
                        duration,
                        f"tooling_unavailable_{tooling_id}_{idx}",
                    )
                )
                all_demands.append(capacity)
            if capacity <= 0:
                for interval in intervals:
                    model.AddNoOverlap([interval])
                model.Add(0 == 1)
            else:
                model.AddCumulative(all_intervals, all_demands, capacity)

    @staticmethod
    def _add_labor_skill_capacity_constraints(
        snapshot: ScheduleSnapshot,
        model: cp_model.CpModel,
        origin: datetime,
        horizon: int,
        intervals_by_skill: dict[str, list[cp_model.IntervalVar]],
    ) -> None:
        if not intervals_by_skill:
            return
        raw = snapshot.raw_data or {}
        windows_by_skill: dict[str, list[tuple[int, int, int]]] = {}
        max_capacity_by_skill: dict[str, int] = {
            skill_code: 1 for skill_code in intervals_by_skill
        }
        for row in raw.get("labor_skill_capacity", []) or []:
            skill_code = str(row.get("skill_code", ""))
            if not skill_code:
                continue
            capacity = int(row.get("available_headcount", 0) or 0)
            max_capacity_by_skill[skill_code] = max(
                max_capacity_by_skill.get(skill_code, 1),
                capacity,
            )
            start = _datetime_offset_minutes(row.get("window_start"), origin)
            end = _datetime_offset_minutes(row.get("window_end"), origin)
            if end > start:
                windows_by_skill.setdefault(skill_code, []).append(
                    (max(0, start), min(end, horizon), capacity)
                )

        for skill_code, intervals in intervals_by_skill.items():
            max_capacity = max(0, max_capacity_by_skill.get(skill_code, 1))
            all_intervals = list(intervals)
            all_demands = [1 for _ in intervals]
            for idx, (start, end, capacity) in enumerate(
                windows_by_skill.get(skill_code, [])
            ):
                blocked_capacity = max(0, max_capacity - capacity)
                if blocked_capacity <= 0:
                    continue
                all_intervals.append(
                    model.NewFixedSizeIntervalVar(
                        start,
                        end - start,
                        f"skill_capacity_block_{skill_code}_{idx}",
                    )
                )
                all_demands.append(blocked_capacity)
            if max_capacity <= 0:
                model.Add(0 == 1)
            else:
                model.AddCumulative(all_intervals, all_demands, max_capacity)

    @staticmethod
    def _urgent_constraint_by_work_order(
        snapshot: ScheduleSnapshot,
        origin: datetime,
    ) -> dict[str, tuple[int, int, int]]:
        raw = snapshot.raw_data or {}
        result: dict[str, tuple[int, int, int]] = {}
        for row in raw.get("urgent_order_constraints", []) or []:
            if not row.get("customer_service_approved"):
                continue
            work_order_id = str(row.get("work_order_id", ""))
            if not work_order_id:
                continue
            result[work_order_id] = (
                _datetime_offset_minutes(row.get("due_time"), origin),
                int(row.get("priority_boost", 5) or 5),
                int(row.get("displacement_cost_per_minute", 1) or 1),
            )
        return result

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
                new_op.is_affected = op.is_affected or op.operation_id in affected_set
                new_op.is_adjusted = op.is_adjusted or (
                    op.operation_id in variable_ids
                    and (
                        selected_resource != op.resource_id
                        or new_op.start_time != op.start_time
                        or new_op.end_time != op.end_time
                    )
                )
                # Preserve positive durations even if input had rounding issues.
                if new_op.end_time <= new_op.start_time:
                    new_op.end_time = new_op.start_time + timedelta(
                        minutes=ref.duration
                    )
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
        existing = {resource.resource_id for resource in resources}
        required_by_op = {
            op.operation_id: list(op.required_capabilities)
            for wo in snapshot.work_orders
            for op in wo.operations
        }
        for row in raw.get("outsourcing_approvals", []) or []:
            if str(row.get("approval_status", "pending")).lower() != "approved":
                continue
            if not row.get("approved_by") or not row.get("source_ref"):
                continue
            vendor_id = str(row.get("vendor_id", "unknown"))
            resource_id = str(row.get("resource_id") or f"OUTSOURCE:{vendor_id}")
            if resource_id in existing:
                continue
            capabilities = {
                str(item) for item in row.get("capability_codes", []) or []
            }
            for op_id in row.get("operation_ids", []) or []:
                capabilities.update(required_by_op.get(str(op_id), []))
            resources.append(
                Resource(
                    resource_id=resource_id,
                    name=f"Approved outsource {vendor_id}",
                    capabilities=sorted(capabilities),
                    criticality="external_approved",
                )
            )
            existing.add(resource_id)
        return resources


def _datetime_offset_minutes(value: Any, origin: datetime) -> int:
    if not value:
        return 0
    try:
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return 0
    return max(0, int((dt - origin).total_seconds() // 60))


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [
            item.strip()
            for item in value.replace("|", ",").replace(";", ",").split(",")
            if item.strip()
        ]
    return [str(value)]
