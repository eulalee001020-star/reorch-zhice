"""Incident Pydantic models for the ReOrch system.

Defines the IncidentCreateRequest (intake payload) and Incident
(full domain object with globally unique ID, deduplication tracking,
and lifecycle metadata).
"""

from datetime import datetime, timezone
from typing import Optional
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
    external_event_id: Optional[str] = None
    occurred_at: datetime
    workshop_id: Optional[str] = None
    resource_id: str
    report_source: ReportSource
    source_system: Optional[str] = None
    description: Optional[str] = None
    idempotency_key: Optional[str] = None
    raw_payload: Optional[dict] = None


class Incident(ReOrchModel):
    """Full Incident domain object with lifecycle metadata."""

    incident_id: UUID = Field(default_factory=uuid4)
    incident_type: IncidentType
    external_event_id: Optional[str] = None
    occurred_at: datetime
    workshop_id: Optional[str] = None
    resource_id: str
    report_source: ReportSource
    source_system: Optional[str] = None
    severity: IncidentSeverity
    status: IncidentStatus = IncidentStatus.PENDING_ANALYSIS
    description: Optional[str] = None
    deduplicated_from: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    idempotency_key: Optional[str] = None
    created_by: Optional[str] = None
    raw_payload: Optional[dict] = None
