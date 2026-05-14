"""Tests for SolverPolicyOrchestrator and SolverPortfolio.

Validates task 6.4 requirements:
- build_solver_policy() assembles a unified SolverPolicyBundle
- Hybrid_Solver consumes a single control object
- Neighborhood_Selector is available as a runtime callback
- Layer 2 version info is recorded
- SolverPortfolio returns correct chain configs per strategy
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.case import CaseRecord, PreferenceProfile
from app.models.enums import (
    DeliveryRiskLevel,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ReportSource,
    RepairMode,
    StrategyType,
)
from app.models.impact import AffectedOperation, ImpactReport
from app.models.incident import Incident
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    SolverChain,
    SolverMetadata,
)
from app.models.schedule import ScheduleDetail
from app.models.strategy import (
    NeighborhoodConfig,
    RepairPolicyConfig,
    RuleSelectionResult,
    SolverChainConfig,
    StrategyRecommendation,
)
from app.services.solver_policy_orchestrator import (
    MODULE_VERSION as ORCH_VERSION,
    SolverPolicyBundle,
    SolverPolicyOrchestrator,
)
from app.services.solver_portfolio import (
    MODULE_VERSION as SP_VERSION,
    SolverPortfolio,
)


# ── Fixtures ────────────────────────────────────────────────────────

def _make_incident(severity: IncidentSeverity = IncidentSeverity.P2_HIGH) -> Incident:
    return Incident(
        incident_id=uuid4(),
        incident_type=IncidentType.EQUIPMENT_FAILURE,
        occurred_at=datetime.now(tz=timezone.utc),
        resource_id="machine-01",
        report_source=ReportSource.MES,
        severity=severity,
        status=IncidentStatus.ANALYZING,
    )


def _make_impact_report(incident_id=None) -> ImpactReport:
    iid = incident_id or uuid4()
    return ImpactReport(
        incident_id=iid,
        schedule_snapshot_id=uuid4(),
        analysis_reference_time=datetime.now(tz=timezone.utc),
        affected_operations=[
            AffectedOperation(
                operation_id="op-1",
                work_order_id="wo-1",
                resource_id="machine-01",
                is_direct=True,
                estimated_delay_minutes=30.0,
            ),
            AffectedOperation(
                operation_id="op-2",
                work_order_id="wo-1",
                resource_id="machine-02",
                is_direct=False,
                estimated_delay_minutes=15.0,
            ),
        ],
        affected_resource_ids=["machine-01", "machine-02"],
        delivery_risk_distribution={DeliveryRiskLevel.WARNING: 1},
        estimated_total_delay_minutes=45.0,
    )


def _make_strategy(
    strategy_type: StrategyType = StrategyType.LOCAL_REPAIR,
) -> StrategyRecommendation:
    return StrategyRecommendation(
        strategy_type=strategy_type,
        confidence=0.8,
        key_factors=["affected_ops_count", "no_breach_risk"],
        reasoning="Local repair recommended based on impact scope.",
    )


def _make_preference_profile() -> PreferenceProfile:
    return PreferenceProfile(
        planner_id="planner-01",
        strategy_preferences={},
        updated_at=datetime.now(tz=timezone.utc),
    )


def _make_candidate_plan() -> CandidatePlan:
    return CandidatePlan(
        plan_id=uuid4(),
        strategy_type="local_repair",
        schedule_detail=ScheduleDetail(
            work_orders=[], operations=[], resources=[],
        ),
        gantt_version="v1",
        solver_chain=SolverChain(
            strategy_type="local_repair",
            rule_selection="minimum_slack_time_rule",
            neighborhood_selection="critical_path",
            repair_policy="balanced",
            solver_name="cp_sat_lns",
            key_parameters={},
            search_budget_seconds=30.0,
            constraint_validation_result="feasible",
        ),
        feasibility_status="feasible",
        solver_metadata=SolverMetadata(
            solve_time_seconds=5.0,
            iteration_count=10,
            objective_trajectory=[100.0, 90.0, 85.0],
        ),
        constraint_report=ConstraintValidationReport(
            is_feasible=True, violations=[], checked_constraints=[],
        ),
    )


# ── SolverPortfolio tests ──────────────────────────────────────────


class TestSolverPortfolio:
    def test_get_chain_config_local_repair(self):
        portfolio = SolverPortfolio()
        config = portfolio.get_chain_config(StrategyType.LOCAL_REPAIR)
        assert isinstance(config, SolverChainConfig)
        assert config.primary_solver == "cp_sat_lns"
        assert config.fallback_solver == "greedy_local_repair"

    def test_get_chain_config_wait_and_repair(self):
        portfolio = SolverPortfolio()
        config = portfolio.get_chain_config(StrategyType.WAIT_AND_REPAIR)
        assert config.primary_solver == "cp_sat_time_shift"

    def test_get_chain_config_global_reschedule(self):
        portfolio = SolverPortfolio()
        config = portfolio.get_chain_config(StrategyType.GLOBAL_RESCHEDULE)
        assert config.primary_solver == "cp_sat_global"
        assert config.max_timeout_seconds == 90.0

    def test_get_chain_config_string_strategy(self):
        portfolio = SolverPortfolio()
        config = portfolio.get_chain_config("local_repair")
        assert config.primary_solver == "cp_sat_lns"

    def test_get_chain_config_unknown_strategy_falls_back(self):
        portfolio = SolverPortfolio()
        config = portfolio.get_chain_config("unknown_strategy")
        # Falls back to LOCAL_REPAIR
        assert config.primary_solver == "cp_sat_lns"

    def test_custom_config_override(self):
        custom = SolverChainConfig(
            primary_solver="custom_solver",
            fallback_solver="custom_fallback",
            fallback_rule="custom_rule",
            degradation_trigger="custom trigger",
            max_timeout_seconds=120.0,
        )
        portfolio = SolverPortfolio(
            custom_configs={StrategyType.LOCAL_REPAIR: custom},
        )
        config = portfolio.get_chain_config(StrategyType.LOCAL_REPAIR)
        assert config.primary_solver == "custom_solver"
        # Other strategies remain default
        wait_config = portfolio.get_chain_config(StrategyType.WAIT_AND_REPAIR)
        assert wait_config.primary_solver == "cp_sat_time_shift"


# ── SolverPolicyOrchestrator tests ─────────────────────────────────


class TestSolverPolicyOrchestrator:
    @pytest.fixture
    def orchestrator(self):
        return SolverPolicyOrchestrator()

    @pytest.mark.asyncio
    async def test_build_solver_policy_returns_bundle(self, orchestrator):
        incident = _make_incident()
        impact = _make_impact_report(incident.incident_id)
        strategy = _make_strategy()
        profile = _make_preference_profile()

        bundle = await orchestrator.build_solver_policy(
            incident=incident,
            impact_report=impact,
            strategy=strategy,
            preference_profile=profile,
            similar_cases=[],
        )

        assert isinstance(bundle, SolverPolicyBundle)

    @pytest.mark.asyncio
    async def test_bundle_contains_rules(self, orchestrator):
        incident = _make_incident()
        impact = _make_impact_report(incident.incident_id)
        strategy = _make_strategy()
        profile = _make_preference_profile()

        bundle = await orchestrator.build_solver_policy(
            incident=incident,
            impact_report=impact,
            strategy=strategy,
            preference_profile=profile,
            similar_cases=[],
        )

        assert isinstance(bundle.rules, list)
        assert len(bundle.rules) > 0
        assert all(isinstance(r, RuleSelectionResult) for r in bundle.rules)

    @pytest.mark.asyncio
    async def test_bundle_contains_repair_config(self, orchestrator):
        incident = _make_incident()
        impact = _make_impact_report(incident.incident_id)
        strategy = _make_strategy()
        profile = _make_preference_profile()

        bundle = await orchestrator.build_solver_policy(
            incident=incident,
            impact_report=impact,
            strategy=strategy,
            preference_profile=profile,
            similar_cases=[],
        )

        assert isinstance(bundle.repair_config, RepairPolicyConfig)
        assert bundle.repair_config.repair_mode == RepairMode.BALANCED

    @pytest.mark.asyncio
    async def test_bundle_contains_solver_chain_config(self, orchestrator):
        incident = _make_incident()
        impact = _make_impact_report(incident.incident_id)
        strategy = _make_strategy()
        profile = _make_preference_profile()

        bundle = await orchestrator.build_solver_policy(
            incident=incident,
            impact_report=impact,
            strategy=strategy,
            preference_profile=profile,
            similar_cases=[],
        )

        assert isinstance(bundle.solver_chain_config, SolverChainConfig)
        assert bundle.solver_chain_config.primary_solver == "cp_sat_lns"

    @pytest.mark.asyncio
    async def test_bundle_has_neighborhood_callback(self, orchestrator):
        """Hybrid_Solver can dynamically request neighborhood configs."""
        incident = _make_incident()
        impact = _make_impact_report(incident.incident_id)
        strategy = _make_strategy()
        profile = _make_preference_profile()

        bundle = await orchestrator.build_solver_policy(
            incident=incident,
            impact_report=impact,
            strategy=strategy,
            preference_profile=profile,
            similar_cases=[],
        )

        assert bundle.get_neighborhood_config is not None
        assert callable(bundle.get_neighborhood_config)

        # Actually invoke the callback
        plan = _make_candidate_plan()
        neighborhoods = await bundle.get_neighborhood_config(
            plan,
            ["op-1", "op-2"],
            0,
            25.0,
            strategy,
            0.5,
        )
        assert isinstance(neighborhoods, list)
        assert all(isinstance(n, NeighborhoodConfig) for n in neighborhoods)

    @pytest.mark.asyncio
    async def test_bundle_records_version_info(self, orchestrator):
        incident = _make_incident()
        impact = _make_impact_report(incident.incident_id)
        strategy = _make_strategy()
        profile = _make_preference_profile()

        bundle = await orchestrator.build_solver_policy(
            incident=incident,
            impact_report=impact,
            strategy=strategy,
            preference_profile=profile,
            similar_cases=[],
        )

        vi = bundle.version_info
        assert vi.rule_selector_version == "1.0.0"
        assert vi.neighborhood_selector_version == "1.0.0"
        assert vi.repair_policy_advisor_version == "1.0.0"
        assert vi.solver_portfolio_version == "1.0.0"
        assert vi.orchestrator_version == ORCH_VERSION
        assert vi.built_at is not None

    @pytest.mark.asyncio
    async def test_bundle_strategy_matches_input(self, orchestrator):
        incident = _make_incident()
        impact = _make_impact_report(incident.incident_id)
        strategy = _make_strategy(StrategyType.GLOBAL_RESCHEDULE)
        profile = _make_preference_profile()

        bundle = await orchestrator.build_solver_policy(
            incident=incident,
            impact_report=impact,
            strategy=strategy,
            preference_profile=profile,
            similar_cases=[],
        )

        assert bundle.strategy.strategy_type == StrategyType.GLOBAL_RESCHEDULE
        assert bundle.solver_chain_config.primary_solver == "cp_sat_global"
        assert bundle.repair_config.repair_mode == RepairMode.AGGRESSIVE

    @pytest.mark.asyncio
    async def test_wait_and_repair_bundle(self, orchestrator):
        incident = _make_incident(IncidentSeverity.P3_MEDIUM)
        impact = _make_impact_report(incident.incident_id)
        strategy = _make_strategy(StrategyType.WAIT_AND_REPAIR)
        profile = _make_preference_profile()

        bundle = await orchestrator.build_solver_policy(
            incident=incident,
            impact_report=impact,
            strategy=strategy,
            preference_profile=profile,
            similar_cases=[],
        )

        assert bundle.repair_config.repair_mode == RepairMode.CONSERVATIVE
        assert bundle.solver_chain_config.primary_solver == "cp_sat_time_shift"

    @pytest.mark.asyncio
    async def test_bundle_serialization_excludes_callback(self, orchestrator):
        """get_neighborhood_config is excluded from JSON serialization."""
        incident = _make_incident()
        impact = _make_impact_report(incident.incident_id)
        strategy = _make_strategy()
        profile = _make_preference_profile()

        bundle = await orchestrator.build_solver_policy(
            incident=incident,
            impact_report=impact,
            strategy=strategy,
            preference_profile=profile,
            similar_cases=[],
        )

        data = bundle.model_dump()
        assert "get_neighborhood_config" not in data
        # But the callback is still usable
        assert bundle.get_neighborhood_config is not None
