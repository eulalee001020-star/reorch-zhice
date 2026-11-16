"""Production readiness gate for customer deployment decisions."""

from __future__ import annotations

from app.models.production_readiness import (
    ProductionReadinessCheck,
    ProductionReadinessEvidence,
    ProductionReadinessResponse,
    ReadinessDecision,
)


class ProductionReadinessGate:
    """Classifies the highest safe deployment level from supplied evidence."""

    def evaluate(
        self, evidence: ProductionReadinessEvidence
    ) -> ProductionReadinessResponse:
        checks = [
            _check_data_foundation(evidence),
            _check_recovery_solve(evidence),
            _check_customer_evidence(evidence),
            _check_policy_learning(evidence),
            _check_writeback_safety(evidence),
            _check_ai_governance(evidence),
            _check_performance(evidence),
            _check_operations_security(evidence),
        ]
        decision = _decision(evidence)
        production_blockers = [
            action
            for check in checks
            for action in check.required_actions
            if check.status == "blocker"
        ]
        return ProductionReadinessResponse(
            site_id=evidence.site_id,
            decision=decision,
            checks=checks,
            allowed_actions=_allowed_actions(decision),
            blocked_actions=_blocked_actions(decision),
            production_blockers=production_blockers,
            claim_boundary=_claim_boundary(decision),
        )


def _check_data_foundation(
    evidence: ProductionReadinessEvidence,
) -> ProductionReadinessCheck:
    required: list[str] = []
    proof = [
        f"p0_permission={evidence.p0_permission_level}",
        f"p0_readiness={evidence.p0_readiness_score:.2f}",
        f"snapshot_available={evidence.snapshot_available}",
        f"work_orders={evidence.work_order_count}",
        f"operations={evidence.operation_count}",
        f"resources={evidence.resource_count}",
    ]
    if not evidence.snapshot_available:
        required.append("provide_reconstructable_schedule_snapshot")
    if evidence.work_order_count <= 0:
        required.append("provide_work_order_master_data")
    if evidence.operation_count <= 0:
        required.append("provide_operation_routing_and_timing_data")
    if evidence.resource_count <= 0:
        required.append("provide_resource_calendar_and_capability_data")
    if evidence.p0_readiness_score < 0.85:
        required.append("raise_p0_data_readiness_to_at_least_0_85")
    return ProductionReadinessCheck(
        module="data_foundation",
        status="blocker" if required else "pass",
        evidence=proof,
        required_actions=required,
    )


def _check_recovery_solve(
    evidence: ProductionReadinessEvidence,
) -> ProductionReadinessCheck:
    required: list[str] = []
    proof = [
        f"incidents={evidence.incident_count}",
        f"solved_incidents={evidence.solved_incident_count}",
        f"feasible_options={evidence.feasible_option_count}",
        f"infeasible_options_retained={evidence.infeasible_option_count}",
    ]
    if evidence.incident_count <= 0:
        required.append("provide_representative_anomaly_cases")
    if evidence.solved_incident_count < evidence.incident_count:
        required.append("solve_all_representative_incidents_or_record_escalation_path")
    if evidence.feasible_option_count < evidence.solved_incident_count:
        required.append("provide_at_least_one_feasible_option_per_solved_incident")
    return ProductionReadinessCheck(
        module="multi_strategy_recovery",
        status="blocker" if required else "pass",
        evidence=proof,
        required_actions=required,
    )


def _check_customer_evidence(
    evidence: ProductionReadinessEvidence,
) -> ProductionReadinessCheck:
    proof = [
        f"evidence_source={evidence.evidence_source}",
        f"real_customer_data={evidence.real_customer_data}",
        f"customer_provenance_confirmed={evidence.customer_provenance_confirmed}",
    ]
    required = []
    if not evidence.real_customer_data:
        required.append("rerun_on_customer_readonly_desensitized_or_shadow_data")
    if not evidence.customer_provenance_confirmed:
        required.append("attach_customer_data_provenance_note")
    if evidence.evidence_source == "public_benchmark":
        required.append("replace_public_benchmark_with_customer_validated_evidence")
    status = "pass" if not required else "blocker"
    return ProductionReadinessCheck(
        module="customer_evidence",
        status=status,
        evidence=proof,
        required_actions=required,
    )


