"""Minimal recovery operators for non-equipment production exceptions."""

from __future__ import annotations

from collections.abc import Callable

from app.models.recovery_operator import (
    RecoveryOperatorCandidate,
    RecoveryOperatorGateReport,
    RecoveryOperatorReplayCase,
    RecoveryOperatorReplaySummary,
    RecoveryOperatorRequest,
    RecoveryOperatorResponse,
)


_CLAIM_BOUNDARY = (
    "Non-equipment operator replay is a planner-review gate, not proof of "
    "autonomous production writeback. Customer-calibrated constraints, planner "
    "approval, audit, rollback, and execution feedback are still required."
)


class NonEquipmentRecoveryOperatorService:
    """Builds Top-N planner-review candidates for non-equipment incidents."""

    def run(self, request: RecoveryOperatorRequest) -> RecoveryOperatorResponse:
        builders = _BUILDERS[request.incident_type]
        candidates = [
            candidate for builder in builders for candidate in [builder(request)]
        ][: request.top_n]
        recommended = next(
            (
                candidate.operator_id
                for candidate in candidates
                if candidate.gate_report.pass_gate
            ),
            None,
        )
        return RecoveryOperatorResponse(
            case_id=request.case_id,
            incident_type=request.incident_type,
            candidates=candidates,
            recommended_operator_id=recommended,
            can_enter_planner_review=recommended is not None,
            claim_boundary=_CLAIM_BOUNDARY,
        )

    def replay_batch(
        self, cases: list[RecoveryOperatorReplayCase]
    ) -> RecoveryOperatorReplaySummary:
        responses = [self.run(case.request) for case in cases]
        gate_pass = sum(response.can_enter_planner_review for response in responses)
        coverage = 0
        for case, response in zip(cases, responses, strict=True):
            top_n_ids = {candidate.operator_id for candidate in response.candidates}
            if (
                case.manual_accepted_operator_id
                and case.manual_accepted_operator_id in top_n_ids
                and any(
                    candidate.operator_id == case.manual_accepted_operator_id
                    and candidate.gate_report.pass_gate
                    for candidate in response.candidates
                )
            ):
                coverage += 1
        count = len(cases)
        return RecoveryOperatorReplaySummary(
            replayed_case_count=count,
            cases_with_gate_pass=gate_pass,
            gate_pass_rate=round(gate_pass / count, 4) if count else 0.0,
            top_n_manual_coverage_count=coverage,
            top_n_manual_coverage_rate=round(coverage / count, 4) if count else 0.0,
            responses=responses,
        )


def _material_wait(request: RecoveryOperatorRequest) -> RecoveryOperatorCandidate:
    context = request.context
    blockers = _missing(context, ["material_id"])
    required_evidence = ["material_id", "material_available_at or partial_quantity_available"]
    if not (context.get("material_available_at") or context.get("partial_quantity_available")):
        blockers.append("missing_material_recovery_evidence")
    warnings: list[str] = []
    if context.get("substitute_material_ids"):
        warnings.append("Substitution exists but requires quality and engineering approval.")
    return _candidate(
        operator_id="material_wait_or_partial_release",
        action_type="delay_or_partial_release",
        description="Hold affected operation until material is available, or release only the covered quantity.",
        expected_effect="Prevents infeasible dispatch before material kitting is confirmed.",
        blockers=blockers,
        warnings=warnings,
        required_evidence=required_evidence,
        approvals=["planner", "warehouse"] if not blockers else [],
    )


def _material_substitute(request: RecoveryOperatorRequest) -> RecoveryOperatorCandidate:
    context = request.context
    blockers = _missing(context, ["material_id", "substitute_material_ids"])
    if not context.get("substitution_approved"):
        blockers.append("substitution_not_approved")
    return _candidate(
        operator_id="material_substitution",
        action_type="substitute_material",
        description="Use an approved substitute material and keep lot traceability.",
        expected_effect="Recovers the blocked operation without waiting for the original material.",
        blockers=blockers,
        required_evidence=["approved_substitute_material", "lot_traceability"],
        approvals=["planner", "quality", "engineering"] if not blockers else [],
    )


def _urgent_priority_swap(request: RecoveryOperatorRequest) -> RecoveryOperatorCandidate:
    context = request.context
    blockers = _missing(context, ["rush_order_id", "due_time", "candidate_displaced_work_order_id"])
    if not context.get("customer_service_approval"):
        blockers.append("customer_service_approval_missing")
    return _candidate(
        operator_id="urgent_priority_swap",
        action_type="priority_swap",
        description="Insert the rush order by displacing a lower-priority operation in the same resource neighborhood.",
        expected_effect="Makes the delivery trade-off explicit before planner confirmation.",
        blockers=blockers,
        required_evidence=["rush_order_due_time", "displaced_order_impact"],
        approvals=["planner", "customer_service"] if not blockers else [],
    )


