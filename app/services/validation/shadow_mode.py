"""Read-only shadow-mode case capture."""

from __future__ import annotations

from app.models.shadow_mode import (
    ShadowCaseCaptureRequest,
    ShadowCaseCaptureResponse,
)


class ShadowModeService:
    """Capture planner feedback without producing writeback commands."""

    def capture(self, request: ShadowCaseCaptureRequest) -> ShadowCaseCaptureResponse:
        missing_fields = _missing_required_fields(request)
        decision = request.planner_decision
        selected_plan_ids = {str(plan.plan_id) for plan in request.candidate_plans}
        if decision.selected_plan_id and decision.selected_plan_id not in selected_plan_ids:
            missing_fields.append("planner_decision.selected_plan_id_not_in_candidates")

        feedback_complete = not missing_fields and bool(decision.decision_status)
        needs_rule_candidate = decision.decision_status in {"rejected", "tweaked"} and bool(
            decision.override_reason or decision.tweak_summary
        )
        audit_bundle = {
            "incident_payload_present": bool(request.incident_payload),
            "schedule_snapshot_id": request.schedule_snapshot_id,
            "candidate_plan_count": len(request.candidate_plans),
            "planner_decision_status": decision.decision_status,
            "source_refs": request.source_refs,
            "writeback_command_created": False,
            "safety_policy": "read_only_shadow_advisory_only",
        }
        return ShadowCaseCaptureResponse(
            advisory_only=True,
            writeback_blocked=True,
            feedback_capture_complete=feedback_complete,
            rule_candidate_recommended=needs_rule_candidate,
            decision_status=decision.decision_status,
            selected_plan_id=decision.selected_plan_id,
            missing_fields=missing_fields,
            audit_bundle=audit_bundle,
        )


def _missing_required_fields(request: ShadowCaseCaptureRequest) -> list[str]:
    missing: list[str] = []
    if not request.incident_payload:
        missing.append("incident_payload")
    if not request.schedule_snapshot_id:
        missing.append("schedule_snapshot_id")
    if not request.candidate_plans:
        missing.append("candidate_plans")
    if not request.source_refs:
        missing.append("source_refs")
    if request.planner_decision.decision_status in {"rejected", "tweaked"} and not (
        request.planner_decision.override_reason
        or request.planner_decision.tweak_summary
    ):
        missing.append("planner_decision.override_reason_or_tweak_summary")
    return missing
