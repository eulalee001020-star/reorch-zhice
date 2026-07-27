"""Reusable large-FJSP anomaly replay and rescheduling service."""

from __future__ import annotations

from uuid import uuid4

from app.adapters.mapping_schema import AdapterMappingProfile, FieldMapping
from app.models.enums import DeliveryRiskLevel, StrategyType
from app.models.impact import AffectedOperation, AffectedWorkOrder, ImpactReport
from app.models.large_fjsp_replay import (
    LargeFjspIncidentReplayResult,
    LargeFjspReplayRequest,
    LargeFjspReplayResponse,
    LargeFjspStrategyKpi,
    LargeFjspStrategyOption,
)
from app.models.reality_harness import P0RealityHarnessRequest
from app.models.schedule import Operation, ScheduleDetail, ScheduleSnapshot, WorkOrder
from app.services.cp_sat_scheduler import CpSatFjspScheduler
from app.services.customer_constraint_ingestion import CustomerConstraintIngestionService
from app.services.machine_rank_service import MachineRankService
from app.services.metaheuristic_backend import MetaheuristicBackend
from app.services.reality_harness import P0RealityHarnessService


_INCIDENT_TYPE_TO_REORCH: dict[str, str] = {
    "machine_down": "machine_down",
    "capacity_degradation": "capacity_degradation",
    "setup_overrun": "capacity_degradation",
    "tooling_conflict": "equipment_failure",
    "rush_order_insert": "urgent_order_insert",
    "material_shortage": "material_shortage",
    "quality_hold": "equipment_failure",
    "operator_skill_shortage": "capacity_degradation",
}

_POLICY_TO_SOLVER: dict[str, StrategyType] = {
    "wait_and_shift": StrategyType.WAIT_AND_REPAIR,
    "keep_plan_warning": StrategyType.WAIT_AND_REPAIR,
    "local_repair": StrategyType.LOCAL_REPAIR,
    "local_resequence": StrategyType.LOCAL_REPAIR,
    "alternative_machine_repair": StrategyType.LOCAL_REPAIR,
    "partial_reassignment": StrategyType.LOCAL_REPAIR,
    "tooling_reallocation": StrategyType.LOCAL_REPAIR,
    "priority_swap": StrategyType.LOCAL_REPAIR,
    "controlled_global_reschedule": StrategyType.GLOBAL_RESCHEDULE,
    "controlled_frozen_zone_release": StrategyType.GLOBAL_RESCHEDULE,
}


