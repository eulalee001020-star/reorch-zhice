"""Compile planner statements into reviewable constraint candidates.

A candidate is a draft: it only reaches the solver after review, replay
and publication.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.models.agent import (
    ConstraintCandidate,
)
from app.services.agent.incident_parsing import _extract_resource_id, _extract_time_hint


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

    raw_scope = data.get("scope")
    scope: dict = dict(raw_scope) if isinstance(raw_scope, dict) else {}
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
    if not resource_id and constraint_type in {
        "calendar",
        "skill",
        "forbidden_assignment",
    }:
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
