"""Production scheduling fact schema.

Revision ID: 003
Revises: 002
Create Date: 2026-05-07 00:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workshops",
        sa.Column("workshop_id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "resources",
        sa.Column("resource_pk", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workshop_id", sa.String(128), sa.ForeignKey("workshops.workshop_id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False, server_default="equipment"),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("criticality", sa.String(64), nullable=False, server_default="general"),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("capacity > 0", name="ck_resources_capacity_positive"),
        sa.UniqueConstraint("workshop_id", "resource_id", name="uq_resources_workshop_resource_id"),
    )
    op.create_index("ix_resources_workshop_id", "resources", ["workshop_id"])

    op.create_table(
        "resource_capabilities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("resource_pk", UUID(as_uuid=True), sa.ForeignKey("resources.resource_pk", ondelete="CASCADE"), nullable=False),
        sa.Column("capability", sa.String(128), nullable=False),
        sa.UniqueConstraint("resource_pk", "capability", name="uq_resource_capability"),
    )
    op.create_index("ix_resource_capabilities_capability", "resource_capabilities", ["capability"])

    op.create_table(
        "resource_calendars",
        sa.Column("calendar_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("resource_pk", UUID(as_uuid=True), sa.ForeignKey("resources.resource_pk", ondelete="CASCADE"), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("availability_type", sa.String(32), nullable=False, server_default="available"),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("window_end > window_start", name="ck_resource_calendars_window_valid"),
        sa.CheckConstraint("capacity >= 0", name="ck_resource_calendars_capacity_nonnegative"),
    )
    op.create_index("ix_resource_calendars_resource_time", "resource_calendars", ["resource_pk", "window_start", "window_end"])

    op.create_table(
        "work_orders",
        sa.Column("work_order_pk", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workshop_id", sa.String(128), sa.ForeignKey("workshops.workshop_id", ondelete="CASCADE"), nullable=False),
        sa.Column("work_order_id", sa.String(128), nullable=False),
        sa.Column("product_name", sa.String(256), nullable=False),
        sa.Column("product_family", sa.String(128), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="1"),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(64), nullable=False, server_default="released"),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("quantity > 0", name="ck_work_orders_quantity_positive"),
        sa.UniqueConstraint("workshop_id", "work_order_id", name="uq_work_orders_workshop_order_id"),
    )
    op.create_index("ix_work_orders_workshop_due_date", "work_orders", ["workshop_id", "due_date"])
    op.create_index("ix_work_orders_status", "work_orders", ["status"])

    op.create_table(
        "operations",
        sa.Column("operation_pk", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("work_order_pk", UUID(as_uuid=True), sa.ForeignKey("work_orders.work_order_pk", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("standard_processing_minutes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(64), nullable=False, server_default="planned"),
        sa.Column("required_capabilities", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "standard_processing_minutes IS NULL OR standard_processing_minutes > 0",
            name="ck_operations_processing_positive",
        ),
        sa.UniqueConstraint("work_order_pk", "operation_id", name="uq_operations_work_order_operation_id"),
    )
    op.create_index("ix_operations_work_order_sequence", "operations", ["work_order_pk", "sequence_no"])

    op.create_table(
        "operation_alternative_resources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("operation_pk", UUID(as_uuid=True), sa.ForeignKey("operations.operation_pk", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_pk", UUID(as_uuid=True), sa.ForeignKey("resources.resource_pk", ondelete="CASCADE"), nullable=False),
        sa.Column("processing_minutes", sa.Integer(), nullable=False),
        sa.Column("setup_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("priority_rank", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("processing_minutes > 0", name="ck_alt_resources_processing_positive"),
        sa.CheckConstraint("setup_minutes >= 0", name="ck_alt_resources_setup_nonnegative"),
        sa.UniqueConstraint("operation_pk", "resource_pk", name="uq_operation_alternative_resource"),
    )

    op.create_table(
        "operation_precedence_edges",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("predecessor_operation_pk", UUID(as_uuid=True), sa.ForeignKey("operations.operation_pk", ondelete="CASCADE"), nullable=False),
        sa.Column("successor_operation_pk", UUID(as_uuid=True), sa.ForeignKey("operations.operation_pk", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False, server_default="finish_to_start"),
        sa.Column("min_lag_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("predecessor_operation_pk <> successor_operation_pk", name="ck_operation_precedence_not_self"),
        sa.UniqueConstraint("predecessor_operation_pk", "successor_operation_pk", name="uq_operation_precedence_edge"),
    )
    op.create_index("ix_operation_precedence_successor", "operation_precedence_edges", ["successor_operation_pk"])

    op.create_table(
        "material_requirements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("operation_pk", UUID(as_uuid=True), sa.ForeignKey("operations.operation_pk", ondelete="CASCADE"), nullable=False),
        sa.Column("material_id", sa.String(128), nullable=False),
        sa.Column("required_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("required_quantity > 0", name="ck_material_requirements_quantity_positive"),
    )
    op.create_index("ix_material_requirements_material_id", "material_requirements", ["material_id"])

    op.create_table(
        "schedule_snapshot_operations",
        sa.Column("snapshot_operation_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("snapshot_id", UUID(as_uuid=True), sa.ForeignKey("schedule_snapshots.snapshot_id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_pk", UUID(as_uuid=True), sa.ForeignKey("operations.operation_pk", ondelete="SET NULL"), nullable=True),
        sa.Column("work_order_id", sa.String(128), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(64), nullable=False, server_default="planned"),
        sa.Column("is_frozen", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("required_capabilities", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("end_time > start_time", name="ck_snapshot_operations_time_valid"),
        sa.UniqueConstraint("snapshot_id", "operation_id", name="uq_snapshot_operations_snapshot_operation"),
    )
    op.create_index("ix_snapshot_ops_resource_time", "schedule_snapshot_operations", ["snapshot_id", "resource_id", "start_time", "end_time"])
    op.create_index("ix_snapshot_ops_work_order", "schedule_snapshot_operations", ["snapshot_id", "work_order_id"])

    op.create_table(
        "solver_runs",
        sa.Column("solver_run_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False),
        sa.Column("baseline_snapshot_id", UUID(as_uuid=True), sa.ForeignKey("schedule_snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("strategy_type", sa.String(64), nullable=False),
        sa.Column("solver_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("search_budget_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("objective_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("parameters", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result_summary", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("search_budget_seconds > 0", name="ck_solver_runs_budget_positive"),
    )
    op.create_index("ix_solver_runs_incident_status", "solver_runs", ["incident_id", "status"])
    op.create_index("ix_solver_runs_snapshot", "solver_runs", ["baseline_snapshot_id"])

    op.add_column("candidate_plans", sa.Column("baseline_snapshot_id", UUID(as_uuid=True), nullable=True))
    op.add_column("candidate_plans", sa.Column("solver_run_id", UUID(as_uuid=True), nullable=True))
    op.add_column("candidate_plans", sa.Column("objective_value", sa.Numeric(18, 6), nullable=True))
    op.add_column("candidate_plans", sa.Column("kpi_vector", JSONB, nullable=True))
    op.create_foreign_key("fk_candidate_plans_baseline_snapshot_id", "candidate_plans", "schedule_snapshots", ["baseline_snapshot_id"], ["snapshot_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_candidate_plans_solver_run_id", "candidate_plans", "solver_runs", ["solver_run_id"], ["solver_run_id"], ondelete="SET NULL")
    op.create_index("ix_candidate_plans_solver_run_id", "candidate_plans", ["solver_run_id"])
    op.create_index("ix_candidate_plans_baseline_snapshot_id", "candidate_plans", ["baseline_snapshot_id"])

    op.create_table(
        "candidate_plan_operations",
        sa.Column("plan_operation_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("candidate_plans.plan_id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_pk", UUID(as_uuid=True), sa.ForeignKey("operations.operation_pk", ondelete="SET NULL"), nullable=True),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("work_order_id", sa.String(128), nullable=False),
        sa.Column("original_resource_id", sa.String(128), nullable=True),
        sa.Column("planned_resource_id", sa.String(128), nullable=False),
        sa.Column("original_start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original_end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planned_end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_adjusted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("adjustment_reason", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("planned_end_time > planned_start_time", name="ck_plan_operations_time_valid"),
        sa.UniqueConstraint("plan_id", "operation_id", name="uq_plan_operations_plan_operation"),
    )
    op.create_index("ix_plan_ops_resource_time", "candidate_plan_operations", ["plan_id", "planned_resource_id", "planned_start_time", "planned_end_time"])
    op.create_index("ix_plan_ops_work_order", "candidate_plan_operations", ["plan_id", "work_order_id"])

    op.create_table(
        "plan_recommendations",
        sa.Column("recommendation_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False),
        sa.Column("recommended_plan_id", UUID(as_uuid=True), sa.ForeignKey("candidate_plans.plan_id", ondelete="CASCADE"), nullable=False),
        sa.Column("top_scored_plan_id", UUID(as_uuid=True), sa.ForeignKey("candidate_plans.plan_id", ondelete="SET NULL"), nullable=True),
        sa.Column("goal_mode", sa.String(64), nullable=False, server_default="balanced"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("recommendation_payload", JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_plan_recommendations_confidence"),
    )
    op.create_index("ix_plan_recommendations_incident_active", "plan_recommendations", ["incident_id", "is_active"])

    op.create_table(
        "writeback_jobs",
        sa.Column("writeback_job_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision_record_id", UUID(as_uuid=True), sa.ForeignKey("decision_records.decision_record_id", ondelete="SET NULL"), nullable=True),
        sa.Column("confirmed_plan_id", UUID(as_uuid=True), sa.ForeignKey("candidate_plans.plan_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_system", sa.String(64), nullable=False, server_default="MES"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("response_payload", JSONB, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("retry_count >= 0", name="ck_writeback_jobs_retry_nonnegative"),
    )
    op.create_index("ix_writeback_jobs_status_retry", "writeback_jobs", ["status", "next_retry_at"])
    op.create_index("ix_writeback_jobs_incident", "writeback_jobs", ["incident_id"])

    op.create_table(
        "outbox_events",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outbox_pending", "outbox_events", ["status", "next_retry_at", "created_at"])
    op.create_index("ix_outbox_aggregate", "outbox_events", ["aggregate_type", "aggregate_id"])


def downgrade() -> None:
    op.drop_index("ix_outbox_aggregate", table_name="outbox_events")
    op.drop_index("ix_outbox_pending", table_name="outbox_events")
    op.drop_table("outbox_events")

    op.drop_index("ix_writeback_jobs_incident", table_name="writeback_jobs")
    op.drop_index("ix_writeback_jobs_status_retry", table_name="writeback_jobs")
    op.drop_table("writeback_jobs")

    op.drop_index("ix_plan_recommendations_incident_active", table_name="plan_recommendations")
    op.drop_table("plan_recommendations")

    op.drop_index("ix_plan_ops_work_order", table_name="candidate_plan_operations")
    op.drop_index("ix_plan_ops_resource_time", table_name="candidate_plan_operations")
    op.drop_table("candidate_plan_operations")

    op.drop_index("ix_candidate_plans_baseline_snapshot_id", table_name="candidate_plans")
    op.drop_index("ix_candidate_plans_solver_run_id", table_name="candidate_plans")
    op.drop_constraint("fk_candidate_plans_solver_run_id", "candidate_plans", type_="foreignkey")
    op.drop_constraint("fk_candidate_plans_baseline_snapshot_id", "candidate_plans", type_="foreignkey")
    op.drop_column("candidate_plans", "kpi_vector")
    op.drop_column("candidate_plans", "objective_value")
    op.drop_column("candidate_plans", "solver_run_id")
    op.drop_column("candidate_plans", "baseline_snapshot_id")

    op.drop_index("ix_solver_runs_snapshot", table_name="solver_runs")
    op.drop_index("ix_solver_runs_incident_status", table_name="solver_runs")
    op.drop_table("solver_runs")

    op.drop_index("ix_snapshot_ops_work_order", table_name="schedule_snapshot_operations")
    op.drop_index("ix_snapshot_ops_resource_time", table_name="schedule_snapshot_operations")
    op.drop_table("schedule_snapshot_operations")

    op.drop_index("ix_material_requirements_material_id", table_name="material_requirements")
    op.drop_table("material_requirements")
    op.drop_index("ix_operation_precedence_successor", table_name="operation_precedence_edges")
    op.drop_table("operation_precedence_edges")
    op.drop_table("operation_alternative_resources")
    op.drop_index("ix_operations_work_order_sequence", table_name="operations")
    op.drop_table("operations")
    op.drop_index("ix_work_orders_status", table_name="work_orders")
    op.drop_index("ix_work_orders_workshop_due_date", table_name="work_orders")
    op.drop_table("work_orders")
    op.drop_index("ix_resource_calendars_resource_time", table_name="resource_calendars")
    op.drop_table("resource_calendars")
    op.drop_index("ix_resource_capabilities_capability", table_name="resource_capabilities")
    op.drop_table("resource_capabilities")
    op.drop_index("ix_resources_workshop_id", table_name="resources")
    op.drop_table("resources")
    op.drop_table("workshops")

