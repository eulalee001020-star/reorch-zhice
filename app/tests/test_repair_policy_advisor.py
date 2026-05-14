"""Unit tests for the Repair_Policy_Advisor service.

Covers:
- Wait-and-Repair → conservative + freeze unaffected + 10s + 1 candidate (Req 25.4)
- Local-Repair → balanced + affected & downstream scope + 30s + 3 candidates (Req 25.5)
- Global-Reschedule → aggressive + broader scope + 60s + 5 candidates (Req 25.6)
- P1 severity budget boost
- Fallback condition output (Req 25.7)
- Structured RepairPolicyConfig output (Req 25.8)
- Template overrides (Req 25.10)
- MODULE_VERSION constant (Req 22.3)
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.enums import (
    DeliveryRiskLevel,
    IncidentSeverity,
    RepairMode,
    StrategyType,
)
from app.models.impact import AffectedOperation, AffectedWorkOrder, ImpactReport
from app.models.strategy import RepairPolicyConfig, StrategyRecommendation
from app.services.repair_policy_advisor import (
    MODULE_VERSION,
    RepairPolicyAdvisor,
    RepairPolicyTemplate,
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


def _make_impact_report(
    affected_op_count: int = 4,
    direct_count: int = 2,
) -> ImpactReport:
    """Create an impact report with a mix of direct and indirect ops."""
    ops = [
        AffectedOperation(
            operation_id=f"op-{i}",
            work_order_id=f"wo-{i % 2}",
            resource_id="machine-01",
            is_direct=i < direct_count,
            estimated_delay_minutes=15.0,
        )
        for i in range(affected_op_count)
    ]
    wos = [
        AffectedWorkOrder(
            work_order_id=f"wo-{i}",
            product_name=f"Product-{i}",
            due_date=datetime(2025, 7, 20, tzinfo=timezone.utc),
            delivery_risk_level=DeliveryRiskLevel.WARNING,
            remaining_buffer_minutes=60.0,
            affected_operations=[o for o in ops if o.work_order_id == f"wo-{i}"],
        )
        for i in range(2)
    ]
    return ImpactReport(
        incident_id=uuid4(),
        schedule_snapshot_id=uuid4(),
        analysis_reference_time=datetime.now(tz=timezone.utc),
        affected_work_orders=wos,
        affected_operations=ops,
        affected_resource_ids=["machine-01"],
        delivery_risk_distribution={DeliveryRiskLevel.WARNING: 2},
        estimated_total_delay_minutes=60.0,
    )


# ── Tests ───────────────────────────────────────────────────────────


class TestModuleVersion:
    def test_module_version_exists(self):
        """MODULE_VERSION constant is defined (Req 22.3)."""
        assert MODULE_VERSION
        assert isinstance(MODULE_VERSION, str)


class TestWaitAndRepairPolicy:
    @pytest.mark.asyncio
    async def test_wait_produces_conservative_mode(self):
        """Wait-and-Repair → conservative repair mode (Req 25.4)."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.WAIT_AND_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P3_MEDIUM,
        )
        assert result.repair_mode == RepairMode.CONSERVATIVE

    @pytest.mark.asyncio
    async def test_wait_has_10s_budget(self):
        """Wait-and-Repair → 10s search budget (Req 25.4)."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.WAIT_AND_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P3_MEDIUM,
        )
        assert result.search_time_budget_seconds == 10.0

    @pytest.mark.asyncio
    async def test_wait_has_1_candidate_target(self):
        """Wait-and-Repair → 1 candidate target (Req 25.4)."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.WAIT_AND_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P3_MEDIUM,
        )
        assert result.candidate_count_target == 1

    @pytest.mark.asyncio
    async def test_wait_perturbation_scope_is_affected_only(self):
        """Wait-and-Repair → perturbation limited to affected ops."""
        advisor = RepairPolicyAdvisor()
        report = _make_impact_report(affected_op_count=3, direct_count=2)
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.WAIT_AND_REPAIR),
            impact_report=report,
            incident_severity=IncidentSeverity.P3_MEDIUM,
        )
        expected_ids = {op.operation_id for op in report.affected_operations}
        assert set(result.allowed_perturbation_scope) == expected_ids


