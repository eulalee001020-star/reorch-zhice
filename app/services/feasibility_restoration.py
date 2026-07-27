"""Minimum-loss, approval-gated feasibility restoration for rescheduling."""

from __future__ import annotations

import copy
import hashlib
import heapq
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from app.core.config import settings
from app.models.enums import StrategyType
from app.models.feasibility_restoration import (
    ConflictRefinementReport,
    FailureClassification,
    FeasibilityCertificate,
    FeasibilityRestorationRequest,
    FeasibilityRestorationResponse,
    RecoveryAction,
    RecoveryActionRule,
    RecoveryActionType,
    RecoveryApprovalAttestation,
    RecoveryPack,
    RecoveryPolicy,
    SafeHoldDisposition,
)
from app.models.production_runtime import (
    DecompositionExecutionRequest,
    RuntimeIncident,
)
from app.models.schedule import Resource, ScheduleDetail, ScheduleSnapshot
from app.models.solver import ConstraintValidationReport, ConstraintViolation
from app.services.anytime_hybrid_scheduler import AnytimeHybridScheduler
from app.services.constraint_assumption_registry import ConstraintAssumptionRegistry
from app.services.constraint_conflict_refiner import ConstraintConflictRefiner
from app.services.decomposition_executor import DecompositionExecutor
from app.services.infeasibility_classifier import InfeasibilityClassifier
from app.services.operational_constraint_validator import OperationalConstraintValidator
from app.services.recovery_approval_policy import RecoveryApprovalPolicy


_CLAIM_BOUNDARY = (
    "A feasibility certificate proves zero detected hard-constraint violations on "
    "the versioned effective snapshot after approved recovery actions. It does not "
    "authorize MES writeback, prove customer ROI, or permit safety, quality, process "
    "precedence, capability, genealogy, or source-authority constraints to be ignored."
)

_ACTION_FAMILY = {
    "expand_repair_scope": "schedule_scope",
    "release_planning_freeze": "planning_freeze",
    "relax_operation_deadline": "operation_deadline",
    "open_overtime_window": "resource_calendar",
    "activate_outsourcing": "equipment_capability",
    "activate_substitute_material": "material_availability",
    "defer_work_order": "demand_commitment",
    "safe_hold": "operational_safety",
}
_CONSTRAINT_REGISTRY = ConstraintAssumptionRegistry()


@dataclass(frozen=True)
class _SolveProbe:
    schedule: ScheduleDetail | None
    status_name: str
    classification: FailureClassification
    validation: ConstraintValidationReport
    solver_log: dict[str, Any]


@dataclass(frozen=True)
class _GeneratedActions:
    searchable: list[RecoveryAction]
    unavailable: list[RecoveryAction]
    action_space_complete: bool


@dataclass(frozen=True)
class _SearchResult:
    packs: list[RecoveryPack]
    trials: int
    incomplete: bool
    first_minimum_action_ids: list[str]
    first_minimum_proven: bool


SchedulerFactory = Callable[[], AnytimeHybridScheduler]


