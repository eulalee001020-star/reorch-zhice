"""Impact analysis Pydantic models for the ReOrch system.

Defines AffectedOperation, AffectedWorkOrder, and ImpactReport
used by the Impact_Analysis_Engine to describe the scope and
severity of an anomaly event.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.enums import DeliveryRiskLevel, IncidentSeverity


class AffectedOperation(ReOrchModel):
    """A single operation affected by an anomaly event."""

    operation_id: str
    work_order_id: str
    resource_id: str
    is_direct: bool  # True=directly affected, False=indirect (downstream)
    estimated_delay_minutes: float


class AffectedWorkOrder(ReOrchModel):
    """A work order affected by an anomaly, with delivery risk assessment."""

    work_order_id: str
    product_name: str
    due_date: datetime
    delivery_risk_level: DeliveryRiskLevel
    remaining_buffer_minutes: float
    affected_operations: list[AffectedOperation] = Field(default_factory=list)


class SeverityExplanation(ReOrchModel):
    """Auditable severity rationale combining intake and impact evidence."""

    initial_severity: IncidentSeverity
    effective_severity: IncidentSeverity
    source: str
    classification_rule: str
    factors: dict[str, Any] = Field(default_factory=dict)
    upgrade_applied: bool = False
    upgrade_rule: str | None = None
    upgrade_reason: str | None = None
    breach_work_order_count: int = 0


class ImpactReport(ReOrchModel):
    """Structured impact report produced by Impact_Analysis_Engine.

    ``analysis_reference_time`` is set to ``schedule_snapshot.captured_at``
    to ensure reproducible time-based calculations.
    """

    incident_id: UUID
    schedule_snapshot_id: UUID
    analysis_reference_time: datetime  # = schedule_snapshot.captured_at
    affected_work_orders: list[AffectedWorkOrder] = Field(default_factory=list)
    affected_operations: list[AffectedOperation] = Field(default_factory=list)
    affected_resource_ids: list[str] = Field(default_factory=list)
    delivery_risk_distribution: dict[DeliveryRiskLevel, int] = Field(
        default_factory=dict
    )
    estimated_total_delay_minutes: float = 0.0
    is_degraded_mode: bool = False
    degraded_reason: str | None = None
    severity_upgraded: bool = False
    upgraded_severity: IncidentSeverity | None = None
    severity_explanation: SeverityExplanation | None = None
