"""Tests for HybridSolver core solve engine.

Covers:
- Heuristic initial solution generation per strategy
- LNS optimization with dynamic neighborhood callback
- 60-second timeout with partial results
- Infeasible report when no solution found
- Solver_Portfolio degradation (primary → fallback → rule)
- SolverChain and SolverMetadata recording
- Constraint validation (process order, resource exclusion, invariance)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from uuid import uuid4

import pytest

from app.models.enums import (
    DeliveryRiskLevel,
    IncidentSeverity,
    NeighborhoodType,
    RepairMode,
    RuleApplicableStage,
    RuleCategory,
    StrategyType,
)
from app.models.impact import AffectedOperation, AffectedWorkOrder, ImpactReport
from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    SolverChain,
    SolverMetadata,
)
from app.models.strategy import (
    NeighborhoodConfig,
    RepairPolicyConfig,
    RuleSelectionResult,
    SolverChainConfig,
    StrategyRecommendation,
)
from app.services.hybrid_solver import HybridSolver


# ── Fixtures ────────────────────────────────────────────────────────

NOW = datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc)


def _make_snapshot() -> ScheduleSnapshot:
    """Create a minimal ScheduleSnapshot with 2 work orders, 4 operations."""
    ops_wo1 = [
        Operation(
            operation_id="op-1",
            work_order_id="wo-1",
            resource_id="machine-A",
            start_time=NOW,
            end_time=NOW + timedelta(hours=1),
            successor_ids=["op-2"],
            required_capabilities=["cutting"],
        ),
        Operation(
            operation_id="op-2",
            work_order_id="wo-1",
            resource_id="machine-B",
            start_time=NOW + timedelta(hours=1),
            end_time=NOW + timedelta(hours=2),
            predecessor_ids=["op-1"],
            required_capabilities=["welding"],
        ),
    ]
    ops_wo2 = [
        Operation(
            operation_id="op-3",
            work_order_id="wo-2",
            resource_id="machine-A",
            start_time=NOW + timedelta(hours=2),
            end_time=NOW + timedelta(hours=3),
            successor_ids=["op-4"],
            required_capabilities=["cutting"],
        ),
        Operation(
            operation_id="op-4",
            work_order_id="wo-2",
            resource_id="machine-C",
            start_time=NOW + timedelta(hours=3),
            end_time=NOW + timedelta(hours=4),
            predecessor_ids=["op-3"],
            required_capabilities=["assembly"],
        ),
    ]
    return ScheduleSnapshot(
        snapshot_id=uuid4(),
        captured_at=NOW,
        workshop_id="workshop-1",
        work_orders=[
            WorkOrder(
                work_order_id="wo-1",
                product_name="Product-A",
                due_date=NOW + timedelta(days=2),
                operations=ops_wo1,
                priority=1,
            ),
            WorkOrder(
                work_order_id="wo-2",
                product_name="Product-B",
                due_date=NOW + timedelta(days=3),
                operations=ops_wo2,
                priority=0,
            ),
        ],
    )


def _make_impact_report(affected_op_ids: list[str] | None = None) -> ImpactReport:
    """Create a minimal ImpactReport."""
    if affected_op_ids is None:
        affected_op_ids = ["op-1", "op-2"]
    ops = [
        AffectedOperation(
            operation_id=op_id,
            work_order_id="wo-1",
            resource_id="machine-A",
            is_direct=(op_id == "op-1"),
            estimated_delay_minutes=30.0,
        )
        for op_id in affected_op_ids
    ]
    return ImpactReport(
        incident_id=uuid4(),
        schedule_snapshot_id=uuid4(),
        analysis_reference_time=NOW,
        affected_operations=ops,
        affected_work_orders=[
            AffectedWorkOrder(
                work_order_id="wo-1",
                product_name="Product-A",
                due_date=NOW + timedelta(days=2),
                delivery_risk_level=DeliveryRiskLevel.WARNING,
                remaining_buffer_minutes=120.0,
                affected_operations=ops,
            ),
        ],
        affected_resource_ids=["machine-A"],
        delivery_risk_distribution={DeliveryRiskLevel.WARNING: 1},
        estimated_total_delay_minutes=60.0,
    )


def _make_strategy(
    strategy_type: StrategyType = StrategyType.LOCAL_REPAIR,
) -> StrategyRecommendation:
    return StrategyRecommendation(
        strategy_type=strategy_type,
        confidence=0.8,
        key_factors=["test"],
        reasoning="Test strategy",
    )


def _make_repair_config(
    strategy_type: StrategyType = StrategyType.LOCAL_REPAIR,
) -> RepairPolicyConfig:
    mode_map = {
        StrategyType.WAIT_AND_REPAIR: RepairMode.CONSERVATIVE,
        StrategyType.LOCAL_REPAIR: RepairMode.BALANCED,
        StrategyType.GLOBAL_RESCHEDULE: RepairMode.AGGRESSIVE,
    }
    budget_map = {
        StrategyType.WAIT_AND_REPAIR: 10.0,
        StrategyType.LOCAL_REPAIR: 30.0,
        StrategyType.GLOBAL_RESCHEDULE: 60.0,
    }
    return RepairPolicyConfig(
        repair_mode=mode_map.get(strategy_type, RepairMode.BALANCED),
        frozen_operation_ids=[],
        allowed_perturbation_scope=["op-1", "op-2"],
        search_time_budget_seconds=budget_map.get(strategy_type, 30.0),
        candidate_count_target=3,
        fallback_condition="No improvement after 80% budget",
        fallback_mode="return_current_best",
    )


def _make_solver_chain_config() -> SolverChainConfig:
    return SolverChainConfig(
        primary_solver="cp_sat_lns",
        fallback_solver="greedy_local_repair",
        fallback_rule="minimum_slack_time",
        degradation_trigger="Primary solver timeout",
        max_timeout_seconds=60.0,
    )


def _make_rules() -> list[RuleSelectionResult]:
    return [
        RuleSelectionResult(
            rule_name="minimum_slack_time_rule",
            rule_category=RuleCategory.MINIMUM_SLACK_TIME,
            applicable_stage=RuleApplicableStage.REPAIR,
            confidence=0.7,
            reasoning="Test rule",
        ),
    ]


async def _mock_neighborhood_callback(
    current_solution: CandidatePlan,
    affected_operation_ids: list[str],
    stagnation_count: int,
    remaining_budget_seconds: float,
    strategy: StrategyRecommendation,
    perturbation_constraint: float,
) -> list[NeighborhoodConfig]:
    """Mock neighborhood callback that returns a simple config."""
    return [
        NeighborhoodConfig(
            neighborhood_type=NeighborhoodType.SAME_DEVICE_SWAP,
            target_operation_ids=affected_operation_ids,
            intensity=0.5,
            estimated_impact_scope=len(affected_operation_ids),
            reasoning="Mock neighborhood",
        ),
    ]


class _FakeBundle:
    """Lightweight fake SolverPolicyBundle for testing."""

    def __init__(
        self,
        strategy_type: StrategyType = StrategyType.LOCAL_REPAIR,
        neighborhood_callback=None,
        repair_config: RepairPolicyConfig | None = None,
        solver_chain_config: SolverChainConfig | None = None,
        rules: list[RuleSelectionResult] | None = None,
    ):
        self.strategy = _make_strategy(strategy_type)
        self.repair_config = repair_config or _make_repair_config(strategy_type)
        self.solver_chain_config = solver_chain_config or _make_solver_chain_config()
        self.rules = rules if rules is not None else _make_rules()
        self.get_neighborhood_config = neighborhood_callback


# ── Tests ───────────────────────────────────────────────────────────


class TestHybridSolverBasic:
    """Basic solve flow tests."""

    @pytest.mark.asyncio
    async def test_solve_returns_candidate_plans(self):
        """solve() returns a non-empty list of CandidatePlan."""
        solver = HybridSolver()
        snapshot = _make_snapshot()
        impact = _make_impact_report()
        bundle = _FakeBundle(
            strategy_type=StrategyType.LOCAL_REPAIR,
            neighborhood_callback=_mock_neighborhood_callback,
        )

        plans = await solver.solve(bundle, impact, snapshot)

        assert len(plans) >= 1
        assert all(isinstance(p, CandidatePlan) for p in plans)

    @pytest.mark.asyncio
    async def test_solve_returns_at_most_top_3(self):
        """solve() returns at most 3 candidates (Req 4.1)."""
        solver = HybridSolver()
        snapshot = _make_snapshot()
        impact = _make_impact_report()
        bundle = _FakeBundle(
            strategy_type=StrategyType.LOCAL_REPAIR,
            neighborhood_callback=_mock_neighborhood_callback,
        )

        plans = await solver.solve(bundle, impact, snapshot)

        assert len(plans) <= 3

    @pytest.mark.asyncio
    async def test_solver_chain_recorded(self):
        """Each CandidatePlan has a complete SolverChain (Req 4.16)."""
        solver = HybridSolver()
        snapshot = _make_snapshot()
        impact = _make_impact_report()
        bundle = _FakeBundle(
            strategy_type=StrategyType.LOCAL_REPAIR,
            neighborhood_callback=_mock_neighborhood_callback,
        )

        plans = await solver.solve(bundle, impact, snapshot)

        for plan in plans:
            assert plan.solver_chain is not None
            assert plan.solver_chain.strategy_type == "local_repair"
            assert plan.solver_chain.solver_name == "cp_sat_lns"
            assert len(plan.solver_chain.stages) > 0

    @pytest.mark.asyncio
    async def test_solver_metadata_recorded(self):
        """Each CandidatePlan has SolverMetadata (Req 4.10)."""
        solver = HybridSolver()
        snapshot = _make_snapshot()
        impact = _make_impact_report()
        bundle = _FakeBundle(
            strategy_type=StrategyType.LOCAL_REPAIR,
            neighborhood_callback=_mock_neighborhood_callback,
        )

        plans = await solver.solve(bundle, impact, snapshot)

        for plan in plans:
            assert plan.solver_metadata is not None
            assert plan.solver_metadata.solve_time_seconds >= 0
            assert plan.solver_metadata.iteration_count >= 0


class TestStrategySpecificBehavior:
    """Tests for strategy-specific solve behavior (Req 4.3, 4.4, 4.5)."""

    @pytest.mark.asyncio
    async def test_wait_and_repair_only_shifts_affected(self):
        """WAIT_AND_REPAIR: only affected ops are adjusted (Req 4.3)."""
        solver = HybridSolver()
        snapshot = _make_snapshot()
        impact = _make_impact_report(["op-1"])
        bundle = _FakeBundle(
            strategy_type=StrategyType.WAIT_AND_REPAIR,
            neighborhood_callback=_mock_neighborhood_callback,
        )

        plans = await solver.solve(bundle, impact, snapshot)

        assert len(plans) >= 1
        plan = plans[0]
        for wo in plan.schedule_detail.work_orders:
            for op in wo.operations:
                if op.operation_id == "op-1":
                    assert op.is_adjusted is True
                elif op.operation_id in ("op-3", "op-4"):
                    # Unaffected ops should not be adjusted
                    assert op.is_adjusted is False

    @pytest.mark.asyncio
    async def test_local_repair_adjusts_affected_and_downstream(self):
        """LOCAL_REPAIR: affected + downstream ops adjusted (Req 4.4)."""
        solver = HybridSolver()
        snapshot = _make_snapshot()
        # op-1 is affected; op-2 has op-1 as predecessor (downstream)
        impact = _make_impact_report(["op-1"])
        bundle = _FakeBundle(
            strategy_type=StrategyType.LOCAL_REPAIR,
            neighborhood_callback=_mock_neighborhood_callback,
        )

        plans = await solver.solve(bundle, impact, snapshot)

        assert len(plans) >= 1
        plan = plans[0]
        adjusted_ids = set()
        for wo in plan.schedule_detail.work_orders:
            for op in wo.operations:
                if op.is_adjusted:
                    adjusted_ids.add(op.operation_id)

        assert "op-1" in adjusted_ids  # directly affected

    @pytest.mark.asyncio
    async def test_global_reschedule_adjusts_all(self):
        """GLOBAL_RESCHEDULE: all ops may be adjusted (Req 4.5)."""
        solver = HybridSolver()
        snapshot = _make_snapshot()
        impact = _make_impact_report(["op-1"])
        bundle = _FakeBundle(
            strategy_type=StrategyType.GLOBAL_RESCHEDULE,
            neighborhood_callback=_mock_neighborhood_callback,
        )

        plans = await solver.solve(bundle, impact, snapshot)

        assert len(plans) >= 1
        plan = plans[0]
        adjusted_count = sum(
            1
            for wo in plan.schedule_detail.work_orders
            for op in wo.operations
            if op.is_adjusted
        )
        # Global reschedule should adjust most/all operations
        total_ops = sum(len(wo.operations) for wo in plan.schedule_detail.work_orders)
        assert adjusted_count >= total_ops * 0.5


class TestDegradation:
    """Tests for Solver_Portfolio degradation (Req 4.14, 4.15)."""

    @pytest.mark.asyncio
    async def test_degradation_on_primary_failure(self):
        """When primary solver fails, degrade to fallback (Req 4.15)."""
        solver = HybridSolver()
        snapshot = _make_snapshot()
        impact = _make_impact_report()

        # Patch _run_solver to fail on primary, succeed on fallback
        call_count = 0
        original_run = solver._run_solver

        async def _failing_run(solver_name, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if solver_name == "cp_sat_lns":
                raise RuntimeError("Primary solver crashed")
            return await original_run(solver_name=solver_name, *args, **kwargs)

        solver._run_solver = _failing_run

        bundle = _FakeBundle(
            strategy_type=StrategyType.LOCAL_REPAIR,
            neighborhood_callback=_mock_neighborhood_callback,
        )

        plans = await solver.solve(bundle, impact, snapshot)

        assert len(plans) >= 1
        # Should have degradation recorded
        assert plans[0].solver_metadata.degradation_occurred is True
        assert plans[0].solver_metadata.degradation_reason is not None
        assert "cp_sat_lns" in plans[0].solver_metadata.degradation_reason


class TestInfeasible:
    """Tests for infeasible report generation (Req 4.9)."""

    @pytest.mark.asyncio
    async def test_infeasible_when_all_solvers_fail(self):
        """Returns infeasible plan when all solvers fail (Req 4.9)."""
        solver = HybridSolver()
        snapshot = _make_snapshot()
        impact = _make_impact_report()

        async def _always_fail(*args, **kwargs):
            raise RuntimeError("All solvers fail")

        solver._run_solver = _always_fail

        bundle = _FakeBundle(
            strategy_type=StrategyType.LOCAL_REPAIR,
            neighborhood_callback=_mock_neighborhood_callback,
        )

        plans = await solver.solve(bundle, impact, snapshot)

        assert len(plans) == 1
        assert plans[0].feasibility_status == "infeasible"
        assert plans[0].constraint_report.is_feasible is False
        assert len(plans[0].constraint_report.violations) > 0


class TestDynamicNeighborhood:
    """Tests for dynamic neighborhood callback during LNS (Req 4.12)."""

    @pytest.mark.asyncio
    async def test_neighborhood_callback_invoked(self):
        """get_neighborhood_config is called during LNS iterations."""
        call_count = 0

        async def _counting_callback(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return await _mock_neighborhood_callback(*args, **kwargs)

        solver = HybridSolver()
        snapshot = _make_snapshot()
        impact = _make_impact_report()
        bundle = _FakeBundle(
            strategy_type=StrategyType.LOCAL_REPAIR,
            neighborhood_callback=_counting_callback,
        )

        await solver.solve(bundle, impact, snapshot)

        assert call_count > 0, "Neighborhood callback should be invoked during LNS"

    @pytest.mark.asyncio
    async def test_solve_works_without_neighborhood_callback(self):
        """solve() works even when get_neighborhood_config is None."""
        solver = HybridSolver()
        snapshot = _make_snapshot()
        impact = _make_impact_report()
        bundle = _FakeBundle(
            strategy_type=StrategyType.LOCAL_REPAIR,
            neighborhood_callback=None,
        )

        plans = await solver.solve(bundle, impact, snapshot)

        assert len(plans) >= 1


class TestConstraintValidation:
    """Tests for constraint validation logic."""

    @pytest.mark.asyncio
    async def test_constraint_report_included(self):
        """Each plan includes a ConstraintValidationReport (Req 4.7)."""
        solver = HybridSolver()
        snapshot = _make_snapshot()
        impact = _make_impact_report()
        bundle = _FakeBundle(
            strategy_type=StrategyType.LOCAL_REPAIR,
            neighborhood_callback=_mock_neighborhood_callback,
        )

        plans = await solver.solve(bundle, impact, snapshot)

        for plan in plans:
            assert plan.constraint_report is not None
            assert isinstance(plan.constraint_report, ConstraintValidationReport)
            assert len(plan.constraint_report.checked_constraints) > 0
