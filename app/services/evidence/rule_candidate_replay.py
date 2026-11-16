"""Server-side deterministic replay for reviewed rule candidates."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from app.models.agent import (
    ConstraintCandidate,
    RuleCandidateReplayRequest,
    RuleCandidateReplayResult,
    RuleReplayScenario,
    RuleReplayScenarioResult,
)


class RuleCandidateReplayService:
    """Derive coverage from executed results, never from a caller-provided count."""

    def run(
        self,
        candidate: ConstraintCandidate,
        request: RuleCandidateReplayRequest,
    ) -> RuleCandidateReplayResult:
        notes = list(request.notes)
        candidate_blocker = _candidate_blocker(candidate)
        scenario_results = [
            self._execute(candidate, scenario) for scenario in request.scenarios
        ]
        blocked_reason = candidate_blocker
        if blocked_reason is None and len(scenario_results) < 3:
            blocked_reason = "at_least_three_executed_scenario_results_required"
        if blocked_reason is None and len({item.scenario_id for item in scenario_results}) != len(
            scenario_results
        ):
            blocked_reason = "duplicate_replay_scenario_ids"
        if blocked_reason is None and any(not item.passed for item in scenario_results):
            blocked_reason = "one_or_more_executed_scenarios_failed"
        pass_replay = blocked_reason is None
        scope_counts: dict[str, int] = {}
        for result in scenario_results:
            scope_counts[result.evidence_scope] = scope_counts.get(result.evidence_scope, 0) + 1
        notes.append(
            "Coverage is derived from server-executed scenario results and evidence fingerprints; production enablement remains a separate gate."
        )
        return RuleCandidateReplayResult(
            pass_replay=pass_replay,
            scenario_count=len(scenario_results),
            scenario_results=scenario_results,
            evidence_scope_counts=scope_counts,
            blocked_reason=blocked_reason,
            metrics={
                "confidence": candidate.confidence,
                "scenario_set": request.scenario_set,
                "source_ref_count": len(candidate.source_refs),
                "passed_scenario_count": sum(item.passed for item in scenario_results),
                "readonly_publish_required": True,
                "caller_scenario_count_ignored": request.scenario_count is not None,
                "customer_result_count": sum(
                    count
                    for scope, count in scope_counts.items()
                    if scope.startswith("customer_")
                ),
            },
            notes=notes,
        )

    def _execute(
        self,
        candidate: ConstraintCandidate,
        scenario: RuleReplayScenario,
    ) -> RuleReplayScenarioResult:
        observed, triggered, blockers = _evaluate(candidate, scenario.facts)
        quality_gate_passed = not blockers
        passed = quality_gate_passed and observed == scenario.expected_outcome
        payload = {
            "candidate_id": candidate.candidate_id,
            "compiled_rule": candidate.compiled_rule,
            "scenario": scenario.model_dump(mode="json"),
            "observed_outcome": observed,
            "rule_triggered": triggered,
            "quality_gate_passed": quality_gate_passed,
            "blockers": blockers,
        }
        return RuleReplayScenarioResult(
            scenario_id=scenario.scenario_id,
            evidence_scope=scenario.evidence_scope,
            snapshot_ref=scenario.snapshot_ref,
            source_refs=scenario.source_refs,
            expected_outcome=scenario.expected_outcome,
            observed_outcome=observed,
            rule_triggered=triggered,
            quality_gate_passed=quality_gate_passed,
            passed=passed,
            blockers=blockers,
            result_fingerprint=_fingerprint(payload),
        )


def _candidate_blocker(candidate: ConstraintCandidate) -> str | None:
    if candidate.constraint_type == "review_note":
        return "rule_type_or_scope_unclear"
    if candidate.confidence < 0.65:
        return "candidate_confidence_below_replay_threshold"
    if candidate.constraint_type in {"calendar", "skill", "forbidden_assignment"}:
        if not candidate.scope.get("machine_ids"):
            return "missing_machine_scope"
    if "缺少明确" in (candidate.risk_note or ""):
        return "risk_note_requires_more_scope"
    return None


def _evaluate(
    candidate: ConstraintCandidate, facts: dict[str, Any]
) -> tuple[str, bool, list[str]]:
    constraint_type = candidate.constraint_type
    machine_ids = {str(item) for item in candidate.scope.get("machine_ids", []) or []}
    operation_ids = {
        str(item) for item in candidate.scope.get("operation_ids", []) or []
    }
    machine_id = str(facts.get("machine_id", ""))
    operation_id = str(facts.get("operation_id", ""))

    if constraint_type == "calendar":
        cutoff = _cutoff_minutes(candidate.compiled_rule or candidate.source_text)
        start = _time_minutes(facts.get("operation_start_time"))
        if cutoff is None or start is None or not machine_id:
            return "review", False, ["calendar_scenario_facts_incomplete"]
        triggered = machine_id in machine_ids and start >= cutoff
        return ("avoid" if triggered else "allow"), triggered, []

    if constraint_type == "quality":
        if not operation_id or "qms_status" not in facts:
            return "review", False, ["quality_scenario_facts_incomplete"]
        in_scope = not operation_ids or operation_id in operation_ids
        released = str(facts.get("qms_status", "")).lower() in {
            "released",
            "cleared",
            "closed",
        }
        triggered = in_scope and not released
        return ("block" if triggered else "allow"), triggered, []

    if constraint_type == "skill":
        if not machine_id or "operator_available" not in facts:
            return "review", False, ["skill_scenario_facts_incomplete"]
        triggered = machine_id in machine_ids and not bool(facts["operator_available"])
        return ("avoid" if triggered else "allow"), triggered, []

    if constraint_type == "forbidden_assignment":
        if not machine_id:
            return "review", False, ["assignment_scenario_facts_incomplete"]
        machine_match = machine_id in machine_ids
        operation_match = not operation_ids or operation_id in operation_ids
        triggered = machine_match and operation_match
        return ("block" if triggered else "allow"), triggered, []

    return "review", False, ["unsupported_rule_type_for_deterministic_replay"]


def _cutoff_minutes(value: str) -> int | None:
    match = re.search(r"(?:[01]?\d|2[0-3]):[0-5]\d", value)
    return _time_minutes(match.group(0)) if match else None


def _time_minutes(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.hour * 60 + value.minute
    text = str(value)
    match = re.search(r"(?:[01]?\d|2[0-3]):[0-5]\d", text)
    if not match:
        return None
    hour, minute = match.group(0).split(":")
    return int(hour) * 60 + int(minute)


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()
