"""Dispatch API: shipment import, route planning, delivery impact of recovery.

Provides:
- POST /api/v1/dispatch/snapshots — import shipments and vehicles
- GET  /api/v1/dispatch/plan — routes for the current schedule
- GET  /api/v1/incidents/{incident_id}/dispatch-impact — delivery outcome of
  each candidate recovery plan, next to the original schedule
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.models.dispatch import DispatchImpact, DispatchPlan, DispatchSnapshot
from app.services.dispatch.planner import completion_by_work_order, plan_dispatch
from app.services.intake.recovery_planning import BASELINE_SOLVER_NAME

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dispatch"])

# Compatibility cache for local-demo reset; durable reads use the operational store.
_dispatch_store: dict[str, DispatchSnapshot] = {}

ORIGINAL_LABEL = "原计划"
BASELINE_LABEL = "只顺延不调整"
REPLAN_LABEL = "重排"
MATERIAL_OPTION_LABELS = {
    "wait_for_supply": "等待到货",
    "approved_substitute": "使用已批准替代料",
}


def current_dispatch() -> DispatchSnapshot | None:
    """Read the durable head so restarts and other workers see committed imports."""
    from app.api.production_runtime import get_operational_store

    payload = get_operational_store().latest_planning_snapshot("dispatch")
    return DispatchSnapshot.model_validate(payload) if payload is not None else None


def _require_dispatch() -> DispatchSnapshot:
    snapshot = current_dispatch()
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No dispatch snapshot available. POST /api/v1/dispatch/snapshots first.",
        )
    return snapshot


async def _require_schedule():
    from app.api.analysis import current_snapshot

    schedule = await current_snapshot()
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ScheduleSnapshot available. Import a schedule first.",
        )
    return schedule


@router.post(
    "/api/v1/dispatch/snapshots",
    response_model=DispatchSnapshot,
    status_code=status.HTTP_201_CREATED,
    summary="导入发运快照",
    description="待发运的货、对应工单、客户收货时间窗，以及可用车辆和班次。",
)
async def create_dispatch_snapshot(body: DispatchSnapshot) -> DispatchSnapshot:
    ids = [stop.shipment_id for stop in body.stops]
    if len(set(ids)) != len(ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="shipment_id values must be unique",
        )
    from app.api.production_runtime import get_operational_store

    try:
        get_operational_store().save_planning_snapshot(
            "dispatch", str(body.dispatch_snapshot_id), body.model_dump(mode="json")
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _dispatch_store[str(body.dispatch_snapshot_id)] = body
    logger.info("Dispatch snapshot stored: %s", body.dispatch_snapshot_id)
    return body


@router.get(
    "/api/v1/dispatch/plan",
    response_model=DispatchPlan,
    summary="按当前排程排线",
    description="每票货在对应工单完工后放行；时间窗赶不上时允许迟到并计入结果。",
)
async def get_dispatch_plan() -> DispatchPlan:
    snapshot = _require_dispatch()
    schedule = await _require_schedule()
    return await asyncio.to_thread(
        plan_dispatch,
        snapshot,
        completion_by_work_order(schedule.work_orders),
        label=ORIGINAL_LABEL,
    )


@router.get(
    "/api/v1/incidents/{incident_id}/dispatch-impact",
    response_model=DispatchImpact,
    summary="各恢复方案对发运的影响",
    description="对原计划和每个候选方案分别排线，比较迟到票数、发不出的票数和里程。",
    responses={404: {"description": "没有发运快照，或该异常还没有候选方案"}},
)
async def get_dispatch_impact(incident_id: UUID) -> DispatchImpact:
    from app.api.solver import _candidate_plans_store, _recommendation_store

    snapshot = _require_dispatch()
    schedule = await _require_schedule()
    key = str(incident_id)
    candidates = _candidate_plans_store.get(key)
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No candidate plans for incident {incident_id}. Solve it first.",
        )
    recommendation = _recommendation_store.get(key)
    recommended_id = str(recommendation.recommended_plan_id) if recommendation else None

    jobs = [(ORIGINAL_LABEL, None, False, completion_by_work_order(schedule.work_orders))]
    for plan in candidates:
        if plan.feasibility_status != "feasible":
            continue
        chain = plan.solver_chain
        if chain.solver_name == BASELINE_SOLVER_NAME:
            label = BASELINE_LABEL
        else:
            option = MATERIAL_OPTION_LABELS.get(chain.key_parameters.get("material_option"))
            label = f"{REPLAN_LABEL}·{option}" if option else REPLAN_LABEL
        jobs.append(
            (
                label,
                str(plan.plan_id),
                str(plan.plan_id) == recommended_id,
                completion_by_work_order(plan.schedule_detail.work_orders),
            )
        )

    plans = [
        await asyncio.to_thread(
            plan_dispatch,
            snapshot,
            completions,
            label=label,
            source_plan_id=plan_id,
            is_recommended=recommended,
        )
        for label, plan_id, recommended, completions in jobs
    ]
    return DispatchImpact(
        incident_id=incident_id,
        dispatch_snapshot_id=snapshot.dispatch_snapshot_id,
        plans=plans,
    )
