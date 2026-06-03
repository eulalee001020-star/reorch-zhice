"""Controlled Agent workflow API endpoints.

These endpoints expose the ReOrch agent architecture as an auditable,
bounded workflow. Agents coordinate the flow; deterministic services own
impact calculation, solving, evaluation, confirmation, and writeback.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, get_optional_current_user
from app.models.agent import (
    AgentDecisionFlowRequest,
    AgentDecisionFlowResponse,
    CaseMemoryOutput,
    CaseMemoryRequest,
    FeedbackStructuringOutput,
    FeedbackStructuringRequest,
    IncidentUnderstandingOutput,
    IncidentUnderstandingRequest,
    PostDecisionLearningOutput,
    PostDecisionLearningRequest,
    PreferenceLearningOutput,
    PreferenceLearningRequest,
    RuleCandidateListResponse,
    RuleCandidateOutput,
    RuleCandidatePublicationRecord,
    RuleCandidatePublishRequest,
    RuleCandidateRequest,
    RuleCandidateReplayRequest,
    RuleCandidateReplayResult,
    RuleCandidateReviewRecord,
    RuleCandidateReviewRequest,
)
from app.services.agent_workflow import (
    AgentOrchestrator,
    AgentWorkflowNotFoundError,
    CaseMemoryAgent,
    FeedbackAgent,
    IncidentAgent,
    PostDecisionLearningAgent,
    PreferenceLearningAgent,
    RuleCandidateAgent,
)
from app.services.persistence import record_entity_version

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])
_rule_candidate_review_store: dict[str, RuleCandidateReviewRecord] = {}


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
    "/rules/compile",
    response_model=RuleCandidateOutput,
    summary="生成待审核规则候选",
    description=(
        "把计划员规则、override 原因或现场复盘文本转换为 constraint candidate。"
        "候选规则只进入人工审核和 replay，不会直接发布为生产硬约束。"
    ),
)
async def compile_rule_candidates(
    body: RuleCandidateRequest,
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> RuleCandidateOutput:
    output = await RuleCandidateAgent().compile_rules(body)
    for candidate in output.candidates:
        record = _upsert_rule_candidate_review_record(candidate)
        await record_entity_version(
            entity_type="constraint_candidate",
            entity_id=candidate.candidate_id,
            data=record.model_dump(mode="json"),
            changed_by=current_user.user_id,
        )
    return output


@router.get(
    "/rules/candidates",
    response_model=RuleCandidateListResponse,
    summary="查询规则候选审核队列",
    description=(
        "返回 RuleCandidateAgent 生成的候选规则及人工审核、replay 和只读发布状态。"
        "这里展示的是候选生命周期，不代表生产约束已经生效。"
    ),
)
async def list_rule_candidates(
    candidate_status: str | None = Query(default=None, alias="status"),
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> RuleCandidateListResponse:
    _ = current_user
    records = list(_rule_candidate_review_store.values())
    if candidate_status:
        records = [record for record in records if record.status == candidate_status]
    records.sort(key=lambda record: record.updated_at, reverse=True)
    return RuleCandidateListResponse(
        records=records,
        status_counts=_rule_candidate_status_counts(),
    )


@router.post(
    "/rules/candidates/{candidate_id}/review",
    response_model=RuleCandidateReviewRecord,
    summary="人工审核规则候选",
    description=(
        "计划员可将候选规则送入 replay，或填写拒绝原因。"
        "被拒绝的候选不会进入 replay 或发布。"
    ),
)
async def review_rule_candidate(
    candidate_id: str,
    body: RuleCandidateReviewRequest,
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> RuleCandidateReviewRecord:
    record = _get_rule_candidate_record(candidate_id)
    action = body.action.strip().lower()
    if action in {"approve", "approve_for_replay", "request_replay"}:
        record.status = "approved_for_replay"
        record.candidate.status = record.status
        record.reviewer_id = body.reviewer_id
        record.review_note = body.review_note
        record.reject_reason = None
    elif action in {"reject", "rejected"}:
        if not body.reject_reason:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="reject_reason is required when rejecting a rule candidate.",
            )
        record.status = "rejected"
        record.candidate.status = record.status
        record.reviewer_id = body.reviewer_id
        record.review_note = body.review_note
        record.reject_reason = body.reject_reason
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="action must be approve_for_replay or reject.",
        )
    record.updated_at = datetime.now(tz=timezone.utc)
    await _record_rule_candidate_version(record, current_user.user_id)
    return record


@router.post(
    "/rules/candidates/{candidate_id}/replay",
    response_model=RuleCandidateReviewRecord,
    summary="对候选规则运行 replay 检查",
    description=(
        "执行确定性 replay 闸门：置信度、范围、规则类型和场景覆盖必须满足最小条件。"
        "通过后只进入待发布状态，不自动成为生产硬约束。"
    ),
)
async def replay_rule_candidate(
    candidate_id: str,
    body: RuleCandidateReplayRequest,
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> RuleCandidateReviewRecord:
    record = _get_rule_candidate_record(candidate_id)
    if record.status == "rejected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rejected candidates cannot run replay.",
        )
    if record.status not in {"approved_for_replay", "replay_failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Candidate must be approved_for_replay before replay.",
        )

    replay_result = _run_rule_candidate_replay(record, body)
    record.replay_result = replay_result
    record.status = "replay_passed" if replay_result.pass_replay else "replay_failed"
    record.candidate.status = record.status
    record.updated_at = datetime.now(tz=timezone.utc)
    await _record_rule_candidate_version(record, current_user.user_id)
    return record


@router.post(
    "/rules/candidates/{candidate_id}/publish",
    response_model=RuleCandidateReviewRecord,
    summary="发布 replay 通过的规则候选为只读记录",
    description=(
        "只生成可审计发布记录，表明该候选可以进入后续配置发布流程。"
        "本接口不直接修改求解器配置或客户系统。"
    ),
)
async def publish_rule_candidate(
    candidate_id: str,
    body: RuleCandidatePublishRequest,
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> RuleCandidateReviewRecord:
    record = _get_rule_candidate_record(candidate_id)
    if record.status != "replay_passed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only replay_passed candidates can be published.",
        )
    record.published_record = RuleCandidatePublicationRecord(
        release_id=f"rule_release_{uuid4().hex[:8]}",
        candidate_id=candidate_id,
        published_by=body.publisher_id,
        release_note=body.release_note,
    )
    record.status = "published_readonly"
    record.candidate.status = record.status
    record.updated_at = datetime.now(tz=timezone.utc)
    await _record_rule_candidate_version(record, current_user.user_id)
    return record


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


@router.post(
    "/case-memory/archive",
    response_model=CaseMemoryOutput,
    summary="沉淀决策案例",
    description=(
        "把确认后的 DecisionRecord 和 ExecutionResult 归档为 Case Library 案例。"
        "案例可用于相似检索、失败归因和后续偏好学习，不会自动发布为规则。"
    ),
)
async def archive_case_memory(
    body: CaseMemoryRequest,
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> CaseMemoryOutput:
    from app.api.cases import _case_library

    output = await CaseMemoryAgent(_case_library).archive(body)
    await record_entity_version(
        entity_type="case_memory_output",
        entity_id=str(output.case_record.case_id),
        data=output.model_dump(mode="json"),
        changed_by=current_user.user_id,
    )
    return output


@router.post(
    "/preference/learn",
    response_model=PreferenceLearningOutput,
    summary="学习计划员偏好",
    description=(
        "从案例库、override history 和执行反馈中生成偏好画像。"
        "偏好只作为推荐排序辅助，不能覆盖硬约束、质量门和人工确认。"
    ),
)
async def learn_preference(
    body: PreferenceLearningRequest,
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> PreferenceLearningOutput:
    from app.api.cases import _case_library

    output = await PreferenceLearningAgent(_case_library).learn(body)
    await record_entity_version(
        entity_type="preference_learning_output",
        entity_id=body.planner_id,
        data=output.model_dump(mode="json"),
        changed_by=current_user.user_id,
    )
    return output


@router.post(
    "/post-decision-learning",
    response_model=PostDecisionLearningOutput,
    summary="确认后运行规则候选、案例沉淀和偏好学习",
    description=(
        "从已确认 DecisionRecord 和 ExecutionResult 出发，按 "
        "RuleCandidateAgent -> CaseMemoryAgent -> PreferenceLearningAgent "
        "生成可审计学习资产。候选规则仍保持人工审核状态，偏好只作为排序辅助。"
    ),
)
async def run_post_decision_learning(
    body: PostDecisionLearningRequest,
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> PostDecisionLearningOutput:
    from app.api.cases import _case_library

    try:
        output = await PostDecisionLearningAgent(_case_library).run(body)
    except AgentWorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    case_id = str(output.case_memory_output.case_record.case_id)
    planner_id = output.preference_learning_output.preference_profile.planner_id
    for candidate in output.rule_candidate_output.candidates:
        record = _upsert_rule_candidate_review_record(candidate)
        await _record_rule_candidate_version(record, current_user.user_id)
    await record_entity_version(
        entity_type="post_decision_learning_output",
        entity_id=case_id,
        data=output.model_dump(mode="json"),
        changed_by=current_user.user_id,
    )
    await record_entity_version(
        entity_type="preference_learning_output",
        entity_id=planner_id,
        data=output.preference_learning_output.model_dump(mode="json"),
        changed_by=current_user.user_id,
    )
    return output


def _upsert_rule_candidate_review_record(
    candidate,
) -> RuleCandidateReviewRecord:
    record = _rule_candidate_review_store.get(candidate.candidate_id)
    now = datetime.now(tz=timezone.utc)
    if record is None:
        record = RuleCandidateReviewRecord(candidate=candidate, updated_at=now)
        _rule_candidate_review_store[candidate.candidate_id] = record
    else:
        record.candidate = candidate
        record.status = candidate.status
        record.updated_at = now
    return record


def _get_rule_candidate_record(candidate_id: str) -> RuleCandidateReviewRecord:
    record = _rule_candidate_review_store.get(candidate_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule candidate {candidate_id} not found.",
        )
    return record


def _rule_candidate_status_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in _rule_candidate_review_store.values():
        counts[record.status] = counts.get(record.status, 0) + 1
    return counts


def _run_rule_candidate_replay(
    record: RuleCandidateReviewRecord,
    request: RuleCandidateReplayRequest,
) -> RuleCandidateReplayResult:
    candidate = record.candidate
    notes = list(request.notes)
    blocked_reason: str | None = None
    if candidate.constraint_type == "review_note":
        blocked_reason = "rule_type_or_scope_unclear"
    elif candidate.confidence < 0.65:
        blocked_reason = "candidate_confidence_below_replay_threshold"
    elif candidate.constraint_type in {"calendar", "skill", "forbidden_assignment"}:
        machine_ids = candidate.scope.get("machine_ids")
        if not machine_ids:
            blocked_reason = "missing_machine_scope"
    elif "缺少明确" in (candidate.risk_note or ""):
        blocked_reason = "risk_note_requires_more_scope"

    pass_replay = blocked_reason is None
    notes.append(
        "Replay checks only validate historical/scenario behavior; production enablement still requires configuration review."
    )
    return RuleCandidateReplayResult(
        pass_replay=pass_replay,
        scenario_count=max(0, request.scenario_count),
        blocked_reason=blocked_reason,
        metrics={
            "confidence": candidate.confidence,
            "scenario_set": request.scenario_set,
            "source_ref_count": len(candidate.source_refs),
            "readonly_publish_required": True,
        },
        notes=notes,
    )


async def _record_rule_candidate_version(
    record: RuleCandidateReviewRecord,
    changed_by: str,
) -> None:
    await record_entity_version(
        entity_type="constraint_candidate_review",
        entity_id=record.candidate.candidate_id,
        data=record.model_dump(mode="json"),
        changed_by=changed_by,
    )
