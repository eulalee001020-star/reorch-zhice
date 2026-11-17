"""Supply-side planning models.

These describe what the schedule needs from the material side: bills of
material, stock, inbound orders and supplier delivery history. They are the
input of MRP netting and kit checks, whose output feeds the scheduler as
material release times.

Two distinctions carry most of the meaning:

* **Arrived is not usable.** An inbound line that has been received may still
  be blocked by inspection, missing certificates or missing accessories. Each
  blocker is a :class:`ReadinessGap` with an owner and a due time. Only a
  released line counts as stock.
* **Promised is not certain.** A supplier's promise date is an input, and the
  supplier's delivery history says how much to trust it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from app.models.base import ReOrchModel

SupplyOrderStatus = Literal["open", "in_transit", "received", "released", "cancelled"]
ShortageKind = Literal["eta_slip", "quantity_short", "lot_rejected"]


class BomLine(ReOrchModel):
    """One parent-component relation. Quantities are per unit of the parent."""

    parent_item_id: str
    component_item_id: str
    quantity_per: float = Field(gt=0)
    scrap_rate: float = Field(default=0.0, ge=0.0, lt=1.0)


class InventoryRecord(ReOrchModel):
    """Stock position of one item at the snapshot time."""

    item_id: str
    on_hand: float = Field(default=0.0, ge=0.0)
    allocated: float = Field(default=0.0, ge=0.0)
    quality_hold: float = Field(default=0.0, ge=0.0)
    safety_stock: float = Field(default=0.0, ge=0.0)

    @property
    def usable(self) -> float:
        """Stock that can be issued now: on hand minus allocated and held."""
        return max(0.0, self.on_hand - self.allocated - self.quality_hold)


class ReadinessGap(ReOrchModel):
    """Something that keeps received material from being used."""

    gap_id: str
    description: str
    owner: str | None = None
    due_at: datetime | None = None
    closed_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.closed_at is None


class SupplyOrderLine(ReOrchModel):
    """One inbound order line: a purchase, a subcontract return or a transfer."""

    order_id: str
    line_id: str = "1"
    item_id: str
    supplier_id: str | None = None
    quantity: float = Field(gt=0)
    promised_at: datetime
    status: SupplyOrderStatus = "open"
    received_at: datetime | None = None
    released_at: datetime | None = None
    gaps: list[ReadinessGap] = Field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.order_id}/{self.line_id}"


class ItemPlanningParams(ReOrchModel):
    """Per-item planning parameters. Items without a row use the defaults."""

    item_id: str
    lead_time_minutes: int = Field(default=0, ge=0)
    inspection_minutes: int = Field(default=0, ge=0)
    lot_multiple: float = Field(default=0.0, ge=0.0)
    minimum_order_quantity: float = Field(default=0.0, ge=0.0)


class WorkOrderDemand(ReOrchModel):
    """What a work order makes. Its components come from the BOM."""

    work_order_id: str
    item_id: str
    quantity: float = Field(gt=0)


class OperationRequirement(ReOrchModel):
    """A component quantity issued at a specific operation.

    Use this when the requirement is known directly, without a BOM. ``quantity``
    is the total for the operation, not per unit.
    """

    work_order_id: str
    operation_id: str
    item_id: str
    quantity: float = Field(gt=0)


class ComponentIssuePoint(ReOrchModel):
    """Where in a routing a BOM component is issued.

    The operation is found by required capability first, then by 1-based
    position in the work order. A component with no issue point is issued at
    the work order's first operation.
    """

    parent_item_id: str
    component_item_id: str
    capability: str | None = None
    position: int | None = Field(default=None, ge=1)


class Supplier(ReOrchModel):
    supplier_id: str
    name: str


class DeliveryRecord(ReOrchModel):
    """One completed delivery, used to score a supplier."""

    supplier_id: str
    item_id: str
    promised_at: datetime
    received_at: datetime
    quantity: float = Field(gt=0)
    rejected_quantity: float = Field(default=0.0, ge=0.0)
    response_hours: float | None = Field(default=None, ge=0.0)


class SubstituteRule(ReOrchModel):
    """An approved alternative for a component. Unapproved rules are ignored."""

    primary_item_id: str
    substitute_item_id: str
    approved: bool = False
    approved_by: str | None = None
    source_ref: str | None = None


class SupplySnapshot(ReOrchModel):
    """Material-side state captured together with a schedule snapshot."""

    supply_snapshot_id: UUID = Field(default_factory=uuid4)
    captured_at: datetime
    workshop_id: str | None = None
    bom: list[BomLine] = Field(default_factory=list)
    issue_points: list[ComponentIssuePoint] = Field(default_factory=list)
    inventory: list[InventoryRecord] = Field(default_factory=list)
    supply_orders: list[SupplyOrderLine] = Field(default_factory=list)
    planning_params: list[ItemPlanningParams] = Field(default_factory=list)
    work_order_demands: list[WorkOrderDemand] = Field(default_factory=list)
    operation_requirements: list[OperationRequirement] = Field(default_factory=list)
    suppliers: list[Supplier] = Field(default_factory=list)
    delivery_history: list[DeliveryRecord] = Field(default_factory=list)
    substitutes: list[SubstituteRule] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


class MrpBucket(ReOrchModel):
    """One time bucket of an MRP record."""

    bucket_start: datetime
    gross_requirement: float = 0.0
    scheduled_receipt: float = 0.0
    projected_available: float = 0.0
    net_requirement: float = 0.0
    planned_order_receipt: float = 0.0
    planned_order_release: float = 0.0


class MrpRecord(ReOrchModel):
    """Time-phased record for one item."""

    item_id: str
    low_level_code: int
    opening_balance: float
    safety_stock: float
    lead_time_buckets: int
    buckets: list[MrpBucket] = Field(default_factory=list)
    past_due_release: float = 0.0


class MrpResult(ReOrchModel):
    bucket_minutes: int
    horizon_start: datetime
    records: list[MrpRecord] = Field(default_factory=list)


class SupplyLot(ReOrchModel):
    """A quantity of an item that becomes usable at a known or unknown time."""

    item_id: str
    quantity: float
    usable_at: datetime | None
    source: str
    confidence: Literal["on_hand", "released", "arrived_pending", "promised"]
    open_gap_ids: list[str] = Field(default_factory=list)


class RequirementCoverage(ReOrchModel):
    """How one component requirement of one operation is covered."""

    work_order_id: str
    operation_id: str
    item_id: str
    required_quantity: float
    covered_quantity: float
    ready_at: datetime | None
    sources: list[str] = Field(default_factory=list)

    @property
    def shortage(self) -> float:
        return max(0.0, self.required_quantity - self.covered_quantity)


class OperationKit(ReOrchModel):
    """Kit status of one operation: every component it needs, together."""

    work_order_id: str
    operation_id: str
    planned_start: datetime
    is_complete: bool
    ready_at: datetime | None
    wait_minutes: float
    requirements: list[RequirementCoverage] = Field(default_factory=list)


class KitReport(ReOrchModel):
    """Kit check of a whole schedule against a supply snapshot."""

    supply_snapshot_id: UUID
    reference_time: datetime
    operations: list[OperationKit] = Field(default_factory=list)
    kit_rate: float = 1.0
    on_time_kit_rate: float = 1.0
    late_operation_ids: list[str] = Field(default_factory=list)
    unresolved_operation_ids: list[str] = Field(default_factory=list)


class ReadinessLine(ReOrchModel):
    """Two-layer status of one inbound line: arrived, and usable."""

    order_key: str
    item_id: str
    supplier_id: str | None
    quantity: float
    arrived: bool
    usable: bool
    arrived_at: datetime | None
    usable_at: datetime | None
    open_gaps: list[ReadinessGap] = Field(default_factory=list)
    overdue_gap_ids: list[str] = Field(default_factory=list)


class ReadinessReport(ReOrchModel):
    reference_time: datetime
    lines: list[ReadinessLine] = Field(default_factory=list)
    arrived_count: int = 0
    usable_count: int = 0
    arrived_not_usable_count: int = 0
    open_gap_count: int = 0
    overdue_gap_count: int = 0
    unowned_gap_count: int = 0


class SupplierScore(ReOrchModel):
    supplier_id: str
    name: str
    deliveries: int
    on_time_rate: float
    average_late_hours: float
    late_p80_minutes: int
    reject_rate: float
    average_response_hours: float | None
    score: float
    tier: Literal["A", "B", "C", "unrated"]
    notes: list[str] = Field(default_factory=list)


class MaterialShortageEvent(ReOrchModel):
    """A supply disruption expressed against the supply snapshot."""

    item_id: str
    kind: ShortageKind = "eta_slip"
    order_id: str | None = None
    line_id: str | None = None
    new_promised_at: datetime | None = None
    short_quantity: float | None = Field(default=None, gt=0)


class MaterialImpact(ReOrchModel):
    """What a shortage event does to the kit status of the schedule."""

    event: MaterialShortageEvent
    affected_order_keys: list[str] = Field(default_factory=list)
    before: KitReport
    after: KitReport
    newly_late_operation_ids: list[str] = Field(default_factory=list)
    newly_unresolved_operation_ids: list[str] = Field(default_factory=list)
    approved_substitutes: list[SubstituteRule] = Field(default_factory=list)
