"""Layer 3 Solver, Evaluation, Recommendation API endpoints.

Validates: Requirements 27.1, 27.5, 29.1, 30.6, 30.8

Provides:
- POST /api/v1/incidents/{incident_id}/solve — trigger solving
- GET  /api/v1/incidents/{incident_id}/candidate-plans — list candidate plans
- GET  /api/v1/candidate-plans/{plan_id} — plan detail (ScheduleDetail, SolverChain)
- GET  /api/v1/candidate-plans/{plan_id}/gantt — plan gantt data
- POST /api/v1/incidents/{incident_id}/recommend — trigger recommendation
- GET  /api/v1/incidents/{incident_id}/recommendation — query PlanSelectionOutput
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.models.case import PreferenceProfile
from app.models.enums import GoalMode
from app.models.recommendation import PlanSelectionInput, PlanSelectionOutput
from app.models.schedule import GanttDiffPayload, ScheduleDetail
from app.models.solver import CandidatePlan, SolverChain

logger = logging.getLogger(__name__)

router = APIRouter(tags=["solver"])

# ---------------------------------------------------------------------------
# Local fallback caches used only when PostgreSQL is unavailable in dev/test.
# ---------------------------------------------------------------------------
_candidate_plans_store: dict[str, list[CandidatePlan]] = {}  # incident_id -> plans
_plan_index: dict[str, CandidatePlan] = {}  # plan_id -> plan
_recommendation_store: dict[str, PlanSelectionOutput] = {}  # incident_id -> output


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class SolveRequest(BaseModel):
    """Optional body for POST /solve — currently empty, may carry overrides."""
    pass


class RecommendRequest(BaseModel):
    """Body for POST /recommend — supports GoalMode and manual_weights."""

    goal_mode: str = Field(
        default=GoalMode.BALANCED.value,
        description="业务目标模式：delivery_priority / stability_priority / bottleneck_priority / cost_priority / balanced",
    )
    manual_weights: dict[str, float] | None = Field(
        default=None,
        description="人工微调权重覆盖（可选）",
    )


# ---------------------------------------------------------------------------
# POST /api/v1/incidents/{incident_id}/solve — trigger solving
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/incidents/{incident_id}/solve",
    response_model=list[CandidatePlan],
    status_code=status.HTTP_200_OK,
    summary="触发求解",
    description=(
        "根据 incident_id 触发混合优化求解引擎，生成 Top-3 候选方案。"
        "需要先有 Incident、ScheduleSnapshot 和影响报告/策略推荐。"
    ),
    responses={404: {"description": "Incident 或依赖数据不存在"}},
)
async def solve_incident(incident_id: UUID, body: SolveRequest | None = None) -> list[CandidatePlan]:
    from app.api.analysis import _impact_report_cache, _snapshot_store, _strategy_cache
    from app.api.incidents import _incident_store
    from app.services.hybrid_solver import HybridSolver
    from app.services.persistence import (
        fetch_any_snapshot,
        fetch_impact_report,
        fetch_incident,
        fetch_strategy_recommendation,
        persist_candidate_plans,
    )
    from app.services.solver_policy_orchestrator import SolverPolicyOrchestrator

    key = str(incident_id)

    # 1. Look up incident
    incident = _incident_store.get(key)
    if incident is None:
        incident = await fetch_incident(incident_id)
        if incident is not None:
            _incident_store[key] = incident
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )

    # 2. Look up impact report
    impact_report = _impact_report_cache.get(key)
    if impact_report is None:
        impact_report = await fetch_impact_report(incident_id)
        if impact_report is not None:
            _impact_report_cache[key] = impact_report
    if impact_report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Impact report for incident {incident_id} not found. Run impact analysis first.",
        )

    # 3. Look up strategy
    strategy = _strategy_cache.get(key)
    if strategy is None:
        strategy = await fetch_strategy_recommendation(incident_id)
        if strategy is not None:
            _strategy_cache[key] = strategy
    if strategy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy for incident {incident_id} not found. Run strategy selection first.",
        )

    # 4. Find snapshot
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

    # 5. Build SolverPolicyBundle
    preference_profile = PreferenceProfile(
        planner_id="default",
        strategy_preferences={},
        adjustment_patterns=[],
        override_history=[],
        updated_at=datetime.now(tz=timezone.utc),
    )

    orchestrator = SolverPolicyOrchestrator()
    bundle = await orchestrator.build_solver_policy(
        incident=incident,
        impact_report=impact_report,
        strategy=strategy,
        preference_profile=preference_profile,
        similar_cases=[],
    )

    # 6. Solve
    solver = HybridSolver()
    candidates = await solver.solve(
        bundle=bundle,
        impact_report=impact_report,
        snapshot=snapshot,
    )

    # 7. Store results
    _candidate_plans_store[key] = candidates
    for plan in candidates:
        _plan_index[str(plan.plan_id)] = plan
    await persist_candidate_plans(
        incident_id,
        candidates,
        baseline_snapshot_id=snapshot.snapshot_id,
    )

    logger.info("Solve completed for incident %s: %d candidate(s)", key, len(candidates))
    return candidates


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id}/candidate-plans — list candidate plans
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/incidents/{incident_id}/candidate-plans",
    response_model=list[CandidatePlan],
    summary="查询候选方案列表",
    description="根据 incident_id 查询已生成的候选方案列表。",
    responses={404: {"description": "Incident 不存在或尚未求解"}},
)
async def list_candidate_plans(incident_id: UUID) -> list[CandidatePlan]:
    from app.services.persistence import list_candidate_plans_from_db

    key = str(incident_id)
    plans = _candidate_plans_store.get(key)
    if plans is None:
        db_plans = await list_candidate_plans_from_db(incident_id)
        if db_plans:
            _candidate_plans_store[key] = db_plans
            for plan in db_plans:
                _plan_index[str(plan.plan_id)] = plan
            plans = db_plans
    if plans is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No candidate plans found for incident {incident_id}. Trigger solve first.",
        )
    return plans


# ---------------------------------------------------------------------------
# GET /api/v1/candidate-plans/{plan_id} — plan detail
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/candidate-plans/{plan_id}",
    response_model=CandidatePlan,
    summary="查询方案详情",
    description="根据 plan_id 查询候选方案详情，含 ScheduleDetail 和 SolverChain。",
    responses={404: {"description": "方案不存在"}},
)
async def get_candidate_plan(plan_id: UUID) -> CandidatePlan:
    from app.services.persistence import fetch_candidate_plan

    key = str(plan_id)
    plan = _plan_index.get(key)
    if plan is None:
        plan = await fetch_candidate_plan(plan_id)
        if plan is not None:
            _plan_index[key] = plan
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate plan {plan_id} not found",
        )
    return plan


# ---------------------------------------------------------------------------
# GET /api/v1/candidate-plans/{plan_id}/gantt — gantt data
# ---------------------------------------------------------------------------


class GanttResponse(BaseModel):
    """Gantt chart data for a candidate plan."""

    plan_id: str
    schedule_detail: ScheduleDetail
    gantt_version: str
    solver_chain: SolverChain


@router.get(
    "/api/v1/candidate-plans/{plan_id}/gantt",
    response_model=GanttResponse,
    summary="查询方案甘特图数据",
    description="根据 plan_id 查询候选方案的甘特图渲染数据（ScheduleDetail + SolverChain）。",
    responses={404: {"description": "方案不存在"}},
)
async def get_candidate_plan_gantt(plan_id: UUID) -> GanttResponse:
    plan = await get_candidate_plan(plan_id)
    return GanttResponse(
        plan_id=str(plan.plan_id),
        schedule_detail=plan.schedule_detail,
        gantt_version=plan.gantt_version,
        solver_chain=plan.solver_chain,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/incidents/{incident_id}/recommend — trigger recommendation
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/incidents/{incident_id}/recommend",
    response_model=PlanSelectionOutput,
    status_code=status.HTTP_200_OK,
    summary="触发推荐",
    description=(
        "根据 incident_id 触发方案推荐引擎，支持 GoalMode 和 manual_weights 参数。"
        "需要先有候选方案（先调用 /solve）。"
    ),
    responses={404: {"description": "Incident 或候选方案不存在"}},
)
async def recommend_plan(
    incident_id: UUID,
    body: RecommendRequest | None = None,
) -> PlanSelectionOutput:
    from app.api.analysis import _snapshot_store
    from app.api.incidents import _incident_store
    from app.services.persistence import (
        fetch_any_snapshot,
        fetch_incident,
        list_candidate_plans_from_db,
        persist_plan_recommendation,
    )
    from app.services.plan_recommendation_engine import PlanRecommendationEngine
    from app.services.plan_selection_input_builder import PlanSelectionInputBuilder

    key = str(incident_id)

    # 1. Look up incident
    incident = _incident_store.get(key)
    if incident is None:
        incident = await fetch_incident(incident_id)
        if incident is not None:
            _incident_store[key] = incident
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )

    # 2. Look up candidate plans
    candidates = _candidate_plans_store.get(key)
    if not candidates:
        db_candidates = await list_candidate_plans_from_db(incident_id)
        if db_candidates:
            candidates = db_candidates
            _candidate_plans_store[key] = candidates
            for plan in candidates:
                _plan_index[str(plan.plan_id)] = plan
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No candidate plans for incident {incident_id}. Trigger solve first.",
        )

    # 3. Find snapshot
    snapshot_id = None
    for snap in _snapshot_store.values():
        snapshot_id = snap.snapshot_id
        break
    if snapshot_id is None:
        snapshot = await fetch_any_snapshot()
        if snapshot is not None:
            snapshot_id = snapshot.snapshot_id
    if snapshot_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ScheduleSnapshot available.",
        )

    # 4. Parse request body
    goal_mode = GoalMode.BALANCED.value
    manual_weights = None
    if body is not None:
        goal_mode = body.goal_mode
        manual_weights = body.manual_weights

    # 5. Build PlanSelectionInput via builder
    selection_input = PlanSelectionInputBuilder.build(
        incident=incident,
        snapshot_id=snapshot_id,
        candidates=candidates,
        goal_mode=goal_mode,
        manual_weights=manual_weights,
    )

    # 6. Run recommendation engine
    engine = PlanRecommendationEngine()
    output = await engine.recommend(selection_input)

    # 7. Store result
    _recommendation_store[key] = output
    await persist_plan_recommendation(incident_id, output)

    logger.info(
        "Recommendation completed for incident %s: recommended=%s, confidence=%.2f",
        key,
        output.recommended_plan_id,
        output.recommendation_confidence,
    )
    return output


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id}/recommendation — query recommendation
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/incidents/{incident_id}/recommendation",
    response_model=PlanSelectionOutput,
    summary="查询推荐结果",
    description="根据 incident_id 查询 PlanSelectionOutput 推荐结果。",
    responses={404: {"description": "推荐结果不存在"}},
)
async def get_recommendation(incident_id: UUID) -> PlanSelectionOutput:
    from app.services.persistence import fetch_plan_recommendation

    key = str(incident_id)
    output = _recommendation_store.get(key)
    if output is None:
        output = await fetch_plan_recommendation(incident_id)
        if output is not None:
            _recommendation_store[key] = output
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No recommendation found for incident {incident_id}. Trigger recommend first.",
        )
    return output
