"""EntityVersion ORM model — generic version history for key entities."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.db.mixins import utcnow


class EntityVersion(Base):
    """Stores point-in-time snapshots of key entities for audit trail.

    Covers: Incident, DecisionRecord, CaseTemplate, PlanSelectionOutput,
    ScheduleDetail, SolverChain, etc.
    """

    __tablename__ = "entity_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_entity_versions_entity",
            "entity_type",
            "entity_id",
            "version_number",
            unique=True,
        ),
        Index("ix_entity_versions_created_at", "created_at"),
    )