class FeasibilityRestorationEngine:
    """Diagnose true infeasibility and search authorized recovery operators."""

    def __init__(
        self,
        *,
        scheduler_factory: SchedulerFactory | None = None,
        decomposition_executor: DecompositionExecutor | None = None,
        validator: OperationalConstraintValidator | None = None,
        refiner: ConstraintConflictRefiner | None = None,
    ) -> None:
        self._scheduler_factory = scheduler_factory or AnytimeHybridScheduler
        self._decomposition = decomposition_executor or DecompositionExecutor()
        self._validator = validator or OperationalConstraintValidator()
        self._refiner = refiner or ConstraintConflictRefiner()

    def evaluate(
        self, request: FeasibilityRestorationRequest
    ) -> FeasibilityRestorationResponse:
        started = time.perf_counter()
        deadline = started + request.timeout_seconds
        if settings.app.env in {"staging", "production"} and (
            request.policy is None or not request.policy.customer_owned
        ):
            raise ValueError("active_customer_owned_recovery_policy_required")
        policy = request.policy or conservative_default_recovery_policy()
        run_id = f"restore-{uuid4().hex}"
        safe_hold = _safe_hold(request, policy)
        requested_strategy = StrategyType(request.strategy_type)

        initial = self._solve(
            request=request,
            snapshot=request.snapshot,
            frozen_operation_ids=request.frozen_operation_ids,
            strategy_type=requested_strategy,
            deadline=deadline,
        )
        if initial.schedule is not None and initial.validation.is_feasible:
            pack = self._build_pack(
                request=request,
                policy=policy,
                actions=[],
                effective_snapshot=request.snapshot,
                probe=initial,
                optimality_proven=True,
            )
            conflict_report = ConflictRefinementReport(
                core_status="not_available",
                explanation="The requested model is already feasible; no conflict core exists.",
            )
            return self._response(
                run_id=run_id,
                request=request,
                status="already_feasible",
                classification=initial.classification,
                conflict_report=conflict_report,
                packs=[pack],
                unavailable_actions=[],
                safe_hold=safe_hold,
                trials=1,
                started=started,
            )

        decisive_probe = initial
        expansion_pack: RecoveryPack | None = None
        if requested_strategy != StrategyType.GLOBAL_RESCHEDULE:
            expanded = self._solve(
                request=request,
                snapshot=request.snapshot,
                frozen_operation_ids=request.frozen_operation_ids,
                strategy_type=StrategyType.GLOBAL_RESCHEDULE,
                deadline=deadline,
            )
            decisive_probe = expanded
            if expanded.schedule is not None and expanded.validation.is_feasible:
                expansion_action = _expansion_action(request, policy)
                expansion_pack = self._build_pack(
                    request=request,
                    policy=policy,
                    actions=[expansion_action],
                    effective_snapshot=request.snapshot,
                    probe=expanded,
                    optimality_proven=True,
                )

        if expansion_pack is not None:
            conflict_report = self._refiner.refine(
                snapshot=request.snapshot,
                impact_report=request.impact_report,
                frozen_operation_ids=request.frozen_operation_ids,
                classification=initial.classification,
            )
            conflict_report.explanation = (
                "The requested local scope was insufficient, but global scope restored "
                "feasibility without relaxing an operational constraint."
            )
            return self._response(
                run_id=run_id,
                request=request,
                status="recovery_available",
                classification=expanded.classification,
                conflict_report=conflict_report,
                packs=[expansion_pack],
                unavailable_actions=[],
                safe_hold=safe_hold,
                trials=2,
                started=started,
            )

        conflict_report = self._refiner.refine(
            snapshot=request.snapshot,
            impact_report=request.impact_report,
            frozen_operation_ids=request.frozen_operation_ids,
            classification=decisive_probe.classification,
            independent_violations=decisive_probe.validation.violations,
        )
        if not decisive_probe.classification.may_enter_relaxation_search:
            status = (
                "blocked"
                if decisive_probe.classification.failure_class
                in {"data_or_governance_blocked", "model_invalid"}
                else "search_exhausted"
            )
            return self._response(
                run_id=run_id,
                request=request,
                status=status,
                classification=decisive_probe.classification,
                conflict_report=conflict_report,
                packs=[],
                unavailable_actions=[],
                safe_hold=safe_hold,
                trials=2 if requested_strategy != StrategyType.GLOBAL_RESCHEDULE else 1,
                started=started,
            )

        generated = _generate_actions(request, policy)
        search = self._search(
            request=request,
            policy=policy,
            actions=generated.searchable,
            action_space_complete=generated.action_space_complete,
            deadline=deadline,
        )
        if search.first_minimum_action_ids:
            conflict_report.core_status = "minimum_correction_set"
            conflict_report.minimum_correction_action_ids = (
                search.first_minimum_action_ids
            )
            conflict_report.optimality_proven = search.first_minimum_proven
            conflict_report.probe_count = search.trials
            conflict_report.explanation = (
                "The listed recovery actions are the first feasible correction set under "
                "the supplied lexicographic policy and bounded action space. The proof does "
                "not extend to unregistered recovery operators."
            )

        executable = [
            pack for pack in search.packs if pack.status == "validated_feasible"
        ]
        pending = [pack for pack in search.packs if pack.status == "pending_approval"]
        if executable:
            response_status = "recovery_available"
        elif pending:
            response_status = "pending_approval"
        elif search.incomplete:
            response_status = "search_exhausted"
        else:
            response_status = "safe_hold_only"
        return self._response(
            run_id=run_id,
            request=request,
            status=response_status,
            classification=decisive_probe.classification,
            conflict_report=conflict_report,
            packs=search.packs,
            unavailable_actions=generated.unavailable,
            safe_hold=safe_hold,
            trials=(
                search.trials
                + (2 if requested_strategy != StrategyType.GLOBAL_RESCHEDULE else 1)
            ),
            started=started,
        )

    def _search(
        self,
        *,
        request: FeasibilityRestorationRequest,
        policy: RecoveryPolicy,
        actions: list[RecoveryAction],
        action_space_complete: bool,
        deadline: float,
    ) -> _SearchResult:
        ordered = sorted(actions, key=_single_action_key)
        queue: list[tuple[tuple[float, ...], tuple[int, ...]]] = []
        seen: set[tuple[int, ...]] = set()
        for index in range(len(ordered)):
            initial_state: tuple[int, ...] = (index,)
            heapq.heappush(
                queue, (_state_key(initial_state, ordered), initial_state)
            )
            seen.add(initial_state)

        packs: list[RecoveryPack] = []
        trials = 0
        unknown_seen = False
        first_minimum_action_ids: list[str] = []
        first_minimum_proven = False
        target_pool = max(request.top_n * 3, request.top_n)
        while queue and trials < policy.max_search_trials and time.perf_counter() < deadline:
            _, current_state = heapq.heappop(queue)
            selected = [ordered[index] for index in current_state]
            if sum(action.penalty_cost for action in selected) > policy.max_total_penalty_cost:
                continue
            if not _within_type_limits(selected, policy):
                continue
            effective_snapshot, effective_frozen = _apply_actions(
                request.snapshot,
                request.frozen_operation_ids,
                selected,
                request.approvals,
            )
            probe = self._solve(
                request=request,
                snapshot=effective_snapshot,
                frozen_operation_ids=effective_frozen,
                strategy_type=StrategyType.GLOBAL_RESCHEDULE,
                deadline=deadline,
            )
            trials += 1
            if probe.classification.failure_class in {
                "search_exhausted",
                "capacity_exhausted",
            }:
                unknown_seen = True
            if probe.schedule is not None and probe.validation.is_feasible:
                optimality_proven = (
                    not packs and not unknown_seen and action_space_complete
                )
                pack = self._build_pack(
                    request=request,
                    policy=policy,
                    actions=selected,
                    effective_snapshot=effective_snapshot,
                    probe=probe,
                    optimality_proven=optimality_proven,
                )
                packs.append(pack)
                if not first_minimum_action_ids:
                    first_minimum_action_ids = [
                        action.action_id for action in selected
                    ]
                    first_minimum_proven = optimality_proven
                if len(packs) >= target_pool and any(
                    item.status == "validated_feasible" for item in packs
                ):
                    break
                continue

            if len(current_state) >= policy.max_actions_per_pack:
                continue
            for next_index in range(current_state[-1] + 1, len(ordered)):
                child = (*current_state, next_index)
                if child in seen:
                    continue
                seen.add(child)
                heapq.heappush(queue, (_state_key(child, ordered), child))

        packs.sort(key=lambda item: tuple(item.lexicographic_rank))
        selected_packs = packs[: request.top_n]
        first_executable = next(
            (item for item in packs if item.status == "validated_feasible"), None
        )
        if first_executable and first_executable not in selected_packs:
            selected_packs = [*selected_packs[: max(0, request.top_n - 1)], first_executable]
            selected_packs.sort(key=lambda item: tuple(item.lexicographic_rank))
        incomplete = bool(queue) or trials >= policy.max_search_trials or unknown_seen
        return _SearchResult(
            packs=selected_packs,
            trials=trials,
            incomplete=incomplete,
            first_minimum_action_ids=first_minimum_action_ids,
            first_minimum_proven=first_minimum_proven,
        )

    def _solve(
        self,
        *,
        request: FeasibilityRestorationRequest,
        snapshot: ScheduleSnapshot,
        frozen_operation_ids: list[str],
        strategy_type: StrategyType,
        deadline: float,
    ) -> _SolveProbe:
        remaining = deadline - time.perf_counter()
        if remaining <= 0.01:
            classification = InfeasibilityClassifier.classify(
                status_name="TIMEOUT", is_feasible=False
            )
            return _SolveProbe(
                schedule=None,
                status_name="TIMEOUT",
                classification=classification,
                validation=ConstraintValidationReport(is_feasible=False),
                solver_log={},
            )
        operation_ids = {
            operation.operation_id
            for work_order in snapshot.work_orders
            for operation in work_order.operations
        }
        if not operation_ids:
            schedule = ScheduleDetail(resources=_resources(snapshot))
            validation = self._validator.validate(schedule, snapshot)
            classification = InfeasibilityClassifier.classify(
                status_name="FEASIBLE_DEFERRED_SCOPE",
                is_feasible=validation.is_feasible,
            )
            return _SolveProbe(
                schedule=schedule if validation.is_feasible else None,
                status_name="FEASIBLE_DEFERRED_SCOPE",
                classification=classification,
                validation=validation,
                solver_log={"deferred_all_active_work_orders": True},
            )

        planning_freeze_conflicts = _planning_frozen_incident_ids(
            request,
            snapshot,
            frozen_operation_ids,
        )
        if planning_freeze_conflicts:
            blockers = [
                f"frozen_incident_operation:{operation_id}"
                for operation_id in planning_freeze_conflicts
            ]
            classification = InfeasibilityClassifier.classify(
                status_name="INFEASIBLE",
                is_feasible=False,
                blockers=blockers,
            )
            return _SolveProbe(
                schedule=None,
                status_name="INFEASIBLE",
                classification=classification,
                validation=ConstraintValidationReport(
                    is_feasible=False,
                    violations=[
                        ConstraintViolation(
                            constraint_type="frozen_incident_operation",
                            operation_id=operation_id,
                            detail=(
                                "A planned frozen operation is incident-affected and "
                                "requires explicit freeze-release approval."
                            ),
                        )
                        for operation_id in planning_freeze_conflicts
                    ],
                    checked_constraints=["planned_freeze_incident_consistency"],
                ),
                solver_log={"blockers": blockers},
            )

        effective_snapshot = _with_frozen_ids(snapshot, frozen_operation_ids)
        if len(operation_ids) > settings.solver.max_model_operations:
            return self._solve_decomposed(
                request=request,
                snapshot=effective_snapshot,
                deadline=deadline,
            )

        active_affected = [
            item.operation_id
            for item in request.impact_report.affected_operations
            if item.operation_id in operation_ids
        ]
        result = self._scheduler_factory().solve(
            snapshot=effective_snapshot,
            impact_report=request.impact_report,
            strategy_type=strategy_type,
            affected_op_ids=active_affected,
            frozen_operation_ids=frozen_operation_ids,
            timeout_seconds=max(0.1, min(remaining, 30.0)),
            goal_mode=_enum_value(request.goal_mode),
        )
        classification = InfeasibilityClassifier.classify(
            status_name=result.status_name,
            is_feasible=result.is_feasible,
            solver_log=result.solver_log,
        )
        if result.schedule_detail is None:
            violations = [
                ConstraintViolation.model_validate(item)
                for item in result.solver_log.get("independent_violations", []) or []
            ]
            return _SolveProbe(
                schedule=None,
                status_name=result.status_name,
                classification=classification,
                validation=ConstraintValidationReport(
                    is_feasible=False,
                    violations=violations,
                ),
                solver_log=result.solver_log,
            )
        validation = self._validator.validate(
            result.schedule_detail,
            effective_snapshot,
            frozen_operation_ids=frozen_operation_ids,
        )
        if not validation.is_feasible:
            classification = InfeasibilityClassifier.classify(
                status_name="INDEPENDENT_VALIDATION_FAILED",
                is_feasible=False,
                blockers=[
                    "independent_constraint_validation_failed",
                    *(item.constraint_type for item in validation.violations),
                ],
            )
        return _SolveProbe(
            schedule=result.schedule_detail if validation.is_feasible else None,
            status_name=result.status_name,
            classification=classification,
            validation=validation,
            solver_log=result.solver_log,
        )

    def _solve_decomposed(
        self,
        *,
        request: FeasibilityRestorationRequest,
        snapshot: ScheduleSnapshot,
        deadline: float,
    ) -> _SolveProbe:
        operation_ids = [
            operation.operation_id
            for work_order in snapshot.work_orders
            for operation in work_order.operations
        ]
        affected = [
            item.operation_id
            for item in request.impact_report.affected_operations
            if item.operation_id in set(operation_ids)
        ] or operation_ids[:1]
        incident = RuntimeIncident(
            incident_id=str(request.impact_report.incident_id),
            incident_type="feasibility_restoration",
            affected_operation_ids=affected,
            delay_minutes=max(
                [
                    int(round(item.estimated_delay_minutes))
                    for item in request.impact_report.affected_operations
                    if item.operation_id in set(affected)
                ]
                or [0]
            ),
            severity="P1",
            occurred_at=request.impact_report.analysis_reference_time,
        )
        response = self._decomposition.execute(
            DecompositionExecutionRequest(
                tenant_id=request.tenant_id,
                snapshot=snapshot,
                incidents=[incident],
                max_subproblem_operations=min(
                    200, max(20, settings.solver.max_model_operations)
                ),
                max_parallelism=min(4, settings.solver.max_concurrent_jobs),
                timeout_seconds=max(0.1, min(deadline - time.perf_counter(), 60.0)),
                goal_mode=_enum_value(request.goal_mode),
            )
        )
        feasible = response.status == "feasible" and response.final_schedule is not None
        statuses = {
            item.solver_status.upper() for item in response.subproblem_results
        }
        subproblem_failure_classes = {
            str(
                item.solver_metadata.get("failure_classification", {}).get(
                    "failure_class", ""
                )
            )
            for item in response.subproblem_results
        }
        all_blockers = sorted(
            {
                *response.blockers,
                *(
                    blocker
                    for item in response.subproblem_results
                    for blocker in item.blockers
                ),
                *(
                    str(blocker)
                    for item in response.subproblem_results
                    for blocker in item.solver_metadata.get("failures", []) or []
                ),
            }
        )
        if feasible:
            raw_status = "FEASIBLE"
        elif "data_or_governance_blocked" in subproblem_failure_classes:
            raw_status = "GOVERNANCE_CONSTRAINT_BLOCKED"
        elif (
            "INFEASIBLE" in statuses
            or "proven_infeasible" in subproblem_failure_classes
        ):
            raw_status = "INFEASIBLE"
        else:
            raw_status = "UNKNOWN"
        classification = InfeasibilityClassifier.classify(
            status_name=raw_status,
            is_feasible=feasible,
            blockers=all_blockers,
        )
        violations = [
            ConstraintViolation.model_validate(item) for item in response.violations
        ]
        validation = ConstraintValidationReport(
            is_feasible=feasible,
            violations=violations,
            checked_constraints=response.checked_constraints,
        )
        return _SolveProbe(
            schedule=response.final_schedule if feasible else None,
            status_name=raw_status,
            classification=classification,
            validation=validation,
            solver_log={
                "backend": "bounded_decomposition",
                "evidence_fingerprint": response.evidence_fingerprint,
                "subproblem_statuses": sorted(statuses),
                "subproblem_failure_classes": sorted(subproblem_failure_classes),
                "blockers": all_blockers,
            },
        )

    def _build_pack(
        self,
        *,
        request: FeasibilityRestorationRequest,
        policy: RecoveryPolicy,
        actions: list[RecoveryAction],
        effective_snapshot: ScheduleSnapshot,
        probe: _SolveProbe,
        optimality_proven: bool,
    ) -> RecoveryPack:
        assert probe.schedule is not None and probe.validation.is_feasible
        all_approved = all(action.approval_status == "approved" for action in actions)
        rank = list(_actions_key(actions))
        pack_id = _fingerprint(
            {
                "snapshot_id": str(request.snapshot.snapshot_id),
                "policy": [policy.policy_id, policy.version],
                "actions": [action.action_id for action in actions],
            },
            prefix="pack",
        )
        certificate = (
            _certificate(
                request=request,
                policy=policy,
                actions=actions,
                approvals=request.approvals,
                effective_snapshot=effective_snapshot,
                schedule=probe.schedule,
                validation=probe.validation,
                solver_status=probe.status_name,
            )
            if all_approved
            else None
        )
        pending_roles = sorted(
            {
                blocker.removeprefix("missing_approval_role:")
                for action in actions
                for blocker in action.approval_blockers
                if blocker.startswith("missing_approval_role:")
            }
        )
        return RecoveryPack(
            pack_id=pack_id,
            status="validated_feasible" if all_approved else "pending_approval",
            actions=actions,
            lexicographic_rank=rank,
            maximum_tier=int(rank[0]),
            total_penalty_cost=sum(action.penalty_cost for action in actions),
            deferred_priority_weight=int(rank[1]),
            solver_status=probe.status_name,
            preview_schedule=probe.schedule,
            executable_schedule=probe.schedule if all_approved else None,
            feasibility_certificate=certificate,
            pending_approval_roles=pending_roles,
            optimality_proven=optimality_proven,
        )

    @staticmethod
    def _response(
        *,
        run_id: str,
        request: FeasibilityRestorationRequest,
        status: str,
        classification: FailureClassification,
        conflict_report: ConflictRefinementReport,
        packs: list[RecoveryPack],
        unavailable_actions: list[RecoveryAction],
        safe_hold: SafeHoldDisposition,
        trials: int,
        started: float,
    ) -> FeasibilityRestorationResponse:
        executable = [item.pack_id for item in packs if item.status == "validated_feasible"]
        review = [item.pack_id for item in packs if item.status == "pending_approval"]
        payload = {
            "run_id": run_id,
            "tenant_id": request.tenant_id,
            "status": status,
            "classification": classification.model_dump(mode="json"),
            "conflicts": [item.conflict_id for item in conflict_report.conflicts],
            "packs": [item.pack_id for item in packs],
            "safe_hold": safe_hold.action_id,
            "trials": trials,
        }
        return FeasibilityRestorationResponse(
            run_id=run_id,
            tenant_id=request.tenant_id,
            status=status,
            classification=classification,
            conflict_report=conflict_report,
            recovery_packs=packs,
            unavailable_actions=unavailable_actions,
            recommended_pack_id=executable[0] if executable else None,
            executable_pack_ids=executable,
            planner_review_pack_ids=review,
            safe_hold=safe_hold,
            search_trials=trials,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            evidence_fingerprint=_fingerprint(payload, prefix="evidence"),
            writeback_allowed=False,
            claim_boundary=_CLAIM_BOUNDARY,
        )


