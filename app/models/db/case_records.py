"""CaseRecord ORM model — decision cases with pgvector embedding."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from pgvector.sqlalchemy import Vector

from app.core.database import Base
from app.models.db.mixins import TimestampMixin


class CaseRecord(TimestampMixin, Base):
    __tablename__ = "case_records"

    case_id: Mapped[uuid.UUID] = mapped_column(
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
    decision_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("decision_records.decision_record_id", ondelete="CASCADE"),
        nullable=False,
    )
    incident_features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    strategy_used: Mapped[str] = mapped_column(String(64), nullable=False)
    was_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    execution_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # pgvector embedding for similarity search
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(768), nullable=True
    )

    __table_args__ = (
        Index("ix_case_records_incident_id", "incident_id"),
        Index("ix_case_records_strategy_used", "strategy_used"),
    )