def _check_policy_learning(
    evidence: ProductionReadinessEvidence,
) -> ProductionReadinessCheck:
    required: list[str] = []
    proof = [
        f"planner_decisions={evidence.planner_decision_count}",
        f"override_reasons={evidence.planner_override_reason_count}",
        f"execution_outcomes={evidence.execution_outcome_count}",
        f"policy_matrix_cells={evidence.strategy_effect_matrix_cell_count}",
        f"high_confidence_cells={evidence.high_confidence_policy_cell_count}",
    ]
    if evidence.planner_decision_count < 30:
        required.append("collect_at_least_30_planner_accept_adjust_reject_decisions")
    if evidence.planner_override_reason_count < 10:
        required.append("collect_structured_planner_override_reasons")
    if evidence.execution_outcome_count < 30:
        required.append("collect_at_least_30_execution_outcomes")
    if evidence.high_confidence_policy_cell_count < 3:
        required.append("build_policy_effect_matrix_with_high_confidence_cells")
    if not required:
        status = "pass"
    elif evidence.planner_decision_count or evidence.execution_outcome_count:
        status = "warning"
    else:
        status = "blocker"
    return ProductionReadinessCheck(
        module="policy_learning_loop",
        status=status,
        evidence=proof,
        required_actions=required,
    )


def _check_writeback_safety(
    evidence: ProductionReadinessEvidence,
) -> ProductionReadinessCheck:
    roles = {role.lower() for role in evidence.approval_roles}
    required: list[str] = []
    proof = [
        f"sandbox_writeback_passed={evidence.sandbox_writeback_passed}",
        f"approval_roles={','.join(sorted(roles)) or 'none'}",
        f"idempotency_ready={evidence.idempotency_ready}",
        f"rollback_plan_ready={evidence.rollback_plan_ready}",
        f"compensation_ready={evidence.compensation_ready}",
        f"audit_ready={evidence.audit_ready}",
    ]
    if not evidence.sandbox_writeback_passed:
        required.append("pass_sandbox_writeback_dry_run")
    if not {"planner", "production_manager"}.issubset(roles):
        required.append("configure_dual_approval_roles")
    if not evidence.idempotency_ready:
        required.append("prove_idempotent_writeback")
    if not evidence.rollback_plan_ready:
        required.append("prepare_writeback_rollback_plan")
    if not evidence.compensation_ready:
        required.append("prepare_compensation_steps_for_partial_failure")
    if not evidence.audit_ready:
        required.append("enable_exportable_writeback_audit_trace")
    return ProductionReadinessCheck(
        module="writeback_safety",
        status="blocker" if required else "pass",
        evidence=proof,
        required_actions=required,
    )


def _check_ai_governance(
    evidence: ProductionReadinessEvidence,
) -> ProductionReadinessCheck:
    required: list[str] = []
    proof = [
        f"ai_role_limited_to_explanation={evidence.ai_role_limited_to_explanation}",
        f"quality_gate_enforced={evidence.quality_gate_enforced}",
        f"human_confirmation_enforced={evidence.human_confirmation_enforced}",
    ]
    if not evidence.ai_role_limited_to_explanation:
        required.append("remove_ai_from_hard_constraint_and_final_dispatch_roles")
    if not evidence.quality_gate_enforced:
        required.append("enforce_quality_gate_before_planner_review")
    if not evidence.human_confirmation_enforced:
        required.append("enforce_human_confirmation_before_writeback")
    return ProductionReadinessCheck(
        module="ai_governance",
        status="blocker" if required else "pass",
        evidence=proof,
        required_actions=required,
    )


