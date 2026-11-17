"""Supplier scoring from delivery history.

The score answers one planning question: how far can a promise date from this
supplier be trusted? It combines four measures, each scaled to 0-1:

==============  ======  =====================================================
Measure         Weight  Scaled as
==============  ======  =====================================================
On-time rate    0.40    share of deliveries no later than promise + tolerance
Quality         0.30    1 - reject rate / 5 %, floored at 0
Lateness        0.20    1 - average late hours / 48 h, floored at 0
Response        0.10    1 - average response hours / 24 h, floored at 0
==============  ======  =====================================================

A supplier with no response data is scored on the other three, re-weighted.
Fewer than three deliveries gives the tier ``unrated``: the numbers are shown
but should not drive a decision.

``late_p80_minutes`` is the 80th-percentile lateness (on-time deliveries count
as zero). The kit check can add it to a promise date as a risk buffer.
"""

from __future__ import annotations

import math
from collections import defaultdict

from app.models.supply import DeliveryRecord, SupplierScore, SupplySnapshot

WEIGHTS = {"on_time": 0.40, "quality": 0.30, "lateness": 0.20, "response": 0.10}
REJECT_CEILING = 0.05
LATE_HOURS_CEILING = 48.0
RESPONSE_HOURS_CEILING = 24.0
MIN_DELIVERIES = 3
TIER_A = 85.0
TIER_B = 70.0


def _late_minutes(record: DeliveryRecord) -> float:
    return max(0.0, (record.received_at - record.promised_at).total_seconds() / 60.0)


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def score_supplier(
    supplier_id: str,
    name: str,
    records: list[DeliveryRecord],
    *,
    tolerance_minutes: int = 60,
) -> SupplierScore:
    if not records:
        return SupplierScore(
            supplier_id=supplier_id,
            name=name,
            deliveries=0,
            on_time_rate=0.0,
            average_late_hours=0.0,
            late_p80_minutes=0,
            reject_rate=0.0,
            average_response_hours=None,
            score=0.0,
            tier="unrated",
            notes=["no delivery history"],
        )
    lateness = [_late_minutes(record) for record in records]
    late_only = [value for value in lateness if value > tolerance_minutes]
    on_time_rate = 1.0 - len(late_only) / len(records)
    average_late_hours = sum(late_only) / len(late_only) / 60.0 if late_only else 0.0
    total_quantity = sum(record.quantity for record in records)
    reject_rate = sum(record.rejected_quantity for record in records) / total_quantity
    responses = [r.response_hours for r in records if r.response_hours is not None]
    average_response = sum(responses) / len(responses) if responses else None

    parts = {
        "on_time": on_time_rate,
        "quality": max(0.0, 1.0 - reject_rate / REJECT_CEILING),
        "lateness": max(0.0, 1.0 - average_late_hours / LATE_HOURS_CEILING),
    }
    if average_response is not None:
        parts["response"] = max(0.0, 1.0 - average_response / RESPONSE_HOURS_CEILING)
    weight_total = sum(WEIGHTS[key] for key in parts)
    score = 100.0 * sum(WEIGHTS[key] * value for key, value in parts.items()) / weight_total

    notes: list[str] = []
    if len(records) < MIN_DELIVERIES:
        tier = "unrated"
        notes.append(f"only {len(records)} deliveries; at least {MIN_DELIVERIES} needed to rate")
    elif score >= TIER_A:
        tier = "A"
    elif score >= TIER_B:
        tier = "B"
    else:
        tier = "C"
    if average_response is None:
        notes.append("no response data; scored on the other three measures")

    return SupplierScore(
        supplier_id=supplier_id,
        name=name,
        deliveries=len(records),
        on_time_rate=round(on_time_rate, 4),
        average_late_hours=round(average_late_hours, 2),
        late_p80_minutes=round(_percentile(lateness, 0.8)),
        reject_rate=round(reject_rate, 4),
        average_response_hours=round(average_response, 2) if average_response is not None else None,
        score=round(score, 1),
        tier=tier,
        notes=notes,
    )


def score_suppliers(supply: SupplySnapshot, *, tolerance_minutes: int = 60) -> list[SupplierScore]:
    """Score every supplier that appears in the master list or the history."""
    names = {supplier.supplier_id: supplier.name for supplier in supply.suppliers}
    history: dict[str, list[DeliveryRecord]] = defaultdict(list)
    for record in supply.delivery_history:
        history[record.supplier_id].append(record)
    scores = [
        score_supplier(
            supplier_id,
            names.get(supplier_id, supplier_id),
            history.get(supplier_id, []),
            tolerance_minutes=tolerance_minutes,
        )
        for supplier_id in sorted(set(names) | set(history))
    ]
    scores.sort(key=lambda item: (-item.score, item.supplier_id))
    return scores
