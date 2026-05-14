"""ImpactReport ORM model — stores full impact analysis as JSONB."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.db.mixins import TimestampMixin


class ImpactReport(TimestampMixin, Base):
    __tablename__ = "impact_reports"

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.incident_id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schedule_snapshots.snapshot_id", ondelete="SET NULL"),
        nullable=True,
    )
    analysis_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="normal"
    )
    report_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    analysis_reference_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_impact_reports_incident_id", "incident_id"),
        Index("ix_impact_reports_snapshot_id", "snapshot_id"),
    )
