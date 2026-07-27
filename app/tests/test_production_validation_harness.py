"""Integrated production digital-twin validation tests."""

from app.models.db.operational_runtime import OperationalBase
from app.services.production_validation_harness import ProductionValidationHarness


def test_operational_runtime_schema_contains_durable_state_tables() -> None:
    assert {
        "runtime_cdc_events",
        "runtime_cdc_checkpoints",
        "runtime_solve_jobs",
        "runtime_shadow_cases",
        "runtime_execution_receipts",
        "runtime_evidence_records",
        "integration_assets",
        "integration_quarantine",
        "integration_audit_events",
    }.issubset(set(OperationalBase.metadata.tables))


def test_integrated_digital_twin_harness_passes_but_customer_gate_stays_open() -> None:
    response = ProductionValidationHarness().run(scale_repetitions=1)

    assert response.all_digital_twin_checks_passed is True
    assert response.customer_evidence_gate_passed is False
    assert len(response.checks) == 12
    assert response.checks["integration_control_plane"]["status"] == "pass"
    assert response.checks["anytime_hybrid_solver"]["status"] == "pass"
    assert response.checks["anytime_hybrid_solver"]["warm_start_verified"] is True
    assert response.checks["feasibility_restoration"]["status"] == "pass"
    assert (
        response.checks["feasibility_restoration"]["writeback_authorized"]
        is False
    )
    assert all(item["status"] == "pass" for item in response.checks.values())
    assert [item["operation_count"] for item in response.scale_results] == [
        1000,
        5000,
        10000,
    ]
    assert response.evidence_ledger.case_count == 30
    assert response.evidence_ledger.roi_is_proxy is True
    assert response.artifact_fingerprint
