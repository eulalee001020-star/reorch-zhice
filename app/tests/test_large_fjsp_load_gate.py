"""Tests for the solver-backed large-FJSP load evidence tool."""

from __future__ import annotations

from app.tests.test_large_fjsp_replay import _request
from tools.run_large_fjsp_load_gate import run_load_gate


def test_load_gate_measures_actual_runs_without_upgrading_synthetic_evidence() -> None:
    report = run_load_gate(
        _request().model_dump(mode="json"),
        repeat_count=2,
        concurrency=2,
        evidence_scope="synthetic",
        max_p95_seconds=30,
        min_solved_rate=1.0,
    )

    assert report["repeat_count"] == 2
    assert report["concurrency"] == 2
    assert report["operation_count"] == 4
    assert report["p95_duration_seconds"] > 0
    assert report["solved_incident_rate"] == 1.0
    assert report["load_gate_passed"] is True
    assert report["production_evidence_eligible"] is False
    assert len(report["input_sha256"]) == 64
    assert len(report["samples"]) == 2