class LargeFjspReplayService:
    """Runs multi-policy replay against an anonymized large-FJSP pack."""

    def __init__(
        self,
        *,
        reality_harness: P0RealityHarnessService | None = None,
        scheduler: CpSatFjspScheduler | None = None,
        metaheuristic: MetaheuristicBackend | None = None,
        machine_ranker: MachineRankService | None = None,
    ) -> None:
        self._reality_harness = reality_harness or P0RealityHarnessService()
        self._scheduler = scheduler or CpSatFjspScheduler()
        self._metaheuristic = metaheuristic or MetaheuristicBackend(self._scheduler)
        self._machine_ranker = machine_ranker or MachineRankService()

    def run(self, request: LargeFjspReplayRequest) -> LargeFjspReplayResponse:
        normalized = _normalize_request(request)
        harness_response = self._reality_harness.assess(
            _to_reality_request(normalized)
        )
        snapshot = harness_response.snapshot
        if snapshot is None:
            return LargeFjspReplayResponse(
                source_system=request.source_system,
                workshop_id=request.workshop_id,
                permission_level=harness_response.permission.level,
                readiness_score=harness_response.readiness_report.readiness_score,
                snapshot_available=False,
                work_order_count=len(request.work_orders),
                operation_count=len(request.operations),
                resource_count=len(request.resources),
                incident_count=len(request.incidents),
                solved_incident_count=0,
                feasible_option_count=0,
                results=[],
                global_gaps=[
                    "snapshot_not_available",
                    *harness_response.permission.required_next_actions,
                ],
                claim_boundary=_CLAIM_BOUNDARY,
            )
        snapshot = CustomerConstraintIngestionService().attach_to_snapshot(
            snapshot,
            CustomerConstraintIngestionService().build_pack(
                material_availability=normalized.material_availability,
                quality_holds=normalized.quality_holds,
                tooling_calendar=normalized.tooling_calendar,
                labor_skill_capacity=normalized.labor_skill_capacity,
                urgent_order_constraints=normalized.urgent_order_constraints,
            ),
        )

        incidents = normalized.incidents[: request.max_incidents]
        frozen_ids = _frozen_operation_ids(normalized.schedule_rows)
        results = [
            self._solve_incident(
                incident=incident,
                snapshot=snapshot,
                frozen_operation_ids=frozen_ids
                if request.freeze_snapshot_operations
                else [],
                timeout_seconds=request.cp_sat_timeout_seconds,
                include_global_reschedule=request.include_global_reschedule,
            )
            for incident in incidents
        ]
        feasible_option_count = sum(
            1
            for result in results
            for option in result.options
            if option.feasibility_status == "feasible"
        )
        solved_incident_count = sum(
            1 for result in results if result.can_generate_executable_plan
        )
        global_gaps = _global_gaps(harness_response.readiness_report.warnings)
        return LargeFjspReplayResponse(
            source_system=request.source_system,
            workshop_id=request.workshop_id,
            permission_level=harness_response.permission.level,
            readiness_score=harness_response.readiness_report.readiness_score,
            snapshot_available=True,
            work_order_count=len(snapshot.work_orders),
            operation_count=sum(len(wo.operations) for wo in snapshot.work_orders),
            resource_count=len(request.resources),
            incident_count=len(incidents),
            solved_incident_count=solved_incident_count,
            feasible_option_count=feasible_option_count,
            results=results,
            global_gaps=global_gaps,
            claim_boundary=_CLAIM_BOUNDARY,
        )

    def _solve_incident(
        self,
        *,
        incident: dict,
        snapshot: ScheduleSnapshot,
        frozen_operation_ids: list[str],
        timeout_seconds: float,
        include_global_reschedule: bool,
    ) -> LargeFjspIncidentReplayResult:
        case_id = str(incident.get("case_id") or incident.get("incident_id") or "")
        source_incident_type = str(
            incident.get("source_incident_type") or incident.get("incident_type", "")
        )
        normalized_incident_type = str(incident.get("incident_type", "equipment_failure"))
        affected_operation_id = _optional_str(incident.get("primary_operation_id"))
        affected_work_order_id = _optional_str(incident.get("primary_work_order_id"))
        baseline_op = _operation_by_id(snapshot, affected_operation_id)
        if baseline_op is None or affected_operation_id is None:
            return LargeFjspIncidentReplayResult(
                case_id=case_id,
                source_incident_type=source_incident_type,
                normalized_incident_type=normalized_incident_type,
                affected_operation_id=affected_operation_id,
                affected_work_order_id=affected_work_order_id,
                options=[],
                remaining_gaps=["affected_operation_not_found_in_snapshot"],
            )

        policies = _policies_for_incident(source_incident_type)
        if not include_global_reschedule:
            policies = [
                policy
                for policy in policies
                if _POLICY_TO_SOLVER.get(policy) != StrategyType.GLOBAL_RESCHEDULE
            ]
        impact = _impact_report(snapshot, incident, baseline_op)
        options = [
            self._solve_policy(
                policy=policy,
                snapshot=snapshot,
                impact=impact,
                affected_operation_id=affected_operation_id,
                solver_frozen_operation_ids=[
                    operation_id
                    for operation_id in frozen_operation_ids
                    if operation_id != affected_operation_id
                ],
                kpi_frozen_operation_ids=frozen_operation_ids,
                timeout_seconds=timeout_seconds,
            )
            for policy in policies
        ]
        if not any(option.feasibility_status == "feasible" for option in options):
            options.append(
                self._solve_policy(
                    policy="controlled_frozen_zone_release",
                    snapshot=snapshot,
                    impact=impact,
                    affected_operation_id=affected_operation_id,
                    solver_frozen_operation_ids=[
                        operation_id
                        for operation_id in frozen_operation_ids
                        if operation_id not in _work_order_operation_ids(
                            snapshot, affected_work_order_id
                        )
                    ],
                    kpi_frozen_operation_ids=frozen_operation_ids,
                    timeout_seconds=timeout_seconds,
                )
            )
        feasible_options = [
            option for option in options if option.feasibility_status == "feasible"
        ]
        recommended = min(feasible_options, key=_option_rank) if feasible_options else None
        return LargeFjspIncidentReplayResult(
            case_id=case_id,
            source_incident_type=source_incident_type,
            normalized_incident_type=normalized_incident_type,
            affected_operation_id=affected_operation_id,
            affected_work_order_id=affected_work_order_id,
            estimated_service_loss_minutes=float(
                incident.get("estimated_service_loss_min") or 0
            ),
            options=options,
            recommended_policy=recommended.policy_type if recommended else None,
            recommendation_reason=_recommendation_reason(recommended)
            if recommended
            else "No feasible solver-backed option was produced.",
            can_generate_executable_plan=bool(recommended),
            remaining_gaps=_incident_gaps(incident),
        )

    def _solve_policy(
        self,
        *,
        policy: str,
        snapshot: ScheduleSnapshot,
        impact: ImpactReport,
        affected_operation_id: str,
        solver_frozen_operation_ids: list[str],
        kpi_frozen_operation_ids: list[str],
        timeout_seconds: float,
    ) -> LargeFjspStrategyOption:
        strategy = _POLICY_TO_SOLVER.get(policy)
        if strategy is None:
            return LargeFjspStrategyOption(
                policy_type=policy,
                solver_strategy="reference_only",
                feasibility_status="blocked",
                solver_status="REFERENCE_ONLY",
                kpi=LargeFjspStrategyKpi(),
                blockers=["policy_not_bound_to_solver_backend"],
                pros=_pros(policy),
                cons=[*_cons(policy), "requires planner or domain-specific branch"],
                decision_boundary="Reference-only policy; do not write back.",
            )

        result = self._solve_with_portfolio(
            snapshot=snapshot,
            impact=impact,
            strategy=strategy,
            affected_operation_id=affected_operation_id,
            frozen_operation_ids=solver_frozen_operation_ids,
            kpi_frozen_operation_ids=kpi_frozen_operation_ids,
            timeout_seconds=timeout_seconds,
        )
        if not result.is_feasible or result.schedule_detail is None:
            return LargeFjspStrategyOption(
                policy_type=policy,
                solver_strategy=strategy.value,
                feasibility_status="infeasible",
                solver_status=result.status_name,
                objective_value=result.objective_value,
                solve_time_seconds=round(result.wall_time_seconds, 4),
                variable_operation_count=len(result.variable_operation_ids),
                kpi=LargeFjspStrategyKpi(),
                pros=_pros(policy),
                cons=[*_cons(policy), "solver did not return a feasible schedule"],
                blockers=[result.status_name, *result.solver_log.get("portfolio_failures", [])],
                decision_boundary="Keep as no-writeback evidence; escalate to planner.",
            )

        kpi = _kpi(
            baseline=snapshot,
            candidate=result.schedule_detail,
            affected_operation_id=affected_operation_id,
            frozen_operation_ids=kpi_frozen_operation_ids,
        )
        return LargeFjspStrategyOption(
            policy_type=policy,
            solver_strategy=strategy.value,
            feasibility_status="feasible",
            solver_status=result.status_name,
            objective_value=result.objective_value,
            solve_time_seconds=round(result.wall_time_seconds, 4),
            variable_operation_count=len(result.variable_operation_ids),
            kpi=kpi,
            pros=_pros(policy, kpi),
            cons=_cons(policy, kpi),
            decision_boundary=(
                "Solver-backed option. It can enter planner review; production "
                "writeback still requires approval, audit, rollback, and execution "
                "feedback."
            ),
        )

    def _solve_with_portfolio(
        self,
        *,
        snapshot: ScheduleSnapshot,
        impact: ImpactReport,
        strategy: StrategyType,
        affected_operation_id: str,
        frozen_operation_ids: list[str],
        kpi_frozen_operation_ids: list[str],
        timeout_seconds: float,
    ):
        direct = self._scheduler.solve(
            snapshot=snapshot,
            impact_report=impact,
            strategy_type=strategy,
            affected_op_ids=[affected_operation_id],
            frozen_operation_ids=frozen_operation_ids,
            timeout_seconds=max(0.2, timeout_seconds * 0.45),
        )
        results = [direct]
        if strategy in {StrategyType.LOCAL_REPAIR, StrategyType.GLOBAL_RESCHEDULE}:
            meta = self._metaheuristic.solve(
                snapshot=snapshot,
                impact_report=impact,
                strategy_type=strategy,
                affected_op_ids=[affected_operation_id],
                frozen_operation_ids=frozen_operation_ids,
                machine_ranks=self._machine_ranker.rank(snapshot, impact),
                timeout_seconds=max(0.2, timeout_seconds * 0.55),
                candidate_count=3,
            )
            results.extend(meta.schedules)

        feasible = [
            result
            for result in results
            if result.is_feasible and result.schedule_detail is not None
        ]
        if not feasible:
            direct.solver_log = {
                **direct.solver_log,
                "portfolio_failures": [
                    result.status_name for result in results if not result.is_feasible
                ],
            }
            return direct

        def rank(result) -> tuple[float, float, float, float]:
            assert result.schedule_detail is not None
            kpi = _kpi(
                baseline=snapshot,
                candidate=result.schedule_detail,
                affected_operation_id=affected_operation_id,
                frozen_operation_ids=kpi_frozen_operation_ids,
            )
            return (
                kpi.frozen_change_count,
                max(0.0, kpi.affected_completion_delta_minutes),
                kpi.total_start_shift_minutes,
                result.wall_time_seconds,
            )

        best = min(feasible, key=rank)
        best.solver_log = {
            **best.solver_log,
            "portfolio_backends": [
                "direct_cp_sat",
                "metaheuristic_lns_cp_sat",
            ],
            "portfolio_feasible_count": len(feasible),
            "portfolio_attempt_count": len(results),
        }
        return best


