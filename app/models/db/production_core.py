"""Production master data ORM models for dynamic flexible job shop scheduling."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
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


class Workshop(TimestampMixin, Base):
    """A production workshop / scheduling scope."""

    __tablename__ = "workshops"

    workshop_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Singapore")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class Resource(TimestampMixin, Base):
    """Equipment, work center, operator group, or other scheduling resource."""

    __tablename__ = "resources"

    resource_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workshop_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("workshops.workshop_id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, default="equipment")
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    criticality: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_resources_capacity_positive"),
        UniqueConstraint("workshop_id", "resource_id", name="uq_resources_workshop_resource_id"),
        Index("ix_resources_workshop_id", "workshop_id"),
    )


class ResourceCapability(Base):
    """Capability tags supported by a resource."""

    __tablename__ = "resource_capabilities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    resource_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.resource_pk", ondelete="CASCADE"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
        UniqueConstraint("resource_pk", "capability", name="uq_resource_capability"),
        Index("ix_resource_capabilities_capability", "capability"),
    )


class ResourceCalendar(Base):
    """Availability or downtime windows for a resource."""

    __tablename__ = "resource_calendars"

    calendar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    resource_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.resource_pk", ondelete="CASCADE"), nullable=False
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    availability_type: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("window_end > window_start", name="ck_resource_calendars_window_valid"),
        CheckConstraint("capacity >= 0", name="ck_resource_calendars_capacity_nonnegative"),
        Index("ix_resource_calendars_resource_time", "resource_pk", "window_start", "window_end"),
    )


class WorkOrder(TimestampMixin, Base):
    """Production work order master data."""

    __tablename__ = "work_orders"

    work_order_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workshop_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("workshops.workshop_id", ondelete="CASCADE"), nullable=False
    )
    work_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_name: Mapped[str] = mapped_column(String(256), nullable=False)
    product_family: Mapped[str | None] = mapped_column(String(128), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=1)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="released")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_work_orders_quantity_positive"),
        UniqueConstraint("workshop_id", "work_order_id", name="uq_work_orders_workshop_order_id"),
        Index("ix_work_orders_workshop_due_date", "workshop_id", "due_date"),
        Index("ix_work_orders_status", "status"),
    )


class Operation(TimestampMixin, Base):
    """Routable operation within a work order."""

    __tablename__ = "operations"

    operation_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    work_order_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_orders.work_order_pk", ondelete="CASCADE"), nullable=False
    )
    operation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    standard_processing_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="planned")
    required_capabilities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "standard_processing_minutes IS NULL OR standard_processing_minutes > 0",
            name="ck_operations_processing_positive",
        ),
        UniqueConstraint("work_order_pk", "operation_id", name="uq_operations_work_order_operation_id"),
        Index("ix_operations_work_order_sequence", "work_order_pk", "sequence_no"),
    )


class OperationAlternativeResource(Base):
    """Eligible resource/mode for a flexible operation."""

    __tablename__ = "operation_alternative_resources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    operation_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operations.operation_pk", ondelete="CASCADE"), nullable=False
    )
    resource_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.resource_pk", ondelete="CASCADE"), nullable=False
    )
    processing_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    setup_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("processing_minutes > 0", name="ck_alt_resources_processing_positive"),
        CheckConstraint("setup_minutes >= 0", name="ck_alt_resources_setup_nonnegative"),
        UniqueConstraint("operation_pk", "resource_pk", name="uq_operation_alternative_resource"),
    )


class OperationPrecedenceEdge(Base):
    """Directed precedence relation between two operations."""

    __tablename__ = "operation_precedence_edges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    predecessor_operation_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operations.operation_pk", ondelete="CASCADE"), nullable=False
    )
    successor_operation_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operations.operation_pk", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, default="finish_to_start")
    min_lag_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(
            "predecessor_operation_pk <> successor_operation_pk",
            name="ck_operation_precedence_not_self",
        ),
        UniqueConstraint(
            "predecessor_operation_pk",
            "successor_operation_pk",
            name="uq_operation_precedence_edge",
        ),
        Index("ix_operation_precedence_successor", "successor_operation_pk"),
    )


class MaterialRequirement(Base):
    """Material availability requirement for an operation."""

    __tablename__ = "material_requirements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    operation_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operations.operation_pk", ondelete="CASCADE"), nullable=False
    )
    material_id: Mapped[str] = mapped_column(String(128), nullable=False)
    required_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("required_quantity > 0", name="ck_material_requirements_quantity_positive"),
        Index("ix_material_requirements_material_id", "material_id"),
    )

