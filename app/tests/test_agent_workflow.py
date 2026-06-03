"""Tests for the controlled Agent workflow API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.analysis import _impact_report_cache, _snapshot_store, _strategy_cache
from app.api.incidents import _incident_store
from app.api.solver import _candidate_plans_store, _plan_index, _recommendation_store
from app.models.enums import (
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ReportSource,
)
from app.models.incident import Incident
from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder


@pytest.fixture(autouse=True)
def _clear_stores():
    from app.api.agents import _rule_candidate_review_store
    from app.api.cases import _case_library

    _rule_candidate_review_store.clear()
    _incident_store.clear()
    _snapshot_store.clear()
    _impact_report_cache.clear()
    _strategy_cache.clear()
    _candidate_plans_store.clear()
    _plan_index.clear()
    _recommendation_store.clear()
    _case_library._case_store.clear()
    _case_library._preference_store.clear()
    yield
    _rule_candidate_review_store.clear()
    _incident_store.clear()
    _snapshot_store.clear()
    _impact_report_cache.clear()
    _strategy_cache.clear()
    _candidate_plans_store.clear()
    _plan_index.clear()
    _recommendation_store.clear()
    _case_library._case_store.clear()
    _case_library._preference_store.clear()


def _make_app():
    from fastapi import FastAPI

    from app.api.agents import router as agents_router

    test_app = FastAPI()
    test_app.include_router(agents_router)
    return test_app


def _seed_incident(**overrides: Any) -> Incident:
    defaults: dict[str, Any] = {
        "incident_id": uuid4(),
        "incident_type": IncidentType.EQUIPMENT_FAILURE.value,
        "occurred_at": datetime(2024, 6, 15, 8, 0, 0, tzinfo=timezone.utc),
        "resource_id": "CNC-001",
        "report_source": ReportSource.MES.value,
        "severity": IncidentSeverity.P3_MEDIUM.value,
        "status": IncidentStatus.PENDING_ANALYSIS.value,
        "created_at": datetime.now(tz=timezone.utc),
    }
    defaults.update(overrides)
    incident = Incident(**defaults)
    _incident_store[str(incident.incident_id)] = incident
    return incident


def _seed_snapshot() -> ScheduleSnapshot:
    base_time = datetime(2024, 6, 15, 8, 0, 0, tzinfo=timezone.utc)
    work_orders = [
        WorkOrder(
            work_order_id="WO-001",
            product_name="Product-A",
            due_date=datetime(2024, 6, 20, 18, 0, 0, tzinfo=timezone.utc),
            operations=[
                Operation(
                    operation_id="OP-001",
                    work_order_id="WO-001",
                    resource_id="CNC-001",
                    start_time=base_time,
                    end_time=datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
                    successor_ids=["OP-002"],
                ),
                Operation(
                    operation_id="OP-002",
                    work_order_id="WO-001",
                    resource_id="CNC-002",
                    start_time=datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
                    end_time=datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
                    predecessor_ids=["OP-001"],
                ),
            ],
            priority=3,
        ),
        WorkOrder(
            work_order_id="WO-002",
            product_name="Product-B",
            due_date=datetime(2024, 6, 21, 18, 0, 0, tzinfo=timezone.utc),
            operations=[
                Operation(
                    operation_id="OP-003",
                    work_order_id="WO-002",
                    resource_id="CNC-003",
                    start_time=datetime(2024, 6, 15, 8, 0, 0, tzinfo=timezone.utc),
                    end_time=datetime(2024, 6, 15, 9, 0, 0, tzinfo=timezone.utc),
                ),
            ],
            priority=1,
        ),
        WorkOrder(
            work_order_id="WO-003",
            product_name="Product-C",
            due_date=datetime(2024, 6, 22, 18, 0, 0, tzinfo=timezone.utc),
            operations=[
                Operation(
                    operation_id="OP-004",
                    work_order_id="WO-003",
                    resource_id="CNC-004",
                    start_time=datetime(2024, 6, 15, 9, 0, 0, tzinfo=timezone.utc),
                    end_time=datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
                ),
            ],
            priority=0,
        ),
    ]
    snapshot = ScheduleSnapshot(
        snapshot_id=uuid4(),
        captured_at=datetime(2024, 6, 15, 7, 55, 0, tzinfo=timezone.utc),
        workshop_id="WS-01",
        source_system="aps",
        work_orders=work_orders,
    )
    _snapshot_store[str(snapshot.snapshot_id)] = snapshot
    return snapshot


@pytest.mark.asyncio
async def test_incident_agent_understands_machine_down_text():
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/agents/incident/understand",
            json={
                "text": "CNC-02 停了，估计要修三个小时，几个急单可能受影响。",
                "workshop_id": "WS-01",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["incident_type"] == "machine_down"
    assert data["resource_id"] == "CNC-02"
    assert data["estimated_duration_minutes"] == 180
    assert data["risk_hint"] == "urgent_order_delay"
    assert data["supported_by_solver"] is True
    assert data["requires_human_confirmation"] is False
    assert data["incident_create_request"]["incident_type"] == "equipment_failure"


@pytest.mark.asyncio
async def test_incident_agent_uses_configured_llm_when_available(monkeypatch):
    from app.services.llm_agent_client import LLMJsonResult

    class FakeLLMClient:
        async def complete_json(self, **kwargs):
            return LLMJsonResult(
                data={
                    "incident_type": "machine_down",
                    "resource_id": "M-03",
                    "estimated_duration_minutes": 240,
                    "risk_hint": "urgent_order_delay",
                    "confidence": 0.91,
                    "supported_by_solver": True,
                    "requires_human_confirmation": False,
                    "unsupported_reason": None,
                },
                provider="fake_llm",
                model="fake-small-agent",
                latency_ms=123.4,
                input_tokens=110,
                output_tokens=45,
            )

    monkeypatch.setattr("app.services.agent_workflow.LLMAgentClient", FakeLLMClient)

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/agents/incident/understand",
            json={
                "text": "设备三号停机，预计四小时，急单有延期风险。",
                "workshop_id": "WS-01",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["resource_id"] == "M-03"
    assert data["estimated_duration_minutes"] == 240
    assert data["trace"][0]["llm_used"] is True
    assert data["trace"][0]["llm_provider"] == "fake_llm"
    assert data["trace"][0]["model_name"] == "fake-small-agent"
    assert data["trace"][0]["input_tokens"] == 110


@pytest.mark.asyncio
async def test_incident_agent_routes_unsupported_low_context_to_confirmation():
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/agents/incident/understand",
            json={"text": "物料还没到"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["incident_type"] == "material_shortage"
    assert data["supported_by_solver"] is False
    assert data["requires_human_confirmation"] is True
    assert data["incident_create_request"] is None


@pytest.mark.asyncio
async def test_agent_decision_flow_runs_tools_without_auto_writeback():
    incident = _seed_incident()
    _seed_snapshot()
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/agents/decision-flow",
            json={
                "incident_id": str(incident.incident_id),
                "estimated_repair_time_minutes": 60,
                "goal_mode": "balanced",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["impact_report"]["incident_id"] == str(incident.incident_id)
    assert data["strategy"]["strategy_type"] in {
        "wait_and_repair",
        "local_repair",
        "global_reschedule",
    }
    assert len(data["candidate_plans"]) >= 1
    assert len(data["quality_gates"]) == len(data["candidate_plans"])
    assert data["quality_gates"][0]["plan_id"] == data["candidate_plans"][0]["plan_id"]
    assert "recommendation_policy" in data["quality_gates"][0]
    assert data["comparison_matrix"] is not None
    assert data["recommendation"] is not None
    assert data["requires_human_confirmation"] is True
    assert len(data["candidate_plans"]) >= 2
    assert len({plan["strategy_type"] for plan in data["candidate_plans"]}) >= 2

    trace_names = [step["agent_name"] for step in data["trace"]]
    assert "Impact Analysis Agent" in trace_names
    assert "Strategy Agent" in trace_names
    assert "Solver Tool / Solver Agent" in trace_names
    assert "Quality Gate Agent" in trace_names
    assert "Evaluation Agent" in trace_names
    assert "Confirmation Agent" in trace_names


@pytest.mark.asyncio
async def test_feedback_agent_structures_operator_override():
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/agents/feedback/structure",
            json={"override_text": "M4 operator unavailable after 16:00"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["override_reason"] == "operator_preference"
    assert "M4" in data["future_rule_candidate"]
    assert "16:00" in data["future_rule_candidate"]
    assert data["rule_candidates"][0]["status"] == "pending_human_review"
    assert data["rule_candidates"][0]["constraint_type"] == "calendar"
    assert data["requires_human_review"] is False


@pytest.mark.asyncio
async def test_rule_candidate_agent_compiles_pending_constraint():
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/agents/rules/compile",
            json={
                "rule_text": "M4 operator unavailable after 16:00, urgent jobs should avoid it",
                "source": "lab_replay",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["requires_human_review"] is True
    candidate = data["candidates"][0]
    assert candidate["constraint_type"] == "calendar"
    assert candidate["scope"]["machine_ids"] == ["M4"]
    assert candidate["status"] == "pending_human_review"
    assert "16:00" in candidate["compiled_rule"]


@pytest.mark.asyncio
async def test_rule_candidate_review_replay_publish_lifecycle():
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        compile_resp = await client.post(
            "/api/v1/agents/rules/compile",
            json={
                "rule_text": "M4 operator unavailable after 16:00, urgent jobs should avoid it",
                "source": "lab_replay",
            },
        )
        candidate_id = compile_resp.json()["candidates"][0]["candidate_id"]

        list_resp = await client.get("/api/v1/agents/rules/candidates")
        review_resp = await client.post(
            f"/api/v1/agents/rules/candidates/{candidate_id}/review",
            json={
                "action": "approve_for_replay",
                "reviewer_id": "planner-1",
                "review_note": "scope confirmed for replay",
            },
        )
        replay_resp = await client.post(
            f"/api/v1/agents/rules/candidates/{candidate_id}/replay",
            json={"scenario_set": "lab_replay_acceptance", "scenario_count": 3},
        )
        publish_resp = await client.post(
            f"/api/v1/agents/rules/candidates/{candidate_id}/publish",
            json={"publisher_id": "planner-1", "release_note": "validated in replay"},
        )

    assert compile_resp.status_code == 200
    assert list_resp.status_code == 200
    assert list_resp.json()["status_counts"]["pending_human_review"] == 1
    assert review_resp.status_code == 200
    assert review_resp.json()["status"] == "approved_for_replay"
    assert replay_resp.status_code == 200
    assert replay_resp.json()["status"] == "replay_passed"
    assert replay_resp.json()["replay_result"]["pass_replay"] is True
    assert publish_resp.status_code == 200
    publish_data = publish_resp.json()
    assert publish_data["status"] == "published_readonly"
    assert publish_data["published_record"]["readonly"] is True


@pytest.mark.asyncio
async def test_rule_candidate_reject_requires_reason():
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        compile_resp = await client.post(
            "/api/v1/agents/rules/compile",
            json={"rule_text": "现场说这个约束还不清楚", "source": "planner_feedback"},
        )
        candidate_id = compile_resp.json()["candidates"][0]["candidate_id"]
        reject_resp = await client.post(
            f"/api/v1/agents/rules/candidates/{candidate_id}/review",
            json={"action": "reject", "reviewer_id": "planner-1"},
        )
        reject_with_reason_resp = await client.post(
            f"/api/v1/agents/rules/candidates/{candidate_id}/review",
            json={
                "action": "reject",
                "reviewer_id": "planner-1",
                "reject_reason": "缺少资源、时间窗口和适用工序。",
            },
        )

    assert reject_resp.status_code == 422
    assert reject_with_reason_resp.status_code == 200
    assert reject_with_reason_resp.json()["status"] == "rejected"
    assert reject_with_reason_resp.json()["reject_reason"] == "缺少资源、时间窗口和适用工序。"


@pytest.mark.asyncio
async def test_rule_candidate_agent_accepts_llm_candidate(monkeypatch):
    from app.services.llm_agent_client import LLMJsonResult

    class FakeLLMClient:
        async def complete_json(self, **kwargs):
            return LLMJsonResult(
                data={
                    "constraint_type": "quality",
                    "scope": {"machine_ids": ["QC-01"], "operation_ids": ["OP-7"]},
                    "compiled_rule": "require QA hold release before OP-7 can be moved",
                    "confidence": 0.84,
                    "risk_note": "QA rule candidate needs human review and replay.",
                },
                provider="fake_llm",
                model="fake-small-agent",
                latency_ms=89.0,
            )

    monkeypatch.setattr("app.services.agent_workflow.LLMAgentClient", FakeLLMClient)

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/agents/rules/compile",
            json={
                "rule_text": "QA hold 没放行前不要移动 OP-7",
                "source": "offline_llm_eval",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    candidate = data["candidates"][0]
    assert candidate["constraint_type"] == "quality"
    assert candidate["compiled_rule"] == "require QA hold release before OP-7 can be moved"
    assert data["trace"][0]["llm_used"] is True
    assert data["trace"][0]["llm_provider"] == "fake_llm"


@pytest.mark.asyncio
async def test_case_memory_and_preference_learning_agents_archive_assets():
    decision_record = _make_decision_record()
    execution_result = _make_execution_result(decision_record)
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        archive_resp = await client.post(
            "/api/v1/agents/case-memory/archive",
            json={
                "decision_record": decision_record.model_dump(mode="json"),
                "execution_result": execution_result.model_dump(mode="json"),
                "case_status": "validated_in_lab",
            },
        )
        learn_resp = await client.post(
            "/api/v1/agents/preference/learn",
            json={"planner_id": "planner-1", "min_samples": 1},
        )

    assert archive_resp.status_code == 200
    archive_data = archive_resp.json()
    assert archive_data["case_record"]["strategy_type"] == "local_repair"
    assert archive_data["status"] == "validated_in_lab"
    assert archive_data["case_record"]["is_override"] is True

    assert learn_resp.status_code == 200
    learn_data = learn_resp.json()
    assert learn_data["sample_count"] == 1
    assert learn_data["recommended_use"] == "ranking_tiebreaker_only"
    assert learn_data["preference_profile"]["planner_id"] == "planner-1"


@pytest.mark.asyncio
async def test_post_decision_learning_runs_rule_case_preference_chain():
    decision_record = _make_decision_record()
    execution_result = _make_execution_result(decision_record)
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/agents/post-decision-learning",
            json={
                "decision_record": decision_record.model_dump(mode="json"),
                "execution_result": execution_result.model_dump(mode="json"),
                "min_samples": 1,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["rule_candidate_output"]["candidates"][0]["status"] == "pending_human_review"
    assert data["case_memory_output"]["status"] == "execution_feedback_captured"
    assert data["preference_learning_output"]["sample_count"] == 1
    assert data["preference_learning_output"]["recommended_use"] == "ranking_tiebreaker_only"
    assert [step["agent_name"] for step in data["trace"]] == [
        "Rule Candidate Agent",
        "Case Memory Agent",
        "Preference Learning Agent",
    ]


def _make_decision_record():
    from app.models.decision import DecisionRecord
    from app.models.solver import SolverChain

    plan_id = uuid4()
    return DecisionRecord(
        decision_record_id=uuid4(),
        incident_id=uuid4(),
        impact_report_summary="M4 downtime affects one urgent order",
        strategy_type="local_repair",
        all_candidate_plan_ids=[plan_id],
        recommended_plan_id=uuid4(),
        confirmed_plan_id=plan_id,
        derived_from_plan_id=plan_id,
        is_override=True,
        is_manual_adjusted=False,
        override_reason="M4 operator unavailable after 16:00",
        confirmed_by="planner-1",
        confirmed_at=datetime.now(tz=timezone.utc),
        plan_selection_input_version="1.0",
        plan_selection_output_version="1.0",
        solver_chain=SolverChain(
            strategy_type="local_repair",
            rule_selection="due_date_priority",
            neighborhood_selection="critical_path",
            repair_policy="balanced",
            solver_name="cp_sat",
            key_parameters={"timeout": 60},
            search_budget_seconds=60.0,
            constraint_validation_result="feasible",
        ),
        rule_selector_version="1.0.0",
        neighborhood_selector_version="1.0.0",
        repair_policy_advisor_version="1.0.0",
    )


def _make_execution_result(decision_record):
    from app.models.execution import ExecutionResult

    return ExecutionResult(
        incident_id=decision_record.incident_id,
        decision_record_id=decision_record.decision_record_id,
        actual_completion_times={},
        planned_completion_times={},
        actual_otd=0.94,
        actual_resource_utilization=0.82,
        deviation_percentage=4.5,
    )