def _normalize_request(request: LargeFjspReplayRequest) -> LargeFjspReplayRequest:
    work_orders = [dict(row) for row in request.work_orders]
    operations = [dict(row) for row in request.operations]
    resources = [dict(row) for row in request.resources]
    incidents = [dict(row) for row in request.incidents]
    material_availability = [dict(row) for row in request.material_availability]
    quality_holds = [dict(row) for row in request.quality_holds]
    tooling_calendar = [dict(row) for row in request.tooling_calendar]
    labor_skill_capacity = [dict(row) for row in request.labor_skill_capacity]
    urgent_order_constraints = [dict(row) for row in request.urgent_order_constraints]
    schedule_by_operation = {
        str(row.get("operation_id")): row for row in request.schedule_rows
    }
    for row in work_orders:
        row["due_time"] = _with_timezone(row.get("due_time"), request.timezone_suffix)
    for row in operations:
        row.update(schedule_by_operation.get(str(row.get("operation_id")), {}))
        row["planned_start"] = _with_timezone(
            row.get("planned_start"), request.timezone_suffix
        )
        row["planned_end"] = _with_timezone(
            row.get("planned_end"), request.timezone_suffix
        )
    for row in incidents:
        row["source_incident_type"] = row.get("incident_type")
        row["incident_type"] = _INCIDENT_TYPE_TO_REORCH.get(
            str(row.get("incident_type", "")),
            "equipment_failure",
        )
        row["occurred_at"] = _with_timezone(
            row.get("occurred_at"), request.timezone_suffix
        )
    return LargeFjspReplayRequest(
        source_system=request.source_system,
        workshop_id=request.workshop_id,
        work_orders=work_orders,
        operations=operations,
        resources=resources,
        schedule_rows=[dict(row) for row in request.schedule_rows],
        incidents=incidents,
        material_availability=material_availability,
        quality_holds=quality_holds,
        tooling_calendar=tooling_calendar,
        labor_skill_capacity=labor_skill_capacity,
        urgent_order_constraints=urgent_order_constraints,
        timezone_suffix=request.timezone_suffix,
        max_incidents=request.max_incidents,
        cp_sat_timeout_seconds=request.cp_sat_timeout_seconds,
        include_global_reschedule=request.include_global_reschedule,
        freeze_snapshot_operations=request.freeze_snapshot_operations,
    )


