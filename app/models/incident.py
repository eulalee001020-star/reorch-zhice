"""Incident Pydantic models for the ReOrch system.

Defines the IncidentCreateRequest (intake payload) and Incident
(full domain object with globally unique ID, deduplication tracking,
and lifecycle metadata).
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.enums import (
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ReportSource,
)


class IncidentCreateRequest(ReOrchModel):
    """Payload accepted by Anomaly_Intake_Center to create an Incident."""

    incident_type: IncidentType
    external_event_id: str | None = None
    occurred_at: datetime
    workshop_id: str | None = None
    resource_id: str
    report_source: ReportSource
    source_system: str | None = None
    description: str | None = None
    idempotency_key: str | None = None
    raw_payload: dict | None = None


class Incident(ReOrchModel):
    """Full Incident domain object with lifecycle metadata."""

    incident_id: UUID = Field(default_factory=uuid4)
    incident_type: IncidentType
    external_event_id: str | None = None
    occurred_at: datetime
    workshop_id: str | None = None
    resource_id: str
    report_source: ReportSource
    source_system: str | None = None
    severity: IncidentSeverity
    status: IncidentStatus = IncidentStatus.PENDING_ANALYSIS
    description: str | None = None
    deduplicated_from: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    idempotency_key: str | None = None
    created_by: str | None = None
    raw_payload: dict | None = None
