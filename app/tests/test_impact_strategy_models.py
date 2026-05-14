"""Tests for Impact and Strategy Pydantic models.

Covers JSON serialization/deserialization round-trip consistency,
field defaults, validation errors, and nested structure integrity.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

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
from app.models.strategy import (
    NeighborhoodConfig,
    RepairPolicyConfig,
    RuleSelectionResult,
    SolverChainConfig,
    StrategyRecommendation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
_DUE = datetime(2025, 1, 20, 18, 0, 0, tzinfo=timezone.utc)


def _make_affected_op(**overrides) -> AffectedOperation:
    defaults = dict(
        operation_id="OP-001",
        work_order_id="WO-001",
        resource_id="CNC-001",
        is_direct=True,
        estimated_delay_minutes=30.0,
    )
    defaults.update(overrides)
    return AffectedOperation(**defaults)


def _make_affected_wo(**overrides) -> AffectedWorkOrder:
    defaults = dict(
        work_order_id="WO-001",
        product_name="Widget-A",
        due_date=_DUE,
        delivery_risk_level=DeliveryRiskLevel.WARNING,
        remaining_buffer_minutes=120.0,
        affected_operations=[_make_affected_op()],
    )
    defaults.update(overrides)
    return AffectedWorkOrder(**defaults)


def _make_impact_report(**overrides) -> ImpactReport:
    incident_id = overrides.pop("incident_id", uuid4())
    snapshot_id = overrides.pop("schedule_snapshot_id", uuid4())
    defaults = dict(
        incident_id=incident_id,
        schedule_snapshot_id=snapshot_id,
        analysis_reference_time=_NOW,
        affected_work_orders=[_make_affected_wo()],
        affected_operations=[_make_affected_op()],
        affected_resource_ids=["CNC-001"],
        delivery_risk_distribution={
            DeliveryRiskLevel.SAFE: 5,
            DeliveryRiskLevel.WARNING: 2,
            DeliveryRiskLevel.BREACH: 1,
        },
        estimated_total_delay_minutes=90.0,
    )
    defaults.update(overrides)
    return ImpactReport(**defaults)


# ---------------------------------------------------------------------------
# AffectedOperation
# ---------------------------------------------------------------------------


class TestAffectedOperation:
    def test_creation(self):
        op = _make_affected_op()
        assert op.operation_id == "OP-001"
        assert op.is_direct is True
        assert op.estimated_delay_minutes == 30.0

    def test_json_round_trip(self):
        op = _make_affected_op(is_direct=False, estimated_delay_minutes=15.5)
        restored = AffectedOperation.model_validate_json(op.model_dump_json())
        assert restored.model_dump() == op.model_dump()

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            AffectedOperation(
                operation_id="OP-001",
                # work_order_id missing
                resource_id="CNC-001",
                is_direct=True,
                estimated_delay_minutes=10.0,
            )


# ---------------------------------------------------------------------------
# AffectedWorkOrder
# ---------------------------------------------------------------------------


class TestAffectedWorkOrder:
    def test_creation_with_nested_ops(self):
        wo = _make_affected_wo()
        assert len(wo.affected_operations) == 1
        assert wo.delivery_risk_level == DeliveryRiskLevel.WARNING.value

    def test_empty_operations_default(self):
        wo = AffectedWorkOrder(
            work_order_id="WO-002",
            product_name="Widget-B",
            due_date=_DUE,
            delivery_risk_level=DeliveryRiskLevel.SAFE,
            remaining_buffer_minutes=200.0,
        )
        assert wo.affected_operations == []

    def test_json_round_trip(self):
        wo = _make_affected_wo()
        restored = AffectedWorkOrder.model_validate_json(wo.model_dump_json())
        assert restored.model_dump() == wo.model_dump()


# ---------------------------------------------------------------------------
# ImpactReport
# ---------------------------------------------------------------------------


class TestImpactReport:
    def test_full_creation(self):
        report = _make_impact_report()
        assert len(report.affected_work_orders) == 1
        assert len(report.affected_operations) == 1
        assert report.estimated_total_delay_minutes == 90.0
        assert report.is_degraded_mode is False
        assert report.severity_upgraded is False
        assert report.upgraded_severity is None

    def test_degraded_mode(self):
        report = _make_impact_report(
            is_degraded_mode=True,
            degraded_reason="ScheduleSnapshot unavailable",
        )
        assert report.is_degraded_mode is True
        assert report.degraded_reason == "ScheduleSnapshot unavailable"

    def test_severity_upgrade(self):
        report = _make_impact_report(
            severity_upgraded=True,
            upgraded_severity=IncidentSeverity.P1_CRITICAL,
        )
        assert report.severity_upgraded is True
        assert report.upgraded_severity == IncidentSeverity.P1_CRITICAL.value

    def test_json_round_trip(self):
        report = _make_impact_report(
            severity_upgraded=True,
            upgraded_severity=IncidentSeverity.P1_CRITICAL,
        )
        json_str = report.model_dump_json()
        restored = ImpactReport.model_validate_json(json_str)
        assert restored.model_dump() == report.model_dump()

    def test_delivery_risk_distribution_round_trip(self):
        """Ensure dict[DeliveryRiskLevel, int] survives JSON round-trip."""
        report = _make_impact_report()
        json_str = report.model_dump_json()
        restored = ImpactReport.model_validate_json(json_str)
        assert restored.delivery_risk_distribution == report.delivery_risk_distribution

    def test_analysis_reference_time_matches_snapshot(self):
        """analysis_reference_time should be set to snapshot.captured_at."""
        ref_time = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        report = _make_impact_report(analysis_reference_time=ref_time)
        assert report.analysis_reference_time == ref_time

    def test_invalid_json_returns_descriptive_error(self):
        with pytest.raises(ValidationError) as exc_info:
            ImpactReport.model_validate_json('{"incident_id": "not-a-uuid"}')
        errors = exc_info.value.errors()
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# StrategyRecommendation
# ---------------------------------------------------------------------------


class TestStrategyRecommendation:
    def test_creation(self):
        rec = StrategyRecommendation(
            strategy_type=StrategyType.LOCAL_REPAIR,
            confidence=0.85,
            key_factors=["low impact scope", "no breach risk"],
            historical_case_ids=[uuid4()],
            reasoning="Affected scope is small, local repair sufficient.",
        )
        assert rec.strategy_type == StrategyType.LOCAL_REPAIR.value
        assert rec.confidence == 0.85
        assert rec.alternative_strategy is None

    def test_low_confidence_with_alternative(self):
        rec = StrategyRecommendation(
            strategy_type=StrategyType.LOCAL_REPAIR,
            confidence=0.4,
            key_factors=["borderline scope"],
            reasoning="Uncertain, providing alternative.",
            alternative_strategy=StrategyType.GLOBAL_RESCHEDULE,
        )
        assert rec.alternative_strategy == StrategyType.GLOBAL_RESCHEDULE.value

    def test_json_round_trip(self):
        case_ids = [uuid4(), uuid4()]
        rec = StrategyRecommendation(
            strategy_type=StrategyType.GLOBAL_RESCHEDULE,
            confidence=0.72,
            key_factors=["breach risk", "high impact"],
            historical_case_ids=case_ids,
            alternative_strategy=StrategyType.LOCAL_REPAIR,
            reasoning="Breach risk detected.",
        )
        restored = StrategyRecommendation.model_validate_json(rec.model_dump_json())
        assert restored.model_dump() == rec.model_dump()

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            StrategyRecommendation(
                strategy_type=StrategyType.LOCAL_REPAIR,
                confidence=0.5,
                # reasoning missing
            )


# ---------------------------------------------------------------------------
# RuleSelectionResult
# ---------------------------------------------------------------------------


class TestRuleSelectionResult:
    def test_creation(self):
        result = RuleSelectionResult(
            rule_name="EDD",
            rule_category=RuleCategory.DUE_DATE_PRIORITY,
            applicable_stage=RuleApplicableStage.INITIAL_SOLUTION,
            confidence=0.9,
            reasoning="Due date pressure is high.",
        )
        assert result.rule_category == RuleCategory.DUE_DATE_PRIORITY.value
        assert result.alternative_rule is None

    def test_low_confidence_with_alternative(self):
        result = RuleSelectionResult(
            rule_name="SPT",
            rule_category=RuleCategory.SHORTEST_PROCESSING_TIME,
            applicable_stage=RuleApplicableStage.REPAIR,
            confidence=0.3,
            reasoning="Uncertain.",
            alternative_rule="MST",
        )
        assert result.alternative_rule == "MST"

    def test_json_round_trip(self):
        result = RuleSelectionResult(
            rule_name="BRP",
            rule_category=RuleCategory.BOTTLENECK_RESOURCE_PRIORITY,
            applicable_stage=RuleApplicableStage.REPAIR,
            confidence=0.75,
            reasoning="Bottleneck device affected.",
        )
        restored = RuleSelectionResult.model_validate_json(result.model_dump_json())
        assert restored.model_dump() == result.model_dump()


# ---------------------------------------------------------------------------
# NeighborhoodConfig
# ---------------------------------------------------------------------------


class TestNeighborhoodConfig:
    def test_creation(self):
        cfg = NeighborhoodConfig(
            neighborhood_type=NeighborhoodType.CRITICAL_PATH,
            target_operation_ids=["OP-001", "OP-002"],
            intensity=0.7,
            estimated_impact_scope=5,
            reasoning="Critical path affected.",
        )
        assert cfg.neighborhood_type == NeighborhoodType.CRITICAL_PATH.value
        assert len(cfg.target_operation_ids) == 2

    def test_empty_targets_default(self):
        cfg = NeighborhoodConfig(
            neighborhood_type=NeighborhoodType.BOTTLENECK_DEVICE,
            intensity=0.5,
            estimated_impact_scope=3,
            reasoning="Bottleneck device neighborhood.",
        )
        assert cfg.target_operation_ids == []

    def test_json_round_trip(self):
        cfg = NeighborhoodConfig(
            neighborhood_type=NeighborhoodType.DELAYED_ORDER,
            target_operation_ids=["OP-010"],
            intensity=0.9,
            estimated_impact_scope=10,
            reasoning="Delayed order neighborhood.",
        )
        restored = NeighborhoodConfig.model_validate_json(cfg.model_dump_json())
        assert restored.model_dump() == cfg.model_dump()


# ---------------------------------------------------------------------------
# RepairPolicyConfig
# ---------------------------------------------------------------------------


class TestRepairPolicyConfig:
    def test_creation(self):
        cfg = RepairPolicyConfig(
            repair_mode=RepairMode.BALANCED,
            frozen_operation_ids=["OP-100", "OP-101"],
            allowed_perturbation_scope=["OP-001", "OP-002"],
            search_time_budget_seconds=30.0,
            candidate_count_target=3,
            fallback_condition="no_improvement_10_iterations",
            fallback_mode="conservative",
        )
        assert cfg.repair_mode == RepairMode.BALANCED.value
        assert cfg.candidate_count_target == 3

    def test_empty_lists_default(self):
        cfg = RepairPolicyConfig(
            repair_mode=RepairMode.CONSERVATIVE,
            search_time_budget_seconds=10.0,
            candidate_count_target=1,
            fallback_condition="timeout",
            fallback_mode="return_best",
        )
        assert cfg.frozen_operation_ids == []
        assert cfg.allowed_perturbation_scope == []

    def test_json_round_trip(self):
        cfg = RepairPolicyConfig(
            repair_mode=RepairMode.AGGRESSIVE,
            frozen_operation_ids=["OP-200"],
            allowed_perturbation_scope=["OP-001", "OP-002", "OP-003"],
            search_time_budget_seconds=60.0,
            candidate_count_target=5,
            fallback_condition="no_feasible_solution",
            fallback_mode="degrade_to_heuristic",
        )
        restored = RepairPolicyConfig.model_validate_json(cfg.model_dump_json())
        assert restored.model_dump() == cfg.model_dump()


# ---------------------------------------------------------------------------
# SolverChainConfig
# ---------------------------------------------------------------------------


class TestSolverChainConfig:
    def test_creation(self):
        cfg = SolverChainConfig(
            primary_solver="cp_sat",
            fallback_solver="greedy_heuristic",
            fallback_rule="earliest_due_date",
            degradation_trigger="timeout_or_infeasible",
            max_timeout_seconds=60.0,
        )
        assert cfg.primary_solver == "cp_sat"
        assert cfg.max_timeout_seconds == 60.0

    def test_json_round_trip(self):
        cfg = SolverChainConfig(
            primary_solver="cp_sat",
            fallback_solver="tabu_search",
            fallback_rule="spt",
            degradation_trigger="3_consecutive_failures",
            max_timeout_seconds=120.0,
        )
        restored = SolverChainConfig.model_validate_json(cfg.model_dump_json())
        assert restored.model_dump() == cfg.model_dump()
