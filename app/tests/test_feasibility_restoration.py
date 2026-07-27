"""Failure-injection tests for approval-gated feasibility restoration."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.config import settings
from app.models.enums import DeliveryRiskLevel, StrategyType
from app.models.feasibility_restoration import (
    FeasibilityRestorationRequest,
    RecoveryApprovalAttestation,
)
from app.models.impact import AffectedOperation, AffectedWorkOrder, ImpactReport
from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder
from app.services.cp_sat_scheduler import CpSatScheduleResult
from app.services.constraint_assumption_registry import ConstraintAssumptionRegistry
from app.services.feasibility_restoration import (
    FeasibilityRestorationEngine,
    conservative_default_recovery_policy,
)
from app.services.infeasibility_classifier import InfeasibilityClassifier
from app.services.recovery_approval_policy import RecoveryApprovalPolicy


NOW = datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc)


def test_classifier_does_not_treat_timeout_as_proven_infeasible() -> None:
    timeout = InfeasibilityClassifier.classify(
        status_name="NO_VALIDATED_INCUMBENT",
        is_feasible=False,
        solver_log={"cp_sat_status": "UNKNOWN"},
    )
    infeasible = InfeasibilityClassifier.classify(
        status_name="NO_VALIDATED_INCUMBENT",
        is_feasible=False,
        solver_log={"cp_sat_status": "INFEASIBLE"},
    )

    assert timeout.failure_class == "search_exhausted"
    assert timeout.may_enter_relaxation_search is False
    assert infeasible.failure_class == "proven_infeasible"
    assert infeasible.may_enter_relaxation_search is True


def test_constraint_registry_forbids_direct_quality_relaxation() -> None:
    registry = ConstraintAssumptionRegistry()

    qms = registry.get("qms_release")
    planning_freeze = registry.get("planning_freeze")

    assert qms is not None
    assert qms.must_remain_satisfied is True
    assert qms.direct_relaxation == "forbidden"
    assert "safe_hold" in qms.recovery_action_types
    assert planning_freeze is not None
    assert planning_freeze.direct_relaxation == (
        "versioned_policy_and_approval_required"
    )


def test_relaxable_deadline_produces_pending_minimum_correction_set() -> None:
    request = _request("deadline")

    response = FeasibilityRestorationEngine().evaluate(request)

    assert response.status == "pending_approval"
    assert response.classification.failure_class == "proven_infeasible"
    assert response.conflict_report.core_status == "minimum_correction_set"
    first = response.recovery_packs[0]
    assert [action.action_type for action in first.actions] == [
        "relax_operation_deadline"
    ]
    assert first.status == "pending_approval"
    assert first.preview_schedule is not None
    assert first.executable_schedule is None
    assert first.feasibility_certificate is None
    assert response.writeback_allowed is False


def test_approved_deadline_recovery_is_revalidated_and_certified() -> None:
    policy = conservative_default_recovery_policy()
    request = _request("deadline").model_copy(update={"policy": policy})
    preview = FeasibilityRestorationEngine().evaluate(request)
    action = preview.recovery_packs[0].actions[0]
    approvals = _approvals(action, policy)

    response = FeasibilityRestorationEngine().evaluate(
        request.model_copy(update={"approvals": approvals})
    )

    pack = response.recovery_packs[0]
    assert response.status == "recovery_available"
    assert response.recommended_pack_id == pack.pack_id
    assert pack.status == "validated_feasible"
    assert pack.executable_schedule is not None
    assert pack.feasibility_certificate is not None
    assert pack.feasibility_certificate.hard_violation_count == 0
    assert pack.feasibility_certificate.writeback_authorized is False
    assert set(pack.feasibility_certificate.approval_source_refs) == {
        "approval:Management",
        "approval:Planner",
    }


def test_two_independent_conflicts_require_minimum_two_action_pack() -> None:
    response = FeasibilityRestorationEngine().evaluate(_two_deadline_request())

    first = response.recovery_packs[0]
    assert len(first.actions) == 2
    assert {action.action_type for action in first.actions} == {
        "relax_operation_deadline"
    }
    assert first.total_penalty_cost == 2000
    assert first.optimality_proven is True
    assert response.conflict_report.minimum_correction_action_ids == [
        action.action_id for action in first.actions
    ]


def test_material_shortage_uses_substitute_only_as_pending_what_if() -> None:
    response = FeasibilityRestorationEngine().evaluate(_request("material"))

    assert response.status == "pending_approval"
    assert response.conflict_report.conflicts[0].constraint_family == (
        "material_availability"
    )
    first = response.recovery_packs[0]
    assert [action.action_type for action in first.actions] == [
        "activate_substitute_material"
    ]
    assert first.pending_approval_roles == ["Engineering", "Quality"]
    assert first.executable_schedule is None


def test_planned_freeze_requires_explicit_release_approval() -> None:
    response = FeasibilityRestorationEngine().evaluate(_request("freeze"))

    assert response.classification.failure_class == "proven_infeasible"
    assert response.status == "pending_approval"
    first = response.recovery_packs[0]
    assert [action.action_type for action in first.actions] == [
        "release_planning_freeze"
    ]
    assert first.actions[0].approval_status == "pending"


def test_qms_block_is_never_sent_to_relaxation_search() -> None:
    response = FeasibilityRestorationEngine().evaluate(_request("qms"))

    assert response.status == "blocked"
    assert response.classification.failure_class == "data_or_governance_blocked"
    assert response.classification.may_enter_relaxation_search is False
    assert response.recovery_packs == []
    assert response.safe_hold.executable_production_schedule is False
    assert response.safe_hold.writeback_authorized is False


def test_unknown_solver_status_preserves_baseline_without_relaxation() -> None:
    engine = FeasibilityRestorationEngine(
        scheduler_factory=lambda: _AlwaysUnknownScheduler()
    )

    response = engine.evaluate(_request("deadline"))

    assert response.status == "search_exhausted"
    assert response.classification.failure_class == "search_exhausted"
    assert response.recovery_packs == []
    assert response.search_trials == 1


def test_production_certificate_requires_signed_multi_role_approvals(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings.app, "env", "production")
    monkeypatch.setattr(
        settings.auth,
        "recovery_approval_secret",
        "test-recovery-approval-secret-32-characters",
    )
    policy = conservative_default_recovery_policy().model_copy(
        update={
            "policy_id": "customer-recovery-policy",
            "customer_owned": True,
        }
    )
    request = _request("deadline").model_copy(update={"policy": policy})
    preview = FeasibilityRestorationEngine().evaluate(request)
    action = preview.recovery_packs[0].actions[0]
    unsigned = _approvals(action, policy)

    unsigned_response = FeasibilityRestorationEngine().evaluate(
        request.model_copy(update={"approvals": unsigned})
    )
    signed = [
        approval.model_copy(
            update={"signature": RecoveryApprovalPolicy.sign(approval)}
        )
        for approval in unsigned
    ]
    signed_response = FeasibilityRestorationEngine().evaluate(
        request.model_copy(update={"approvals": signed})
    )

    assert unsigned_response.status == "pending_approval"
    assert signed_response.status == "recovery_available"
    assert signed_response.recovery_packs[0].feasibility_certificate is not None


@pytest.mark.asyncio
async def test_feasibility_restoration_runtime_api_returns_structured_gate() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/runtime/feasibility-restoration/evaluate",
            json=_request("deadline").model_dump(mode="json"),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending_approval"
    assert body["classification"]["failure_class"] == "proven_infeasible"
    assert body["writeback_allowed"] is False
    assert body["recovery_packs"][0]["status"] == "pending_approval"


@pytest.mark.asyncio
async def test_production_api_requires_customer_owned_policy(monkeypatch) -> None:
    monkeypatch.setattr(settings.app, "env", "production")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/runtime/feasibility-restoration/evaluate",
            json=_request("deadline").model_dump(mode="json"),
        )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "active_customer_owned_recovery_policy_required"
    )


def test_large_snapshot_routes_through_bounded_decomposition(monkeypatch) -> None:
    monkeypatch.setattr(settings.solver, "max_model_operations", 20)

    response = FeasibilityRestorationEngine().evaluate(_large_request())

    assert response.status == "already_feasible"
    pack = response.recovery_packs[0]
    assert pack.solver_status == "FEASIBLE"
    assert pack.feasibility_certificate is not None
    assert pack.feasibility_certificate.hard_violation_count == 0


def test_large_infeasible_snapshot_restores_inside_decomposition(monkeypatch) -> None:
    monkeypatch.setattr(settings.solver, "max_model_operations", 20)

    response = FeasibilityRestorationEngine().evaluate(
        _large_request(material_conflict=True)
    )

    assert response.classification.failure_class == "proven_infeasible"
    assert response.status == "pending_approval"
    assert response.recovery_packs
    assert response.recovery_packs[0].actions[0].action_type == (
        "activate_substitute_material"
    )


class _AlwaysUnknownScheduler:
    def solve(self, **_: object) -> CpSatScheduleResult:
        return CpSatScheduleResult(
            schedule_detail=None,
            status_name="UNKNOWN",
            is_feasible=False,
        )


def _request(kind: str) -> FeasibilityRestorationRequest:
    raw_data: dict[str, object] = {
        "resources": [
            {"resource_id": "M1", "name": "M1", "capabilities": ["cnc"]}
        ],
        "work_orders": [
            {
                "work_order_id": "WO1",
                "source_ref": "ERP:WO1",
                "operations": [
                    {
                        "operation_id": "OP1",
                        "status": "planned",
                        "source_ref": "MES:OP1",
                        "eligible_resources": ["M1"],
                    }
                ],
            }
        ],
    }
    delay = 0.0
    frozen: list[str] = []
    if kind == "deadline":
        raw_data.update(
            {
                "operation_release_constraints": [
                    {
                        "operation_id": "OP1",
                        "release_at": (NOW + timedelta(minutes=30)).isoformat(),
                        "source_ref": "MES:release:OP1",
                    }
                ],
                "operation_deadline_constraints": [
                    {
                        "operation_id": "OP1",
                        "deadline_at": (NOW + timedelta(minutes=45)).isoformat(),
                        "relaxable": True,
                        "source_ref": "APS:deadline:OP1",
                    }
                ],
            }
        )
    elif kind == "material":
        raw_data.update(
            {
                "material_availability": [
                    {
                        "material_id": "MAT1",
                        "operation_ids": ["OP1"],
                        "available_quantity": 0,
                        "required_quantity": 1,
                        "source_ref": "ERP:material:MAT1",
                    }
                ],
                "substitute_material_approvals": [
                    {
                        "primary_material_id": "MAT1",
                        "substitute_material_id": "MAT2",
                        "operation_ids": ["OP1"],
                        "approval_status": "pending",
                        "available_quantity": 1,
                        "required_quantity": 1,
                        "available_at": NOW.isoformat(),
                        "source_ref": "QMS:substitute:MAT2",
                    }
                ],
            }
        )
    elif kind == "freeze":
        raw_data["frozen_operation_ids"] = ["OP1"]
        frozen = ["OP1"]
        delay = 30.0
    elif kind == "qms":
        raw_data["qms_release_gates"] = [
            {
                "gate_id": "G1",
                "operation_ids": ["OP1"],
                "status": "pending",
                "source_ref": "QMS:gate:G1",
            }
        ]
    else:
        raise ValueError(kind)

    operation = Operation(
        operation_id="OP1",
        work_order_id="WO1",
        resource_id="M1",
        required_capabilities=["cnc"],
        start_time=NOW,
        end_time=NOW + timedelta(minutes=60),
    )
    work_order = WorkOrder(
        work_order_id="WO1",
        product_name="A",
        due_date=NOW + timedelta(hours=4),
        priority=1,
        operations=[operation],
    )
    snapshot = ScheduleSnapshot(
        captured_at=NOW,
        workshop_id="WS-RESTORE",
        source_system="MES",
        work_orders=[work_order],
        raw_data=raw_data,
    )
    affected = AffectedOperation(
        operation_id="OP1",
        work_order_id="WO1",
        resource_id="M1",
        is_direct=True,
        estimated_delay_minutes=delay,
    )
    impact = ImpactReport(
        incident_id=uuid4(),
        schedule_snapshot_id=snapshot.snapshot_id,
        analysis_reference_time=NOW,
        affected_operations=[affected],
        affected_work_orders=[
            AffectedWorkOrder(
                work_order_id="WO1",
                product_name="A",
                due_date=work_order.due_date,
                delivery_risk_level=DeliveryRiskLevel.BREACH,
                remaining_buffer_minutes=0,
                affected_operations=[affected],
            )
        ],
        affected_resource_ids=["M1"],
    )
    return FeasibilityRestorationRequest(
        tenant_id="TENANT-RESTORE",
        snapshot=snapshot,
        impact_report=impact,
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        frozen_operation_ids=frozen,
        timeout_seconds=5,
    )


def _approvals(action, policy) -> list[RecoveryApprovalAttestation]:
    return [
        RecoveryApprovalAttestation(
            action_id=action.action_id,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            approver_id=f"{role}-1",
            approver_role=role,
            source_ref=f"approval:{role}",
        )
        for role in action.required_approval_roles
    ]


def _large_request(*, material_conflict: bool = False) -> FeasibilityRestorationRequest:
    resources = [
        {"resource_id": f"M{index}", "name": f"M{index}", "capabilities": ["cnc"]}
        for index in range(5)
    ]
    work_orders: list[WorkOrder] = []
    raw_work_orders: list[dict[str, object]] = []
    affected: AffectedOperation | None = None
    for index in range(25):
        resource_id = f"M{index % 5}"
        slot = index // 5
        start = NOW + timedelta(minutes=slot * 30)
        operation = Operation(
            operation_id=f"OP{index}",
            work_order_id=f"WO{index}",
            resource_id=resource_id,
            required_capabilities=["cnc"],
            start_time=start,
            end_time=start + timedelta(minutes=20),
        )
        work_orders.append(
            WorkOrder(
                work_order_id=f"WO{index}",
                product_name="A",
                due_date=NOW + timedelta(hours=8),
                operations=[operation],
            )
        )
        raw_work_orders.append(
            {
                "work_order_id": f"WO{index}",
                "source_ref": f"ERP:WO{index}",
                "operations": [
                    {
                        "operation_id": f"OP{index}",
                        "status": "planned",
                        "source_ref": f"MES:OP{index}",
                        "eligible_resources": [resource_id],
                    }
                ],
            }
        )
        if index == 0:
            affected = AffectedOperation(
                operation_id="OP0",
                work_order_id="WO0",
                resource_id="M0",
                is_direct=True,
                estimated_delay_minutes=5,
            )
    assert affected is not None
    raw_data: dict[str, object] = {
        "resources": resources,
        "work_orders": raw_work_orders,
    }
    if material_conflict:
        raw_data.update(
            {
                "material_availability": [
                    {
                        "material_id": "MAT-LARGE",
                        "operation_ids": ["OP0"],
                        "available_quantity": 0,
                        "required_quantity": 1,
                        "source_ref": "ERP:MAT-LARGE",
                    }
                ],
                "substitute_material_approvals": [
                    {
                        "primary_material_id": "MAT-LARGE",
                        "substitute_material_id": "MAT-LARGE-SUB",
                        "operation_ids": ["OP0"],
                        "approval_status": "pending",
                        "available_quantity": 1,
                        "required_quantity": 1,
                        "available_at": NOW.isoformat(),
                        "source_ref": "QMS:MAT-LARGE-SUB",
                    }
                ],
            }
        )
    snapshot = ScheduleSnapshot(
        captured_at=NOW,
        workshop_id="WS-LARGE-RESTORE",
        work_orders=work_orders,
        raw_data=raw_data,
    )
    impact = ImpactReport(
        incident_id=uuid4(),
        schedule_snapshot_id=snapshot.snapshot_id,
        analysis_reference_time=NOW,
        affected_operations=[affected],
        affected_resource_ids=["M0"],
    )
    return FeasibilityRestorationRequest(
        tenant_id="TENANT-LARGE",
        snapshot=snapshot,
        impact_report=impact,
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        timeout_seconds=10,
    )


def _two_deadline_request() -> FeasibilityRestorationRequest:
    request = _request("deadline")
    second_operation = Operation(
        operation_id="OP2",
        work_order_id="WO2",
        resource_id="M2",
        required_capabilities=["cnc"],
        start_time=NOW,
        end_time=NOW + timedelta(minutes=60),
    )
    second_work_order = WorkOrder(
        work_order_id="WO2",
        product_name="B",
        due_date=NOW + timedelta(hours=4),
        priority=1,
        operations=[second_operation],
    )
    snapshot = request.snapshot.model_copy(deep=True)
    raw = copy.deepcopy(snapshot.raw_data or {})
    raw["resources"].append(
        {"resource_id": "M2", "name": "M2", "capabilities": ["cnc"]}
    )
    raw["work_orders"].append(
        {
            "work_order_id": "WO2",
            "source_ref": "ERP:WO2",
            "operations": [
                {
                    "operation_id": "OP2",
                    "status": "planned",
                    "source_ref": "MES:OP2",
                    "eligible_resources": ["M2"],
                }
            ],
        }
    )
    raw["operation_release_constraints"].append(
        {
            "operation_id": "OP2",
            "release_at": (NOW + timedelta(minutes=30)).isoformat(),
            "source_ref": "MES:release:OP2",
        }
    )
    raw["operation_deadline_constraints"].append(
        {
            "operation_id": "OP2",
            "deadline_at": (NOW + timedelta(minutes=45)).isoformat(),
            "relaxable": True,
            "source_ref": "APS:deadline:OP2",
        }
    )
    snapshot = snapshot.model_copy(
        update={
            "work_orders": [*snapshot.work_orders, second_work_order],
            "raw_data": raw,
        },
        deep=True,
    )
    impact = request.impact_report.model_copy(
        update={"schedule_snapshot_id": snapshot.snapshot_id}, deep=True
    )
    return request.model_copy(
        update={"snapshot": snapshot, "impact_report": impact}, deep=True
    )
