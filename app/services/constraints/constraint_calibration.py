"""Compile calibrated shop-floor constraints into scheduler-ready inputs."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from app.models.constraint_calibration import (
    ChangeoverCalibration,
    CompiledConstraintCalibration,
    ConstraintCalibrationConflict,
    ConstraintCalibrationPack,
    FreezeWindowCalibration,
    MachineCapabilityCalibration,
    ResourceCalendarCalibration,
    ReviewedConstraintCandidateInput,
)
from app.models.planning import (
    ChangeoverRuleInput,
    InitialScheduleRequest,
    ResourceCalendarWindowInput,
)


class ConstraintCalibrationService:
    """Compile human-confirmed constraints with conservative guardrails."""

    def compile(self, pack: ConstraintCalibrationPack) -> CompiledConstraintCalibration:
        conflicts: list[ConstraintCalibrationConflict] = []
        resource_capabilities = _compile_capabilities(pack.machine_capabilities, conflicts)
        resource_calendar = _compile_calendar(pack.resource_calendars, conflicts)
        freeze_windows = _compile_freeze_windows(pack.freeze_windows, conflicts)
        changeovers = _compile_changeovers(pack.changeovers, conflicts)

        omitted_candidate_count = 0
        for reviewed in pack.rule_candidates:
            if not _candidate_is_publishable(reviewed):
                omitted_candidate_count += 1
                conflicts.append(
                    _warning(
                        "rule_candidate_not_active",
                        "Rule candidate omitted because it is not both published and replay-passed.",
                        "rule_candidate",
                        reviewed.candidate.candidate_id,
                        reviewed.source_refs or reviewed.candidate.source_refs,
                    )
                )
                continue
            applied = _apply_rule_candidate(
                reviewed,
                resource_capabilities,
                resource_calendar,
                changeovers,
                freeze_windows,
                conflicts,
            )
            if not applied:
                omitted_candidate_count += 1

        _check_known_resources(pack, resource_capabilities, resource_calendar, conflicts)
        _check_calendar_overlaps(resource_calendar, conflicts)
        _check_duplicate_changeovers(changeovers, conflicts)

        blocked = any(conflict.severity == "blocker" for conflict in conflicts)
        raw_data_patch = {
            "resource_capabilities": resource_capabilities,
            "resource_calendar": [
                window.model_dump(mode="json") for window in resource_calendar
            ],
            "changeover_rules": [rule.model_dump(mode="json") for rule in changeovers],
            "freeze_windows": freeze_windows,
            "constraint_calibration_status": "blocked" if blocked else "compiled",
        }
        initial_request = (
            _apply_to_initial_request(
                pack.base_request,
                resource_capabilities,
                resource_calendar,
                changeovers,
                raw_data_patch,
            )
            if pack.base_request and not blocked
            else None
        )
        applied_count = (
            len(resource_capabilities)
            + len(resource_calendar)
            + len(changeovers)
            + len(freeze_windows)
        )
        return CompiledConstraintCalibration(
            workshop_id=pack.workshop_id,
            blocked=blocked,
            applied_constraint_count=applied_count,
            omitted_candidate_count=omitted_candidate_count,
            resource_capabilities=resource_capabilities,
            resource_calendar=resource_calendar,
            changeover_rules=changeovers,
            freeze_windows=freeze_windows,
            raw_data_patch=raw_data_patch,
            conflicts=conflicts,
            initial_schedule_request=initial_request,
        )


def _compile_capabilities(
    entries: list[MachineCapabilityCalibration],
    conflicts: list[ConstraintCalibrationConflict],
) -> dict[str, list[str]]:
    capabilities_by_resource: dict[str, set[str]] = defaultdict(set)
    seen: set[str] = set()
    for entry in entries:
        if not _is_approved(entry.approval_status, entry.approved_by):
            conflicts.append(
                _warning(
                    "capability_not_approved",
                    "Machine capability omitted because it is not human-approved.",
                    "resource",
                    entry.resource_id,
                    entry.source_refs,
                )
            )
            continue
        normalized = _dedupe(entry.capabilities)
        if not normalized:
            conflicts.append(
                _blocker(
                    "empty_capability_set",
                    "Approved machine capability entry must include at least one capability.",
                    "resource",
                    entry.resource_id,
                    entry.source_refs,
                )
            )
            continue
        if entry.resource_id in seen:
            conflicts.append(
                _warning(
                    "duplicate_capability_entry",
                    "Duplicate capability entries for the same resource were merged.",
                    "resource",
                    entry.resource_id,
                    entry.source_refs,
                )
            )
        seen.add(entry.resource_id)
        capabilities_by_resource[entry.resource_id].update(normalized)
    return {
        resource_id: sorted(capabilities)
        for resource_id, capabilities in capabilities_by_resource.items()
    }


def _compile_calendar(
    entries: list[ResourceCalendarCalibration],
    conflicts: list[ConstraintCalibrationConflict],
) -> list[ResourceCalendarWindowInput]:
    windows: list[ResourceCalendarWindowInput] = []
    for entry in entries:
        if not _is_approved(entry.approval_status, entry.approved_by):
            conflicts.append(
                _warning(
                    "calendar_not_approved",
                    "Resource calendar window omitted because it is not human-approved.",
                    "resource",
                    entry.resource_id,
                    entry.source_refs,
                )
            )
            continue
        if entry.window_end <= entry.window_start:
            conflicts.append(
                _blocker(
                    "invalid_calendar_window",
                    "Calendar window_end must be later than window_start.",
                    "resource",
                    entry.resource_id,
                    entry.source_refs,
                )
            )
            continue
        windows.append(
            ResourceCalendarWindowInput(
                resource_id=entry.resource_id,
                window_start=entry.window_start,
                window_end=entry.window_end,
                availability_type=entry.availability_type,
                reason=entry.reason,
            )
        )
    return windows


def _compile_freeze_windows(
    entries: list[FreezeWindowCalibration],
    conflicts: list[ConstraintCalibrationConflict],
) -> list[dict]:
    windows: list[dict] = []
    for entry in entries:
        entity_id = entry.operation_id or entry.resource_id
        if not _is_approved(entry.approval_status, entry.approved_by):
            conflicts.append(
                _warning(
                    "freeze_window_not_approved",
                    "Freeze window omitted because it is not human-approved.",
                    "freeze_window",
                    entity_id,
                    entry.source_refs,
                )
            )
            continue
        if not entry.resource_id and not entry.operation_id:
            conflicts.append(
                _blocker(
                    "freeze_window_without_scope",
                    "Freeze window must target a resource_id or operation_id.",
                    "freeze_window",
                    None,
                    entry.source_refs,
                )
            )
            continue
        if entry.window_end <= entry.window_start:
            conflicts.append(
                _blocker(
                    "invalid_freeze_window",
                    "Freeze window_end must be later than window_start.",
                    "freeze_window",
                    entity_id,
                    entry.source_refs,
                )
            )
            continue
        windows.append(
            {
                "resource_id": entry.resource_id,
                "operation_id": entry.operation_id,
                "window_start": entry.window_start.isoformat(),
                "window_end": entry.window_end.isoformat(),
                "reason": entry.reason,
            }
        )
    return windows


def _compile_changeovers(
    entries: list[ChangeoverCalibration],
    conflicts: list[ConstraintCalibrationConflict],
) -> list[ChangeoverRuleInput]:
    rules: list[ChangeoverRuleInput] = []
    for entry in entries:
        entity_id = _changeover_key(
            entry.from_product_family,
            entry.to_product_family,
            entry.resource_id,
        )
        if not _is_approved(entry.approval_status, entry.approved_by):
            conflicts.append(
                _warning(
                    "changeover_not_approved",
                    "Changeover rule omitted because it is not human-approved.",
                    "changeover",
                    entity_id,
                    entry.source_refs,
                )
            )
            continue
        if entry.setup_minutes < 0:
            conflicts.append(
                _blocker(
                    "negative_changeover_minutes",
                    "Changeover setup_minutes cannot be negative.",
                    "changeover",
                    entity_id,
                    entry.source_refs,
                )
            )
            continue
        rules.append(
            ChangeoverRuleInput(
                from_product_family=entry.from_product_family,
                to_product_family=entry.to_product_family,
                setup_minutes=entry.setup_minutes,
                cost=entry.cost,
                resource_id=entry.resource_id,
            )
        )
    return rules


def _apply_rule_candidate(
    reviewed: ReviewedConstraintCandidateInput,
    resource_capabilities: dict[str, list[str]],
    resource_calendar: list[ResourceCalendarWindowInput],
    changeovers: list[ChangeoverRuleInput],
    freeze_windows: list[dict],
    conflicts: list[ConstraintCalibrationConflict],
) -> bool:
    candidate = reviewed.candidate
    scope = candidate.scope
    refs = reviewed.source_refs or candidate.source_refs
    if candidate.constraint_type == "machine_capability":
        resource_id = _str_or_none(scope.get("resource_id"))
        capabilities = _list_of_strings(scope.get("capabilities"))
        if not resource_id or not capabilities:
            conflicts.append(_unsupported_candidate(candidate.candidate_id, refs))
            return False
        merged = set(resource_capabilities.get(resource_id, []))
        merged.update(capabilities)
        resource_capabilities[resource_id] = sorted(merged)
        return True
    if candidate.constraint_type == "resource_calendar":
        try:
            resource_calendar.append(
                ResourceCalendarWindowInput(
                    resource_id=str(scope["resource_id"]),
                    window_start=_parse_datetime(scope["window_start"]),
                    window_end=_parse_datetime(scope["window_end"]),
                    availability_type=str(scope.get("availability_type", "unavailable")),
                    reason=_str_or_none(scope.get("reason")),
                )
            )
        except (KeyError, TypeError, ValueError):
            conflicts.append(_unsupported_candidate(candidate.candidate_id, refs))
            return False
        return True
    if candidate.constraint_type == "changeover":
        try:
            changeovers.append(
                ChangeoverRuleInput(
                    from_product_family=str(scope["from_product_family"]),
                    to_product_family=str(scope["to_product_family"]),
                    setup_minutes=int(scope["setup_minutes"]),
                    cost=float(scope.get("cost", 0.0)),
                    resource_id=_str_or_none(scope.get("resource_id")),
                )
            )
        except (KeyError, TypeError, ValueError):
            conflicts.append(_unsupported_candidate(candidate.candidate_id, refs))
            return False
        return True
    if candidate.constraint_type == "freeze_window":
        try:
            start = _parse_datetime(scope["window_start"])
            end = _parse_datetime(scope["window_end"])
        except (KeyError, TypeError, ValueError):
            conflicts.append(_unsupported_candidate(candidate.candidate_id, refs))
            return False
        freeze_windows.append(
            {
                "resource_id": _str_or_none(scope.get("resource_id")),
                "operation_id": _str_or_none(scope.get("operation_id")),
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "reason": _str_or_none(scope.get("reason")),
            }
        )
        return True

    conflicts.append(_unsupported_candidate(candidate.candidate_id, refs))
    return False


def _check_known_resources(
    pack: ConstraintCalibrationPack,
    resource_capabilities: dict[str, list[str]],
    resource_calendar: list[ResourceCalendarWindowInput],
    conflicts: list[ConstraintCalibrationConflict],
) -> None:
    if not pack.base_request:
        return
    known = {resource.resource_id for resource in pack.base_request.resources}
    for resource_id in sorted(resource_capabilities):
        if resource_id not in known:
            conflicts.append(
                _blocker(
                    "capability_unknown_resource",
                    "Capability matrix references a resource absent from the base request.",
                    "resource",
                    resource_id,
                )
            )
    for window in resource_calendar:
        if window.resource_id not in known:
            conflicts.append(
                _blocker(
                    "calendar_unknown_resource",
                    "Resource calendar references a resource absent from the base request.",
                    "resource",
                    window.resource_id,
                )
            )


def _check_calendar_overlaps(
    windows: list[ResourceCalendarWindowInput],
    conflicts: list[ConstraintCalibrationConflict],
) -> None:
    by_resource: dict[str, list[ResourceCalendarWindowInput]] = defaultdict(list)
    for window in windows:
        by_resource[window.resource_id].append(window)
    for resource_id, resource_windows in by_resource.items():
        sorted_windows = sorted(resource_windows, key=lambda window: window.window_start)
        for left, right in zip(sorted_windows, sorted_windows[1:]):
            if left.window_end > right.window_start:
                conflicts.append(
                    _warning(
                        "overlapping_calendar_windows",
                        "Overlapping calendar windows were kept; confirm whether this is intended.",
                        "resource",
                        resource_id,
                    )
                )
                break


def _check_duplicate_changeovers(
    rules: list[ChangeoverRuleInput],
    conflicts: list[ConstraintCalibrationConflict],
) -> None:
    seen: dict[str, int] = {}
    for rule in rules:
        key = _changeover_key(
            rule.from_product_family,
            rule.to_product_family,
            rule.resource_id,
        )
        previous = seen.get(key)
        if previous is None:
            seen[key] = rule.setup_minutes
            continue
        if previous != rule.setup_minutes:
            conflicts.append(
                _blocker(
                    "conflicting_changeover_rule",
                    "Same changeover key has conflicting setup minutes.",
                    "changeover",
                    key,
                )
            )
        else:
            conflicts.append(
                _warning(
                    "duplicate_changeover_rule",
                    "Duplicate changeover rule was kept with the same setup minutes.",
                    "changeover",
                    key,
                )
            )


def _apply_to_initial_request(
    base_request: InitialScheduleRequest,
    resource_capabilities: dict[str, list[str]],
    resource_calendar: list[ResourceCalendarWindowInput],
    changeovers: list[ChangeoverRuleInput],
    raw_data_patch: dict,
) -> InitialScheduleRequest:
    request = base_request.model_copy(deep=True)
    for resource in request.resources:
        additions = resource_capabilities.get(resource.resource_id)
        if additions:
            resource.capabilities = _dedupe([*resource.capabilities, *additions])
    request.resource_calendar = [*request.resource_calendar, *resource_calendar]
    request.changeover_rules = [*request.changeover_rules, *changeovers]
    existing_raw = getattr(request, "raw_data", None)
    if isinstance(existing_raw, dict):
        existing_raw.update(raw_data_patch)
    return request


def _candidate_is_publishable(reviewed: ReviewedConstraintCandidateInput) -> bool:
    return reviewed.review_status == "published_readonly" and reviewed.replay_passed


def _is_approved(status: str, approved_by: str | None) -> bool:
    return status == "approved" and bool(approved_by)


def _dedupe(values: list[str]) -> list[str]:
    return sorted({value.strip() for value in values if value and value.strip()})


def _list_of_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return _dedupe([part for part in value.split(",")])
    if isinstance(value, list):
        return _dedupe([str(item) for item in value])
    return []


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError("Expected datetime or ISO8601 string.")


def _changeover_key(
    from_product_family: str,
    to_product_family: str,
    resource_id: str | None,
) -> str:
    resource = resource_id or "*"
    return f"{resource}:{from_product_family}->{to_product_family}"


def _unsupported_candidate(
    candidate_id: str,
    source_refs: list[str],
) -> ConstraintCalibrationConflict:
    return _warning(
        "unsupported_rule_candidate",
        "Published rule candidate could not be compiled into a supported P0 constraint type.",
        "rule_candidate",
        candidate_id,
        source_refs,
    )


def _blocker(
    code: str,
    message: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    source_refs: list[str] | None = None,
) -> ConstraintCalibrationConflict:
    return ConstraintCalibrationConflict(
        code=code,
        severity="blocker",
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
        source_refs=source_refs or [],
    )


def _warning(
    code: str,
    message: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    source_refs: list[str] | None = None,
) -> ConstraintCalibrationConflict:
    return ConstraintCalibrationConflict(
        code=code,
        severity="warning",
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
        source_refs=source_refs or [],
    )
