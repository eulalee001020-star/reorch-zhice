"""Large-scale flexible shop capability assessment and replay services."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone

from app.models.flexible_shop import (
    BenchmarkResult,
    CapabilityStatus,
    CounterfactualReplayMatrixRequest,
    CounterfactualReplayMatrixResponse,
    CounterfactualReplayResult,
    CounterfactualReplayRunCase,
    CounterfactualReplayRunRequest,
    CounterfactualReplayRunResponse,
    DataSourceReadinessCheck,
    DecompositionSolveRequest,
    DecompositionSolveResponse,
    DecompositionSubproblem,
    DynamicIncidentScenario,
    DynamicReschedulingPlanRequest,
    DynamicReschedulingPlanResponse,
    ExecutionFeedbackIngestionRequest,
    ExecutionFeedbackIngestionResponse,
    ExecutionPolicyFeedback,
    FlexibleOperation,
    FlexibleShopBenchmarkRequest,
    FlexibleShopBenchmarkResponse,
    FlexibleShopCapabilityRequest,
    FlexibleShopCapabilityResponse,
    FlexibleShopContext,
    HistoricalRecoveryCase,
    IncidentCategory,
    IncidentRecoveryPlan,
    LargeFjspConstraintModelRequest,
    LargeFjspConstraintModelResponse,
    MultiIncidentRecoveryRequest,
    MultiIncidentRecoveryResponse,
    PolicyOutcomeObservation,
    ProductionWritebackSafetyRequest,
    ProductionWritebackSafetyResponse,
    PolicyEffectivenessCell,
    RealDataIntegrationRequest,
    RealDataIntegrationResponse,
    RecoveryPolicyCandidate,
    SolverStrategyPlan,
    WritebackSafetyGateCheck,
    ConstraintFamilyCompilation,
)


_INCIDENT_POLICIES: dict[IncidentCategory, list[str]] = {
    "equipment_failure": [
        "wait_and_shift",
        "local_repair",
        "alternative_resource_reassignment",
        "rolling_window_repair",
        "controlled_global_reschedule",
    ],
    "rush_order": [
        "rush_insertion",
        "priority_swap",
        "overtime_what_if",
        "outsourcing_what_if",
        "manual_escalation",
    ],
    "material_shortage": [
        "material_substitution",
        "resequence_unblocked_operations",
        "procurement_eta_repair",
        "alternative_bom_route",
        "manual_escalation",
    ],
    "quality_exception": [
        "quality_hold_freeze",
        "rework_routing",
        "quarantine_and_resequence",
        "downstream_block_release",
    ],
    "labor_absence": [
        "skill_reassignment",
        "shift_swap",
        "overtime_approval",
        "manual_escalation",
    ],
    "tooling_conflict": [
        "tooling_reallocation",
        "setup_delay_repair",
        "alternative_tooling_route",
        "manual_escalation",
    ],
    "batch_rework": [
        "batch_split",
        "rework_route_insertion",
        "capacity_rebalance",
        "controlled_global_reschedule",
    ],
}


_INCIDENT_REQUIRED_CONSTRAINTS: dict[IncidentCategory, list[str]] = {
    "equipment_failure": ["resource_calendar", "alternative_resources", "frozen_zone"],
    "rush_order": ["priority_rules", "changeover_matrix", "buffer_capacity"],
    "material_shortage": ["material_availability", "substitute_material", "transport_eta"],
    "quality_exception": ["quality_hold", "rework_route", "traceability"],
    "labor_absence": ["skill_calendar", "approval_policy"],
    "tooling_conflict": ["tooling_availability", "setup_matrix"],
    "batch_rework": ["batch_route", "quality_hold", "buffer_capacity"],
}


class FlexibleShopCapabilityService:
    """Assesses whether a large flexible shop is ready for replay/shadow/pilot."""

    def assess(
        self, request: FlexibleShopCapabilityRequest
    ) -> FlexibleShopCapabilityResponse:
        statuses = [
            self._data_model_status(request.context),
            self._constraint_status(request.context),
            self._solver_status(request.context),
            self._dynamic_status(request),
            self._performance_status(request),
            self._integration_status(request.context),
            self._writeback_status(request),
            self._policy_graph_status(request),
        ]
        if any(status.status == "missing" and status.blockers for status in statuses):
            overall = "blocked"
        elif request.sandbox_writeback_ready and request.shadow_case_count >= 10:
            overall = "pilot_ready"
        elif request.historical_replay_case_count >= 10:
            overall = "shadow_ready"
        else:
            overall = "replay_only"
        return FlexibleShopCapabilityResponse(
            site_id=request.context.site_id,
            overall_status=overall,
            statuses=statuses,
            claim_boundary=(
                "This assessment validates large-shop readiness structure. "
                "It does not prove production ROI or unattended writeback."
            ),
        )

    @staticmethod
    def _data_model_status(context: FlexibleShopContext) -> CapabilityStatus:
        blockers: list[str] = []
        warnings: list[str] = []
        checks = {
            "multi_workshop": len(context.workshops) >= 1,
            "machine_groups": bool(context.machine_groups),
            "resources": bool(context.resources),
            "work_orders": bool(context.work_orders),
            "alternative_modes": any(
                len(operation.modes) >= 2
                for work_order in context.work_orders
                for operation in work_order.operations
            ),
            "wip": bool(context.wip_items),
            "frozen_zone": bool(context.frozen_zones)
            or any(
                operation.frozen_until is not None
                for work_order in context.work_orders
                for operation in work_order.operations
            ),
            "batch_or_rework": any(
                operation.batch_id or operation.rework_of_operation_id
                for work_order in context.work_orders
                for operation in work_order.operations
            ),
        }
        for name, passed in checks.items():
            if not passed:
                if name in {"resources", "work_orders"}:
                    blockers.append(f"missing_{name}")
                else:
                    warnings.append(f"missing_{name}")
        return _status(
            "data_model",
            checks,
            blockers,
            warnings,
            [
                "Add route alternatives, WIP locations, batch/rework flags, and frozen-zone markers.",
            ],
        )

    @staticmethod
    def _constraint_status(context: FlexibleShopContext) -> CapabilityStatus:
        constraints = context.constraints
        checks = {
            "material": bool(constraints.materials),
            "skill": bool(constraints.skills),
            "tooling": bool(constraints.tooling),
            "changeover": bool(constraints.changeovers),
            "quality_hold": bool(constraints.quality_holds),
            "outsourcing": bool(constraints.outsourcing),
            "transport_amr": bool(constraints.transport),
            "buffer": bool(constraints.buffers),
        }
        warnings = [f"missing_{name}_constraint" for name, passed in checks.items() if not passed]
        return _status(
            "constraint_system",
            checks,
            [],
            warnings,
            [
                "Calibrate material, skill, tooling, changeover, quality, outsourcing, transport/AMR, and buffer constraints.",
            ],
        )

    @staticmethod
    def _solver_status(context: FlexibleShopContext) -> CapabilityStatus:
        operation_count = _operation_count(context)
        has_bottlenecks = any(group.is_bottleneck for group in context.machine_groups) or any(
            resource.is_bottleneck for resource in context.resources
        )
        checks = {
            "rolling_window_required": operation_count > 500,
            "decomposition_required": operation_count > 1000,
            "bottleneck_rank_available": has_bottlenecks,
            "warm_start_possible": bool(context.wip_items) or bool(context.frozen_zones),
            "timeout_feasible_policy_required": True,
        }
        warnings = []
        if operation_count > 1000 and not has_bottlenecks:
            warnings.append("large_instance_without_bottleneck_marks")
        return _status(
            "solver_strategy",
            checks,
            [],
            warnings,
            [
                "Use bottleneck-first decomposition, rolling windows, LNS/ALNS neighborhoods, warm starts, and best-known-feasible fallback.",
            ],
        )

    @staticmethod
    def _dynamic_status(request: FlexibleShopCapabilityRequest) -> CapabilityStatus:
        target = set(request.incident_types_to_support)
        supported = set(_INCIDENT_POLICIES)
        checks = {incident_type: incident_type in target for incident_type in supported}
        warnings = [
            f"not_in_initial_scope_{incident_type}"
            for incident_type, included in checks.items()
            if not included
        ]
        return _status(
            "dynamic_rescheduling",
            checks,
            [],
            warnings,
            [
                "Start with one high-frequency incident type, then expand to material, quality, labor, tooling, and batch rework.",
            ],
        )

    @staticmethod
    def _performance_status(request: FlexibleShopCapabilityRequest) -> CapabilityStatus:
        targets = request.benchmark_operation_targets
        checks = {
            "1k_ops_target": any(value >= 1000 for value in targets),
            "5k_ops_target": any(value >= 5000 for value in targets),
            "10k_ops_target": any(value >= 10000 for value in targets),
            "p95_latency_required": True,
            "concurrent_incident_required": True,
        }
        warnings = [f"missing_benchmark_target_{label}" for label, passed in checks.items() if not passed]
        return _status(
            "performance_engineering",
            checks,
            [],
            warnings,
            [
                "Run synthetic 1k/5k/10k operation benchmarks, then repeat on customer snapshots.",
            ],
        )

    @staticmethod
    def _integration_status(context: FlexibleShopContext) -> CapabilityStatus:
        required = {"ERP", "MES", "WMS", "QMS", "IoT"}
        available = {key.upper() for key in context.integration_sources}
        checks = {source: source in available for source in required}
        blockers = [
            f"missing_{source.lower()}_source"
            for source, passed in checks.items()
            if not passed and source in {"ERP", "MES"}
        ]
        warnings = [
            f"missing_{source.lower()}_source"
            for source, passed in checks.items()
            if not passed and source not in {"ERP", "MES"}
        ]
        return _status(
            "data_integration",
            checks,
            blockers,
            warnings,
            [
                "Add incremental sync, ID crosswalk, source lineage, and freshness checks for ERP/MES/WMS/QMS/IoT.",
            ],
        )

    @staticmethod
    def _writeback_status(request: FlexibleShopCapabilityRequest) -> CapabilityStatus:
        checks = {
            "sandbox_ready": request.sandbox_writeback_ready,
            "approval_roles": bool(request.approved_writeback_roles),
            "idempotency_required": True,
            "rollback_required": True,
            "audit_required": True,
        }
        blockers = []
        if not request.sandbox_writeback_ready:
            blockers.append("sandbox_writeback_not_ready")
        if not request.approved_writeback_roles:
            blockers.append("missing_writeback_approval_roles")
        return _status(
            "writeback_safety",
            checks,
            blockers,
            [],
            [
                "Complete sandbox, approval flow, idempotency key, rollback, compensation, permission, and audit tests.",
            ],
        )

    @staticmethod
    def _policy_graph_status(request: FlexibleShopCapabilityRequest) -> CapabilityStatus:
        checks = {
            "historical_replay_10_plus": request.historical_replay_case_count >= 10,
            "shadow_cases_10_plus": request.shadow_case_count >= 10,
            "execution_feedback": request.execution_feedback_case_count > 0,
            "counterfactual_replay_required": True,
            "strategy_matrix_required": True,
        }
        warnings = [name for name, passed in checks.items() if not passed]
        return _status(
            "recovery_policy_graph",
            checks,
            [],
            warnings,
            [
                "Collect real historical replay, shadow decisions, execution outcomes, and build policy effectiveness matrix.",
            ],
        )


class DynamicReschedulingPlanner:
    """Builds incident-specific large-shop recovery plans."""

    def plan(
        self, request: DynamicReschedulingPlanRequest
    ) -> DynamicReschedulingPlanResponse:
        operation_count = _operation_count(request.context)
        global_strategy = _solver_strategy(
            operation_count=operation_count,
            has_bottleneck=_has_bottleneck(request.context),
            timeout_seconds=request.solve_timeout_seconds,
            incident_count=len(request.incidents),
        )
        plans = [
            self._plan_one(request.context, incident, global_strategy)
            for incident in request.incidents
        ]
        return DynamicReschedulingPlanResponse(
            plans=plans,
            global_solver_strategy=global_strategy,
            claim_boundary=(
                "Plans route large-shop incidents to policies and solver strategy. "
                "Customer production use still requires replay/shadow validation."
            ),
        )

    def _plan_one(
        self,
        context: FlexibleShopContext,
        incident: DynamicIncidentScenario,
        strategy: SolverStrategyPlan,
    ) -> IncidentRecoveryPlan:
        constraints = _INCIDENT_REQUIRED_CONSTRAINTS[incident.incident_type]
        blockers = _constraint_blockers(context, incident.incident_type)
        fingerprint = {
            "site_id": context.site_id,
            "operation_count": _operation_count(context),
            "workshop_count": len(context.workshops),
            "resource_count": len(context.resources),
            "incident_type": incident.incident_type,
            "severity": incident.severity,
            "affected_operation_count": len(incident.affected_operation_ids),
            "has_bottleneck": _has_bottleneck(context),
        }
        if incident.resource_id:
            fingerprint["resource_id"] = incident.resource_id
        if incident.material_id:
            fingerprint["material_id"] = incident.material_id
        return IncidentRecoveryPlan(
            incident_id=incident.incident_id,
            incident_type=incident.incident_type,
            context_fingerprint=fingerprint,
            recovery_policies=_INCIDENT_POLICIES[incident.incident_type],
            required_constraints=constraints,
            required_gates=[
                "DataGate",
                "ConstraintGate",
                "QualityGate",
                "EvidenceGate",
                "PlannerConfirmationGate",
                "WritebackGate",
            ],
            solver_strategy=strategy,
            blockers=blockers,
        )


class FlexibleShopBenchmarkService:
    """Runs a deterministic large-shop benchmark proxy.

    The benchmark intentionally measures routing/gating scale behavior, not
    customer production solve quality. Real CP-SAT/LNS timings must be captured
    on customer snapshots.
    """

    def run(
        self, request: FlexibleShopBenchmarkRequest
    ) -> FlexibleShopBenchmarkResponse:
        results = [self._run_target(target, request.solve_timeout_seconds) for target in request.targets]
        return FlexibleShopBenchmarkResponse(
            generated_at=datetime.now(tz=timezone.utc),
            results=results,
            claim_boundary=(
                "Synthetic benchmark estimates routing/gating scalability. "
                "It is not a substitute for customer 1k/5k/10k snapshot solver benchmarks."
            ),
        )

    @staticmethod
    def _run_target(target, timeout_seconds: float) -> BenchmarkResult:
        n = target.operation_count
        r = target.resource_count
        c = target.concurrent_incidents
        log_factor = math.log2(max(n, 2))
        routing_ms = round(8.0 + 0.006 * n + 0.8 * log_factor + 2.5 * c, 2)
        gate_ms = round(5.0 + 0.0035 * n + 0.3 * r + 1.5 * c, 2)
        budget = min(timeout_seconds, max(5.0, 0.012 * n / max(c, 1)))
        if n >= 5000:
            strategy = "bottleneck_first_decomposition + rolling_window + LNS/ALNS + warm_start"
        elif n >= 1000:
            strategy = "rolling_window + local_repair + CP-SAT_subproblem"
        else:
            strategy = "direct_local_repair + CP-SAT"
        pass_shadow = routing_ms < 250.0 and gate_ms < 250.0 and budget <= timeout_seconds
        notes = [
            "routing/gating proxy only",
            "capture real P95 CP-SAT/LNS latency on customer snapshots before production use",
        ]
        if n >= 10000:
            notes.append("requires decomposition and best-known-feasible timeout policy")
        return BenchmarkResult(
            operation_count=n,
            resource_count=r,
            concurrent_incidents=c,
            benchmark_mode="synthetic_routing_gate_proxy",
            p95_routing_latency_ms=routing_ms,
            p95_gate_latency_ms=gate_ms,
            recommended_solver_budget_seconds=round(budget, 2),
            recommended_strategy=strategy,
            pass_shadow_threshold=pass_shadow,
            notes=notes,
        )


class CounterfactualReplayMatrixService:
    """Aggregates counterfactual replay observations into strategy matrix cells."""

    def build(
        self, request: CounterfactualReplayMatrixRequest
    ) -> CounterfactualReplayMatrixResponse:
        grouped: dict[tuple[str, str], list] = defaultdict(list)
        context_counts: dict[str, int] = defaultdict(int)
        for case in request.cases:
            context_counts[case.context_key] += 1
            for observation in case.observations:
                grouped[(case.context_key, observation.policy_type)].append(observation)

        cells: list[PolicyEffectivenessCell] = []
        insufficient_contexts = sorted(
            context for context, count in context_counts.items() if count < request.min_sample_count
        )
        for (context_key, policy_type), observations in sorted(grouped.items()):
            sample_count = len(observations)
            total_weight = sum(item.sample_weight for item in observations) or 1.0
            feasible = sum(item.sample_weight for item in observations if item.hard_feasible) / total_weight
            accepted = sum(item.sample_weight for item in observations if item.accepted_by_planner) / total_weight
            failed = sum(item.sample_weight for item in observations if item.execution_failed) / total_weight
            delay = sum(item.delay_delta_minutes * item.sample_weight for item in observations) / total_weight
            perturb = sum(item.perturbation_cost * item.sample_weight for item in observations) / total_weight
            cells.append(
                PolicyEffectivenessCell(
                    context_key=context_key,
                    policy_type=policy_type,
                    sample_count=sample_count,
                    feasible_rate=round(feasible, 4),
                    planner_acceptance_rate=round(accepted, 4),
                    mean_delay_delta_minutes=round(delay, 2),
                    mean_perturbation_cost=round(perturb, 2),
                    execution_failure_rate=round(failed, 4),
                    confidence_level=_confidence(sample_count, context_key not in insufficient_contexts),
                )
            )
        return CounterfactualReplayMatrixResponse(
            cells=cells,
            insufficient_contexts=insufficient_contexts,
            claim_boundary=(
                "Policy matrix is only as strong as replay/shadow/execution samples. "
                "Low-confidence cells must not drive autonomous writeback."
            ),
        )


class RealDataIntegrationService:
    """Checks whether real customer sources can support replay and shadow mode."""

    def assess(
        self, request: RealDataIntegrationRequest
    ) -> RealDataIntegrationResponse:
        by_source = {source.source_system: source for source in request.sources}
        source_checks = [
            self._check_source(source_system, by_source.get(source_system), request)
            for source_system in request.required_sources
        ]
        blockers = [
            blocker
            for check in source_checks
            for blocker in check.blockers
        ]
        mock_checks = [
            check for check in source_checks if check.status == "mock_only"
        ]
        canonical_entities = _canonical_entities_present(request.context)
        id_alignment_score = _id_alignment_score(request)
        lineage_score = _lineage_score(request)
        freshness_status = _freshness_status(request)

        if blockers:
            overall = "blocked"
        elif mock_checks:
            overall = "mock_only"
        elif id_alignment_score >= 0.8 and lineage_score >= 0.6:
            overall = "shadow_ready"
        else:
            overall = "ingestion_ready"

        return RealDataIntegrationResponse(
            overall_status=overall,
            source_checks=source_checks,
            canonical_entities_present=canonical_entities,
            id_alignment_score=round(id_alignment_score, 4),
            lineage_score=round(lineage_score, 4),
            freshness_status=freshness_status,
            next_actions=_integration_next_actions(source_checks, id_alignment_score),
            claim_boundary=(
                "This validates source contracts and ID lineage for real-data "
                "ingestion. It does not prove production scheduling quality."
            ),
        )

    @staticmethod
    def _check_source(
        source_system: str,
        source,
        request: RealDataIntegrationRequest,
    ) -> DataSourceReadinessCheck:
        if source is None:
            blockers = []
            if source_system in {"ERP", "MES"}:
                blockers.append(f"missing_required_{source_system.lower()}_source")
            return DataSourceReadinessCheck(
                source_system=source_system,
                status="missing",
                blockers=blockers,
                warnings=[f"missing_{source_system.lower()}_source"],
            )

        blockers: list[str] = []
        warnings: list[str] = []
        if source.connection_mode == "mock" and not request.allow_mock_sources:
            blockers.append(f"{source_system.lower()}_is_mock_source")
        if source.sample_record_count <= 0:
            warnings.append(f"{source_system.lower()}_has_no_sample_records")
        if not source.incremental_key and source.connection_mode != "csv_drop":
            warnings.append(f"{source_system.lower()}_missing_incremental_key")
        if not source.id_namespace:
            warnings.append(f"{source_system.lower()}_missing_id_namespace")
        if not source.lineage_fields:
            warnings.append(f"{source_system.lower()}_missing_lineage_fields")

        status = "ready"
        if source.connection_mode == "mock":
            status = "mock_only"
        elif warnings:
            status = "partial"

        return DataSourceReadinessCheck(
            source_system=source_system,
            status=status,
            blockers=blockers,
            warnings=warnings,
            canonical_entities=_source_entities(source_system),
        )


class LargeFjspConstraintCompiler:
    """Compiles a large flexible job shop context into constraint families."""

    def compile(
        self, request: LargeFjspConstraintModelRequest
    ) -> LargeFjspConstraintModelResponse:
        context = request.context
        operations = _all_operations(context)
        modes = [mode for operation in operations for mode in operation.modes]
        blockers: list[str] = []
        warnings: list[str] = []
        if not operations:
            blockers.append("missing_operations")
        if not context.resources:
            blockers.append("missing_resources")
        if not modes:
            blockers.append("missing_operation_modes")

        families = [
            _compile_family("assignment", bool(modes), len(modes), 0),
            _compile_family(
                "precedence",
                any(operation.predecessor_ids for operation in operations),
                sum(len(operation.predecessor_ids) for operation in operations),
                0,
            ),
            _compile_family("resource_no_overlap", bool(context.resources), len(operations), 0),
            _compile_family(
                "material_availability",
                bool(context.constraints.materials),
                sum(len(operation.material_ids) for operation in operations),
                0,
            ),
            _compile_family(
                "skill_capacity",
                bool(context.constraints.skills),
                sum(len(mode.required_skill_codes) for mode in modes),
                0,
            ),
            _compile_family(
                "tooling_capacity",
                bool(context.constraints.tooling),
                sum(len(mode.required_tooling_ids) for mode in modes),
                0,
            ),
            _compile_family(
                "changeover_matrix",
                bool(context.constraints.changeovers),
                len(context.constraints.changeovers),
                1 if request.include_soft_objectives else 0,
            ),
            _compile_family(
                "quality_hold",
                bool(context.constraints.quality_holds),
                len(context.constraints.quality_holds),
                0,
            ),
            _compile_family(
                "transport_amr",
                bool(context.constraints.transport),
                len(context.constraints.transport),
                0,
            ),
            _compile_family(
                "buffer_capacity",
                bool(context.constraints.buffers),
                len(context.constraints.buffers),
                0,
            ),
            _compile_family(
                "frozen_wip",
                bool(context.frozen_zones or context.wip_items),
                len(context.frozen_zones) + len(context.wip_items),
                0,
            ),
        ]

        warnings.extend(
            f"partial_constraint_family_{family.family}"
            for family in families
            if family.coverage_score < 1.0
        )
        compile_status = "compiled"
        if blockers:
            compile_status = "blocked"
        elif warnings:
            compile_status = "partial"

        return LargeFjspConstraintModelResponse(
            compile_status=compile_status,
            variable_counts={
                "operations": len(operations),
                "operation_modes": len(modes),
                "resources": len(context.resources),
                "work_orders": len(context.work_orders),
                "predecessor_arcs": sum(
                    len(operation.predecessor_ids) for operation in operations
                ),
            },
            constraint_families=families,
            hard_constraints=[
                "each operation selects exactly one feasible mode",
                "operation precedence and release times",
                "resource no-overlap and calendar blocks",
                "material, skill, tooling, quality-hold, transport, buffer gates",
                "frozen-zone and WIP anchors",
            ],
            soft_objectives=_soft_objectives(request.include_soft_objectives),
            blockers=blockers,
            warnings=warnings,
            claim_boundary=(
                "This is a deterministic constraint compilation summary. "
                "Production feasibility still requires solving customer snapshots."
            ),
        )


class DecompositionDynamicSolver:
    """Builds a decomposed dynamic rescheduling solve route."""

    def plan(self, request: DecompositionSolveRequest) -> DecompositionSolveResponse:
        context = request.context
        operation_count = _operation_count(context)
        blockers: list[str] = []
        if operation_count == 0:
            blockers.append("missing_operations")
        if not context.resources:
            blockers.append("missing_resources")
        if not request.incidents:
            blockers.append("missing_incidents")

        strategy = _solver_strategy(
            operation_count=operation_count,
            has_bottleneck=_has_bottleneck(context),
            timeout_seconds=request.timeout_seconds,
            incident_count=len(request.incidents),
        )
        frozen_operation_ids = _frozen_operation_ids(context)
        if blockers:
            return DecompositionSolveResponse(
                solve_status="blocked",
                global_strategy=strategy,
                subproblems=[],
                frozen_operation_ids=frozen_operation_ids,
                warm_start_source="unavailable",
                fallback_policy="manual_planner_review",
                estimated_parallelism=1,
                blockers=blockers,
                claim_boundary=(
                    "Blocked before solve-route construction. Customer data must "
                    "pass DataGate and ConstraintGate."
                ),
            )

        subproblems = _build_subproblems(context, request, strategy)
        status = "feasible_plan_route"
        if any(problem.solver_backend == "manual_review" for problem in subproblems):
            status = "reference_only"

        return DecompositionSolveResponse(
            solve_status=status,
            global_strategy=strategy,
            subproblems=subproblems,
            frozen_operation_ids=frozen_operation_ids,
            warm_start_source="current_schedule_snapshot + WIP + frozen_zone",
            fallback_policy=(
                "return_best_known_feasible"
                if request.require_feasible_fallback
                else "reference_only_on_timeout"
            ),
            estimated_parallelism=max(1, min(4, len(subproblems))),
            blockers=[],
            claim_boundary=(
                "This constructs the decomposition and solver budget route. "
                "It does not claim the route has been accepted on a live plant."
            ),
        )


class MultiIncidentRecoveryStrategyService:
    """Expands each incident into policy candidates with roles and gates."""

    def build(
        self, request: MultiIncidentRecoveryRequest
    ) -> MultiIncidentRecoveryResponse:
        candidates: list[RecoveryPolicyCandidate] = []
        blockers: list[str] = []
        for incident in request.incidents:
            blockers.extend(_constraint_blockers(request.context, incident.incident_type))
            for policy in _INCIDENT_POLICIES[incident.incident_type]:
                candidates.append(
                    RecoveryPolicyCandidate(
                        incident_id=incident.incident_id,
                        incident_type=incident.incident_type,
                        policy_type=policy,
                        when_to_use=_policy_when_to_use(policy),
                        hard_gates=_INCIDENT_REQUIRED_CONSTRAINTS[
                            incident.incident_type
                        ],
                        expected_tradeoffs=_policy_tradeoffs(policy),
                        ai_role=(
                            "parse incident, retrieve similar cases, explain "
                            "tradeoffs, and structure planner feedback"
                        ),
                        solver_role=(
                            "verify feasibility, generate candidate timing/resource "
                            "changes, and report constraint violations"
                        ),
                        human_role=(
                            "approve, adjust, reject, or mark the policy as "
                            "reference-only before writeback"
                        ),
                    )
                )

        return MultiIncidentRecoveryResponse(
            candidates=candidates,
            conflict_resolution_order=[
                "safety_and_quality_hold",
                "frozen_zone_and_released_WIP",
                "customer_due_date_priority",
                "bottleneck_capacity",
                "material_and_tooling_availability",
                "minimize_schedule_perturbation",
            ],
            blockers=sorted(set(blockers)),
            claim_boundary=(
                "Recovery candidates are policy options, not autonomous decisions. "
                "QualityGate and planner confirmation remain mandatory."
            ),
        )


class CounterfactualReplayRunner:
    """Runs deterministic counterfactual policy scoring for historical cases."""

    def run(
        self, request: CounterfactualReplayRunRequest
    ) -> CounterfactualReplayRunResponse:
        results: list[CounterfactualReplayResult] = []
        matrix_cases = []
        for case in request.cases:
            policies = case.policies_to_test or _INCIDENT_POLICIES[case.incident_type]
            observations: list[PolicyOutcomeObservation] = []
            for index, policy in enumerate(policies):
                result = _score_counterfactual_policy(case, policy, index)
                results.append(result)
                observations.append(
                    PolicyOutcomeObservation(
                        policy_type=policy,
                        hard_feasible=result.hard_feasible,
                        accepted_by_planner=False,
                        delay_delta_minutes=result.predicted_delay_delta_minutes,
                        perturbation_cost=result.perturbation_cost,
                        execution_failed=result.execution_risk_score >= 0.8,
                    )
                )
            matrix_cases.append(
                _historical_case_from_observations(case, observations)
            )

        matrix = CounterfactualReplayMatrixService().build(
            CounterfactualReplayMatrixRequest(
                cases=matrix_cases,
                min_sample_count=request.min_sample_count,
            )
        )
        return CounterfactualReplayRunResponse(
            results=results,
            matrix=matrix,
            claim_boundary=(
                "Replay scoring is deterministic and audit-friendly. Real confidence "
                "requires historical snapshots, planner review, and execution outcomes."
            ),
        )


class ProductionWritebackSafetyService:
    """Evaluates controlled writeback readiness before touching production systems."""

    def evaluate(
        self, request: ProductionWritebackSafetyRequest
    ) -> ProductionWritebackSafetyResponse:
        checks = [
            _gate("SandboxMode", request.sandbox_mode, "sandbox_mode_required"),
            _gate("ApprovalChain", bool(request.approval_chain), "missing_approval_chain"),
            _gate("Idempotency", bool(request.idempotency_key), "missing_idempotency_key"),
            _gate("Rollback", bool(request.rollback_plan_ref), "missing_rollback_plan"),
            _gate(
                "Compensation",
                bool(request.compensation_steps),
                "missing_compensation_steps",
            ),
            _gate("Permission", bool(request.permission_scope), "missing_permission_scope"),
            _gate("Audit", bool(request.audit_trace_ref), "missing_audit_trace"),
            _gate("SourceRefs", request.source_ref_count > 0, "missing_source_refs"),
            _gate(
                "PolicyConfidence",
                request.policy_confidence_level in {"medium", "high"},
                "low_policy_confidence",
            ),
        ]
        blocking_reasons = [
            check.blocker for check in checks if not check.passed and check.blocker
        ]
        if blocking_reasons:
            status = "blocked"
        elif request.policy_confidence_level == "high":
            status = "allow_controlled_writeback"
        elif request.sandbox_mode:
            status = "allow_sandbox_dry_run"
        else:
            status = "dry_run_only"

        return ProductionWritebackSafetyResponse(
            gate_status=status,
            checks=checks,
            blocking_reasons=blocking_reasons,
            required_approvals=request.approval_chain,
            idempotency_key=request.idempotency_key,
            claim_boundary=(
                "Writeback requires sandbox-first execution, approvals, idempotency, "
                "rollback, compensation, permissions, and audit. This gate does not "
                "authorize unattended autonomous writeback."
            ),
        )


class ExecutionFeedbackService:
    """Ingests physical execution signals into policy-graph feedback updates."""

    def ingest(
        self, request: ExecutionFeedbackIngestionRequest
    ) -> ExecutionFeedbackIngestionResponse:
        if not request.signals:
            return ExecutionFeedbackIngestionResponse(
                execution_status="insufficient_signals",
                feedback_updates=[],
                observed_signal_count=0,
                deviation_summary={"max_abs_deviation_minutes": 0, "blocked_events": 0},
                claim_boundary=(
                    "No execution signal was provided; no policy update can be made."
                ),
            )

        max_abs_deviation = max(
            abs(signal.deviation_minutes) for signal in request.signals
        )
        blocked_events = sum(
            1
            for signal in request.signals
            if signal.event_type in {"blocked", "rework", "rejected", "delay_alert"}
        )
        quality_events = sum(
            1
            for signal in request.signals
            if signal.event_type in {"rework", "rejected"}
            or signal.quality_state in {"hold", "rejected"}
        )
        if quality_events:
            status = "quality_hold"
            outcome = "failed_in_execution"
            weight_delta = -0.3
        elif blocked_events:
            status = "blocked"
            outcome = "needs_recalibration"
            weight_delta = -0.2
        elif max_abs_deviation > 30:
            status = "deviated"
            outcome = "needs_recalibration"
            weight_delta = -0.1
        else:
            status = "on_track"
            outcome = "validated"
            weight_delta = 0.1

        feedback = ExecutionPolicyFeedback(
            context_key=request.context_key,
            policy_type=request.policy_type,
            outcome_signal=outcome,
            evidence_refs=[
                f"{signal.source_system}:{signal.event_type}:{index}"
                for index, signal in enumerate(request.signals)
            ],
            weight_delta=weight_delta,
            notes=[
                f"max_abs_deviation_minutes={round(max_abs_deviation, 2)}",
                f"blocked_events={blocked_events}",
                f"quality_events={quality_events}",
            ],
        )
        return ExecutionFeedbackIngestionResponse(
            execution_status=status,
            feedback_updates=[feedback],
            observed_signal_count=len(request.signals),
            deviation_summary={
                "max_abs_deviation_minutes": round(max_abs_deviation, 2),
                "blocked_events": blocked_events,
                "quality_events": quality_events,
            },
            claim_boundary=(
                "Execution feedback updates policy confidence; it must be reviewed "
                "before changing dispatch or writeback behavior."
            ),
        )


def _status(
    module: str,
    checks: dict[str, bool],
    blockers: list[str],
    warnings: list[str],
    next_steps: list[str],
) -> CapabilityStatus:
    coverage = sum(1 for passed in checks.values() if passed) / max(len(checks), 1)
    if blockers:
        status = "missing"
    elif coverage >= 0.75:
        status = "ready"
    else:
        status = "partial"
    return CapabilityStatus(
        module=module,
        status=status,
        coverage_score=round(coverage, 4),
        blockers=blockers,
        warnings=warnings,
        next_steps=next_steps,
    )


def _canonical_entities_present(context: FlexibleShopContext) -> list[str]:
    entities: list[str] = []
    if context.work_orders:
        entities.append("work_order")
    if _all_operations(context):
        entities.append("operation")
    if context.resources:
        entities.append("resource")
    if context.machine_groups:
        entities.append("machine_group")
    if context.wip_items:
        entities.append("wip")
    if context.frozen_zones:
        entities.append("frozen_zone")
    if context.constraints.materials:
        entities.append("material")
    if context.constraints.quality_holds:
        entities.append("quality_hold")
    return entities


def _id_alignment_score(request: RealDataIntegrationRequest) -> float:
    canonical_count = len(_canonical_entities_present(request.context))
    if canonical_count == 0:
        return 0.0
    covered_types = {
        item.canonical_entity_type
        for item in request.id_crosswalks
        if item.confidence >= 0.8
    }
    return min(1.0, len(covered_types) / canonical_count)


def _lineage_score(request: RealDataIntegrationRequest) -> float:
    if not request.sources:
        return 0.0
    ready = sum(1 for source in request.sources if source.lineage_fields)
    return ready / len(request.sources)


def _freshness_status(
    request: RealDataIntegrationRequest,
) -> str:
    freshness = [
        source.freshness_minutes
        for source in request.sources
        if source.freshness_minutes is not None
    ]
    if not freshness:
        return "unknown"
    return "fresh" if max(freshness) <= 15 else "stale"


def _integration_next_actions(
    checks: list[DataSourceReadinessCheck],
    id_alignment_score: float,
) -> list[str]:
    actions: list[str] = []
    for check in checks:
        actions.extend(check.blockers)
        actions.extend(check.warnings)
    if id_alignment_score < 0.8:
        actions.append("complete_id_crosswalk_for_core_entities")
    if not actions:
        actions.append("run_historical_replay_on_real_snapshot")
    return sorted(set(actions))


def _source_entities(source_system: str) -> list[str]:
    mapping = {
        "ERP": ["work_order", "due_date", "bom", "customer_priority"],
        "MES": ["operation", "resource", "actual_progress", "downtime"],
        "WMS": ["material_inventory", "material_eta", "warehouse_location"],
        "QMS": ["quality_hold", "inspection_result", "rework_route"],
        "IoT": ["resource_state", "runtime_event", "downtime_signal"],
        "RFID": ["wip_location", "movement_event"],
        "AMR": ["transport_job", "lane_eta", "vehicle_state"],
        "APS": ["baseline_schedule", "planned_start_end"],
        "SCADA": ["machine_signal", "alarm_event"],
    }
    return mapping.get(source_system, [])


def _all_operations(context: FlexibleShopContext) -> list[FlexibleOperation]:
    return [
        operation
        for work_order in context.work_orders
        for operation in work_order.operations
    ]


def _compile_family(
    family: str,
    covered: bool,
    hard_count: int,
    soft_count: int,
) -> ConstraintFamilyCompilation:
    return ConstraintFamilyCompilation(
        family=family,
        hard_constraint_count=hard_count if covered else 0,
        soft_constraint_count=soft_count if covered else 0,
        coverage_score=1.0 if covered else 0.0,
        missing_fields=[] if covered else [family],
        encoded_as=_family_encoding(family) if covered else [],
    )


def _family_encoding(family: str) -> list[str]:
    encodings = {
        "assignment": ["optional_interval", "exactly_one"],
        "precedence": ["end_before_start"],
        "resource_no_overlap": ["no_overlap"],
        "material_availability": ["release_lower_bound"],
        "skill_capacity": ["cumulative_capacity"],
        "tooling_capacity": ["cumulative_capacity"],
        "changeover_matrix": ["sequence_dependent_setup"],
        "quality_hold": ["hard_block_until_release"],
        "transport_amr": ["transport_lag", "lane_capacity"],
        "buffer_capacity": ["cumulative_buffer_limit"],
        "frozen_wip": ["fixed_interval", "release_anchor"],
    }
    return encodings.get(family, ["constraint_family"])


def _soft_objectives(include: bool) -> list[str]:
    if not include:
        return []
    return [
        "minimize_total_tardiness",
        "minimize_schedule_perturbation",
        "minimize_setup_changeover_cost",
        "protect_bottleneck_utilization",
        "minimize_outsourcing_and_overtime_cost",
    ]


def _frozen_operation_ids(context: FlexibleShopContext) -> list[str]:
    frozen = {
        operation_id
        for zone in context.frozen_zones
        for operation_id in zone.operation_ids
    }
    frozen.update(
        operation.operation_id
        for operation in _all_operations(context)
        if operation.frozen_until is not None
    )
    return sorted(frozen)


def _build_subproblems(
    context: FlexibleShopContext,
    request: DecompositionSolveRequest,
    strategy: SolverStrategyPlan,
) -> list[DecompositionSubproblem]:
    operations = _all_operations(context)
    affected_ids = sorted(
        {
            operation_id
            for incident in request.incidents
            for operation_id in incident.affected_operation_ids
        }
    )
    subproblems: list[DecompositionSubproblem] = []
    if affected_ids:
        subproblems.append(
            DecompositionSubproblem(
                subproblem_id="incident-neighborhood-1",
                scope_type="incident_neighborhood",
                operation_ids=affected_ids[: request.max_subproblem_operations],
                incident_ids=[incident.incident_id for incident in request.incidents],
                solver_backend="cp_sat",
                time_budget_seconds=max(5.0, request.timeout_seconds * 0.25),
                freeze_policy="freeze_unaffected_released_wip",
                expected_output="locally feasible repaired schedule",
            )
        )

    bottleneck_group_ids = [
        group.group_id for group in context.machine_groups if group.is_bottleneck
    ]
    if bottleneck_group_ids:
        bottleneck_ops = _operations_for_machine_groups(context, bottleneck_group_ids)
        subproblems.append(
            DecompositionSubproblem(
                subproblem_id="bottleneck-first-1",
                scope_type="bottleneck_group",
                machine_group_ids=bottleneck_group_ids,
                operation_ids=bottleneck_ops[: request.max_subproblem_operations],
                incident_ids=[incident.incident_id for incident in request.incidents],
                solver_backend="lns" if strategy.use_lns else "cp_sat",
                time_budget_seconds=max(10.0, request.timeout_seconds * 0.35),
                freeze_policy="freeze_non_bottleneck_operations",
                expected_output="bottleneck-capacity-preserving repair",
            )
        )

    window_size = max(1, request.max_subproblem_operations)
    for index, chunk in enumerate(_chunks([op.operation_id for op in operations], window_size)):
        if index >= 3:
            break
        backend = "alns" if request.enable_alns_memory and strategy.use_alns_memory else "lns"
        subproblems.append(
            DecompositionSubproblem(
                subproblem_id=f"rolling-window-{index + 1}",
                scope_type="rolling_window",
                workshop_ids=[workshop.workshop_id for workshop in context.workshops],
                operation_ids=chunk,
                incident_ids=[incident.incident_id for incident in request.incidents],
                window_index=index + 1,
                solver_backend=backend,
                time_budget_seconds=max(10.0, request.timeout_seconds * 0.25),
                freeze_policy="freeze_outside_rolling_window",
                expected_output="time-window feasible candidate with bounded perturbation",
            )
        )

    if any(incident.incident_type == "rush_order" for incident in request.incidents):
        subproblems.append(
            DecompositionSubproblem(
                subproblem_id="outsourcing-branch-1",
                scope_type="outsourcing_branch",
                operation_ids=affected_ids,
                incident_ids=[
                    incident.incident_id
                    for incident in request.incidents
                    if incident.incident_type == "rush_order"
                ],
                solver_backend="heuristic",
                time_budget_seconds=max(5.0, request.timeout_seconds * 0.1),
                freeze_policy="compare_as_what_if_branch",
                expected_output="cost and lead-time branch for approval review",
            )
        )

    if not subproblems:
        subproblems.append(
            DecompositionSubproblem(
                subproblem_id="manual-reference-1",
                scope_type="global_repair",
                operation_ids=[],
                incident_ids=[incident.incident_id for incident in request.incidents],
                solver_backend="manual_review",
                time_budget_seconds=5.0,
                freeze_policy="no_solver_scope",
                expected_output="reference-only review due to missing affected scope",
            )
        )
    return subproblems


def _operations_for_machine_groups(
    context: FlexibleShopContext,
    machine_group_ids: list[str],
) -> list[str]:
    groups = set(machine_group_ids)
    return [
        operation.operation_id
        for operation in _all_operations(context)
        if any(mode.machine_group_id in groups for mode in operation.modes)
    ]


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _policy_when_to_use(policy: str) -> str:
    if "local" in policy or "reassignment" in policy:
        return "Use when the affected scope is limited and alternatives exist."
    if "global" in policy:
        return "Use only when local repair fails or downstream impact is systemic."
    if "hold" in policy or "quality" in policy:
        return "Use when quality release is uncertain or traceability is required."
    if "outsourcing" in policy or "overtime" in policy:
        return "Use as an approval-gated branch when due-date risk exceeds cost."
    return "Use as a bounded what-if option under hard-constraint gates."


def _policy_tradeoffs(policy: str) -> list[str]:
    tradeoffs = {
        "wait_and_shift": ["low disruption", "higher delay risk"],
        "local_repair": ["limited blast radius", "may miss global optimum"],
        "alternative_resource_reassignment": [
            "uses redundancy",
            "may increase setup or transport cost",
        ],
        "controlled_global_reschedule": [
            "higher chance of feasible recovery",
            "larger perturbation",
        ],
        "outsourcing_what_if": ["protects due date", "requires approval and cost check"],
        "quality_hold_freeze": ["protects compliance", "blocks downstream capacity"],
        "batch_split": ["improves flow", "adds coordination complexity"],
    }
    return tradeoffs.get(policy, ["requires replay evidence", "requires planner review"])


def _score_counterfactual_policy(
    case: CounterfactualReplayRunCase,
    policy: str,
    index: int,
) -> CounterfactualReplayResult:
    risky_terms = {"global", "outsourcing", "overtime", "manual"}
    feasible = not ("substitution" in policy and "material" not in case.context_key)
    perturbation = 8.0 + index * 7.0
    delay_delta = -20.0 + index * 6.0
    if policy == case.baseline_policy:
        perturbation = 3.0
        delay_delta = 0.0
    risk = 0.2 + index * 0.08
    if any(term in policy for term in risky_terms):
        risk += 0.2
    risk = min(1.0, risk)
    rejection_reasons: list[str] = []
    if not feasible:
        rejection_reasons.append("missing_required_context_for_policy")
    if risk >= 0.8:
        rejection_reasons.append("execution_risk_too_high")
    return CounterfactualReplayResult(
        case_id=case.case_id,
        context_key=case.context_key,
        incident_type=case.incident_type,
        policy_type=policy,
        hard_feasible=feasible,
        quality_gate_passed=feasible and risk < 0.8,
        predicted_delay_delta_minutes=round(delay_delta, 2),
        perturbation_cost=round(perturbation, 2),
        execution_risk_score=round(risk, 4),
        planner_review_required=True,
        rejection_reasons=rejection_reasons,
    )


def _historical_case_from_observations(
    case: CounterfactualReplayRunCase,
    observations: list[PolicyOutcomeObservation],
) -> HistoricalRecoveryCase:
    return HistoricalRecoveryCase(
        case_id=case.case_id,
        context_key=case.context_key,
        incident_type=case.incident_type,
        observations=observations,
    )


def _gate(
    gate: str,
    passed: bool,
    blocker: str,
) -> WritebackSafetyGateCheck:
    return WritebackSafetyGateCheck(
        gate=gate,
        passed=passed,
        blocker=None if passed else blocker,
        evidence_ref=gate if passed else None,
    )


def _operation_count(context: FlexibleShopContext) -> int:
    return sum(len(work_order.operations) for work_order in context.work_orders)


def _has_bottleneck(context: FlexibleShopContext) -> bool:
    return any(group.is_bottleneck for group in context.machine_groups) or any(
        resource.is_bottleneck for resource in context.resources
    )


def _solver_strategy(
    *,
    operation_count: int,
    has_bottleneck: bool,
    timeout_seconds: float,
    incident_count: int,
) -> SolverStrategyPlan:
    if operation_count >= 5000:
        decomposition = "workshop_and_bottleneck_group"
        rolling_window = 480
        use_lns = True
        use_alns = True
    elif operation_count >= 1000:
        decomposition = "bottleneck_group"
        rolling_window = 360
        use_lns = True
        use_alns = False
    else:
        decomposition = "single_scope"
        rolling_window = 240
        use_lns = False
        use_alns = False
    rationale = [
        f"operation_count={operation_count}",
        f"incident_count={incident_count}",
        "large flexible shops prefer feasible repair over global optimality",
    ]
    if has_bottleneck:
        rationale.append("bottleneck markers available for decomposition")
    return SolverStrategyPlan(
        decomposition_level=decomposition,
        bottleneck_first=has_bottleneck,
        rolling_window_minutes=rolling_window,
        use_lns=use_lns,
        use_alns_memory=use_alns,
        warm_start="current_schedule_snapshot + frozen/WIP anchors",
        timeout_seconds=timeout_seconds,
        fallback_policy="return_best_known_feasible_or_reference_only",
        rationale=rationale,
    )


def _constraint_blockers(
    context: FlexibleShopContext, incident_type: IncidentCategory
) -> list[str]:
    constraints = context.constraints
    blockers: list[str] = []
    if incident_type == "material_shortage" and not constraints.materials:
        blockers.append("material_constraints_required")
    if incident_type == "quality_exception" and not constraints.quality_holds:
        blockers.append("quality_hold_constraints_required")
    if incident_type == "labor_absence" and not constraints.skills:
        blockers.append("skill_constraints_required")
    if incident_type == "tooling_conflict" and not constraints.tooling:
        blockers.append("tooling_constraints_required")
    if incident_type == "batch_rework" and not any(
        operation.batch_id or operation.rework_of_operation_id
        for work_order in context.work_orders
        for operation in work_order.operations
    ):
        blockers.append("batch_or_rework_data_required")
    return blockers


def _confidence(sample_count: int, context_sufficient: bool) -> str:
    if sample_count >= 30 and context_sufficient:
        return "high"
    if sample_count >= 10 and context_sufficient:
        return "medium"
    return "low"
