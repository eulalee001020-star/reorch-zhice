"""Customer non-equipment constraint data contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.models.base import ReOrchModel


class MaterialAvailabilityRow(ReOrchModel):
    material_id: str
    operation_ids: list[str] = Field(default_factory=list)
    work_order_ids: list[str] = Field(default_factory=list)
    available_quantity: float = Field(default=0.0, ge=0.0)
    required_quantity: float = Field(default=1.0, gt=0.0)
    available_at: datetime | None = None
    source_ref: str | None = None


class QualityHoldRow(ReOrchModel):
    hold_id: str
    blocked_operation_ids: list[str] = Field(default_factory=list)
    work_order_ids: list[str] = Field(default_factory=list)
    status: str = "held"
    release_at: datetime | None = None
    quality_owner: str | None = None
    source_ref: str | None = None


class ToolingCalendarRow(ReOrchModel):
    tooling_id: str
    operation_ids: list[str] = Field(default_factory=list)
    quantity: int = Field(default=1, ge=0)
    unavailable_start: datetime | None = None
    unavailable_end: datetime | None = None
    source_ref: str | None = None


class LaborSkillCapacityRow(ReOrchModel):
    skill_code: str
    operation_ids: list[str] = Field(default_factory=list)
    available_headcount: int = Field(default=1, ge=0)
    window_start: datetime | None = None
    window_end: datetime | None = None
    workshop_id: str | None = None
    source_ref: str | None = None


class UrgentOrderConstraintRow(ReOrchModel):
    rush_order_id: str
    work_order_id: str
    due_time: datetime
    priority_boost: int = Field(default=5, ge=0)
    displacement_cost_per_minute: int = Field(default=1, ge=0)
    customer_service_approved: bool = False
    source_ref: str | None = None


class TransportLaneRow(ReOrchModel):
    lane_id: str
    predecessor_operation_id: str
    successor_operation_id: str
    transport_mode: str = "AMR"
    capacity: int = Field(default=1, gt=0)
    eta_minutes: int = Field(default=0, ge=0)
    source_ref: str | None = None


class BufferFlowRow(ReOrchModel):
    buffer_id: str
    predecessor_operation_id: str
    successor_operation_id: str
    capacity: int = Field(gt=0)
    current_wip: int = Field(default=0, ge=0)
    occupancy_quantity: int = Field(default=1, gt=0)
    source_ref: str | None = None


class OutsourcingApprovalRow(ReOrchModel):
    vendor_id: str
    operation_ids: list[str] = Field(default_factory=list)
    resource_id: str | None = None
    capability_codes: list[str] = Field(default_factory=list)
    lead_time_minutes: int = Field(gt=0)
    capacity_per_day: int = Field(default=1, gt=0)
    approval_status: str = "pending"
    approved_by: str | None = None
    valid_until: datetime | None = None
    source_ref: str | None = None


class SubstituteMaterialApprovalRow(ReOrchModel):
    primary_material_id: str
    substitute_material_id: str
    operation_ids: list[str] = Field(default_factory=list)
    approval_status: str = "pending"
    available_quantity: float = Field(default=0.0, ge=0.0)
    required_quantity: float = Field(default=1.0, gt=0.0)
    available_at: datetime | None = None
    approved_by: str | None = None
    source_ref: str | None = None


class BatchGenealogyRow(ReOrchModel):
    batch_id: str
    parent_batch_id: str | None = None
    operation_ids: list[str] = Field(default_factory=list)
    parent_operation_ids: list[str] = Field(default_factory=list)
    quality_state: str = "released"
    release_at: datetime | None = None
    rework_required: bool = False
    rework_operation_id: str | None = None
    source_ref: str | None = None


class QmsReleaseGateRow(ReOrchModel):
    gate_id: str
    operation_ids: list[str] = Field(default_factory=list)
    batch_ids: list[str] = Field(default_factory=list)
    status: str = "pending"
    release_at: datetime | None = None
    required_approvals: list[str] = Field(default_factory=list)
    approvals: list[str] = Field(default_factory=list)
    certificate_ref: str | None = None
    source_ref: str | None = None


class CustomerConstraintPack(ReOrchModel):
    material_availability: list[MaterialAvailabilityRow] = Field(default_factory=list)
    quality_holds: list[QualityHoldRow] = Field(default_factory=list)
    tooling_calendar: list[ToolingCalendarRow] = Field(default_factory=list)
    labor_skill_capacity: list[LaborSkillCapacityRow] = Field(default_factory=list)
    urgent_order_constraints: list[UrgentOrderConstraintRow] = Field(default_factory=list)
    transport_lanes: list[TransportLaneRow] = Field(default_factory=list)
    buffer_flows: list[BufferFlowRow] = Field(default_factory=list)
    outsourcing_approvals: list[OutsourcingApprovalRow] = Field(default_factory=list)
    substitute_material_approvals: list[SubstituteMaterialApprovalRow] = Field(
        default_factory=list
    )
    batch_genealogy: list[BatchGenealogyRow] = Field(default_factory=list)
    qms_release_gates: list[QmsReleaseGateRow] = Field(default_factory=list)

    def as_raw_data(self) -> dict:
        return self.model_dump(mode="json")
