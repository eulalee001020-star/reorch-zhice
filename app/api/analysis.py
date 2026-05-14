"""Impact Analysis & Strategy Selector API endpoints.

Validates: Requirements 2.6, 3.7, 18.4

Provides:
- GET  /api/v1/incidents/{incident_id}/impact-report — query impact report
- GET  /api/v1/incidents/{incident_id}/strategy — query strategy recommendation
- POST /api/v1/schedule-snapshots — import schedule snapshot (APS data import)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, get_optional_current_user
from app.models.case import PreferenceProfile
from app.models.impact import ImpactReport
from app.models.schedule import ScheduleSnapshot
from app.models.strategy import StrategyRecommendation
from app.services.impact_analysis_engine import ImpactAnalysisEngine
from app.services.persistence import (
    assign_snapshot_version,
    fetch_any_snapshot,
    fetch_impact_report,
    fetch_incident,
    fetch_strategy_recommendation,
    persist_impact_report,
    persist_schedule_snapshot,
    persist_strategy_recommendation,
)
from app.services.strategy_selector import StrategySelector

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])

# ---------------------------------------------------------------------------
# Local fallback caches used only when PostgreSQL is unavailable in dev/test.
# ---------------------------------------------------------------------------
_snapshot_store: dict[str, ScheduleSnapshot] = {}
_impact_report_cache: dict[str, ImpactReport] = {}
_strategy_cache: dict[str, StrategyRecommendation] = {}


# ---------------------------------------------------------------------------
# POST /api/v1/schedule-snapshots — import schedule snapshot
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/schedule-snapshots",
    response_model=ScheduleSnapshot,
    status_code=status.HTTP_201_CREATED,
    summary="导入排程快照",
    description="接收来自 APS 系统的排程快照数据，存储为不可变的 ScheduleSnapshot。",
)
async def create_schedule_snapshot(
    body: ScheduleSnapshot,
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> ScheduleSnapshot:
    body = await assign_snapshot_version(body)
    body.created_by = body.created_by or current_user.user_id
    key = str(body.snapshot_id)
    _snapshot_store[key] = body
    await persist_schedule_snapshot(body, user_id=current_user.user_id)
    logger.info("Schedule snapshot stored: %s", key)
    return body


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id}/impact-report
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/incidents/{incident_id}/impact-report",
    response_model=ImpactReport,
    summary="查询影响报告",
    description="根据 incident_id 查询影响范围分析报告。首次请求时执行分析并缓存结果。",
    responses={404: {"description": "Incident 或 ScheduleSnapshot 不存在"}},
)
async def get_impact_report(incident_id: UUID) -> ImpactReport:
    # Return cached report if available
    cache_key = str(incident_id)
    if cache_key in _impact_report_cache:
        return _impact_report_cache[cache_key]

    persisted_report = await fetch_impact_report(incident_id)
    if persisted_report is not None:
        _impact_report_cache[cache_key] = persisted_report
        return persisted_report

    # Look up incident from the incidents API in-memory store
    from app.api.incidents import _incident_store

    incident = _incident_store.get(cache_key)
    if incident is None:
        incident = await fetch_incident(incident_id)
        if incident is not None:
            _incident_store[cache_key] = incident
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )

    # Find a matching snapshot — pick the first available one for MVP
    snapshot: ScheduleSnapshot | None = None
    for snap in _snapshot_store.values():
        snapshot = snap
        break
    if snapshot is None:
        snapshot = await fetch_any_snapshot()
        if snapshot is not None:
            _snapshot_store[str(snapshot.snapshot_id)] = snapshot

    engine = ImpactAnalysisEngine()
    report = await engine.analyze(incident, snapshot)

    _impact_report_cache[cache_key] = report
    await persist_impact_report(report)
    return report


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id}/strategy
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/incidents/{incident_id}/strategy",
    response_model=StrategyRecommendation,
    summary="查询策略推荐",
    description=(
        "根据 incident_id 查询高层策略推荐。"
        "需要先有影响报告（自动触发分析）。"
    ),
    responses={404: {"description": "Incident 不存在或影响报告尚未生成"}},
)
async def get_strategy(
    incident_id: UUID,
    estimated_repair_time_minutes: float = Query(
        60.0, description="设备预计修复时间（分钟），默认 60"
    ),
) -> StrategyRecommendation:
    cache_key = str(incident_id)

    # Return cached strategy if available
    if cache_key in _strategy_cache:
        return _strategy_cache[cache_key]

    persisted_strategy = await fetch_strategy_recommendation(incident_id)
    if persisted_strategy is not None:
        _strategy_cache[cache_key] = persisted_strategy
        return persisted_strategy

    # Ensure impact report exists (trigger analysis if needed)
    if cache_key not in _impact_report_cache:
        # Try to generate it
        report = await get_impact_report(incident_id)
    else:
        report = _impact_report_cache[cache_key]

    # Determine total_active_work_orders from snapshot
    total_active_work_orders = 0
    for snap in _snapshot_store.values():
        total_active_work_orders = len(snap.work_orders)
        break

    # Use empty similar_cases and default PreferenceProfile for MVP
    similar_cases: list = []
    preference_profile = PreferenceProfile(
        planner_id="default",
        strategy_preferences={},
        adjustment_patterns=[],
        override_history=[],
        updated_at=datetime.now(tz=timezone.utc),
    )

    selector = StrategySelector()
    recommendation = await selector.select_strategy(
        impact_report=report,
        similar_cases=similar_cases,
        preference_profile=preference_profile,
        total_active_work_orders=total_active_work_orders,
        estimated_repair_time_minutes=estimated_repair_time_minutes,
    )

    _strategy_cache[cache_key] = recommendation
    await persist_strategy_recommendation(incident_id, recommendation)
    return recommendation
