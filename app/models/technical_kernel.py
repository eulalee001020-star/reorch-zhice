"""Constraint-to-Recovery technical kernel models."""

from __future__ import annotations

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.incident import Incident
from app.models.impact import ImpactReport
from app.models.planning import DataReadinessReport, PlanQualityGateReport
from app.models.replay_validation import ReplayValidationResponse
from app.models.schedule import ScheduleSnapshot
from app.models.shadow_mode import ShadowCaseCaptureResponse
from app.models.solver import CandidatePlan


class DecisionGraphNode(ReOrchModel):
    """One entity in the production decision graph."""

    node_id: str
    node_type: str
    label: str
    attributes: dict = Field(default_factory=dict)


class DecisionGraphEdge(ReOrchModel):
    """Directed relationship between production graph entities."""

    source_id: str
    target_id: str
    edge_type: str
    attributes: dict = Field(default_factory=dict)


class DecisionGraph(ReOrchModel):
    """Order-operation-resource graph reconstructed from a schedule snapshot."""

    snapshot_id: str
    workshop_id: str
    nodes: list[DecisionGraphNode] = Field(default_factory=list)
    edges: list[DecisionGraphEdge] = Field(default_factory=list)


class DecisionGraphBuildRequest(ReOrchModel):
    """Build an auditable decision graph and affected subgraph."""

    snapshot: ScheduleSnapshot
    incident: Incident | None = None
    freeze_operation_ids: list[str] = Field(default_factory=list)


class DecisionGraphBuildResponse(ReOrchModel):
    """Decision graph with anomaly impact and repairable frontier."""

    graph: DecisionGraph
    affected_operation_ids: list[str] = Field(default_factory=list)
    downstream_operation_ids: list[str] = Field(default_factory=list)
    repairable_frontier_ids: list[str] = Field(default_factory=list)
    alternative_resources: dict[str, list[str]] = Field(default_factory=dict)
    metrics: dict[str, int | float | str] = Field(default_factory=dict)


class RecoveryOperatorRequest(ReOrchModel):
    """Select recovery operators from incident impact and graph evidence."""

    incident: Incident
    impact_report: ImpactReport | None = None
    decision_graph: DecisionGraphBuildResponse
    allowed_operator_types: list[str] = Field(default_factory=list)
    max_operator_count: int = Field(default=5, ge=1, le=12)


class RecoveryOperatorRecommendation(ReOrchModel):
    """One recovery operator option before solving."""

    operator_type: str
    label: str
    algorithm_family: str
    solver_backend: str
    scope: str
    rank: int
    why_selected: list[str] = Field(default_factory=list)
    required_gates: list[str] = Field(default_factory=list)
    expected_metrics: list[str] = Field(default_factory=list)
    llm_role: str = "No final scheduling authority; explanation and rule-candidate support only."


class RecoveryOperatorResponse(ReOrchModel):
    """Recovery operator portfolio selected for one incident."""

    incident_id: str
    repair_scope: str
    recommendations: list[RecoveryOperatorRecommendation] = Field(default_factory=list)
    rejected_operator_types: list[str] = Field(default_factory=list)
    claim_boundary: str = (
        "Operators generate candidate repair paths; solver, gates, and planner "
        "confirmation decide whether a plan is usable."
    )


class EvidenceGateFinding(ReOrchModel):
    """One gate finding for candidate-plan safety."""

    gate_name: str
    status: str
    severity: str
    message: str
    source_refs: list[str] = Field(default_factory=list)


class EvidenceGateRequest(ReOrchModel):
    """Evaluate whether candidates may be recommended, shown, or written back."""

    data_readiness: DataReadinessReport | None = None
    candidate_plans: list[CandidatePlan] = Field(default_factory=list)
    quality_gates: list[PlanQualityGateReport] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    replay_validation: ReplayValidationResponse | None = None
    shadow_capture: ShadowCaseCaptureResponse | None = None
    planner_confirmed: bool = False


class EvidenceGateResponse(ReOrchModel):
    """Unified Data/Constraint/Evidence/Policy/Writeback gate result."""

    allow_solve: bool
    allow_recommendation: bool
    allow_formal_explanation: bool
    allow_shadow: bool
    allow_writeback: bool
    overall_status: str
    findings: list[EvidenceGateFinding] = Field(default_factory=list)
    recommendation_policy: str
