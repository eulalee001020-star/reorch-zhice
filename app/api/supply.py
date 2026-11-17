"""Supply planning API: snapshot import, kit check, MRP, readiness, suppliers.

Provides:
- POST /api/v1/supply/snapshots — import material-side state
- GET  /api/v1/supply/kit-report — kit status of the current schedule
- GET  /api/v1/supply/mrp — time-phased netting of the schedule's needs
- GET  /api/v1/supply/readiness — arrived vs usable, with open gaps
- GET  /api/v1/supply/suppliers — supplier scores
- GET  /api/v1/incidents/{incident_id}/material-impact — effect of a supply incident
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.models.schedule import ScheduleSnapshot
from app.models.supply import (
    KitReport,
    MaterialImpact,
    MrpResult,
    ReadinessReport,
    SupplierScore,
    SupplySnapshot,
)
from app.services.intake.recovery_planning import (
    is_material_incident,
    material_event_from_incident,
)
from app.services.supply.bom import BomCycleError
from app.services.supply.kitting import check_kits, collect_requirements
from app.services.supply.mrp import run_mrp
from app.services.supply.readiness import readiness_report
from app.services.supply.shortage import ShortageEventError, assess
from app.services.supply.supplier_scorecard import score_suppliers

logger = logging.getLogger(__name__)

router = APIRouter(tags=["supply"])

# Latest supply snapshot. Supply state is kept in memory: it is re-imported
# with every schedule snapshot and is not yet part of the durable schema.
_supply_store: dict[str, SupplySnapshot] = {}


def current_supply() -> SupplySnapshot | None:
    """The most recently imported supply snapshot, if any."""
    if not _supply_store:
        return None
    return next(reversed(_supply_store.values()))


async def _current_schedule() -> ScheduleSnapshot:
    from app.api.analysis import current_snapshot

    snapshot = await current_snapshot()
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ScheduleSnapshot available. Import a schedule first.",
        )
    return snapshot


def _require_supply() -> SupplySnapshot:
    supply = current_supply()
    if supply is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No supply snapshot available. POST /api/v1/supply/snapshots first.",
        )
    return supply


@router.post(
    "/api/v1/supply/snapshots",
    response_model=SupplySnapshot,
    status_code=status.HTTP_201_CREATED,
    summary="导入物料侧快照",
    description="BOM、库存、在途与到货订单、供应商交付记录。与排程快照配套导入。",
)
async def create_supply_snapshot(body: SupplySnapshot) -> SupplySnapshot:
    try:
        from app.services.supply.bom import low_level_codes

        low_level_codes(body.bom)
    except BomCycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "BOM contains a cycle", "cycle": str(exc)},
        ) from exc
    _supply_store[str(body.supply_snapshot_id)] = body
    logger.info("Supply snapshot stored: %s", body.supply_snapshot_id)
    return body


@router.get(
    "/api/v1/supply/kit-report",
    response_model=KitReport,
    summary="齐套检查",
    description="按需求时间把库存和在途分配给各工序，给出每道工序的齐套时间。",
)
async def get_kit_report(
    risk_adjusted: bool = Query(False, description="按供应商历史延迟给承诺日期加缓冲"),
    allow_substitutes: bool = Query(False, description="允许使用已批准的替代料"),
    reference_time: datetime | None = Query(None, description="判断时点，默认为排程快照时间"),
) -> KitReport:
    supply = _require_supply()
    schedule = await _current_schedule()
    scores = {item.supplier_id: item for item in score_suppliers(supply)} if risk_adjusted else None
    return check_kits(
        supply,
        schedule,
        reference_time=reference_time,
        supplier_scores=scores,
        risk_adjusted=risk_adjusted,
        allow_substitutes=allow_substitutes,
    )


@router.get(
    "/api/v1/supply/mrp",
    response_model=MrpResult,
    summary="MRP 净需求",
    description="把排程的物料需求按时间分桶，与库存和在途对减，给出净需求和建议下达。",
)
async def get_mrp(
    bucket_minutes: int = Query(1440, ge=30, le=10080),
    bucket_count: int = Query(7, ge=1, le=60),
) -> MrpResult:
    supply = _require_supply()
    schedule = await _current_schedule()
    requirements = [
        (item_id, quantity, operation.start_time)
        for _work_order, operation, item_id, quantity in collect_requirements(supply, schedule)
    ]
    return run_mrp(
        supply,
        requirements,
        bucket_minutes=bucket_minutes,
        bucket_count=bucket_count,
        horizon_start=schedule.captured_at,
    )


@router.get(
    "/api/v1/supply/readiness",
    response_model=ReadinessReport,
    summary="到货与可用两层状态",
    description="区分“已到货”和“可使用”，列出挡住使用的缺项、责任人和完成时间。",
)
async def get_readiness(
    reference_time: datetime | None = Query(None),
) -> ReadinessReport:
    supply = _require_supply()
    if reference_time is None:
        reference_time = (await _current_schedule()).captured_at
    return readiness_report(supply, reference_time=reference_time)


@router.get(
    "/api/v1/supply/suppliers",
    response_model=list[SupplierScore],
    summary="供应商评分",
    description="按准时率、质量、延迟幅度和响应速度评分，并给出承诺日期的风险缓冲。",
)
async def get_supplier_scores() -> list[SupplierScore]:
    return score_suppliers(_require_supply())


@router.get(
    "/api/v1/incidents/{incident_id}/material-impact",
    response_model=MaterialImpact,
    summary="供应异常对齐套的影响",
    responses={404: {"description": "Incident 不存在或不是物料异常"}},
)
async def get_material_impact(incident_id: UUID) -> MaterialImpact:
    from app.api.incidents import _incident_store
    from app.services.storage.persistence import fetch_incident

    incident = _incident_store.get(str(incident_id)) or await fetch_incident(incident_id)
    if incident is None or not is_material_incident(incident):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} is not a material incident.",
        )
    supply = _require_supply()
    schedule = await _current_schedule()
    try:
        impact, _updated = assess(
            supply,
            schedule,
            material_event_from_incident(incident),
            reference_time=incident.occurred_at,
        )
    except ShortageEventError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return impact
