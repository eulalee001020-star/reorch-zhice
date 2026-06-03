"""NGS laboratory repair scheduling domain models."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import Field

from app.models.base import ReOrchModel


class NgsSample(ReOrchModel):
    """A lab sample or case with a TAT commitment."""

    sample_id: str
    assay: str
    priority: str = "routine"
    arrival_time: datetime
    due_time: datetime
    risk_class: str = "standard"
    max_hold_minutes: int | None = None


class NgsEntity(ReOrchModel):
    """Traceable lab entity in the sample lineage."""

    entity_id: str
    entity_type: str
    sample_id: str
    parent_entity_ids: list[str] = Field(default_factory=list)


class NgsOperation(ReOrchModel):
    """Scheduled lab operation in the multi-entity DAG."""

    operation_id: str
    sample_id: str
    entity_id: str
    stage: str
    duration_minutes: int = Field(gt=0)
    eligible_resource_ids: list[str] = Field(default_factory=list)
    predecessor_ids: list[str] = Field(default_factory=list)
    planned_start: datetime
    planned_end: datetime
    resource_id: str
    reagent_lot_id: str | None = None
    pool_id: str | None = None
    run_id: str | None = None
    index_id: str | None = None
    qc_status: str | None = None
    zone: str | None = None
    frozen_flag: bool = False


class NgsResourceWindow(ReOrchModel):
    """Unavailable resource window."""

    resource_id: str
    window_start: datetime
    window_end: datetime
    reason: str


class NgsResource(ReOrchModel):
    """Lab instrument, operator pool, or compute resource."""

    resource_id: str
    resource_type: str
    capabilities: list[str] = Field(default_factory=list)
    capacity: int = Field(default=1, ge=1)
    zone: str | None = None


class NgsReagentLot(ReOrchModel):
    """Reagent lot with expiry and open-stability constraints."""

    lot_id: str
    compatible_assays: list[str] = Field(default_factory=list)
    quantity_available: int = Field(ge=0)
    expires_at: datetime
    opened_at: datetime | None = None
    open_stability_hours: float | None = None


class NgsPool(ReOrchModel):
    """Sequencing pool with index and capacity constraints."""

    pool_id: str
    sample_ids: list[str] = Field(default_factory=list)
    index_ids: list[str] = Field(default_factory=list)
    max_members: int = Field(default=8, ge=1)
    run_id: str | None = None


class NgsRun(ReOrchModel):
    """Sequencing run."""

    run_id: str
    resource_id: str
    pool_ids: list[str] = Field(default_factory=list)
    capacity_pools: int = Field(default=1, ge=1)
    scheduled_start: datetime
    scheduled_end: datetime
    frozen_flag: bool = False


class NgsLabEvent(ReOrchModel):
    """Observed event that triggers repair scheduling."""

    event_id: str
    event_type: str
    observed_at: datetime
    target_id: str | None = None
    description: str
    severity: str = "warning"


class NgsLabSnapshot(ReOrchModel):
    """A complete NGS lab scheduling snapshot."""

    snapshot_id: str
    captured_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    lab_id: str
    samples: list[NgsSample] = Field(default_factory=list)
    entities: list[NgsEntity] = Field(default_factory=list)
    operations: list[NgsOperation] = Field(default_factory=list)
    resources: list[NgsResource] = Field(default_factory=list)
    resource_calendar: list[NgsResourceWindow] = Field(default_factory=list)
    reagents: list[NgsReagentLot] = Field(default_factory=list)
    pools: list[NgsPool] = Field(default_factory=list)
    runs: list[NgsRun] = Field(default_factory=list)
    events: list[NgsLabEvent] = Field(default_factory=list)


class NgsGateIssue(ReOrchModel):
    """One protected feasibility gate issue."""

    gate: str
    severity: str = "blocker"
    entity_type: str
    entity_id: str
    message: str
    source_refs: list[str] = Field(default_factory=list)


class NgsQualityGateReport(ReOrchModel):
    """Protected feasibility result for one NGS repair candidate."""

    candidate_id: str
    pass_gate: bool
    confidence_level: str
    hard_blockers: list[NgsGateIssue] = Field(default_factory=list)
    warnings: list[NgsGateIssue] = Field(default_factory=list)
    gate_summary: dict[str, str] = Field(default_factory=dict)


class NgsRepairAction(ReOrchModel):
    """Action in a repair candidate."""

    action_type: str
    target_id: str
    description: str
    source_refs: list[str] = Field(default_factory=list)


class NgsRepairCandidate(ReOrchModel):
    """Protected repair candidate for NGS lab scheduling."""

    candidate_id: str
    strategy_type: str
    label: str
    operations: list[NgsOperation] = Field(default_factory=list)
    pools: list[NgsPool] = Field(default_factory=list)
    runs: list[NgsRun] = Field(default_factory=list)
    repair_actions: list[NgsRepairAction] = Field(default_factory=list)
    hard_feasible: bool = False
    weighted_tardiness_minutes: int = 0
    urgent_tardiness_minutes: int = 0
    rescue_burden: int = 0
    schedule_stability: float = Field(default=1.0, ge=0.0, le=1.0)
    soft_score: float = 0.0
    gate_report: NgsQualityGateReport | None = None
    explanation: str | None = None


class NgsImpactReport(ReOrchModel):
    """Impact report across samples, pools, runs, and TAT commitments."""

    impacted_samples: list[str] = Field(default_factory=list)
    impacted_entities: list[str] = Field(default_factory=list)
    impacted_pools: list[str] = Field(default_factory=list)
    impacted_runs: list[str] = Field(default_factory=list)
    tat_risk_samples: list[str] = Field(default_factory=list)
    event_summary: list[str] = Field(default_factory=list)


class NgsAgentTraceStep(ReOrchModel):
    """Visible agent execution step for the NGS copilot."""

    agent_name: str
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    decision: str
    confidence: float = Field(ge=0.0, le=1.0)
    boundary: str


class NgsLabDemoResponse(ReOrchModel):
    """End-to-end NGS lab repair scheduling demo output."""

    scenario_id: str
    replay_case_id: str | None = None
    source_package_id: str | None = None
    product_name: str = "ReOrch for NGS Lab Scheduling"
    snapshot: NgsLabSnapshot
    impact_report: NgsImpactReport
    feasible_candidates: list[NgsRepairCandidate] = Field(default_factory=list)
    rejected_candidates: list[NgsRepairCandidate] = Field(default_factory=list)
    recommended_candidate: NgsRepairCandidate | None = None
    agent_trace: list[NgsAgentTraceStep] = Field(default_factory=list)
    audit_package: dict = Field(default_factory=dict)
    runbook: list[str] = Field(default_factory=list)


class NgsReplayCaseResult(ReOrchModel):
    """One case result from an experiment-package batch replay."""

    case_id: str
    scenario_id: str
    description: str | None = None
    expected_recommended_strategy: str | None = None
    pass_replay: bool
    failure_reasons: list[str] = Field(default_factory=list)
    response: NgsLabDemoResponse


class NgsBatchReplayResponse(ReOrchModel):
    """Batch replay result loaded from an NGS experiment package."""

    package_id: str
    package_version: str
    source_path: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    case_results: list[NgsReplayCaseResult] = Field(default_factory=list)
    aggregate_metrics: dict = Field(default_factory=dict)


class NgsBatchReplayRequest(ReOrchModel):
    """Optional uploaded experiment package for batch replay."""

    package_payload: dict | None = None
    source_name: str = "uploaded_package"


class NgsPlannerDecisionRequest(ReOrchModel):
    """Planner confirmation, rejection, or override for one replay case."""

    package_id: str
    case_id: str
    action: str
    selected_candidate_id: str | None = None
    planner_id: str = "planner-1"
    reason: str | None = None
    override_reason: str | None = None


class NgsPlannerDecisionRecord(ReOrchModel):
    """Read-only NGS planner decision audit record."""

    decision_id: str
    package_id: str
    case_id: str
    action: str
    selected_candidate_id: str | None = None
    planner_id: str
    reason: str | None = None
    override_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    lims_writeback_executed: bool = False
    audit_refs: list[str] = Field(default_factory=list)


class NgsPlannerDecisionResponse(ReOrchModel):
    """Decision response with accumulated audit records."""

    record: NgsPlannerDecisionRecord
    records: list[NgsPlannerDecisionRecord] = Field(default_factory=list)
