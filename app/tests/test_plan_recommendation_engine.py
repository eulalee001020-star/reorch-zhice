"""Tests for PlanRecommendationEngine.

Validates: Requirements 29.1–29.12
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.models.enums import (
    GoalMode,
    IncidentSeverity,
    IncidentType,
    ReportSource,
)
from app.models.incident import Incident
from app.models.recommendation import PlanSelectionInput, PlanSelectionOutput
from app.models.schedule import ScheduleDetail
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    SolverChain,
    SolverMetadata,
)
from app.services.plan_recommendation_engine import PlanRecommendationEngine


# ── Helpers ─────────────────────────────────────────────────────────


def _chain(**kw) -> SolverChain:
    defaults = dict(
        strategy_type="local_repair",
        rule_selection="due_date_priority",
        neighborhood_selection="critical_path",
        repair_policy="balanced",
        solver_name="cp_sat",
        key_parameters={},
        search_budget_seconds=30.0,
        constraint_validation_result="pass",
    )
    defaults.update(kw)
    return SolverChain(**defaults)


def _meta(**kw) -> SolverMetadata:
    defaults = dict(solve_time_seconds=5.0, iteration_count=100)
    defaults.update(kw)
    return SolverMetadata(**defaults)


def _report(feasible: bool = True) -> ConstraintValidationReport:
    return ConstraintValidationReport(
        is_feasible=feasible,
        checked_constraints=["equipment_capability"],
    )


def _plan(
    strategy: str = "local_repair",
    feasibility: str = "feasible",
    plan_id: UUID | None = None,
    degradation: bool = False,
) -> CandidatePlan:
    return CandidatePlan(
        plan_id=plan_id or uuid4(),
        strategy_type=strategy,
        schedule_detail=ScheduleDetail(),
        gantt_version="v1",
        solver_chain=_chain(strategy_type=strategy),
        feasibility_status=feasibility,
        solver_metadata=_meta(
            degradation_occurred=degradation,
            degradation_reason="timeout" if degradation else None,
        ),
        constraint_report=_report(feasibility != "infeasible"),
    )


def _input(
    candidates: list[CandidatePlan] | None = None,
    severity: str = "P2-High",
    goal_mode: str = "balanced",
    preference: dict | None = None,
    case_matches: list[dict] | None = None,
    manual_weights: dict | None = None,
    execution_constraints: dict | None = None,
) -> PlanSelectionInput:
    return PlanSelectionInput(
        incident_id=uuid4(),
        incident_type="equipment_failure",
        severity=severity,
        schedule_snapshot_id=uuid4(),
        candidate_plans=candidates or [_plan()],
        goal_mode=goal_mode,
        preference_profile=preference or {},
        historical_case_matches=case_matches or [],
        manual_weights=manual_weights,
        execution_constraints=execution_constraints,
    )


# ── Tests ───────────────────────────────────────────────────────────


class TestRecommendBasic:
    """Basic recommendation output structure."""

    @pytest.mark.asyncio
    async def test_returns_plan_selection_output(self):
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input())
        assert isinstance(result, PlanSelectionOutput)

    @pytest.mark.asyncio
    async def test_recommended_plan_id_is_uuid(self):
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input())
        assert isinstance(result.recommended_plan_id, UUID)

    @pytest.mark.asyncio
    async def test_confidence_in_range(self):
        """Recommendation_Confidence is between 0 and 1 (Req 29.6)."""
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input())
        assert 0.0 <= result.recommendation_confidence <= 1.0

    @pytest.mark.asyncio
    async def test_goal_mode_used_matches_input(self):
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input(goal_mode="delivery_priority"))
        assert result.goal_mode_used == "delivery_priority"

    @pytest.mark.asyncio
    async def test_audit_metadata_present(self):
        """Audit metadata includes goal_mode and incident info (Req 29.10)."""
        engine = PlanRecommendationEngine()
        inp = _input(severity="P1-Critical")
        result = await engine.recommend(inp)
        assert result.audit_metadata["goal_mode"] == "balanced"
        assert result.audit_metadata["severity"] == "P1-Critical"


class TestFilterInfeasible:
    """Infeasible plans are filtered out (Req 29.3)."""

    @pytest.mark.asyncio
    async def test_infeasible_plans_excluded(self):
        good = _plan(feasibility="feasible")
        bad = _plan(feasibility="infeasible")
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input(candidates=[good, bad]))
        # Recommended should be the feasible one
        assert result.recommended_plan_id == good.plan_id

    @pytest.mark.asyncio
    async def test_all_infeasible_falls_back_to_all(self):
        """If all plans are infeasible, use them anyway as fallback."""
        p1 = _plan(feasibility="infeasible")
        p2 = _plan(feasibility="infeasible")
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input(candidates=[p1, p2]))
        assert result.recommended_plan_id in (p1.plan_id, p2.plan_id)


class TestRankingAndAlternatives:
    """Ranking, alternatives, and top-scored vs recommended (Req 29.4, 29.5)."""

    @pytest.mark.asyncio
    async def test_alternative_plan_ids_excludes_recommended(self):
        """alternative_plan_ids should not contain the recommended plan (Req 29.11)."""
        p1 = _plan()
        p2 = _plan()
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input(candidates=[p1, p2]))
        assert result.recommended_plan_id not in result.alternative_plan_ids

    @pytest.mark.asyncio
    async def test_at_least_one_alternative(self):
        """At least 1 alternative when multiple candidates exist (Req 29.4)."""
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input(candidates=[_plan(), _plan()]))
        assert len(result.alternative_plan_ids) >= 1

    @pytest.mark.asyncio
    async def test_ranked_plan_list_has_all_feasible(self):
        p1 = _plan()
        p2 = _plan()
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input(candidates=[p1, p2]))
        ids_in_list = {e["plan_id"] for e in result.ranked_plan_list}
        assert str(p1.plan_id) in ids_in_list
        assert str(p2.plan_id) in ids_in_list

    @pytest.mark.asyncio
    async def test_top_scored_and_recommended_distinguished(self):
        """top_scored_plan_id and recommended_plan_id are both present (Req 29.5)."""
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input(candidates=[_plan(), _plan()]))
        assert isinstance(result.top_scored_plan_id, UUID)
        assert isinstance(result.recommended_plan_id, UUID)


class TestAutoPreselection:
    """Auto-preselection logic (Req 29.7, 29.8)."""

    @pytest.mark.asyncio
    async def test_auto_preselect_when_high_confidence(self):
        """Auto-preselect when confidence >= threshold and no high risk."""
        # Single feasible plan → high confidence
        engine = PlanRecommendationEngine(confidence_threshold=0.7)
        result = await engine.recommend(_input(candidates=[_plan()]))
        assert result.recommendation_confidence >= 0.7
        assert result.auto_preselected is True

    @pytest.mark.asyncio
    async def test_no_auto_preselect_when_low_confidence(self):
        """No auto-preselect when confidence < 0.5 (Req 29.8)."""
        # All infeasible → low confidence
        engine = PlanRecommendationEngine()
        p1 = _plan(feasibility="infeasible")
        result = await engine.recommend(_input(candidates=[p1]))
        assert result.recommendation_confidence < 0.5
        assert result.auto_preselected is False

    @pytest.mark.asyncio
    async def test_no_auto_preselect_with_degradation_risk(self):
        """No auto-preselect when solver degradation occurred."""
        engine = PlanRecommendationEngine(confidence_threshold=0.5)
        p = _plan(degradation=True)
        result = await engine.recommend(_input(candidates=[p]))
        assert result.auto_preselected is False


class TestReasonCodes:
    """Structured reason output (Req 29.9)."""

    @pytest.mark.asyncio
    async def test_reason_codes_non_empty(self):
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input())
        assert len(result.reason_codes) > 0

    @pytest.mark.asyncio
    async def test_reason_summary_non_empty(self):
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input())
        assert len(result.reason_summary) > 0

    @pytest.mark.asyncio
    async def test_reason_codes_include_strategy(self):
        engine = PlanRecommendationEngine()
        result = await engine.recommend(
            _input(candidates=[_plan(strategy="global_reschedule")])
        )
        assert any("global_reschedule" in c for c in result.reason_codes)


class TestRiskFlags:
    """Risk flag collection."""

    @pytest.mark.asyncio
    async def test_timeout_partial_flagged(self):
        engine = PlanRecommendationEngine()
        p = _plan(feasibility="timeout_partial")
        result = await engine.recommend(_input(candidates=[p]))
        assert "solver_timeout_partial_solution" in result.risk_flags

    @pytest.mark.asyncio
    async def test_high_severity_flagged(self):
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input(severity="P1-Critical"))
        assert "high_severity_incident" in result.risk_flags


class TestWeightsAndCases:
    """Weights and case ID extraction."""

    @pytest.mark.asyncio
    async def test_manual_weights_used(self):
        w = {"spi": 0.5, "delayed_order_count": 0.5}
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input(manual_weights=w))
        assert result.weights_used == w

    @pytest.mark.asyncio
    async def test_default_weights_when_no_manual(self):
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input())
        assert "spi" in result.weights_used

    @pytest.mark.asyncio
    async def test_matched_case_ids_extracted(self):
        cid = uuid4()
        engine = PlanRecommendationEngine()
        result = await engine.recommend(
            _input(case_matches=[{"case_id": str(cid), "similarity": 0.9}])
        )
        assert cid in result.matched_case_ids


class TestComparisonMatrixAndGantt:
    """Placeholder comparison matrix and gantt diff."""

    @pytest.mark.asyncio
    async def test_comparison_matrix_has_rows(self):
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input(candidates=[_plan(), _plan()]))
        assert len(result.comparison_matrix.rows) >= 1

    @pytest.mark.asyncio
    async def test_gantt_diff_has_baseline(self):
        snap_id = uuid4()
        inp = _input()
        inp.schedule_snapshot_id = snap_id
        engine = PlanRecommendationEngine()
        result = await engine.recommend(inp)
        assert result.gantt_diff_payload.baseline_snapshot_id == str(snap_id)


class TestOutputSerialization:
    """PlanSelectionOutput round-trip (Req 30.9)."""

    @pytest.mark.asyncio
    async def test_output_roundtrip(self):
        engine = PlanRecommendationEngine()
        result = await engine.recommend(_input(candidates=[_plan(), _plan()]))
        json_str = result.model_dump_json()
        restored = PlanSelectionOutput.model_validate_json(json_str)
        assert restored.recommended_plan_id == result.recommended_plan_id
        assert restored.recommendation_confidence == result.recommendation_confidence
        assert restored.auto_preselected == result.auto_preselected
