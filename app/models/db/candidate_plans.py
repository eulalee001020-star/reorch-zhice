"""CandidatePlan ORM model — solver-generated schedule alternatives."""

import uuid
from datetime import datetime

from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.db.mixins import TimestampMixin


class CandidatePlan(TimestampMixin, Base):
    __tablename__ = "candidate_plans"

    plan_id: Mapped[uuid.UUID] = mapped_column(
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
    baseline_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schedule_snapshots.snapshot_id", ondelete="RESTRICT"),
        nullable=True,
    )
    solver_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solver_runs.solver_run_id", ondelete="SET NULL"),
        nullable=True,
    )
    strategy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_detail: Mapped[dict] = mapped_column(JSONB, nullable=False)
    solver_chain: Mapped[dict] = mapped_column(JSONB, nullable=False)
    feasibility_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="feasible"
    )
    objective_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    kpi_vector: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    solver_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    constraint_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    gantt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_candidate_plans_incident_id", "incident_id"),
        Index("ix_candidate_plans_solver_run_id", "solver_run_id"),
        Index("ix_candidate_plans_baseline_snapshot_id", "baseline_snapshot_id"),
        Index("ix_candidate_plans_strategy_type", "strategy_type"),
    )
