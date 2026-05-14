"""Incident ORM model with state-machine CHECK constraint."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.db.mixins import TimestampMixin

# Valid incident status values
_VALID_STATUSES = (
    "pending_analysis",
    "analyzing",
    "pending_confirmation",
    "confirmed",
    "executing",
    "closed",
)

_VALID_SEVERITIES = ("P1-Critical", "P2-High", "P3-Medium", "P4-Low")


class Incident(TimestampMixin, Base):
    """Core incident table — tracks anomaly events through their lifecycle."""

    __tablename__ = "incidents"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    incident_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    workshop_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    report_source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_analysis"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    deduplicated_from: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True, default=list
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Optimistic locking
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint(
            f"status IN {_VALID_STATUSES!r}",
            name="ck_incident_status_valid",
        ),
        CheckConstraint(
            f"severity IN {_VALID_SEVERITIES!r}",
            name="ck_incident_severity_valid",
        ),
        Index("ix_incidents_status", "status"),
        Index("ix_incidents_severity", "severity"),
        Index("ix_incidents_occurred_at", "occurred_at"),
        Index("ix_incidents_resource_id", "resource_id"),
        Index("ix_incidents_workshop_status", "workshop_id", "status"),
        Index("ix_incidents_external_event_id", "external_event_id"),
        UniqueConstraint("idempotency_key", name="uq_incidents_idempotency_key"),
    )
