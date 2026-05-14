"""PoC value tracking and ROI estimate service."""

from __future__ import annotations

from app.models.planning import ValueTrackingInput, ValueTrackingReport


class ValueTrackingService:
    """Converts before/after operational metrics into a value report."""

    def estimate(self, value_input: ValueTrackingInput) -> ValueTrackingReport:
        saved_decision_minutes = max(
            0.0,
            value_input.baseline_decision_minutes - value_input.actual_decision_minutes,
        )
        reduced_tardiness_minutes = max(
            0.0,
            value_input.baseline_tardiness_minutes - value_input.actual_tardiness_minutes,
        )
        reduced_changeovers = max(
            0,
            value_input.baseline_changeovers - value_input.actual_changeovers,
        )
        reduced_overtime_hours = max(
            0.0,
            value_input.baseline_overtime_hours - value_input.actual_overtime_hours,
        )

        planner_time_savings = (
            saved_decision_minutes / 60.0
            * value_input.planner_hourly_cost
            * max(1, value_input.incident_count)
        )
        tardiness_savings = (
            reduced_tardiness_minutes
            * value_input.tardiness_cost_per_minute
            * max(1, value_input.incident_count)
        )
        changeover_savings = (
            reduced_changeovers
            * value_input.changeover_cost
            * max(1, value_input.incident_count)
        )
        overtime_savings = (
            reduced_overtime_hours
            * value_input.overtime_hourly_cost
            * max(1, value_input.incident_count)
        )

        estimated = (
            planner_time_savings
            + tardiness_savings
            + changeover_savings
            + overtime_savings
        )

        commentary = (
            "Value is currently driven by decision-time reduction only; "
            "add customer-specific delay, changeover, and overtime costs for renewal-grade ROI."
        )
        if value_input.tardiness_cost_per_minute or value_input.changeover_cost or value_input.overtime_hourly_cost:
            commentary = (
                "Estimated savings include customer-specific delay, changeover, "
                "overtime, and planner-time assumptions. Validate with finance before renewal pricing."
            )

        return ValueTrackingReport(
            saved_decision_minutes=round(saved_decision_minutes, 2),
            reduced_tardiness_minutes=round(reduced_tardiness_minutes, 2),
            reduced_changeovers=reduced_changeovers,
            reduced_overtime_hours=round(reduced_overtime_hours, 2),
            estimated_savings=round(estimated, 2),
            savings_breakdown={
                "planner_time_savings": round(planner_time_savings, 2),
                "tardiness_savings": round(tardiness_savings, 2),
                "changeover_savings": round(changeover_savings, 2),
                "overtime_savings": round(overtime_savings, 2),
            },
            payback_commentary=commentary,
        )
