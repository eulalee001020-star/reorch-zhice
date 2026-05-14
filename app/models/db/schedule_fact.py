"""Structured schedule fact tables for snapshots, solver plans, and recommendations."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.db.mixins import TimestampMixin


class ScheduleSnapshotOperation(Base):
    """Flattened operation intervals for immutable schedule snapshots."""

    __tablename__ = "schedule_snapshot_operations"

    snapshot_operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schedule_snapshots.snapshot_id", ondelete="CASCADE"),
        nullable=False,
    )
    operation_pk: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operations.operation_pk", ondelete="SET NULL"), nullable=True
    )
    work_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="planned")
    is_frozen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    required_capabilities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("end_time > start_time", name="ck_snapshot_operations_time_valid"),
        UniqueConstraint("snapshot_id", "operation_id", name="uq_snapshot_operations_snapshot_operation"),
        Index("ix_snapshot_ops_resource_time", "snapshot_id", "resource_id", "start_time", "end_time"),
        Index("ix_snapshot_ops_work_order", "snapshot_id", "work_order_id"),
    )


class SolverRun(TimestampMixin, Base):
    """A concrete solver execution against one incident and baseline snapshot."""

    __tablename__ = "solver_runs"

    solver_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False
    )
    baseline_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schedule_snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False
    )
    strategy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    solver_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    search_budget_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    objective_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("search_budget_seconds > 0", name="ck_solver_runs_budget_positive"),
        Index("ix_solver_runs_incident_status", "incident_id", "status"),
        Index("ix_solver_runs_snapshot", "baseline_snapshot_id"),
    )


class CandidatePlanOperation(Base):
    """Structured operation intervals for a candidate plan."""

    __tablename__ = "candidate_plan_operations"

    plan_operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_plans.plan_id", ondelete="CASCADE"), nullable=False
    )
    operation_pk: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operations.operation_pk", ondelete="SET NULL"), nullable=True
    )
    operation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    work_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    original_resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    planned_resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    original_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    planned_end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_adjusted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    adjustment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("planned_end_time > planned_start_time", name="ck_plan_operations_time_valid"),
        UniqueConstraint("plan_id", "operation_id", name="uq_plan_operations_plan_operation"),
        Index("ix_plan_ops_resource_time", "plan_id", "planned_resource_id", "planned_start_time", "planned_end_time"),
        Index("ix_plan_ops_work_order", "plan_id", "work_order_id"),
    )


class PlanRecommendation(TimestampMixin, Base):
    """Persisted recommendation output for one incident."""

    __tablename__ = "plan_recommendations"

    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False
    )
    recommended_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_plans.plan_id", ondelete="CASCADE"), nullable=False
    )
    top_scored_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_plans.plan_id", ondelete="SET NULL"), nullable=True
    )
    goal_mode: Mapped[str] = mapped_column(String(64), nullable=False, default="balanced")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    recommendation_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_plan_recommendations_confidence"),
        Index("ix_plan_recommendations_incident_active", "incident_id", "is_active"),
    )


class WritebackJob(TimestampMixin, Base):
    """MES/APS writeback job and retry state."""

    __tablename__ = "writeback_jobs"

    writeback_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False
    )
    decision_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decision_records.decision_record_id", ondelete="SET NULL"), nullable=True
    )
    confirmed_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_plans.plan_id", ondelete="RESTRICT"), nullable=False
    )
    target_system: Mapped[str] = mapped_column(String(64), nullable=False, default="MES")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("retry_count >= 0", name="ck_writeback_jobs_retry_nonnegative"),
        Index("ix_writeback_jobs_status_retry", "status", "next_retry_at"),
        Index("ix_writeback_jobs_incident", "incident_id"),
    )