def conservative_default_recovery_policy() -> RecoveryPolicy:
    """Fail-closed fallback for development; production should supply customer policy."""
    return RecoveryPolicy(
        policy_id="system-conservative-default",
        version="1.0",
        customer_owned=False,
        rules=[
            RecoveryActionRule(
                action_type="expand_repair_scope", tier=0, auto_execute=True
            ),
            RecoveryActionRule(
                action_type="release_planning_freeze",
                tier=2,
                penalty_cost=20,
                required_approval_roles=["Planner", "Management"],
                max_uses_per_pack=20,
            ),
            RecoveryActionRule(
                action_type="open_overtime_window",
                tier=3,
                penalty_cost=300,
                required_approval_roles=["Planner", "Production_Manager"],
                max_uses_per_pack=20,
            ),
            RecoveryActionRule(
                action_type="activate_outsourcing",
                tier=3,
                penalty_cost=500,
                required_approval_roles=["Planner", "Procurement"],
                max_uses_per_pack=20,
            ),
            RecoveryActionRule(
                action_type="activate_substitute_material",
                tier=3,
                penalty_cost=400,
                required_approval_roles=["Quality", "Engineering"],
                max_uses_per_pack=20,
            ),
            RecoveryActionRule(
                action_type="relax_operation_deadline",
                tier=4,
                penalty_cost=1000,
                required_approval_roles=["Planner", "Management"],
                max_uses_per_pack=20,
            ),
            RecoveryActionRule(
                action_type="defer_work_order",
                tier=4,
                penalty_cost=5000,
                required_approval_roles=["Management", "Customer_Service"],
                max_uses_per_pack=20,
            ),
            RecoveryActionRule(action_type="safe_hold", tier=0, auto_execute=True),
        ],
    )


