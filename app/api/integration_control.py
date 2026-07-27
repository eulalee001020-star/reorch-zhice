"""API for enterprise integration governance and certification assets."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from app.api.production_runtime import get_operational_store
from app.core.auth import CurrentUser, Role, get_optional_current_user
from app.core.config import settings
from app.models.integration_control import (
    AssetActivationRequest,
    ConnectorConformanceReport,
    ConnectorRegistrationRequest,
    ConstraintDefinitionDraft,
    DecisionReadinessManifest,
    DecisionReadinessRequest,
    IntegrationAuditEvent,
    IntegrationControlOverview,
    IntegrationControlValidationRequest,
    IntegrationControlValidationResult,
    QuarantineRecord,
    QuarantineResolutionRequest,
    ScenarioDataContractDraft,
    SchemaDriftReport,
    SchemaObservationRequest,
    SourceAuthorityMatrixDraft,
    VersionedAssetRecord,
    WritebackCertificationReport,
)
from app.services.decision_readiness import (
    DecisionReadinessError,
    DecisionReadinessService,
)
from app.services.integration_control_validation import (
    IntegrationControlValidationHarness,
)
from app.services.integration_registry import (
    IntegrationRegistryError,
    IntegrationRegistryService,
)
from app.services.schema_drift_guard import SchemaDriftError, SchemaDriftGuard


router = APIRouter(prefix="/api/v1/integration-control", tags=["integration-control"])


@router.get("/overview", response_model=IntegrationControlOverview)
async def get_integration_overview(
    tenant_id: str = Query("default"),
    user: CurrentUser = Depends(get_optional_current_user),
) -> IntegrationControlOverview:
    _enforce_tenant(user, tenant_id)
    return await run_in_threadpool(
        DecisionReadinessService(get_operational_store()).overview, tenant_id
    )


@router.get("/assets", response_model=list[VersionedAssetRecord])
async def list_integration_assets(
    tenant_id: str = Query("default"),
    asset_type: str | None = Query(None),
    asset_status: str | None = Query(None, alias="status"),
    user: CurrentUser = Depends(get_optional_current_user),
) -> list[VersionedAssetRecord]:
    _enforce_tenant(user, tenant_id)
    return await run_in_threadpool(
        IntegrationRegistryService(get_operational_store()).list_assets,
        tenant_id,
        asset_type=asset_type,
        status=asset_status,
    )


@router.post("/authority-matrices", response_model=VersionedAssetRecord)
async def register_authority_matrix(
    body: SourceAuthorityMatrixDraft,
    user: CurrentUser = Depends(get_optional_current_user),
) -> VersionedAssetRecord:
    _require_admin(user, body.tenant_id)
    return await _registry_call(
        IntegrationRegistryService(get_operational_store()).register_authority_matrix,
        body,
        user.user_id,
    )


@router.post(
    "/authority-matrices/{matrix_id}/versions/{version}/activate",
    response_model=VersionedAssetRecord,
)
async def activate_authority_matrix(
    matrix_id: str,
    version: str,
    body: AssetActivationRequest,
    tenant_id: str = Query("default"),
    user: CurrentUser = Depends(get_optional_current_user),
) -> VersionedAssetRecord:
    _require_admin(user, tenant_id)
    return await _registry_call(
        IntegrationRegistryService(get_operational_store()).activate_authority_matrix,
        tenant_id,
        matrix_id,
        version,
        user.user_id,
        body.approval_note,
    )


@router.post("/scenario-contracts", response_model=VersionedAssetRecord)
async def register_scenario_contract(
    body: ScenarioDataContractDraft,
    user: CurrentUser = Depends(get_optional_current_user),
) -> VersionedAssetRecord:
    _require_admin(user, body.tenant_id)
    return await _registry_call(
        IntegrationRegistryService(get_operational_store()).register_scenario_contract,
        body,
        user.user_id,
    )


@router.post(
    "/scenario-contracts/{contract_id}/versions/{version}/activate",
    response_model=VersionedAssetRecord,
)
async def activate_scenario_contract(
    contract_id: str,
    version: str,
    body: AssetActivationRequest,
    tenant_id: str = Query("default"),
    user: CurrentUser = Depends(get_optional_current_user),
) -> VersionedAssetRecord:
    _require_admin(user, tenant_id)
    return await _registry_call(
        IntegrationRegistryService(get_operational_store()).activate_scenario_contract,
        tenant_id,
        contract_id,
        version,
        user.user_id,
        body.approval_note,
    )


@router.post("/connectors", response_model=VersionedAssetRecord)
async def register_connector_manifest(
    body: ConnectorRegistrationRequest,
    user: CurrentUser = Depends(get_optional_current_user),
) -> VersionedAssetRecord:
    _require_admin(user, body.tenant_id)
    return await _registry_call(
        IntegrationRegistryService(get_operational_store()).register_connector_manifest,
        body,
        user.user_id,
    )


@router.post("/connector-conformance", response_model=VersionedAssetRecord)
async def register_connector_conformance(
    body: ConnectorConformanceReport,
    user: CurrentUser = Depends(get_optional_current_user),
) -> VersionedAssetRecord:
    _require_admin(user, body.tenant_id)
    return await _registry_call(
        IntegrationRegistryService(get_operational_store()).register_connector_conformance,
        body,
        user.user_id,
    )


@router.post(
    "/connectors/{connector_id}/versions/{version}/activate",
    response_model=VersionedAssetRecord,
)
async def activate_connector_manifest(
    connector_id: str,
    version: str,
    body: AssetActivationRequest,
    tenant_id: str = Query("default"),
    user: CurrentUser = Depends(get_optional_current_user),
) -> VersionedAssetRecord:
    _require_admin(user, tenant_id)
    return await _registry_call(
        IntegrationRegistryService(get_operational_store()).activate_connector_manifest,
        tenant_id,
        connector_id,
        version,
        user.user_id,
        body.approval_note,
    )


@router.post("/schema-drift/evaluate", response_model=SchemaDriftReport)
async def evaluate_schema_drift(
    body: SchemaObservationRequest,
    user: CurrentUser = Depends(get_optional_current_user),
) -> SchemaDriftReport:
    _require_admin(user, body.tenant_id)
    return await run_in_threadpool(SchemaDriftGuard(get_operational_store()).evaluate, body)


@router.get("/quarantine", response_model=list[QuarantineRecord])
async def list_quarantine(
    tenant_id: str = Query("default"),
    quarantine_status: str | None = Query(None, alias="status"),
    user: CurrentUser = Depends(get_optional_current_user),
) -> list[QuarantineRecord]:
    _enforce_tenant(user, tenant_id)
    return await run_in_threadpool(
        get_operational_store().list_quarantine_records,
        tenant_id,
        status=quarantine_status,
    )


@router.post("/quarantine/{quarantine_id}/resolve", response_model=QuarantineRecord)
async def resolve_quarantine(
    quarantine_id: str,
    body: QuarantineResolutionRequest,
    user: CurrentUser = Depends(get_optional_current_user),
) -> QuarantineRecord:
    record = get_operational_store().get_quarantine_record(quarantine_id)
    if record is None:
        raise HTTPException(status_code=404, detail="quarantine_record_not_found")
    _require_admin(user, record.tenant_id)
    try:
        return await run_in_threadpool(
            SchemaDriftGuard(get_operational_store()).resolve,
            quarantine_id,
            action=body.action,
            actor_id=user.user_id,
            resolution_note=body.resolution_note,
        )
    except SchemaDriftError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/constraints", response_model=VersionedAssetRecord)
async def register_constraint(
    body: ConstraintDefinitionDraft,
    user: CurrentUser = Depends(get_optional_current_user),
) -> VersionedAssetRecord:
    _require_admin(user, body.tenant_id)
    return await _registry_call(
        IntegrationRegistryService(get_operational_store()).register_constraint,
        body,
        user.user_id,
    )


@router.post(
    "/constraints/{constraint_id}/versions/{version}/activate",
    response_model=VersionedAssetRecord,
)
async def activate_constraint(
    constraint_id: str,
    version: str,
    body: AssetActivationRequest,
    tenant_id: str = Query("default"),
    user: CurrentUser = Depends(get_optional_current_user),
) -> VersionedAssetRecord:
    _require_admin(user, tenant_id)
    return await _registry_call(
        IntegrationRegistryService(get_operational_store()).activate_constraint,
        tenant_id,
        constraint_id,
        version,
        user.user_id,
        body.approval_note,
    )


@router.post("/writeback-certifications", response_model=VersionedAssetRecord)
async def register_writeback_certification(
    body: WritebackCertificationReport,
    user: CurrentUser = Depends(get_optional_current_user),
) -> VersionedAssetRecord:
    _require_admin(user, body.tenant_id)
    return await _registry_call(
        IntegrationRegistryService(get_operational_store()).register_writeback_certification,
        body,
        user.user_id,
    )


@router.post("/readiness/evaluate", response_model=DecisionReadinessManifest)
async def evaluate_decision_readiness(
    body: DecisionReadinessRequest,
    user: CurrentUser = Depends(get_optional_current_user),
) -> DecisionReadinessManifest:
    _enforce_tenant(user, body.tenant_id)
    if user.role not in {Role.PLANNER, Role.IT_ADMIN}:
        raise HTTPException(status_code=403, detail="Planner or IT_Admin role required")
    if settings.app.env in {"staging", "production"} and not body.canonical_records:
        raise HTTPException(
            status_code=409,
            detail="canonical_records_required_for_production_readiness_evaluation",
        )
    try:
        return await run_in_threadpool(
            DecisionReadinessService(get_operational_store()).evaluate, body
        )
    except DecisionReadinessError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/validation/digital-twin", response_model=IntegrationControlValidationResult
)
async def validate_integration_control_plane(
    body: IntegrationControlValidationRequest,
    user: CurrentUser = Depends(get_optional_current_user),
) -> IntegrationControlValidationResult:
    _require_admin(user, body.tenant_id)
    return await run_in_threadpool(
        IntegrationControlValidationHarness(get_operational_store()).run,
        tenant_id=body.tenant_id,
        actor_id=user.user_id,
    )


@router.get("/audit", response_model=list[IntegrationAuditEvent])
async def list_integration_audit(
    tenant_id: str = Query("default"),
    limit: int = Query(200, ge=1, le=1000),
    user: CurrentUser = Depends(get_optional_current_user),
) -> list[IntegrationAuditEvent]:
    _enforce_tenant(user, tenant_id)
    return await run_in_threadpool(
        get_operational_store().list_integration_audit, tenant_id, limit=limit
    )


async def _registry_call(callable_, *args):
    try:
        return await run_in_threadpool(callable_, *args)
    except IntegrationRegistryError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _require_admin(user: CurrentUser, tenant_id: str) -> None:
    _enforce_tenant(user, tenant_id)
    if user.role != Role.IT_ADMIN or user.user_id == "system":
        raise HTTPException(status_code=403, detail="Named IT_Admin approval required")


def _enforce_tenant(user: CurrentUser, tenant_id: str) -> None:
    if user.auth_source == "local_system":
        return
    if user.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="tenant_scope_mismatch")
