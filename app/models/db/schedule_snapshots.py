"""ScheduleSnapshot ORM model — immutable schedule state at anomaly time."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.db.mixins import TimestampMixin


class ScheduleSnapshot(TimestampMixin, Base):
    __tablename__ = "schedule_snapshots"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    workshop_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="1.0", server_default="1.0"
    )
    snapshot_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    parent_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schedule_snapshots.snapshot_id", ondelete="SET NULL"),
        nullable=True,
    )
    baseline_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schedule_snapshots.snapshot_id", ondelete="SET NULL"),
        nullable=True,
    )
    import_batch_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snapshot_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snapshot_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_immutable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_schedule_snapshots_captured_at", "captured_at"),
        Index("ix_schedule_snapshots_workshop_id", "workshop_id"),
        Index("ix_schedule_snapshots_workshop_version", "workshop_id", "snapshot_version"),
        Index("ix_schedule_snapshots_import_batch_id", "import_batch_id"),
    )
