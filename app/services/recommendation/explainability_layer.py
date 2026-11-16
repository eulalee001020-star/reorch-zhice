"""Explainability Layer — generates structured, human-readable explanations
for recommended plans and solver chain decisions.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 28.1, 28.2, 28.3,
           28.7, 28.8, 28.9
"""

from __future__ import annotations

import logging

from app.models.case import CaseRecord
from app.models.evaluation import ComparisonMatrix
from app.models.explanation import RecommendationExplanation, SolverChainExplanation
from app.models.solver import CandidatePlan

logger = logging.getLogger(__name__)

# Maximum number of core reasons (Req 6.2)
_MAX_CORE_REASONS = 3

# Maximum summary length in characters (Req 6.5)
_MAX_SUMMARY_LENGTH = 200

# Strategy type → algorithm category label
_ALGORITHM_CATEGORIES: dict[str, str] = {
    "wait_and_repair": "时间偏移修复 + 约束校验",
    "local_repair": "LNS 局部搜索 + CP-SAT",
    "global_reschedule": "CP-SAT 全局重排",
}

# Strategy type → applicable scenario description (Req 28.3)
_APPLICABLE_SCENARIOS: dict[str, str] = {
    "wait_and_repair": "设备预计短时间内恢复，仅需调整受影响工序的开始时间，保持原排程整体不变",
    "local_repair": "受影响工序比例有限，通过局部邻域搜索修复受影响区域及直接下游",
    "global_reschedule": "影响范围较大或存在交期违约风险，需对整个车间排程进行全局优化",
}

# Strategy type → chain reason template (Req 28.3, 28.4, 28.5, 28.6)
_CHAIN_REASON_TEMPLATES: dict[str, str] = {
    "wait_and_repair": "影响范围可控且设备即将恢复，采用最小扰动策略仅调整时间偏移",
    "local_repair": "受影响工序集中在局部区域，局部搜索可在有限预算内高效修复",
    "global_reschedule": "影响范围广泛或存在关键工单交期违约风险，需全局重新优化排程",
}


class ExplainabilityLayer:
    """Generate structured explanations for recommendations and solver chains.

    Responsibilities (Req 6, 28):
    - ``explain_recommendation``: produce ``RecommendationExplanation``
      with core reasons (≤3), advantages, risks, alternative comparisons,
      and a ≤200-char business-language summary.
    - ``explain_solver_chain``: produce ``SolverChainExplanation``
      distinguishing "方案生成链路" from "方案排序链路" (Req 28.7).
    - Use business terms (工单号, 设备名, 交期日期) not pure technical
      jargon (Req 6.3).
    - Reference historical case IDs when cases were used (Req 6.4).
    - Output structured data objects for frontend rendering (Req 6.6, 28.9).
    """

    async def explain_recommendation(
        self,
        recommended_plan: CandidatePlan,
        alternatives: list[CandidatePlan],
        comparison_matrix: ComparisonMatrix,
        matched_cases: list[CaseRecord],
    ) -> RecommendationExplanation:
        """Generate a ``RecommendationExplanation`` for the recommended plan.

        Parameters
        ----------
        recommended_plan:
            The plan selected as the AI recommendation.
        alternatives:
            Other candidate plans for comparison.
        comparison_matrix:
            Evaluation scores for all candidates.
        matched_cases:
            Historical cases that influenced the recommendation.
        """
        # --- Core reasons (≤3, Req 6.2) ---
        core_reasons = _build_core_reasons(
            recommended_plan, alternatives, comparison_matrix, matched_cases
        )

        # --- Key advantages (Req 6.2) ---
        key_advantages = _build_key_advantages(
            recommended_plan, comparison_matrix
        )

        # --- Main risks (Req 6.2) ---
        main_risks = _build_main_risks(recommended_plan)

        # --- Comparison with alternatives (Req 6.1) ---
        comparisons = _build_alternative_comparisons(
            recommended_plan, alternatives, comparison_matrix
        )

        # --- Summary ≤200 chars (Req 6.5) ---
        summary = _build_summary(recommended_plan, comparison_matrix)

        # --- Referenced case IDs (Req 6.4) ---
        referenced_case_ids = [
            str(case.case_id) for case in matched_cases
        ]

        return RecommendationExplanation(
            core_reasons=core_reasons,
            key_advantages=key_advantages,
            main_risks=main_risks,
            comparison_with_alternatives=comparisons,
            summary=summary,
            referenced_case_ids=referenced_case_ids,
        )

    async def explain_solver_chain(
        self,
        plan: CandidatePlan,
    ) -> SolverChainExplanation:
        """Generate a ``SolverChainExplanation`` for a candidate plan.

        Distinguishes "方案生成链路" (how the plan was produced by the
        solver) from "方案排序链路" (how plans were ranked/recommended).
        This method covers the generation chain only (Req 28.7).

        Parameters
        ----------
        plan:
            The candidate plan whose solver chain to explain.
        """
        chain = plan.solver_chain
        strategy = chain.strategy_type

        algorithm_category = _ALGORITHM_CATEGORIES.get(
            strategy, f"{chain.solver_name} ({strategy})"
        )
        applicable_scenario = _APPLICABLE_SCENARIOS.get(
            strategy, f"策略类型: {strategy}"
        )
        chain_reason = _CHAIN_REASON_TEMPLATES.get(
            strategy, f"基于 {strategy} 策略选择的求解链路"
        )

        # Optimization objectives from solver chain context
        optimization_objectives = _infer_objectives(strategy)

        # Computation time from solver metadata
        computation_time = (
            plan.solver_metadata.solve_time_seconds
            if plan.solver_metadata
            else 0.0
        )

        # Stages from solver chain (Req 28.8)
        stages = list(chain.stages) if chain.stages else []

        # Frozen constraints for local repair (Req 28.5)
        frozen_constraints = _extract_frozen_constraints(plan)

        return SolverChainExplanation(
            algorithm_category=algorithm_category,
            applicable_scenario=applicable_scenario,
            chain_reason=chain_reason,
            optimization_objectives=optimization_objectives,
            computation_time_seconds=computation_time,
            stages=stages,
            frozen_constraints=frozen_constraints,
        )


