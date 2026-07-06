"""Tests for production application readiness gating."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.planning import router as planning_router
from app.models.production_readiness import ProductionReadinessEvidence
from app.services.production_readiness import ProductionReadinessGate


def test_public_large_fjsp_pack_is_replay_ready_not_production_ready() -> None:
    response = ProductionReadinessGate().evaluate(_public_large_fjsp_evidence())

    assert response.decision == "replay_ready"
    assert "read_only_replay" in response.allowed_actions
    assert "production_writeback" in response.blocked_actions
    assert "unattended_autonomous_dispatch" in response.blocked_actions
    assert any(
        "rerun_on_customer_readonly_desensitized_or_shadow_data" == blocker
        for blocker in response.production_blockers
    )
    assert (
        "replace_public_benchmark_with_customer_validated_evidence"
        in response.production_blockers
    )


def test_customer_shadow_evidence_allows_shadow_without_writeback() -> None:
    evidence = _public_large_fjsp_evidence()
    evidence.evidence_source = "customer_desensitized"
    evidence.real_customer_data = True
    evidence.customer_provenance_confirmed = True
    evidence.quality_gate_enforced = True
    evidence.human_confirmation_enforced = True

    response = ProductionReadinessGate().evaluate(evidence)

    assert response.decision == "shadow_ready"
    assert "customer_shadow_mode" in response.allowed_actions
    assert "production_writeback" in response.blocked_actions
    assert "pass_sandbox_writeback_dry_run" in response.production_blockers


def test_full_closed_loop_evidence_is_production_ready() -> None:
    evidence = _public_large_fjsp_evidence()
    evidence.evidence_source = "customer_live_shadow"
    evidence.real_customer_data = True
    evidence.customer_provenance_confirmed = True
    evidence.planner_decision_count = 45
    evidence.planner_override_reason_count = 18
    evidence.execution_outcome_count = 42
    evidence.strategy_effect_matrix_cell_count = 18
    evidence.high_confidence_policy_cell_count = 5
    evidence.sandbox_writeback_passed = True
    evidence.approval_roles = ["planner", "production_manager"]
    evidence.idempotency_ready = True
    evidence.rollback_plan_ready = True
    evidence.compensation_ready = True
    evidence.audit_ready = True
    evidence.quality_gate_enforced = True
    evidence.human_confirmation_enforced = True
    evidence.p95_solver_latency_ms = 18_500
    evidence.p95_gate_latency_ms = 240
    evidence.concurrent_incident_tested = 3
    evidence.performance_targets_tested = [1000, 5000, 10000]
    evidence.security_review_passed = True
    evidence.backup_restore_drill_passed = True
    evidence.observability_alerting_ready = True
    evidence.sso_rbac_ready = True
    evidence.retention_policy_approved = True

    response = ProductionReadinessGate().evaluate(evidence)

    assert response.decision == "production_ready"
    assert "production_writeback" in response.allowed_actions
    assert "read_only_replay" in response.allowed_actions
    assert "counterfactual_replay" in response.allowed_actions
    assert "read_only_replay" not in response.blocked_actions
    assert response.production_blockers == []


def test_missing_snapshot_blocks_replay() -> None:
    evidence = _public_large_fjsp_evidence()
    evidence.snapshot_available = False

    response = ProductionReadinessGate().evaluate(evidence)

    assert response.decision == "blocked"
    assert response.allowed_actions == ["data_gap_analysis"]
    assert "provide_reconstructable_schedule_snapshot" in response.production_blockers


@pytest.mark.asyncio
async def test_production_readiness_api() -> None:
    test_app = FastAPI()
    test_app.include_router(planning_router)
    transport = ASGITransport(app=test_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/planning/production-readiness/evaluate",
            json=_public_large_fjsp_evidence().model_dump(mode="json"),
        )

    assert response.status_code == 200
    assert response.json()["decision"] == "replay_ready"


def _public_large_fjsp_evidence() -> ProductionReadinessEvidence:
    return ProductionReadinessEvidence(
        site_id="LARGE-FJSP-PACK-20260706",
        evidence_source="public_benchmark",
        real_customer_data=False,
        customer_provenance_confirmed=False,
        p0_permission_level="shadow_ready",
        p0_readiness_score=0.90,
        snapshot_available=True,
        work_order_count=80,
        operation_count=517,
        resource_count=60,
        incident_count=30,
        solved_incident_count=30,
        feasible_option_count=71,
        infeasible_option_count=43,
        p95_solver_latency_ms=23.8,
        p95_gate_latency_ms=29.31,
        concurrent_incident_tested=1,
        performance_targets_tested=[1000, 5000, 10000],
    )
