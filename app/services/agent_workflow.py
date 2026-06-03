"""Controlled agent workflow for ReOrch.

The agents here organize the decision flow. They do not bypass constraints:
impact analysis, strategy selection, solving, evaluation, recommendation, and
writeback remain deterministic services or optimization tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.models.agent import (
    AgentDecisionFlowRequest,
    AgentDecisionFlowResponse,
    AgentTraceStep,
    CaseMemoryOutput,
    CaseMemoryRequest,
    ConstraintCandidate,
    FeedbackStructuringOutput,
    FeedbackStructuringRequest,
    IncidentUnderstandingOutput,
    IncidentUnderstandingRequest,
    PostDecisionLearningOutput,
    PostDecisionLearningRequest,
    PreferenceLearningOutput,
    PreferenceLearningRequest,
    RuleCandidateOutput,
    RuleCandidateRequest,
)
from app.models.case import PreferenceProfile
from app.models.decision import DecisionRecord
from app.models.enums import GoalMode, IncidentType, ReportSource, StrategyType
from app.models.evaluation import ComparisonMatrix
from app.models.execution import ExecutionResult
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
from app.services.llm_agent_client import LLMAgentClient, LLMJsonResult
from app.services.persistence import (
    fetch_any_snapshot,
    fetch_incident,
    persist_candidate_plans,
    persist_impact_report,
    persist_plan_recommendation,
    persist_strategy_recommendation,
)
from app.services.plan_quality_gate import PlanQualityGate
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
    llm_result: LLMJsonResult | None = None,
    fallback_reason: str | None = None,
    deterministic_tools: list[str] | None = None,
    guardrail: str,
) -> AgentTraceStep:
    return AgentTraceStep(
        agent_name=agent_name,
        input_summary=input_summary,
        output_summary=output_summary,
        freedom_level=freedom_level,
        llm_allowed=llm_allowed,
        llm_used=llm_result is not None,
        llm_provider=llm_result.provider if llm_result else None,
        model_name=llm_result.model if llm_result else None,
        latency_ms=llm_result.latency_ms if llm_result else None,
        input_tokens=llm_result.input_tokens if llm_result else None,
        output_tokens=llm_result.output_tokens if llm_result else None,
        fallback_reason=fallback_reason,
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
        llm_result: LLMJsonResult | None = None
        fallback_reason: str | None = None
        try:
            llm_result = await LLMAgentClient().complete_json(
                agent_name="Incident Agent",
                system_prompt=(
                    "You extract manufacturing disruption incidents for a controlled "
                    "scheduling copilot. Output fields: incident_type, resource_id, "
                    "estimated_duration_minutes, risk_hint, confidence, "
                    "supported_by_solver, requires_human_confirmation, unsupported_reason. "
                    "Supported auto-solve incident_type is machine_down only."
                ),
                user_payload={
                    "text": text,
                    "workshop_id": request.workshop_id,
                    "source_system": request.source_system,
                    "report_source": request.report_source,
                },
            )
        except Exception as exc:  # pragma: no cover - network/provider dependent
            fallback_reason = f"llm_call_failed:{type(exc).__name__}"

        parsed = _parsed_incident_from_llm(llm_result.data) if llm_result else None
        if parsed is None:
            parsed = _parse_incident_text(text)
            fallback_reason = fallback_reason or "llm_disabled_or_invalid_json_fallback"

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
            llm_result=llm_result,
            fallback_reason=fallback_reason,
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

    target_candidate_count: int = 3

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
        orchestrator = SolverPolicyOrchestrator()
        solver = HybridSolver()
        candidates: list[CandidatePlan] = []
        strategy_sequence = _candidate_strategy_sequence(strategy.strategy_type)

        for strategy_type in strategy_sequence:
            current_strategy = (
                strategy
                if _strategy_value(strategy.strategy_type) == strategy_type.value
                else _comparison_strategy(strategy, strategy_type)
            )
            bundle = await orchestrator.build_solver_policy(
                incident=incident,
                impact_report=impact_report,
                strategy=current_strategy,
                preference_profile=preference_profile,
                similar_cases=[],
            )
            generated = await solver.solve(
                bundle=bundle,
                impact_report=impact_report,
                snapshot=snapshot,
            )
            if not generated:
                continue

            if _strategy_value(current_strategy.strategy_type) == _strategy_value(strategy.strategy_type):
                candidates.extend(generated)
            else:
                candidates.append(generated[0])

            if len(candidates) >= self.target_candidate_count:
                break

        candidates = candidates[: self.target_candidate_count]
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
            output_summary=(
                f"candidate_count={len(candidates)}, "
                f"strategies={','.join(_strategy_value(plan.strategy_type) for plan in candidates)}"
            ),
            freedom_level="none",
            llm_allowed=False,
            deterministic_tools=["SolverPolicyOrchestrator", "HybridSolver", "ConstraintValidator"],
            guardrail=(
                "不能自由生成方案，必须调用排程算法和约束校验；"
                "若推荐策略不足 Top-K，补充对照策略候选供计划员比较。"
            ),
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


class RuleCandidateAgent:
    """Compile planner text into reviewable constraint candidates."""

    async def compile_rules(self, request: RuleCandidateRequest) -> RuleCandidateOutput:
        text = request.rule_text.strip()
        if not text:
            trace = _trace(
                agent_name="Rule Candidate Agent",
                input_summary="text_length=0",
                output_summary="candidate_count=0",
                freedom_level="medium",
                llm_allowed=True,
                deterministic_tools=["rule_text_guard"],
                guardrail="空规则文本不能生成约束候选。",
            )
            return RuleCandidateOutput(
                candidates=[],
                requires_human_review=True,
                trace=[trace],
            )

        llm_result: LLMJsonResult | None = None
        fallback_reason: str | None = None
        try:
            llm_result = await LLMAgentClient().complete_json(
                agent_name="Rule Candidate Agent",
                system_prompt=(
                    "You convert planner feedback into one reviewable scheduling "
                    "constraint candidate. Output fields: constraint_type, scope, "
                    "compiled_rule, confidence, risk_note. The status must remain "
                    "pending_human_review and the rule must not be auto-published."
                ),
                user_payload={
                    "rule_text": text,
                    "context": request.context,
                    "source": request.source,
                    "incident_id": str(request.incident_id) if request.incident_id else None,
                    "decision_record_id": (
                        str(request.decision_record_id)
                        if request.decision_record_id
                        else None
                    ),
                },
            )
        except Exception as exc:  # pragma: no cover - network/provider dependent
            fallback_reason = f"llm_call_failed:{type(exc).__name__}"

        candidate = (
            _constraint_candidate_from_llm(
                data=llm_result.data,
                text=text,
                source=request.source,
                incident_id=request.incident_id,
                decision_record_id=request.decision_record_id,
            )
            if llm_result
            else None
        )
        if candidate is None:
            candidate = _compile_constraint_candidate(
                text=text,
                context=request.context,
                source=request.source,
                incident_id=request.incident_id,
                decision_record_id=request.decision_record_id,
            )
            fallback_reason = fallback_reason or "llm_disabled_or_invalid_json_fallback"

        trace = _trace(
            agent_name="Rule Candidate Agent",
            input_summary=f"text_length={len(text)}, source={request.source}",
            output_summary=(
                f"type={candidate.constraint_type}, "
                f"confidence={candidate.confidence:.2f}, status={candidate.status}"
            ),
            freedom_level="medium",
            llm_allowed=True,
            llm_result=llm_result,
            fallback_reason=fallback_reason,
            deterministic_tools=["constraint_classifier", "resource_regex", "time_parser"],
            guardrail=(
                "只生成 pending_human_review 候选规则，不发布 hard constraint，"
                "不直接修改求解器权重或生产主数据。"
            ),
        )
        return RuleCandidateOutput(
            candidates=[candidate],
            requires_human_review=True,
            trace=[trace],
        )


class FeedbackAgent:
    """Structure planner overrides into case-library learning candidates."""

    async def structure_override(
        self, request: FeedbackStructuringRequest
    ) -> FeedbackStructuringOutput:
        text = request.override_text.strip()
        llm_result: LLMJsonResult | None = None
        fallback_reason: str | None = None
        try:
            llm_result = await LLMAgentClient().complete_json(
                agent_name="Feedback Agent",
                system_prompt=(
                    "You structure planner override feedback for a scheduling "
                    "case library. Output fields: override_reason, reason_detail, "
                    "future_rule_candidate, confidence. Use conservative labels; "
                    "do not convert one feedback sample into an active hard rule."
                ),
                user_payload={
                    "override_text": text,
                    "planner_id": request.planner_id,
                    "incident_id": str(request.incident_id) if request.incident_id else None,
                    "decision_record_id": (
                        str(request.decision_record_id)
                        if request.decision_record_id
                        else None
                    ),
                },
            )
        except Exception as exc:  # pragma: no cover - network/provider dependent
            fallback_reason = f"llm_call_failed:{type(exc).__name__}"

        structured = _feedback_from_llm(llm_result.data, text) if llm_result else None
        if structured is None:
            structured = _deterministic_feedback_structure(text)
            fallback_reason = fallback_reason or "llm_disabled_or_invalid_json_fallback"

        reason = structured["reason"]
        detail = structured["detail"]
        future_rule = structured["future_rule"]
        confidence = structured["confidence"]

        rule_candidates: list[ConstraintCandidate] = []
        rule_trace: list[AgentTraceStep] = []
        if future_rule:
            rule_output = await RuleCandidateAgent().compile_rules(
                RuleCandidateRequest(
                    rule_text=text,
                    context={"future_rule_candidate": future_rule},
                    source="feedback_agent",
                    incident_id=request.incident_id,
                    decision_record_id=request.decision_record_id,
                )
            )
            rule_candidates = rule_output.candidates
            rule_trace = rule_output.trace

        trace = _trace(
            agent_name="Feedback Agent",
            input_summary=f"text_length={len(text)}",
            output_summary=f"override_reason={reason}, confidence={confidence:.2f}",
            freedom_level="medium",
            llm_allowed=True,
            llm_result=llm_result,
            fallback_reason=fallback_reason,
            deterministic_tools=["override_classifier", "resource_regex", "time_parser"],
            guardrail="只沉淀归因和候选规则，不直接改排程约束或写回策略。",
        )

        return FeedbackStructuringOutput(
            override_reason=reason,
            reason_detail=detail,
            future_rule_candidate=future_rule,
            rule_candidates=rule_candidates,
            confidence=round(confidence, 2),
            requires_human_review=confidence < 0.75,
            decision_record_id=request.decision_record_id,
            incident_id=request.incident_id,
            trace=[trace, *rule_trace],
        )


class CaseMemoryAgent:
    """Archive confirmed decisions as reusable, searchable cases."""

    def __init__(self, case_library=None) -> None:
        self._case_library = case_library

    async def archive(self, request: CaseMemoryRequest) -> CaseMemoryOutput:
        case_library = self._case_library
        if case_library is None:
            from app.services.case_library import CaseLibrary

            case_library = CaseLibrary()

        case = await case_library.create_case(
            request.decision_record,
            request.execution_result,
        )
        case_title = _build_case_title(request.decision_record)
        incident_signature = _build_incident_signature(request.decision_record)
        reusability = _case_reusability(case)

        trace = _trace(
            agent_name="Case Memory Agent",
            input_summary=(
                f"decision_record={request.decision_record.decision_record_id}, "
                f"execution_result={request.execution_result.incident_id}"
            ),
            output_summary=f"case={case.case_id}, status={request.case_status}",
            freedom_level="medium",
            llm_allowed=True,
            deterministic_tools=["CaseLibrary.create_case", "case_signature_builder"],
            guardrail=(
                "沉淀案例和归因，不把单次案例自动发布为规则，"
                "没有执行反馈的案例只能作为待验证资产。"
            ),
        )
        return CaseMemoryOutput(
            case_record=case,
            case_title=case_title,
            incident_signature=incident_signature,
            reusability=reusability,
            status=request.case_status,
            trace=[trace],
        )


class PreferenceLearningAgent:
    """Learn planner preference signals without changing solver constraints."""

    def __init__(self, case_library=None) -> None:
        self._case_library = case_library

    async def learn(self, request: PreferenceLearningRequest) -> PreferenceLearningOutput:
        case_records = list(request.case_records)
        if not case_records and self._case_library is not None:
            case_records = self._case_library.list_cases()

        if request.existing_profile is not None:
            profile = request.existing_profile
        elif self._case_library is not None:
            profile = self._case_library.get_preference_profile(request.planner_id)
        else:
            profile = _default_preference_profile(request.planner_id)

        sample_count = len(case_records)
        evidence_summary: list[str] = []
        profile.override_history = [
            {
                "case_id": str(case.case_id),
                "strategy_type": case.strategy_type,
                "override_reason": case.override_reason,
                "created_at": case.created_at.isoformat(),
                "effect": "decrease overridden strategy weight during ranking tie-breaks",
            }
            for case in case_records
            if case.is_override
        ]
        profile.adjustment_patterns = [
            {
                "case_id": str(case.case_id),
                "strategy_type": case.strategy_type,
                "signal": "override" if case.is_override else "confirmed",
                "effect": (
                    "negative ranking signal"
                    if case.is_override
                    else "positive ranking signal"
                ),
                "created_at": case.created_at.isoformat(),
            }
            for case in case_records
        ]

        if sample_count < request.min_samples:
            evidence_summary.append(
                f"样本量 {sample_count} 低于最小阈值 {request.min_samples}，仅输出观察，不调整排序。"
            )
            confidence = round(0.25 + sample_count * 0.08, 2)
            recommended_use = "observation_only"
        else:
            strategy_counts: dict[str, int] = {}
            override_counts: dict[str, int] = {}
            for case in case_records:
                strategy_counts[case.strategy_type] = (
                    strategy_counts.get(case.strategy_type, 0) + 1
                )
                if case.is_override:
                    override_counts[case.strategy_type] = (
                        override_counts.get(case.strategy_type, 0) + 1
                    )

            raw_scores = {
                strategy: max(0.05, count - override_counts.get(strategy, 0) * 0.5)
                for strategy, count in strategy_counts.items()
            }
            score_sum = sum(raw_scores.values()) or 1.0
            profile.strategy_preferences = {
                strategy: round(score / score_sum, 4)
                for strategy, score in raw_scores.items()
            }
            profile.updated_at = datetime.now(tz=timezone.utc)

            dominant_strategy = max(
                profile.strategy_preferences,
                key=profile.strategy_preferences.get,
            )
            evidence_summary.append(
                f"基于 {sample_count} 个案例，当前最强偏好信号是 {dominant_strategy}。"
            )
            override_total = sum(1 for case in case_records if case.is_override)
            evidence_summary.append(
                f"override 样本 {override_total} 个，偏好只能作为推荐排序辅助，不能覆盖硬约束。"
            )
            confidence = round(min(0.88, 0.45 + sample_count * 0.04), 2)
            recommended_use = "ranking_tiebreaker_only"

        if self._case_library is not None:
            self._case_library._preference_store[request.planner_id] = profile
        from app.services.persistence import persist_preference_profile

        await persist_preference_profile(profile, user_id=request.planner_id)

        trace = _trace(
            agent_name="Preference Learning Agent",
            input_summary=(
                f"planner={request.planner_id}, sample_count={sample_count}, "
                f"min_samples={request.min_samples}"
            ),
            output_summary=(
                f"recommended_use={recommended_use}, confidence={confidence:.2f}"
            ),
            freedom_level="medium",
            llm_allowed=True,
            deterministic_tools=["case_aggregation", "preference_weight_normalizer"],
            guardrail=(
                "只输出偏好画像和排序辅助建议，不自动修改全局求解目标，"
                "上线前必须经过 replay 和 shadow mode 验证。"
            ),
        )
        return PreferenceLearningOutput(
            preference_profile=profile,
            evidence_summary=evidence_summary,
            recommended_use=recommended_use,
            confidence=confidence,
            requires_replay_validation=True,
            sample_count=sample_count,
            trace=[trace],
        )


class PostDecisionLearningAgent:
    """Run the confirmed-decision learning loop as one auditable unit."""

    def __init__(self, case_library=None) -> None:
        self._case_library = case_library

    async def run(self, request: PostDecisionLearningRequest) -> PostDecisionLearningOutput:
        decision_record = request.decision_record or await _load_decision_record_for_learning(
            decision_record_id=request.decision_record_id,
            incident_id=request.incident_id,
        )
        if decision_record is None:
            raise AgentWorkflowNotFoundError(
                "DecisionRecord not found. Confirm a plan before running learning."
            )

        execution_result = (
            request.execution_result
            or await _load_execution_result_for_learning(decision_record.incident_id)
        )
        if execution_result is None:
            raise AgentWorkflowNotFoundError(
                "ExecutionResult not found. Track execution or provide execution_result "
                "before archiving case memory."
            )

        rule_output = await RuleCandidateAgent().compile_rules(
            RuleCandidateRequest(
                rule_text=request.rule_text or _post_decision_rule_text(decision_record),
                context={
                    "strategy_type": decision_record.strategy_type,
                    "confirmed_plan_id": str(decision_record.confirmed_plan_id),
                    "is_override": decision_record.is_override,
                    "is_manual_adjusted": decision_record.is_manual_adjusted,
                },
                source="post_decision_learning",
                incident_id=decision_record.incident_id,
                decision_record_id=decision_record.decision_record_id,
            )
        )
        case_output = await CaseMemoryAgent(self._case_library).archive(
            CaseMemoryRequest(
                decision_record=decision_record,
                execution_result=execution_result,
                case_status="execution_feedback_captured",
                tags=["post_decision_learning"],
            )
        )
        planner_id = request.planner_id or decision_record.confirmed_by
        preference_output = await PreferenceLearningAgent(self._case_library).learn(
            PreferenceLearningRequest(
                planner_id=planner_id,
                min_samples=request.min_samples,
            )
        )

        return PostDecisionLearningOutput(
            rule_candidate_output=rule_output,
            case_memory_output=case_output,
            preference_learning_output=preference_output,
            trace=[
                *rule_output.trace,
                *case_output.trace,
                *preference_output.trace,
            ],
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
        quality_gates = []
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
            gate = PlanQualityGate()
            quality_gates = [gate.evaluate(plan) for plan in candidates]
            blocked_count = sum(1 for report in quality_gates if not report.pass_gate)
            warning_count = sum(1 for report in quality_gates if report.warnings)
            trace.append(
                _trace(
                    agent_name="Quality Gate Agent",
                    input_summary=f"candidate_plans={len(candidates)}",
                    output_summary=(
                        f"passed={len(quality_gates) - blocked_count}, "
                        f"blocked={blocked_count}, warnings={warning_count}"
                    ),
                    freedom_level="none",
                    llm_allowed=False,
                    deterministic_tools=["PlanQualityGate", "ConstraintValidationReport"],
                    guardrail=(
                        "每个候选方案必须生成 pass/warning/block 结果；"
                        "硬约束失败方案不能作为推荐方案进入确认。"
                    ),
                )
            )
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
            quality_gates=quality_gates,
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


async def _load_decision_record_for_learning(
    *,
    decision_record_id: UUID | None,
    incident_id: UUID | None,
) -> DecisionRecord | None:
    if decision_record_id is not None:
        try:
            from app.api.confirmation import _find_decision_record

            record = await _find_decision_record(decision_record_id)
            if record is not None:
                return record
        except Exception:
            pass

        from app.services.persistence import fetch_decision_record_by_id

        return await fetch_decision_record_by_id(decision_record_id)

    if incident_id is None:
        return None

    try:
        from app.api.confirmation import _decision_record_store

        record = _decision_record_store.get(str(incident_id))
        if record is not None:
            return record
    except Exception:
        pass

    from app.services.persistence import fetch_decision_record_by_incident

    return await fetch_decision_record_by_incident(incident_id)


async def _load_execution_result_for_learning(
    incident_id: UUID,
) -> ExecutionResult | None:
    from app.services.persistence import fetch_execution_result_by_incident

    try:
        from app.api.confirmation import _writeback_module

        result = _writeback_module.get_execution_result(incident_id)
        if result is not None:
            return result
        try:
            return await _writeback_module.track_execution(incident_id)
        except ValueError:
            pass
    except Exception:
        pass

    return await fetch_execution_result_by_incident(incident_id)


def _post_decision_rule_text(decision_record: DecisionRecord) -> str:
    if decision_record.override_reason:
        return decision_record.override_reason
    if decision_record.is_manual_adjusted:
        return (
            f"Planner adjusted and confirmed {decision_record.strategy_type}; "
            "review adjustment pattern before future replay."
        )
    return (
        f"Planner confirmed {decision_record.strategy_type} for incident "
        f"{decision_record.incident_id}; keep as case evidence, not a hard rule."
    )


def _find_candidate(candidates: list[CandidatePlan], plan_id: UUID) -> CandidatePlan | None:
    for candidate in candidates:
        if str(candidate.plan_id) == str(plan_id):
            return candidate
    return None


def _candidate_strategy_sequence(strategy_type: str | StrategyType) -> list[StrategyType]:
    primary = StrategyType(_strategy_value(strategy_type))
    sequence = [primary]
    for candidate in (
        StrategyType.WAIT_AND_REPAIR,
        StrategyType.LOCAL_REPAIR,
        StrategyType.GLOBAL_RESCHEDULE,
    ):
        if candidate not in sequence:
            sequence.append(candidate)
    return sequence


def _comparison_strategy(
    base_strategy: StrategyRecommendation,
    strategy_type: StrategyType,
) -> StrategyRecommendation:
    return StrategyRecommendation(
        strategy_type=strategy_type,
        confidence=max(0.35, round(base_strategy.confidence * 0.75, 4)),
        key_factors=[
            f"comparison_candidate_for_top_k:{strategy_type.value}",
            "generated_to_support_planner_tradeoff_review",
        ],
        historical_case_ids=list(base_strategy.historical_case_ids),
        alternative_strategy=None,
        reasoning=(
            f"Generated as a Top-K comparison candidate alongside "
            f"{_strategy_value(base_strategy.strategy_type)}. It is not auto-selected; "
            "quality gate, KPI evaluation and planner confirmation still decide usability."
        ),
    )


def _strategy_value(strategy_type: str | StrategyType) -> str:
    return strategy_type.value if hasattr(strategy_type, "value") else str(strategy_type)


def _compile_constraint_candidate(
    *,
    text: str,
    context: dict,
    source: str,
    incident_id: UUID | None,
    decision_record_id: UUID | None,
) -> ConstraintCandidate:
    resource_id = _extract_resource_id(text)
    time_hint = _extract_time_hint(text)
    constraint_type = _detect_constraint_type(text, resource_id, time_hint)
    scope = {
        "machine_ids": [resource_id] if resource_id else [],
        "operation_ids": context.get("operation_ids", []),
        "product_family": context.get("product_family"),
        "time_window": f"after {time_hint}" if time_hint else context.get("time_window"),
    }
    confidence = _constraint_confidence(
        constraint_type=constraint_type,
        resource_id=resource_id,
        time_hint=time_hint,
        context=context,
    )
    compiled_rule = _compiled_constraint_rule(
        constraint_type=constraint_type,
        text=text,
        resource_id=resource_id,
        time_hint=time_hint,
        context=context,
    )
    return ConstraintCandidate(
        candidate_id=f"constraint_candidate_{uuid4().hex[:8]}",
        constraint_type=constraint_type,
        scope=scope,
        source_text=text,
        compiled_rule=compiled_rule,
        confidence=confidence,
        status="pending_human_review",
        risk_note=_constraint_risk_note(
            constraint_type=constraint_type,
            resource_id=resource_id,
            time_hint=time_hint,
        ),
        source_refs=_constraint_source_refs(
            source=source,
            incident_id=incident_id,
            decision_record_id=decision_record_id,
        ),
    )


def _constraint_candidate_from_llm(
    *,
    data: dict,
    text: str,
    source: str,
    incident_id: UUID | None,
    decision_record_id: UUID | None,
) -> ConstraintCandidate | None:
    constraint_type = str(data.get("constraint_type") or "")
    if constraint_type not in {
        "material",
        "quality",
        "changeover",
        "calendar",
        "skill",
        "forbidden_assignment",
        "resource_preference",
        "review_note",
    }:
        return None

    try:
        confidence = round(float(data.get("confidence", 0.0)), 2)
    except (TypeError, ValueError):
        return None
    confidence = max(0.0, min(confidence, 0.9))

    scope = data.get("scope") if isinstance(data.get("scope"), dict) else {}
    machine_ids = scope.get("machine_ids")
    if isinstance(machine_ids, str):
        scope["machine_ids"] = [machine_ids]
    elif not isinstance(machine_ids, list):
        resource_id = _extract_resource_id(text)
        scope["machine_ids"] = [resource_id] if resource_id else []

    compiled_rule = data.get("compiled_rule")
    if not isinstance(compiled_rule, str) or not compiled_rule.strip():
        return None

    risk_note = data.get("risk_note")
    if not isinstance(risk_note, str) or not risk_note.strip():
        risk_note = "LLM 候选规则必须人工审核，并通过 replay 或 shadow mode 后才能发布。"

    return ConstraintCandidate(
        candidate_id=f"constraint_candidate_{uuid4().hex[:8]}",
        constraint_type=constraint_type,
        scope=scope,
        source_text=text,
        compiled_rule=compiled_rule.strip(),
        confidence=confidence,
        status="pending_human_review",
        risk_note=risk_note.strip(),
        source_refs=_constraint_source_refs(
            source=source,
            incident_id=incident_id,
            decision_record_id=decision_record_id,
        ),
    )


def _detect_constraint_type(
    text: str,
    resource_id: str | None,
    time_hint: str | None,
) -> str:
    lowered = text.lower()
    if any(token in text for token in ("物料", "材料", "齐套", "缺料")):
        return "material"
    if any(token in text for token in ("返工", "质检", "质量", "报废", "QA", "QC")):
        return "quality"
    if any(token in text for token in ("换线", "切换", "换型", "changeover")):
        return "changeover"
    if any(token in lowered for token in ("operator", "shift", "unavailable")) or any(
        token in text for token in ("人员", "班次", "操作员", "不在", "不可用")
    ):
        return "calendar" if time_hint else "skill"
    if any(token in text for token in ("禁止", "不能", "不要", "不可")) or any(
        token in lowered for token in ("avoid", "forbid", "do not")
    ):
        return "forbidden_assignment" if resource_id else "resource_preference"
    return "resource_preference" if resource_id else "review_note"


def _constraint_confidence(
    *,
    constraint_type: str,
    resource_id: str | None,
    time_hint: str | None,
    context: dict,
) -> float:
    score = 0.56
    if constraint_type != "review_note":
        score += 0.12
    if resource_id:
        score += 0.14
    if time_hint:
        score += 0.08
    if context:
        score += 0.04
    return round(min(score, 0.9), 2)


def _compiled_constraint_rule(
    *,
    constraint_type: str,
    text: str,
    resource_id: str | None,
    time_hint: str | None,
    context: dict,
) -> str:
    if constraint_type == "calendar" and resource_id and time_hint:
        return f"avoid assigning urgent jobs to {resource_id} after {time_hint}"
    if constraint_type == "material":
        return "check material readiness before releasing or recommending this plan"
    if constraint_type == "quality":
        return "require quality/rework confirmation before treating operation as available"
    if constraint_type == "changeover":
        return "include changeover risk before recommending resource reassignment"
    if constraint_type == "forbidden_assignment" and resource_id:
        return f"review forbidden assignment candidate for {resource_id}"
    if resource_id:
        return f"review future assignments involving {resource_id}"
    return context.get("future_rule_candidate") or f"review rule candidate: {text}"


def _constraint_risk_note(
    *,
    constraint_type: str,
    resource_id: str | None,
    time_hint: str | None,
) -> str:
    if constraint_type == "review_note":
        return "规则类型和适用范围不足，必须人工补充后才能 replay。"
    if not resource_id and constraint_type in {"calendar", "skill", "forbidden_assignment"}:
        return "缺少明确资源范围，不能升级为硬约束。"
    if constraint_type == "calendar" and not time_hint:
        return "缺少明确时间窗口，不能发布为班次/日历规则。"
    return "候选规则需要人工审核，并通过历史 replay 或 shadow mode 后才能发布。"


def _constraint_source_refs(
    *,
    source: str,
    incident_id: UUID | None,
    decision_record_id: UUID | None,
) -> list[str]:
    refs = [f"{source}:rule_text"]
    if incident_id is not None:
        refs.append(f"incident:{incident_id}")
    if decision_record_id is not None:
        refs.append(f"decision_record:{decision_record_id}")
    return refs


def _build_case_title(decision_record) -> str:
    strategy = decision_record.strategy_type.replace("_", " ")
    suffix = "override" if decision_record.is_override else "confirmed"
    return f"{strategy} case for incident {decision_record.incident_id} ({suffix})"


def _build_incident_signature(decision_record) -> str:
    override_flag = "override" if decision_record.is_override else "accepted"
    return f"{decision_record.strategy_type}:{override_flag}:{decision_record.incident_id}"


def _case_reusability(case) -> str:
    if case.is_override:
        return "use_for_failure_analysis_and_rule_candidate_review"
    if case.execution_result is None:
        return "pending_execution_feedback"
    if case.execution_result.deviation_percentage <= 10:
        return "similar_incident_strategy_reference"
    return "use_with_caution_high_execution_deviation"


def _feedback_from_llm(data: dict, text: str) -> dict | None:
    reason = data.get("override_reason")
    if reason not in {
        "operator_preference",
        "material_constraint",
        "resource_constraint",
        "quality_constraint",
        "schedule_stability",
        "manual_business_judgment",
    }:
        return None
    try:
        confidence = round(float(data.get("confidence", 0.0)), 2)
    except (TypeError, ValueError):
        return None
    confidence = max(0.0, min(confidence, 0.92))

    detail = data.get("reason_detail")
    if not isinstance(detail, str) or not detail.strip():
        detail = text
    future_rule = data.get("future_rule_candidate")
    if not isinstance(future_rule, str) or not future_rule.strip():
        future_rule = None

    return {
        "reason": reason,
        "detail": detail.strip(),
        "future_rule": future_rule.strip() if future_rule else None,
        "confidence": confidence,
    }


def _deterministic_feedback_structure(text: str) -> dict:
    resource_id = _extract_resource_id(text)
    time_hint = _extract_time_hint(text)
    lowered = text.lower()

    if any(token in lowered for token in ("operator", "unavailable", "shift")) or any(
        token in text for token in ("操作员", "人员", "班次", "不在", "不可用")
    ):
        reason = "operator_preference"
        confidence = 0.86 if resource_id and time_hint else 0.76
        if resource_id and time_hint:
            future_rule = f"avoid assigning urgent jobs to {resource_id} after {time_hint}"
        elif resource_id:
            future_rule = f"review assignment constraints for {resource_id}"
        else:
            future_rule = "review operator availability before urgent assignment"
    elif any(token in text for token in ("物料", "材料", "齐套", "缺料")):
        reason = "material_constraint"
        confidence = 0.8
        future_rule = "check material readiness before releasing repaired plan"
    elif any(token in text for token in ("质检", "质量", "返工", "QC", "QA")):
        reason = "quality_constraint"
        confidence = 0.78
        future_rule = "require quality confirmation before releasing repaired plan"
    elif resource_id is not None:
        reason = "resource_constraint"
        confidence = 0.78
        future_rule = f"review future assignments involving {resource_id}"
    else:
        reason = "manual_business_judgment"
        confidence = 0.62
        future_rule = None

    return {
        "reason": reason,
        "detail": text,
        "future_rule": future_rule,
        "confidence": confidence,
    }


def _parse_report_source(value: str) -> ReportSource:
    try:
        return ReportSource(value)
    except ValueError:
        return ReportSource.MANUAL


def _parsed_incident_from_llm(data: dict) -> _ParsedIncident | None:
    incident_type = str(data.get("incident_type") or "unknown")
    if incident_type not in {
        "machine_down",
        "material_shortage",
        "urgent_order_insert",
        "capacity_degradation",
        "unknown",
    }:
        return None

    resource_id = data.get("resource_id")
    if isinstance(resource_id, str) and resource_id.strip():
        resource_id = resource_id.strip().upper().replace(" ", "").replace("_", "-")
    else:
        resource_id = None

    duration = data.get("estimated_duration_minutes")
    try:
        estimated_duration = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        estimated_duration = None

    try:
        confidence = round(float(data.get("confidence", 0.0)), 2)
    except (TypeError, ValueError):
        return None
    confidence = max(0.0, min(confidence, 0.98))

    supported_by_solver = incident_type == "machine_down"
    unsupported_reason = data.get("unsupported_reason")
    if not supported_by_solver and not unsupported_reason:
        unsupported_reason = (
            "Current PoC solver supports machine_down via equipment_failure; "
            f"{incident_type} needs customer adapter/rule extension before auto-solving."
        )
    if supported_by_solver and resource_id is None:
        unsupported_reason = "Missing machine/resource id."

    requires_confirmation = bool(data.get("requires_human_confirmation", False))
    requires_confirmation = (
        requires_confirmation
        or confidence < 0.75
        or not supported_by_solver
        or resource_id is None
        or incident_type == "unknown"
    )

    risk_hint = data.get("risk_hint")
    risk_hint = str(risk_hint) if risk_hint else None

    return _ParsedIncident(
        incident_type=incident_type,
        resource_id=resource_id,
        estimated_duration_minutes=estimated_duration,
        risk_hint=risk_hint,
        confidence=confidence,
        supported_by_solver=supported_by_solver,
        requires_human_confirmation=requires_confirmation,
        unsupported_reason=str(unsupported_reason) if unsupported_reason else None,
    )


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
