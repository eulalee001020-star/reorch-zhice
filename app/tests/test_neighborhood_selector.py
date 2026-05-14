"""Unit tests for the Neighborhood_Selector service.

Covers:
- Six neighborhood types selection (Req 24.2)
- Local-Repair prefers local neighborhoods, blocks global (Req 24.5)
- Invariance protection: unaffected ops excluded (Req 24.10)
- Stagnation escalation to larger neighborhoods (Req 24.6)
- Budget-aware low-cost preference (Req 24.7)
- MODULE_VERSION constant (Req 22.3)
- Structured output format (Req 24.4)
- Rule-driven and learning-driven protocol (Req 24.9)
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.enums import (
    NeighborhoodType,
    StrategyType,
)
from app.models.schedule import ScheduleDetail
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    SolverChain,
    SolverMetadata,
)
from app.models.strategy import NeighborhoodConfig, StrategyRecommendation
from app.services.neighborhood_selector import (
    MODULE_VERSION,
    NeighborhoodSelector,
    _STAGNATION_ESCALATION_THRESHOLD,
    _LOW_BUDGET_SECONDS,
)


# ── Fixtures ────────────────────────────────────────────────────────

def _make_strategy(
    strategy_type: StrategyType = StrategyType.LOCAL_REPAIR,
    confidence: float = 0.75,
) -> StrategyRecommendation:
    return StrategyRecommendation(
        strategy_type=strategy_type,
        confidence=confidence,
        key_factors=["test_factor"],
        reasoning="Test strategy reasoning.",
    )


def _make_candidate_plan() -> CandidatePlan:
    return CandidatePlan(
        plan_id=uuid4(),
        strategy_type="local_repair",
        schedule_detail=ScheduleDetail(work_orders=[], resources=[]),
        gantt_version="v1",
        solver_chain=SolverChain(
            strategy_type="local_repair",
            rule_selection="minimum_slack_time",
            neighborhood_selection="critical_path",
            repair_policy="balanced",
            solver_name="cp_sat",
            key_parameters={},
            search_budget_seconds=30.0,
            constraint_validation_result="pass",
        ),
        feasibility_status="feasible",
        solver_metadata=SolverMetadata(
            solve_time_seconds=5.0,
            iteration_count=100,
        ),
        constraint_report=ConstraintValidationReport(
            is_feasible=True,
            checked_constraints=["device_capability", "process_order"],
        ),
    )


_AFFECTED_OPS = ["op-1", "op-2", "op-3"]

_LOCAL_TYPES = {
    NeighborhoodType.CRITICAL_PATH,
    NeighborhoodType.SAME_DEVICE_SWAP,
    NeighborhoodType.DELAYED_ORDER,
}

_GLOBAL_TYPES = {
    NeighborhoodType.BOTTLENECK_DEVICE,
    NeighborhoodType.OPERATION_INSERT,
    NeighborhoodType.DEVICE_REASSIGNMENT,
}


# ── Tests ───────────────────────────────────────────────────────────


class TestModuleVersion:
    def test_module_version_exists(self):
        """MODULE_VERSION constant is defined (Req 22.3)."""
        assert MODULE_VERSION
        assert isinstance(MODULE_VERSION, str)


class TestLocalRepairStrategy:
    @pytest.mark.asyncio
    async def test_local_repair_prefers_local_neighborhoods(self):
        """Local-Repair prefers local neighborhoods (Req 24.5)."""
        selector = NeighborhoodSelector()
        results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=0,
            remaining_budget_seconds=30.0,
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            perturbation_constraint=0.5,
        )
        assert len(results) >= 1
        # Top result should be a local neighborhood
        top_type = NeighborhoodType(results[0].neighborhood_type)
        assert top_type in _LOCAL_TYPES

    @pytest.mark.asyncio
    async def test_local_repair_blocks_global_neighborhoods(self):
        """Local-Repair blocks global neighborhoods by default (Req 24.5)."""
        selector = NeighborhoodSelector()
        results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=0,
            remaining_budget_seconds=30.0,
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            perturbation_constraint=0.5,
        )
        result_types = {NeighborhoodType(r.neighborhood_type) for r in results}
        # No global neighborhoods should appear
        assert not result_types & _GLOBAL_TYPES


class TestGlobalRescheduleStrategy:
    @pytest.mark.asyncio
    async def test_global_reschedule_includes_all_neighborhoods(self):
        """Global-Reschedule allows all neighborhood types (Req 24.2)."""
        selector = NeighborhoodSelector()
        results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=0,
            remaining_budget_seconds=30.0,
            strategy=_make_strategy(StrategyType.GLOBAL_RESCHEDULE),
            perturbation_constraint=0.8,
        )
        result_types = {NeighborhoodType(r.neighborhood_type) for r in results}
        # Should include both local and global neighborhoods
        assert len(result_types) == 6


class TestWaitAndRepairStrategy:
    @pytest.mark.asyncio
    async def test_wait_strategy_favors_same_device_swap(self):
        """Wait-and-Repair favors same_device_swap."""
        selector = NeighborhoodSelector()
        results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=0,
            remaining_budget_seconds=30.0,
            strategy=_make_strategy(StrategyType.WAIT_AND_REPAIR),
            perturbation_constraint=0.5,
        )
        assert len(results) >= 1
        top_type = NeighborhoodType(results[0].neighborhood_type)
        assert top_type == NeighborhoodType.SAME_DEVICE_SWAP


class TestInvarianceProtection:
    @pytest.mark.asyncio
    async def test_local_repair_scopes_to_affected_ops(self):
        """Invariance protection: target ops limited to affected set (Req 24.10)."""
        selector = NeighborhoodSelector()
        results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=0,
            remaining_budget_seconds=30.0,
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            perturbation_constraint=0.5,
        )
        affected_set = set(_AFFECTED_OPS)
        for r in results:
            # All target ops must be within the affected set
            assert set(r.target_operation_ids) <= affected_set

    @pytest.mark.asyncio
    async def test_global_reschedule_allows_broader_scope(self):
        """Global-Reschedule may use broader scope (no invariance restriction)."""
        selector = NeighborhoodSelector()
        results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=0,
            remaining_budget_seconds=30.0,
            strategy=_make_strategy(StrategyType.GLOBAL_RESCHEDULE),
            perturbation_constraint=0.8,
        )
        # Some neighborhoods should have empty target_operation_ids (global scope)
        has_global_scope = any(len(r.target_operation_ids) == 0 for r in results)
        assert has_global_scope


class TestStagnationEscalation:
    @pytest.mark.asyncio
    async def test_no_escalation_below_threshold(self):
        """No escalation when stagnation <= threshold (Req 24.6)."""
        selector = NeighborhoodSelector()
        results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=_STAGNATION_ESCALATION_THRESHOLD,
            remaining_budget_seconds=30.0,
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            perturbation_constraint=0.5,
        )
        result_types = {NeighborhoodType(r.neighborhood_type) for r in results}
        # Still no global neighborhoods at threshold
        assert not result_types & _GLOBAL_TYPES

    @pytest.mark.asyncio
    async def test_escalation_above_threshold_allows_global(self):
        """Stagnation > threshold allows global neighborhoods for Local-Repair (Req 24.6)."""
        selector = NeighborhoodSelector()
        results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=_STAGNATION_ESCALATION_THRESHOLD + 3,
            remaining_budget_seconds=30.0,
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            perturbation_constraint=0.5,
        )
        result_types = {NeighborhoodType(r.neighborhood_type) for r in results}
        # Global neighborhoods should now appear
        assert result_types & _GLOBAL_TYPES


class TestBudgetAwareSelection:
    @pytest.mark.asyncio
    async def test_low_budget_prefers_low_cost(self):
        """Near time limit, prefer low-cost neighborhoods (Req 24.7)."""
        selector = NeighborhoodSelector()
        results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=0,
            remaining_budget_seconds=3.0,  # very low budget
            strategy=_make_strategy(StrategyType.GLOBAL_RESCHEDULE),
            perturbation_constraint=0.8,
        )
        assert len(results) >= 1
        top_type = NeighborhoodType(results[0].neighborhood_type)
        # Low-cost neighborhoods should be preferred
        low_cost = {NeighborhoodType.SAME_DEVICE_SWAP, NeighborhoodType.OPERATION_INSERT}
        assert top_type in low_cost

    @pytest.mark.asyncio
    async def test_high_budget_allows_expensive_neighborhoods(self):
        """With ample budget, expensive neighborhoods are available."""
        selector = NeighborhoodSelector()
        results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=0,
            remaining_budget_seconds=50.0,
            strategy=_make_strategy(StrategyType.GLOBAL_RESCHEDULE),
            perturbation_constraint=0.8,
        )
        result_types = {NeighborhoodType(r.neighborhood_type) for r in results}
        assert NeighborhoodType.DEVICE_REASSIGNMENT in result_types


class TestStructuredOutput:
    @pytest.mark.asyncio
    async def test_output_has_required_fields(self):
        """Output contains all required structured fields (Req 24.4)."""
        selector = NeighborhoodSelector()
        results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=0,
            remaining_budget_seconds=30.0,
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            perturbation_constraint=0.5,
        )
        assert len(results) >= 1
        r = results[0]
        assert isinstance(r, NeighborhoodConfig)
        assert r.neighborhood_type  # non-empty
        assert isinstance(r.target_operation_ids, list)
        assert 0.0 <= r.intensity <= 1.0
        assert isinstance(r.estimated_impact_scope, int)
        assert r.reasoning  # non-empty string

    @pytest.mark.asyncio
    async def test_six_neighborhood_types_supported(self):
        """All six neighborhood types are supported (Req 24.2)."""
        selector = NeighborhoodSelector()
        results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=0,
            remaining_budget_seconds=30.0,
            strategy=_make_strategy(StrategyType.GLOBAL_RESCHEDULE),
            perturbation_constraint=0.8,
        )
        result_types = {NeighborhoodType(r.neighborhood_type) for r in results}
        expected = {
            NeighborhoodType.CRITICAL_PATH,
            NeighborhoodType.BOTTLENECK_DEVICE,
            NeighborhoodType.DELAYED_ORDER,
            NeighborhoodType.SAME_DEVICE_SWAP,
            NeighborhoodType.OPERATION_INSERT,
            NeighborhoodType.DEVICE_REASSIGNMENT,
        }
        assert result_types == expected


class TestPerturbationConstraint:
    @pytest.mark.asyncio
    async def test_tight_perturbation_penalizes_global(self):
        """Tight perturbation constraint penalizes global neighborhoods."""
        selector = NeighborhoodSelector()
        # Tight constraint
        tight_results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=0,
            remaining_budget_seconds=30.0,
            strategy=_make_strategy(StrategyType.GLOBAL_RESCHEDULE),
            perturbation_constraint=0.1,
        )
        # Loose constraint
        loose_results = await selector.select_neighborhood(
            current_solution=_make_candidate_plan(),
            affected_operation_ids=_AFFECTED_OPS,
            stagnation_count=0,
            remaining_budget_seconds=30.0,
            strategy=_make_strategy(StrategyType.GLOBAL_RESCHEDULE),
            perturbation_constraint=0.8,
        )
        # With tight constraint, device_reassignment should rank lower
        def _find_rank(results: list[NeighborhoodConfig], nh_type: str) -> int:
            for i, r in enumerate(results):
                if r.neighborhood_type == nh_type:
                    return i
            return len(results)

        tight_rank = _find_rank(tight_results, NeighborhoodType.DEVICE_REASSIGNMENT)
        loose_rank = _find_rank(loose_results, NeighborhoodType.DEVICE_REASSIGNMENT)
        assert tight_rank >= loose_rank
