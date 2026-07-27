"""Constraint calibration models for P0 customer onboarding."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.models.agent import ConstraintCandidate
from app.models.base import ReOrchModel
from app.models.planning import (
    ChangeoverRuleInput,
    InitialScheduleRequest,
    ResourceCalendarWindowInput,
)


class MachineCapabilityCalibration(ReOrchModel):
    """Human-confirmed capability matrix entry for one resource."""

    resource_id: str
    capabilities: list[str] = Field(default_factory=list)
    approval_status: str = "approved"
    approved_by: str | None = None
    source_refs: list[str] = Field(default_factory=list)


class ResourceCalendarCalibration(ReOrchModel):
    """Human-confirmed resource calendar entry."""

    resource_id: str
    window_start: datetime
    window_end: datetime
    availability_type: str = "unavailable"
    reason: str | None = None
    approval_status: str = "approved"
    approved_by: str | None = None
    source_refs: list[str] = Field(default_factory=list)


class FreezeWindowCalibration(ReOrchModel):
    """Human-confirmed freeze window that must be respected during repair."""

    window_start: datetime
    window_end: datetime
    resource_id: str | None = None
    operation_id: str | None = None
    reason: str | None = None
    approval_status: str = "approved"
    approved_by: str | None = None
    source_refs: list[str] = Field(default_factory=list)


class ChangeoverCalibration(ReOrchModel):
    """Human-confirmed sequence-dependent setup rule."""

    from_product_family: str
    to_product_family: str
    setup_minutes: int
    cost: float = Field(default=0.0, ge=0.0)
    resource_id: str | None = None
    approval_status: str = "approved"
    approved_by: str | None = None
    source_refs: list[str] = Field(default_factory=list)


class ReviewedConstraintCandidateInput(ReOrchModel):
    """AI or planner-feedback rule candidate plus review/replay state."""

    candidate: ConstraintCandidate
    review_status: str = "pending_human_review"
    replay_passed: bool = False
    reviewer_id: str | None = None
    source_refs: list[str] = Field(default_factory=list)


class ConstraintCalibrationPack(ReOrchModel):
    """Constraint pack compiled after P0 data mapping and site interviews."""

    workshop_id: str
    base_request: InitialScheduleRequest | None = None
    machine_capabilities: list[MachineCapabilityCalibration] = Field(default_factory=list)
    resource_calendars: list[ResourceCalendarCalibration] = Field(default_factory=list)
    freeze_windows: list[FreezeWindowCalibration] = Field(default_factory=list)
    changeovers: list[ChangeoverCalibration] = Field(default_factory=list)
    rule_candidates: list[ReviewedConstraintCandidateInput] = Field(default_factory=list)


class ConstraintCalibrationConflict(ReOrchModel):
    """Compile-time finding for a calibrated constraint pack."""

    code: str
    severity: str
    message: str
    entity_type: str | None = None
    entity_id: str | None = None
    source_refs: list[str] = Field(default_factory=list)


class CompiledConstraintCalibration(ReOrchModel):
    """Result of compiling calibrated constraints into scheduler-ready inputs."""

    workshop_id: str
    blocked: bool
    applied_constraint_count: int
    omitted_candidate_count: int
    resource_capabilities: dict[str, list[str]] = Field(default_factory=dict)
    resource_calendar: list[ResourceCalendarWindowInput] = Field(default_factory=list)
    changeover_rules: list[ChangeoverRuleInput] = Field(default_factory=list)
    freeze_windows: list[dict] = Field(default_factory=list)
    raw_data_patch: dict = Field(default_factory=dict)
    conflicts: list[ConstraintCalibrationConflict] = Field(default_factory=list)
    initial_schedule_request: InitialScheduleRequest | None = None
