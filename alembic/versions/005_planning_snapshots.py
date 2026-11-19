"""Durable supply and dispatch snapshots.

Revision ID: 005
Revises: 004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The local runtime can have already bootstrapped this additive table.
    if sa.inspect(op.get_bind()).has_table("planning_snapshots"):
        return
    op.create_table(
        "planning_snapshots",
        sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON().with_variant(JSONB, "postgresql"), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "snapshot_id", name="uq_planning_snapshot_identity"),
    )
    op.create_index("ix_planning_snapshot_latest", "planning_snapshots", ["kind", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_planning_snapshot_latest", table_name="planning_snapshots")
    op.drop_table("planning_snapshots")
