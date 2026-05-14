"""Tests for database schema definitions — verifies tables, columns, constraints, indexes."""

import uuid

from sqlalchemy import inspect as sa_inspect

from app.core.database import Base

# Ensure all models are loaded
import app.models.db  # noqa: F401


EXPECTED_TABLES = [
    "workshops",
    "resources",
    "resource_capabilities",
    "resource_calendars",
    "work_orders",
    "operations",
    "operation_alternative_resources",
    "operation_precedence_edges",
    "material_requirements",
    "incidents",
    "schedule_snapshots",
    "schedule_snapshot_operations",
    "impact_reports",
    "solver_runs",
    "candidate_plans",
    "candidate_plan_operations",
    "plan_recommendations",
    "decision_records",
    "writeback_jobs",
    "execution_results",
    "case_records",
    "case_templates",
    "preference_profiles",
    "audit_logs",
    "solver_policy_versions",
    "entity_versions",
    "outbox_events",
]


def test_all_expected_tables_registered():
    """All 12 core tables are present in metadata."""
    tables = set(Base.metadata.tables.keys())
    for name in EXPECTED_TABLES:
        assert name in tables, f"Missing table: {name}"


def test_incidents_table_columns():
    """Incidents table has all required columns."""
    table = Base.metadata.tables["incidents"]
    col_names = {c.name for c in table.columns}
    required = {
        "incident_id", "incident_type", "external_event_id", "occurred_at",
        "workshop_id", "resource_id", "report_source", "source_system",
        "severity", "status", "description",
        "deduplicated_from", "raw_payload", "idempotency_key", "created_by", "version",
        "created_at", "updated_at",
    }
    assert required.issubset(col_names), f"Missing: {required - col_names}"


def test_incidents_has_status_check_constraint():
    """Incidents table has a CHECK constraint on status."""
    table = Base.metadata.tables["incidents"]
    check_names = [c.name for c in table.constraints if hasattr(c, "sqltext")]
    assert "ck_incident_status_valid" in check_names


def test_incidents_has_severity_check_constraint():
    """Incidents table has a CHECK constraint on severity."""
    table = Base.metadata.tables["incidents"]
    check_names = [c.name for c in table.constraints if hasattr(c, "sqltext")]
    assert "ck_incident_severity_valid" in check_names


def test_incidents_has_version_column_for_optimistic_locking():
    """Incidents table has a version column for optimistic locking."""
    table = Base.metadata.tables["incidents"]
    col_names = {c.name for c in table.columns}
    assert "version" in col_names


def test_case_records_has_embedding_column():
    """case_records table has a pgvector embedding column."""
    table = Base.metadata.tables["case_records"]
    col_names = {c.name for c in table.columns}
    assert "embedding" in col_names


def test_decision_records_has_derived_from_plan_id():
    """decision_records has derived_from_plan_id for adjusted plans."""
    table = Base.metadata.tables["decision_records"]
    col_names = {c.name for c in table.columns}
    assert "derived_from_plan_id" in col_names


def test_decision_records_has_module_versions():
    """decision_records stores strategy module versions."""
    table = Base.metadata.tables["decision_records"]
    col_names = {c.name for c in table.columns}
    assert "module_versions" in col_names


def test_schedule_snapshots_has_immutable_flag():
    """schedule_snapshots has is_immutable flag."""
    table = Base.metadata.tables["schedule_snapshots"]
    col_names = {c.name for c in table.columns}
    assert "is_immutable" in col_names


def test_schedule_snapshots_has_versioning_fields():
    """schedule_snapshots stores source, version, lineage, and import metadata."""
    table = Base.metadata.tables["schedule_snapshots"]
    col_names = {c.name for c in table.columns}
    required = {
        "source_system", "schema_version", "snapshot_version",
        "parent_snapshot_id", "baseline_snapshot_id", "import_batch_id",
        "snapshot_hash", "is_active", "created_by",
    }
    assert required.issubset(col_names)


def test_audit_logs_has_governance_fields():
    """audit_logs captures role, result, request correlation, and IP metadata."""
    table = Base.metadata.tables["audit_logs"]
    col_names = {c.name for c in table.columns}
    required = {"role", "result", "request_id", "ip_address"}
    assert required.issubset(col_names)


def test_entity_versions_table_exists():
    """entity_versions table exists for audit trail."""
    table = Base.metadata.tables["entity_versions"]
    col_names = {c.name for c in table.columns}
    required = {"id", "entity_type", "entity_id", "version_number", "data", "changed_by", "created_at"}
    assert required.issubset(col_names)


def test_impact_reports_has_foreign_keys():
    """impact_reports references incidents and schedule_snapshots."""
    table = Base.metadata.tables["impact_reports"]
    fk_referred = set()
    for fk in table.foreign_keys:
        fk_referred.add(fk.column.table.name)
    assert "incidents" in fk_referred
    assert "schedule_snapshots" in fk_referred


def test_candidate_plans_has_solver_chain_jsonb():
    """candidate_plans stores solver_chain as JSONB."""
    table = Base.metadata.tables["candidate_plans"]
    col_names = {c.name for c in table.columns}
    assert "solver_chain" in col_names
    assert "schedule_detail" in col_names
    assert "baseline_snapshot_id" in col_names
    assert "solver_run_id" in col_names
    assert "objective_value" in col_names
    assert "kpi_vector" in col_names


def test_incidents_status_column_has_default():
    """Incidents status column has a default value of pending_analysis."""
    table = Base.metadata.tables["incidents"]
    status_col = table.c.status
    assert status_col.default is not None or status_col.server_default is not None


def test_production_master_tables_have_unique_business_keys():
    """Production master data tables expose workshop-scoped business keys."""
    resources = Base.metadata.tables["resources"]
    resource_constraints = {c.name for c in resources.constraints}
    assert "uq_resources_workshop_resource_id" in resource_constraints

    work_orders = Base.metadata.tables["work_orders"]
    work_order_constraints = {c.name for c in work_orders.constraints}
    assert "uq_work_orders_workshop_order_id" in work_order_constraints


def test_schedule_snapshot_operations_are_queryable_by_resource_time():
    """Snapshot operation facts support Gantt and overlap queries."""
    table = Base.metadata.tables["schedule_snapshot_operations"]
    col_names = {c.name for c in table.columns}
    required = {
        "snapshot_id", "operation_id", "work_order_id", "resource_id",
        "start_time", "end_time", "is_frozen", "required_capabilities",
    }
    assert required.issubset(col_names)
    assert "ix_snapshot_ops_resource_time" in {idx.name for idx in table.indexes}


def test_candidate_plan_operations_are_queryable_by_resource_time():
    """Candidate plan operation facts support plan diff and MES writeback."""
    table = Base.metadata.tables["candidate_plan_operations"]
    col_names = {c.name for c in table.columns}
    required = {
        "plan_id", "operation_id", "work_order_id",
        "original_resource_id", "planned_resource_id",
        "planned_start_time", "planned_end_time", "is_adjusted",
    }
    assert required.issubset(col_names)
    assert "ix_plan_ops_resource_time" in {idx.name for idx in table.indexes}


def test_outbox_events_support_pending_publish_scan():
    """Outbox events support reliable async publication scans."""
    table = Base.metadata.tables["outbox_events"]
    col_names = {c.name for c in table.columns}
    required = {
        "event_id", "aggregate_type", "aggregate_id", "event_type",
        "payload", "status", "retry_count", "next_retry_at", "published_at",
    }
    assert required.issubset(col_names)
    assert "ix_outbox_pending" in {idx.name for idx in table.indexes}
