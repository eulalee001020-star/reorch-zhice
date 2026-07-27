"""Customer evidence and ROI ledger gate tests."""

import json
from pathlib import Path

from app.services.recovery_evidence_ledger import RecoveryEvidenceLedgerService


ROOT = Path(__file__).resolve().parents[2]


def test_digital_twin_30_case_ledger_is_proxy_not_customer_proof() -> None:
    ledger = RecoveryEvidenceLedgerService().build_digital_twin_ledger()

    assert ledger.case_count == 30
    assert ledger.roi_is_proxy is True
    assert ledger.customer_evidence_gate_passed is False
    assert ledger.aggregate_roi["total_gross_benefit"] > 0
    assert len({case.incident.incident_type for case in ledger.cases}) == 7


def test_ten_complete_customer_cases_pass_evidence_gate() -> None:
    template = json.loads(
        (
            ROOT
            / "datasets/customer_evidence_pack/customer_recovery_cases.template.json"
        ).read_text(encoding="utf-8")
    )["rows"][0]
    rows = []
    for index in range(10):
        row = json.loads(json.dumps(template))
        row["case_id"] = f"CUSTOMER-CASE-{index + 1:03d}"
        row["incident"]["incident_id"] = f"INC-{index + 1:03d}"
        row["source_refs"] = [
            f"MES:incident:{index + 1:03d}",
            f"APS:snapshot:{index + 1:03d}",
            f"MES:execution:{index + 1:03d}",
        ]
        row["planner_baseline"]["baseline_decision_ref"] = (
            f"APS:decision:{index + 1:03d}"
        )
        row["execution_outcome"]["source_event_ids"] = [
            f"MES-EVENT-{index + 1:03d}"
        ]
        rows.append(row)

    ledger = RecoveryEvidenceLedgerService().build_customer_ledger(rows)

    assert ledger.customer_evidence_gate_passed is True
    assert ledger.roi_is_proxy is False
    assert ledger.blockers == []
    assert ledger.aggregate_roi["total_gross_benefit"] == 30000.0


def test_missing_customer_provenance_keeps_gate_closed() -> None:
    template = json.loads(
        (
            ROOT
            / "datasets/customer_evidence_pack/customer_recovery_cases.template.json"
        ).read_text(encoding="utf-8")
    )["rows"][0]
    rows = []
    for index in range(10):
        row = json.loads(json.dumps(template))
        row["case_id"] = f"CASE-{index}"
        row["incident"]["incident_id"] = f"INC-{index}"
        row["planner_baseline"]["provenance_confirmed"] = False
        rows.append(row)

    ledger = RecoveryEvidenceLedgerService().build_customer_ledger(rows)

    assert ledger.customer_evidence_gate_passed is False
    assert any("planner_baseline_provenance_missing" in item for item in ledger.blockers)
