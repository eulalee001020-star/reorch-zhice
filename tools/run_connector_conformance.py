#!/usr/bin/env python3
"""Execute Connector SDK conformance against a customer-provided factory."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from app.integration_sdk import (
    ConnectorConformanceRunner,
    EnterpriseConnector,
    WritebackCertificationHarness,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--factory",
        required=True,
        help="Import path module:function returning an EnterpriseConnector.",
    )
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument(
        "--evidence-scope",
        choices=["digital_twin", "customer_sandbox", "customer_production"],
        default="customer_sandbox",
    )
    parser.add_argument("--writeback-adapter-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    connector = _load_connector(args.factory)
    conformance = ConnectorConformanceRunner().run(
        connector,
        tenant_id=args.tenant_id,
        evidence_scope=args.evidence_scope,
    )
    artifact: dict[str, object] = {
        "connector_conformance": conformance.model_dump(mode="json")
    }
    all_passed = conformance.passed
    if args.writeback_adapter_id:
        if args.evidence_scope == "customer_production":
            raise ValueError("writeback_certification_must_not_target_customer_production")
        certification = WritebackCertificationHarness().run(
            connector,
            tenant_id=args.tenant_id,
            adapter_id=args.writeback_adapter_id,
            evidence_scope=args.evidence_scope,
        )
        artifact["writeback_certification"] = certification.model_dump(mode="json")
        all_passed = all_passed and certification.passed

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "passed": all_passed,
                "connector_id": connector.manifest.connector_id,
                "connector_version": connector.manifest.connector_version,
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if all_passed else 1


def _load_connector(factory_path: str) -> EnterpriseConnector:
    module_name, separator, function_name = factory_path.partition(":")
    if not separator:
        raise ValueError("factory_must_use_module:function_format")
    factory = getattr(importlib.import_module(module_name), function_name)
    connector = factory()
    if not isinstance(connector, EnterpriseConnector):
        raise TypeError("factory_must_return_EnterpriseConnector")
    return connector


if __name__ == "__main__":
    raise SystemExit(main())