# ── Internal helpers ────────────────────────────────────────────────


def _build_core_reasons(
    recommended: CandidatePlan,
    alternatives: list[CandidatePlan],
    matrix: ComparisonMatrix,
    matched_cases: list[CaseRecord],
) -> list[str]:
    """Build ≤3 core reasons using business terms (Req 6.2, 6.3)."""
    reasons: list[str] = []

    # Reason 1: feasibility
    if recommended.feasibility_status == "feasible":
        reasons.append("方案满足全部硬约束，可直接执行")
    elif recommended.feasibility_status == "timeout_partial":
        reasons.append("方案为求解超时下的最优可行解")

    # Reason 2: strategy-based reasoning
    strategy = recommended.strategy_type
    strategy_labels = {
        "wait_and_repair": "采用等待修复策略，对原排程扰动最小",
        "local_repair": "采用局部修复策略，仅调整受影响区域",
        "global_reschedule": "采用全局重排策略，全面优化交期与资源利用",
    }
    label = strategy_labels.get(strategy)
    if label:
        reasons.append(label)

    # Reason 3: historical case reference (Req 6.4)
    if matched_cases:
        case = matched_cases[0]
        case_result = "成功" if case.execution_result else "已归档"
        reasons.append(
            f"参考历史案例 {case.case_id}（执行结果: {case_result}）"
        )

    # Ensure ≤3
    return reasons[:_MAX_CORE_REASONS]


def _build_key_advantages(
    recommended: CandidatePlan,
    matrix: ComparisonMatrix,
) -> list[str]:
    """Build key advantages using KPI data (Req 6.2)."""
    advantages: list[str] = []

    # Find the recommended plan's row in the matrix
    rec_row = _find_row(matrix, str(recommended.plan_id))
    if rec_row:
        kpi = rec_row.kpi_vector
        if kpi.delayed_order_count == 0:
            advantages.append("无工单延迟")
        elif kpi.delayed_order_count <= 2:
            advantages.append(f"仅 {kpi.delayed_order_count} 个工单延迟")

        if kpi.spi <= 0.1:
            advantages.append("排程扰动极低（SPI ≤ 10%）")
        elif kpi.spi <= 0.2:
            advantages.append(f"排程扰动可控（SPI = {kpi.spi:.0%}）")

        if kpi.critical_order_otd_impact >= 0.95:
            advantages.append("关键工单准时交付率 ≥ 95%")

    if not advantages:
        advantages.append("综合评分最优")

    return advantages