def _to_reality_request(request: LargeFjspReplayRequest) -> P0RealityHarnessRequest:
    return P0RealityHarnessRequest(
        source_system=request.source_system,
        workshop_id=request.workshop_id,
        raw_work_orders=request.work_orders,
        raw_operations=request.operations,
        raw_machines=request.resources,
        raw_incidents=request.incidents,
        profile=AdapterMappingProfile(
            source_system=request.source_system,
            field_mapping=FieldMapping(
                work_order={
                    "work_order_id": "work_order_id",
                    "product_id": "product_family",
                    "product_name": "product_family",
                    "quantity": "quantity",
                    "priority": "priority",
                    "due_time": "due_time",
                    "status": "status",
                },
                operation={
                    "operation_id": "operation_id",
                    "work_order_id": "work_order_id",
                    "sequence": "operation_seq",
                    "required_capability": "",
                    "required_capabilities": "",
                    "processing_time_min": "standard_duration_min",
                    "machine_id": "assigned_resource_id",
                    "eligible_machine_ids": "eligible_machines",
                    "start_time": "planned_start",
                    "end_time": "planned_end",
                    "predecessors": "precedence_prev_operation_id",
                    "successors": "successors",
                },
                machine={
                    "machine_id": "resource_id",
                    "name": "resource_id",
                    "capabilities": "capability_group",
                    "status": "status_at_snapshot",
                    "calendar": "calendar",
                    "is_bottleneck": "is_bottleneck",
                    "has_redundancy": "has_redundancy",
                    "criticality": "criticality",
                },
                incident={
                    "incident_id": "case_id",
                    "incident_type": "incident_type",
                    "machine_id": "primary_resource_id",
                    "start_time": "occurred_at",
                    "severity": "severity",
                    "description": "incident_description",
                },
            ),
        ),
    )


