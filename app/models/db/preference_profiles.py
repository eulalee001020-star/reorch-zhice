"""PreferenceProfile ORM model — per-planner strategy preferences."""

import uuid

from sqlalchemy import Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.db.mixins import TimestampMixin


class PreferenceProfile(TimestampMixin, Base):
    __tablename__ = "preference_profiles"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    planner_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_preference_profiles_planner_id", "planner_id"),)
