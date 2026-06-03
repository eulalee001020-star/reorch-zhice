"""NGS lab repair scheduling API."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status

from app.models.ngs import (
    NgsBatchReplayRequest,
    NgsBatchReplayResponse,
    NgsLabDemoResponse,
    NgsPlannerDecisionRecord,
    NgsPlannerDecisionRequest,
    NgsPlannerDecisionResponse,
)
from app.services.ngs_lab import NgsProtectedPortfolioService

router = APIRouter(prefix="/api/v1/ngs-lab", tags=["ngs-lab"])
_ngs_planner_decisions: list[NgsPlannerDecisionRecord] = []


@router.post(
    "/demo-run",
    response_model=NgsLabDemoResponse,
    summary="运行 NGS 实验室 protected repair portfolio 样例",
)
async def run_ngs_lab_demo() -> NgsLabDemoResponse:
    return NgsProtectedPortfolioService().run_demo()


@router.post(
    "/batch-replay",
    response_model=NgsBatchReplayResponse,
    summary="读取 NGS 实验包并运行 batch replay",
)
async def run_ngs_lab_batch_replay(
    body: NgsBatchReplayRequest | None = None,
) -> NgsBatchReplayResponse:
    try:
        if body and body.package_payload is not None:
            return NgsProtectedPortfolioService().run_batch_replay(
                package_payload=body.package_payload,
                source_name=body.source_name,
            )
        return NgsProtectedPortfolioService().run_batch_replay()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/planner-decisions",
    response_model=NgsPlannerDecisionResponse,
    summary="记录 NGS replay 后的计划员确认、驳回或 override",
)
async def record_ngs_planner_decision(
    body: NgsPlannerDecisionRequest,
) -> NgsPlannerDecisionResponse:
    action = body.action.strip().lower()
    if action not in {"confirm", "reject", "override"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="action must be confirm, reject, or override.",
        )
    if action == "confirm" and not body.selected_candidate_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="selected_candidate_id is required for confirm.",
        )
    if action == "reject" and not body.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="reason is required for reject.",
        )
    if action == "override" and not (body.selected_candidate_id and body.override_reason):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="selected_candidate_id and override_reason are required for override.",
        )

    record = NgsPlannerDecisionRecord(
        decision_id=f"ngs_decision_{uuid4().hex[:8]}",
        package_id=body.package_id,
        case_id=body.case_id,
        action=action,
        selected_candidate_id=body.selected_candidate_id,
        planner_id=body.planner_id,
        reason=body.reason,
        override_reason=body.override_reason,
        audit_refs=[
            f"ngs_package:{body.package_id}",
            f"replay_case:{body.case_id}",
            f"candidate:{body.selected_candidate_id}" if body.selected_candidate_id else "candidate:none",
        ],
    )
    _ngs_planner_decisions.append(record)
    return NgsPlannerDecisionResponse(record=record, records=list(_ngs_planner_decisions))


@router.get(
    "/planner-decisions",
    response_model=list[NgsPlannerDecisionRecord],
    summary="查询 NGS replay 计划员决策记录",
)
async def list_ngs_planner_decisions(
    package_id: str | None = Query(default=None),
    case_id: str | None = Query(default=None),
) -> list[NgsPlannerDecisionRecord]:
    records = list(_ngs_planner_decisions)
    if package_id:
        records = [record for record in records if record.package_id == package_id]
    if case_id:
        records = [record for record in records if record.case_id == case_id]
    return records