def _policies_for_incident(source_incident_type: str) -> list[str]:
    mapping = {
        "machine_down": [
            "wait_and_shift",
            "alternative_machine_repair",
            "local_repair",
            "controlled_global_reschedule",
        ],
        "capacity_degradation": [
            "keep_plan_warning",
            "partial_reassignment",
            "local_repair",
            "controlled_global_reschedule",
        ],
        "setup_overrun": [
            "local_resequence",
            "local_repair",
            "controlled_global_reschedule",
        ],
        "tooling_conflict": [
            "tooling_reallocation",
            "local_repair",
            "controlled_global_reschedule",
        ],
        "rush_order_insert": [
            "priority_swap",
            "local_repair",
            "controlled_global_reschedule",
        ],
        "material_shortage": [
            "wait_and_shift",
            "local_repair",
            "controlled_global_reschedule",
        ],
        "quality_hold": [
            "wait_and_shift",
            "local_repair",
            "controlled_global_reschedule",
        ],
        "operator_skill_shortage": [
            "local_repair",
            "controlled_global_reschedule",
        ],
    }
    return mapping.get(source_incident_type, ["local_repair", "controlled_global_reschedule"])


def _impact_report(
    snapshot: ScheduleSnapshot,
    incident: dict,
    affected_operation: Operation,
) -> ImpactReport:
    work_order = _work_order_by_id(snapshot, affected_operation.work_order_id)
    delay = float(incident.get("estimated_service_loss_min") or 0)
    affected = AffectedOperation(
        operation_id=affected_operation.operation_id,
        work_order_id=affected_operation.work_order_id,
        resource_id=affected_operation.resource_id,
        is_direct=True,
        estimated_delay_minutes=delay,
    )
    return ImpactReport(
        incident_id=uuid4(),
        schedule_snapshot_id=snapshot.snapshot_id,
        analysis_reference_time=snapshot.captured_at,
        affected_work_orders=[
            AffectedWorkOrder(
                work_order_id=work_order.work_order_id if work_order else affected.work_order_id,
                product_name=work_order.product_name if work_order else "unknown",
                due_date=work_order.due_date if work_order else affected_operation.end_time,
                delivery_risk_level=DeliveryRiskLevel.WARNING,
                remaining_buffer_minutes=0,
                affected_operations=[affected],
            )
        ],
        affected_operations=[affected],
        affected_resource_ids=[affected.resource_id],
        delivery_risk_distribution={DeliveryRiskLevel.WARNING: 1},
        estimated_total_delay_minutes=delay,
    )


