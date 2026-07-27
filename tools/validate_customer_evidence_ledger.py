"""Validate 10-30 customer recovery cases and produce a gated ROI ledger."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.recovery_evidence_ledger import RecoveryEvidenceLedgerService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = json.loads(args.input.read_text(encoding="utf-8"))
    rows = document.get("rows", document) if isinstance(document, dict) else document
    ledger = RecoveryEvidenceLedgerService().build_customer_ledger(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(ledger.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "case_count": ledger.case_count,
                "customer_evidence_gate_passed": ledger.customer_evidence_gate_passed,
                "blockers": ledger.blockers,
                "ledger_fingerprint": ledger.ledger_fingerprint,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ledger.customer_evidence_gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
