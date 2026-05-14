"""Controlled agent workflow for ReOrch.

The agents here organize the decision flow. They do not bypass constraints:
impact analysis, strategy selection, solving, evaluation, recommendation, and
writeback remain deterministic services or optimization tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from app.models.agent import (
    AgentDecisionFlowRequest,
    AgentDecisionFlowResponse,
    AgentTraceStep,
    FeedbackStructuringOutput,
    FeedbackStructuringRequest,
    IncidentUnderstandingOutput,
    IncidentUnderstandingRequest,
)
from app.models.case import PreferenceProfile
from app.models.enums import GoalMode, IncidentType, ReportSource
from app.models.evaluation import ComparisonMatrix
from app.models.explanation import RecommendationExplanation, SolverChainExplanation
from app.models.impact import ImpactReport
from app.models.incident import Incident, IncidentCreateRequest
from app.models.recommendation import PlanSelectionOutput
from app.models.schedule import ScheduleSnapshot
from app.models.solver import CandidatePlan
from app.models.strategy import StrategyRecommendation
from app.services.evaluation_center import EvaluationCenter
from app.services.explainability_layer import ExplainabilityLayer
from app.services.hybrid_solver import HybridSolver
from app.services.impact_analysis_engine import ImpactAnalysisEngine
from app.services.persistence import (
    fetch_any_snapshot,
    fetch_incident,
    persist_candidate_plans,
    persist_impact_report,
    persist_plan_recommendation,
    persist_strategy_recommendation,
)
from app.services.plan_recommendation_engine import PlanRecommendationEngine
from app.services.plan_selection_input_builder import PlanSelectionInputBuilder
from app.services.solver_policy_orchestrator import SolverPolicyOrchestrator
from app.services.strategy_selector import StrategySelector


_MACHINE_RESOURCE_RE = re.compile(
    r"\b((?:CNC|MC|M|EQ|LINE)[-_ ]?\d{1,4})\b",
    flags=re.IGNORECASE,
)
_GENERIC_RESOURCE_RE = re.compile(
    r"(?:设备|机台|机器|产线)\s*([A-Za-z]{0,4}[-_ ]?\d{1,4})",
    flags=re.IGNORECASE,
)
_CLOCK_RE = re.compile(r"(?:after\s*)?([01]?\d|2[0-3]):([0-5]\d)", re.IGNORECASE)


class AgentWorkflowError(Exception):
    """Base error for controlled agent workflow failures."""


class AgentWorkflowNotFoundError(AgentWorkflowError):
    """Raised when a required persisted object cannot be found."""


@dataclass(frozen=True)
class _ParsedIncident:
    incident_type: str
    resource_id: str | None
    estimated_duration_minutes: int | None
    risk_hint: str | None
    confidence: float
    supported_by_solver: bool
    requires_human_confirmation: bool
    unsupported_reason: str | None


def _trace(
    *,
    agent_name: str,
    input_summary: str,
    output_summary: str,
    freedom_level: str,
    llm_allowed: bool,
    deterministic_tools: list[str] | None = None,
    guardrail: str,
) -> AgentTraceStep:
    return AgentTraceStep(
        agent_name=agent_name,
        input_summary=input_summary,
        output_summary=output_summary,
        freedom_level=freedom_level,
        llm_allowed=llm_allowed,
        deterministic_tools=deterministic_tools or [],
        guardrail=guardrail,
    )


def _default_preference_profile(planner_id: str) -> PreferenceProfile:
    return PreferenceProfile(
        planner_id=planner_id,
        strategy_preferences={},
        adjustment_patterns=[],
        override_history=[],
        updated_at=datetime.now(tz=timezone.utc),
    )


class IncidentAgent:
    """Low-freedom incident understanding from text or alarm payloads."""

    async def understand_text(
        self, request: IncidentUnderstandingRequest
    ) -> IncidentUnderstandingOutput:
        text = request.text.strip()
        parsed = _parse_incident_text(text)

        create_request: IncidentCreateRequest | None = None
        if (
            parsed.supported_by_solver
            and not parsed.requires_human_confirmation
            and parsed.resource_id is not None
        ):
            create_request = IncidentCreateRequest(
                incident_type=IncidentType.EQUIPMENT_FAILURE,
                occurred_at=request.occurred_at or datetime.now(tz=timezone.utc),
                workshop_id=request.workshop_id,
                resource_id=parsed.resource_id,
                report_source=_parse_report_source(request.report_source),
                source_system=request.source_system,
                description=text,
                raw_payload={
                    "source_text": text,
                    "incident_agent": {
                        "incident_type": parsed.incident_type,
                        "estimated_duration_minutes": parsed.estimated_duration_minutes,
                        "risk_hint": parsed.risk_hint,
                        "confidence": parsed.confidence,
                    },
                },
            )

        trace = _trace(
            agent_name="Incident Agent",
            input_summary=f"text_length={len(text)}",
            output_summary=(
                f"type={parsed.incident_type}, resource={parsed.resource_id}, "
                f"confidence={parsed.confidence:.2f}"
            ),
            freedom_level="low",
            llm_allowed=True,
            deterministic_tools=["keyword_classifier", "resource_regex", "duration_parser"],
            guardrail=(
                "字段补全必须带置信度；低置信度或非求解支持类型进入人工确认，"
                "不会自动进入求解流程。"
            ),
        )

        return IncidentUnderstandingOutput(
            incident_type=parsed.incident_type,
            resource_id=parsed.resource_id,
            estimated_duration_minutes=parsed.estimated_duration_minutes,
            risk_hint=parsed.risk_hint,
            confidence=parsed.confidence,
            requires_human_confirmation=parsed.requires_human_confirmation,
            supported_by_solver=parsed.supported_by_solver,
            unsupported_reason=parsed.unsupported_reason,
            normalized_fields={
                "incident_type": parsed.incident_type,
                "machine_id": parsed.resource_id,
                "estimated_duration": parsed.estimated_duration_minutes,
                "risk_hint": parsed.risk_hint,
            },
            incident_create_request=create_request,
            trace=[trace],
        )


class ImpactAnalysisAgent:
    """Impact agent: deterministic impact computation wrapper."""

    async def run(
        self,
        incident: Incident,
        snapshot: ScheduleSnapshot | None,
        *,
        user_id: str | None,
    ) -> tuple[ImpactReport, AgentTraceStep]:
        report = await ImpactAnalysisEngine().analyze(incident, snapshot)
        await persist_impact_report(report, user_id=user_id)

        from app.api.analysis import _impact_report_cache

        _impact_report_cache[str(incident.incident_id)] = report
        return report, _trace(
            agent_name="Impact Analysis Agent",
            input_summary=f"incident={incident.incident_id}, snapshot={getattr(snapshot, 'snapshot_id', None)}",
            output_summary=(
                f"affected_work_orders={len(report.affected_work_orders)}, "
                f"affected_operations={len(report.affected_operations)}"
            ),
            freedom_level="none",
            llm_allowed=False,
            deterministic_tools=["ImpactAnalysisEngine"],
            guardrail="只调用影响范围计算工具，不自由生成影响数据。",
        )


class StrategyAgent:
    """Strategy recommendation under explicit rule constraints."""

    async def run(
        self,
        impact_report: ImpactReport,
        snapshot: ScheduleSnapshot | None,
        *,
        planner_id: str,
        estimated_repair_time_minutes: float,
        user_id: str | None,
    ) -> tuple[StrategyRecommendation, PreferenceProfile, AgentTraceStep]:
        preference_profile = _default_preference_profile(planner_id)
        total_active_work_orders = len(snapshot.work_orders) if snapshot else 0

        recommendation = await StrategySelector().select_strategy(
            impact_report=impact_report,
            similar_cases=[],
            preference_profile=preference_profile,
            total_active_work_orders=total_active_work_orders,
            estimated_repair_time_minutes=estimated_repair_time_minutes,
        )
        await persist_strategy_recommendation(
            impact_report.incident_id,
            recommendation,
            user_id=user_id,
        )

        from app.api.analysis import _strategy_cache

        _strategy_cache[str(impact_report.incident_id)] = recommendation
        return recommendation, preference_profile, _trace(
            agent_name="Strategy Agent",
            input_summary=(
                f"affected_orders={len(impact_report.affected_work_orders)}, "
                f"downtime={estimated_repair_time_minutes:.1f}min"
            ),
            output_summary=(
                f"strategy={recommendation.strategy_type}, "
                f"confidence={recommendation.confidence:.2f}"
            ),
            freedom_level="medium",
            llm_allowed=True,
            deterministic_tools=["StrategySelector"],
            guardrail=(
                "策略依据来自影响工序、受影响订单、downtime、slack、priority、"
                "可替代机器和设备负载等规则因子。"
            ),
        )


class SolverAgent:
    """Solver tool wrapper. It must call optimization services."""

    async def run(
        self,
        *,
        incident: Incident,
        impact_report: ImpactReport,
        strategy: StrategyRecommendation,
        preference_profile: PreferenceProfile,
        snapshot: ScheduleSnapshot,
        user_id: str | None,
    ) -> tuple[list[CandidatePlan], AgentTraceStep]:
        bundle = await SolverPolicyOrchestrator().build_solver_policy(
            incident=incident,
            impact_report=impact_report,
            strategy=strategy,
            preference_profile=preference_profile,
            similar_cases=[],
        )
        candidates = await HybridSolver().solve(
            bundle=bundle,
            impact_report=impact_report,
            snapshot=snapshot,
        )
        await persist_candidate_plans(
            incident.incident_id,
            candidates,
            baseline_snapshot_id=snapshot.snapshot_id,
            user_id=user_id,
        )

        from app.api.solver import _candidate_plans_store, _plan_index

        key = str(incident.incident_id)
        _candidate_plans_store[key] = candidates
        for plan in candidates:
            _plan_index[str(plan.plan_id)] = plan

        return candidates, _trace(
            agent_name="Solver Tool / Solver Agent",
            input_summary=f"strategy={strategy.strategy_type}, snapshot={snapshot.snapshot_id}",
            output_summary=f"candidate_count={len(candidates)}",
            freedom_level="none",
            llm_allowed=False,
            deterministic_tools=["SolverPolicyOrchestrator", "HybridSolver", "ConstraintValidator"],
            guardrail="不能自由生成方案，必须调用排程算法和约束校验。",
        )


class EvaluationAgent:
    """Evaluation agent: deterministic KPI and recommendation tools."""

    async def run(
        self,
        *,
        incident: Incident,
        snapshot: ScheduleSnapshot,
        candidates: list[CandidatePlan],
        goal_mode: GoalMode | str,
        manual_weights: dict[str, float] | None,
        user_id: str | None,
    ) -> tuple[ComparisonMatrix, PlanSelectionOutput, AgentTraceStep]:
        matrix = await EvaluationCenter().evaluate(
            candidates=candidates,
            snapshot=snapshot,
            goal_mode=goal_mode,
        )
        selection_input = PlanSelectionInputBuilder.build(
            incident=incident,
            snapshot_id=snapshot.snapshot_id,
            candidates=candidates,
            goal_mode=goal_mode,
            preference_profile=None,
            case_matches=[],
            manual_weights=manual_weights,
        )
        recommendation = await PlanRecommendationEngine().recommend(selection_input)
        await persist_plan_recommendation(incident.incident_id, recommendation, user_id=user_id)

        from app.api.solver import _recommendation_store

        _recommendation_store[str(incident.incident_id)] = recommendation
        return matrix, recommendation, _trace(
            agent_name="Evaluation Agent",
            input_summary=f"candidate_count={len(candidates)}, goal_mode={goal_mode}",
            output_summary=f"recommended_plan={recommendation.recommended_plan_id}",
            freedom_level="none",
            llm_allowed=False,
            deterministic_tools=["EvaluationCenter", "PlanRecommendationEngine"],
            guardrail="只计算指标对比和推荐排序，不能篡改候选方案数据。",
        )


class ExplanationAgent:
    """Natural-language explanation over immutable plan and KPI data."""

    async def run(
        self,
        *,
        recommended_plan: CandidatePlan,
        alternatives: list[CandidatePlan],
        comparison_matrix: ComparisonMatrix,
    ) -> tuple[RecommendationExplanation, SolverChainExplanation, AgentTraceStep]:
        layer = ExplainabilityLayer()
        recommendation_explanation = await layer.explain_recommendation(
            recommended_plan=recommended_plan,
            alternatives=alternatives,
            comparison_matrix=comparison_matrix,
            matched_cases=[],
        )
        solver_chain_explanation = await layer.explain_solver_chain(recommended_plan)
        return recommendation_explanation, solver_chain_explanation, _trace(
            agent_name="Explanation Agent",
            input_summary=f"recommended_plan={recommended_plan.plan_id}",
            output_summary="recommendation_explanation_and_solver_chain",
            freedom_level="medium",
            llm_allowed=True,
            deterministic_tools=["ExplainabilityLayer"],
            guardrail="可以自然语言表达，但不能修改指标、方案和约束校验结果。",
        )


class FeedbackAgent:
    """Structure planner overrides into case-library learning candidates."""

    async def structure_override(
        self, request: FeedbackStructuringRequest
    ) -> FeedbackStructuringOutput:
        text = request.override_text.strip()
        resource_id = _extract_resource_id(text)
        time_hint = _extract_time_hint(text)
        lowered = text.lower()

        if any(token in lowered for token in ("operator", "unavailable", "shift")) or any(
            token in text for token in ("操作员", "人员", "班次", "不在", "不可用")
        ):
            reason = "operator_preference"
            confidence = 0.86 if resource_id and time_hint else 0.76
            detail = text
            if resource_id and time_hint:
                future_rule = f"avoid assigning urgent jobs to {resource_id} after {time_hint}"
            elif resource_id:
                future_rule = f"review assignment constraints for {resource_id}"
            else:
                future_rule = "review operator availability before urgent assignment"
        elif any(token in text for token in ("物料", "材料", "齐套", "缺料")):
            reason = "material_constraint"
            confidence = 0.8
            detail = text
            future_rule = "check material readiness before releasing repaired plan"
        elif resource_id is not None:
            reason = "resource_constraint"
            confidence = 0.78
            detail = text
            future_rule = f"review future assignments involving {resource_id}"
        else:
            reason = "manual_business_judgment"
            confidence = 0.62
            detail = text
            future_rule = None

        trace = _trace(
            agent_name="Feedback Agent",
            input_summary=f"text_length={len(text)}",
            output_summary=f"override_reason={reason}, confidence={confidence:.2f}",
            freedom_level="medium",
            llm_allowed=True,
            deterministic_tools=["override_classifier", "resource_regex", "time_parser"],
            guardrail="只沉淀归因和候选规则，不直接改排程约束或写回策略。",
        )

        return FeedbackStructuringOutput(
            override_reason=reason,
            reason_detail=detail,
            future_rule_candidate=future_rule,
            confidence=round(confidence, 2),
            requires_human_review=confidence < 0.75,
            decision_record_id=request.decision_record_id,
            incident_id=request.incident_id,
            trace=[trace],
        )


class AgentOrchestrator:
    """Controlled workflow coordinator for the ReOrch decision loop."""

    async def run_decision_flow(
        self,
        request: AgentDecisionFlowRequest,
        *,
        user_id: str | None,
    ) -> AgentDecisionFlowResponse:
        incident = await _load_incident(request.incident_id)
        snapshot = await _load_latest_snapshot()
        trace: list[AgentTraceStep] = [
            _trace(
                agent_name="Orchestrator",
                input_summary=f"incident={request.incident_id}",
                output_summary="workflow_started",
                freedom_level="low",
                llm_allowed=False,
                deterministic_tools=["workflow_state_machine"],
                guardrail="按受控顺序组织 Agent，不允许跳过影响分析、约束求解和人工确认。",
            )
        ]

        impact_report, impact_trace = await ImpactAnalysisAgent().run(
            incident,
            snapshot,
            user_id=user_id,
        )
        trace.append(impact_trace)

        strategy, preference_profile, strategy_trace = await StrategyAgent().run(
            impact_report,
            snapshot,
            planner_id=request.planner_id,
            estimated_repair_time_minutes=request.estimated_repair_time_minutes,
            user_id=user_id,
        )
        trace.append(strategy_trace)

        candidates: list[CandidatePlan] = []
        comparison_matrix: ComparisonMatrix | None = None
        recommendation: PlanSelectionOutput | None = None
        recommendation_explanation: RecommendationExplanation | None = None
        solver_chain_explanation: SolverChainExplanation | None = None

        if request.auto_solve and snapshot is not None:
            candidates, solver_trace = await SolverAgent().run(
                incident=incident,
                impact_report=impact_report,
                strategy=strategy,
                preference_profile=preference_profile,
                snapshot=snapshot,
                user_id=user_id,
            )
            trace.append(solver_trace)
        elif request.auto_solve:
            trace.append(
                _trace(
                    agent_name="Solver Tool / Solver Agent",
                    input_summary="snapshot=None",
                    output_summary="solver_skipped_no_schedule_snapshot",
                    freedom_level="none",
                    llm_allowed=False,
                    deterministic_tools=["ScheduleSnapshotGuard"],
                    guardrail="没有排程快照时不能生成伪方案。",
                )
            )

        if request.auto_recommend and candidates and snapshot is not None:
            comparison_matrix, recommendation, evaluation_trace = await EvaluationAgent().run(
                incident=incident,
                snapshot=snapshot,
                candidates=candidates,
                goal_mode=request.goal_mode,
                manual_weights=request.manual_weights,
                user_id=user_id,
            )
            trace.append(evaluation_trace)

            recommended = _find_candidate(candidates, recommendation.recommended_plan_id)
            if recommended is not None:
                alternatives = [plan for plan in candidates if plan.plan_id != recommended.plan_id]
                (
                    recommendation_explanation,
                    solver_chain_explanation,
                    explanation_trace,
                ) = await ExplanationAgent().run(
                    recommended_plan=recommended,
                    alternatives=alternatives,
                    comparison_matrix=comparison_matrix,
                )
                trace.append(explanation_trace)

        trace.append(
            _trace(
                agent_name="Confirmation Agent",
                input_summary=f"recommendation={getattr(recommendation, 'recommended_plan_id', None)}",
                output_summary="pending_human_confirmation",
                freedom_level="none",
                llm_allowed=False,
                deterministic_tools=["ConfirmationModule"],
                guardrail="不会自动确认、不会自动写回 MES；必须由有权限用户形成 DecisionRecord。",
            )
        )

        return AgentDecisionFlowResponse(
            incident=incident,
            impact_report=impact_report,
            strategy=strategy,
            candidate_plans=candidates,
            comparison_matrix=comparison_matrix,
            recommendation=recommendation,
            recommendation_explanation=recommendation_explanation,
            solver_chain_explanation=solver_chain_explanation,
            requires_human_confirmation=True,
            trace=trace,
        )


async def _load_incident(incident_id: UUID) -> Incident:
    from app.api.incidents import _incident_store

    key = str(incident_id)
    incident = _incident_store.get(key)
    if incident is None:
        incident = await fetch_incident(incident_id)
        if incident is not None:
            _incident_store[key] = incident
    if incident is None:
        raise AgentWorkflowNotFoundError(f"Incident {incident_id} not found")
    return incident


async def _load_latest_snapshot() -> ScheduleSnapshot | None:
    from app.api.analysis import _snapshot_store

    if _snapshot_store:
        return max(_snapshot_store.values(), key=lambda snapshot: snapshot.captured_at)

    snapshot = await fetch_any_snapshot()
    if snapshot is not None:
        _snapshot_store[str(snapshot.snapshot_id)] = snapshot
    return snapshot


def _find_candidate(candidates: list[CandidatePlan], plan_id: UUID) -> CandidatePlan | None:
    for candidate in candidates:
        if str(candidate.plan_id) == str(plan_id):
            return candidate
    return None


def _parse_report_source(value: str) -> ReportSource:
    try:
        return ReportSource(value)
    except ValueError:
        return ReportSource.MANUAL


def _parse_incident_text(text: str) -> _ParsedIncident:
    resource_id = _extract_resource_id(text)
    estimated_duration = _extract_duration_minutes(text)
    risk_hint = "urgent_order_delay" if _has_urgent_risk(text) else None
    incident_type = _detect_incident_type(text, resource_id)
    supported_by_solver = incident_type == "machine_down"

    confidence = _confidence(
        incident_type=incident_type,
        resource_id=resource_id,
        estimated_duration_minutes=estimated_duration,
        risk_hint=risk_hint,
    )

    unsupported_reason: str | None = None
    if not supported_by_solver:
        unsupported_reason = (
            "Current PoC solver supports machine_down via equipment_failure; "
            f"{incident_type} needs customer adapter/rule extension before auto-solving."
        )
    elif resource_id is None:
        unsupported_reason = "Missing machine/resource id."

    requires_confirmation = (
        confidence < 0.75
        or not supported_by_solver
        or resource_id is None
        or incident_type == "unknown"
    )

    return _ParsedIncident(
        incident_type=incident_type,
        resource_id=resource_id,
        estimated_duration_minutes=estimated_duration,
        risk_hint=risk_hint,
        confidence=confidence,
        supported_by_solver=supported_by_solver,
        requires_human_confirmation=requires_confirmation,
        unsupported_reason=unsupported_reason,
    )


def _detect_incident_type(text: str, resource_id: str | None) -> str:
    lowered = text.lower()
    if _is_machine_down(text, lowered, resource_id):
        return "machine_down"
    if any(token in text for token in ("物料", "材料", "缺料", "齐套", "没到", "未到")) or "material" in lowered:
        return "material_shortage"
    if any(token in text for token in ("客户加急", "急单", "加急", "插单")) or "urgent" in lowered:
        return "urgent_order_insert"
    if any(token in text for token in ("产能下降", "产能降低", "降速", "效率下降", "设备产能")) or "capacity" in lowered:
        return "capacity_degradation"
    return "unknown"


def _is_machine_down(text: str, lowered: str, resource_id: str | None) -> bool:
    machine_failure_terms = ("坏", "停了", "停机", "故障", "宕机", "down", "failure", "stopped")
    if any(term in lowered for term in ("down", "failure", "stopped")):
        return True
    if any(term in text for term in machine_failure_terms):
        return resource_id is not None or any(token in text for token in ("设备", "机台", "机器", "产线", "CNC"))
    return False


def _has_urgent_risk(text: str) -> bool:
    lowered = text.lower()
    return any(token in text for token in ("急单", "加急", "客户急")) or "urgent" in lowered


def _confidence(
    *,
    incident_type: str,
    resource_id: str | None,
    estimated_duration_minutes: int | None,
    risk_hint: str | None,
) -> float:
    if incident_type == "unknown":
        return 0.25

    score = 0.68 if incident_type == "machine_down" else 0.62
    if resource_id:
        score += 0.22
    elif incident_type == "machine_down":
        score -= 0.18
    if estimated_duration_minutes is not None:
        score += 0.06
    if risk_hint is not None:
        score += 0.03
    if incident_type != "machine_down":
        score = min(score, 0.72)
    return round(max(0.1, min(score, 0.98)), 2)


def _extract_resource_id(text: str) -> str | None:
    match = _MACHINE_RESOURCE_RE.search(text)
    if match is None:
        match = _GENERIC_RESOURCE_RE.search(text)
    if match is None:
        return None
    resource = match.group(1).upper().replace(" ", "")
    return resource.replace("_", "-")


def _extract_time_hint(text: str) -> str | None:
    match = _CLOCK_RE.search(text)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"
    cn_match = re.search(r"([01]?\d|2[0-3])\s*点(?:半)?(?:以后|后|之后)?", text)
    if cn_match:
        return f"{int(cn_match.group(1)):02d}:00"
    return None


def _extract_duration_minutes(text: str) -> int | None:
    patterns = [
        (re.compile(r"(\d+(?:\.\d+)?)\s*(?:个)?\s*(小时|钟头|h|hour|hours)", re.IGNORECASE), 60),
        (re.compile(r"(\d+(?:\.\d+)?)\s*(?:分钟|分|min|mins|minute|minutes)", re.IGNORECASE), 1),
    ]
    for pattern, multiplier in patterns:
        match = pattern.search(text)
        if match:
            return int(round(float(match.group(1)) * multiplier))

    cn_hour = re.search(r"([一二两俩三四五六七八九十半]+)\s*(?:个)?\s*(小时|钟头)", text)
    if cn_hour:
        return int(round(_parse_chinese_number(cn_hour.group(1)) * 60))

    cn_minute = re.search(r"([一二两俩三四五六七八九十]+)\s*(?:分钟|分)", text)
    if cn_minute:
        return int(round(_parse_chinese_number(cn_minute.group(1))))

    return None


def _parse_chinese_number(value: str) -> float:
    if value == "半":
        return 0.5
    digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "俩": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value == "十":
        return 10
    if "十" in value:
        left, _, right = value.partition("十")
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return float(digits.get(value, 0))