def _check_performance(
    evidence: ProductionReadinessEvidence,
) -> ProductionReadinessCheck:
    required: list[str] = []
    tested = set(evidence.performance_targets_tested)
    proof = [
        f"p95_solver_latency_ms={evidence.p95_solver_latency_ms}",
        f"p95_gate_latency_ms={evidence.p95_gate_latency_ms}",
        f"concurrent_incident_tested={evidence.concurrent_incident_tested}",
        f"targets_tested={sorted(tested)}",
    ]
    if evidence.p95_solver_latency_ms is None:
        required.append("measure_p95_solver_latency_on_customer_like_workload")
    elif evidence.p95_solver_latency_ms > 60_000:
        required.append("reduce_p95_solver_latency_below_60s_or_limit_scope")
    if evidence.p95_gate_latency_ms is None:
        required.append("measure_p95_quality_gate_latency")
    elif evidence.p95_gate_latency_ms > 1_000:
        required.append("reduce_p95_quality_gate_latency_below_1s")
    if evidence.concurrent_incident_tested < 3:
        required.append("run_concurrent_incident_pressure_test")
    if not {1000, 5000, 10000}.issubset(tested):
        required.append("run_1k_5k_10k_operation_pressure_tests")
    return ProductionReadinessCheck(
        module="performance_engineering",
        status="blocker" if required else "pass",
        evidence=proof,
        required_actions=required,
    )


def _check_operations_security(
    evidence: ProductionReadinessEvidence,
) -> ProductionReadinessCheck:
    required: list[str] = []
    proof = [
        f"security_review_passed={evidence.security_review_passed}",
        f"backup_restore_drill_passed={evidence.backup_restore_drill_passed}",
        f"observability_alerting_ready={evidence.observability_alerting_ready}",
        f"sso_rbac_ready={evidence.sso_rbac_ready}",
        f"retention_policy_approved={evidence.retention_policy_approved}",
    ]
    if not evidence.security_review_passed:
        required.append("pass_customer_security_review")
    if not evidence.backup_restore_drill_passed:
        required.append("complete_backup_restore_drill")
    if not evidence.observability_alerting_ready:
        required.append("enable_metrics_alerting_and_trace_correlation")
    if not evidence.sso_rbac_ready:
        required.append("integrate_customer_sso_or_rbac_mapping")
    if not evidence.retention_policy_approved:
        required.append("approve_data_retention_and_deletion_policy")
    return ProductionReadinessCheck(
        module="operations_security",
        status="blocker" if required else "pass",
        evidence=proof,
        required_actions=required,
    )


def _decision(evidence: ProductionReadinessEvidence) -> ReadinessDecision:
    if not _has_core_snapshot(evidence):
        return "blocked"
    if not _has_recovery_coverage(evidence):
        return "replay_ready"
    if _is_production_ready(evidence):
        return "production_ready"
    if _is_controlled_pilot_ready(evidence):
        return "controlled_pilot_ready"
    if _is_customer_shadow_ready(evidence):
        return "shadow_ready"
    return "replay_ready"


def _has_core_snapshot(evidence: ProductionReadinessEvidence) -> bool:
    return (
        evidence.snapshot_available
        and evidence.work_order_count > 0
        and evidence.operation_count > 0
        and evidence.resource_count > 0
        and evidence.p0_readiness_score >= 0.85
    )


def _has_recovery_coverage(evidence: ProductionReadinessEvidence) -> bool:
    return (
        evidence.incident_count > 0
        and evidence.solved_incident_count >= evidence.incident_count
        and evidence.feasible_option_count >= evidence.solved_incident_count
    )


def _has_customer_source(evidence: ProductionReadinessEvidence) -> bool:
    return (
        evidence.real_customer_data
        and evidence.customer_provenance_confirmed
        and evidence.evidence_source != "public_benchmark"
    )


def _has_writeback_safety(evidence: ProductionReadinessEvidence) -> bool:
    roles = {role.lower() for role in evidence.approval_roles}
    return (
        evidence.sandbox_writeback_passed
        and {"planner", "production_manager"}.issubset(roles)
        and evidence.idempotency_ready
        and evidence.rollback_plan_ready
        and evidence.compensation_ready
        and evidence.audit_ready
    )


def _has_ai_governance(evidence: ProductionReadinessEvidence) -> bool:
    return (
        evidence.ai_role_limited_to_explanation
        and evidence.quality_gate_enforced
        and evidence.human_confirmation_enforced
    )


def _has_pilot_performance(evidence: ProductionReadinessEvidence) -> bool:
    return (
        evidence.p95_solver_latency_ms is not None
        and evidence.p95_solver_latency_ms <= 60_000
        and evidence.p95_gate_latency_ms is not None
        and evidence.p95_gate_latency_ms <= 1_000
    )


