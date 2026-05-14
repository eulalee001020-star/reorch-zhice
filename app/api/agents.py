"""Controlled Agent workflow API endpoints.

These endpoints expose the ReOrch agent architecture as an auditable,
bounded workflow. Agents coordinate the flow; deterministic services own
impact calculation, solving, evaluation, confirmation, and writeback.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, get_optional_current_user
from app.models.agent import (
    AgentDecisionFlowRequest,
    AgentDecisionFlowResponse,
    FeedbackStructuringOutput,
    FeedbackStructuringRequest,
    IncidentUnderstandingOutput,
    IncidentUnderstandingRequest,
)
from app.services.agent_workflow import (
    AgentOrchestrator,
    AgentWorkflowNotFoundError,
    FeedbackAgent,
    IncidentAgent,
)
from app.services.persistence import record_entity_version

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.post(
    "/incident/understand",
    response_model=IncidentUnderstandingOutput,
    summary="自然语言异常理解",
    description=(
        "将报警文本或人工描述转换为标准 incident 字段。"
        "低置信度或当前求解器不支持的类型只进入人工确认，不自动求解。"
    ),
)
async def understand_incident_text(
    body: IncidentUnderstandingRequest,
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> IncidentUnderstandingOutput:
    _ = current_user
    return await IncidentAgent().understand_text(body)


@router.post(
    "/decision-flow",
    response_model=AgentDecisionFlowResponse,
    summary="运行受控 Agent 决策流",
    description=(
        "从已有 Incident 出发，按 Orchestrator -> Impact -> Strategy -> Solver "
        "-> Evaluation -> Explanation -> Confirmation 的受控链路生成建议。"
        "接口不会自动确认，也不会自动写回 MES。"
    ),
)
async def run_agent_decision_flow(
    body: AgentDecisionFlowRequest,
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> AgentDecisionFlowResponse:
    try:
        return await AgentOrchestrator().run_decision_flow(
            body,
            user_id=current_user.user_id,
        )
    except AgentWorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/feedback/structure",
    response_model=FeedbackStructuringOutput,
    summary="结构化人工 override 原因",
    description=(
        "把人工覆盖、拒绝或执行反馈整理为 case library 的归因候选，"
        "用于后续规则沉淀；不会直接修改排程约束。"
    ),
)
async def structure_feedback(
    body: FeedbackStructuringRequest,
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> FeedbackStructuringOutput:
    output = await FeedbackAgent().structure_override(body)
    entity_id = str(output.decision_record_id or output.incident_id or uuid4())
    await record_entity_version(
        entity_type="feedback_case_candidate",
        entity_id=entity_id,
        data=output.model_dump(mode="json"),
        changed_by=current_user.user_id,
    )
    return output
