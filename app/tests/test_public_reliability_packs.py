import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_public_reliability_packs_pass_when_blocked_source_is_explicit(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "run_public_reliability_packs.py"),
            "--allow-blocked",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["total"] == 5
    assert report["passed"] == 4
    assert report["gate_conclusion"]["system_failure"] is False
    assert report["gate_conclusion"]["digital_twin_engineering_consistency"] == "pass"
    assert report["gate_conclusion"]["official_anonymized_mes_source"] == "fail"
    assert report["gate_conclusion"]["real_shadow_2_to_4_weeks"] is False
    blocked = next(row for row in report["results"] if row["pack_id"] == "p0_ulster_mes")
    assert blocked["status"] == "fail"
    assert blocked["acquisition_status"] == "acquisition_blocked"
    assert blocked["counts"]["surrogate_operations"] == 7
    assert blocked["counts"]["surrogate_downtime_events"] == 2
    assert blocked["counts"]["digital_twin_operations"] == 10_000
    assert blocked["counts"]["digital_twin_mes_receipts"] == 10_000
    assert blocked["counts"]["admission_rehearsal_cases"] == 30
    assert blocked["counts"]["admission_rehearsal_planner_dispositions"] == 30
    assert blocked["counts"]["admission_rehearsal_execution_receipts"] == 30
    assert blocked["counts"]["real_customer_cases"] == 0
    assert blocked["errors"] == ["source acquisition incomplete"]


def test_strict_public_reliability_gate_fails_on_missing_official_source(tmp_path: Path) -> None:
    output = tmp_path / "strict-report.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "run_public_reliability_packs.py"), "--output", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1


def test_ulster_digital_twin_integrity_checks_pass() -> None:
    from tools.run_public_reliability_packs import validate_pack

    result = validate_pack(ROOT / "datasets" / "public_reliability_packs" / "p0_ulster_mes")

    assert result["errors"] == ["source acquisition incomplete"]
    assert result["counts"]["digital_twin_cdc_events"] == 10_000
