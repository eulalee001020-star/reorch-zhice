"""Shared enumerations for the ReOrch system.

All domain enums are defined here as the single source of truth,
referenced by Pydantic schemas, ORM models, and API layers.
"""

from enum import Enum


class IncidentSeverity(str, Enum):
    """Intake severity classification for anomaly events."""

    P1_CRITICAL = "P1-Critical"
    P2_HIGH = "P2-High"
    P3_MEDIUM = "P3-Medium"
    P4_LOW = "P4-Low"


class IncidentType(str, Enum):
    """Anomaly event types. MVP: equipment failure only."""

    EQUIPMENT_FAILURE = "equipment_failure"


class IncidentStatus(str, Enum):
    """Incident lifecycle states (state-machine enforced)."""

    PENDING_ANALYSIS = "pending_analysis"
    ANALYZING = "analyzing"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    EXECUTING = "executing"
    CLOSED = "closed"


class DeliveryRiskLevel(str, Enum):
    """Delivery risk assessment for affected work orders."""

    SAFE = "safe"
    WARNING = "warning"
    BREACH = "breach"


class StrategyType(str, Enum):
    """High-level re-scheduling strategy categories."""

    WAIT_AND_REPAIR = "wait_and_repair"
    LOCAL_REPAIR = "local_repair"
    GLOBAL_RESCHEDULE = "global_reschedule"


class RepairMode(str, Enum):
    """Repair intensity modes set by Repair_Policy_Advisor."""

    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class RuleCategory(str, Enum):
    """Scheduling rule categories used by Rule_Selector."""

    DUE_DATE_PRIORITY = "due_date_priority"
    SHORTEST_PROCESSING_TIME = "shortest_processing_time"
    MINIMUM_SLACK_TIME = "minimum_slack_time"
    BOTTLENECK_RESOURCE_PRIORITY = "bottleneck_resource_priority"
    CRITICAL_ORDER_PRIORITY = "critical_order_priority"


class NeighborhoodType(str, Enum):
    """LNS neighborhood operator types used by Neighborhood_Selector."""

    CRITICAL_PATH = "critical_path"
    BOTTLENECK_DEVICE = "bottleneck_device"
    DELAYED_ORDER = "delayed_order"
    SAME_DEVICE_SWAP = "same_device_swap"
    OPERATION_INSERT = "operation_insert"
    DEVICE_REASSIGNMENT = "device_reassignment"


class ConfirmAction(str, Enum):
    """Human confirmation actions in the Confirmation_Module."""

    ACCEPT = "accept"
    ACCEPT_WITH_ADJUSTMENT = "accept_with_adjustment"
    REJECT_AND_RESELECT = "reject_and_reselect"


class WritebackStatus(str, Enum):
    """MES writeback result status."""

    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


class GoalMode(str, Enum):
    """Business objective modes driving evaluation & recommendation."""

    DELIVERY_PRIORITY = "delivery_priority"
    STABILITY_PRIORITY = "stability_priority"
    BOTTLENECK_PRIORITY = "bottleneck_priority"
    COST_PRIORITY = "cost_priority"
    BALANCED = "balanced"  # default


class RuleApplicableStage(str, Enum):
    """Stage at which a scheduling rule is applied."""

    INITIAL_SOLUTION = "initial_solution"
    REPAIR = "repair"


class ReportSource(str, Enum):
    """Origin of an anomaly report."""

    MES = "MES"
    IOT = "IoT"
    MANUAL = "manual"
