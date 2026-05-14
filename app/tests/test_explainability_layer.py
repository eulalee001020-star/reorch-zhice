"""Tests for ExplainabilityLayer service.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 28.1, 28.2, 28.3,
           28.7, 28.8, 28.9
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.case import CaseRecord
from app.models.evaluation import ComparisonMatrix, ComparisonMatrixRow, KPIVector
from app.models.explanation import RecommendationExplanation, SolverChainExplanation
from app.models.execution import ExecutionResult
from app.models.schedule import ScheduleDetail
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    ConstraintViolation,
    SolverChain,
    SolverMetadata,
)
from app.services.explainability_layer import ExplainabilityLayer

_NOW = datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc)


# ── Helpers ─────────────────────────────────────────────────────────


def _chain(strategy: str = "local_repair", **kw) -> SolverChain:
    defaults = dict(
        strategy_type=strategy,
        rule_selection="due_date_priority",
        neighborhood_selection="critical_path",
        repair_policy="balanced",
        solver_name="cp_sat",
        key_parameters={},
        search_budget_seconds=30.0,
        constraint_validation_result="pass",
        stages=["规则选择", "初解生成", "邻域选择", "LNS修复", "约束校验"],
    )
    defaults.update(kw)
    return SolverChain(**defaults)


def _meta(**kw) -> SolverMetadata:
    defaults = dict(solve_time_seconds=12.5, iteration_count=150)
    defaults.update(kw)
    return SolverMetadata(**defaults)


def _report(feasible: bool = True, violations: list | None = None) -> ConstraintValidationReport:
    return ConstraintValidationReport(
        is_feasible=feasible,
        violations=violations or [],
        checked_constraints=["equipment_capability", "process_order"],
    )


def _plan(
    strategy: str = "local_repair",
    feasibility: str = "feasible",
    plan_id=None,
    degradation: bool = False,
    violations: list | None = None,
) -> CandidatePlan:
    return CandidatePlan(
        plan_id=plan_id or uuid4(),
        strategy_type=strategy,
        schedule_detail=ScheduleDetail(),
        gantt_version="v1",
        solver_chain=_chain(strategy=strategy),
        feasibility_status=feasibility,
        solver_metadata=_meta(
            degradation_occurred=degradation,
            degradation_reason="timeout" if degradation else None,
        ),
        constraint_report=_report(
            feasible=(feasibility != "infeasible"),
            violations=violations,
        ),
    )


def _kpi(**kw) -> KPIVector:
    defaults = dict(
        delayed_order_count=2,
        max_delay_minutes=45.0,
        spi=0.15,
        resource_utilization_delta=-0.03,
        changeover_count_delta=1,
        critical_order_otd_impact=0.95,
        normalized_score=0.82,
    )
    defaults.update(kw)
    return KPIVector(**defaults)


def _matrix_row(plan_id: str, **kpi_kw) -> ComparisonMatrixRow:
    return ComparisonMatrixRow(
        plan_id=plan_id,
        kpi_vector=_kpi(**kpi_kw),
        delta_vs_baseline={},
        is_score_close=False,
    )


def _matrix(plans: list[CandidatePlan], kpi_overrides: list[dict] | None = None) -> ComparisonMatrix:
    rows = []
    for i, p in enumerate(plans):
        kw = kpi_overrides[i] if kpi_overrides and i < len(kpi_overrides) else {}
        rows.append(_matrix_row(str(p.plan_id), **kw))
    return ComparisonMatrix(
        rows=rows,
        normalization_method="min-max",
        score_unit_descriptions={},
        baseline_snapshot_id="snap-001",
    )


def _case(case_id=None, with_result: bool = False) -> CaseRecord:
    return CaseRecord(
        case_id=case_id or uuid4(),
        incident_features={"type": "equipment_failure"},
        impact_scope={"affected_orders": 3},
        strategy_type="local_repair",
        confirmed_plan_summary="局部修复方案",
        execution_result=ExecutionResult(
            incident_id=uuid4(),
            decision_record_id=uuid4(),
            actual_completion_times={},
            planned_completion_times={},
            actual_otd=0.95,
            actual_resource_utilization=0.8,
            deviation_percentage=5.0,
        ) if with_result else None,
        is_override=False,
        rule_selection="due_date_priority",
        neighborhood_selection="critical_path",
        repair_policy="balanced",
        solver_chain=_chain(),
        created_at=_NOW,
    )


# ── Tests: explain_recommendation ───────────────────────────────────


class TestExplainRecommendation:
    """Tests for ExplainabilityLayer.explain_recommendation."""

    @pytest.mark.asyncio
    async def test_returns_recommendation_explanation(self):
        """Output is a structured RecommendationExplanation (Req 6.6)."""
        layer = ExplainabilityLayer()
        rec = _plan()
        alt = _plan()
        result = await layer.explain_recommendation(
            rec, [alt], _matrix([rec, alt]), []
        )
        assert isinstance(result, RecommendationExplanation)

    @pytest.mark.asyncio
    async def test_core_reasons_at_most_three(self):
        """Core reasons ≤ 3 (Req 6.2)."""
        layer = ExplainabilityLayer()
        rec = _plan()
        cases = [_case(with_result=True)]
        result = await layer.explain_recommendation(
            rec, [_plan()], _matrix([rec, _plan()]), cases
        )
        assert len(result.core_reasons) <= 3
        assert len(result.core_reasons) >= 1

    @pytest.mark.asyncio
    async def test_key_advantages_present(self):
        """Key advantages are generated (Req 6.2)."""
        layer = ExplainabilityLayer()
        rec = _plan()
        result = await layer.explain_recommendation(
            rec, [], _matrix([rec]), []
        )
        assert len(result.key_advantages) >= 1

    @pytest.mark.asyncio
    async def test_main_risks_present(self):
        """Main risks are generated (Req 6.2)."""
        layer = ExplainabilityLayer()
        rec = _plan()
        result = await layer.explain_recommendation(
            rec, [], _matrix([rec]), []
        )
        assert len(result.main_risks) >= 1

    @pytest.mark.asyncio
    async def test_summary_within_200_chars(self):
        """Summary ≤ 200 characters (Req 6.5)."""
        layer = ExplainabilityLayer()
        rec = _plan()
        result = await layer.explain_recommendation(
            rec, [], _matrix([rec]), []
        )
        assert len(result.summary) <= 200
        assert len(result.summary) > 0

    @pytest.mark.asyncio
    async def test_uses_business_terms(self):
        """Summary uses business terms not pure technical jargon (Req 6.3)."""
        layer = ExplainabilityLayer()
        rec = _plan(strategy="local_repair")
        result = await layer.explain_recommendation(
            rec, [], _matrix([rec]), []
        )
        # Should contain Chinese business terms
        assert any(
            term in result.summary
            for term in ["局部修复", "全局重排", "等待修复", "工单", "OTD", "扰动"]
        )

    @pytest.mark.asyncio
    async def test_references_case_ids_when_cases_provided(self):
        """Historical case IDs referenced in explanation (Req 6.4)."""
        layer = ExplainabilityLayer()
        case = _case(with_result=True)
        rec = _plan()
        result = await layer.explain_recommendation(
            rec, [], _matrix([rec]), [case]
        )
        assert str(case.case_id) in result.referenced_case_ids

    @pytest.mark.asyncio
    async def test_no_case_ids_when_no_cases(self):
        """No case IDs when no historical cases used."""
        layer = ExplainabilityLayer()
        rec = _plan()
        result = await layer.explain_recommendation(
            rec, [], _matrix([rec]), []
        )
        assert result.referenced_case_ids == []

    @pytest.mark.asyncio
    async def test_case_id_mentioned_in_core_reasons(self):
        """Case ID appears in core reasons when cases are used (Req 6.4)."""
        layer = ExplainabilityLayer()
        case = _case(with_result=True)
        rec = _plan()
        result = await layer.explain_recommendation(
            rec, [], _matrix([rec]), [case]
        )
        case_mentioned = any(
            str(case.case_id) in reason for reason in result.core_reasons
        )
        assert case_mentioned

    @pytest.mark.asyncio
    async def test_comparison_with_alternatives(self):
        """Generates comparison for each alternative (Req 6.1)."""
        layer = ExplainabilityLayer()
        rec = _plan()
        alt1 = _plan()
        alt2 = _plan()
        result = await layer.explain_recommendation(
            rec, [alt1, alt2], _matrix([rec, alt1, alt2]), []
        )
        assert len(result.comparison_with_alternatives) == 2
        alt_ids = {c["plan_id"] for c in result.comparison_with_alternatives}
        assert str(alt1.plan_id) in alt_ids
        assert str(alt2.plan_id) in alt_ids

    @pytest.mark.asyncio
    async def test_comparison_includes_key_differences(self):
        """Each alternative comparison has key_differences (Req 6.1)."""
        layer = ExplainabilityLayer()
        rec = _plan()
        alt = _plan()
        result = await layer.explain_recommendation(
            rec,
            [alt],
            _matrix(
                [rec, alt],
                kpi_overrides=[
                    {"delayed_order_count": 1, "spi": 0.10},
                    {"delayed_order_count": 5, "spi": 0.30},
                ],
            ),
            [],
        )
        assert len(result.comparison_with_alternatives) == 1
        comp = result.comparison_with_alternatives[0]
        assert "key_differences" in comp
        assert len(comp["key_differences"]) >= 1

    @pytest.mark.asyncio
    async def test_structured_output_serializable(self):
        """Output is structured and JSON-serializable (Req 6.6)."""
        layer = ExplainabilityLayer()
        rec = _plan()
        result = await layer.explain_recommendation(
            rec, [_plan()], _matrix([rec, _plan()]), []
        )
        json_str = result.model_dump_json()
        restored = RecommendationExplanation.model_validate_json(json_str)
        assert restored.core_reasons == result.core_reasons
        assert restored.summary == result.summary

    @pytest.mark.asyncio
    async def test_timeout_partial_plan_risks(self):
        """Timeout partial plan generates appropriate risk (Req 6.2)."""
        layer = ExplainabilityLayer()
        rec = _plan(feasibility="timeout_partial")
        result = await layer.explain_recommendation(
            rec, [], _matrix([rec]), []
        )
        assert any("超时" in r for r in result.main_risks)

    @pytest.mark.asyncio
    async def test_degradation_plan_risks(self):
        """Degraded solver generates appropriate risk."""
        layer = ExplainabilityLayer()
        rec = _plan(degradation=True)
        result = await layer.explain_recommendation(
            rec, [], _matrix([rec]), []
        )
        assert any("降级" in r for r in result.main_risks)


# ── Tests: explain_solver_chain ─────────────────────────────────────


class TestExplainSolverChain:
    """Tests for ExplainabilityLayer.explain_solver_chain."""

    @pytest.mark.asyncio
    async def test_returns_solver_chain_explanation(self):
        """Output is a structured SolverChainExplanation (Req 28.9)."""
        layer = ExplainabilityLayer()
        result = await layer.explain_solver_chain(_plan())
        assert isinstance(result, SolverChainExplanation)

    @pytest.mark.asyncio
    async def test_algorithm_category_for_local_repair(self):
        """Local repair shows LNS + CP-SAT category (Req 28.3)."""
        layer = ExplainabilityLayer()
        result = await layer.explain_solver_chain(_plan(strategy="local_repair"))
        assert "LNS" in result.algorithm_category or "CP-SAT" in result.algorithm_category

    @pytest.mark.asyncio
    async def test_algorithm_category_for_wait_and_repair(self):
        """Wait-and-repair shows time-shift category (Req 28.4)."""
        layer = ExplainabilityLayer()
        result = await layer.explain_solver_chain(_plan(strategy="wait_and_repair"))
        assert "时间偏移" in result.algorithm_category

    @pytest.mark.asyncio
    async def test_algorithm_category_for_global_reschedule(self):
        """Global reschedule shows CP-SAT global category (Req 28.6)."""
        layer = ExplainabilityLayer()
        result = await layer.explain_solver_chain(_plan(strategy="global_reschedule"))
        assert "全局" in result.algorithm_category or "CP-SAT" in result.algorithm_category

    @pytest.mark.asyncio
    async def test_applicable_scenario_present(self):
        """Applicable scenario is a non-empty business description (Req 28.3)."""
        layer = ExplainabilityLayer()
        result = await layer.explain_solver_chain(_plan())
        assert len(result.applicable_scenario) > 0

    @pytest.mark.asyncio
    async def test_chain_reason_present(self):
        """Chain reason explains why this chain was chosen (Req 28.3)."""
        layer = ExplainabilityLayer()
        result = await layer.explain_solver_chain(_plan())
        assert len(result.chain_reason) > 0

    @pytest.mark.asyncio
    async def test_optimization_objectives_present(self):
        """Optimization objectives are listed."""
        layer = ExplainabilityLayer()
        result = await layer.explain_solver_chain(_plan())
        assert len(result.optimization_objectives) >= 1

    @pytest.mark.asyncio
    async def test_computation_time_from_metadata(self):
        """Computation time comes from solver_metadata (Req 28.3)."""
        layer = ExplainabilityLayer()
        plan = _plan()
        result = await layer.explain_solver_chain(plan)
        assert result.computation_time_seconds == plan.solver_metadata.solve_time_seconds

    @pytest.mark.asyncio
    async def test_stages_from_solver_chain(self):
        """Stages come from solver_chain.stages (Req 28.8)."""
        layer = ExplainabilityLayer()
        plan = _plan()
        result = await layer.explain_solver_chain(plan)
        assert result.stages == plan.solver_chain.stages

    @pytest.mark.asyncio
    async def test_frozen_constraints_for_local_repair(self):
        """Local repair includes frozen constraints (Req 28.5)."""
        layer = ExplainabilityLayer()
        result = await layer.explain_solver_chain(_plan(strategy="local_repair"))
        assert result.frozen_constraints is not None
        assert len(result.frozen_constraints) >= 1

    @pytest.mark.asyncio
    async def test_frozen_constraints_for_wait_and_repair(self):
        """Wait-and-repair includes frozen constraints."""
        layer = ExplainabilityLayer()
        result = await layer.explain_solver_chain(_plan(strategy="wait_and_repair"))
        assert result.frozen_constraints is not None

    @pytest.mark.asyncio
    async def test_no_frozen_constraints_for_global(self):
        """Global reschedule has no frozen constraints."""
        layer = ExplainabilityLayer()
        result = await layer.explain_solver_chain(_plan(strategy="global_reschedule"))
        assert result.frozen_constraints is None

    @pytest.mark.asyncio
    async def test_structured_output_serializable(self):
        """Output is structured and JSON-serializable (Req 28.9)."""
        layer = ExplainabilityLayer()
        result = await layer.explain_solver_chain(_plan())
        json_str = result.model_dump_json()
        restored = SolverChainExplanation.model_validate_json(json_str)
        assert restored.algorithm_category == result.algorithm_category
        assert restored.stages == result.stages

    @pytest.mark.asyncio
    async def test_distinguishes_generation_from_ranking(self):
        """Explanation covers generation chain, not ranking (Req 28.7).

        The solver chain explanation should describe how the plan was
        *generated* (solver algorithm), not how it was *ranked*.
        """
        layer = ExplainabilityLayer()
        result = await layer.explain_solver_chain(_plan())
        # Should not mention ranking/recommendation concepts
        assert "排序" not in result.chain_reason
        assert "推荐" not in result.chain_reason
        # Should mention solver/generation concepts
        assert any(
            term in result.chain_reason
            for term in ["修复", "搜索", "优化", "策略", "扰动", "调整"]
        )
