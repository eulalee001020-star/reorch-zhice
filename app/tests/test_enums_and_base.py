"""Tests for shared enums and base Pydantic model."""

from uuid import UUID, uuid4

import pytest

from app.models.enums import (
    ConfirmAction,
    DeliveryRiskLevel,
    GoalMode,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    NeighborhoodType,
    RepairMode,
    ReportSource,
    RuleApplicableStage,
    RuleCategory,
    StrategyType,
    WritebackStatus,
)
from app.models.base import ReOrchModel


# ---------------------------------------------------------------------------
# Enum value tests
# ---------------------------------------------------------------------------

class TestIncidentSeverity:
    def test_values(self):
        assert IncidentSeverity.P1_CRITICAL.value == "P1-Critical"
        assert IncidentSeverity.P2_HIGH.value == "P2-High"
        assert IncidentSeverity.P3_MEDIUM.value == "P3-Medium"
        assert IncidentSeverity.P4_LOW.value == "P4-Low"

    def test_member_count(self):
        assert len(IncidentSeverity) == 4

    def test_str_enum(self):
        assert isinstance(IncidentSeverity.P1_CRITICAL, str)


class TestIncidentType:
    def test_equipment_failure(self):
        assert IncidentType.EQUIPMENT_FAILURE.value == "equipment_failure"

    def test_member_count(self):
        assert len(IncidentType) == 1


class TestIncidentStatus:
    def test_all_statuses(self):
        expected = {
            "pending_analysis",
            "analyzing",
            "pending_confirmation",
            "confirmed",
            "executing",
            "closed",
        }
        assert {s.value for s in IncidentStatus} == expected

    def test_member_count(self):
        assert len(IncidentStatus) == 6


class TestDeliveryRiskLevel:
    def test_values(self):
        assert DeliveryRiskLevel.SAFE.value == "safe"
        assert DeliveryRiskLevel.WARNING.value == "warning"
        assert DeliveryRiskLevel.BREACH.value == "breach"


class TestStrategyType:
    def test_values(self):
        assert StrategyType.WAIT_AND_REPAIR.value == "wait_and_repair"
        assert StrategyType.LOCAL_REPAIR.value == "local_repair"
        assert StrategyType.GLOBAL_RESCHEDULE.value == "global_reschedule"


class TestRepairMode:
    def test_values(self):
        assert RepairMode.CONSERVATIVE.value == "conservative"
        assert RepairMode.BALANCED.value == "balanced"
        assert RepairMode.AGGRESSIVE.value == "aggressive"


class TestRuleCategory:
    def test_member_count(self):
        assert len(RuleCategory) == 5

    def test_values(self):
        expected = {
            "due_date_priority",
            "shortest_processing_time",
            "minimum_slack_time",
            "bottleneck_resource_priority",
            "critical_order_priority",
        }
        assert {r.value for r in RuleCategory} == expected


class TestNeighborhoodType:
    def test_member_count(self):
        assert len(NeighborhoodType) == 6

    def test_values(self):
        expected = {
            "critical_path",
            "bottleneck_device",
            "delayed_order",
            "same_device_swap",
            "operation_insert",
            "device_reassignment",
        }
        assert {n.value for n in NeighborhoodType} == expected


class TestConfirmAction:
    def test_values(self):
        assert ConfirmAction.ACCEPT.value == "accept"
        assert ConfirmAction.ACCEPT_WITH_ADJUSTMENT.value == "accept_with_adjustment"
        assert ConfirmAction.REJECT_AND_RESELECT.value == "reject_and_reselect"


class TestWritebackStatus:
    def test_values(self):
        assert WritebackStatus.SUCCESS.value == "success"
        assert WritebackStatus.PARTIAL_SUCCESS.value == "partial_success"
        assert WritebackStatus.FAILED.value == "failed"


class TestGoalMode:
    def test_member_count(self):
        assert len(GoalMode) == 5

    def test_balanced_default(self):
        assert GoalMode.BALANCED.value == "balanced"

    def test_values(self):
        expected = {
            "delivery_priority",
            "stability_priority",
            "bottleneck_priority",
            "cost_priority",
            "balanced",
        }
        assert {g.value for g in GoalMode} == expected


class TestRuleApplicableStage:
    def test_values(self):
        assert RuleApplicableStage.INITIAL_SOLUTION.value == "initial_solution"
        assert RuleApplicableStage.REPAIR.value == "repair"


class TestReportSource:
    def test_values(self):
        assert ReportSource.MES.value == "MES"
        assert ReportSource.IOT.value == "IoT"
        assert ReportSource.MANUAL.value == "manual"


# ---------------------------------------------------------------------------
# Base model tests
# ---------------------------------------------------------------------------

class TestReOrchModel:
    def test_from_attributes(self):
        """Model should support construction from ORM-like objects."""

        class DummyORM:
            name = "test"
            value = 42

        class MyModel(ReOrchModel):
            name: str
            value: int

        obj = MyModel.model_validate(DummyORM())
        assert obj.name == "test"
        assert obj.value == 42

    def test_use_enum_values(self):
        """Enum fields should serialize to their string values."""

        class MyModel(ReOrchModel):
            severity: IncidentSeverity

        obj = MyModel(severity=IncidentSeverity.P1_CRITICAL)
        dumped = obj.model_dump()
        assert dumped["severity"] == "P1-Critical"

    def test_str_strip_whitespace(self):
        class MyModel(ReOrchModel):
            name: str

        obj = MyModel(name="  hello  ")
        assert obj.name == "hello"

    def test_json_round_trip(self):
        class MyModel(ReOrchModel):
            id: UUID
            status: IncidentStatus

        original = MyModel(id=uuid4(), status=IncidentStatus.ANALYZING)
        json_str = original.model_dump_json()
        restored = MyModel.model_validate_json(json_str)
        assert restored.id == original.id
        assert restored.status == original.status