def _has_full_performance(evidence: ProductionReadinessEvidence) -> bool:
    return (
        _has_pilot_performance(evidence)
        and evidence.concurrent_incident_tested >= 3
        and {1000, 5000, 10000}.issubset(set(evidence.performance_targets_tested))
    )


def _has_ops_security(evidence: ProductionReadinessEvidence) -> bool:
    return (
        evidence.security_review_passed
        and evidence.backup_restore_drill_passed
        and evidence.observability_alerting_ready
        and evidence.sso_rbac_ready
        and evidence.retention_policy_approved
    )


def _is_customer_shadow_ready(evidence: ProductionReadinessEvidence) -> bool:
    return (
        _has_customer_source(evidence)
        and _has_recovery_coverage(evidence)
        and _has_ai_governance(evidence)
    )


def _is_controlled_pilot_ready(evidence: ProductionReadinessEvidence) -> bool:
    return (
        _is_customer_shadow_ready(evidence)
        and _has_writeback_safety(evidence)
        and _has_pilot_performance(evidence)
        and evidence.security_review_passed
        and evidence.observability_alerting_ready
    )


def _is_production_ready(evidence: ProductionReadinessEvidence) -> bool:
    return (
        _is_controlled_pilot_ready(evidence)
        and evidence.planner_decision_count >= 30
        and evidence.planner_override_reason_count >= 10
        and evidence.execution_outcome_count >= 30
        and evidence.high_confidence_policy_cell_count >= 3
        and _has_full_performance(evidence)
        and _has_ops_security(evidence)
    )


def _allowed_actions(decision: ReadinessDecision) -> list[str]:
    mapping = {
        "blocked": ["data_gap_analysis"],
        "replay_ready": [
            "read_only_replay",
            "counterfactual_replay",
            "multi_strategy_tradeoff_report",
        ],
        "shadow_ready": [
            "read_only_replay",
            "counterfactual_replay",
            "multi_strategy_tradeoff_report",
            "customer_shadow_mode",
            "planner_review_without_writeback",
        ],
        "controlled_pilot_ready": [
            "read_only_replay",
            "counterfactual_replay",
            "multi_strategy_tradeoff_report",
            "customer_shadow_mode",
            "planner_review_without_writeback",
            "sandbox_writeback",
            "human_approved_controlled_writeback",
        ],
        "production_ready": [
            "read_only_replay",
            "counterfactual_replay",
            "multi_strategy_tradeoff_report",
            "customer_shadow_mode",
            "planner_review_without_writeback",
            "sandbox_writeback",
            "human_approved_controlled_writeback",
            "production_writeback",
            "policy_learning_optimization",
        ],
    }
    return mapping[decision]


def _blocked_actions(decision: ReadinessDecision) -> list[str]:
    all_actions = {
        "read_only_replay",
        "counterfactual_replay",
        "multi_strategy_tradeoff_report",
        "customer_shadow_mode",
        "planner_review_without_writeback",
        "sandbox_writeback",
        "human_approved_controlled_writeback",
        "production_writeback",
        "policy_learning_optimization",
        "unattended_autonomous_dispatch",
    }
    return sorted(all_actions.difference(_allowed_actions(decision)))


def _claim_boundary(decision: ReadinessDecision) -> str:
    if decision == "production_ready":
        return (
            "Evidence supports human-governed production use. AI still does not "
            "bypass solver feasibility, quality gates, approvals, audit, or rollback."
        )
    if decision == "controlled_pilot_ready":
        return (
            "Evidence supports a controlled customer pilot with human approval and "
            "audited writeback. It does not support unattended autonomous dispatch."
        )
    if decision == "shadow_ready":
        return (
            "Evidence supports customer read-only shadow mode and planner review. "
            "Writeback remains blocked until sandbox, approval, rollback, and audit pass."
        )
    if decision == "replay_ready":
        return (
            "Evidence supports read-only replay and multi-strategy comparison. It "
            "does not prove customer production readiness, ROI, or policy learning."
        )
    return (
        "Core data is insufficient for reliable replay; only data-gap analysis is allowed."
    )
