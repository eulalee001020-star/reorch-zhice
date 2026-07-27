"""Operational runtime and integration control-plane schema.

Revision ID: 004
Revises: 003
Create Date: 2026-07-12 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runtime_cdc_events",
        sa.Column("event_id", sa.String(160), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("source_system", sa.String(64), nullable=False),
        sa.Column("partition_key", sa.String(128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entity_type", sa.String(128), nullable=False),
        sa.Column("entity_id", sa.String(256), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("committed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "source_system",
            "partition_key",
            "sequence",
            name="uq_runtime_cdc_source_sequence",
        ),
    )
    op.create_index(
        "ix_runtime_cdc_asof",
        "runtime_cdc_events",
        ["tenant_id", "source_system", "partition_key", "occurred_at", "sequence"],
    )

    op.create_table(
        "runtime_cdc_checkpoints",
        sa.Column("checkpoint_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("source_system", sa.String(64), nullable=False),
        sa.Column("partition_key", sa.String(128), nullable=False),
        sa.Column("committed_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("watermark_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint_token", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "source_system",
            "partition_key",
            name="uq_runtime_cdc_checkpoint",
        ),
    )

    op.create_table(
        "runtime_solve_jobs",
        sa.Column("job_id", sa.String(96), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("solve_request", JSONB, nullable=False),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("checkpoint", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_runtime_solve_idempotency"
        ),
    )
    op.create_index(
        "ix_runtime_solve_claim",
        "runtime_solve_jobs",
        ["status", "priority", "created_at"],
    )
    op.create_index(
        "ix_runtime_solve_lease",
        "runtime_solve_jobs",
        ["status", "lease_expires_at"],
    )

    op.create_table(
        "runtime_shadow_cases",
        sa.Column("shadow_case_id", sa.String(96), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("evidence_scope", sa.String(40), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_runtime_shadow_tenant_status",
        "runtime_shadow_cases",
        ["tenant_id", "status"],
    )

    op.create_table(
        "runtime_execution_receipts",
        sa.Column("receipt_id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("shadow_case_id", sa.String(96), nullable=False),
        sa.Column("source_event_id", sa.String(160), nullable=False),
        sa.Column("operation_id", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "source_event_id",
            name="uq_runtime_execution_source_event",
        ),
    )
    op.create_index(
        "ix_runtime_receipt_shadow_operation",
        "runtime_execution_receipts",
        ["shadow_case_id", "operation_id"],
    )

    op.create_table(
        "runtime_evidence_records",
        sa.Column("evidence_id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("evidence_type", sa.String(80), nullable=False),
        sa.Column("evidence_scope", sa.String(40), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_runtime_evidence_type",
        "runtime_evidence_records",
        ["tenant_id", "evidence_type"],
    )

    op.create_table(
        "integration_assets",
        sa.Column("asset_key", sa.String(320), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("asset_type", sa.String(64), nullable=False),
        sa.Column("asset_id", sa.String(128), nullable=False),
        sa.Column("scope_key", sa.String(256), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=True),
        sa.Column("approval_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "asset_type",
            "asset_id",
            "version",
            name="uq_integration_asset_version",
        ),
    )
    op.create_index(
        "ix_integration_asset_active",
        "integration_assets",
        ["tenant_id", "asset_type", "scope_key", "status"],
    )

    op.create_table(
        "integration_quarantine",
        sa.Column("quarantine_id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("connector_id", sa.String(128), nullable=False),
        sa.Column("source_system", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("reason_codes", JSONB, nullable=False),
        sa.Column("observation", JSONB, nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(128), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "connector_id",
            "fingerprint",
            name="uq_integration_quarantine_observation",
        ),
    )
    op.create_index(
        "ix_integration_quarantine_open",
        "integration_quarantine",
        ["tenant_id", "status", "observed_at"],
    )

    op.create_table(
        "integration_audit_events",
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(96), nullable=False),
        sa.Column("asset_type", sa.String(64), nullable=True),
        sa.Column("asset_id", sa.String(128), nullable=True),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("details", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_integration_audit_tenant_time",
        "integration_audit_events",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_integration_audit_tenant_time", table_name="integration_audit_events")
    op.drop_table("integration_audit_events")
    op.drop_index("ix_integration_quarantine_open", table_name="integration_quarantine")
    op.drop_table("integration_quarantine")
    op.drop_index("ix_integration_asset_active", table_name="integration_assets")
    op.drop_table("integration_assets")
    op.drop_index("ix_runtime_evidence_type", table_name="runtime_evidence_records")
    op.drop_table("runtime_evidence_records")
    op.drop_index(
        "ix_runtime_receipt_shadow_operation", table_name="runtime_execution_receipts"
    )
    op.drop_table("runtime_execution_receipts")
    op.drop_index("ix_runtime_shadow_tenant_status", table_name="runtime_shadow_cases")
    op.drop_table("runtime_shadow_cases")
    op.drop_index("ix_runtime_solve_lease", table_name="runtime_solve_jobs")
    op.drop_index("ix_runtime_solve_claim", table_name="runtime_solve_jobs")
    op.drop_table("runtime_solve_jobs")
    op.drop_table("runtime_cdc_checkpoints")
    op.drop_index("ix_runtime_cdc_asof", table_name="runtime_cdc_events")
    op.drop_table("runtime_cdc_events")
