"""P0 Reality Harness models.

The harness is the customer-data gate before replay, shadow mode, or any
planning run. It deliberately does not create writeback permission.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from app.adapters.mapping_schema import AdapterMappingProfile
from app.adapters.mapping_validator import CanonicalDataset, MappingValidationReport
from app.models.base import ReOrchModel
from app.models.planning import DataReadinessReport
from app.models.schedule import ScheduleSnapshot

RealityPermissionLevel = Literal[
    "stop",
    "repair_only",
    "replay_only",
    "shadow_ready",
]


class P0RealityHarnessRequest(ReOrchModel):
    """Raw customer payload pack for P0 read-only validation."""

    source_system: str = "customer_p0_pack"
    workshop_id: str = "P0-WORKSHOP"
    planning_start: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    raw_work_orders: list[dict] = Field(default_factory=list)
    raw_operations: list[dict] = Field(default_factory=list)
    raw_machines: list[dict] = Field(default_factory=list)
    raw_incidents: list[dict] = Field(default_factory=list)
    profile: AdapterMappingProfile = Field(default_factory=AdapterMappingProfile)


class FieldMappingCompileRequest(ReOrchModel):
    """Raw sample rows used to propose an adapter mapping profile."""

    source_system: str = "customer_sample"
    raw_work_orders: list[dict] = Field(default_factory=list)
    raw_operations: list[dict] = Field(default_factory=list)
    raw_machines: list[dict] = Field(default_factory=list)
    raw_incidents: list[dict] = Field(default_factory=list)


class FieldMappingSuggestion(ReOrchModel):
    """One conservative mapping suggestion for customer review."""

    entity_type: str
    canonical_field: str
    source_field: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    requires_human_confirmation: bool = True


class FieldMappingCompileResponse(ReOrchModel):
    """Suggested mapping profile and unresolved required fields."""

    source_system: str
    profile: AdapterMappingProfile
    suggestions: list[FieldMappingSuggestion] = Field(default_factory=list)
    unmapped_required_fields: list[str] = Field(default_factory=list)


class RealityHarnessPermission(ReOrchModel):
    """Action ceiling derived from customer-data quality and traceability."""

    level: RealityPermissionLevel
    allow_candidate_generation: bool = False
    allow_historical_replay: bool = False
    allow_shadow_mode: bool = False
    allow_writeback: bool = False
    reasons: list[str] = Field(default_factory=list)
    required_next_actions: list[str] = Field(default_factory=list)


class RealityHarnessAuditStep(ReOrchModel):
    """Small audit trace for customer-data onboarding."""

    step: str
    status: str
    evidence: dict = Field(default_factory=dict)


class P0RealityHarnessResponse(ReOrchModel):
    """Result of P0 customer-data readiness validation."""

    source_system: str
    workshop_id: str
    dataset: CanonicalDataset
    mapping_report: MappingValidationReport
    readiness_report: DataReadinessReport
    permission: RealityHarnessPermission
    snapshot: ScheduleSnapshot | None = None
    audit_steps: list[RealityHarnessAuditStep] = Field(default_factory=list)