def _generate_actions(
    request: FeasibilityRestorationRequest,
    policy: RecoveryPolicy,
) -> _GeneratedActions:
    raw = request.snapshot.raw_data or {}
    rules = {rule.action_type: rule for rule in policy.rules if rule.enabled}
    raw_operations = {
        str(operation["operation_id"]): operation
        for work_order in raw.get("work_orders", []) or []
        for operation in work_order.get("operations", []) or []
        if operation.get("operation_id")
    }
    actions: list[RecoveryAction] = []

    rule = rules.get("release_planning_freeze")
    if rule:
        quality_frozen = {
            str(operation_id)
            for row in raw.get("quality_holds", []) or []
            if str(row.get("status", "held")).lower()
            not in {"released", "cleared", "closed"}
            for operation_id in row.get("blocked_operation_ids", []) or []
        }
        frozen = set(request.frozen_operation_ids) | {
            str(item) for item in raw.get("frozen_operation_ids", []) or []
        }
        for operation_id in sorted(frozen - quality_frozen):
            row = raw_operations.get(operation_id, {})
            status = str(row.get("status", "unknown")).lower()
            blockers = []
            if status not in {"planned", "queued", "released", "scheduled"}:
                blockers.append("operation_state_does_not_prove_not_started")
            if not row.get("source_ref"):
                blockers.append("missing_operation_state_source_ref")
            actions.append(
                _action(
                    request=request,
                    policy=policy,
                    rule=rule,
                    targets={"operation_id": operation_id},
                    description="Release a planning freeze for an operation proven not started.",
                    evidence_refs=_refs(row),
                    evidence_blockers=blockers,
                )
            )

    rule = rules.get("relax_operation_deadline")
    if rule:
        for row in raw.get("operation_deadline_constraints", []) or []:
            if not row.get("relaxable"):
                continue
            blockers = [] if row.get("source_ref") else ["missing_deadline_source_ref"]
            actions.append(
                _action(
                    request=request,
                    policy=policy,
                    rule=rule,
                    targets={
                        "operation_id": str(row.get("operation_id", "")),
                        "row_fingerprint": _row_fingerprint(row),
                    },
                    description="Remove an explicitly relaxable operation deadline boundary.",
                    evidence_refs=_refs(row),
                    evidence_blockers=blockers,
                )
            )

    rule = rules.get("open_overtime_window")
    if rule:
        for row in raw.get("resource_calendar", []) or []:
            if (
                row.get("availability_type", "unavailable") != "unavailable"
                or str(row.get("reason", "")).lower() != "off_shift"
                or not row.get("relaxable")
            ):
                continue
            blockers = [] if row.get("source_ref") else ["missing_calendar_source_ref"]
            actions.append(
                _action(
                    request=request,
                    policy=policy,
                    rule=rule,
                    targets={
                        "resource_id": str(row.get("resource_id", "")),
                        "row_fingerprint": _row_fingerprint(row),
                    },
                    description="Open a governed off-shift calendar window as approved overtime.",
                    evidence_refs=_refs(row),
                    evidence_blockers=blockers,
                )
            )

    approval_sources: tuple[tuple[RecoveryActionType, str, str], ...] = (
        (
            "activate_outsourcing",
            "outsourcing_approvals",
            "Activate a sourced outsourcing option with lead-time and capacity evidence.",
        ),
        (
            "activate_substitute_material",
            "substitute_material_approvals",
            "Activate a substitute material option with quantity and traceability evidence.",
        ),
    )
    for action_type, field_name, description in approval_sources:
        rule = rules.get(action_type)
        if rule is None:
            continue
        for row in raw.get(field_name, []) or []:
            if str(row.get("approval_status", "pending")).lower() == "approved":
                continue
            approval_blockers: list[str] = []
            if not row.get("source_ref"):
                approval_blockers.append(f"missing_{field_name}_source_ref")
            if action_type == "activate_outsourcing" and not (
                row.get("vendor_id")
                and int(row.get("lead_time_minutes", 0) or 0) > 0
                and int(row.get("capacity_per_day", 0) or 0) > 0
            ):
                approval_blockers.append("incomplete_outsourcing_capacity_evidence")
            if action_type == "activate_substitute_material" and float(
                row.get("available_quantity", 0) or 0
            ) < float(row.get("required_quantity", 1) or 1):
                approval_blockers.append("substitute_quantity_is_insufficient")
            actions.append(
                _action(
                    request=request,
                    policy=policy,
                    rule=rule,
                    targets={
                        "operation_ids": [
                            str(item) for item in row.get("operation_ids", []) or []
                        ],
                        "row_fingerprint": _row_fingerprint(row),
                    },
                    description=description,
                    evidence_refs=_refs(row),
                    evidence_blockers=approval_blockers,
                )
            )

    rule = rules.get("defer_work_order")
    if rule:
        raw_work_orders = {
            str(row.get("work_order_id", "")): row
            for row in raw.get("work_orders", []) or []
        }
        for work_order in sorted(
            request.snapshot.work_orders, key=lambda item: (item.priority, item.work_order_id)
        ):
            raw_work_order = raw_work_orders.get(work_order.work_order_id, {})
            raw_ops = [
                raw_operations.get(operation.operation_id, {})
                for operation in work_order.operations
            ]
            statuses = {str(row.get("status", "unknown")).lower() for row in raw_ops}
            blockers = []
            if not statuses or not statuses.issubset(
                {"planned", "queued", "released", "scheduled"}
            ):
                blockers.append("work_order_contains_started_or_unknown_operation_state")
            if not raw_work_order.get("source_ref"):
                blockers.append("missing_work_order_source_ref")
            actions.append(
                _action(
                    request=request,
                    policy=policy,
                    rule=rule,
                    targets={
                        "work_order_id": work_order.work_order_id,
                        "priority_weight": max(1, work_order.priority + 1),
                    },
                    description="Defer an unstarted work order as an explicit service exception.",
                    evidence_refs=_refs(raw_work_order),
                    evidence_blockers=blockers,
                )
            )

    actions.sort(key=_single_action_key)
    action_space_complete = len(actions) <= 64
    actions = actions[:64]
    return _GeneratedActions(
        searchable=[item for item in actions if item.approval_status != "invalid"],
        unavailable=[item for item in actions if item.approval_status == "invalid"],
        action_space_complete=action_space_complete,
    )


