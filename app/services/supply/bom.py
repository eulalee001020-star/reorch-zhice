"""Bill-of-material structure: low-level codes and requirement explosion."""

from __future__ import annotations

from collections import defaultdict

from app.models.supply import BomLine


class BomCycleError(ValueError):
    """Raised when an item is, directly or indirectly, a component of itself."""


def children_by_parent(bom: list[BomLine]) -> dict[str, list[BomLine]]:
    index: dict[str, list[BomLine]] = defaultdict(list)
    for line in bom:
        index[line.parent_item_id].append(line)
    return dict(index)


def low_level_codes(bom: list[BomLine]) -> dict[str, int]:
    """Return each item's low-level code: its deepest position in any BOM.

    End items have code 0. MRP must process items in ascending code so that
    every parent's planned orders exist before its components are netted.
    """
    parents: dict[str, set[str]] = defaultdict(set)
    items: set[str] = set()
    for line in bom:
        parents[line.component_item_id].add(line.parent_item_id)
        items.update((line.parent_item_id, line.component_item_id))

    codes: dict[str, int] = {}
    visiting: list[str] = []

    def code_of(item: str) -> int:
        if item in codes:
            return codes[item]
        if item in visiting:
            cycle = visiting[visiting.index(item) :]
            raise BomCycleError(" -> ".join([*cycle, item]))
        visiting.append(item)
        value = 1 + max((code_of(parent) for parent in parents.get(item, ())), default=-1)
        visiting.pop()
        codes[item] = value
        return value

    for item in sorted(items):
        code_of(item)
    return codes


def gross_quantity(line: BomLine, parent_quantity: float) -> float:
    """Component quantity needed for ``parent_quantity`` parents, with scrap."""
    return parent_quantity * line.quantity_per / (1.0 - line.scrap_rate)


def explode(bom: list[BomLine], item_id: str, quantity: float) -> dict[str, float]:
    """Total quantity of every component under ``item_id``, all levels."""
    children = children_by_parent(bom)
    low_level_codes(bom)  # raises on cycles before the walk below
    totals: dict[str, float] = defaultdict(float)

    def walk(parent: str, parent_quantity: float) -> None:
        for line in children.get(parent, []):
            needed = gross_quantity(line, parent_quantity)
            totals[line.component_item_id] += needed
            walk(line.component_item_id, needed)

    walk(item_id, quantity)
    return dict(totals)
