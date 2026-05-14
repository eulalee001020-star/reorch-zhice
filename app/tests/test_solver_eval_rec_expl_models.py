"""Tests for Solver, Evaluation, Recommendation, and Explanation models.

Covers creation, field defaults, JSON round-trip consistency,
nested structure integrity, and validation errors.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.evaluation import ComparisonMatrix, ComparisonMatrixRow, KPIVector
from app.models.explanation import RecommendationExplanation, SolverChainExplanation
from app.models.recommendation import PlanSelectionInput, PlanSelectionOutput
from app.models.schedule import GanttDiffPayload, ScheduleDetail
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    ConstraintViolation,
    SolverChain,
    SolverMetadata,
)

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


def _make_solver_metadata(**overrides) -> SolverMetadata:
    defaults = dict(
        solve_time_seconds=12.5,
        iteration_count=150,
        objective_trajectory=[100.0, 85.0, 72.0, 68.0],
    )
    defaults.update(overrides)
    return SolverMetadata(**defaults)


def _make_constraint_violation(**overrides) -> ConstraintViolation:
    defaults = dict(
        constraint_type="equipment_capability",
        operation_id="OP-001",
        resource_id="CNC-001",
        detail="Operation requires milling but device only supports turning.",
    )
    defaults.update(overrides)
    return ConstraintViolation(**defaults)


def _make_constraint_report(**overrides) -> ConstraintValidationReport:
    defaults = dict(
        is_feasible=True,
        violations=[],
        checked_constraints=["equipment_capability", "process_order", "resource_mutex"],
    )
    defaults.update(overrides)
    return ConstraintValidationReport(**defaults)


def _make_candidate_plan(**overrides) -> CandidatePlan:
    defaults = dict(
        strategy_type="local_repair",
        schedule_detail=ScheduleDetail(),
        gantt_version="v1.0",
        solver_chain=_make_solver_chain(),
        feasibility_status="feasible",
        solver_metadata=_make_solver_metadata(),
        constraint_report=_make_constraint_report(),
    )
    defaults.update(overrides)
    return CandidatePlan(**defaults)


def _make_kpi_vector(**overrides) -> KPIVector:
    defaults = dict(
        delayed_order_count=2,
        max_delay_minutes=45.0,
        spi=0.15,
        resource_utilization_delta=-0.03,
        changeover_count_delta=1,
        critical_order_otd_impact=0.95,
        normalized_score=0.82,
    )
    defaults.update(overrides)
    return KPIVector(**defaults)


def _make_comparison_matrix_row(**overrides) -> ComparisonMatrixRow:
    defaults = dict(
        plan_id="plan-001",
        kpi_vector=_make_kpi_vector(),
        delta_vs_baseline={"delayed_order_count": 2.0, "spi": 0.15},
        is_score_close=False,
    )
    defaults.update(overrides)
    return ComparisonMatrixRow(**defaults)


def _make_comparison_matrix(**overrides) -> ComparisonMatrix:
    defaults = dict(
        rows=[_make_comparison_matrix_row()],
        normalization_method="min_max",
        score_unit_descriptions={"spi": "Schedule Perturbation Index (0-1)"},
        baseline_snapshot_id="snap-001",
    )
    defaults.update(overrides)
    return ComparisonMatrix(**defaults)


# ---------------------------------------------------------------------------
# SolverChain
# ---------------------------------------------------------------------------


class TestSolverChain:
    def test_creation(self):
        sc = _make_solver_chain()
        assert sc.strategy_type == "local_repair"
        assert sc.solver_name == "cp_sat"
        assert len(sc.stages) == 5

    def test_empty_stages_default(self):
        sc = SolverChain(
            strategy_type="global_reschedule",
            rule_selection="spt",
            neighborhood_selection="bottleneck_device",
            repair_policy="aggressive",
            solver_name="cp_sat",
            key_parameters={},
            search_budget_seconds=60.0,
            constraint_validation_result="pass",
        )
        assert sc.stages == []

    def test_json_round_trip(self):
        sc = _make_solver_chain()
        restored = SolverChain.model_validate_json(sc.model_dump_json())
        assert restored.model_dump() == sc.model_dump()


# ---------------------------------------------------------------------------
# SolverMetadata
# ---------------------------------------------------------------------------


class TestSolverMetadata:
    def test_creation(self):
        sm = _make_solver_metadata()
        assert sm.solve_time_seconds == 12.5
        assert sm.degradation_occurred is False
        assert sm.degradation_reason is None

    def test_degradation(self):
        sm = _make_solver_metadata(
            degradation_occurred=True,
            degradation_reason="Primary solver timeout",
        )
        assert sm.degradation_occurred is True
        assert sm.degradation_reason == "Primary solver timeout"

    def test_json_round_trip(self):
        sm = _make_solver_metadata(degradation_occurred=True, degradation_reason="timeout")
        restored = SolverMetadata.model_validate_json(sm.model_dump_json())
        assert restored.model_dump() == sm.model_dump()


# ---------------------------------------------------------------------------
# ConstraintViolation & ConstraintValidationReport
# ---------------------------------------------------------------------------


class TestConstraintViolation:
    def test_creation(self):
        cv = _make_constraint_violation()
        assert cv.constraint_type == "equipment_capability"
        assert cv.resource_id == "CNC-001"

    def test_optional_resource_id(self):
        cv = ConstraintViolation(
            constraint_type="process_order",
            operation_id="OP-002",
            detail="Predecessor not completed.",
        )
        assert cv.resource_id is None

    def test_json_round_trip(self):
        cv = _make_constraint_violation()
        restored = ConstraintViolation.model_validate_json(cv.model_dump_json())
        assert restored.model_dump() == cv.model_dump()


class TestConstraintValidationReport:
    def test_feasible_report(self):
        report = _make_constraint_report()
        assert report.is_feasible is True
        assert report.violations == []

    def test_infeasible_report(self):
        report = _make_constraint_report(
            is_feasible=False,
            violations=[_make_constraint_violation()],
        )
        assert report.is_feasible is False
        assert len(report.violations) == 1

    def test_json_round_trip(self):
        report = _make_constraint_report(
            is_feasible=False,
            violations=[_make_constraint_violation()],
        )
        restored = ConstraintValidationReport.model_validate_json(report.model_dump_json())
        assert restored.model_dump() == report.model_dump()


# ---------------------------------------------------------------------------
# CandidatePlan
# ---------------------------------------------------------------------------


class TestCandidatePlan:
    def test_creation(self):
        plan = _make_candidate_plan()
        assert plan.strategy_type == "local_repair"
        assert plan.feasibility_status == "feasible"
        assert plan.plan_id is not None
        assert plan.created_at is not None

    def test_auto_generated_fields(self):
        p1 = _make_candidate_plan()
        p2 = _make_candidate_plan()
        assert p1.plan_id != p2.plan_id

    def test_json_round_trip(self):
        plan = _make_candidate_plan()
        restored = CandidatePlan.model_validate_json(plan.model_dump_json())
        assert restored.model_dump() == plan.model_dump()

    def test_nested_solver_chain_preserved(self):
        plan = _make_candidate_plan()
        json_str = plan.model_dump_json()
        restored = CandidatePlan.model_validate_json(json_str)
        assert restored.solver_chain.stages == plan.solver_chain.stages
        assert restored.solver_metadata.iteration_count == plan.solver_metadata.iteration_count

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            CandidatePlan(
                strategy_type="local_repair",
                # schedule_detail missing
                gantt_version="v1",
                solver_chain=_make_solver_chain(),
                feasibility_status="feasible",
                solver_metadata=_make_solver_metadata(),
                constraint_report=_make_constraint_report(),
            )


# ---------------------------------------------------------------------------
# KPIVector
# ---------------------------------------------------------------------------


class TestKPIVector:
    def test_creation(self):
        kpi = _make_kpi_vector()
        assert kpi.delayed_order_count == 2
        assert kpi.normalized_score == 0.82

    def test_json_round_trip(self):
        kpi = _make_kpi_vector()
        restored = KPIVector.model_validate_json(kpi.model_dump_json())
        assert restored.model_dump() == kpi.model_dump()

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            KPIVector(delayed_order_count=1)  # missing other required fields


# ---------------------------------------------------------------------------
# ComparisonMatrixRow & ComparisonMatrix
# ---------------------------------------------------------------------------


class TestComparisonMatrixRow:
    def test_creation(self):
        row = _make_comparison_matrix_row()
        assert row.plan_id == "plan-001"
        assert row.is_score_close is False

    def test_score_close_flag(self):
        row = _make_comparison_matrix_row(is_score_close=True)
        assert row.is_score_close is True

    def test_json_round_trip(self):
        row = _make_comparison_matrix_row()
        restored = ComparisonMatrixRow.model_validate_json(row.model_dump_json())
        assert restored.model_dump() == row.model_dump()


class TestComparisonMatrix:
    def test_creation(self):
        matrix = _make_comparison_matrix()
        assert len(matrix.rows) == 1
        assert matrix.normalization_method == "min_max"
        assert matrix.baseline_snapshot_id == "snap-001"

    def test_score_unit_descriptions(self):
        matrix = _make_comparison_matrix()
        assert "spi" in matrix.score_unit_descriptions

    def test_json_round_trip(self):
        matrix = _make_comparison_matrix()
        restored = ComparisonMatrix.model_validate_json(matrix.model_dump_json())
        assert restored.model_dump() == matrix.model_dump()


# ---------------------------------------------------------------------------
# PlanSelectionInput
# ---------------------------------------------------------------------------


class TestPlanSelectionInput:
    def test_creation(self):
        inp = PlanSelectionInput(
            incident_id=uuid4(),
            incident_type="equipment_failure",
            severity="P2-High",
            schedule_snapshot_id=uuid4(),
            candidate_plans=[_make_candidate_plan()],
            goal_mode="balanced",
            preference_profile={"strategy_preferences": {"local_repair": 0.8}},
            historical_case_matches=[{"case_id": str(uuid4()), "similarity": 0.85}],
        )
        assert len(inp.candidate_plans) == 1
        assert inp.manual_weights is None
        assert inp.execution_constraints is None

    def test_with_manual_weights(self):
        inp = PlanSelectionInput(
            incident_id=uuid4(),
            incident_type="equipment_failure",
            severity="P1-Critical",
            schedule_snapshot_id=uuid4(),
            goal_mode="delivery_priority",
            manual_weights={"otd": 0.5, "spi": 0.3, "utilization": 0.2},
        )
        assert inp.manual_weights is not None
        assert inp.manual_weights["otd"] == 0.5

    def test_json_round_trip(self):
        inp = PlanSelectionInput(
            incident_id=uuid4(),
            incident_type="equipment_failure",
            severity="P2-High",
            schedule_snapshot_id=uuid4(),
            candidate_plans=[_make_candidate_plan()],
            goal_mode="balanced",
            manual_weights={"otd": 0.6, "spi": 0.4},
            execution_constraints={"max_changeover": 5},
        )
        restored = PlanSelectionInput.model_validate_json(inp.model_dump_json())
        assert restored.model_dump() == inp.model_dump()

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            PlanSelectionInput(
                incident_id=uuid4(),
                # incident_type missing
                severity="P2-High",
                schedule_snapshot_id=uuid4(),
                goal_mode="balanced",
            )


# ---------------------------------------------------------------------------
# PlanSelectionOutput
# ---------------------------------------------------------------------------


class TestPlanSelectionOutput:
    def _make_output(self, **overrides):
        plan_id = uuid4()
        defaults = dict(
            recommended_plan_id=plan_id,
            recommended_rank=1,
            top_scored_plan_id=plan_id,
            recommendation_confidence=0.88,
            auto_preselected=True,
            ranked_plan_list=[{"plan_id": str(plan_id), "rank": 1}],
            reason_codes=["high_otd", "low_spi"],
            reason_summary="Best balance of OTD and stability.",
            risk_flags=["changeover_increase"],
            comparison_matrix=_make_comparison_matrix(),
            gantt_diff_payload=GanttDiffPayload(
                baseline_snapshot_id="snap-001",
                candidate_plan_id=str(plan_id),
            ),
            goal_mode_used="balanced",
            weights_used={"otd": 0.4, "spi": 0.3, "utilization": 0.3},
            matched_case_ids=[uuid4()],
            alternative_plan_ids=[uuid4(), uuid4()],
            audit_metadata={"version": "1.0", "timestamp": str(_NOW)},
        )
        defaults.update(overrides)
        return PlanSelectionOutput(**defaults)

    def test_creation(self):
        out = self._make_output()
        assert out.recommendation_confidence == 0.88
        assert out.auto_preselected is True
        assert len(out.alternative_plan_ids) == 2

    def test_json_round_trip(self):
        out = self._make_output()
        restored = PlanSelectionOutput.model_validate_json(out.model_dump_json())
        assert restored.model_dump() == out.model_dump()

    def test_low_confidence_no_preselect(self):
        out = self._make_output(
            recommendation_confidence=0.35,
            auto_preselected=False,
        )
        assert out.recommendation_confidence == 0.35
        assert out.auto_preselected is False

    def test_alternative_plan_ids_present(self):
        alt_ids = [uuid4(), uuid4(), uuid4()]
        out = self._make_output(alternative_plan_ids=alt_ids)
        assert len(out.alternative_plan_ids) == 3

    def test_audit_metadata_preserved(self):
        metadata = {"model_version": "2.1", "run_id": "abc-123"}
        out = self._make_output(audit_metadata=metadata)
        assert out.audit_metadata["model_version"] == "2.1"


# ---------------------------------------------------------------------------
# RecommendationExplanation
# ---------------------------------------------------------------------------


class TestRecommendationExplanation:
    def test_creation(self):
        expl = RecommendationExplanation(
            core_reasons=["Lowest delay", "Best OTD"],
            key_advantages=["No changeover increase"],
            main_risks=["Slight SPI increase"],
            comparison_with_alternatives=[
                {"plan_id": "plan-002", "diff": "Higher delay by 15 min"}
            ],
            summary="推荐方案在交期和稳定性之间取得最佳平衡。",
            referenced_case_ids=["case-001"],
        )
        assert len(expl.core_reasons) == 2
        assert len(expl.referenced_case_ids) == 1

    def test_core_reasons_limit(self):
        """core_reasons should support up to 3 items per design."""
        expl = RecommendationExplanation(
            core_reasons=["R1", "R2", "R3"],
            summary="Short summary.",
        )
        assert len(expl.core_reasons) == 3

    def test_json_round_trip(self):
        expl = RecommendationExplanation(
            core_reasons=["Reason A"],
            key_advantages=["Advantage 1"],
            main_risks=["Risk 1"],
            comparison_with_alternatives=[],
            summary="Summary text.",
            referenced_case_ids=["case-x"],
        )
        restored = RecommendationExplanation.model_validate_json(expl.model_dump_json())
        assert restored.model_dump() == expl.model_dump()


# ---------------------------------------------------------------------------
# SolverChainExplanation
# ---------------------------------------------------------------------------


class TestSolverChainExplanation:
    def test_creation(self):
        expl = SolverChainExplanation(
            algorithm_category="LNS + CP-SAT",
            applicable_scenario="局部修复：受影响工序≤20%",
            chain_reason="影响范围有限，局部搜索效率更高。",
            optimization_objectives=["minimize_delay", "minimize_spi"],
            computation_time_seconds=12.5,
            stages=["规则选择", "初解生成", "LNS修复", "约束校验"],
        )
        assert expl.algorithm_category == "LNS + CP-SAT"
        assert expl.frozen_constraints is None

    def test_with_frozen_constraints(self):
        expl = SolverChainExplanation(
            algorithm_category="Heuristic",
            applicable_scenario="等待修复",
            chain_reason="设备即将恢复，仅调整时间。",
            optimization_objectives=["minimize_delay"],
            computation_time_seconds=2.0,
            stages=["时间偏移", "约束校验"],
            frozen_constraints=["OP-100", "OP-101"],
        )
        assert expl.frozen_constraints == ["OP-100", "OP-101"]

    def test_json_round_trip(self):
        expl = SolverChainExplanation(
            algorithm_category="CP-SAT Global",
            applicable_scenario="全局重排",
            chain_reason="影响范围大，需全局优化。",
            optimization_objectives=["minimize_delay", "maximize_otd"],
            computation_time_seconds=55.0,
            stages=["全局初解", "CP-SAT优化", "约束校验"],
            frozen_constraints=["OP-200"],
        )
        restored = SolverChainExplanation.model_validate_json(expl.model_dump_json())
        assert restored.model_dump() == expl.model_dump()
