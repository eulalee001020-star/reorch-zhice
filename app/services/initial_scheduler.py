"""From-zero initial scheduling service.

The service generates several schedule options with different business
objectives. It is intentionally independent from the anomaly-rescheduling
flow so ReOrch can support both baseline planning and exception recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ortools.sat.python import cp_model

from app.models.enums import StrategyType
from app.models.planning import (
    ChangeoverRuleInput,
    InitialScheduleOption,
    InitialScheduleRequest,
    InitialScheduleResponse,
    PlanningOperationInput,
)
from app.models.schedule import (
    Operation,
    Resource,
    ScheduleDetail,
    ScheduleSnapshot,
    WorkOrder,
)
from app.models.solver import (
    CandidatePlan,
    SolverChain,
    SolverMetadata,
)
from app.services.constraint_validator import ConstraintValidator
from app.services.data_readiness import DataReadinessService


_SUPPORTED_GOALS = {
    "delivery_priority",
    "throughput_priority",
    "bottleneck_priority",
    "cost_priority",
    "balanced",
}


@dataclass(frozen=True)
class _OpRuntime:
    op: PlanningOperationInput
    work_order: str
    due_offset: int
    priority_weight: int
    product_name: str
    product_family: str


class InitialScheduler:
    """Generate Top-K initial schedule options from orders and resources."""

    def __init__(
        self,
        readiness: DataReadinessService | None = None,
        validator: ConstraintValidator | None = None,
    ) -> None:
        self._readiness = readiness or DataReadinessService()
        self._validator = validator or ConstraintValidator()

    async def generate(self, request: InitialScheduleRequest) -> InitialScheduleResponse:
        readiness_report = self._readiness.assess_initial_schedule_request(request)
        if not readiness_report.is_ready:
            return InitialScheduleResponse(
                workshop_id=request.workshop_id,
                readiness_report=readiness_report,
                options=[],
            )

        goals = [goal for goal in request.goal_modes if goal in _SUPPORTED_GOALS]
        if not goals:
            goals = ["balanced"]

        options: list[InitialScheduleOption] = []
        per_goal_budget = max(0.5, request.time_budget_seconds / max(1, len(goals)))

        for index, goal in enumerate(goals[: request.max_solutions]):
            option = self._solve_one_goal(
                request=request,
                goal_mode=goal,
                timeout_seconds=per_goal_budget,
                random_seed=31 + index,
            )
            if option is not None:
                options.append(option)

        return InitialScheduleResponse(
            workshop_id=request.workshop_id,
            readiness_report=readiness_report,
            options=options,
        )

    def _solve_one_goal(
        self,
        *,
        request: InitialScheduleRequest,
        goal_mode: str,
        timeout_seconds: float,
        random_seed: int,
    ) -> InitialScheduleOption | None:
        origin = request.planning_start
        op_runtimes = _collect_operations(request)
        if not op_runtimes:
            return None

        resource_ids = [r.resource_id for r in request.resources]
        resource_cost = {
            r.resource_id: max(1, int(round(r.cost_per_minute)))
            for r in request.resources
        }
        bottleneck_ids = {r.resource_id for r in request.resources if r.is_bottleneck}
        horizon = _horizon_minutes(request, op_runtimes)

        model = cp_model.CpModel()
        starts: dict[str, cp_model.IntVar] = {}
        ends: dict[str, cp_model.IntVar] = {}
        presences: dict[tuple[str, str], cp_model.IntVar] = {}
        intervals_by_resource: dict[str, list[cp_model.IntervalVar]] = {
            rid: [] for rid in resource_ids
        }

        for runtime in op_runtimes.values():
            op = runtime.op
            start = model.NewIntVar(0, horizon, f"start_{op.operation_id}")
            end = model.NewIntVar(0, horizon, f"end_{op.operation_id}")
            starts[op.operation_id] = start
            ends[op.operation_id] = end
            model.Add(end == start + op.duration_minutes)

            if op.release_time is not None:
                model.Add(start >= _minutes_between(origin, op.release_time))
            for material in op.material_requirements:
                if material.available_at is not None:
                    model.Add(start >= _minutes_between(origin, material.available_at))

            presence_vars: list[cp_model.IntVar] = []
            for resource_id in op.eligible_resource_ids:
                presence = model.NewBoolVar(f"use_{op.operation_id}_{resource_id}")
                interval = model.NewOptionalIntervalVar(
                    start,
                    op.duration_minutes,
                    end,
                    presence,
                    f"interval_{op.operation_id}_{resource_id}",
                )
                presences[(op.operation_id, resource_id)] = presence
                presence_vars.append(presence)
                intervals_by_resource.setdefault(resource_id, []).append(interval)
            model.AddExactlyOne(presence_vars)

        for runtime in op_runtimes.values():
            op = runtime.op
            for pred_id in op.predecessor_ids:
                if pred_id in ends:
                    model.Add(starts[op.operation_id] >= ends[pred_id])

        _add_unavailable_calendar_intervals(
            model=model,
            request=request,
            origin=origin,
            horizon=horizon,
            intervals_by_resource=intervals_by_resource,
        )
        for intervals in intervals_by_resource.values():
            if intervals:
                model.AddNoOverlap(intervals)

        _add_changeover_constraints(
            model=model,
            request=request,
            op_runtimes=op_runtimes,
            starts=starts,
            ends=ends,
            presences=presences,
        )

        makespan = model.NewIntVar(0, horizon, "makespan")
        model.AddMaxEquality(makespan, list(ends.values()))

        tardiness_terms: list[cp_model.LinearExpr] = []
        for wo in request.work_orders:
            wo_ends = [
                ends[op.operation_id]
                for op in wo.operations
                if op.operation_id in ends
            ]
            if not wo_ends:
                continue
            completion = model.NewIntVar(0, horizon, f"completion_{wo.work_order_id}")
            model.AddMaxEquality(completion, wo_ends)
            due_offset = max(0, _minutes_between(origin, wo.due_date))
            tardiness = model.NewIntVar(0, horizon, f"tardiness_{wo.work_order_id}")
            model.Add(tardiness >= completion - due_offset)
            model.Add(tardiness >= 0)
            tardiness_terms.append(tardiness * max(1, wo.priority + 1))

        load_by_resource: dict[str, cp_model.IntVar] = {}
        for rid in resource_ids:
            terms: list[cp_model.LinearExpr] = []
            for runtime in op_runtimes.values():
                op = runtime.op
                presence = presences.get((op.operation_id, rid))
                if presence is not None:
                    terms.append(presence * op.duration_minutes)
            load = model.NewIntVar(0, horizon, f"load_{rid}")
            model.Add(load == sum(terms) if terms else 0)
            load_by_resource[rid] = load

        max_load = model.NewIntVar(0, horizon, "max_resource_load")
        min_load = model.NewIntVar(0, horizon, "min_resource_load")
        if load_by_resource:
            model.AddMaxEquality(max_load, list(load_by_resource.values()))
            model.AddMinEquality(min_load, list(load_by_resource.values()))
        load_span = model.NewIntVar(0, horizon, "load_span")
        model.Add(load_span == max_load - min_load)

        cost_terms: list[cp_model.LinearExpr] = []
        for runtime in op_runtimes.values():
            op = runtime.op
            for rid in op.eligible_resource_ids:
                presence = presences[(op.operation_id, rid)]
                cost_terms.append(presence * op.duration_minutes * resource_cost.get(rid, 100))

        objective = _build_objective(
            goal_mode=goal_mode,
            makespan=makespan,
            tardiness_terms=tardiness_terms,
            load_by_resource=load_by_resource,
            load_span=load_span,
            cost_terms=cost_terms,
            bottleneck_ids=bottleneck_ids,
        )
        model.Minimize(objective)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout_seconds
        solver.parameters.num_search_workers = 8
        solver.parameters.random_seed = random_seed

        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None

        detail = _build_schedule_detail(
            request=request,
            op_runtimes=op_runtimes,
            starts=starts,
            ends=ends,
            presences=presences,
            solver=solver,
        )
        snapshot = ScheduleSnapshot(
            captured_at=request.planning_start,
            workshop_id=request.workshop_id,
            source_system="initial_scheduler",
            work_orders=detail.work_orders,
        )
        report = self._validator.validate_constraints(
            schedule_detail=detail,
            snapshot=snapshot,
            strategy_type=StrategyType.GLOBAL_RESCHEDULE,
            affected_op_ids=[],
        )

        chain = SolverChain(
            strategy_type="initial_schedule",
            rule_selection=goal_mode,
            neighborhood_selection="not_applicable_initial_plan",
            repair_policy=goal_mode,
            solver_name="cp_sat_initial_scheduler",
            key_parameters={
                "goal_mode": goal_mode,
                "timeout_seconds": timeout_seconds,
                "status": solver.StatusName(status),
                "objective_value": solver.ObjectiveValue(),
            },
            search_budget_seconds=timeout_seconds,
            constraint_validation_result="feasible" if report.is_feasible else "infeasible",
            stages=[
                "初始排程建模",
                "多目标权重配置",
                "CP-SAT求解",
                "硬约束校验",
                "KPI计算",
            ],
        )
        plan = CandidatePlan(
            strategy_type="initial_schedule",
            schedule_detail=detail,
            gantt_version="initial-v1",
            solver_chain=chain,
            feasibility_status="feasible" if report.is_feasible else "infeasible",
            solver_metadata=SolverMetadata(
                solve_time_seconds=round(solver.WallTime(), 4),
                iteration_count=0,
                objective_trajectory=[float(solver.ObjectiveValue())],
            ),
            constraint_report=report,
        )
        profile = _goal_profile(goal_mode)
        return InitialScheduleOption(
            goal_mode=goal_mode,
            label=profile["label"],
            strengths=profile["strengths"],
            tradeoffs=profile["tradeoffs"],
            candidate_plan=plan,
            kpis=_compute_initial_kpis(request, detail),
        )


def _collect_operations(request: InitialScheduleRequest) -> dict[str, _OpRuntime]:
    result: dict[str, _OpRuntime] = {}
    for wo in request.work_orders:
        for op in wo.operations:
            family = op.product_family or wo.product_family or "unknown"
            result[op.operation_id] = _OpRuntime(
                op=op,
                work_order=wo.work_order_id,
                due_offset=max(0, _minutes_between(request.planning_start, wo.due_date)),
                priority_weight=max(1, wo.priority + 1),
                product_name=wo.product_name,
                product_family=family,
            )
    return result


def _horizon_minutes(
    request: InitialScheduleRequest,
    op_runtimes: dict[str, _OpRuntime],
) -> int:
    total_duration = sum(runtime.op.duration_minutes for runtime in op_runtimes.values())
    latest_due = max(
        [_minutes_between(request.planning_start, wo.due_date) for wo in request.work_orders]
        or [0]
    )
    latest_release = max(
        [
            _minutes_between(request.planning_start, runtime.op.release_time)
            for runtime in op_runtimes.values()
            if runtime.op.release_time is not None
        ]
        or [0]
    )
    return max(60, total_duration + latest_due + latest_release + 24 * 60)


def _build_objective(
    *,
    goal_mode: str,
    makespan: cp_model.IntVar,
    tardiness_terms: list[cp_model.LinearExpr],
    load_by_resource: dict[str, cp_model.IntVar],
    load_span: cp_model.IntVar,
    cost_terms: list[cp_model.LinearExpr],
    bottleneck_ids: set[str],
) -> cp_model.LinearExpr:
    tardiness = sum(tardiness_terms) if tardiness_terms else 0
    cost = sum(cost_terms) if cost_terms else 0
    bottleneck_load = sum(
        load for rid, load in load_by_resource.items() if rid in bottleneck_ids
    )

    if goal_mode == "delivery_priority":
        return tardiness * 120 + makespan * 2 + load_span
    if goal_mode == "throughput_priority":
        return makespan * 30 + tardiness * 20 + load_span
    if goal_mode == "bottleneck_priority":
        return tardiness * 50 + makespan * 6 + load_span * 8 - bottleneck_load * 4
    if goal_mode == "cost_priority":
        return cost + tardiness * 40 + makespan
    return tardiness * 70 + makespan * 8 + load_span * 4 + cost


def _add_unavailable_calendar_intervals(
    *,
    model: cp_model.CpModel,
    request: InitialScheduleRequest,
    origin: datetime,
    horizon: int,
    intervals_by_resource: dict[str, list[cp_model.IntervalVar]],
) -> None:
    for index, window in enumerate(request.resource_calendar):
        if window.availability_type != "unavailable":
            continue
        start = max(0, _minutes_between(origin, window.window_start))
        end = min(horizon, max(start, _minutes_between(origin, window.window_end)))
        duration = end - start
        if duration <= 0:
            continue
        interval = model.NewFixedSizeIntervalVar(
            start,
            duration,
            f"calendar_block_{window.resource_id}_{index}",
        )
        intervals_by_resource.setdefault(window.resource_id, []).append(interval)


def _add_changeover_constraints(
    *,
    model: cp_model.CpModel,
    request: InitialScheduleRequest,
    op_runtimes: dict[str, _OpRuntime],
    starts: dict[str, cp_model.IntVar],
    ends: dict[str, cp_model.IntVar],
    presences: dict[tuple[str, str], cp_model.IntVar],
) -> None:
    setup_lookup = _build_setup_lookup(request.changeover_rules)
    if not setup_lookup:
        return

    resource_ids = [resource.resource_id for resource in request.resources]
    for resource_id in resource_ids:
        op_ids = [
            op_id
            for op_id, runtime in op_runtimes.items()
            if (runtime.op.operation_id, resource_id) in presences
        ]
        if len(op_ids) <= 1:
            continue

        arcs: list[list[int | cp_model.IntVar]] = []
        empty = model.NewBoolVar(f"changeover_empty_{resource_id}")
        assigned = [presences[(op_id, resource_id)] for op_id in op_ids]
        model.Add(sum(assigned) == 0).OnlyEnforceIf(empty)
        model.Add(sum(assigned) >= 1).OnlyEnforceIf(empty.Not())
        arcs.append([0, 0, empty])

        node_by_op = {op_id: index + 1 for index, op_id in enumerate(op_ids)}

        for op_id, node in node_by_op.items():
            presence = presences[(op_id, resource_id)]
            arcs.append([node, node, presence.Not()])
            start_arc = model.NewBoolVar(f"changeover_start_{resource_id}_{op_id}")
            end_arc = model.NewBoolVar(f"changeover_end_{resource_id}_{op_id}")
            arcs.append([0, node, start_arc])
            arcs.append([node, 0, end_arc])

        for left_id, left_node in node_by_op.items():
            for right_id, right_node in node_by_op.items():
                if left_id == right_id:
                    continue
                arc = model.NewBoolVar(f"changeover_{resource_id}_{left_id}_{right_id}")
                arcs.append([left_node, right_node, arc])
                setup_minutes = _setup_minutes(
                    setup_lookup,
                    resource_id,
                    op_runtimes[left_id].product_family,
                    op_runtimes[right_id].product_family,
                )
                if setup_minutes:
                    model.Add(starts[right_id] >= ends[left_id] + setup_minutes).OnlyEnforceIf(arc)

        model.AddCircuit(arcs)


def _build_setup_lookup(
    rules: list[ChangeoverRuleInput],
) -> dict[tuple[str | None, str, str], int]:
    lookup: dict[tuple[str | None, str, str], int] = {}
    for rule in rules:
        if rule.from_product_family == rule.to_product_family:
            continue
        key = (rule.resource_id, rule.from_product_family, rule.to_product_family)
        lookup[key] = max(lookup.get(key, 0), rule.setup_minutes)
    return lookup


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


def _build_schedule_detail(
    *,
    request: InitialScheduleRequest,
    op_runtimes: dict[str, _OpRuntime],
    starts: dict[str, cp_model.IntVar],
    ends: dict[str, cp_model.IntVar],
    presences: dict[tuple[str, str], cp_model.IntVar],
    solver: cp_model.CpSolver,
) -> ScheduleDetail:
    successor_map: dict[str, list[str]] = {op_id: [] for op_id in op_runtimes}
    for runtime in op_runtimes.values():
        for pred in runtime.op.predecessor_ids:
            successor_map.setdefault(pred, []).append(runtime.op.operation_id)

    resources = [
        Resource(
            resource_id=res.resource_id,
            name=res.name or res.resource_id,
            capabilities=res.capabilities,
            is_bottleneck=res.is_bottleneck,
            has_redundancy=res.has_redundancy,
            criticality=res.criticality,
        )
        for res in request.resources
    ]

    work_orders: list[WorkOrder] = []
    for wo in request.work_orders:
        operations: list[Operation] = []
        for op_in in wo.operations:
            assigned_resource = _assigned_resource(op_in, presences, solver)
            start_dt = request.planning_start + timedelta(
                minutes=solver.Value(starts[op_in.operation_id])
            )
            end_dt = request.planning_start + timedelta(
                minutes=solver.Value(ends[op_in.operation_id])
            )
            operations.append(
                Operation(
                    operation_id=op_in.operation_id,
                    work_order_id=wo.work_order_id,
                    resource_id=assigned_resource,
                    required_capabilities=op_in.required_capabilities,
                    start_time=start_dt,
                    end_time=end_dt,
                    predecessor_ids=op_in.predecessor_ids,
                    successor_ids=successor_map.get(op_in.operation_id, []),
                    is_affected=False,
                    is_adjusted=True,
                )
            )
        operations.sort(key=lambda op: op.start_time)
        work_orders.append(
            WorkOrder(
                work_order_id=wo.work_order_id,
                product_name=wo.product_name,
                due_date=wo.due_date,
                operations=operations,
                priority=wo.priority,
            )
        )

    return ScheduleDetail(work_orders=work_orders, resources=resources)


def _assigned_resource(
    op: PlanningOperationInput,
    presences: dict[tuple[str, str], cp_model.IntVar],
    solver: cp_model.CpSolver,
) -> str:
    for rid in op.eligible_resource_ids:
        presence = presences.get((op.operation_id, rid))
        if presence is not None and solver.BooleanValue(presence):
            return rid
    return op.eligible_resource_ids[0]


def _compute_initial_kpis(
    request: InitialScheduleRequest,
    detail: ScheduleDetail,
) -> dict[str, float | int | str]:
    latest_end: datetime | None = None
    total_tardiness = 0.0
    max_tardiness = 0.0
    on_time = 0
    operation_count = 0
    busy_by_resource: dict[str, float] = {}
    family_by_op = {
        op.operation_id: op.product_family or wo.product_family or "unknown"
        for wo in request.work_orders
        for op in wo.operations
    }

    for wo in detail.work_orders:
        if not wo.operations:
            continue
        operation_count += len(wo.operations)
        completion = max(op.end_time for op in wo.operations)
        latest_end = completion if latest_end is None else max(latest_end, completion)
        tardiness = max(0.0, (completion - wo.due_date).total_seconds() / 60)
        total_tardiness += tardiness
        max_tardiness = max(max_tardiness, tardiness)
        if tardiness == 0:
            on_time += 1
        for op in wo.operations:
            busy_by_resource[op.resource_id] = busy_by_resource.get(op.resource_id, 0.0) + (
                op.end_time - op.start_time
            ).total_seconds() / 60

    makespan = 0.0
    if latest_end is not None:
        makespan = max(0.0, (latest_end - request.planning_start).total_seconds() / 60)

    changeovers = 0
    by_resource: dict[str, list[Operation]] = {}
    for wo in detail.work_orders:
        for op in wo.operations:
            by_resource.setdefault(op.resource_id, []).append(op)
    for ops in by_resource.values():
        ordered = sorted(ops, key=lambda op: op.start_time)
        for left, right in zip(ordered, ordered[1:]):
            if family_by_op.get(left.operation_id) != family_by_op.get(right.operation_id):
                changeovers += 1

    bottleneck_ids = {r.resource_id for r in request.resources if r.is_bottleneck}
    bottleneck_busy = sum(busy_by_resource.get(rid, 0.0) for rid in bottleneck_ids)
    bottleneck_utilization = (
        round(bottleneck_busy / max(1.0, makespan * max(1, len(bottleneck_ids))), 4)
        if bottleneck_ids
        else 0.0
    )

    cost_by_resource = {r.resource_id: r.cost_per_minute for r in request.resources}
    total_cost = sum(
        minutes * cost_by_resource.get(rid, 0.0)
        for rid, minutes in busy_by_resource.items()
    )

    order_count = len(detail.work_orders)
    return {
        "work_order_count": order_count,
        "operation_count": operation_count,
        "makespan_minutes": round(makespan, 2),
        "total_tardiness_minutes": round(total_tardiness, 2),
        "max_tardiness_minutes": round(max_tardiness, 2),
        "otd_rate": round(on_time / order_count, 4) if order_count else 0.0,
        "changeover_count": changeovers,
        "bottleneck_utilization": bottleneck_utilization,
        "estimated_resource_cost": round(total_cost, 2),
    }


def _goal_profile(goal_mode: str) -> dict[str, Any]:
    profiles: dict[str, dict[str, Any]] = {
        "delivery_priority": {
            "label": "交付优先方案",
            "strengths": ["优先降低延期订单数", "关键订单风险暴露更清晰"],
            "tradeoffs": ["可能牺牲部分资源均衡", "可能增加切换和执行复杂度"],
        },
        "throughput_priority": {
            "label": "吞吐优先方案",
            "strengths": ["优先缩短整体完工时间", "适合产能紧张窗口"],
            "tradeoffs": ["部分低优先级订单可能被推后"],
        },
        "bottleneck_priority": {
            "label": "瓶颈优先方案",
            "strengths": ["优先保护关键设备利用率", "减少瓶颈资源空转"],
            "tradeoffs": ["非瓶颈资源可能出现等待"],
        },
        "cost_priority": {
            "label": "成本优先方案",
            "strengths": ["优先选择低成本资源组合", "适合交付压力较低时使用"],
            "tradeoffs": ["可能牺牲交付速度和瓶颈利用率"],
        },
        "balanced": {
            "label": "平衡方案",
            "strengths": ["在交付、吞吐、资源均衡和成本之间折中", "适合作为默认基准方案"],
            "tradeoffs": ["单一指标未必最优"],
        },
    }
    return profiles.get(goal_mode, profiles["balanced"])


def _minutes_between(origin: datetime, value: datetime) -> int:
    if origin.tzinfo is None and value.tzinfo is not None:
        origin = origin.replace(tzinfo=value.tzinfo)
    if origin.tzinfo is not None and value.tzinfo is None:
        value = value.replace(tzinfo=origin.tzinfo)
    return max(0, int((value - origin).total_seconds() // 60))
