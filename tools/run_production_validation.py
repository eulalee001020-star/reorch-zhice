"""Run the integrated production digital-twin validation pack."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.production_validation_harness import ProductionValidationHarness  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale-repetitions", type=int, default=5)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/production_digital_twin_validation.json"),
    )
    args = parser.parse_args()
    response = ProductionValidationHarness().run(
        scale_repetitions=args.scale_repetitions
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "all_digital_twin_checks_passed": response.all_digital_twin_checks_passed,
                "customer_evidence_gate_passed": response.customer_evidence_gate_passed,
                "artifact_fingerprint": response.artifact_fingerprint,
                "scale_p95_ms": {
                    str(item["operation_count"]): item["p95_elapsed_ms"]
                    for item in response.scale_results
                },
                "case_count": response.evidence_ledger.case_count,
                "blockers": response.blockers,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if response.all_digital_twin_checks_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
