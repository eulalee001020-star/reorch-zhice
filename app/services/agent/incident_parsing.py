"""Deterministic parsing of free-text incident reports.

These functions turn a planner's sentence into incident fields without a
model call. They are the fallback when no model is configured and the
check applied to model output when one is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.enums import ReportSource

_MACHINE_RESOURCE_RE = re.compile(
    r"\b((?:CNC|MC|M|EQ|LINE)[-_ ]?\d{1,4})\b",
    flags=re.IGNORECASE,
)


_GENERIC_RESOURCE_RE = re.compile(
    r"(?:设备|机台|机器|产线)\s*([A-Za-z]{0,4}[-_ ]?\d{1,4})",
    flags=re.IGNORECASE,
)


_CLOCK_RE = re.compile(r"(?:after\s*)?([01]?\d|2[0-3]):([0-5]\d)", re.IGNORECASE)


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
    if (
        any(token in text for token in ("物料", "材料", "缺料", "齐套", "没到", "未到"))
        or "material" in lowered
    ):
        return "material_shortage"
    if any(token in text for token in ("客户加急", "急单", "加急", "插单")) or "urgent" in lowered:
        return "urgent_order_insert"
    if (
        any(token in text for token in ("产能下降", "产能降低", "降速", "效率下降", "设备产能"))
        or "capacity" in lowered
    ):
        return "capacity_degradation"
    return "unknown"


def _is_machine_down(text: str, lowered: str, resource_id: str | None) -> bool:
    machine_failure_terms = (
        "坏",
        "停了",
        "停机",
        "故障",
        "宕机",
        "down",
        "failure",
        "stopped",
    )
    if any(term in lowered for term in ("down", "failure", "stopped")):
        return True
    if any(term in text for term in machine_failure_terms):
        return resource_id is not None or any(
            token in text for token in ("设备", "机台", "机器", "产线", "CNC")
        )
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
        (
            re.compile(r"(\d+(?:\.\d+)?)\s*(?:个)?\s*(小时|钟头|h|hour|hours)", re.IGNORECASE),
            60,
        ),
        (
            re.compile(r"(\d+(?:\.\d+)?)\s*(?:分钟|分|min|mins|minute|minutes)", re.IGNORECASE),
            1,
        ),
    ]
    for pattern, multiplier in patterns:
        match = pattern.search(text)
        if match:
            return round(float(match.group(1)) * multiplier)

    cn_hour = re.search(r"([一二两俩三四五六七八九十半]+)\s*(?:个)?\s*(小时|钟头)", text)
    if cn_hour:
        return round(_parse_chinese_number(cn_hour.group(1)) * 60)

    cn_minute = re.search(r"([一二两俩三四五六七八九十]+)\s*(?:分钟|分)", text)
    if cn_minute:
        return round(_parse_chinese_number(cn_minute.group(1)))

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
