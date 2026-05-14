"""Tests for Decision, Case, and Execution Pydantic models.

Covers creation, field defaults, JSON round-trip consistency,
nested structure integrity, and validation errors.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.case import CaseRecord, CaseTemplate, PreferenceProfile
from app.models.decision import ConfirmRequest, ConfirmResponse, DecisionRecord
from app.models.enums import ConfirmAction, WritebackStatus
from app.models.execution import ExecutionResult
from app.models.execution import WritebackStatus as ReExportedWritebackStatus
from app.models.solver import ConstraintValidationReport, SolverChain

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc)


def _make_solver_chain(**overrides) -> SolverChain:
    defaults = dict(
        strategy_type="local_repair",
        rule_selection="due_date_priority",
        neighborhood_selection="critical_path",
        repair_policy="balanced",
        solver_name="cp_sat",
        key_parameters={"max_time": 30},
        search_budget_seconds=30.0,
        constraint_validation_result="pass",
        stages=["规则选择", "初解生成", "邻域选择", "LNS修复", "约束校验"],
    )
    defaults.update(overrides)
    return SolverChain(**defaults)


def _make_constraint_report(**overrides) -> ConstraintValidationReport:
    defaults = dict(
        is_feasible=True,
        violations=[],
        checked_constraints=["equipment_capability", "process_order", "resource_mutex"],
    )
    defaults.update(overrides)
    return ConstraintValidationReport(**defaults)


def _make_execution_result(**overrides) -> ExecutionResult:
    defaults = dict(
        incident_id=uuid4(),
        decision_record_id=uuid4(),
        actual_completion_times={"WO-001": _NOW},
        planned_completion_times={"WO-001": _NOW},
        actual_otd=0.95,
        actual_resource_utilization=0.82,
        deviation_percentage=3.5,
    )
    defaults.update(overrides)
    return ExecutionResult(**defaults)


def _make_decision_record(**overrides) -> DecisionRecord:
    plan_id = uuid4()
    defaults = dict(
        decision_record_id=uuid4(),
        incident_id=uuid4(),
        impact_report_summary="2 work orders affected, 1 breach risk",
        strategy_type="local_repair",
        all_candidate_plan_ids=[plan_id, uuid4(), uuid4()],
        recommended_plan_id=plan_id,
        confirmed_plan_id=plan_id,
        derived_from_plan_id=plan_id,
        is_override=False,
        is_manual_adjusted=False,
        confirmed_by="planner_001",
        confirmed_at=_NOW,
        plan_selection_input_version="v1.0",
        plan_selection_output_version="v1.0",
        solver_chain=_make_solver_chain(),
        rule_selector_version="rs-v1.2",
        neighborhood_selector_version="ns-v1.0",
        repair_policy_advisor_version="rpa-v1.1",
    )
    defaults.update(overrides)
    return DecisionRecord(**defaults)


def _make_case_record(**overrides) -> CaseRecord:
    defaults = dict(
        case_id=uuid4(),
        incident_features={"type": "equipment_failure", "resource": "CNC-001"},
        impact_scope={"affected_wo_count": 2, "breach_count": 1},
        strategy_type="local_repair",
        confirmed_plan_summary="Rescheduled OP-001 and OP-002 to CNC-002.",
        is_override=False,
        rule_selection="due_date_priority",
        neighborhood_selection="critical_path",
        repair_policy="balanced",
        solver_chain=_make_solver_chain(),
        created_at=_NOW,
    )
    defaults.update(overrides)
    return CaseRecord(**defaults)


# ---------------------------------------------------------------------------
# ExecutionResult
# ---------------------------------------------------------------------------


class TestExecutionResult:
    def test_creation(self):
        er = _make_execution_result()
        assert er.actual_otd == 0.95
        assert er.deviation_percentage == 3.5

    def test_json_round_trip(self):
        er = _make_execution_result()
        restored = ExecutionResult.model_validate_json(er.model_dump_json())
        assert restored.model_dump() == er.model_dump()

    def test_empty_completion_times_default(self):
        er = ExecutionResult(
            incident_id=uuid4(),
            decision_record_id=uuid4(),
            actual_otd=1.0,
            actual_resource_utilization=0.9,
            deviation_percentage=0.0,
        )
        assert er.actual_completion_times == {}
        assert er.planned_completion_times == {}

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            ExecutionResult(
                incident_id=uuid4(),
                # decision_record_id missing
                actual_otd=0.9,
                actual_resource_utilization=0.8,
                deviation_percentage=5.0,
            )


# ---------------------------------------------------------------------------
# WritebackStatus re-export
# ---------------------------------------------------------------------------


class TestWritebackStatusReExport:
    def test_re_exported_from_execution(self):
        assert ReExportedWritebackStatus is WritebackStatus

    def test_values(self):
        assert ReExportedWritebackStatus.SUCCESS == "success"
        assert ReExportedWritebackStatus.PARTIAL_SUCCESS == "partial_success"
        assert ReExportedWritebackStatus.FAILED == "failed"


# ---------------------------------------------------------------------------
# ConfirmRequest
# ---------------------------------------------------------------------------


class TestConfirmRequest:
    def test_accept(self):
        req = ConfirmRequest(
            incident_id=uuid4(),
            action=ConfirmAction.ACCEPT,
            selected_plan_id=uuid4(),
            confirmed_by="planner_001",
        )
        assert req.action == ConfirmAction.ACCEPT.value
        assert req.adjustments is None
        assert req.override_reason is None

    def test_accept_with_adjustment(self):
        req = ConfirmRequest(
            incident_id=uuid4(),
            action=ConfirmAction.ACCEPT_WITH_ADJUSTMENT,
            selected_plan_id=uuid4(),
            adjustments=[{"op_id": "OP-001", "new_resource": "CNC-002"}],
            confirmed_by="planner_002",
        )
        assert req.adjustments is not None
        assert len(req.adjustments) == 1

    def test_reject_with_override_reason(self):
        req = ConfirmRequest(
            incident_id=uuid4(),
            action=ConfirmAction.REJECT_AND_RESELECT,
            selected_plan_id=uuid4(),
            override_reason="Prefer manual arrangement for this case.",
            confirmed_by="planner_003",
        )
        assert req.override_reason is not None

    def test_json_round_trip(self):
        req = ConfirmRequest(
            incident_id=uuid4(),
            action=ConfirmAction.ACCEPT_WITH_ADJUSTMENT,
            selected_plan_id=uuid4(),
            adjustments=[{"op_id": "OP-001", "shift": 15}],
            confirmed_by="planner_001",
        )
        restored = ConfirmRequest.model_validate_json(req.model_dump_json())
        assert restored.model_dump() == req.model_dump()

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            ConfirmRequest(
                incident_id=uuid4(),
                action=ConfirmAction.ACCEPT,
                # selected_plan_id missing
                confirmed_by="planner_001",
            )


# ---------------------------------------------------------------------------
# ConfirmResponse
# ---------------------------------------------------------------------------


class TestConfirmResponse:
    def test_creation(self):
        plan_id = uuid4()
        resp = ConfirmResponse(
            confirmed_plan_id=plan_id,
            derived_from_plan_id=plan_id,
            is_manual_adjusted=False,
            constraint_validation=_make_constraint_report(),
            decision_record_id=uuid4(),
        )
        assert resp.confirmed_plan_id == plan_id
        assert resp.is_manual_adjusted is False

    def test_adjusted_response(self):
        original_id = uuid4()
        new_id = uuid4()
        resp = ConfirmResponse(
            confirmed_plan_id=new_id,
            derived_from_plan_id=original_id,
            is_manual_adjusted=True,
            constraint_validation=_make_constraint_report(),
            decision_record_id=uuid4(),
        )
        assert resp.derived_from_plan_id == original_id
        assert resp.confirmed_plan_id == new_id
        assert resp.is_manual_adjusted is True

    def test_json_round_trip(self):
        resp = ConfirmResponse(
            confirmed_plan_id=uuid4(),
            derived_from_plan_id=uuid4(),
            is_manual_adjusted=True,
            constraint_validation=_make_constraint_report(),
            decision_record_id=uuid4(),
        )
        restored = ConfirmResponse.model_validate_json(resp.model_dump_json())
        assert restored.model_dump() == resp.model_dump()


# ---------------------------------------------------------------------------
# DecisionRecord
# ---------------------------------------------------------------------------


class TestDecisionRecord:
    def test_creation(self):
        dr = _make_decision_record()
        assert dr.is_override is False
        assert dr.is_manual_adjusted is False
        assert dr.override_reason is None
        assert len(dr.all_candidate_plan_ids) == 3

    def test_override_record(self):
        alt_plan = uuid4()
        dr = _make_decision_record(
            is_override=True,
            override_reason="Prefer less disruption.",
            confirmed_plan_id=alt_plan,
        )
        assert dr.is_override is True
        assert dr.override_reason == "Prefer less disruption."

    def test_strategy_module_versions(self):
        dr = _make_decision_record()
        assert dr.rule_selector_version == "rs-v1.2"
        assert dr.neighborhood_selector_version == "ns-v1.0"
        assert dr.repair_policy_advisor_version == "rpa-v1.1"

    def test_plan_selection_versions(self):
        dr = _make_decision_record(
            plan_selection_input_version="v2.0",
            plan_selection_output_version="v2.1",
        )
        assert dr.plan_selection_input_version == "v2.0"
        assert dr.plan_selection_output_version == "v2.1"

    def test_nested_solver_chain_preserved(self):
        dr = _make_decision_record()
        json_str = dr.model_dump_json()
        restored = DecisionRecord.model_validate_json(json_str)
        assert restored.solver_chain.stages == dr.solver_chain.stages
        assert restored.solver_chain.solver_name == "cp_sat"

    def test_json_round_trip(self):
        dr = _make_decision_record(
            is_override=True,
            is_manual_adjusted=True,
            override_reason="Testing override.",
        )
        restored = DecisionRecord.model_validate_json(dr.model_dump_json())
        assert restored.model_dump() == dr.model_dump()

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            DecisionRecord(
                decision_record_id=uuid4(),
                incident_id=uuid4(),
                # impact_report_summary missing
                strategy_type="local_repair",
            )


# ---------------------------------------------------------------------------
# CaseRecord
# ---------------------------------------------------------------------------


class TestCaseRecord:
    def test_creation(self):
        cr = _make_case_record()
        assert cr.strategy_type == "local_repair"
        assert cr.execution_result is None
        assert cr.embedding_vector is None
        assert cr.override_reason is None

    def test_with_execution_result(self):
        er = _make_execution_result()
        cr = _make_case_record(execution_result=er)
        assert cr.execution_result is not None
        assert cr.execution_result.actual_otd == 0.95

    def test_with_embedding_vector(self):
        vec = [0.1, 0.2, 0.3, 0.4, 0.5]
        cr = _make_case_record(embedding_vector=vec)
        assert cr.embedding_vector == vec
        assert len(cr.embedding_vector) == 5

    def test_override_case(self):
        cr = _make_case_record(
            is_override=True,
            override_reason="Planner preferred manual arrangement.",
        )
        assert cr.is_override is True
        assert cr.override_reason is not None

    def test_json_round_trip(self):
        cr = _make_case_record(
            execution_result=_make_execution_result(),
            embedding_vector=[0.1, 0.2, 0.3],
        )
        restored = CaseRecord.model_validate_json(cr.model_dump_json())
        assert restored.model_dump() == cr.model_dump()

    def test_nested_solver_chain_preserved(self):
        cr = _make_case_record()
        json_str = cr.model_dump_json()
        restored = CaseRecord.model_validate_json(json_str)
        assert restored.solver_chain.stages == cr.solver_chain.stages

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            CaseRecord(
                case_id=uuid4(),
                # incident_features missing
                impact_scope={},
                strategy_type="local_repair",
                confirmed_plan_summary="summary",
                is_override=False,
                rule_selection="edd",
                neighborhood_selection="cp",
                repair_policy="balanced",
                solver_chain=_make_solver_chain(),
                created_at=_NOW,
            )


# ---------------------------------------------------------------------------
# CaseTemplate
# ---------------------------------------------------------------------------


class TestCaseTemplate:
    def test_creation(self):
        ct = CaseTemplate(
            template_id=uuid4(),
            template_name="Equipment Failure - Local Repair",
            applicable_incident_types=["equipment_failure"],
            recommended_strategy="local_repair",
            key_parameter_thresholds={"max_affected_wo_pct": 0.2},
            status="published",
            created_by="manager_001",
            created_at=_NOW,
        )
        assert ct.reference_count == 0
        assert ct.adoption_rate == 0.0
        assert ct.status == "published"

    def test_draft_template(self):
        ct = CaseTemplate(
            template_id=uuid4(),
            template_name="Draft Template",
            recommended_strategy="global_reschedule",
            status="draft",
            created_by="manager_002",
            created_at=_NOW,
        )
        assert ct.status == "draft"
        assert ct.applicable_incident_types == []
        assert ct.key_parameter_thresholds == {}

    def test_with_usage_stats(self):
        ct = CaseTemplate(
            template_id=uuid4(),
            template_name="High Adoption Template",
            recommended_strategy="local_repair",
            status="published",
            reference_count=42,
            adoption_rate=0.85,
            created_by="manager_001",
            created_at=_NOW,
        )
        assert ct.reference_count == 42
        assert ct.adoption_rate == 0.85

    def test_json_round_trip(self):
        ct = CaseTemplate(
            template_id=uuid4(),
            template_name="Test Template",
            applicable_incident_types=["equipment_failure"],
            recommended_strategy="wait_and_repair",
            key_parameter_thresholds={"buffer_threshold": 60},
            status="published",
            reference_count=10,
            adoption_rate=0.7,
            created_by="manager_001",
            created_at=_NOW,
        )
        restored = CaseTemplate.model_validate_json(ct.model_dump_json())
        assert restored.model_dump() == ct.model_dump()

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            CaseTemplate(
                template_id=uuid4(),
                # template_name missing
                recommended_strategy="local_repair",
                status="draft",
                created_by="mgr",
                created_at=_NOW,
            )


# ---------------------------------------------------------------------------
# PreferenceProfile
# ---------------------------------------------------------------------------


class TestPreferenceProfile:
    def test_creation(self):
        pp = PreferenceProfile(
            planner_id="planner_001",
            strategy_preferences={"local_repair": 0.7, "global_reschedule": 0.3},
            adjustment_patterns=[{"pattern": "shift_time", "frequency": 5}],
            override_history=[{"case_id": str(uuid4()), "reason": "manual preference"}],
            updated_at=_NOW,
        )
        assert pp.planner_id == "planner_001"
        assert pp.strategy_preferences["local_repair"] == 0.7
        assert len(pp.adjustment_patterns) == 1
        assert len(pp.override_history) == 1

    def test_empty_defaults(self):
        pp = PreferenceProfile(
            planner_id="planner_002",
            updated_at=_NOW,
        )
        assert pp.strategy_preferences == {}
        assert pp.adjustment_patterns == []
        assert pp.override_history == []

    def test_json_round_trip(self):
        pp = PreferenceProfile(
            planner_id="planner_003",
            strategy_preferences={"wait_and_repair": 0.5, "local_repair": 0.5},
            adjustment_patterns=[],
            override_history=[{"reason": "test"}],
            updated_at=_NOW,
        )
        restored = PreferenceProfile.model_validate_json(pp.model_dump_json())
        assert restored.model_dump() == pp.model_dump()

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            PreferenceProfile(
                # planner_id missing
                updated_at=_NOW,
            )
