"""Realistic single-workshop digital twin scenario runner."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.case import PreferenceProfile
from app.models.enums import IncidentSeverity, IncidentType, ReportSource
from app.models.incident import Incident
from app.models.planning import (
    ChangeoverRuleInput,
    DigitalTwinRunResponse,
    InitialScheduleOption,
    InitialScheduleRequest,
    PlanningMaterialRequirementInput,
    PlanningOperationInput,
    PlanningResourceInput,
    PlanningWorkOrderInput,
    ResourceCalendarWindowInput,
    ValueTrackingInput,
    WritebackPreviewRequest,
)
from app.models.schedule import ScheduleSnapshot
from app.services.digital_twin_utils import schedule_snapshot_from_initial_option
from app.services.enterprise_integration import EnterpriseIntegrationService
from app.services.hybrid_solver import HybridSolver
from app.services.impact_analysis_engine import ImpactAnalysisEngine
from app.services.initial_scheduler import InitialScheduler
from app.services.plan_quality_gate import PlanQualityGate
from app.services.simulation_sandbox import SimulationSandbox
from app.services.solver_policy_orchestrator import SolverPolicyOrchestrator
from app.services.strategy_selector import StrategySelector
from app.services.value_tracking import ValueTrackingService


class DigitalTwinRunner:
    """Builds and executes a realistic PoC digital twin scenario."""

    async def run_sample(self) -> DigitalTwinRunResponse:
        scenario_id = "reorch-poc-digital-twin-001"
        request = self._build_request()
        initial_response = await InitialScheduler().generate(request)
        selected = _select_balanced(initial_response.options)
        if selected is None:
            return DigitalTwinRunResponse(
                scenario_id=scenario_id,
                initial_schedule=initial_response,
                runbook=[
                    "Initial scheduling did not produce a feasible option. Check readiness blockers and constraint tightness.",
                ],
            )

        incident_time = request.planning_start + timedelta(hours=5, minutes=20)
        snapshot = schedule_snapshot_from_initial_option(
            request=request,
            option=selected,
            captured_at=incident_time,
        )
        resource_id = _resource_with_future_load(snapshot, incident_time)
        incident = Incident(
            incident_type=IncidentType.EQUIPMENT_FAILURE,
            external_event_id="DT-CNC-FAIL-001",
            occurred_at=incident_time,
            workshop_id=request.workshop_id,
            resource_id=resource_id,
            report_source=ReportSource.IOT,
            source_system="digital_twin",
            severity=IncidentSeverity.P2_HIGH,
            description=f"Digital twin: {resource_id} equipment alarm, estimated repair 180 minutes.",
            raw_payload={
                "alarm_code": "SPINDLE_OVERHEAT",
                "estimated_repair_time_minutes": 180,
            },
        )

        impact = await ImpactAnalysisEngine().analyze(incident, snapshot)
        strategy = await StrategySelector().select_strategy(
            impact_report=impact,
            similar_cases=[],
            preference_profile=PreferenceProfile(
                planner_id="digital-twin",
                strategy_preferences={"local_repair": 0.45, "global_reschedule": 0.35},
                adjustment_patterns=[],
                override_history=[],
                updated_at=incident_time,
            ),
            total_active_work_orders=len(snapshot.work_orders),
            estimated_repair_time_minutes=180,
        )
        bundle = await SolverPolicyOrchestrator().build_solver_policy(
            incident=incident,
            impact_report=impact,
            strategy=strategy,
            preference_profile=PreferenceProfile(
                planner_id="digital-twin",
                strategy_preferences={"local_repair": 0.45, "global_reschedule": 0.35},
                adjustment_patterns=[],
                override_history=[],
                updated_at=incident_time,
            ),
            similar_cases=[],
        )
        candidates = await HybridSolver().solve(
            bundle=bundle,
            impact_report=impact,
            snapshot=snapshot,
        )

        gate = PlanQualityGate()
        quality_gates = [gate.evaluate(plan) for plan in candidates]
        sandbox = SimulationSandbox()
        simulation_results = [
            sandbox.simulate(plan, snapshot).__dict__
            for plan in candidates
        ]
        writeback_preview = None
        if candidates:
            writeback_preview = EnterpriseIntegrationService().build_writeback_preview(
                WritebackPreviewRequest(
                    candidate_plan=candidates[0],
                    target_format="siemens",
                    only_adjusted_operations=True,
                )
            )

        value_report = ValueTrackingService().estimate(
            ValueTrackingInput(
                incident_count=1,
                baseline_decision_minutes=90,
                actual_decision_minutes=8,
                baseline_tardiness_minutes=240,
                actual_tardiness_minutes=90,
                baseline_changeovers=8,
                actual_changeovers=5,
                baseline_overtime_hours=6,
                actual_overtime_hours=2,
                planner_hourly_cost=150,
                tardiness_cost_per_minute=30,
                changeover_cost=600,
                overtime_hourly_cost=220,
            )
        )
        validation_evidence = {
            "source_refs": {
                "scenario_id": scenario_id,
                "workshop_id": request.workshop_id,
                "baseline_snapshot_id": str(snapshot.snapshot_id),
                "selected_initial_plan_id": str(selected.candidate_plan.plan_id),
                "incident_resource_id": resource_id,
                "affected_work_order_ids": [
                    item.work_order_id for item in impact.affected_work_orders
                ],
                "affected_operation_ids": [
                    item.operation_id for item in impact.affected_operations
                ],
                "quality_gate_plan_ids": [
                    str(report.plan_id) for report in quality_gates
                ],
            },
            "model_cost_proxy": {
                "external_llm_calls": 0,
                "estimated_input_tokens": 0,
                "estimated_output_tokens": 0,
                "deterministic_workflow_steps": 8,
                "solver_candidate_count": len(candidates),
                "writeback_instruction_count": (
                    writeback_preview.instruction_count if writeback_preview else 0
                ),
                "note": (
                    "Digital twin MVP uses deterministic services and solvers; "
                    "token telemetry starts when external LLM providers are enabled."
                ),
            },
            "replay_shadow_proxy": {
                "baseline_decision_minutes": 90,
                "digital_twin_decision_minutes": 8,
                "saved_decision_minutes": value_report.saved_decision_minutes,
                "reduced_tardiness_minutes": value_report.reduced_tardiness_minutes,
                "reduced_changeovers": value_report.reduced_changeovers,
                "reduced_overtime_hours": value_report.reduced_overtime_hours,
                "estimated_savings": value_report.estimated_savings,
            },
            "threshold_calibration": {
                "strategy_confidence": strategy.confidence,
                "quality_gate_confidence_levels": [
                    report.confidence_level for report in quality_gates
                ],
                "quality_gate_policies": [
                    report.recommendation_policy for report in quality_gates
                ],
                "execution_risk_scores": [
                    item["execution_risk_score"] for item in simulation_results
                ],
                "risk_flags": sorted(
                    {
                        flag
                        for item in simulation_results
                        for flag in item.get("risk_flags", [])
                    }
                ),
            },
            "audit_package_proxy": {
                "contains": [
                    "input_request",
                    "selected_initial_schedule",
                    "baseline_snapshot",
                    "incident",
                    "impact_report",
                    "strategy",
                    "candidate_plans",
                    "quality_gates",
                    "simulation_results",
                    "writeback_preview",
                    "value_report",
                ],
                "planner_confirmation_required": True,
                "production_writeback_enabled": False,
            },
        }

        return DigitalTwinRunResponse(
            scenario_id=scenario_id,
            initial_schedule=initial_response,
            selected_initial_option=selected,
            baseline_snapshot=snapshot,
            incident=incident.model_dump(mode="json"),
            impact_report=impact.model_dump(mode="json"),
            strategy=strategy.model_dump(mode="json"),
            reschedule_candidates=candidates,
            quality_gates=quality_gates,
            simulation_results=simulation_results,
            writeback_preview=writeback_preview,
            value_report=value_report,
            validation_evidence=validation_evidence,
            runbook=[
                "1. Import ERP/APS orders, operations, routings, resources, calendars, materials and changeover rules.",
                "2. Generate initial schedule options and select the balanced baseline.",
                "3. Capture a schedule snapshot at incident time.",
                "4. Ingest IoT/MES equipment-failure event.",
                "5. Run impact analysis, strategy selection and CP-SAT rescheduling.",
                "6. Pass candidate plans through quality gate and digital-twin simulation.",
                "7. Prepare MES writeback instructions for planner review.",
                "8. Track actual execution and convert the result into PoC ROI and reusable cases.",
            ],
        )

    @staticmethod
    def _build_request() -> InitialScheduleRequest:
        start = datetime(2026, 5, 12, 8, 0, tzinfo=timezone.utc)
        resources = [
            PlanningResourceInput(
                resource_id="CNC-01",
                name="CNC Makino A51",
                capabilities=["milling", "drilling"],
                is_bottleneck=True,
                cost_per_minute=6,
                criticality="bottleneck",
            ),
            PlanningResourceInput(
                resource_id="CNC-02",
                name="CNC Brother S700",
                capabilities=["milling", "drilling"],
                cost_per_minute=4,
            ),
            PlanningResourceInput(
                resource_id="LATHE-01",
                name="Turning Center",
                capabilities=["turning"],
                cost_per_minute=4,
            ),
            PlanningResourceInput(
                resource_id="HT-01",
                name="Heat Treatment Batch Furnace",
                capabilities=["heat_treatment"],
                is_bottleneck=True,
                cost_per_minute=8,
                criticality="bottleneck",
            ),
            PlanningResourceInput(
                resource_id="ASSY-01",
                name="Assembly Cell",
                capabilities=["assembly"],
                cost_per_minute=3,
            ),
            PlanningResourceInput(
                resource_id="QC-01",
                name="CMM Inspection",
                capabilities=["inspection"],
                cost_per_minute=5,
            ),
            PlanningResourceInput(
                resource_id="PACK-01",
                name="Packing Station",
                capabilities=["packing"],
                cost_per_minute=2,
            ),
        ]

        calendar = [
            ResourceCalendarWindowInput(
                resource_id="CNC-02",
                window_start=start + timedelta(hours=4),
                window_end=start + timedelta(hours=5, minutes=30),
                availability_type="unavailable",
                reason="planned tool calibration",
            ),
            ResourceCalendarWindowInput(
                resource_id="HT-01",
                window_start=start + timedelta(hours=8),
                window_end=start + timedelta(hours=9),
                availability_type="unavailable",
                reason="furnace temperature recovery",
            ),
        ]

        changeovers = []
        families = ["A", "B", "C"]
        for left in families:
            for right in families:
                if left == right:
                    continue
                changeovers.append(
                    ChangeoverRuleInput(
                        from_product_family=left,
                        to_product_family=right,
                        setup_minutes=35 if {left, right} == {"A", "C"} else 20,
                        cost=500,
                        resource_id=None,
                    )
                )

        def mat(material_id: str, hours: float = 0, status: str = "available"):
            return [
                PlanningMaterialRequirementInput(
                    material_id=material_id,
                    required_quantity=1,
                    available_at=start + timedelta(hours=hours),
                    status=status,
                )
            ]

        work_orders = [
            _wo(
                "WO-9001",
                "Servo housing",
                "A",
                start + timedelta(hours=13),
                3,
                [
                    _op("WO-9001-10", "WO-9001", 150, ["CNC-01", "CNC-02"], ["milling"], [], "A", mat("AL-6061")),
                    _op("WO-9001-20", "WO-9001", 70, ["QC-01"], ["inspection"], ["WO-9001-10"], "A", mat("CMM-FIXTURE")),
                    _op("WO-9001-30", "WO-9001", 90, ["ASSY-01"], ["assembly"], ["WO-9001-20"], "A", mat("SERVO-KIT", 3, "reserved")),
                    _op("WO-9001-40", "WO-9001", 40, ["PACK-01"], ["packing"], ["WO-9001-30"], "A", mat("PACK-A")),
                ],
            ),
            _wo(
                "WO-9002",
                "Pump shaft",
                "B",
                start + timedelta(hours=12),
                2,
                [
                    _op("WO-9002-10", "WO-9002", 120, ["LATHE-01"], ["turning"], [], "B", mat("STEEL-42CRMO")),
                    _op("WO-9002-20", "WO-9002", 110, ["HT-01"], ["heat_treatment"], ["WO-9002-10"], "B", mat("HT-BASKET")),
                    _op("WO-9002-30", "WO-9002", 55, ["QC-01"], ["inspection"], ["WO-9002-20"], "B", mat("CMM-FIXTURE")),
                    _op("WO-9002-40", "WO-9002", 35, ["PACK-01"], ["packing"], ["WO-9002-30"], "B", mat("PACK-B")),
                ],
            ),
            _wo(
                "WO-9003",
                "Valve block urgent",
                "C",
                start + timedelta(hours=10),
                4,
                [
                    _op("WO-9003-10", "WO-9003", 95, ["CNC-01", "CNC-02"], ["milling"], [], "C", mat("AL-7075")),
                    _op("WO-9003-20", "WO-9003", 45, ["QC-01"], ["inspection"], ["WO-9003-10"], "C", mat("CMM-FIXTURE")),
                    _op("WO-9003-30", "WO-9003", 65, ["ASSY-01"], ["assembly"], ["WO-9003-20"], "C", mat("SEAL-KIT", 4, "delayed")),
                ],
            ),
            _wo(
                "WO-9004",
                "Robot joint bracket",
                "A",
                start + timedelta(hours=17),
                1,
                [
                    _op("WO-9004-10", "WO-9004", 180, ["CNC-01", "CNC-02"], ["milling"], [], "A", mat("AL-6061")),
                    _op("WO-9004-20", "WO-9004", 100, ["ASSY-01"], ["assembly"], ["WO-9004-10"], "A", mat("BEARING-KIT", 5, "delayed")),
                    _op("WO-9004-30", "WO-9004", 60, ["QC-01"], ["inspection"], ["WO-9004-20"], "A", mat("CMM-FIXTURE")),
                ],
            ),
            _wo(
                "WO-9005",
                "Connector plate",
                "C",
                start + timedelta(hours=15),
                1,
                [
                    _op("WO-9005-10", "WO-9005", 105, ["CNC-02"], ["milling"], [], "C", mat("AL-7075")),
                    _op("WO-9005-20", "WO-9005", 35, ["PACK-01"], ["packing"], ["WO-9005-10"], "C", mat("PACK-C")),
                ],
            ),
        ]

        return InitialScheduleRequest(
            workshop_id="WS-HMLV-01",
            planning_start=start,
            resources=resources,
            resource_calendar=calendar,
            changeover_rules=changeovers,
            work_orders=work_orders,
            time_budget_seconds=8,
        )


def _wo(
    work_order_id: str,
    product_name: str,
    family: str,
    due_date: datetime,
    priority: int,
    operations: list[PlanningOperationInput],
) -> PlanningWorkOrderInput:
    return PlanningWorkOrderInput(
        work_order_id=work_order_id,
        product_name=product_name,
        product_family=family,
        due_date=due_date,
        priority=priority,
        operations=operations,
    )


def _op(
    operation_id: str,
    work_order_id: str,
    duration: int,
    resources: list[str],
    capabilities: list[str],
    predecessors: list[str],
    family: str,
    materials: list[PlanningMaterialRequirementInput],
) -> PlanningOperationInput:
    return PlanningOperationInput(
        operation_id=operation_id,
        work_order_id=work_order_id,
        duration_minutes=duration,
        eligible_resource_ids=resources,
        required_capabilities=capabilities,
        predecessor_ids=predecessors,
        product_family=family,
        material_requirements=materials,
    )


def _select_balanced(options: list[InitialScheduleOption]) -> InitialScheduleOption | None:
    for option in options:
        if option.goal_mode == "balanced":
            return option
    return options[0] if options else None


def _resource_with_future_load(snapshot: ScheduleSnapshot, incident_time: datetime) -> str:
    load: dict[str, float] = {}
    for wo in snapshot.work_orders:
        for op in wo.operations:
            if op.end_time <= incident_time:
                continue
            minutes = max(0.0, (op.end_time - max(op.start_time, incident_time)).total_seconds() / 60)
            load[op.resource_id] = load.get(op.resource_id, 0.0) + minutes
    cnc_load = {rid: minutes for rid, minutes in load.items() if rid.startswith("CNC-")}
    if cnc_load:
        return max(cnc_load, key=cnc_load.get)
    return max(load, key=load.get) if load else "CNC-01"
