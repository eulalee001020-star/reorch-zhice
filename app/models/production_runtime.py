"""Production runtime contracts for decomposition, CDC, jobs, and evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.schedule import ScheduleDetail, ScheduleSnapshot


EvidenceScope = Literal[
    "digital_twin",
    "customer_historical",
    "customer_shadow",
    "customer_production",
]


class RuntimeIncident(ReOrchModel):
    """One incident used by the executable joint-recovery path."""

    incident_id: str
    incident_type: str
    affected_operation_ids: list[str] = Field(min_length=1)
    delay_minutes: int = Field(default=0, ge=0)
    resource_id: str | None = None
    work_order_id: str | None = None
    severity: Literal["P1", "P2", "P3"] = "P2"
    occurred_at: datetime | None = None


class DecompositionExecutionRequest(ReOrchModel):
    """Executable bounded-subgraph solve request."""

    tenant_id: str
    snapshot: ScheduleSnapshot
    incidents: list[RuntimeIncident] = Field(min_length=1)
    max_subproblem_operations: int = Field(default=80, ge=5, le=1000)
    neighborhood_hops: int = Field(default=2, ge=0, le=8)
    max_parallelism: int = Field(default=2, ge=1, le=16)
    scenario_type: str | None = None
    readiness_manifest_id: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)
    goal_mode: Literal[
        "balanced",
        "delivery_priority",
        "stability_priority",
        "bottleneck_priority",
        "cost_priority",
    ] = "balanced"
    fail_on_unmapped_incident: bool = True


class SubproblemExecutionResult(ReOrchModel):
    subproblem_id: str
    incident_ids: list[str] = Field(default_factory=list)
    operation_ids: list[str] = Field(default_factory=list)
    status: Literal[
        "feasible",
        "infeasible",
        "failed",
        "cancelled",
        "checkpoint_reused",
    ]
    solver_status: str
    elapsed_ms: float = Field(ge=0.0)
    worker_name: str
    adjusted_operation_count: int = Field(default=0, ge=0)
    objective_value: float | None = None
    schedule_detail: ScheduleDetail | None = None
    blockers: list[str] = Field(default_factory=list)
    solver_metadata: dict[str, Any] = Field(default_factory=dict)
    evidence_fingerprint: str


class DecompositionExecutionResponse(ReOrchModel):
    run_id: str = Field(default_factory=lambda: f"decomp-{uuid4().hex}")
    tenant_id: str
    status: Literal["feasible", "partial", "blocked", "cancelled"]
    operation_count: int = Field(ge=0)
    incident_count: int = Field(ge=0)
    subproblem_results: list[SubproblemExecutionResult] = Field(default_factory=list)
    joint_incident_groups: list[list[str]] = Field(default_factory=list)
    requested_parallelism: int = Field(ge=1)
    observed_parallelism: int = Field(ge=0)
    merge_conflicts_detected: int = Field(default=0, ge=0)
    serial_repairs_run: int = Field(default=0, ge=0)
    final_schedule: ScheduleDetail | None = None
    checked_constraints: list[str] = Field(default_factory=list)
    violations: list[dict[str, Any]] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    elapsed_ms: float = Field(ge=0.0)
    evidence_fingerprint: str
    claim_boundary: str


class CdcEvent(ReOrchModel):
    """Ordered source event used to build an as-of consistent state."""

    event_id: str
    tenant_id: str
    source_system: str
    partition_key: str = "default"
    sequence: int = Field(ge=1)
    occurred_at: datetime
    entity_type: str
    entity_id: str
    operation: Literal["upsert", "delete"] = "upsert"
    payload: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"
    connector_id: str | None = None
    schema_fields: dict[str, str] | None = None
    checksum: str | None = None


class CdcIngestResult(ReOrchModel):
    event_id: str
    status: Literal[
        "accepted",
        "duplicate",
        "gap_buffered",
        "stale_rejected",
        "checksum_rejected",
        "collision_rejected",
    ]
    committed_sequence: int = Field(ge=0)
    watermark_at: datetime | None = None
    gap_sequences: list[int] = Field(default_factory=list)
    checkpoint_token: str
    reason: str | None = None


class SourceWatermark(ReOrchModel):
    tenant_id: str
    source_system: str
    partition_key: str
    committed_sequence: int = Field(ge=0)
    watermark_at: datetime | None = None
    checkpoint_token: str
    gap_sequences: list[int] = Field(default_factory=list)


class AsOfSnapshotRequest(ReOrchModel):
    tenant_id: str
    required_sources: list[str] = Field(min_length=1)
    as_of: datetime
    max_source_skew_seconds: int = Field(default=120, ge=0, le=86400)
    partition_key: str = "default"


class AsOfSnapshotResponse(ReOrchModel):
    status: Literal["consistent", "blocked"]
    tenant_id: str
    as_of: datetime
    source_watermarks: list[SourceWatermark] = Field(default_factory=list)
    entities: dict[str, dict[str, Any]] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    snapshot_fingerprint: str
    claim_boundary: str


class TenantSolveQuota(ReOrchModel):
    max_queued_jobs: int = Field(default=20, ge=1)
    max_running_jobs: int = Field(default=2, ge=1)
    max_operations_per_job: int = Field(default=10000, ge=1)


class SolveJobSubmitRequest(ReOrchModel):
    tenant_id: str
    idempotency_key: str
    solve_request: DecompositionExecutionRequest
    priority: int = Field(default=100, ge=0, le=1000)


class SolveJobRecord(ReOrchModel):
    job_id: str = Field(default_factory=lambda: f"solve-{uuid4().hex}")
    tenant_id: str
    idempotency_key: str
    status: Literal[
        "queued",
        "running",
        "cancel_requested",
        "cancelled",
        "completed",
        "failed",
    ] = "queued"
    priority: int = 100
    attempt: int = Field(default=0, ge=0)
    solve_request: DecompositionExecutionRequest
    result: DecompositionExecutionResponse | None = None
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    error: str | None = None


class SolveJobSubmitResponse(ReOrchModel):
    created: bool
    job: SolveJobRecord


class ExecutionReceipt(ReOrchModel):
    receipt_id: str
    tenant_id: str
    shadow_case_id: str
    source_system: str = "MES"
    source_event_id: str
    operation_id: str
    event_type: Literal[
        "accepted",
        "started",
        "completed",
        "rejected",
        "blocked",
        "rework",
    ]
    observed_at: datetime
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    actual_resource_id: str | None = None
    actual_quantity: float | None = Field(default=None, ge=0.0)
    quality_state: str | None = None
    reason_code: str | None = None


class ReadOnlyShadowRunRequest(ReOrchModel):
    tenant_id: str
    evidence_scope: EvidenceScope = "digital_twin"
    consistent_snapshot_ref: str
    solve_request: DecompositionExecutionRequest
    source_refs: list[str] = Field(min_length=1)


class ShadowExecutionStatus(ReOrchModel):
    shadow_case_id: str
    tenant_id: str
    evidence_scope: EvidenceScope = "digital_twin"
    status: Literal[
        "recommendation_ready",
        "planner_reviewed",
        "awaiting_execution",
        "execution_closed",
        "blocked",
    ]
    advisory_only: bool = True
    writeback_invocation_count: int = Field(default=0, ge=0)
    solve_result: DecompositionExecutionResponse | None = None
    planner_baseline: dict[str, Any] | None = None
    planner_decision: dict[str, Any] | None = None
    receipts: list[ExecutionReceipt] = Field(default_factory=list)
    expected_terminal_operation_ids: list[str] = Field(default_factory=list)
    execution_metrics: dict[str, float | int | str | bool] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    evidence_fingerprint: str


class ShadowPlannerDecisionRequest(ReOrchModel):
    planner_baseline: dict[str, Any]
    planner_decision: dict[str, Any]


class ExecutionReceiptBatch(ReOrchModel):
    receipts: list[ExecutionReceipt] = Field(min_length=1)


class RoiCostAssumptions(ReOrchModel):
    delay_cost_per_minute: float = Field(default=35.0, ge=0.0)
    planner_cost_per_minute: float = Field(default=2.0, ge=0.0)
    overtime_cost_per_minute: float = Field(default=3.0, ge=0.0)
    scrap_cost_per_case: float = Field(default=800.0, ge=0.0)


class RecoveryEvidenceCase(ReOrchModel):
    case_id: str
    evidence_scope: EvidenceScope
    source_refs: list[str] = Field(min_length=1)
    incident: RuntimeIncident
    planner_baseline: dict[str, Any]
    system_recovery: dict[str, Any]
    planner_decision: dict[str, Any]
    execution_outcome: dict[str, Any]
    assumptions: RoiCostAssumptions | None = None
    roi: dict[str, float | int | str | bool] = Field(default_factory=dict)
    evidence_fingerprint: str


class RecoveryEvidenceLedger(ReOrchModel):
    ledger_id: str = Field(default_factory=lambda: f"ledger-{uuid4().hex}")
    evidence_scope: EvidenceScope
    cases: list[RecoveryEvidenceCase] = Field(default_factory=list)
    case_count: int = Field(ge=0)
    planner_baseline_complete: bool
    execution_outcome_complete: bool
    roi_is_proxy: bool
    customer_evidence_gate_passed: bool
    aggregate_roi: dict[str, float | int | str | bool] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    ledger_fingerprint: str
    claim_boundary: str


class ProductionValidationRunResponse(ReOrchModel):
    run_id: str = Field(default_factory=lambda: f"prodval-{uuid4().hex}")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    evidence_scope: EvidenceScope = "digital_twin"
    checks: dict[str, dict[str, Any]] = Field(default_factory=dict)
    scale_results: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ledger: RecoveryEvidenceLedger
    all_digital_twin_checks_passed: bool
    customer_evidence_gate_passed: bool
    blockers: list[str] = Field(default_factory=list)
    artifact_fingerprint: str
    claim_boundary: str


class CustomerEvidenceLedgerRequest(ReOrchModel):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=30)


class ProductionValidationRunRequest(ReOrchModel):
    scale_repetitions: int = Field(default=5, ge=1, le=20)