def _action(
    *,
    request: FeasibilityRestorationRequest,
    policy: RecoveryPolicy,
    rule: RecoveryActionRule,
    targets: dict[str, Any],
    description: str,
    evidence_refs: list[str],
    evidence_blockers: list[str],
) -> RecoveryAction:
    constraint_family = _ACTION_FAMILY[rule.action_type]
    if constraint_family not in {"schedule_scope", "operational_safety"} and not (
        _CONSTRAINT_REGISTRY.action_is_registered(
            constraint_family, rule.action_type
        )
    ):
        raise ValueError(
            f"unregistered_recovery_action:{constraint_family}:{rule.action_type}"
        )
    action_id = _fingerprint(
        {
            "snapshot_id": str(request.snapshot.snapshot_id),
            "policy": [policy.policy_id, policy.version],
            "action_type": rule.action_type,
            "targets": targets,
        },
        prefix="action",
    )
    status, blockers = _approval_status(
        action_id=action_id,
        policy=policy,
        rule=rule,
        approvals=request.approvals,
        evidence_blockers=evidence_blockers,
    )
    return RecoveryAction(
        action_id=action_id,
        action_type=rule.action_type,
        constraint_family=constraint_family,
        tier=rule.tier,
        penalty_cost=rule.penalty_cost,
        targets=targets,
        description=description,
        required_approval_roles=rule.required_approval_roles,
        approval_status=status,
        approval_blockers=blockers,
        evidence_refs=evidence_refs,
    )