class TestLocalRepairPolicy:
    @pytest.mark.asyncio
    async def test_local_produces_balanced_mode(self):
        """Local-Repair → balanced repair mode (Req 25.5)."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P2_HIGH,
        )
        assert result.repair_mode == RepairMode.BALANCED

    @pytest.mark.asyncio
    async def test_local_has_30s_budget(self):
        """Local-Repair → 30s search budget (Req 25.5)."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P2_HIGH,
        )
        assert result.search_time_budget_seconds == 30.0

    @pytest.mark.asyncio
    async def test_local_has_3_candidate_target(self):
        """Local-Repair → 3 candidate target (Req 25.5)."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P2_HIGH,
        )
        assert result.candidate_count_target == 3

    @pytest.mark.asyncio
    async def test_local_perturbation_includes_downstream(self):
        """Local-Repair → perturbation includes affected + downstream (Req 25.5)."""
        advisor = RepairPolicyAdvisor()
        report = _make_impact_report(affected_op_count=4, direct_count=2)
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            impact_report=report,
            incident_severity=IncidentSeverity.P2_HIGH,
        )
        # All affected ops (direct + indirect/downstream) should be in scope
        all_op_ids = {op.operation_id for op in report.affected_operations}
        assert set(result.allowed_perturbation_scope) == all_op_ids


class TestGlobalReschedulePolicy:
    @pytest.mark.asyncio
    async def test_global_produces_aggressive_mode(self):
        """Global-Reschedule → aggressive repair mode (Req 25.6)."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.GLOBAL_RESCHEDULE),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P1_CRITICAL,
        )
        assert result.repair_mode == RepairMode.AGGRESSIVE

    @pytest.mark.asyncio
    async def test_global_has_60s_base_budget(self):
        """Global-Reschedule → 60s base budget (boosted for P1) (Req 25.6)."""
        advisor = RepairPolicyAdvisor()
        # Use P3 to avoid P1 boost for this test
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.GLOBAL_RESCHEDULE),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P3_MEDIUM,
        )
        assert result.search_time_budget_seconds == 60.0

    @pytest.mark.asyncio
    async def test_global_has_5_candidate_target(self):
        """Global-Reschedule → 5 candidate target (Req 25.6)."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.GLOBAL_RESCHEDULE),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P3_MEDIUM,
        )
        assert result.candidate_count_target == 5

    @pytest.mark.asyncio
    async def test_global_no_frozen_ops(self):
        """Global-Reschedule → no frozen operations (Req 25.6)."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.GLOBAL_RESCHEDULE),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P3_MEDIUM,
        )
        assert result.frozen_operation_ids == []


class TestP1SeverityBoost:
    @pytest.mark.asyncio
    async def test_p1_boosts_wait_budget(self):
        """P1 severity multiplies Wait budget by 1.5."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.WAIT_AND_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P1_CRITICAL,
        )
        assert result.search_time_budget_seconds == 15.0  # 10 * 1.5

    @pytest.mark.asyncio
    async def test_p1_boosts_local_budget(self):
        """P1 severity multiplies Local budget by 1.5."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P1_CRITICAL,
        )
        assert result.search_time_budget_seconds == 45.0  # 30 * 1.5

    @pytest.mark.asyncio
    async def test_p1_boosts_global_budget(self):
        """P1 severity multiplies Global budget by 1.5."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.GLOBAL_RESCHEDULE),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P1_CRITICAL,
        )
        assert result.search_time_budget_seconds == 90.0  # 60 * 1.5

    @pytest.mark.asyncio
    async def test_non_p1_no_boost(self):
        """Non-P1 severity does not boost budget."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P4_LOW,
        )
        assert result.search_time_budget_seconds == 30.0


class TestFallbackCondition:
    @pytest.mark.asyncio
    async def test_all_strategies_have_fallback(self):
        """All strategies produce non-empty fallback fields (Req 25.7)."""
        advisor = RepairPolicyAdvisor()
        for st in StrategyType:
            result = await advisor.advise(
                strategy=_make_strategy(st),
                impact_report=_make_impact_report(),
                incident_severity=IncidentSeverity.P3_MEDIUM,
            )
            assert result.fallback_condition
            assert result.fallback_mode


class TestStructuredOutput:
    @pytest.mark.asyncio
    async def test_output_is_repair_policy_config(self):
        """Output is a valid RepairPolicyConfig (Req 25.8)."""
        advisor = RepairPolicyAdvisor()
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P2_HIGH,
        )
        assert isinstance(result, RepairPolicyConfig)
        assert result.repair_mode in (
            RepairMode.CONSERVATIVE,
            RepairMode.BALANCED,
            RepairMode.AGGRESSIVE,
        )
        assert isinstance(result.frozen_operation_ids, list)
        assert isinstance(result.allowed_perturbation_scope, list)
        assert result.search_time_budget_seconds > 0
        assert result.candidate_count_target >= 1


class TestTemplateOverrides:
    @pytest.mark.asyncio
    async def test_template_overrides_budget(self):
        """Template can override search budget (Req 25.10)."""
        template = RepairPolicyTemplate(
            search_time_budget_seconds=45.0,
        )
        advisor = RepairPolicyAdvisor(templates=[template])
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P2_HIGH,
        )
        assert result.search_time_budget_seconds == 45.0

    @pytest.mark.asyncio
    async def test_template_overrides_repair_mode(self):
        """Template can override repair mode (Req 25.10)."""
        template = RepairPolicyTemplate(
            repair_mode=RepairMode.AGGRESSIVE,
        )
        advisor = RepairPolicyAdvisor(templates=[template])
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.WAIT_AND_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P3_MEDIUM,
        )
        assert result.repair_mode == RepairMode.AGGRESSIVE

    @pytest.mark.asyncio
    async def test_template_overrides_candidate_count(self):
        """Template can override candidate count target (Req 25.10)."""
        template = RepairPolicyTemplate(
            candidate_count_target=10,
        )
        advisor = RepairPolicyAdvisor(templates=[template])
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P2_HIGH,
        )
        assert result.candidate_count_target == 10

    @pytest.mark.asyncio
    async def test_no_template_uses_defaults(self):
        """Without templates, defaults are used."""
        advisor = RepairPolicyAdvisor(templates=[])
        result = await advisor.advise(
            strategy=_make_strategy(StrategyType.LOCAL_REPAIR),
            impact_report=_make_impact_report(),
            incident_severity=IncidentSeverity.P2_HIGH,
        )
        assert result.repair_mode == RepairMode.BALANCED
        assert result.search_time_budget_seconds == 30.0
        assert result.candidate_count_target == 3