def _urgent_overtime_window(request: RecoveryOperatorRequest) -> RecoveryOperatorCandidate:
    context = request.context
    blockers = _missing(context, ["rush_order_id", "due_time"])
    if not context.get("overtime_window"):
        blockers.append("overtime_window_missing")
    return _candidate(
        operator_id="urgent_overtime_window",
        action_type="extend_capacity_window",
        description="Place the rush order into an approved overtime or extra-shift window.",
        expected_effect="Protects existing commitments while exposing overtime cost.",
        blockers=blockers,
        required_evidence=["approved_overtime_window", "capacity_owner"],
        approvals=["planner", "production_manager"] if not blockers else [],
    )


def _quality_hold_freeze(request: RecoveryOperatorRequest) -> RecoveryOperatorCandidate:
    context = request.context
    blockers = _missing(context, ["hold_id", "quality_owner"])
    return _candidate(
        operator_id="quality_hold_freeze_and_resequence",
        action_type="freeze_and_resequence_downstream",
        description="Freeze the held operation and resequence downstream work without moving unreleased quality scope.",
        expected_effect="Avoids illegal movement before QA release while preserving feasible downstream work.",
        blockers=blockers,
        required_evidence=["hold_id", "quality_owner", "hold_scope"],
        approvals=["planner", "quality"] if not blockers else [],
    )


def _quality_release_repair(request: RecoveryOperatorRequest) -> RecoveryOperatorCandidate:
    context = request.context
    blockers = _missing(context, ["hold_id", "quality_release_at"])
    if not context.get("release_authorized"):
        blockers.append("quality_release_not_authorized")
    return _candidate(
        operator_id="quality_release_repair",
        action_type="release_and_local_repair",
        description="Repair the schedule after an authorized quality release timestamp.",
        expected_effect="Restores flow only after QA authorization is recorded.",
        blockers=blockers,
        required_evidence=["quality_release_at", "release_authorization"],
        approvals=["planner", "quality"] if not blockers else [],
    )


def _tooling_reallocation(request: RecoveryOperatorRequest) -> RecoveryOperatorCandidate:
    context = request.context
    blockers = _missing(context, ["tooling_id", "conflicting_operation_id"])
    if not (context.get("alternative_tooling_ids") or context.get("next_available_at")):
        blockers.append("missing_tooling_recovery_path")
    return _candidate(
        operator_id="tooling_reallocation",
        action_type="reallocate_tooling",
        description="Assign an alternative tool or wait for the next audited tooling availability window.",
        expected_effect="Prevents double-booking a fixture/tool while keeping the conflict visible.",
        blockers=blockers,
        required_evidence=["tooling_id", "tool_calendar_or_alternative_tool"],
        approvals=["planner", "tooling_owner"] if not blockers else [],
    )


def _labor_reassignment(request: RecoveryOperatorRequest) -> RecoveryOperatorCandidate:
    context = request.context
    blockers = _missing(context, ["skill_code", "required_headcount"])
    if not (
        context.get("alternate_team_ids")
        or context.get("overtime_approval")
        or context.get("next_shift_available_at")
    ):
        blockers.append("missing_labor_recovery_path")
    return _candidate(
        operator_id="labor_skill_pool_reassignment",
        action_type="reassign_skill_pool",
        description="Reassign qualified labor, use approved overtime, or delay to the next qualified shift.",
        expected_effect="Keeps skill constraints explicit instead of treating labor as unlimited capacity.",
        blockers=blockers,
        required_evidence=["skill_code", "qualified_labor_availability"],
        approvals=["planner", "production_manager"] if not blockers else [],
    )


def _candidate(
    *,
    operator_id: str,
    action_type: str,
    description: str,
    expected_effect: str,
    blockers: list[str],
    required_evidence: list[str],
    approvals: list[str],
    warnings: list[str] | None = None,
) -> RecoveryOperatorCandidate:
    pass_gate = not blockers
    return RecoveryOperatorCandidate(
        operator_id=operator_id,
        action_type=action_type,
        description=description,
        expected_effect=expected_effect,
        gate_report=RecoveryOperatorGateReport(
            pass_gate=pass_gate,
            hard_blockers=blockers,
            warnings=warnings or [],
            required_human_approvals=approvals,
            required_evidence=required_evidence,
            decision_boundary=(
                "May enter planner review; no production writeback without approval."
                if pass_gate
                else "Reference only until blockers are resolved."
            ),
        ),
    )


def _missing(context: dict[str, object], keys: list[str]) -> list[str]:
    return [f"missing_{key}" for key in keys if not context.get(key)]


_BUILDERS: dict[str, list[Callable[[RecoveryOperatorRequest], RecoveryOperatorCandidate]]] = {
    "material_shortage": [_material_wait, _material_substitute],
    "urgent_order_insert": [_urgent_priority_swap, _urgent_overtime_window],
    "quality_hold": [_quality_hold_freeze, _quality_release_repair],
    "tooling_conflict": [_tooling_reallocation],
    "labor_shortage": [_labor_reassignment],
    "operator_skill_shortage": [_labor_reassignment],
}
