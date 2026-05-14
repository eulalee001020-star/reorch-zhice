"""Comprehensive JSON serialization round-trip consistency tests.

Covers all 8 core models: Incident, CandidatePlan, DecisionRecord,
CaseTemplate, PlanSelectionInput, PlanSelectionOutput, ScheduleDetail,
SolverChain.

Validates:
- Round-trip consistency: model_dump_json() → model_validate_json() → model_dump() == original
- Descriptive errors on invalid JSON deserialization
- Deeply nested structure survival through round-trip

Requirements: 21.3, 21.4, 21.5, 30.9
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.case import CaseTemplate
from app.models.decision import DecisionRecord
from app.models.evaluation import (
    ComparisonMatrix,
    ComparisonMatrixRow,
    KPIVector,
)
from app.models.incident import Incident
from app.models.enums import (
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ReportSource,
)
from app.models.recommendation import PlanSelectionInput, PlanSelectionOutput
from app.models.schedule import (
    GanttDiffPayload,
    Operation,
    Resource,
    ScheduleDetail,
    WorkOrder,
)
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    ConstraintViolation,
    SolverChain,
    SolverMetadata,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
_DUE = datetime(2025, 1, 20, 18, 0, 0, tzinfo=timezone.utc)
_PLAN_ID = uuid4()
_INCIDENT_ID = uuid4()
_SNAPSHOT_ID = uuid4()
_DECISION_ID = uuid4()
_TEMPLATE_ID = uuid4()


def _make_solver_chain() -> SolverChain:
    return SolverChain(
        strategy_type="local_repair",
        rule_selection="due_date_priority",
        neighborhood_selection="critical_path",
        repair_policy="balanced",
        solver_name="cp_sat_lns",
        key_parameters={"max_iter": 500, "perturbation_rate": 0.3},
        search_budget_seconds=45.0,
        constraint_validation_result="feasible",
        stages=["规则选择", "初解生成", "邻域选择", "LNS修复", "约束校验"],
    )


def _make_solver_metadata() -> SolverMetadata:
    return SolverMetadata(
        solve_time_seconds=12.5,
        iteration_count=320,
        objective_trajectory=[100.0, 85.0, 72.0, 68.5],
        degradation_occurred=False,
    )


def _make_constraint_report() -> ConstraintValidationReport:
    return ConstraintValidationReport(
        is_feasible=True,
        violations=[
            ConstraintViolation(
                constraint_type="resource_capacity",
                operation_id="OP-005",
                resource_id="CNC-002",
                detail="Minor capacity warning",
            )
        ],
        checked_constraints=[
            "equipment_capability",
            "process_order",
            "resource_mutex",
            "material_availability",
        ],
    )


def _make_operation(op_id: str = "OP-001") -> Operation:
    return Operation(
        operation_id=op_id,
        work_order_id="WO-001",
        resource_id="CNC-001",
        required_capabilities=["milling", "drilling"],
        start_time=_NOW,
        end_time=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        predecessor_ids=["OP-000"] if op_id != "OP-001" else [],
        successor_ids=["OP-002"],
        is_affected=True,
        is_adjusted=True,
    )


def _make_schedule_detail() -> ScheduleDetail:
    return ScheduleDetail(
        work_orders=[
            WorkOrder(
                work_order_id="WO-001",
                product_name="Widget-A",
                due_date=_DUE,
                operations=[_make_operation("OP-001"), _make_operation("OP-002")],
                priority=1,
            ),
            WorkOrder(
                work_order_id="WO-002",
                product_name="Widget-B",
                due_date=datetime(2025, 1, 22, 12, 0, 0, tzinfo=timezone.utc),
                operations=[_make_operation("OP-003")],
                priority=2,
            ),
        ],
        resources=[
            Resource(
                resource_id="CNC-001",
                name="CNC Machine 1",
                capabilities=["milling", "drilling"],
                is_bottleneck=True,
                has_redundancy=False,
                criticality="critical",
            ),
            Resource(
                resource_id="CNC-002",
                name="CNC Machine 2",
                capabilities=["milling"],
                is_bottleneck=False,
                has_redundancy=True,
                criticality="general",
            ),
        ],
    )


def _make_candidate_plan() -> CandidatePlan:
    return CandidatePlan(
        plan_id=_PLAN_ID,
        strategy_type="local_repair",
        schedule_detail=_make_schedule_detail(),
        gantt_version="v1.0",
        solver_chain=_make_solver_chain(),
        feasibility_status="feasible",
        solver_metadata=_make_solver_metadata(),
        constraint_report=_make_constraint_report(),
        created_at=_NOW,
    )


def _make_kpi_vector() -> KPIVector:
    return KPIVector(
        delayed_order_count=2,
        max_delay_minutes=45.0,
        spi=0.15,
        resource_utilization_delta=-0.03,
        changeover_count_delta=1,
        critical_order_otd_impact=0.95,
        normalized_score=0.82,
    )


def _make_comparison_matrix() -> ComparisonMatrix:
    return ComparisonMatrix(
        rows=[
            ComparisonMatrixRow(
                plan_id=str(_PLAN_ID),
                kpi_vector=_make_kpi_vector(),
                delta_vs_baseline={"spi": 0.15, "otd": -0.05},
                is_score_close=False,
            ),
        ],
        normalization_method="min_max",
        score_unit_descriptions={"spi": "Schedule Perturbation Index (0-1)"},
        baseline_snapshot_id=str(_SNAPSHOT_ID),
    )


def _make_gantt_diff() -> GanttDiffPayload:
    return GanttDiffPayload(
        baseline_snapshot_id=str(_SNAPSHOT_ID),
        candidate_plan_id=str(_PLAN_ID),
        adjusted_operations=[{"op_id": "OP-001", "change": "rescheduled"}],
        time_shifts=[{"op_id": "OP-001", "delta_min": 30}],
        resource_switches=[{"op_id": "OP-002", "from": "CNC-001", "to": "CNC-002"}],
        critical_path_changes=[{"added": "OP-003"}],
    )


def _make_incident() -> Incident:
    return Incident(
        incident_id=_INCIDENT_ID,
        incident_type=IncidentType.EQUIPMENT_FAILURE,
        occurred_at=_NOW,
        resource_id="CNC-001",
        report_source=ReportSource.MES,
        severity=IncidentSeverity.P2_HIGH,
        status=IncidentStatus.ANALYZING,
        description="Spindle overheating on CNC-001",
        deduplicated_from=[uuid4(), uuid4()],
        created_at=_NOW,
        raw_payload={"temp": 95.2, "sensor": "T-001"},
    )


def _make_decision_record() -> DecisionRecord:
    alt_plan_id = uuid4()
    return DecisionRecord(
        decision_record_id=_DECISION_ID,
        incident_id=_INCIDENT_ID,
        impact_report_summary="2 work orders affected, 1 Breach risk",
        strategy_type="local_repair",
        all_candidate_plan_ids=[_PLAN_ID, alt_plan_id],
        recommended_plan_id=_PLAN_ID,
        confirmed_plan_id=_PLAN_ID,
        derived_from_plan_id=_PLAN_ID,
        is_override=False,
        is_manual_adjusted=True,
        override_reason=None,
        confirmed_by="planner_zhang",
        confirmed_at=_NOW,
        plan_selection_input_version="v1.0",
        plan_selection_output_version="v1.0",
        solver_chain=_make_solver_chain(),
        rule_selector_version="rs-v2.1",
        neighborhood_selector_version="ns-v1.3",
        repair_policy_advisor_version="rpa-v1.0",
    )


def _make_case_template() -> CaseTemplate:
    return CaseTemplate(
        template_id=_TEMPLATE_ID,
        template_name="CNC故障-局部修复模板",
        applicable_incident_types=["equipment_failure"],
        recommended_strategy="local_repair",
        key_parameter_thresholds={
            "max_affected_ratio": 0.2,
            "min_buffer_minutes": 30,
        },
        status="published",
        reference_count=15,
        adoption_rate=0.87,
        created_by="admin_li",
        created_at=_NOW,
    )


def _make_plan_selection_input() -> PlanSelectionInput:
    return PlanSelectionInput(
        incident_id=_INCIDENT_ID,
        incident_type="equipment_failure",
        severity="P2-High",
        schedule_snapshot_id=_SNAPSHOT_ID,
        candidate_plans=[_make_candidate_plan()],
        goal_mode="balanced",
        preference_profile={"strategy_preferences": {"local_repair": 0.7}},
        historical_case_matches=[{"case_id": str(uuid4()), "similarity": 0.85}],
        manual_weights={"otd": 0.4, "spi": 0.3, "utilization": 0.3},
        execution_constraints={"max_changeover": 5},
    )


def _make_plan_selection_output() -> PlanSelectionOutput:
    alt_id = uuid4()
    return PlanSelectionOutput(
        recommended_plan_id=_PLAN_ID,
        recommended_rank=1,
        top_scored_plan_id=_PLAN_ID,
        recommendation_confidence=0.88,
        auto_preselected=True,
        ranked_plan_list=[
            {"plan_id": str(_PLAN_ID), "rank": 1, "score": 0.88},
            {"plan_id": str(alt_id), "rank": 2, "score": 0.82},
        ],
        reason_codes=["low_spi", "high_otd"],
        reason_summary="方案扰动最小且关键工单准时交付率最高",
        risk_flags=["changeover_increase"],
        comparison_matrix=_make_comparison_matrix(),
        gantt_diff_payload=_make_gantt_diff(),
        goal_mode_used="balanced",
        weights_used={"otd": 0.4, "spi": 0.3, "utilization": 0.3},
        matched_case_ids=[uuid4()],
        alternative_plan_ids=[alt_id],
        audit_metadata={"engine_version": "v1.0", "timestamp": str(_NOW)},
    )


# ---------------------------------------------------------------------------
# Round-trip consistency tests for all 8 core models
# ---------------------------------------------------------------------------

_ROUNDTRIP_CASES = [
    ("Incident", _make_incident),
    ("CandidatePlan", _make_candidate_plan),
    ("DecisionRecord", _make_decision_record),
    ("CaseTemplate", _make_case_template),
    ("PlanSelectionInput", _make_plan_selection_input),
    ("PlanSelectionOutput", _make_plan_selection_output),
    ("ScheduleDetail", _make_schedule_detail),
    ("SolverChain", _make_solver_chain),
]


@pytest.mark.parametrize("name,factory", _ROUNDTRIP_CASES, ids=[c[0] for c in _ROUNDTRIP_CASES])
def test_json_roundtrip_consistency(name: str, factory):
    """Validates: Requirements 21.3, 21.5, 30.9

    Serialize → deserialize → assert model_dump equality.
    """
    original = factory()
    json_str = original.model_dump_json()
    model_cls = type(original)
    restored = model_cls.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump(), (
        f"{name} round-trip mismatch"
    )


# ---------------------------------------------------------------------------
# Invalid JSON deserialization — descriptive errors
# ---------------------------------------------------------------------------

_INVALID_JSON_CASES = [
    ("Incident", Incident, '{"incident_type": "bad_type"}'),
    ("CandidatePlan", CandidatePlan, '{"plan_id": "not-a-uuid", "strategy_type": 1}'),
    ("DecisionRecord", DecisionRecord, '{"decision_record_id": 123}'),
    ("CaseTemplate", CaseTemplate, '{"template_id": "bad"}'),
    ("PlanSelectionInput", PlanSelectionInput, '{"incident_id": null}'),
    ("PlanSelectionOutput", PlanSelectionOutput, '{"recommended_plan_id": "x"}'),
    ("ScheduleDetail", ScheduleDetail, '{"work_orders": "not_a_list"}'),
    ("SolverChain", SolverChain, '{"strategy_type": 999}'),
]


@pytest.mark.parametrize(
    "name,model_cls,bad_json",
    _INVALID_JSON_CASES,
    ids=[c[0] for c in _INVALID_JSON_CASES],
)
def test_invalid_json_returns_descriptive_error(name: str, model_cls, bad_json: str):
    """Validates: Requirements 21.4

    Deserializing malformed JSON must raise ValidationError with
    at least one error entry containing location info.
    """
    with pytest.raises(ValidationError) as exc_info:
        model_cls.model_validate_json(bad_json)
    errors = exc_info.value.errors()
    assert len(errors) >= 1, f"{name}: expected at least 1 error entry"
    # Each error should have location info
    first = errors[0]
    assert "loc" in first, f"{name}: error missing 'loc' field"
    assert "msg" in first, f"{name}: error missing 'msg' field"


# ---------------------------------------------------------------------------
# Deeply nested structure round-trip tests
# ---------------------------------------------------------------------------


class TestDeeplyNestedRoundTrip:
    """Validates: Requirements 21.3, 21.5

    Deeply nested structures must survive JSON round-trip.
    """

    def test_candidate_plan_with_nested_solver_chain_and_schedule(self):
        """CandidatePlan → SolverChain + SolverMetadata + ConstraintReport + ScheduleDetail."""
        plan = _make_candidate_plan()
        json_str = plan.model_dump_json()
        restored = CandidatePlan.model_validate_json(json_str)

        assert restored.solver_chain.stages == plan.solver_chain.stages
        assert restored.solver_chain.key_parameters == plan.solver_chain.key_parameters
        assert restored.solver_metadata.objective_trajectory == plan.solver_metadata.objective_trajectory
        assert restored.constraint_report.violations[0].detail == plan.constraint_report.violations[0].detail
        assert len(restored.schedule_detail.work_orders) == 2
        assert len(restored.schedule_detail.resources) == 2
        assert restored.model_dump() == plan.model_dump()

    def test_schedule_detail_with_multiple_work_orders_and_operations(self):
        """ScheduleDetail with WorkOrders containing Operations and Resources."""
        sd = _make_schedule_detail()
        json_str = sd.model_dump_json()
        restored = ScheduleDetail.model_validate_json(json_str)

        assert len(restored.work_orders) == 2
        assert restored.work_orders[0].operations[0].required_capabilities == ["milling", "drilling"]
        assert restored.resources[0].is_bottleneck is True
        assert restored.model_dump() == sd.model_dump()

    def test_plan_selection_output_with_comparison_matrix_and_gantt_diff(self):
        """PlanSelectionOutput → ComparisonMatrix + GanttDiffPayload."""
        output = _make_plan_selection_output()
        json_str = output.model_dump_json()
        restored = PlanSelectionOutput.model_validate_json(json_str)

        # ComparisonMatrix nested checks
        assert len(restored.comparison_matrix.rows) == 1
        row = restored.comparison_matrix.rows[0]
        assert row.kpi_vector.normalized_score == output.comparison_matrix.rows[0].kpi_vector.normalized_score
        assert row.delta_vs_baseline == output.comparison_matrix.rows[0].delta_vs_baseline

        # GanttDiffPayload nested checks
        assert len(restored.gantt_diff_payload.adjusted_operations) == 1
        assert len(restored.gantt_diff_payload.time_shifts) == 1
        assert len(restored.gantt_diff_payload.resource_switches) == 1

        assert restored.model_dump() == output.model_dump()

    def test_decision_record_with_nested_solver_chain(self):
        """DecisionRecord → SolverChain nested round-trip."""
        dr = _make_decision_record()
        json_str = dr.model_dump_json()
        restored = DecisionRecord.model_validate_json(json_str)

        assert restored.solver_chain.solver_name == dr.solver_chain.solver_name
        assert restored.solver_chain.stages == dr.solver_chain.stages
        assert restored.all_candidate_plan_ids == dr.all_candidate_plan_ids
        assert restored.model_dump() == dr.model_dump()

    def test_plan_selection_input_with_nested_candidate_plans(self):
        """PlanSelectionInput → CandidatePlan[] → ScheduleDetail + SolverChain."""
        psi = _make_plan_selection_input()
        json_str = psi.model_dump_json()
        restored = PlanSelectionInput.model_validate_json(json_str)

        assert len(restored.candidate_plans) == 1
        cp = restored.candidate_plans[0]
        assert len(cp.schedule_detail.work_orders) == 2
        assert cp.solver_chain.solver_name == "cp_sat_lns"
        assert restored.model_dump() == psi.model_dump()
