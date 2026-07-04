"""Tests for the Constraint-to-Recovery technical kernel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.planning import router as planning_router
from app.models.enums import IncidentSeverity, IncidentStatus, IncidentType, ReportSource
from app.models.incident import Incident
from app.models.planning import (
    DataReadinessReport,
    ReadinessIssue,
)
from app.models.schedule import Operation, Resource, ScheduleDetail, ScheduleSnapshot, WorkOrder
from app.models.solver import CandidatePlan, ConstraintValidationReport, SolverChain, SolverMetadata
from app.models.technical_kernel import (
    DecisionGraphBuildRequest,
    EvidenceGateRequest,
    RecoveryOperatorRequest,
)
from app.services.plan_quality_gate import PlanQualityGate
from app.services.technical_kernel import (
    DecisionGraphService,
    EvidenceGateService,
    RecoveryOperatorPortfolioService,
)


def test_decision_graph_builds_affected_subgraph_and_frontier() -> None:
    start = datetime(2026, 7, 4, 8, tzinfo=timezone.utc)
    snapshot = _snapshot(start)
    incident = _incident(start + timedelta(minutes=30))

    response = DecisionGraphService().build(
        DecisionGraphBuildRequest(
            snapshot=snapshot,
            incident=incident,
            freeze_operation_ids=["OP-20"],
        )
    )

    assert response.metrics["node_count"] == 6
    assert set(response.affected_operation_ids) == {"OP-10", "OP-20"}
    assert response.downstream_operation_ids == ["OP-20"]
    assert response.repairable_frontier_ids == ["OP-10"]
    assert response.alternative_resources["OP-10"] == ["CNC-02"]


def test_recovery_operator_portfolio_selects_equipment_repair_paths() -> None:
    start = datetime(2026, 7, 4, 8, tzinfo=timezone.utc)
    graph = DecisionGraphService().build(
        DecisionGraphBuildRequest(
            snapshot=_snapshot(start),
            incident=_incident(start + timedelta(minutes=30)),
        )
    )
    response = RecoveryOperatorPortfolioService().select(
        RecoveryOperatorRequest(
            incident=_incident(start + timedelta(minutes=30)),
            decision_graph=graph,
            max_operator_count=4,
        )
    )

    operator_types = [item.operator_type for item in response.recommendations]

    assert response.repair_scope == "local"
    assert "wait_and_shift" in operator_types
    assert "alternative_machine_repair" in operator_types
    assert "local_insertion" in operator_types
    assert response.recommendations[0].rank == 1
    assert all("Gate" in gate for item in response.recommendations for gate in item.required_gates)


def test_evidence_gate_blocks_writeback_without_confirmation_and_source_refs() -> None:
    start = datetime(2026, 7, 4, 8, tzinfo=timezone.utc)
    plan = _candidate_plan(_schedule(start))
    quality = PlanQualityGate().evaluate(plan)
    request = EvidenceGateRequest(
        data_readiness=DataReadinessReport(
            is_ready=True,
            readiness_score=0.95,
            required_inputs=[],
            recommendations=[],
        ),
        candidate_plans=[plan],
        quality_gates=[quality],
        source_refs=[],
        planner_confirmed=False,
    )

    response = EvidenceGateService().evaluate(request)

    assert response.allow_solve is True
    assert response.allow_recommendation is True
    assert response.allow_formal_explanation is False
    assert response.allow_writeback is False
    assert response.recommendation_policy == "show_as_reference_only"
    assert {finding.gate_name for finding in response.findings} >= {
        "DataGate",
        "ConstraintGate",
        "EvidenceGate",
        "WritebackGate",
    }


def test_evidence_gate_stops_solve_when_data_has_blockers() -> None:
    start = datetime(2026, 7, 4, 8, tzinfo=timezone.utc)
    response = EvidenceGateService().evaluate(
        EvidenceGateRequest(
            data_readiness=DataReadinessReport(
                is_ready=False,
                readiness_score=0.5,
                blockers=[
                    ReadinessIssue(
                        severity="blocker",
                        code="missing_operation_id",
                        message="operation_id is required",
                    )
                ],
                required_inputs=[],
                recommendations=[],
            ),
            candidate_plans=[_candidate_plan(_schedule(start))],
            source_refs=["snapshot:S1"],
        )
    )

    assert response.allow_solve is False
    assert response.allow_recommendation is False
    assert response.recommendation_policy == "do_not_recommend"


@pytest.mark.asyncio
async def test_technical_kernel_api() -> None:
    start = datetime(2026, 7, 4, 8, tzinfo=timezone.utc)
    snapshot = _snapshot(start)
    incident = _incident(start + timedelta(minutes=30))
    test_app = FastAPI()
    test_app.include_router(planning_router)
    transport = ASGITransport(app=test_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        graph_response = await client.post(
            "/api/v1/planning/technical-kernel/decision-graph",
            json={
                "snapshot": snapshot.model_dump(mode="json"),
                "incident": incident.model_dump(mode="json"),
            },
        )
        recovery_response = await client.post(
            "/api/v1/planning/technical-kernel/recovery-operators",
            json={
                "incident": incident.model_dump(mode="json"),
                "decision_graph": graph_response.json(),
            },
        )

    assert graph_response.status_code == 200
    assert recovery_response.status_code == 200
    assert recovery_response.json()["recommendations"][0]["operator_type"] == "wait_and_shift"


def _snapshot(start: datetime) -> ScheduleSnapshot:
    return ScheduleSnapshot(
        captured_at=start,
        workshop_id="WS-TECH",
        work_orders=[
            WorkOrder(
                work_order_id="WO-1",
                product_name="Part A",
                due_date=start + timedelta(hours=8),
                operations=[
                    Operation(
                        operation_id="OP-10",
                        work_order_id="WO-1",
                        resource_id="CNC-01",
                        required_capabilities=["milling"],
                        start_time=start,
                        end_time=start + timedelta(hours=1),
                        successor_ids=["OP-20"],
                    ),
                    Operation(
                        operation_id="OP-20",
                        work_order_id="WO-1",
                        resource_id="ASM-01",
                        required_capabilities=["assembly"],
                        start_time=start + timedelta(hours=1),
                        end_time=start + timedelta(hours=2),
                        predecessor_ids=["OP-10"],
                    ),
                ],
            )
        ],
        raw_data={
            "resources": [
                Resource(
                    resource_id="CNC-01",
                    name="CNC-01",
                    capabilities=["milling"],
                ).model_dump(mode="json"),
                Resource(
                    resource_id="CNC-02",
                    name="CNC-02",
                    capabilities=["milling"],
                ).model_dump(mode="json"),
                Resource(
                    resource_id="ASM-01",
                    name="ASM-01",
                    capabilities=["assembly"],
                ).model_dump(mode="json"),
            ]
        },
    )


def _incident(occurred_at: datetime) -> Incident:
    return Incident(
        incident_type=IncidentType.EQUIPMENT_FAILURE,
        occurred_at=occurred_at,
        resource_id="CNC-01",
        report_source=ReportSource.MES,
        severity=IncidentSeverity.P2_HIGH,
        status=IncidentStatus.PENDING_ANALYSIS,
        raw_payload={"estimated_duration_minutes": 90},
    )


def _schedule(start: datetime) -> ScheduleDetail:
    return ScheduleDetail(
        resources=[
            Resource(resource_id="CNC-01", name="CNC-01", capabilities=["milling"])
        ],
        work_orders=[
            WorkOrder(
                work_order_id="WO-1",
                product_name="Part A",
                due_date=start + timedelta(hours=8),
                operations=[
                    Operation(
                        operation_id="OP-10",
                        work_order_id="WO-1",
                        resource_id="CNC-01",
                        required_capabilities=["milling"],
                        start_time=start,
                        end_time=start + timedelta(hours=1),
                    )
                ],
            )
        ],
    )


def _candidate_plan(schedule: ScheduleDetail) -> CandidatePlan:
    return CandidatePlan(
        strategy_type="local_repair",
        schedule_detail=schedule,
        gantt_version="v1",
        solver_chain=SolverChain(
            strategy_type="local_repair",
            rule_selection="validated_rules",
            neighborhood_selection="operation_insert",
            repair_policy="freeze_unaffected",
            solver_name="cp_sat_lns",
            key_parameters={},
            search_budget_seconds=5,
            constraint_validation_result="feasible",
            stages=["decision_graph", "recovery_operator", "quality_gate"],
        ),
        feasibility_status="feasible",
        solver_metadata=SolverMetadata(solve_time_seconds=0.8, iteration_count=8),
        constraint_report=ConstraintValidationReport(
            is_feasible=True,
            checked_constraints=[
                "resource_mutex",
                "operation_precedence",
                "resource_capability",
            ],
        ),
    )
