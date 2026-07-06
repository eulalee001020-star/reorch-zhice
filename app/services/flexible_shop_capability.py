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
    DynamicIncidentScenario,
    DynamicReschedulingPlanRequest,
    DynamicReschedulingPlanResponse,
    FlexibleShopBenchmarkRequest,
    FlexibleShopBenchmarkResponse,
    FlexibleShopCapabilityRequest,
    FlexibleShopCapabilityResponse,
    FlexibleShopContext,
    IncidentCategory,
    IncidentRecoveryPlan,
    PolicyEffectivenessCell,
    SolverStrategyPlan,
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
