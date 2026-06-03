"""Tests for the NGS lab protected repair portfolio."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.services.ngs_lab import NgsProtectedPortfolioService


def test_ngs_demo_generates_top_k_feasible_and_rejected_candidates():
    response = NgsProtectedPortfolioService().run_demo()

    assert response.product_name == "ReOrch for NGS Lab Scheduling"
    assert response.impact_report.impacted_samples == ["S-002", "S-003"]
    assert len(response.feasible_candidates) >= 3
    assert len(response.rejected_candidates) >= 1
    assert response.recommended_candidate is not None
    assert response.recommended_candidate.candidate_id in {
        candidate.candidate_id for candidate in response.feasible_candidates
    }

    scores = [candidate.soft_score for candidate in response.feasible_candidates]
    assert scores == sorted(scores, reverse=True)
    assert all(candidate.hard_feasible for candidate in response.feasible_candidates)
    assert all(candidate.gate_report and candidate.gate_report.pass_gate for candidate in response.feasible_candidates)


def test_ngs_dispatch_baseline_is_blocked_by_protected_quality_gates():
    response = NgsProtectedPortfolioService().run_demo()
    dispatch = next(
        candidate
        for candidate in response.rejected_candidates
        if candidate.strategy_type == "dispatching_urgent_first"
    )

    assert dispatch.gate_report is not None
    assert dispatch.hard_feasible is False
    assert dispatch.gate_report.pass_gate is False
    blocked_gates = {issue.gate for issue in dispatch.gate_report.hard_blockers}
    assert {
        "qc_route_safety",
        "reagent_validity",
        "index_compatibility",
        "resource_calendar",
    }.issubset(blocked_gates)
    assert dispatch.explanation
    assert dispatch.explanation.startswith("Rejected by protected feasibility gate")


def test_ngs_agent_trace_exposes_real_decision_chain_boundaries():
    response = NgsProtectedPortfolioService().run_demo()
    agents = {step.agent_name: step for step in response.agent_trace}

    assert set(agents) == {
        "NGS Incident Agent",
        "Constraint Evidence Agent",
        "Protected Portfolio Agent",
        "Explanation Agent",
        "Case Memory Agent",
        "Preference Learning Agent",
    }
    assert "hard gate 未通过" in agents["Protected Portfolio Agent"].boundary
    assert agents["Preference Learning Agent"].output_refs == ["preference_profile:not_updated"]
    assert all(0.0 <= step.confidence <= 1.0 for step in response.agent_trace)


def test_ngs_batch_replay_reads_experiment_package():
    batch = NgsProtectedPortfolioService().run_batch_replay()

    assert batch.package_id == "ngs-lrsp-public-safe-batch-v1"
    assert batch.aggregate_metrics["case_count"] == 3
    assert batch.aggregate_metrics["pass_count"] == 3
    assert {case.case_id for case in batch.case_results} == {"LAB_A", "LAB_B", "LAB_C"}
    assert {
        case.response.recommended_candidate.strategy_type
        for case in batch.case_results
        if case.response.recommended_candidate
    } == {"reagent_repair", "stage_first_redistribution", "event_local_repair"}


def test_ngs_batch_replay_accepts_uploaded_package_payload():
    package = {
        "package_id": "uploaded-ngs-package",
        "version": "v-test",
        "cases": [
            {
                "case_id": "LAB_UPLOAD",
                "scenario_id": "uploaded_reagent_scenario",
                "expected": {
                    "min_feasible": 1,
                    "min_rejected": 1,
                    "recommended_strategy": "reagent_repair",
                },
            }
        ],
    }
    batch = NgsProtectedPortfolioService().run_batch_replay(
        package_payload=package,
        source_name="unit_test_upload.json",
    )

    assert batch.package_id == "uploaded-ngs-package"
    assert batch.source_path == "unit_test_upload.json"
    assert batch.aggregate_metrics["case_count"] == 1
    assert batch.case_results[0].case_id == "LAB_UPLOAD"


@pytest.mark.asyncio
async def test_ngs_demo_run_api_returns_auditable_portfolio():
    from fastapi import FastAPI

    from app.api.ngs_lab import router

    test_app = FastAPI()
    test_app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        resp = await client.post("/api/v1/ngs-lab/demo-run")

    assert resp.status_code == 200
    data = resp.json()
    assert data["audit_package"]["candidate_count"] >= 4
    assert data["audit_package"]["lims_writeback_executed"] is False
    assert data["recommended_candidate"]["hard_feasible"] is True
    assert len(data["agent_trace"]) == 6


@pytest.mark.asyncio
async def test_ngs_batch_replay_api_returns_package_results():
    from fastapi import FastAPI

    from app.api.ngs_lab import router

    test_app = FastAPI()
    test_app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        resp = await client.post("/api/v1/ngs-lab/batch-replay")

    assert resp.status_code == 200
    data = resp.json()
    assert data["package_id"] == "ngs-lrsp-public-safe-batch-v1"
    assert data["aggregate_metrics"]["pass_rate"] == 1.0
    assert len(data["case_results"]) == 3


@pytest.mark.asyncio
async def test_ngs_batch_replay_api_accepts_payload_and_records_planner_decision():
    from fastapi import FastAPI

    from app.api.ngs_lab import _ngs_planner_decisions, router

    _ngs_planner_decisions.clear()
    test_app = FastAPI()
    test_app.include_router(router)
    package = {
        "package_id": "uploaded-ngs-package",
        "version": "v-test",
        "cases": [
            {
                "case_id": "LAB_UPLOAD",
                "scenario_id": "uploaded_reagent_scenario",
                "expected": {
                    "min_feasible": 1,
                    "min_rejected": 1,
                    "recommended_strategy": "reagent_repair",
                },
            }
        ],
    }

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        replay_resp = await client.post(
            "/api/v1/ngs-lab/batch-replay",
            json={"package_payload": package, "source_name": "uploaded.json"},
        )
        candidate_id = replay_resp.json()["case_results"][0]["response"]["recommended_candidate"]["candidate_id"]
        decision_resp = await client.post(
            "/api/v1/ngs-lab/planner-decisions",
            json={
                "package_id": "uploaded-ngs-package",
                "case_id": "LAB_UPLOAD",
                "action": "override",
                "selected_candidate_id": candidate_id,
                "planner_id": "planner-1",
                "override_reason": "Planner selected this option to reduce rescue burden.",
            },
        )

    assert replay_resp.status_code == 200
    assert replay_resp.json()["package_id"] == "uploaded-ngs-package"
    assert decision_resp.status_code == 200
    data = decision_resp.json()
    assert data["record"]["action"] == "override"
    assert data["record"]["lims_writeback_executed"] is False
    assert data["records"][0]["audit_refs"][0] == "ngs_package:uploaded-ngs-package"