def _build_main_risks(plan: CandidatePlan) -> list[str]:
    """Build main risks and trade-offs (Req 6.2)."""
    risks: list[str] = []

    if plan.feasibility_status == "timeout_partial":
        risks.append("求解超时，方案可能非全局最优")

    if plan.solver_metadata and plan.solver_metadata.degradation_occurred:
        reason = plan.solver_metadata.degradation_reason or "未知原因"
        risks.append(f"求解过程发生降级（{reason}）")

    if plan.constraint_report and plan.constraint_report.violations:
        count = len(plan.constraint_report.violations)
        risks.append(f"存在 {count} 条约束违反需关注")

    strategy = plan.strategy_type
    if strategy == "global_reschedule":
        risks.append("全局重排对原排程扰动较大，需关注换型次数变化")
    elif strategy == "wait_and_repair":
        risks.append("等待修复期间产能闲置，需确认设备恢复时间预估准确性")

    if not risks:
        risks.append("当前方案无显著风险")

    return risks


def _build_alternative_comparisons(
    recommended: CandidatePlan,
    alternatives: list[CandidatePlan],
    matrix: ComparisonMatrix,
) -> list[dict]:
    """Build comparison dicts for each alternative (Req 6.1)."""
    comparisons: list[dict] = []
    rec_row = _find_row(matrix, str(recommended.plan_id))

    for alt in alternatives:
        alt_row = _find_row(matrix, str(alt.plan_id))
        comparison: dict = {
            "plan_id": str(alt.plan_id),
            "strategy_type": alt.strategy_type,
        }

        if rec_row and alt_row:
            rec_score = rec_row.kpi_vector.normalized_score
            alt_score = alt_row.kpi_vector.normalized_score
            score_diff = rec_score - alt_score
            comparison["score_difference"] = round(score_diff, 4)

            # Build human-readable diff description
            diffs: list[str] = []
            rec_kpi = rec_row.kpi_vector
            alt_kpi = alt_row.kpi_vector

            delay_diff = alt_kpi.delayed_order_count - rec_kpi.delayed_order_count
            if delay_diff > 0:
                diffs.append(f"延迟工单多 {delay_diff} 个")
            elif delay_diff < 0:
                diffs.append(f"延迟工单少 {abs(delay_diff)} 个")

            spi_diff = alt_kpi.spi - rec_kpi.spi
            if abs(spi_diff) > 0.01:
                direction = "高" if spi_diff > 0 else "低"
                diffs.append(f"排程扰动{direction} {abs(spi_diff):.0%}")

            comparison["key_differences"] = diffs if diffs else ["评分接近，差异不显著"]
        else:
            comparison["key_differences"] = ["评分数据不可用"]

        comparisons.append(comparison)

    return comparisons


def _build_summary(
    plan: CandidatePlan,
    matrix: ComparisonMatrix,
) -> str:
    """Build a ≤200-char business-language summary (Req 6.5)."""
    strategy_labels = {
        "wait_and_repair": "等待修复",
        "local_repair": "局部修复",
        "global_reschedule": "全局重排",
    }
    strategy_label = strategy_labels.get(plan.strategy_type, plan.strategy_type)

    rec_row = _find_row(matrix, str(plan.plan_id))
    if rec_row:
        kpi = rec_row.kpi_vector
        summary = (
            f"推荐采用{strategy_label}策略，"
            f"延迟工单 {kpi.delayed_order_count} 个，"
            f"排程扰动 {kpi.spi:.0%}，"
            f"关键工单 OTD {kpi.critical_order_otd_impact:.0%}。"
        )
    else:
        summary = f"推荐采用{strategy_label}策略，方案满足全部硬约束。"

    # Truncate to ≤200 chars
    if len(summary) > _MAX_SUMMARY_LENGTH:
        summary = summary[: _MAX_SUMMARY_LENGTH - 1] + "…"

    return summary


def _find_row(matrix: ComparisonMatrix, plan_id: str):
    """Find a ComparisonMatrixRow by plan_id."""
    for row in matrix.rows:
        if row.plan_id == plan_id:
            return row
    return None


def _infer_objectives(strategy: str) -> list[str]:
    """Infer optimization objectives from strategy type."""
    base = ["最小化工单延迟", "最小化排程扰动"]
    if strategy == "wait_and_repair":
        return ["最小化时间偏移", "保持原排程不变"]
    elif strategy == "local_repair":
        return base + ["保护未受影响区域不变性"]
    elif strategy == "global_reschedule":
        return base + ["最大化资源利用率", "最小化换型次数"]
    return base


def _extract_frozen_constraints(plan: CandidatePlan) -> list[str] | None:
    """Extract frozen constraint descriptions for local repair plans."""
    strategy = plan.solver_chain.strategy_type
    if strategy == "wait_and_repair":
        return ["所有未受影响工序保持冻结"]
    elif strategy == "local_repair":
        return ["未受影响工序保持冻结，仅修复受影响区域及直接下游"]
    # Global reschedule has no frozen constraints
    return None
