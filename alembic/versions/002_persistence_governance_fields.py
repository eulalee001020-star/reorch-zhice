"""Persistence governance fields for incidents, snapshots, and audit logs.

Revision ID: 002
Revises: 001
Create Date: 2026-05-07 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- incidents ---
    op.add_column("incidents", sa.Column("external_event_id", sa.String(length=128), nullable=True))
    op.add_column("incidents", sa.Column("workshop_id", sa.String(length=128), nullable=True))
    op.add_column("incidents", sa.Column("source_system", sa.String(length=64), nullable=True))
    op.add_column("incidents", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column("incidents", sa.Column("created_by", sa.String(length=128), nullable=True))
    op.create_index("ix_incidents_workshop_status", "incidents", ["workshop_id", "status"])
    op.create_index("ix_incidents_external_event_id", "incidents", ["external_event_id"])
    op.create_unique_constraint("uq_incidents_idempotency_key", "incidents", ["idempotency_key"])

    # --- schedule_snapshots ---
    op.add_column("schedule_snapshots", sa.Column("source_system", sa.String(length=64), nullable=True))
    op.add_column(
        "schedule_snapshots",
        sa.Column("schema_version", sa.String(length=32), nullable=False, server_default="1.0"),
    )
    op.add_column(
        "schedule_snapshots",
        sa.Column("snapshot_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "schedule_snapshots",
        sa.Column("parent_snapshot_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "schedule_snapshots",
        sa.Column("baseline_snapshot_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column("schedule_snapshots", sa.Column("import_batch_id", sa.String(length=128), nullable=True))
    op.add_column("schedule_snapshots", sa.Column("snapshot_hash", sa.String(length=128), nullable=True))
    op.add_column(
        "schedule_snapshots",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column("schedule_snapshots", sa.Column("created_by", sa.String(length=128), nullable=True))
    op.create_foreign_key(
        "fk_schedule_snapshots_parent_snapshot_id",
        "schedule_snapshots",
        "schedule_snapshots",
        ["parent_snapshot_id"],
        ["snapshot_id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_schedule_snapshots_baseline_snapshot_id",
        "schedule_snapshots",
        "schedule_snapshots",
        ["baseline_snapshot_id"],
        ["snapshot_id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_schedule_snapshots_workshop_version",
        "schedule_snapshots",
        ["workshop_id", "snapshot_version"],
    )
    op.create_index("ix_schedule_snapshots_import_batch_id", "schedule_snapshots", ["import_batch_id"])

    # --- audit_logs ---
    op.add_column("audit_logs", sa.Column("role", sa.String(length=64), nullable=True))
    op.add_column(
        "audit_logs",
        sa.Column("result", sa.String(length=32), nullable=False, server_default="success"),
    )
    op.add_column("audit_logs", sa.Column("request_id", sa.String(length=128), nullable=True))
    op.add_column("audit_logs", sa.Column("ip_address", sa.String(length=64), nullable=True))
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_column("audit_logs", "ip_address")
    op.drop_column("audit_logs", "request_id")
    op.drop_column("audit_logs", "result")
    op.drop_column("audit_logs", "role")

    op.drop_index("ix_schedule_snapshots_import_batch_id", table_name="schedule_snapshots")
    op.drop_index("ix_schedule_snapshots_workshop_version", table_name="schedule_snapshots")
    op.drop_constraint("fk_schedule_snapshots_baseline_snapshot_id", "schedule_snapshots", type_="foreignkey")
    op.drop_constraint("fk_schedule_snapshots_parent_snapshot_id", "schedule_snapshots", type_="foreignkey")
    op.drop_column("schedule_snapshots", "created_by")
    op.drop_column("schedule_snapshots", "is_active")
    op.drop_column("schedule_snapshots", "snapshot_hash")
    op.drop_column("schedule_snapshots", "import_batch_id")
    op.drop_column("schedule_snapshots", "baseline_snapshot_id")
    op.drop_column("schedule_snapshots", "parent_snapshot_id")
    op.drop_column("schedule_snapshots", "snapshot_version")
    op.drop_column("schedule_snapshots", "schema_version")
    op.drop_column("schedule_snapshots", "source_system")

    op.drop_constraint("uq_incidents_idempotency_key", "incidents", type_="unique")
    op.drop_index("ix_incidents_external_event_id", table_name="incidents")
    op.drop_index("ix_incidents_workshop_status", table_name="incidents")
    op.drop_column("incidents", "created_by")
    op.drop_column("incidents", "idempotency_key")
    op.drop_column("incidents", "source_system")
    op.drop_column("incidents", "workshop_id")
    op.drop_column("incidents", "external_event_id")

