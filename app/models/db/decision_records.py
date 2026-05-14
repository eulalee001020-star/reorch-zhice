"""DecisionRecord ORM model — full audit trail for each decision."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.db.mixins import TimestampMixin


class DecisionRecord(TimestampMixin, Base):
    __tablename__ = "decision_records"

    decision_record_id: Mapped[uuid.UUID] = mapped_column(
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
    original_recommended_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_plans.plan_id", ondelete="SET NULL"),
        nullable=True,
    )
    confirmed_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_plans.plan_id", ondelete="SET NULL"),
        nullable=True,
    )
    derived_from_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_plans.plan_id", ondelete="SET NULL"),
        nullable=True,
    )
    is_manual_adjusted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Structured input/output snapshots for audit
    plan_selection_input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    plan_selection_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Strategy module versions at decision time
    module_versions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_decision_records_incident_id", "incident_id"),
        Index("ix_decision_records_confirmed_at", "confirmed_at"),
    )
