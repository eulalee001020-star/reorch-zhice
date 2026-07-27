"""Recovery operator models for non-equipment production exceptions."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.base import ReOrchModel


NonEquipmentIncidentType = Literal[
    "material_shortage",
    "urgent_order_insert",
    "quality_hold",
    "tooling_conflict",
    "labor_shortage",
    "operator_skill_shortage",
]


class RecoveryOperatorRequest(ReOrchModel):
    """Minimal replay input for one non-equipment incident."""

    case_id: str
    incident_type: NonEquipmentIncidentType
    affected_operation_id: str
    affected_work_order_id: str | None = None
    context: dict[str, object] = Field(default_factory=dict)
    top_n: int = Field(default=3, ge=1, le=5)


class RecoveryOperatorGateReport(ReOrchModel):
    pass_gate: bool
    hard_blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    required_human_approvals: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    decision_boundary: str


class RecoveryOperatorCandidate(ReOrchModel):
    operator_id: str
    action_type: str
    description: str
    expected_effect: str
    gate_report: RecoveryOperatorGateReport


class RecoveryOperatorResponse(ReOrchModel):
    case_id: str
    incident_type: NonEquipmentIncidentType
    candidates: list[RecoveryOperatorCandidate] = Field(default_factory=list)
    recommended_operator_id: str | None = None
    can_enter_planner_review: bool = False
    claim_boundary: str


class RecoveryOperatorReplayCase(ReOrchModel):
    request: RecoveryOperatorRequest
    manual_accepted_operator_id: str | None = None


class RecoveryOperatorReplaySummary(ReOrchModel):
    replayed_case_count: int
    cases_with_gate_pass: int
    gate_pass_rate: float
    top_n_manual_coverage_count: int
    top_n_manual_coverage_rate: float
    responses: list[RecoveryOperatorResponse] = Field(default_factory=list)
