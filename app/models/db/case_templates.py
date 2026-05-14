"""CaseTemplate ORM model — reusable decision templates."""

import uuid

from sqlalchemy import Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.db.mixins import TimestampMixin


class CaseTemplate(TimestampMixin, Base):
    __tablename__ = "case_templates"

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    applicable_incident_type: Mapped[str] = mapped_column(String(64), nullable=False)
    recommended_strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft"
    )

    __table_args__ = (
        Index("ix_case_templates_status", "status"),
        Index("ix_case_templates_incident_type", "applicable_incident_type"),
    )
