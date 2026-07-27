"""Relational schema for CDC, solve jobs, and shadow execution evidence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


JSON_DOCUMENT = JSON().with_variant(JSONB, "postgresql")


class OperationalBase(DeclarativeBase):
    pass


class CdcEventRecord(OperationalBase):
    __tablename__ = "runtime_cdc_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_system",
            "partition_key",
            "sequence",
            name="uq_runtime_cdc_source_sequence",
        ),
        Index(
            "ix_runtime_cdc_asof",
            "tenant_id",
            "source_system",
            "partition_key",
            "occurred_at",
            "sequence",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    partition_key: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(256), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    committed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CdcCheckpointRecord(OperationalBase):
    __tablename__ = "runtime_cdc_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_system",
            "partition_key",
            name="uq_runtime_cdc_checkpoint",
        ),
    )

    checkpoint_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    partition_key: Mapped[str] = mapped_column(String(128), nullable=False)
    committed_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    watermark_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkpoint_token: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SolveJobRecordORM(OperationalBase):
    __tablename__ = "runtime_solve_jobs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_runtime_solve_idempotency"
        ),
        Index("ix_runtime_solve_claim", "status", "priority", "created_at"),
        Index("ix_runtime_solve_lease", "status", "lease_expires_at"),
    )

    job_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    solve_request: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    checkpoint: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class ShadowCaseRecordORM(OperationalBase):
    __tablename__ = "runtime_shadow_cases"
    __table_args__ = (
        Index("ix_runtime_shadow_tenant_status", "tenant_id", "status"),
    )

    shadow_case_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_scope: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecutionReceiptRecordORM(OperationalBase):
    __tablename__ = "runtime_execution_receipts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source_event_id", name="uq_runtime_execution_source_event"
        ),
        Index("ix_runtime_receipt_shadow_operation", "shadow_case_id", "operation_id"),
    )

    receipt_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    shadow_case_id: Mapped[str] = mapped_column(String(96), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)


class RuntimeEvidenceRecordORM(OperationalBase):
    __tablename__ = "runtime_evidence_records"
    __table_args__ = (
        Index("ix_runtime_evidence_type", "tenant_id", "evidence_type"),
    )

    evidence_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_scope: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IntegrationAssetRecordORM(OperationalBase):
    """Immutable versioned integration-governance asset."""

    __tablename__ = "integration_assets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "asset_type",
            "asset_id",
            "version",
            name="uq_integration_asset_version",
        ),
        Index(
            "ix_integration_asset_active",
            "tenant_id",
            "asset_type",
            "scope_key",
            "status",
        ),
    )

    asset_key: Mapped[str] = mapped_column(String(320), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approval_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationQuarantineRecordORM(OperationalBase):
    """Schema observations blocked from canonical ingestion."""

    __tablename__ = "integration_quarantine"
    __table_args__ = (
        Index(
            "ix_integration_quarantine_open",
            "tenant_id",
            "status",
            "observed_at",
        ),
        UniqueConstraint(
            "tenant_id",
            "connector_id",
            "fingerprint",
            name="uq_integration_quarantine_observation",
        ),
    )

    quarantine_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connector_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_system: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    reason_codes: Mapped[list] = mapped_column(JSON_DOCUMENT, nullable=False)
    observation: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(128))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class IntegrationAuditRecordORM(OperationalBase):
    """Append-only audit trail for integration control-plane mutations."""

    __tablename__ = "integration_audit_events"
    __table_args__ = (
        Index("ix_integration_audit_tenant_time", "tenant_id", "created_at"),
    )

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(96), nullable=False)
    asset_type: Mapped[str | None] = mapped_column(String(64))
    asset_id: Mapped[str | None] = mapped_column(String(128))
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
