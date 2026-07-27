"""Production runtime API for data consistency, solving, and evidence."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.core.auth import CurrentUser, get_optional_current_user
from app.core.config import settings
from app.models.feasibility_restoration import (
    FeasibilityRestorationRequest,
    FeasibilityRestorationResponse,
)
from app.models.integration_control import SchemaObservationRequest
from app.models.production_runtime import (
    AsOfSnapshotRequest,
    AsOfSnapshotResponse,
    CdcEvent,
    CdcIngestResult,
    CustomerEvidenceLedgerRequest,
    DecompositionExecutionRequest,
    DecompositionExecutionResponse,
    ExecutionReceiptBatch,
    ProductionValidationRunRequest,
    ProductionValidationRunResponse,
    ReadOnlyShadowRunRequest,
    RecoveryEvidenceLedger,
    ShadowExecutionStatus,
    ShadowPlannerDecisionRequest,
    SolveJobRecord,
    SolveJobSubmitRequest,
    SolveJobSubmitResponse,
    TenantSolveQuota,
)
from app.services.cdc_consistency import CdcConsistencyService
from app.services.decomposition_executor import DecompositionExecutor
from app.services.decision_readiness import (
    DecisionReadinessError,
    DecisionReadinessService,
)
from app.services.operational_store import RelationalOperationalStore
from app.services.feasibility_restoration import FeasibilityRestorationEngine
from app.services.production_validation_harness import ProductionValidationHarness
from app.services.recovery_evidence_ledger import RecoveryEvidenceLedgerService
from app.services.shadow_execution import ReadOnlyShadowRunner
from app.services.schema_drift_guard import SchemaDriftGuard
from app.services.solve_job_runtime import DurableSolveQueue, SolveJobWorker


router = APIRouter(prefix="/api/v1/runtime", tags=["production-runtime"])
_store: RelationalOperationalStore | None = None
_queue: DurableSolveQueue | None = None


def get_operational_store() -> RelationalOperationalStore:
    global _store
    if _store is None:
        database_url = settings.runtime.database_url
        if not database_url:
            if settings.app.env in {"staging", "production"}:
                database_url = settings.db.sync_url
            else:
                path = Path(settings.runtime.local_database_path).resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                database_url = f"sqlite+pysqlite:///{path}"
        _store = RelationalOperationalStore(database_url)
    return _store


def get_solve_queue() -> DurableSolveQueue:
    global _queue
    if _queue is None:
        _queue = DurableSolveQueue(
            get_operational_store(),
            default_quota=TenantSolveQuota(
                max_queued_jobs=settings.runtime.default_max_queued_jobs,
                max_running_jobs=settings.runtime.default_max_running_jobs,
                max_operations_per_job=settings.runtime.default_max_operations_per_job,
            ),
        )
    return _queue


@router.post("/decomposition/execute", response_model=DecompositionExecutionResponse)
async def execute_decomposition(
    body: DecompositionExecutionRequest,
    user: CurrentUser = Depends(get_optional_current_user),
) -> DecompositionExecutionResponse:
    _enforce_tenant(user, body.tenant_id)
    _enforce_decision_readiness(body)
    return await run_in_threadpool(DecompositionExecutor().execute, body)


@router.post(
    "/feasibility-restoration/evaluate",
    response_model=FeasibilityRestorationResponse,
)
async def evaluate_feasibility_restoration(
    body: FeasibilityRestorationRequest,
    user: CurrentUser = Depends(get_optional_current_user),
) -> FeasibilityRestorationResponse:
    """Diagnose infeasibility and simulate or execute approved recovery actions."""
    _enforce_tenant(user, body.tenant_id)
    if user.role.value not in {"Planner", "Management", "IT_Admin"}:
        raise HTTPException(
            status_code=403,
            detail="Planner, Management, or IT_Admin role required",
        )
    if settings.app.env in {"staging", "production"} and (
        body.policy is None or not body.policy.customer_owned
    ):
        raise HTTPException(
            status_code=409,
            detail="active_customer_owned_recovery_policy_required",
        )
    return await run_in_threadpool(FeasibilityRestorationEngine().evaluate, body)


@router.post("/cdc/events", response_model=CdcIngestResult)
async def ingest_cdc_event(
    body: CdcEvent,
    user: CurrentUser = Depends(get_optional_current_user),
) -> CdcIngestResult:
    _enforce_tenant(user, body.tenant_id)
    if bool(body.connector_id) != bool(body.schema_fields):
        raise HTTPException(
            status_code=409,
            detail="connector_id_and_schema_fields_must_be_provided_together",
        )
    if body.connector_id and body.schema_fields:
        drift = await run_in_threadpool(
            SchemaDriftGuard(get_operational_store()).evaluate,
            SchemaObservationRequest(
                tenant_id=body.tenant_id,
                connector_id=body.connector_id,
                source_system=body.source_system,
                entity_type=body.entity_type,
                schema_version=body.schema_version,
                fields=body.schema_fields,
                observed_at=body.occurred_at,
                sample_record_count=1,
                source_refs=[f"cdc-event:{body.event_id}"],
            ),
        )
        if drift.status == "quarantined":
            raise HTTPException(status_code=409, detail=drift.model_dump(mode="json"))
    elif settings.app.env in {"staging", "production"}:
        raise HTTPException(
            status_code=409,
            detail="governed_cdc_ingestion_requires_connector_schema_observation",
        )
    return await run_in_threadpool(
        CdcConsistencyService(get_operational_store()).ingest, body
    )


@router.post("/cdc/as-of", response_model=AsOfSnapshotResponse)
async def materialize_asof_snapshot(
    body: AsOfSnapshotRequest,
    user: CurrentUser = Depends(get_optional_current_user),
) -> AsOfSnapshotResponse:
    _enforce_tenant(user, body.tenant_id)
    response = await run_in_threadpool(
        CdcConsistencyService(get_operational_store()).materialize_as_of, body
    )
    if response.status == "blocked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=response.model_dump(mode="json"),
        )
    return response


@router.post("/solve-jobs", response_model=SolveJobSubmitResponse)
async def submit_solve_job(
    body: SolveJobSubmitRequest,
    user: CurrentUser = Depends(get_optional_current_user),
) -> SolveJobSubmitResponse:
    _enforce_tenant(user, body.tenant_id)
    _enforce_decision_readiness(body.solve_request)
    try:
        job, created = await run_in_threadpool(get_solve_queue().submit, body)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return SolveJobSubmitResponse(created=created, job=job)


@router.get("/solve-jobs/{job_id}", response_model=SolveJobRecord)
async def get_solve_job(
    job_id: str,
    user: CurrentUser = Depends(get_optional_current_user),
) -> SolveJobRecord:
    job = await run_in_threadpool(get_solve_queue().get, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="solve_job_not_found")
    _enforce_tenant(user, job.tenant_id)
    return job


@router.post("/solve-jobs/{job_id}/cancel", response_model=SolveJobRecord)
async def cancel_solve_job(
    job_id: str,
    user: CurrentUser = Depends(get_optional_current_user),
) -> SolveJobRecord:
    existing = get_solve_queue().get(job_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="solve_job_not_found")
    _enforce_tenant(user, existing.tenant_id)
    job = await run_in_threadpool(get_solve_queue().cancel, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="solve_job_not_found")
    return job


@router.post("/solve-workers/{worker_id}/run-once", response_model=SolveJobRecord | None)
async def run_solve_worker_once(
    worker_id: str,
    user: CurrentUser = Depends(get_optional_current_user),
) -> SolveJobRecord | None:
    if user.role.value != "IT_Admin":
        raise HTTPException(status_code=403, detail="IT_Admin role required")
    result = await run_in_threadpool(
        SolveJobWorker(
            get_solve_queue(),
            worker_id=worker_id,
            lease_seconds=settings.runtime.solve_lease_seconds,
        ).run_once
    )
    return result.job


@router.post("/shadow-runs", response_model=ShadowExecutionStatus)
async def run_readonly_shadow(
    body: ReadOnlyShadowRunRequest,
    user: CurrentUser = Depends(get_optional_current_user),
) -> ShadowExecutionStatus:
    _enforce_tenant(user, body.tenant_id)
    return await run_in_threadpool(
        ReadOnlyShadowRunner(get_operational_store()).run, body
    )


@router.post(
    "/shadow-runs/{shadow_case_id}/planner-decision",
    response_model=ShadowExecutionStatus,
)
async def record_shadow_planner_decision(
    shadow_case_id: str,
    body: ShadowPlannerDecisionRequest,
    user: CurrentUser = Depends(get_optional_current_user),
) -> ShadowExecutionStatus:
    runner = ReadOnlyShadowRunner(get_operational_store())
    current = runner.get(shadow_case_id)
    if current is None:
        raise HTTPException(status_code=404, detail="shadow_case_not_found")
    _enforce_tenant(user, current.tenant_id)
    try:
        return await run_in_threadpool(
            runner.record_planner_decision,
            shadow_case_id,
            planner_baseline=body.planner_baseline,
            planner_decision=body.planner_decision,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/shadow-runs/{shadow_case_id}/execution-receipts",
    response_model=ShadowExecutionStatus,
)
async def ingest_shadow_execution_receipts(
    shadow_case_id: str,
    body: ExecutionReceiptBatch,
    user: CurrentUser = Depends(get_optional_current_user),
) -> ShadowExecutionStatus:
    runner = ReadOnlyShadowRunner(get_operational_store())
    current = runner.get(shadow_case_id)
    if current is None:
        raise HTTPException(status_code=404, detail="shadow_case_not_found")
    _enforce_tenant(user, current.tenant_id)
    try:
        return await run_in_threadpool(
            runner.ingest_receipts, shadow_case_id, body.receipts
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/shadow-runs/{shadow_case_id}", response_model=ShadowExecutionStatus)
async def get_shadow_run(
    shadow_case_id: str,
    user: CurrentUser = Depends(get_optional_current_user),
) -> ShadowExecutionStatus:
    record = ReadOnlyShadowRunner(get_operational_store()).get(shadow_case_id)
    if record is None:
        raise HTTPException(status_code=404, detail="shadow_case_not_found")
    _enforce_tenant(user, record.tenant_id)
    return record


@router.post("/evidence/customer-ledger", response_model=RecoveryEvidenceLedger)
async def build_customer_evidence_ledger(
    body: CustomerEvidenceLedgerRequest,
    user: CurrentUser = Depends(get_optional_current_user),
) -> RecoveryEvidenceLedger:
    _ = user
    try:
        return await run_in_threadpool(
            RecoveryEvidenceLedgerService(
                store=get_operational_store()
            ).build_customer_ledger,
            body.rows,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/validation/digital-twin", response_model=ProductionValidationRunResponse)
async def run_production_validation(
    body: ProductionValidationRunRequest,
    user: CurrentUser = Depends(get_optional_current_user),
) -> ProductionValidationRunResponse:
    if user.role.value not in {"Planner", "IT_Admin"}:
        raise HTTPException(status_code=403, detail="Planner or IT_Admin role required")
    return await run_in_threadpool(
        ProductionValidationHarness().run,
        scale_repetitions=body.scale_repetitions,
    )


def _enforce_tenant(user: CurrentUser, tenant_id: str) -> None:
    if user.auth_source == "local_system":
        return
    if user.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="tenant_scope_mismatch")


def _enforce_decision_readiness(body: DecompositionExecutionRequest) -> None:
    has_scenario = bool(body.scenario_type)
    has_manifest = bool(body.readiness_manifest_id)
    if has_scenario != has_manifest:
        raise HTTPException(
            status_code=409,
            detail="scenario_type_and_readiness_manifest_id_must_be_provided_together",
        )
    if not has_manifest:
        if settings.app.env in {"staging", "production"}:
            raise HTTPException(
                status_code=409,
                detail="active_decision_readiness_manifest_required",
            )
        return
    try:
        DecisionReadinessService(get_operational_store()).assert_ready_manifest(
            body.tenant_id,
            body.readiness_manifest_id or "",
            body.scenario_type,
        )
    except DecisionReadinessError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