def _approval_status(
    *,
    action_id: str,
    policy: RecoveryPolicy,
    rule: RecoveryActionRule,
    approvals: list[RecoveryApprovalAttestation],
    evidence_blockers: list[str],
) -> tuple[str, list[str]]:
    if evidence_blockers:
        return "invalid", sorted(set(evidence_blockers))
    if rule.auto_execute:
        return "approved", []
    now = datetime.now(tz=timezone.utc)
    matching = [item for item in approvals if item.action_id == action_id]
    invalid: list[str] = []
    valid_roles: set[str] = set()
    for item in matching:
        if item.policy_id != policy.policy_id or item.policy_version != policy.version:
            invalid.append("approval_policy_version_mismatch")
            continue
        if item.expires_at is not None and item.expires_at <= now:
            invalid.append("approval_expired")
            continue
        if not item.approver_id or not item.source_ref:
            invalid.append("approval_provenance_missing")
            continue
        if settings.app.env in {"staging", "production"}:
            verified, reason = RecoveryApprovalPolicy.verify(item)
            if not verified:
                invalid.append(reason or "approval_signature_invalid")
                continue
        valid_roles.add(item.approver_role.casefold())
    missing = [
        role
        for role in rule.required_approval_roles
        if role.casefold() not in valid_roles
    ]
    blockers = [*invalid, *(f"missing_approval_role:{role}" for role in missing)]
    if missing:
        return "pending", sorted(set(blockers))
    if invalid and not matching:
        return "invalid", sorted(set(blockers))
    return "approved", sorted(set(blockers))


