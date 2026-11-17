"""Time-phased MRP netting.

The record logic is the textbook one. For each item and bucket::

    projected[t] = projected[t-1] + scheduled_receipt[t]
                   + planned_receipt[t] - gross[t]

A planned receipt is created in the first bucket where the projected balance
would fall below safety stock, sized by the lot rule, and released one lead
time earlier. Items are processed in low-level-code order, and each planned
order release of a parent becomes a gross requirement of its components in
the same bucket.

Work orders are treated as firm: they are not re-planned here. Their
component requirements enter as gross requirements at the start of the
operation that issues them.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta

from app.models.supply import (
    InventoryRecord,
    ItemPlanningParams,
    MrpBucket,
    MrpRecord,
    MrpResult,
    SupplySnapshot,
)
from app.services.supply.bom import children_by_parent, gross_quantity, low_level_codes

EPSILON = 1e-9


def lot_size(net: float, params: ItemPlanningParams | None) -> float:
    """Apply minimum order quantity and lot multiple to a net requirement."""
    if net <= EPSILON:
        return 0.0
    quantity = net
    if params is None:
        return quantity
    quantity = max(quantity, params.minimum_order_quantity)
    if params.lot_multiple > EPSILON:
        quantity = math.ceil(quantity / params.lot_multiple - EPSILON) * params.lot_multiple
    return quantity


def _bucket_index(moment: datetime, start: datetime, bucket_minutes: int, count: int) -> int:
    offset = (moment - start).total_seconds() / 60.0
    return min(count - 1, max(0, int(offset // bucket_minutes)))


def run_mrp(
    snapshot: SupplySnapshot,
    requirements: list[tuple[str, float, datetime]],
    *,
    bucket_minutes: int = 1440,
    bucket_count: int = 14,
    horizon_start: datetime | None = None,
) -> MrpResult:
    """Net ``requirements`` against stock and inbound orders.

    ``requirements`` are independent gross requirements as
    ``(item_id, quantity, needed_at)``.
    """
    if bucket_minutes <= 0 or bucket_count <= 0:
        raise ValueError("bucket_minutes and bucket_count must be positive")
    start = horizon_start or snapshot.captured_at
    codes = low_level_codes(snapshot.bom)
    children = children_by_parent(snapshot.bom)
    inventory: dict[str, InventoryRecord] = {row.item_id: row for row in snapshot.inventory}
    params: dict[str, ItemPlanningParams] = {row.item_id: row for row in snapshot.planning_params}

    gross: dict[str, list[float]] = defaultdict(lambda: [0.0] * bucket_count)
    receipts: dict[str, list[float]] = defaultdict(lambda: [0.0] * bucket_count)
    for item_id, quantity, needed_at in requirements:
        gross[item_id][_bucket_index(needed_at, start, bucket_minutes, bucket_count)] += quantity
    for line in snapshot.supply_orders:
        if line.status in {"released", "cancelled"}:
            continue
        index = _bucket_index(line.promised_at, start, bucket_minutes, bucket_count)
        receipts[line.item_id][index] += line.quantity

    items = set(gross) | set(receipts) | set(inventory) | set(codes)
    records: list[MrpRecord] = []
    for item_id in sorted(items, key=lambda item: (codes.get(item, 0), item)):
        stock = inventory.get(item_id)
        item_params = params.get(item_id)
        safety = stock.safety_stock if stock else 0.0
        opening = stock.usable if stock else 0.0
        lead_buckets = (
            math.ceil(item_params.lead_time_minutes / bucket_minutes) if item_params else 0
        )
        balance = opening
        buckets: list[MrpBucket] = []
        planned_receipts = [0.0] * bucket_count
        planned_releases = [0.0] * bucket_count
        past_due = 0.0
        for index in range(bucket_count):
            available = balance + receipts[item_id][index] - gross[item_id][index]
            net = max(0.0, safety - available)
            receipt = lot_size(net, item_params)
            if receipt > EPSILON:
                planned_receipts[index] = receipt
                release_index = index - lead_buckets
                if release_index < 0:
                    past_due += receipt
                else:
                    planned_releases[release_index] += receipt
                available += receipt
            balance = available
            buckets.append(
                MrpBucket(
                    bucket_start=start + timedelta(minutes=bucket_minutes * index),
                    gross_requirement=round(gross[item_id][index], 6),
                    scheduled_receipt=round(receipts[item_id][index], 6),
                    projected_available=round(balance, 6),
                    net_requirement=round(net, 6),
                    planned_order_receipt=round(receipt, 6),
                )
            )
        for index, bucket in enumerate(buckets):
            bucket.planned_order_release = round(planned_releases[index], 6)
        # A parent's planned order release is a gross requirement of its
        # components in the same bucket. Past-due releases land in bucket 0.
        for line in children.get(item_id, []):
            component = gross[line.component_item_id]
            if past_due > EPSILON:
                component[0] += gross_quantity(line, past_due)
            for index, release in enumerate(planned_releases):
                if release > EPSILON:
                    component[index] += gross_quantity(line, release)
        records.append(
            MrpRecord(
                item_id=item_id,
                low_level_code=codes.get(item_id, 0),
                opening_balance=round(opening, 6),
                safety_stock=safety,
                lead_time_buckets=lead_buckets,
                buckets=buckets,
                past_due_release=round(past_due, 6),
            )
        )
    return MrpResult(bucket_minutes=bucket_minutes, horizon_start=start, records=records)
