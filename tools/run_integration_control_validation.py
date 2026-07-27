#!/usr/bin/env python3
"""Run the six-asset integration control-plane digital-twin validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.integration_control_validation import (
    IntegrationControlValidationHarness,
)
from app.services.operational_store import RelationalOperationalStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", default="digital-twin")
    parser.add_argument("--database-url", default="sqlite+pysqlite:///:memory:")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/integration_control_validation.json"),
    )
    args = parser.parse_args()

    result = IntegrationControlValidationHarness(
        RelationalOperationalStore(args.database_url)
    ).run(tenant_id=args.tenant_id, actor_id="cli-it-admin")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "all_checks_passed": result.all_checks_passed,
                "check_count": len(result.checks),
                "readiness": result.readiness_manifest.status,
                "customer_writeback_certified": (
                    result.overview.production_writeback_certified
                ),
                "artifact_fingerprint": result.artifact_fingerprint,
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.all_checks_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
