"""Initial schema — all core tables, pgvector, constraints, indexes.

Revision ID: 001
Revises: None
Create Date: 2025-01-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- incidents ---
    op.create_table(
        "incidents",
        sa.Column("incident_id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("incident_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("report_source", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_analysis"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("deduplicated_from", ARRAY(UUID(as_uuid=True)), nullable=True),
        sa.Column("raw_payload", JSONB, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending_analysis','analyzing','pending_confirmation','confirmed','executing','closed')",
            name="ck_incident_status_valid",
        ),
        sa.CheckConstraint(
            "severity IN ('P1-Critical','P2-High','P3-Medium','P4-Low')",
            name="ck_incident_severity_valid",
        ),
    )
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_severity", "incidents", ["severity"])
    op.create_index("ix_incidents_occurred_at", "incidents", ["occurred_at"])
    op.create_index("ix_incidents_resource_id", "incidents", ["resource_id"])

    # --- schedule_snapshots ---
    op.create_table(
        "schedule_snapshots",
        sa.Column("snapshot_id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workshop_id", sa.String(128), nullable=False),
        sa.Column("snapshot_data", JSONB, nullable=False),
        sa.Column("is_immutable", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_schedule_snapshots_captured_at", "schedule_snapshots", ["captured_at"])
    op.create_index("ix_schedule_snapshots_workshop_id", "schedule_snapshots", ["workshop_id"])

    # --- impact_reports ---
    op.create_table(
        "impact_reports",
        sa.Column("report_id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_id", UUID(as_uuid=True), sa.ForeignKey("schedule_snapshots.snapshot_id", ondelete="SET NULL"), nullable=True),
        sa.Column("analysis_mode", sa.String(32), nullable=False, server_default="normal"),
        sa.Column("report_data", JSONB, nullable=False),
        sa.Column("analysis_reference_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_impact_reports_incident_id", "impact_reports", ["incident_id"])
    op.create_index("ix_impact_reports_snapshot_id", "impact_reports", ["snapshot_id"])

    # --- candidate_plans ---
    op.create_table(
        "candidate_plans",
        sa.Column("plan_id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False),
        sa.Column("strategy_type", sa.String(64), nullable=False),
        sa.Column("schedule_detail", JSONB, nullable=False),
        sa.Column("solver_chain", JSONB, nullable=False),
        sa.Column("feasibility_status", sa.String(32), nullable=False, server_default="feasible"),
        sa.Column("solver_metadata", JSONB, nullable=True),
        sa.Column("constraint_report", JSONB, nullable=True),
        sa.Column("gantt_version", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_candidate_plans_incident_id", "candidate_plans", ["incident_id"])
    op.create_index("ix_candidate_plans_strategy_type", "candidate_plans", ["strategy_type"])

    # --- decision_records ---
    op.create_table(
        "decision_records",
        sa.Column("decision_record_id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_recommended_plan_id", UUID(as_uuid=True), sa.ForeignKey("candidate_plans.plan_id", ondelete="SET NULL"), nullable=True),
        sa.Column("confirmed_plan_id", UUID(as_uuid=True), sa.ForeignKey("candidate_plans.plan_id", ondelete="SET NULL"), nullable=True),
        sa.Column("derived_from_plan_id", UUID(as_uuid=True), sa.ForeignKey("candidate_plans.plan_id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_manual_adjusted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_override", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("override_reason", sa.Text, nullable=True),
        sa.Column("confirmed_by", sa.String(128), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_selection_input", JSONB, nullable=True),
        sa.Column("plan_selection_output", JSONB, nullable=True),
        sa.Column("module_versions", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_decision_records_incident_id", "decision_records", ["incident_id"])
    op.create_index("ix_decision_records_confirmed_at", "decision_records", ["confirmed_at"])

    # --- execution_results ---
    op.create_table(
        "execution_results",
        sa.Column("execution_result_id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("decision_record_id", UUID(as_uuid=True), sa.ForeignKey("decision_records.decision_record_id", ondelete="CASCADE"), nullable=False),
        sa.Column("actual_metrics", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_execution_results_decision_record_id", "execution_results", ["decision_record_id"])

    # --- case_records (with pgvector embedding) ---
    op.create_table(
        "case_records",
        sa.Column("case_id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision_record_id", UUID(as_uuid=True), sa.ForeignKey("decision_records.decision_record_id", ondelete="CASCADE"), nullable=False),
        sa.Column("incident_features", JSONB, nullable=False),
        sa.Column("strategy_used", sa.String(64), nullable=False),
        sa.Column("was_overridden", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("execution_result", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    # Add pgvector column via raw SQL (vector type not in standard SA dialect)
    op.execute("ALTER TABLE case_records ADD COLUMN embedding vector(768)")
    op.create_index("ix_case_records_incident_id", "case_records", ["incident_id"])
    op.create_index("ix_case_records_strategy_used", "case_records", ["strategy_used"])

    # --- case_templates ---
    op.create_table(
        "case_templates",
        sa.Column("template_id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("applicable_incident_type", sa.String(64), nullable=False),
        sa.Column("recommended_strategy", sa.String(64), nullable=False),
        sa.Column("parameters", JSONB, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_case_templates_status", "case_templates", ["status"])
    op.create_index("ix_case_templates_incident_type", "case_templates", ["applicable_incident_type"])

    # --- preference_profiles ---
    op.create_table(
        "preference_profiles",
        sa.Column("profile_id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("planner_id", sa.String(128), nullable=False, unique=True),
        sa.Column("preferences", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_preference_profiles_planner_id", "preference_profiles", ["planner_id"])

    # --- audit_logs ---
    op.create_table(
        "audit_logs",
        sa.Column("log_id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=True),
        sa.Column("details", JSONB, nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_audit_logs_entity_type_entity_id", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])

    # --- solver_policy_versions ---
    op.create_table(
        "solver_policy_versions",
        sa.Column("version_id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("module_name", sa.String(128), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("config", JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_solver_policy_versions_module_name", "solver_policy_versions", ["module_name"])
    op.create_index("ix_solver_policy_versions_active", "solver_policy_versions", ["module_name", "is_active"])

    # --- entity_versions (version history for audit trail) ---
    op.create_table(
        "entity_versions",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("changed_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_entity_versions_entity",
        "entity_versions",
        ["entity_type", "entity_id", "version_number"],
        unique=True,
    )
    op.create_index("ix_entity_versions_created_at", "entity_versions", ["created_at"])


def downgrade() -> None:
    op.drop_table("entity_versions")
    op.drop_table("solver_policy_versions")
    op.drop_table("audit_logs")
    op.drop_table("preference_profiles")
    op.drop_table("case_templates")
    op.drop_table("case_records")
    op.drop_table("execution_results")
    op.drop_table("decision_records")
    op.drop_table("candidate_plans")
    op.drop_table("impact_reports")
    op.drop_table("schedule_snapshots")
    op.drop_table("incidents")
    op.execute("DROP EXTENSION IF EXISTS vector")
