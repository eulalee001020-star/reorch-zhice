"""Operational quality gate for candidate plans."""

from __future__ import annotations

from app.models.planning import PlanQualityGateReport
from app.models.solver import CandidatePlan


class PlanQualityGate:
    """Decides whether a candidate plan is safe to present for confirmation."""

    def evaluate(self, plan: CandidatePlan) -> PlanQualityGateReport:
        warnings: list[str] = []
        hard_blockers = []

        if plan.feasibility_status == "infeasible":
            hard_blockers.extend(plan.constraint_report.violations)
        if plan.constraint_report and not plan.constraint_report.is_feasible:
            hard_blockers.extend(plan.constraint_report.violations)

        if plan.feasibility_status == "timeout_partial":
            warnings.append("Solver timed out; plan is partial and requires planner review.")
        if plan.solver_metadata.degradation_occurred:
            warnings.append(
                f"Solver degraded: {plan.solver_metadata.degradation_reason or 'no reason recorded'}."
            )
        if len(plan.constraint_report.checked_constraints) < 3:
            warnings.append("Constraint coverage is limited; do not auto-preselect.")

        pass_gate = not hard_blockers
        confidence = self._confidence_level(plan, warnings, pass_gate)
        policy = self._recommendation_policy(pass_gate, confidence)

        return PlanQualityGateReport(
            plan_id=plan.plan_id,
            pass_gate=pass_gate,
            confidence_level=confidence,
            hard_blockers=hard_blockers,
            warnings=warnings,
            recommendation_policy=policy,
        )

    @staticmethod
    def _confidence_level(
        plan: CandidatePlan,
        warnings: list[str],
        pass_gate: bool,
    ) -> str:
        if not pass_gate:
            return "blocked"
        if plan.feasibility_status == "timeout_partial" or len(warnings) >= 2:
            return "low"
        if warnings:
            return "medium"
        return "high"

    @staticmethod
    def _recommendation_policy(pass_gate: bool, confidence: str) -> str:
        if not pass_gate:
            return "do_not_recommend"
        if confidence == "high":
            return "can_recommend_with_planner_confirmation"
        if confidence == "medium":
            return "recommend_with_risk_warning"
        return "show_as_reference_only"
