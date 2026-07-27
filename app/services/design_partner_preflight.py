"""Evidence-gated Design Partner onboarding assessment."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.models.design_partner import (
    ApprovalType,
    CaseMetrics,
    CheckStatus,
    ConstraintAttestation,
    DataProvenanceEvidence,
    DesignPartnerPreflightRequest,
    DesignPartnerPreflightResponse,
    EvidenceCheck,
    GovernanceApproval,
    MoatLayerAssessment,
    MoatStatus,
    PreflightStage,
    RecoveryCaseEvidence,
    RoiCostModel,
    RoiEvidenceLevel,
    RoiEvidenceSummary,
    WorkflowEvidence,
)
from app.models.reality_harness import P0RealityHarnessResponse
from app.services.reality_harness import P0RealityHarnessService

_CORE_APPROVAL_TYPES: set[ApprovalType] = {
    "data_use",
    "historical_replay",
    "retention",
    "security_review",
}
_GENERATED_DELIVERABLES = [
    "data_mapping_and_readiness_report",
    "governance_evidence_matrix",
    "constraint_attestation_register",
    "replay_decision_and_execution_ledger",
    "roi_evidence_ledger",
    "moat_asset_register",
    "sandbox_writeback_gate_status",
]


class DesignPartnerPreflightService:
    """Derive the highest safe trial stage from submitted, source-backed evidence."""

    def __init__(self, reality_harness: P0RealityHarnessService | None = None) -> None:
        self._reality_harness = reality_harness or P0RealityHarnessService()

    def assess(
        self,
        request: DesignPartnerPreflightRequest,
    ) -> DesignPartnerPreflightResponse:
        reality = self._reality_harness.assess(request.reality_request)
        valid_approvals = _valid_approval_map(request.governance_approvals)
        auditable_cases, excluded_case_ids = _partition_cases(request.recovery_cases)
        confirmed_constraints = _confirmed_constraints(request.constraints)
        roi_summary = _build_roi_summary(
            request.recovery_cases,
            request.roi_cost_model,
        )

        checks = [
            _mapping_check(reality),
            _readiness_check(reality),
            _workshop_identity_check(request),
            _provenance_check(request.provenance),
            _governance_check(valid_approvals),
            _constraint_check(request.constraints, confirmed_constraints),
            _validation_asset_check(
                request.recovery_cases,
                auditable_cases,
                excluded_case_ids,
            ),
            _workflow_check(request.workflow_evidence),
            _roi_check(roi_summary),
        ]

        stage = _derive_stage(
            request=request,
            reality=reality,
            checks=checks,
            approvals=valid_approvals,
            confirmed_constraints=confirmed_constraints,
            auditable_cases=auditable_cases,
        )
        allowed_actions, blocked_actions = _derive_actions(
            stage,
            valid_approvals,
        )
        next_actions = _next_actions(
            request=request,
            reality=reality,
            checks=checks,
            approvals=valid_approvals,
            confirmed_constraints=confirmed_constraints,
            auditable_cases=auditable_cases,
        )

        data_fingerprint = _fingerprint(
            request.reality_request.model_dump(mode="json")
        )
        evidence_fingerprint = _fingerprint(request.model_dump(mode="json"))
        claim_boundary = (
            "Synthetic sample only: it proves the workflow can run, not customer demand, "
            "production performance, or ROI."
            if request.evidence_scope == "synthetic_sample"
            else "This preflight validates submitted references and action gates; it is not "
            "independent verification of production performance or realized customer ROI."
        )
        return DesignPartnerPreflightResponse(
            preflight_id=f"DPF-{evidence_fingerprint[:16]}",
            evidence_scope=request.evidence_scope,
            customer_ref=request.customer_ref,
            site_id=request.site_id,
            workshop_id=request.reality_request.workshop_id,
            data_fingerprint=data_fingerprint,
            stage=stage,
            reality_harness=reality,
            checks=checks,
            roi_summary=roi_summary,
            moat_layers=_assess_moat_layers(
                request=request,
                reality=reality,
                approvals=valid_approvals,
                confirmed_constraints=confirmed_constraints,
                auditable_cases=auditable_cases,
            ),
            allowed_actions=allowed_actions,
            blocked_actions=blocked_actions,
            required_next_actions=next_actions,
            generated_deliverables=list(_GENERATED_DELIVERABLES),
            claim_boundary=claim_boundary,
        )

    def build_synthetic_sample_request(self) -> DesignPartnerPreflightRequest:
        """Build a deterministic demonstration request with no customer evidence."""
        reference_time = datetime(2026, 5, 14, 5, 0, tzinfo=timezone.utc)
        approval_types = sorted(_CORE_APPROVAL_TYPES)
        return DesignPartnerPreflightRequest(
            evidence_scope="synthetic_sample",
            customer_ref="SYNTHETIC-SAMPLE",
            site_id="P0-REALITY-LINE",
            reality_request=self._reality_harness.load_sample_pack(
                source_system="synthetic_p0_sample",
                workshop_id="P0-REALITY-LINE",
            ),
            provenance=DataProvenanceEvidence(
                dataset_name="synthetic-p0-sample",
                source_systems=["synthetic_ERP", "synthetic_MES", "synthetic_APS"],
                exported_at=reference_time,
                data_window_start=reference_time - timedelta(days=30),
                data_window_end=reference_time,
                data_owner_role="synthetic_fixture_owner",
                data_owner_approved=True,
                replay_authorized=True,
                desensitized=True,
                provenance_ref="fixture://p0_reality_pack/README.md",
                mapping_profile_ref="fixture://default_mapping_profile",
                mapping_approved_by="synthetic_fixture_owner",
            ),
            governance_approvals=[
                GovernanceApproval(
                    approval_type=approval_type,
                    approved=True,
                    approver_role="synthetic_fixture_owner",
                    evidence_ref=f"fixture://governance/{approval_type}",
                    approved_at=reference_time,
                )
                for approval_type in approval_types
            ],
        )


def _mapping_check(reality: P0RealityHarnessResponse) -> EvidenceCheck:
    report = reality.mapping_report
    if report.blocking_errors:
        return EvidenceCheck(
            check_id="canonical_mapping",
            category="data",
            status="blocked",
            finding=f"Canonical mapping has {report.blocking_errors} blocking errors.",
            required_action="Fix required fields and reference integrity, then rerun preflight.",
        )
    return EvidenceCheck(
        check_id="canonical_mapping",
        category="data",
        status="passed" if report.warnings == 0 else "warning",
        finding=(
            f"Mapped {report.valid_records}/{report.total_records} records with "
            f"{report.warnings} warnings."
        ),
        required_action=(
            "Review mapping warnings with the customer data owner."
            if report.warnings
            else None
        ),
    )


def _readiness_check(reality: P0RealityHarnessResponse) -> EvidenceCheck:
    permission = reality.permission
    return EvidenceCheck(
        check_id="customer_data_readiness",
        category="data",
        status="passed" if permission.allow_historical_replay else "blocked",
        finding=(
            f"Reality Harness level={permission.level}, "
            f"readiness={reality.readiness_report.readiness_score:.2f}."
        ),
        required_action=(
            None
            if permission.allow_historical_replay
            else "Complete the Reality Harness repair actions before any replay."
        ),
    )


def _workshop_identity_check(request: DesignPartnerPreflightRequest) -> EvidenceCheck:
    matches = request.site_id == request.reality_request.workshop_id
    return EvidenceCheck(
        check_id="workshop_identity",
        category="data",
        status="passed" if matches else "blocked",
        finding=(
            "site_id matches the Reality Harness workshop_id."
            if matches
            else "site_id and Reality Harness workshop_id do not match."
        ),
        required_action=(
            None
            if matches
            else "Use one stable pseudonymous workshop identifier across the pack."
        ),
    )


def _provenance_check(provenance: DataProvenanceEvidence) -> EvidenceCheck:
    missing: list[str] = []
    if not provenance.source_systems:
        missing.append("source_systems")
    if provenance.exported_at is None:
        missing.append("exported_at")
    if provenance.data_window_start is None or provenance.data_window_end is None:
        missing.append("data_window")
    elif provenance.data_window_start >= provenance.data_window_end:
        missing.append("valid_data_window")
    if not provenance.data_owner_role:
        missing.append("data_owner_role")
    if not provenance.data_owner_approved:
        missing.append("data_owner_approval")
    if not provenance.replay_authorized:
        missing.append("replay_authorization")
    if not provenance.provenance_ref:
        missing.append("provenance_ref")
    if not provenance.mapping_profile_ref or not provenance.mapping_approved_by:
        missing.append("approved_mapping_profile")

    refs = _refs(provenance.provenance_ref, provenance.mapping_profile_ref)
    if missing:
        return EvidenceCheck(
            check_id="data_provenance",
            category="governance",
            status="blocked",
            finding=f"Missing provenance evidence: {', '.join(missing)}.",
            evidence_refs=refs,
            required_action="Obtain a signed data manifest and customer-approved mapping profile.",
        )
    if not provenance.desensitized:
        return EvidenceCheck(
            check_id="data_provenance",
            category="governance",
            status="warning",
            finding="Provenance is complete, but the export is not marked desensitized.",
            evidence_refs=refs,
            required_action="Document isolated processing, access control, and deletion scope.",
        )
    return EvidenceCheck(
        check_id="data_provenance",
        category="governance",
        status="passed",
        finding="Data ownership, time window, mapping, and replay authorization are traceable.",
        evidence_refs=refs,
    )


def _governance_check(
    approvals: dict[ApprovalType, GovernanceApproval],
) -> EvidenceCheck:
    missing = sorted(_CORE_APPROVAL_TYPES - approvals.keys())
    refs = [
        item.evidence_ref
        for key, item in approvals.items()
        if key in _CORE_APPROVAL_TYPES and item.evidence_ref
    ]
    if missing:
        return EvidenceCheck(
            check_id="core_governance_approvals",
            category="governance",
            status="blocked",
            finding=f"Missing valid approvals: {', '.join(missing)}.",
            evidence_refs=refs,
            required_action="Collect referenced data-use, replay, retention, and security approvals.",
        )
    return EvidenceCheck(
        check_id="core_governance_approvals",
        category="governance",
        status="passed",
        finding="Core customer-data governance approvals are referenced and in force.",
        evidence_refs=refs,
    )


def _constraint_check(
    submitted: list[ConstraintAttestation],
    confirmed: list[ConstraintAttestation],
) -> EvidenceCheck:
    if not submitted:
        return EvidenceCheck(
            check_id="constraint_attestation",
            category="constraint_translation",
            status="not_provided",
            finding="No workshop constraints have been attested.",
            required_action="Interview planning, quality, tooling, and line owners and cite each rule source.",
        )
    hard_drafts = [
        item.constraint_id
        for item in submitted
        if item.enforcement == "hard" and item not in confirmed
    ]
    ratio = len(confirmed) / len(submitted)
    status: CheckStatus = (
        "passed" if ratio >= 0.80 and not hard_drafts else "warning"
    )
    return EvidenceCheck(
        check_id="constraint_attestation",
        category="constraint_translation",
        status=status,
        finding=(
            f"{len(confirmed)}/{len(submitted)} constraints are source-backed and customer-confirmed; "
            f"{len(hard_drafts)} hard constraints remain unconfirmed."
        ),
        evidence_refs=sorted({ref for item in confirmed for ref in item.source_refs}),
        required_action=(
            None
            if status == "passed"
            else "Confirm all hard constraints and reach at least 80% attestation coverage before shadow mode."
        ),
    )


def _validation_asset_check(
    submitted: list[RecoveryCaseEvidence],
    auditable: list[RecoveryCaseEvidence],
    excluded_case_ids: list[str],
) -> EvidenceCheck:
    if not submitted:
        return EvidenceCheck(
            check_id="validation_case_assets",
            category="validation",
            status="not_provided",
            finding="No replay, shadow, or execution cases were submitted.",
            required_action="Replay historical incidents and retain baseline, output, and planner-decision references.",
        )
    status: CheckStatus = "passed" if len(auditable) >= 5 else "warning"
    return EvidenceCheck(
        check_id="validation_case_assets",
        category="validation",
        status=status,
        finding=(
            f"{len(auditable)}/{len(submitted)} cases are auditable; "
            f"excluded={len(excluded_case_ids)}."
        ),
        evidence_refs=sorted(
            {
                ref
                for case in auditable
                for ref in _case_refs(case)
            }
        ),
        required_action=(
            None
            if status == "passed"
            else "Build at least five source-backed replay cases before read-only shadow mode."
        ),
    )


def _workflow_check(workflow: WorkflowEvidence) -> EvidenceCheck:
    required = {
        "planner_confirmation_ref": workflow.planner_confirmation_ref,
        "approval_matrix_ref": workflow.approval_matrix_ref,
        "audit_export_ref": workflow.audit_export_ref,
    }
    missing = [key for key, value in required.items() if not value]
    refs = _workflow_refs(workflow)
    if len(missing) == len(required):
        return EvidenceCheck(
            check_id="workflow_embedding",
            category="workflow",
            status="not_provided",
            finding="No confirmation, approval, or audit workflow evidence was submitted.",
            required_action="Run and retain a planner confirmation and audit-export walkthrough.",
        )
    return EvidenceCheck(
        check_id="workflow_embedding",
        category="workflow",
        status="passed" if not missing else "warning",
        finding=(
            "Core confirmation, approval, and audit workflow references are present."
            if not missing
            else f"Missing workflow references: {', '.join(missing)}."
        ),
        evidence_refs=refs,
        required_action=(
            None
            if not missing
            else "Complete the missing workflow walkthroughs before shadow mode."
        ),
    )


def _roi_check(summary: RoiEvidenceSummary) -> EvidenceCheck:
    if summary.evidence_level == "none":
        return EvidenceCheck(
            check_id="roi_evidence",
            category="roi",
            status="not_provided",
            finding="No source-backed comparable cases are available for ROI.",
            evidence_refs=summary.evidence_refs,
            required_action="Capture per-case baseline and ReOrch metrics with source references.",
        )
    return EvidenceCheck(
        check_id="roi_evidence",
        category="roi",
        status=(
            "passed"
            if summary.evidence_level in {"execution_measured", "finance_validated_execution"}
            else "warning"
        ),
        finding=(
            f"ROI evidence level={summary.evidence_level}; "
            f"eligible_cases={summary.eligible_case_count}."
        ),
        evidence_refs=summary.evidence_refs,
        required_action=(
            None
            if summary.evidence_level == "finance_validated_execution"
            else "Do not present replay estimates as realized ROI; add execution and finance validation."
        ),
    )


def _derive_stage(
    *,
    request: DesignPartnerPreflightRequest,
    reality: P0RealityHarnessResponse,
    checks: list[EvidenceCheck],
    approvals: dict[ApprovalType, GovernanceApproval],
    confirmed_constraints: list[ConstraintAttestation],
    auditable_cases: list[RecoveryCaseEvidence],
) -> PreflightStage:
    core_check_ids = {
        "canonical_mapping",
        "customer_data_readiness",
        "workshop_identity",
        "data_provenance",
        "core_governance_approvals",
    }
    if any(
        check.status == "blocked" and check.check_id in core_check_ids
        for check in checks
    ):
        return "data_repair"

    constraint_ratio = (
        len(confirmed_constraints) / len(request.constraints)
        if request.constraints
        else 0.0
    )
    hard_constraints_ready = all(
        item in confirmed_constraints
        for item in request.constraints
        if item.enforcement == "hard"
    )
    shadow_ready = all(
        (
            reality.permission.allow_shadow_mode,
            "read_only_shadow" in approvals,
            constraint_ratio >= 0.80,
            hard_constraints_ready,
            len(reality.dataset.incidents) >= 10,
            len(auditable_cases) >= 5,
            bool(request.workflow_evidence.planner_confirmation_ref),
            bool(request.workflow_evidence.approval_matrix_ref),
            bool(request.workflow_evidence.audit_export_ref),
        )
    )
    if shadow_ready and request.evidence_scope == "customer_provided":
        return "shadow_ready"
    return "replay_ready"


def _derive_actions(
    stage: PreflightStage,
    approvals: dict[ApprovalType, GovernanceApproval],
) -> tuple[list[str], list[str]]:
    allowed = ["field_mapping_review", "data_repair"]
    if stage in {"replay_ready", "shadow_ready"}:
        allowed.extend(
            [
                "historical_replay",
                "offline_roi_baseline",
                "sandbox_instruction_preview",
            ]
        )
    if stage == "shadow_ready":
        allowed.extend(["read_only_shadow", "planner_feedback_capture"])

    blocked = [
        "autonomous_production_execution",
        "production_writeback",
        "cross_customer_raw_data_reuse",
        "sandbox_writeback_execution_without_runtime_gate",
    ]
    if stage != "shadow_ready":
        blocked.append("read_only_shadow")
    if "sandbox_writeback" not in approvals:
        blocked.append("sandbox_writeback_execution")
    return allowed, blocked


def _next_actions(
    *,
    request: DesignPartnerPreflightRequest,
    reality: P0RealityHarnessResponse,
    checks: list[EvidenceCheck],
    approvals: dict[ApprovalType, GovernanceApproval],
    confirmed_constraints: list[ConstraintAttestation],
    auditable_cases: list[RecoveryCaseEvidence],
) -> list[str]:
    actions = [
        check.required_action
        for check in checks
        if check.required_action and check.status != "passed"
    ]
    if len(reality.dataset.incidents) < 10:
        actions.append(
            f"Provide at least 10 historical incidents; current={len(reality.dataset.incidents)}."
        )
    if len(auditable_cases) < 5:
        actions.append(
            f"Complete at least 5 auditable replay cases; current={len(auditable_cases)}."
        )
    ratio = len(confirmed_constraints) / len(request.constraints) if request.constraints else 0.0
    if ratio < 0.80:
        actions.append(
            f"Raise source-backed constraint attestation to 80%; current={ratio:.0%}."
        )
    if "read_only_shadow" not in approvals:
        actions.append("Obtain a referenced read-only shadow-mode approval.")
    if "sandbox_writeback" not in approvals:
        actions.append(
            "Keep writeback disabled; obtain a separate sandbox approval only after contract testing."
        )
    return _dedupe(actions)


def _build_roi_summary(
    cases: list[RecoveryCaseEvidence],
    cost_model: RoiCostModel,
) -> RoiEvidenceSummary:
    eligible, excluded = _partition_cases(cases)
    deltas = {
        "saved_decision_minutes": 0.0,
        "reduced_tardiness_minutes": 0.0,
        "reduced_changeovers": 0.0,
        "reduced_overtime_hours": 0.0,
    }
    breakdown = {
        "planner_time_savings": 0.0,
        "tardiness_savings": 0.0,
        "changeover_savings": 0.0,
        "overtime_savings": 0.0,
    }
    realized = 0.0
    for case in eligible:
        case_deltas = _case_deltas(case.baseline_metrics, case.reorch_metrics)
        for key, value in case_deltas.items():
            deltas[key] += value
        case_breakdown = {
            "planner_time_savings": (
                case_deltas["saved_decision_minutes"]
                / 60.0
                * cost_model.planner_hourly_cost
            ),
            "tardiness_savings": (
                case_deltas["reduced_tardiness_minutes"]
                * cost_model.tardiness_cost_per_minute
            ),
            "changeover_savings": (
                case_deltas["reduced_changeovers"] * cost_model.changeover_cost
            ),
            "overtime_savings": (
                case_deltas["reduced_overtime_hours"]
                * cost_model.overtime_hourly_cost
            ),
        }
        for key, value in case_breakdown.items():
            breakdown[key] += value
        if case.evaluation_mode == "controlled_execution" and case.execution_result_ref:
            realized += sum(case_breakdown.values())

    finance_validated = bool(
        cost_model.cost_source_ref and cost_model.finance_confirmed_by
    )
    has_execution = any(
        case.evaluation_mode == "controlled_execution" and case.execution_result_ref
        for case in eligible
    )
    if not eligible:
        evidence_level: RoiEvidenceLevel = "none"
    elif has_execution and finance_validated:
        evidence_level = "finance_validated_execution"
    elif has_execution:
        evidence_level = "execution_measured"
    elif any(case.evaluation_mode == "read_only_shadow" for case in eligible):
        evidence_level = "shadow_observed"
    else:
        evidence_level = "replay_counterfactual"

    estimated = sum(breakdown.values())
    roi_ratio = None
    if evidence_level == "finance_validated_execution" and cost_model.poc_cost > 0:
        roi_ratio = round(
            (realized - cost_model.poc_cost) / cost_model.poc_cost,
            4,
        )

    claim_by_level = {
        "none": "No ROI claim is supported.",
        "replay_counterfactual": "Only counterfactual replay value may be reported; it is not realized savings.",
        "shadow_observed": "Observed decision-workflow gains may be reported; operating savings remain estimated.",
        "execution_measured": "Case-level measured savings may be reported; finance validation is still pending.",
        "finance_validated_execution": "Finance-validated case-level ROI may be reported without unobserved extrapolation.",
    }
    refs = sorted(
        {
            ref
            for case in eligible
            for ref in _case_refs(case)
        }
        | ({cost_model.cost_source_ref} if cost_model.cost_source_ref else set())
    )
    return RoiEvidenceSummary(
        currency=cost_model.currency,
        evidence_level=evidence_level,
        submitted_case_count=len(cases),
        eligible_case_count=len(eligible),
        excluded_case_ids=excluded,
        measured_deltas={key: round(value, 2) for key, value in deltas.items()},
        estimated_case_savings=round(estimated, 2),
        realized_case_savings=round(realized, 2),
        savings_breakdown={key: round(value, 2) for key, value in breakdown.items()},
        finance_validated=finance_validated,
        roi_ratio=roi_ratio,
        evidence_refs=refs,
        claim_allowed=claim_by_level[evidence_level],
    )


def _assess_moat_layers(
    *,
    request: DesignPartnerPreflightRequest,
    reality: P0RealityHarnessResponse,
    approvals: dict[ApprovalType, GovernanceApproval],
    confirmed_constraints: list[ConstraintAttestation],
    auditable_cases: list[RecoveryCaseEvidence],
) -> list[MoatLayerAssessment]:
    provenance = request.provenance
    provenance_items = [
        bool(provenance.source_systems),
        bool(provenance.provenance_ref),
        bool(provenance.mapping_profile_ref),
        bool(provenance.mapping_approved_by),
        provenance.data_owner_approved,
        provenance.replay_authorized,
    ]
    data_score = min(
        100.0,
        reality.readiness_report.readiness_score * 55.0
        + sum(provenance_items) / len(provenance_items) * 45.0,
    )
    reusable_adapters = int(
        bool(provenance.adapter_template_ref)
        and not provenance.adapter_template_contains_customer_identifiers
    )
    data_layer = MoatLayerAssessment(
        layer="data_integration",
        evidence_coverage_score=round(data_score, 1),
        status=_coverage_status(data_score),
        customer_private_asset_count=int(bool(provenance.mapping_profile_ref)) + 1,
        reusable_deidentified_asset_count=reusable_adapters,
        strengths=_dedupe(
            [
                "Canonical dataset and deterministic data fingerprint are available.",
                *(
                    ["Customer-approved mapping profile is referenced."]
                    if provenance.mapping_profile_ref and provenance.mapping_approved_by
                    else []
                ),
            ]
        ),
        gaps=(
            []
            if reusable_adapters
            else ["No deidentified reusable adapter template has been evidenced."]
        ),
    )

    total_constraints = len(request.constraints)
    confirmed_ratio = (
        len(confirmed_constraints) / total_constraints if total_constraints else 0.0
    )
    replay_validated = [
        item for item in confirmed_constraints if item.status == "replay_validated"
    ]
    replay_ratio = len(replay_validated) / total_constraints if total_constraints else 0.0
    implicit_count = sum(
        item.category == "planner_policy" for item in confirmed_constraints
    )
    reusable_constraints = sum(
        bool(item.reusable_template_ref)
        and not item.reusable_template_contains_customer_identifiers
        for item in replay_validated
    )
    constraint_score = min(
        100.0,
        confirmed_ratio * 60.0
        + replay_ratio * 25.0
        + min(implicit_count, 3) / 3.0 * 5.0
        + min(reusable_constraints, 3) / 3.0 * 10.0,
    )
    constraint_layer = MoatLayerAssessment(
        layer="constraint_translation",
        evidence_coverage_score=round(constraint_score, 1),
        status=_coverage_status(constraint_score),
        customer_private_asset_count=len(confirmed_constraints),
        reusable_deidentified_asset_count=reusable_constraints,
        strengths=(
            [f"{len(confirmed_constraints)} source-backed customer constraints are retained."]
            if confirmed_constraints
            else []
        ),
        gaps=_dedupe(
            [
                *(
                    ["Constraint attestation is below 80%."]
                    if confirmed_ratio < 0.80
                    else []
                ),
                *(
                    ["No replay-validated deidentified constraint template is available."]
                    if not reusable_constraints
                    else []
                ),
            ]
        ),
    )

    case_count = len(auditable_cases)
    multi_plan_ratio = (
        sum(len(case.compared_plan_ids) >= 2 for case in auditable_cases) / case_count
        if case_count
        else 0.0
    )
    reviewed_ratio = (
        sum(case.planner_outcome != "not_reviewed" for case in auditable_cases) / case_count
        if case_count
        else 0.0
    )
    execution_ratio = (
        sum(bool(case.execution_result_ref) for case in auditable_cases) / case_count
        if case_count
        else 0.0
    )
    reusable_cases = sum(
        bool(case.deidentified_case_pattern_ref)
        and not case.case_pattern_contains_customer_identifiers
        for case in auditable_cases
    )
    validation_score = min(
        100.0,
        min(case_count, 10) / 10.0 * 45.0
        + multi_plan_ratio * 20.0
        + reviewed_ratio * 20.0
        + execution_ratio * 15.0,
    )
    validation_layer = MoatLayerAssessment(
        layer="validation_assets",
        evidence_coverage_score=round(validation_score, 1),
        status=_coverage_status(validation_score),
        customer_private_asset_count=case_count,
        reusable_deidentified_asset_count=reusable_cases,
        strengths=(
            [f"{case_count} auditable recovery cases are retained."] if case_count else []
        ),
        gaps=_dedupe(
            [
                *(["Fewer than five auditable replay cases are available."] if case_count < 5 else []),
                *(["No execution-result closure is available."] if execution_ratio == 0 else []),
                *(
                    ["No deidentified anomaly/operator case pattern is available."]
                    if reusable_cases == 0
                    else []
                ),
            ]
        ),
    )

    workflow_refs = _workflow_refs(request.workflow_evidence)
    workflow_score = min(
        100.0,
        len(workflow_refs) / 6.0 * 80.0
        + int("sandbox_writeback" in approvals) * 10.0
        + int(bool(request.workflow_evidence.approval_matrix_ref)) * 10.0,
    )
    reusable_workflow = int(
        bool(request.workflow_evidence.deployment_template_ref)
        and not request.workflow_evidence.deployment_template_contains_customer_identifiers
    )
    workflow_layer = MoatLayerAssessment(
        layer="workflow_embedding",
        evidence_coverage_score=round(workflow_score, 1),
        status=_coverage_status(workflow_score),
        customer_private_asset_count=len(workflow_refs),
        reusable_deidentified_asset_count=reusable_workflow,
        strengths=(
            ["Planner confirmation and approval matrix are referenced."]
            if request.workflow_evidence.planner_confirmation_ref
            and request.workflow_evidence.approval_matrix_ref
            else []
        ),
        gaps=_dedupe(
            [
                *(
                    ["Rollback runbook has not been evidenced."]
                    if not request.workflow_evidence.rollback_runbook_ref
                    else []
                ),
                *(
                    ["Sandbox contract test has not been evidenced."]
                    if not request.workflow_evidence.sandbox_contract_test_ref
                    else []
                ),
            ]
        ),
    )
    layers = [data_layer, constraint_layer, validation_layer, workflow_layer]
    if request.evidence_scope == "synthetic_sample":
        return [
            layer.model_copy(
                update={
                    "evidence_coverage_score": 0.0,
                    "status": "nascent",
                    "customer_private_asset_count": 0,
                    "reusable_deidentified_asset_count": 0,
                    "strengths": [],
                    "gaps": _dedupe(
                        [
                            "Synthetic fixtures do not count as customer or reusable moat evidence.",
                            *layer.gaps,
                        ]
                    ),
                }
            )
            for layer in layers
        ]
    return layers


def _valid_approval_map(
    approvals: list[GovernanceApproval],
) -> dict[ApprovalType, GovernanceApproval]:
    now = datetime.now(tz=timezone.utc)
    valid: dict[ApprovalType, GovernanceApproval] = {}
    for approval in approvals:
        expires_at = approval.expires_at
        in_force = expires_at is None or (
            expires_at.tzinfo is not None and expires_at > now
        )
        if (
            approval.approved
            and approval.approver_role
            and approval.evidence_ref
            and approval.approved_at is not None
            and approval.approved_at.tzinfo is not None
            and in_force
        ):
            valid[approval.approval_type] = approval
    return valid


def _confirmed_constraints(
    constraints: list[ConstraintAttestation],
) -> list[ConstraintAttestation]:
    return [
        item
        for item in constraints
        if item.status in {"customer_confirmed", "replay_validated"}
        and item.owner_role
        and item.source_refs
    ]


def _partition_cases(
    cases: list[RecoveryCaseEvidence],
) -> tuple[list[RecoveryCaseEvidence], list[str]]:
    duplicates = {case_id for case_id, count in Counter(case.case_id for case in cases).items() if count > 1}
    eligible: list[RecoveryCaseEvidence] = []
    excluded: list[str] = []
    for case in cases:
        if case.case_id in duplicates or not _case_is_auditable(case):
            excluded.append(case.case_id)
        else:
            eligible.append(case)
    return eligible, sorted(set(excluded))


def _case_is_auditable(case: RecoveryCaseEvidence) -> bool:
    if not case.baseline_source_ref or not case.reorch_output_ref:
        return False
    if not _has_comparable_metric(case.baseline_metrics, case.reorch_metrics):
        return False
    if case.evaluation_mode == "read_only_shadow":
        return bool(case.planner_decision_ref) and case.planner_outcome != "not_reviewed"
    if case.evaluation_mode == "controlled_execution":
        return bool(case.execution_result_ref)
    return True


def _has_comparable_metric(baseline: CaseMetrics, reorch: CaseMetrics) -> bool:
    return any(
        getattr(baseline, field) is not None and getattr(reorch, field) is not None
        for field in (
            "decision_minutes",
            "tardiness_minutes",
            "changeovers",
            "overtime_hours",
        )
    )


def _case_deltas(baseline: CaseMetrics, reorch: CaseMetrics) -> dict[str, float]:
    return {
        "saved_decision_minutes": _signed_delta(
            baseline.decision_minutes,
            reorch.decision_minutes,
        ),
        "reduced_tardiness_minutes": _signed_delta(
            baseline.tardiness_minutes,
            reorch.tardiness_minutes,
        ),
        "reduced_changeovers": _signed_delta(
            baseline.changeovers,
            reorch.changeovers,
        ),
        "reduced_overtime_hours": _signed_delta(
            baseline.overtime_hours,
            reorch.overtime_hours,
        ),
    }


def _signed_delta(baseline: float | int | None, reorch: float | int | None) -> float:
    if baseline is None or reorch is None:
        return 0.0
    return float(baseline) - float(reorch)


def _case_refs(case: RecoveryCaseEvidence) -> list[str]:
    return _refs(
        case.baseline_source_ref,
        case.reorch_output_ref,
        case.planner_decision_ref,
        case.execution_result_ref,
    )


def _workflow_refs(workflow: WorkflowEvidence) -> list[str]:
    return _refs(
        workflow.planner_confirmation_ref,
        workflow.approval_matrix_ref,
        workflow.audit_export_ref,
        workflow.rollback_runbook_ref,
        workflow.sandbox_contract_test_ref,
        workflow.deployment_template_ref,
    )


def _refs(*items: str | None) -> list[str]:
    return sorted({item for item in items if item})


def _coverage_status(score: float) -> MoatStatus:
    if score >= 75.0:
        return "validated"
    if score >= 40.0:
        return "building"
    return "nascent"


def _fingerprint(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
