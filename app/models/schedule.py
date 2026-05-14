"""Schedule-related Pydantic models for the ReOrch system.

Defines ScheduleSnapshot, ScheduleDetail (with nested WorkOrder,
Operation, Resource), and GanttDiffPayload used across the
optimization and visualization layers.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import Field

from app.models.base import ReOrchModel


# ---------------------------------------------------------------------------
# Nested structures for ScheduleDetail
# ---------------------------------------------------------------------------


class Resource(ReOrchModel):
    """Production resource (equipment / device)."""

    resource_id: str
    name: str
    capabilities: list[str] = Field(default_factory=list)
    is_bottleneck: bool = False
    has_redundancy: bool = False
    criticality: str = "general"


class Operation(ReOrchModel):
    """Single operation (process step) within a WorkOrder."""

    operation_id: str
    work_order_id: str
    resource_id: str
    required_capabilities: list[str] = Field(default_factory=list)
    start_time: datetime
    end_time: datetime
    predecessor_ids: list[str] = Field(default_factory=list)
    successor_ids: list[str] = Field(default_factory=list)
    is_affected: bool = False
    is_adjusted: bool = False


class WorkOrder(ReOrchModel):
    """Production work order containing a sequence of operations."""

    work_order_id: str
    product_name: str
    due_date: datetime
    operations: list[Operation] = Field(default_factory=list)
    priority: int = 0


# ---------------------------------------------------------------------------
# Top-level schedule models
# ---------------------------------------------------------------------------


class ScheduleDetail(ReOrchModel):
    """Structured schedule data for a candidate plan or snapshot."""

    work_orders: list[WorkOrder] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)


class ScheduleSnapshot(ReOrchModel):
    """Immutable schedule state captured at anomaly time."""

    snapshot_id: UUID = Field(default_factory=uuid4)
    captured_at: datetime
    workshop_id: str
    source_system: Optional[str] = None
    schema_version: str = "1.0"
    snapshot_version: int = 1
    parent_snapshot_id: Optional[UUID] = None
    baseline_snapshot_id: Optional[UUID] = None
    import_batch_id: Optional[str] = None
    snapshot_hash: Optional[str] = None
    is_active: bool = True
    created_by: Optional[str] = None
    work_orders: list[WorkOrder] = Field(default_factory=list)
    raw_data: Optional[dict] = None


# ---------------------------------------------------------------------------
# Gantt diff payload
# ---------------------------------------------------------------------------


class GanttDiffPayload(ReOrchModel):
    """Data driving the diff-gantt visualisation between baseline and plan."""

    baseline_snapshot_id: str
    candidate_plan_id: str
    adjusted_operations: list[dict] = Field(default_factory=list)
    time_shifts: list[dict] = Field(default_factory=list)
    resource_switches: list[dict] = Field(default_factory=list)
    critical_path_changes: list[dict] = Field(default_factory=list)