def _kpi(
    *,
    baseline: ScheduleSnapshot,
    candidate: ScheduleDetail,
    affected_operation_id: str,
    frozen_operation_ids: list[str],
) -> LargeFjspStrategyKpi:
    baseline_ops = _operation_index(baseline)
    candidate_ops = _detail_operation_index(candidate)
    adjusted = 0
    switches = 0
    total_shift = 0.0
    max_shift = 0.0
    frozen_changes = 0
    frozen_set = set(frozen_operation_ids)
    for op_id, base_op in baseline_ops.items():
        cand_op = candidate_ops.get(op_id)
        if cand_op is None:
            continue
        start_shift = abs((cand_op.start_time - base_op.start_time).total_seconds() / 60)
        resource_changed = cand_op.resource_id != base_op.resource_id
        time_changed = start_shift > 0.001 or cand_op.end_time != base_op.end_time
        if time_changed or resource_changed:
            adjusted += 1
            total_shift += start_shift
            max_shift = max(max_shift, start_shift)
        if resource_changed:
            switches += 1
        if op_id in frozen_set and (time_changed or resource_changed):
            frozen_changes += 1
    base_affected = baseline_ops[affected_operation_id]
    cand_affected = candidate_ops.get(affected_operation_id, base_affected)
    affected_delta = (cand_affected.end_time - base_affected.end_time).total_seconds() / 60
    return LargeFjspStrategyKpi(
        adjusted_operation_count=adjusted,
        resource_switch_count=switches,
        total_start_shift_minutes=round(total_shift, 2),
        max_start_shift_minutes=round(max_shift, 2),
        affected_completion_delta_minutes=round(affected_delta, 2),
        total_tardiness_delta_minutes=round(
            _total_tardiness(candidate.work_orders) - _total_tardiness(baseline.work_orders),
            2,
        ),
        frozen_change_count=frozen_changes,
    )


def _total_tardiness(work_orders: list[WorkOrder]) -> float:
    total = 0.0
    for work_order in work_orders:
        if not work_order.operations:
            continue
        completion = max(op.end_time for op in work_order.operations)
        total += max(0.0, (completion - work_order.due_date).total_seconds() / 60)
    return total


def _operation_index(snapshot: ScheduleSnapshot) -> dict[str, Operation]:
    return {
        op.operation_id: op for wo in snapshot.work_orders for op in wo.operations
    }


def _detail_operation_index(schedule: ScheduleDetail) -> dict[str, Operation]:
    return {
        op.operation_id: op for wo in schedule.work_orders for op in wo.operations
    }


def _operation_by_id(snapshot: ScheduleSnapshot, operation_id: str | None) -> Operation | None:
    if operation_id is None:
        return None
    return _operation_index(snapshot).get(operation_id)


def _work_order_by_id(snapshot: ScheduleSnapshot, work_order_id: str) -> WorkOrder | None:
    for work_order in snapshot.work_orders:
        if work_order.work_order_id == work_order_id:
            return work_order
    return None


def _work_order_operation_ids(
    snapshot: ScheduleSnapshot, work_order_id: str | None
) -> set[str]:
    if work_order_id is None:
        return set()
    work_order = _work_order_by_id(snapshot, work_order_id)
    if work_order is None:
        return set()
    return {operation.operation_id for operation in work_order.operations}


def _frozen_operation_ids(schedule_rows: list[dict]) -> list[str]:
    return [
        str(row.get("operation_id"))
        for row in schedule_rows
        if str(row.get("frozen_flag", "")).lower() == "true"
    ]


def _option_rank(option: LargeFjspStrategyOption) -> tuple[float, float, float, float]:
    return (
        option.kpi.frozen_change_count,
        max(0.0, option.kpi.affected_completion_delta_minutes),
        option.kpi.total_start_shift_minutes,
        option.solve_time_seconds,
    )


