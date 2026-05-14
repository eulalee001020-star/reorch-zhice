"""ExecutionResult ORM model — actual vs planned metrics after writeback."""

import uuid

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.db.mixins import TimestampMixin


class ExecutionResult(TimestampMixin, Base):
    __tablename__ = "execution_results"

    execution_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    decision_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("decision_records.decision_record_id", ondelete="CASCADE"),
        nullable=False,
    )
    actual_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index("ix_execution_results_decision_record_id", "decision_record_id"),
    )
