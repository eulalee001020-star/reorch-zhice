"""Load a supply snapshot from a directory of CSV files.

Every file is optional except that a snapshot with no files is empty. The
expected files and their columns mirror the models in ``app.models.supply``:

``bom.csv``, ``issue_points.csv``, ``inventory.csv``, ``supply_orders.csv``,
``readiness_gaps.csv``, ``planning_params.csv``, ``suppliers.csv``,
``delivery_history.csv``, ``substitutes.csv``.

Work order demands come from the schedule's own ``work_orders.csv``
(``work_order_id``, ``product_id``, ``quantity``).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models.supply import (
    BomLine,
    ComponentIssuePoint,
    DeliveryRecord,
    InventoryRecord,
    ItemPlanningParams,
    ReadinessGap,
    SubstituteRule,
    Supplier,
    SupplyOrderLine,
    SupplySnapshot,
    WorkOrderDemand,
)


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            {key: (value if value != "" else None) for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def _present(row: dict[str, Any]) -> dict[str, Any]:
    """Drop empty cells so that model defaults apply."""
    return {key: value for key, value in row.items() if value is not None}


def load_supply_snapshot(
    directory: Path,
    *,
    captured_at: datetime,
    work_orders_csv: Path | None = None,
    workshop_id: str | None = None,
) -> SupplySnapshot:
    gaps: dict[tuple[str, str], list[ReadinessGap]] = defaultdict(list)
    for row in _rows(directory / "readiness_gaps.csv"):
        data = _present(row)
        key = (data.pop("order_id"), data.pop("line_id", "1"))
        gaps[key].append(ReadinessGap(**data))

    supply_orders = []
    for row in _rows(directory / "supply_orders.csv"):
        data = _present(row)
        line = SupplyOrderLine(**data)
        line.gaps = gaps.get((line.order_id, line.line_id), [])
        supply_orders.append(line)

    demands = []
    if work_orders_csv is not None:
        for row in _rows(work_orders_csv):
            if row.get("product_id") and row.get("quantity"):
                demands.append(
                    WorkOrderDemand(
                        work_order_id=row["work_order_id"],
                        item_id=row["product_id"],
                        quantity=float(row["quantity"]),
                    )
                )

    def load(name: str, model: type) -> list:
        return [model(**_present(row)) for row in _rows(directory / name)]

    return SupplySnapshot(
        captured_at=captured_at,
        workshop_id=workshop_id,
        bom=load("bom.csv", BomLine),
        issue_points=load("issue_points.csv", ComponentIssuePoint),
        inventory=load("inventory.csv", InventoryRecord),
        supply_orders=supply_orders,
        planning_params=load("planning_params.csv", ItemPlanningParams),
        work_order_demands=demands,
        suppliers=load("suppliers.csv", Supplier),
        delivery_history=load("delivery_history.csv", DeliveryRecord),
        substitutes=load("substitutes.csv", SubstituteRule),
    )