def _recommendation_reason(option: LargeFjspStrategyOption | None) -> str | None:
    if option is None:
        return None
    return (
        f"Lowest ranked feasible option under frozen-change, affected-delay, "
        f"perturbation, and solve-time criteria; adjusted "
        f"{option.kpi.adjusted_operation_count} operations."
    )


def _pros(policy: str, kpi: LargeFjspStrategyKpi | None = None) -> list[str]:
    base = {
        "wait_and_shift": ["lowest conceptual change", "simple for planners to audit"],
        "keep_plan_warning": ["avoids unnecessary full reschedule", "low operational disruption"],
        "alternative_machine_repair": ["uses flexible-machine redundancy", "protects affected resource calendar"],
        "partial_reassignment": ["limits scope to affected neighborhood", "can relieve degraded capacity"],
        "local_repair": ["bounded blast radius", "usually fast enough for shadow-mode review"],
        "local_resequence": ["targets setup/local sequence issue", "keeps global plan stable"],
        "tooling_reallocation": ["explicitly handles tooling conflict", "keeps work order flow visible"],
        "priority_swap": ["directly expresses rush-order tradeoff", "auditable displacement"],
        "controlled_global_reschedule": ["broadest feasibility search", "best fallback when local repair fails"],
        "controlled_frozen_zone_release": [
            "recovers cases blocked by frozen downstream operations",
            "makes approval need explicit",
        ],
    }.get(policy, ["auditable policy branch"])
    if kpi and kpi.resource_switch_count:
        return [*base, f"uses {kpi.resource_switch_count} resource switch(es)"]
    return base


def _cons(policy: str, kpi: LargeFjspStrategyKpi | None = None) -> list[str]:
    base = {
        "wait_and_shift": ["can increase delay", "may not use available alternative resources"],
        "keep_plan_warning": ["does not actively recover lost capacity"],
        "alternative_machine_repair": ["may increase setup or transport coordination"],
        "partial_reassignment": ["can leave downstream bottlenecks unresolved"],
        "local_repair": ["may miss global optimum"],
        "local_resequence": ["depends on reliable setup/changeover data"],
        "tooling_reallocation": ["requires tooling availability truth"],
        "priority_swap": ["may displace lower-priority work orders"],
        "controlled_global_reschedule": ["higher perturbation", "requires stricter planner review"],
        "controlled_frozen_zone_release": [
            "requires planner approval to release frozen operations",
            "not eligible for autonomous writeback",
        ],
    }.get(policy, ["requires planner review"])
    if kpi and kpi.frozen_change_count:
        return [*base, f"changes {kpi.frozen_change_count} frozen operation(s)"]
    if kpi and kpi.total_start_shift_minutes > 0:
        return [*base, f"total start shift {kpi.total_start_shift_minutes} min"]
    return base


def _incident_gaps(incident: dict) -> list[str]:
    gaps: list[str] = []
    if "missing" in str(incident.get("manual_decision_placeholder", "")):
        gaps.append("missing_planner_decision")
    if "missing" in str(incident.get("execution_outcome_placeholder", "")):
        gaps.append("missing_execution_outcome")
    return gaps


def _global_gaps(warnings) -> list[str]:
    codes = {warning.code for warning in warnings}
    gaps: list[str] = []
    if "missing_operation_capabilities" in codes:
        gaps.append("operation_capabilities_should_be_confirmed_or_use_explicit_eligibility")
    if "due_time_before_scheduled_end" in codes:
        gaps.append("due_dates_need_customer_confirmation_before_roi_claim")
    gaps.append("planner_decisions_required_for_policy_acceptance_rate")
    gaps.append("execution_outcomes_required_for_recovery_policy_graph_confidence")
    return gaps


def _optional_str(value) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _with_timezone(value, suffix: str) -> str | None:
    if value is None or value == "":
        return value
    text = str(value)
    if text.endswith("Z") or "+" in text[10:] or "-" in text[10:]:
        return text
    return f"{text}{suffix}"


_CLAIM_BOUNDARY = (
    "This produces solver-backed replay options for anonymized large-FJSP "
    "snapshots. It supports read-only replay and shadow preparation, but not "
    "ROI, autonomous writeback, or high-confidence policy learning without "
    "planner decisions and execution outcomes."
)
