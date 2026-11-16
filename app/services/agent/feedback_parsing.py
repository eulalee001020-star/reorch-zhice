"""Structure a planner's override reason into feedback fields."""

from __future__ import annotations

from app.services.agent.incident_parsing import _extract_resource_id, _extract_time_hint


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
