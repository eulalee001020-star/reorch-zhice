"""Smoke tests for benchmark assets and the dependency-free benchmark runner."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = ROOT / "benchmark"


def test_benchmark_json_assets_parse():
    for path in [
        BENCHMARK_DIR / "kpi_dictionary.json",
        BENCHMARK_DIR / "constraint_dictionary.json",
        BENCHMARK_DIR / "acceptance_criteria.json",
        BENCHMARK_DIR / "datasets" / "dynamic_fjsp_small.json",
        BENCHMARK_DIR / "import_templates" / "schedule_snapshot_import_template.json",
    ]:
        with path.open("r", encoding="utf-8") as fh:
            assert json.load(fh)


def test_benchmark_runner_validates_default_dataset():
    script = BENCHMARK_DIR / "scripts" / "run_benchmark.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["valid"] is True
    assert report["kpis"]["operation_count"] == 3

