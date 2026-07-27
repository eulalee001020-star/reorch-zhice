#!/usr/bin/env python3
"""Run an actual solver-backed large-FJSP load gate.

The input must be a JSON payload accepted by ``LargeFjspReplayRequest``.
This tool measures the current implementation; it does not extrapolate
1k/5k/10k performance from formulas or upgrade synthetic evidence to a
customer-production claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.large_fjsp_replay import LargeFjspReplayRequest
from app.services.large_fjsp_replay import LargeFjspReplayService


def run_load_gate(
    payload: dict[str, Any],
    *,
    repeat_count: int,
    concurrency: int,
    evidence_scope: str,
    max_p95_seconds: float,
    min_solved_rate: float,
) -> dict[str, Any]:
    request = LargeFjspReplayRequest.model_validate(payload)
    encoded = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    input_sha256 = hashlib.sha256(encoded).hexdigest()

    samples: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(_run_once, request.model_dump(mode="json"), index)
            for index in range(repeat_count)
        ]
        for future in as_completed(futures):
            samples.append(future.result())
    samples.sort(key=lambda item: item["run_index"])

    durations = [float(sample["duration_seconds"]) for sample in samples]
    incident_total = sum(int(sample["incident_count"]) for sample in samples)
    solved_total = sum(int(sample["solved_incident_count"]) for sample in samples)
    solved_rate = solved_total / incident_total if incident_total else 0.0
    capacity_rejections = sum(
        int(sample["solver_capacity_rejection_count"]) for sample in samples
    )
    decomposition_required = sum(
        int(sample["decomposition_required_count"]) for sample in samples
    )
    p50 = _percentile(durations, 0.50)
    p95 = _percentile(durations, 0.95)
    load_gate_passed = (
        p95 <= max_p95_seconds
        and solved_rate >= min_solved_rate
        and capacity_rejections == 0
        and decomposition_required == 0
    )
    customer_evidence = evidence_scope in {
        "customer_desensitized",
        "customer_shadow",
    }

    first = samples[0] if samples else {}
    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "evidence_scope": evidence_scope,
        "input_sha256": input_sha256,
        "workshop_id": request.workshop_id,
        "repeat_count": repeat_count,
        "concurrency": concurrency,
        "operation_count": first.get("operation_count", 0),
        "resource_count": first.get("resource_count", 0),
        "incident_count_per_run": first.get("incident_count", 0),
        "p50_duration_seconds": p50,
        "p95_duration_seconds": p95,
        "solved_incident_rate": round(solved_rate, 4),
        "solver_capacity_rejection_count": capacity_rejections,
        "decomposition_required_count": decomposition_required,
        "thresholds": {
            "max_p95_seconds": max_p95_seconds,
            "min_solved_rate": min_solved_rate,
            "capacity_rejections_allowed": 0,
        },
        "load_gate_passed": load_gate_passed,
        "production_evidence_eligible": load_gate_passed and customer_evidence,
        "samples": samples,
        "claim_boundary": (
            "This report measures the supplied payload on one process and host. "
            "Synthetic/public evidence cannot prove customer production capacity. "
            "Production acceptance also requires customer-like 1k/5k/10k runs, "
            "multi-process deployment tests, constraint coverage, HA, and field evidence."
        ),
    }


def _run_once(payload: dict[str, Any], run_index: int) -> dict[str, Any]:
    request = LargeFjspReplayRequest.model_validate(payload)
    started = time.perf_counter()
    response = LargeFjspReplayService().run(request)
    duration = time.perf_counter() - started
    statuses = [
        option.solver_status for result in response.results for option in result.options
    ]
    return {
        "run_index": run_index,
        "duration_seconds": round(duration, 6),
        "operation_count": response.operation_count,
        "resource_count": response.resource_count,
        "incident_count": response.incident_count,
        "solved_incident_count": response.solved_incident_count,
        "feasible_option_count": response.feasible_option_count,
        "solver_capacity_rejection_count": statuses.count("SOLVER_CAPACITY_EXHAUSTED"),
        "decomposition_required_count": statuses.count(
            "INSTANCE_REQUIRES_DECOMPOSITION"
        ),
        "permission_level": response.permission_level,
        "readiness_score": response.readiness_score,
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 6)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--evidence-scope",
        choices=[
            "synthetic",
            "public_benchmark",
            "customer_desensitized",
            "customer_shadow",
        ],
        default="synthetic",
    )
    parser.add_argument("--max-p95-seconds", type=float, default=180.0)
    parser.add_argument("--min-solved-rate", type=float, default=0.95)
    args = parser.parse_args()
    if args.repeat < 1 or args.concurrency < 1:
        parser.error("--repeat and --concurrency must be positive")
    if args.concurrency > args.repeat:
        parser.error("--concurrency cannot exceed --repeat")

    payload = json.loads(args.input_json.read_text(encoding="utf-8"))
    report = run_load_gate(
        payload,
        repeat_count=args.repeat,
        concurrency=args.concurrency,
        evidence_scope=args.evidence_scope,
        max_p95_seconds=args.max_p95_seconds,
        min_solved_rate=args.min_solved_rate,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["load_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
