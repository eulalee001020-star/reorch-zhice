"""Reproducible travel fit, explicit economic penalties and held-out buffer check.

This does not learn business preferences from routing outcomes. Penalties must
come from an attributed cost ledger, expressed in one currency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from app.models.dispatch import DispatchCostWeights


def _number(value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("observations must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(
            "observations must be finite and non-negative (distance/time strictly positive)"
        )
    return number


def calibrate(document: dict) -> dict:
    if not isinstance(document.get("source"), str) or not document["source"].strip():
        raise ValueError("an attributed data source is required")
    train, holdout = [], []
    for row in document["drives"]:
        if row["split"] not in {"train", "holdout"}:
            raise ValueError("each drive must declare train or holdout")
        pair = (_number(row["km"], positive=True), _number(row["minutes"], positive=True))
        (train if row["split"] == "train" else holdout).append(pair)
    if len(train) < 3 or not holdout:
        raise ValueError("at least three training drives and one holdout are required")
    # Least squares with zero intercept: observations contain driving time only.
    minutes_per_km = sum(km * minutes for km, minutes in train) / sum(km * km for km, _ in train)
    rates = document["cost_rates"]
    distance_cost = _number(rates["distance_per_km"], positive=True)
    weights = DispatchCostWeights(
        **{
            key: _number(rates[column]) / distance_cost
            for key, column in {
                "late": "late_per_minute",
                "overtime": "overtime_per_minute",
                "vehicle": "vehicle_per_trip",
                "unserved": "unserved_per_shipment",
            }.items()
        }
    )
    supplier = document["supplier_late_minutes"]
    history = sorted(_number(value) for value in supplier["train"])
    future = [_number(value) for value in supplier["holdout"]]
    if len(history) < 3 or not future:
        raise ValueError("supplier buffer requires training history and separate holdout")
    buffer = history[math.ceil(0.8 * len(history)) - 1]
    return {
        "source": document["source"],
        "input_sha256": hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest(),
        "dispatch_parameters": {
            "speed_kmh": round(60 / minutes_per_km, 6),
            "cost_weights": weights.model_dump(),
        },
        "travel_validation": {
            "train_count": len(train),
            "holdout_count": len(holdout),
            "holdout_mae_minutes": round(
                sum(abs(km * minutes_per_km - minutes) for km, minutes in holdout) / len(holdout), 6
            ),
        },
        "supplier_buffer_validation": {
            "train_count": len(history),
            "holdout_count": len(future),
            "late_p80_minutes": buffer,
            "holdout_coverage": sum(value <= buffer for value in future) / len(future),
        },
        "sensitivity_cost_weights": {
            str(factor): {
                key: round(value * factor, 6) for key, value in weights.model_dump().items()
            }
            for factor in (0.5, 1.0, 2.0)
        },
        "claim_boundary": "Test calibration only. Supplier score weights/SLA thresholds require labelled business decisions; no automatic promotion. Travel assumes planar distance and excludes service/wait time.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observations", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = calibrate(json.loads(args.observations.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