def _apply_actions(
    snapshot: ScheduleSnapshot,
    frozen_operation_ids: list[str],
    actions: list[RecoveryAction],
    approvals: list[RecoveryApprovalAttestation],
) -> tuple[ScheduleSnapshot, list[str]]:
    raw = copy.deepcopy(snapshot.raw_data or {})
    frozen = set(frozen_operation_ids) | {
        str(item) for item in raw.get("frozen_operation_ids", []) or []
    }
    deferred_work_orders: set[str] = set()
    for action in actions:
        target = action.targets
        if action.action_type == "release_planning_freeze":
            frozen.discard(str(target.get("operation_id", "")))
        elif action.action_type == "relax_operation_deadline":
            raw["operation_deadline_constraints"] = [
                row
                for row in raw.get("operation_deadline_constraints", []) or []
                if _row_fingerprint(row) != target.get("row_fingerprint")
            ]
        elif action.action_type == "open_overtime_window":
            raw["resource_calendar"] = [
                row
                for row in raw.get("resource_calendar", []) or []
                if _row_fingerprint(row) != target.get("row_fingerprint")
            ]
        elif action.action_type == "activate_outsourcing":
            _activate_approval_row(
                raw,
                "outsourcing_approvals",
                str(target.get("row_fingerprint", "")),
                action,
                approvals,
            )
        elif action.action_type == "activate_substitute_material":
            _activate_approval_row(
                raw,
                "substitute_material_approvals",
                str(target.get("row_fingerprint", "")),
                action,
                approvals,
            )
        elif action.action_type == "defer_work_order":
            deferred_work_orders.add(str(target.get("work_order_id", "")))
    raw["frozen_operation_ids"] = sorted(frozen)
    effective = snapshot.model_copy(update={"raw_data": raw}, deep=True)
    if deferred_work_orders:
        effective = _remove_work_orders(effective, deferred_work_orders)
    return effective, sorted(frozen)


def _activate_approval_row(
    raw: dict[str, Any],
    field_name: str,
    row_fingerprint: str,
    action: RecoveryAction,
    approvals: list[RecoveryApprovalAttestation],
) -> None:
    approvers = sorted(
        {
            item.approver_id
            for item in approvals
            if item.action_id == action.action_id and item.approver_id
        }
    )
    for row in raw.get(field_name, []) or []:
        if _row_fingerprint(row) != row_fingerprint:
            continue
        row["approval_status"] = "approved"
        row["approved_by"] = ",".join(approvers) or "pending_recovery_simulation"


def _remove_work_orders(
    snapshot: ScheduleSnapshot,
    work_order_ids: set[str],
) -> ScheduleSnapshot:
    removed_operations = {
        operation.operation_id
        for work_order in snapshot.work_orders
        if work_order.work_order_id in work_order_ids
        for operation in work_order.operations
    }
    raw = copy.deepcopy(snapshot.raw_data or {})
    raw["work_orders"] = [
        row
        for row in raw.get("work_orders", []) or []
        if str(row.get("work_order_id", "")) not in work_order_ids
    ]
    for field_name in ("operation_release_constraints", "operation_deadline_constraints"):
        raw[field_name] = [
            row
            for row in raw.get(field_name, []) or []
            if str(row.get("operation_id", "")) not in removed_operations
        ]
    list_fields = {
        "material_availability": "operation_ids",
        "substitute_material_approvals": "operation_ids",
        "quality_holds": "blocked_operation_ids",
        "tooling_calendar": "operation_ids",
        "labor_skill_capacity": "operation_ids",
        "outsourcing_approvals": "operation_ids",
        "batch_genealogy": "operation_ids",
        "qms_release_gates": "operation_ids",
    }
    for field_name, key in list_fields.items():
        filtered: list[dict[str, Any]] = []
        for source in raw.get(field_name, []) or []:
            row = dict(source)
            if key in row:
                row[key] = [
                    item
                    for item in row.get(key, []) or []
                    if str(item) not in removed_operations
                ]
                if not row[key]:
                    continue
            filtered.append(row)
        raw[field_name] = filtered
    raw["transport_lanes"] = [
        row
        for row in raw.get("transport_lanes", []) or []
        if str(row.get("predecessor_operation_id", "")) not in removed_operations
        and str(row.get("successor_operation_id", "")) not in removed_operations
    ]
    raw["buffer_flows"] = [
        row
        for row in raw.get("buffer_flows", []) or []
        if str(row.get("predecessor_operation_id", "")) not in removed_operations
        and str(row.get("successor_operation_id", "")) not in removed_operations
    ]
    raw["urgent_order_constraints"] = [
        row
        for row in raw.get("urgent_order_constraints", []) or []
        if str(row.get("work_order_id", "")) not in work_order_ids
    ]
    raw["frozen_operation_ids"] = [
        item
        for item in raw.get("frozen_operation_ids", []) or []
        if str(item) not in removed_operations
    ]
    return snapshot.model_copy(
        update={
            "work_orders": [
                work_order.model_copy(deep=True)
                for work_order in snapshot.work_orders
                if work_order.work_order_id not in work_order_ids
            ],
            "raw_data": raw,
        },
        deep=True,
    )


def _certificate(
    *,
    request: FeasibilityRestorationRequest,
    policy: RecoveryPolicy,
    actions: list[RecoveryAction],
    approvals: list[RecoveryApprovalAttestation],
    effective_snapshot: ScheduleSnapshot,
    schedule: ScheduleDetail,
    validation: ConstraintValidationReport,
    solver_status: str,
) -> FeasibilityCertificate:
    if not validation.is_feasible or validation.violations:
        raise ValueError("cannot_issue_certificate_for_constraint_violating_schedule")
    action_ids = {action.action_id for action in actions}
    source_refs = sorted(
        {
            approval.source_ref
            for approval in approvals
            if approval.action_id in action_ids
        }
    )
    deferred = sorted(
        {
            str(action.targets.get("work_order_id"))
            for action in actions
            if action.action_type == "defer_work_order"
        }
    )
    effective_fingerprint = _fingerprint(
        effective_snapshot.model_dump(mode="json"), prefix="snapshot"
    )
    schedule_fingerprint = _fingerprint(
        schedule.model_dump(mode="json"), prefix="schedule"
    )
    payload = {
        "original_snapshot_id": str(request.snapshot.snapshot_id),
        "effective_snapshot_fingerprint": effective_fingerprint,
        "policy": [policy.policy_id, policy.version],
        "constraint_registry_version": _CONSTRAINT_REGISTRY.version,
        "actions": sorted(action_ids),
        "approval_source_refs": source_refs,
        "deferred_work_order_ids": deferred,
        "checked_hard_constraints": validation.checked_constraints,
        "solver_status": solver_status,
        "schedule_fingerprint": schedule_fingerprint,
    }
    return FeasibilityCertificate(
        original_snapshot_id=str(request.snapshot.snapshot_id),
        effective_snapshot_fingerprint=effective_fingerprint,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        constraint_registry_version=_CONSTRAINT_REGISTRY.version,
        approved_action_ids=sorted(action_ids),
        approval_source_refs=source_refs,
        deferred_work_order_ids=deferred,
        checked_hard_constraints=validation.checked_constraints,
        hard_violation_count=0,
        solver_status=solver_status,
        schedule_fingerprint=schedule_fingerprint,
        certificate_fingerprint=_fingerprint(payload, prefix="certificate"),
        writeback_authorized=False,
    )


