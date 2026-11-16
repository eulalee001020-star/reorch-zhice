"""Deterministic classification of solver outcomes before recovery search."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.models.feasibility_restoration import FailureClassification


_GOVERNANCE_MARKERS = (
    "GOVERNANCE",
    "QMS_",
    "QMS:",
    "BATCH_NOT_RELEASED",
    "QUALITY_HOLD",
    "BUFFER_ALREADY_OVER_CAPACITY",
    "INDEPENDENT_CONSTRAINT_VALIDATION_FAILED",
)
_CAPACITY_STATUSES = {"SOLVER_CAPACITY_EXHAUSTED", "QUEUE_TIMEOUT"}
_UNKNOWN_STATUSES = {
    "UNKNOWN",
    "NO_VALIDATED_INCUMBENT",
    "INSTANCE_REQUIRES_DECOMPOSITION",
    "HEURISTIC_TIMEOUT",
    "TIMEOUT",
}


class InfeasibilityClassifier:
    """Keep timeout, governance failure, and proven infeasibility separate."""

    @staticmethod
    def classify(
        *,
        status_name: str,
        is_feasible: bool,
        solver_log: dict[str, Any] | None = None,
        blockers: Iterable[str] = (),
    ) -> FailureClassification:
        log = solver_log or {}
        raw_status = str(status_name or "UNKNOWN").upper()
        cp_status = str(log.get("cp_sat_status") or "").upper()
        all_blockers = sorted(
            {
                *(str(item) for item in blockers),
                *(str(item) for item in log.get("blockers", []) or []),
                *(str(item) for item in log.get("failures", []) or []),
            }
        )
        normalized_blockers = [item.upper() for item in all_blockers]

        if is_feasible:
            return FailureClassification(
                failure_class="feasible",
                raw_solver_status=raw_status,
                proof_status="not_applicable",
                blockers=all_blockers,
                baseline_must_be_preserved=False,
                may_enter_relaxation_search=False,
                required_next_step="independent_validation_and_quality_gate",
            )
        if raw_status == "MODEL_INVALID" or cp_status == "MODEL_INVALID":
            return FailureClassification(
                failure_class="model_invalid",
                raw_solver_status=raw_status,
                proof_status="not_applicable",
                blockers=all_blockers,
                may_enter_relaxation_search=False,
                required_next_step="repair_model_or_schema_before_rescheduling",
            )
        if raw_status in _CAPACITY_STATUSES or cp_status in _CAPACITY_STATUSES:
            return FailureClassification(
                failure_class="capacity_exhausted",
                raw_solver_status=raw_status,
                proof_status="not_proven",
                blockers=all_blockers,
                may_enter_relaxation_search=False,
                required_next_step="preserve_baseline_and_retry_through_durable_queue",
            )
        if raw_status == "GOVERNANCE_CONSTRAINT_BLOCKED" or any(
            any(marker in blocker for marker in _GOVERNANCE_MARKERS)
            for blocker in normalized_blockers
        ):
            return FailureClassification(
                failure_class="data_or_governance_blocked",
                raw_solver_status=raw_status,
                proof_status="not_applicable",
                blockers=all_blockers,
                may_enter_relaxation_search=False,
                required_next_step="quarantine_or_release_governed_source_state",
            )
        if raw_status == "INFEASIBLE" or cp_status == "INFEASIBLE":
            return FailureClassification(
                failure_class="proven_infeasible",
                raw_solver_status=raw_status,
                proof_status="proven",
                blockers=all_blockers,
                may_enter_relaxation_search=True,
                required_next_step="extract_conflicts_and_search_authorized_recovery",
            )
        if raw_status in _UNKNOWN_STATUSES or cp_status in _UNKNOWN_STATUSES:
            return FailureClassification(
                failure_class="search_exhausted",
                raw_solver_status=raw_status,
                proof_status="not_proven",
                blockers=all_blockers,
                may_enter_relaxation_search=False,
                required_next_step="preserve_baseline_expand_scope_or_search_budget",
            )
        return FailureClassification(
            failure_class="search_exhausted",
            raw_solver_status=raw_status,
            proof_status="not_proven",
            blockers=all_blockers,
            may_enter_relaxation_search=False,
            required_next_step="preserve_baseline_and_review_solver_diagnostics",
        )
