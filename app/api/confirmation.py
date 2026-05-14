"""Layer 4 Confirmation & Writeback API endpoints.

Validates: Requirements 7.6, 8.3, 8.7

Provides:
- POST /api/v1/incidents/{incident_id}/confirm — confirm/adjust/reject plan
- GET  /api/v1/incidents/{incident_id}/decision-record — query decision record
- GET  /api/v1/incidents/{incident_id}/writeback-status — query writeback status
- GET  /api/v1/incidents/{incident_id}/execution-result — query execution result
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.auth import CurrentUser, get_optional_current_user
from app.models.agent import FeedbackStructuringRequest
from app.models.decision import ConfirmRequest, ConfirmResponse, DecisionRecord
from app.models.enums import ConfirmAction, WritebackStatus
from app.models.execution import ExecutionResult
from app.services.confirmation_module import (
    ConfirmationModule,
    ConstraintViolationError,
    OverrideReasonRequiredError,
    PermissionDeniedError,
)
from app.services.export_service import ExportService
from app.services.persistence import (
    fetch_any_snapshot,
    fetch_decision_record_by_id,
    fetch_decision_record_by_incident,
    fetch_execution_result_by_incident,
    fetch_plan_recommendation,
    fetch_writeback_job_by_incident,
    list_candidate_plans_from_db,
    persist_audit_log,
    persist_decision_record,
    record_entity_version,
)
from app.services.agent_workflow import FeedbackAgent
from app.services.writeback_module import WritebackModule

logger = logging.getLogger(__name__)

router = APIRouter(tags=["confirmation"])

# ---------------------------------------------------------------------------
# Local fallback stores used only when PostgreSQL is unavailable in dev/test.
# ---------------------------------------------------------------------------
_decision_record_store: dict[str, DecisionRecord] = {}  # incident_id -> record
_confirmation_module = ConfirmationModule()
_writeback_module = WritebackModule()
_export_service = ExportService()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ConfirmRequestBody(BaseModel):
    """Body for POST /confirm."""

    action: ConfirmAction = Field(
        description="确认操作类型: accept / accept_with_adjustment / reject_and_reselect"
    )
    selected_plan_id: UUID = Field(description="选择的方案 ID")
    adjustments: list[dict] | None = Field(
        default=None, description="微调内容（仅 accept_with_adjustment 时使用）"
    )
    override_reason: str | None = Field(
        default=None, description="否决原因（仅 reject_and_reselect 时必填）"
    )
    confirmed_by: str | None = Field(default=None, description="确认人标识")


class WritebackStatusResponse(BaseModel):
    """Response for writeback status query."""

    incident_id: str
    status: WritebackStatus
    total_instructions: int = 0
    success_count: int = 0
    failed_count: int = 0
    failed_instructions: list[dict] = Field(default_factory=list)
    timestamp: str = ""


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str


# ---------------------------------------------------------------------------
# POST /api/v1/incidents/{incident_id}/confirm
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/incidents/{incident_id}/confirm",
    response_model=ConfirmResponse,
    status_code=status.HTTP_200_OK,
    summary="确认/微调/否决方案",
    description=(
        "对 incident 的候选方案执行确认操作。"
        "支持三种操作：确认采纳、微调后采纳、否决并重选。"
    ),
    responses={
        400: {"description": "请求参数错误或约束违反"},
        403: {"description": "权限不足"},
        404: {"description": "Incident 或候选方案不存在"},
    },
)
async def confirm_plan(
    incident_id: UUID,
    body: ConfirmRequestBody,
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> ConfirmResponse:
    from app.api.analysis import _snapshot_store, _strategy_cache, _impact_report_cache
    from app.api.solver import _candidate_plans_store, _recommendation_store

    key = str(incident_id)
    actor_id = current_user.user_id

    # 1. Look up candidate plans
    candidates = _candidate_plans_store.get(key)
    if not candidates:
        db_candidates = await list_candidate_plans_from_db(incident_id)
        if db_candidates:
            candidates = db_candidates
            _candidate_plans_store[key] = candidates
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No candidate plans for incident {incident_id}. Trigger solve first.",
        )

    # 2. Find snapshot
    snapshot = None
    for snap in _snapshot_store.values():
        snapshot = snap
        break
    if snapshot is None:
        snapshot = await fetch_any_snapshot()
        if snapshot is not None:
            _snapshot_store[str(snapshot.snapshot_id)] = snapshot
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ScheduleSnapshot available.",
        )

    # 3. Get recommendation for recommended_plan_id
    recommendation = _recommendation_store.get(key)
    if recommendation is None:
        recommendation = await fetch_plan_recommendation(incident_id)
        if recommendation is not None:
            _recommendation_store[key] = recommendation
    recommended_plan_id = (
        recommendation.recommended_plan_id
        if recommendation
        else candidates[0].plan_id
    )

    # 4. Get strategy and impact summary
    strategy_type = "local_repair"
    impact_summary = "Impact analysis summary"
    strategy = _strategy_cache.get(key)
    if strategy:
        strategy_type = strategy.strategy_type.value if hasattr(strategy.strategy_type, "value") else strategy.strategy_type
    impact_report = _impact_report_cache.get(key)
    if impact_report:
        impact_summary = (
            f"{len(impact_report.affected_work_orders)} work orders affected, "
            f"estimated delay {impact_report.estimated_total_delay_minutes} min"
        )

    # 5. Build ConfirmRequest
    confirm_request = ConfirmRequest(
        incident_id=incident_id,
        action=body.action,
        selected_plan_id=body.selected_plan_id,
        adjustments=body.adjustments,
        override_reason=body.override_reason,
        confirmed_by=actor_id if actor_id != "system" else body.confirmed_by or actor_id,
    )

    # 6. Execute confirmation
    try:
        response = await _confirmation_module.confirm(
            request=confirm_request,
            candidate_plans=candidates,
            recommended_plan_id=recommended_plan_id,
            snapshot=snapshot,
            impact_report_summary=impact_summary,
            strategy_type=strategy_type,
            role=current_user.role,
        )
    except PermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except ConstraintViolationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Constraint violation: {e}",
        )
    except OverrideReasonRequiredError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    # 7. Build and store DecisionRecord
    # The ConfirmationModule already builds the record internally;
    # we reconstruct a minimal one for the store
    plan_map = {p.plan_id: p for p in candidates}
    selected_plan = plan_map.get(body.selected_plan_id)
    if selected_plan:
        record = DecisionRecord(
            decision_record_id=response.decision_record_id,
            incident_id=incident_id,
            impact_report_summary=impact_summary,
            strategy_type=strategy_type,
            all_candidate_plan_ids=[p.plan_id for p in candidates],
            recommended_plan_id=recommended_plan_id,
            confirmed_plan_id=response.confirmed_plan_id,
            derived_from_plan_id=response.derived_from_plan_id,
            is_override=body.action == ConfirmAction.REJECT_AND_RESELECT,
            is_manual_adjusted=response.is_manual_adjusted,
            override_reason=body.override_reason,
            confirmed_by=confirm_request.confirmed_by,
            confirmed_at=datetime.now(tz=timezone.utc),
            plan_selection_input_version="1.0",
            plan_selection_output_version="1.0",
            solver_chain=selected_plan.solver_chain,
            rule_selector_version="1.0.0",
            neighborhood_selector_version="1.0.0",
            repair_policy_advisor_version="1.0.0",
        )
        _decision_record_store[key] = record
        await persist_decision_record(record, user_id=current_user.user_id)
        await persist_audit_log(
            action=body.action.value,
            entity_type="decision_record",
            entity_id=str(record.decision_record_id),
            user_id=current_user.user_id,
            role=current_user.role.value,
            details={
                "incident_id": key,
                "selected_plan_id": str(body.selected_plan_id),
                "is_override": record.is_override,
            },
        )
        if record.is_override and record.override_reason:
            feedback = await FeedbackAgent().structure_override(
                FeedbackStructuringRequest(
                    override_text=record.override_reason,
                    decision_record_id=record.decision_record_id,
                    incident_id=incident_id,
                    planner_id=record.confirmed_by,
                )
            )
            await record_entity_version(
                entity_type="feedback_case_candidate",
                entity_id=str(record.decision_record_id),
                data=feedback.model_dump(mode="json"),
                changed_by=current_user.user_id,
            )

        # 8. Trigger writeback
        await _writeback_module.writeback_to_mes(selected_plan, record)

    logger.info(
        "Confirmation for incident %s: action=%s, confirmed_plan=%s",
        key,
        body.action.value,
        response.confirmed_plan_id,
    )
    return response


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id}/decision-record
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/incidents/{incident_id}/decision-record",
    response_model=DecisionRecord,
    summary="查询决策记录",
    description="根据 incident_id 查询完整的决策记录。",
    responses={404: {"description": "决策记录不存在"}},
)
async def get_decision_record(incident_id: UUID) -> DecisionRecord:
    key = str(incident_id)
    record = _decision_record_store.get(key)
    if record is None:
        record = await fetch_decision_record_by_incident(incident_id)
        if record is not None:
            _decision_record_store[key] = record
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No decision record for incident {incident_id}. Confirm a plan first.",
        )
    return record


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id}/writeback-status
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/incidents/{incident_id}/writeback-status",
    response_model=WritebackStatusResponse,
    summary="查询回写状态",
    description="根据 incident_id 查询 MES 回写状态。",
    responses={404: {"description": "回写状态不存在"}},
)
async def get_writeback_status(incident_id: UUID) -> WritebackStatusResponse:
    key = str(incident_id)
    wb_status = _writeback_module.get_writeback_status(incident_id)
    persisted_job = None
    if wb_status is None:
        persisted_job = await fetch_writeback_job_by_incident(incident_id)
        if persisted_job is not None:
            wb_status = WritebackStatus(persisted_job["status"])
    if wb_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No writeback status for incident {incident_id}.",
        )

    report = _writeback_module.get_writeback_report(incident_id)
    if report is None and persisted_job is None:
        persisted_job = await fetch_writeback_job_by_incident(incident_id)
    if report is None and persisted_job is not None:
        response_payload = persisted_job.get("response_payload") or {}
        return WritebackStatusResponse(
            incident_id=key,
            status=WritebackStatus(persisted_job["status"]),
            total_instructions=response_payload.get("total_instructions", 0),
            success_count=response_payload.get("success_count", 0),
            failed_count=response_payload.get("failed_count", 0),
            failed_instructions=response_payload.get("failed_instructions", []),
            timestamp=persisted_job.get("updated_at") or "",
        )
    return WritebackStatusResponse(
        incident_id=key,
        status=wb_status,
        total_instructions=report.total_instructions if report else 0,
        success_count=report.success_count if report else 0,
        failed_count=report.failed_count if report else 0,
        failed_instructions=report.failed_instructions if report else [],
        timestamp=report.timestamp if report else "",
    )


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id}/execution-result
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/incidents/{incident_id}/execution-result",
    response_model=ExecutionResult,
    summary="查询执行结果",
    description="根据 incident_id 查询执行结果（实际 vs 计划完成时间、OTD、资源利用率）。",
    responses={404: {"description": "执行结果不存在"}},
)
async def get_execution_result(incident_id: UUID) -> ExecutionResult:
    key = str(incident_id)
    result = _writeback_module.get_execution_result(incident_id)
    if result is None:
        result = await fetch_execution_result_by_incident(incident_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No execution result for incident {incident_id}.",
        )
    return result



# ---------------------------------------------------------------------------
# GET /api/v1/decisions/{decision_record_id}/export/pdf
# ---------------------------------------------------------------------------


class ExportResponse(BaseModel):
    """Response for export endpoints."""

    filename: str
    content_type: str
    decision_record_id: str
    content_preview: str = ""
    created_at: str = ""


@router.get(
    "/api/v1/decisions/{decision_record_id}/export/pdf",
    response_model=ExportResponse,
    summary="导出决策记录 PDF",
    description="导出决策记录为 PDF 格式（含甘特图快照、推荐理由、关键 KPI）。",
    responses={404: {"description": "决策记录不存在"}},
)
async def export_pdf(decision_record_id: UUID) -> ExportResponse:
    # Find the decision record and register it for export
    record = await _find_decision_record(decision_record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision record {decision_record_id} not found.",
        )

    _register_for_export(record)

    try:
        result = _export_service.export_pdf(decision_record_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    return ExportResponse(
        filename=result.filename,
        content_type=result.content_type,
        decision_record_id=result.decision_record_id,
        content_preview=result.content[:200].decode("utf-8", errors="replace"),
        created_at=result.created_at,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/decisions/{decision_record_id}/export/excel
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/decisions/{decision_record_id}/export/excel",
    response_model=ExportResponse,
    summary="导出决策记录 Excel",
    description="导出决策记录为 Excel 格式（含完整 ScheduleDetail）。",
    responses={404: {"description": "决策记录不存在"}},
)
async def export_excel(decision_record_id: UUID) -> ExportResponse:
    record = await _find_decision_record(decision_record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision record {decision_record_id} not found.",
        )

    _register_for_export(record)

    try:
        result = _export_service.export_excel(decision_record_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    return ExportResponse(
        filename=result.filename,
        content_type=result.content_type,
        decision_record_id=result.decision_record_id,
        content_preview=result.content[:200].decode("utf-8", errors="replace"),
        created_at=result.created_at,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _find_decision_record(decision_record_id: UUID) -> DecisionRecord | None:
    """Find a decision record by ID across all stores."""
    target = str(decision_record_id)
    for record in _decision_record_store.values():
        if str(record.decision_record_id) == target:
            return record
    return await fetch_decision_record_by_id(decision_record_id)


def _register_for_export(record: DecisionRecord) -> None:
    """Register a decision record with the export service."""
    from app.api.solver import _plan_index

    _export_service.register_decision(record)

    # Try to find and register the confirmed plan
    plan = _plan_index.get(str(record.confirmed_plan_id))
    if plan:
        _export_service.register_decision(record, plan)
