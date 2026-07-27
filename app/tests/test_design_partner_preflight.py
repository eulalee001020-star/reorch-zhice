"""Tests for evidence-gated Design Partner onboarding."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.design_partner import (
    CaseMetrics,
    ConstraintAttestation,
    DataProvenanceEvidence,
    DesignPartnerPreflightRequest,
    GovernanceApproval,
    RecoveryCaseEvidence,
    RoiCostModel,
    WorkflowEvidence,
)
from app.services.design_partner_preflight import DesignPartnerPreflightService
from app.services.reality_harness import P0RealityHarnessService

_NOW = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)


def _approval(approval_type: str) -> GovernanceApproval:
    return GovernanceApproval(
        approval_type=approval_type,
        approved=True,
        approver_role="Workshop data owner",
        evidence_ref=f"evidence/governance/{approval_type}.pdf",
        approved_at=_NOW,
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


def _request(*, with_core_governance: bool = True) -> DesignPartnerPreflightRequest:
    reality_request = P0RealityHarnessService().load_sample_pack(
        source_system="customer_export",
        workshop_id="SITE-01",
    )
    approvals = []
    if with_core_governance:
        approvals = [
            _approval("data_use"),
            _approval("historical_replay"),
            _approval("retention"),
            _approval("security_review"),
        ]
    return DesignPartnerPreflightRequest(
        evidence_scope="customer_provided",
        customer_ref="CUSTOMER-ALPHA",
        site_id="SITE-01",
        reality_request=reality_request,
        provenance=DataProvenanceEvidence(
            dataset_name="site-01-history-v1",
            source_systems=["ERP", "MES", "APS"],
            exported_at=_NOW,
            data_window_start=_NOW - timedelta(days=90),
            data_window_end=_NOW,
            data_owner_role="MES owner",
            data_owner_approved=True,
            replay_authorized=True,
            desensitized=True,
            provenance_ref="evidence/data/manifest.sha256",
            mapping_profile_ref="evidence/data/mapping-v1.json",
            mapping_approved_by="MES owner",
        ),
        governance_approvals=approvals,
    )


def _replay_cases(count: int = 5) -> list[RecoveryCaseEvidence]:
    return [
        RecoveryCaseEvidence(
            case_id=f"CASE-{index:03d}",
            incident_type="machine_down",
            evaluation_mode="historical_replay",
            recovery_operator_ids=["reroute", "shift_right"],
            compared_plan_ids=[f"P-{index}-A", f"P-{index}-B"],
            selected_plan_id=f"P-{index}-A",
            planner_outcome="accepted",
            baseline_metrics=CaseMetrics(
                decision_minutes=45,
                tardiness_minutes=120,
                changeovers=4,
                overtime_hours=2,
            ),
            reorch_metrics=CaseMetrics(
                decision_minutes=15,
                tardiness_minutes=90,
                changeovers=3,
                overtime_hours=1,
            ),
            baseline_source_ref=f"evidence/cases/{index}/baseline.json",
            reorch_output_ref=f"evidence/cases/{index}/replay.json",
            planner_decision_ref=f"evidence/cases/{index}/decision.json",
            deidentified_case_pattern_ref=f"templates/machine-down-{index}.json",
            case_pattern_contains_customer_identifiers=False,
        )
        for index in range(count)
    ]


def _confirmed_constraints(count: int = 5) -> list[ConstraintAttestation]:
    categories = ["material", "quality", "tooling", "calendar", "planner_policy"]
    return [
        ConstraintAttestation(
            constraint_id=f"C-{index:03d}",
            category=categories[index % len(categories)],
            enforcement="hard" if index < 3 else "preference",
            status="replay_validated",
            owner_role="Planning owner",
            source_refs=[f"evidence/constraints/C-{index:03d}.pdf"],
            reusable_template_ref=f"templates/C-{index:03d}.json",
            reusable_template_contains_customer_identifiers=False,
        )
        for index in range(count)
    ]


def _add_ten_unique_incidents(request: DesignPartnerPreflightRequest) -> None:
    template = request.reality_request.raw_incidents[0]
    request.reality_request.raw_incidents = [
        {
            **template,
            "incident_id": f"INC-{index:03d}",
            "start_time": (_NOW - timedelta(days=index + 1)).isoformat(),
        }
        for index in range(10)
    ]


def test_missing_governance_blocks_replay() -> None:
    response = DesignPartnerPreflightService().assess(
        _request(with_core_governance=False)
    )

    assert response.stage == "data_repair"
    assert "historical_replay" not in response.allowed_actions
    assert "production_writeback" in response.blocked_actions
    governance = next(
        check for check in response.checks if check.check_id == "core_governance_approvals"
    )
    assert governance.status == "blocked"


def test_initial_customer_pack_is_replay_ready_but_not_shadow_ready() -> None:
    request = _request()

    first = DesignPartnerPreflightService().assess(request)
    second = DesignPartnerPreflightService().assess(request)

    assert first.stage == "replay_ready"
    assert "historical_replay" in first.allowed_actions
    assert "read_only_shadow" in first.blocked_actions
    assert first.roi_summary.evidence_level == "none"
    assert first.preflight_id == second.preflight_id
    assert first.data_fingerprint == second.data_fingerprint


def test_shadow_gate_requires_cases_constraints_workflow_and_approval() -> None:
    request = _request()
    _add_ten_unique_incidents(request)
    request.constraints = _confirmed_constraints()
    request.recovery_cases = _replay_cases()
    request.governance_approvals.append(_approval("read_only_shadow"))
    request.workflow_evidence = WorkflowEvidence(
        planner_confirmation_ref="evidence/workflow/confirmation.json",
        approval_matrix_ref="evidence/workflow/approval-matrix.pdf",
        audit_export_ref="evidence/workflow/audit-export.json",
        rollback_runbook_ref="evidence/workflow/rollback.md",
    )
    request.roi_cost_model = RoiCostModel(
        planner_hourly_cost=150,
        tardiness_cost_per_minute=8,
        changeover_cost=500,
        overtime_hourly_cost=200,
        poc_cost=100_000,
        cost_source_ref="evidence/finance/cost-model.xlsx",
        finance_confirmed_by="Finance owner",
    )

    response = DesignPartnerPreflightService().assess(request)

    assert response.stage == "shadow_ready"
    assert "read_only_shadow" in response.allowed_actions
    assert response.roi_summary.evidence_level == "replay_counterfactual"
    assert response.roi_summary.estimated_case_savings > 0
    assert response.roi_summary.realized_case_savings == 0
    assert response.roi_summary.roi_ratio is None
    assert "not realized savings" in response.roi_summary.claim_allowed


def test_only_execution_and_finance_evidence_produces_roi_ratio() -> None:
    request = _request()
    request.recovery_cases = [
        RecoveryCaseEvidence(
            case_id="EXEC-001",
            incident_type="machine_down",
            evaluation_mode="controlled_execution",
            compared_plan_ids=["PLAN-A", "PLAN-B"],
            planner_outcome="accepted",
            baseline_metrics=CaseMetrics(
                decision_minutes=40,
                tardiness_minutes=100,
            ),
            reorch_metrics=CaseMetrics(
                decision_minutes=10,
                tardiness_minutes=50,
            ),
            baseline_source_ref="evidence/exec/baseline.json",
            reorch_output_ref="evidence/exec/reorch.json",
            planner_decision_ref="evidence/exec/decision.json",
            execution_result_ref="evidence/exec/result.json",
        )
    ]
    request.roi_cost_model = RoiCostModel(
        planner_hourly_cost=120,
        tardiness_cost_per_minute=10,
        poc_cost=500,
        cost_source_ref="evidence/finance/cost-model.xlsx",
        finance_confirmed_by="Finance owner",
    )

    response = DesignPartnerPreflightService().assess(request)

    assert response.roi_summary.evidence_level == "finance_validated_execution"
    assert response.roi_summary.realized_case_savings == 560
    assert response.roi_summary.roi_ratio == 0.12


def test_roi_ledger_keeps_negative_outcomes_visible() -> None:
    request = _request()
    request.recovery_cases = [
        RecoveryCaseEvidence(
            case_id="REGRESSION-001",
            incident_type="machine_down",
            evaluation_mode="controlled_execution",
            baseline_metrics=CaseMetrics(decision_minutes=10),
            reorch_metrics=CaseMetrics(decision_minutes=20),
            baseline_source_ref="evidence/regression/baseline.json",
            reorch_output_ref="evidence/regression/reorch.json",
            execution_result_ref="evidence/regression/result.json",
        )
    ]
    request.roi_cost_model = RoiCostModel(planner_hourly_cost=60)

    response = DesignPartnerPreflightService().assess(request)

    assert response.roi_summary.measured_deltas["saved_decision_minutes"] == -10
    assert response.roi_summary.estimated_case_savings == -10
    assert response.roi_summary.realized_case_savings == -10


@pytest.mark.asyncio
async def test_design_partner_preflight_api_contract() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/planning/design-partner/preflight",
            json=_request().model_dump(mode="json"),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "replay_ready"
    assert body["claim_boundary"].startswith("This preflight validates")
    assert len(body["moat_layers"]) == 4


@pytest.mark.asyncio
async def test_sample_preflight_cannot_be_misread_as_customer_evidence() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/planning/design-partner/sample-preflight"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["evidence_scope"] == "synthetic_sample"
    assert body["stage"] == "replay_ready"
    assert body["claim_boundary"].startswith("Synthetic sample only")
    assert all(layer["evidence_coverage_score"] == 0 for layer in body["moat_layers"])
    assert all(layer["customer_private_asset_count"] == 0 for layer in body["moat_layers"])