def _expansion_action(
    request: FeasibilityRestorationRequest, policy: RecoveryPolicy
) -> RecoveryAction:
    rule = next(
        (
            item
            for item in policy.rules
            if item.action_type == "expand_repair_scope" and item.enabled
        ),
        RecoveryActionRule(
            action_type="expand_repair_scope", tier=0, auto_execute=True
        ),
    )
    return _action(
        request=request,
        policy=policy,
        rule=rule,
        targets={"strategy_type": StrategyType.GLOBAL_RESCHEDULE.value},
        description="Expand from the requested repair neighborhood to global schedule scope.",
        evidence_refs=[],
        evidence_blockers=[],
    )


def _safe_hold(
    request: FeasibilityRestorationRequest, policy: RecoveryPolicy
) -> SafeHoldDisposition:
    affected = sorted(
        {item.operation_id for item in request.impact_report.affected_operations}
    )
    action_id = _fingerprint(
        {
            "snapshot_id": str(request.snapshot.snapshot_id),
            "policy": [policy.policy_id, policy.version],
            "action_type": "safe_hold",
            "affected": affected,
        },
        prefix="action",
    )
    return SafeHoldDisposition(
        action_id=action_id,
        affected_operation_ids=affected,
        reason=(
            "Preserve actual shop-floor state and hold affected dispatches when no "
            "approved, independently validated production schedule exists."
        ),
    )


def _with_frozen_ids(
    snapshot: ScheduleSnapshot, frozen_operation_ids: list[str]
) -> ScheduleSnapshot:
    raw = copy.deepcopy(snapshot.raw_data or {})
    raw["frozen_operation_ids"] = sorted(set(frozen_operation_ids))
    return snapshot.model_copy(update={"raw_data": raw}, deep=True)


def _planning_frozen_incident_ids(
    request: FeasibilityRestorationRequest,
    snapshot: ScheduleSnapshot,
    frozen_operation_ids: list[str],
) -> list[str]:
    raw = snapshot.raw_data or {}
    raw_operations = {
        str(operation["operation_id"]): operation
        for work_order in raw.get("work_orders", []) or []
        for operation in work_order.get("operations", []) or []
        if operation.get("operation_id")
    }
    quality_frozen = {
        str(operation_id)
        for row in raw.get("quality_holds", []) or []
        if str(row.get("status", "held")).lower()
        not in {"released", "cleared", "closed"}
        for operation_id in row.get("blocked_operation_ids", []) or []
    }
    frozen = set(frozen_operation_ids) | {
        str(item) for item in raw.get("frozen_operation_ids", []) or []
    }
    delayed = {
        item.operation_id
        for item in request.impact_report.affected_operations
        if item.estimated_delay_minutes > 0
    }
    return sorted(
        operation_id
        for operation_id in frozen & delayed
        if operation_id not in quality_frozen
        and str(raw_operations.get(operation_id, {}).get("status", "unknown")).lower()
        in {"planned", "queued", "released", "scheduled"}
    )


def _resources(snapshot: ScheduleSnapshot) -> list[Resource]:
    result: list[Resource] = []
    for row in (snapshot.raw_data or {}).get("resources", []) or []:
        resource_id = str(row.get("resource_id", ""))
        if not resource_id:
            continue
        result.append(
            Resource(
                resource_id=resource_id,
                name=str(row.get("name") or resource_id),
                capabilities=[str(item) for item in row.get("capabilities", []) or []],
            )
        )
    return result


def _within_type_limits(
    actions: list[RecoveryAction], policy: RecoveryPolicy
) -> bool:
    limits = {
        rule.action_type: rule.max_uses_per_pack
        for rule in policy.rules
        if rule.enabled
    }
    counts: dict[str, int] = {}
    for action in actions:
        counts[action.action_type] = counts.get(action.action_type, 0) + 1
        if counts[action.action_type] > limits.get(action.action_type, 1):
            return False
    return True


def _single_action_key(action: RecoveryAction) -> tuple[float, ...]:
    return (*_actions_key([action]), float(int(action.action_id[-8:], 16)))


def _state_key(
    state: tuple[int, ...], actions: list[RecoveryAction]
) -> tuple[float, ...]:
    return (*_actions_key([actions[index] for index in state]), *map(float, state))


def _actions_key(actions: list[RecoveryAction]) -> tuple[float, float, float, float]:
    if not actions:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        float(max(action.tier for action in actions)),
        float(
            sum(
                int(action.targets.get("priority_weight", 0) or 0)
                for action in actions
                if action.action_type == "defer_work_order"
            )
        ),
        float(sum(action.penalty_cost for action in actions)),
        float(len(actions)),
    )


def _row_fingerprint(row: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(row, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _fingerprint(payload: Any, *, prefix: str) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()
    return f"{prefix}-{digest[:24]}"


def _refs(row: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(row[key])
            for key in ("source_ref", "certificate_ref", "constraint_id")
            if row.get(key)
        }
    )


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))
