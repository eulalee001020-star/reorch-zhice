"""Hybrid_Solver core solve engine for the ReOrch system.

Implements the Layer 3 optimization solver that:
1. Accepts SolverPolicyBundle, ImpactReport, ScheduleSnapshot
2. Generates heuristic initial solutions based on selected rules
3. Runs LNS optimization loop with dynamic neighborhood selection
   via SolverPolicyBundle.get_neighborhood_config() each iteration
4. Validates constraints on each candidate
5. Supports 60-second timeout with partial results
6. Supports Solver_Portfolio degradation (primary → fallback → rule)
7. Records SolverChain and SolverMetadata for each CandidatePlan

For MVP, uses heuristic-based schedule variations (time shifts,
resource swaps) rather than full CP-SAT modeling. The architecture
and data flow are production-ready.

Requirements: 4.1–4.16
"""

from __future__ import annotations

import asyncio
import logging
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from app.models.enums import StrategyType
from app.models.impact import ImpactReport
from app.models.schedule import (
    Operation,
    ScheduleDetail,
    ScheduleSnapshot,
    WorkOrder,
)
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    ConstraintViolation,
    SolverChain,
    SolverMetadata,
)
from app.models.strategy import StrategyRecommendation
from app.services.cp_sat_scheduler import CpSatFjspScheduler

if TYPE_CHECKING:
    from app.services.solver_policy_orchestrator import SolverPolicyBundle

logger = logging.getLogger(__name__)

MODULE_VERSION: str = "1.0.0"

# ── Constants ───────────────────────────────────────────────────────
_DEFAULT_TIMEOUT_SECONDS: float = 60.0
_TOP_K: int = 3
_MAX_LNS_ITERATIONS: int = 50
_STAGNATION_LIMIT: int = 10


class HybridSolver:
    """Hybrid optimization solve engine (Req 4.1–4.16).

    Accepts a SolverPolicyBundle (from Solver_Policy_Layer) along with
    ImpactReport and ScheduleSnapshot.  Returns list[CandidatePlan].

    The solver never depends on individual selectors directly — all
    strategy control comes through the bundle (Req 22.2).
    """

    async def solve(
        self,
        bundle: "SolverPolicyBundle",
        impact_report: ImpactReport,
        snapshot: ScheduleSnapshot,
    ) -> list[CandidatePlan]:
        """Generate Top-3 candidate plans within 60 seconds (Req 4.1).

        Flow:
        1. Extract repair_config, rules, solver_chain_config from bundle
        2. Determine affected operations and strategy-specific scope
        3. Try primary solver; on failure degrade per solver_chain_config
        4. Return validated candidates with SolverChain/SolverMetadata
        """
        start_time = time.monotonic()
        timeout = min(
            bundle.repair_config.search_time_budget_seconds,
            bundle.solver_chain_config.max_timeout_seconds,
            _DEFAULT_TIMEOUT_SECONDS,
        )

        strategy_type = self._resolve_strategy_type(bundle.strategy.strategy_type)
        affected_op_ids = [
            op.operation_id for op in impact_report.affected_operations
        ]

        solver_chain_config = bundle.solver_chain_config
        solvers_to_try = [
            solver_chain_config.primary_solver,
            solver_chain_config.fallback_solver,
            solver_chain_config.fallback_rule,
        ]

        candidates: list[CandidatePlan] = []
        degradation_occurred = False
        degradation_reason: str | None = None
        actual_solver_name = solvers_to_try[0]

        for idx, solver_name in enumerate(solvers_to_try):
            actual_solver_name = solver_name
            elapsed = time.monotonic() - start_time
            remaining = timeout - elapsed
            if remaining <= 0:
                break

            try:
                candidates = await self._run_solver(
                    solver_name=solver_name,
                    bundle=bundle,
                    impact_report=impact_report,
                    snapshot=snapshot,
                    strategy_type=strategy_type,
                    affected_op_ids=affected_op_ids,
                    timeout_seconds=remaining,
                    start_time=start_time,
                )
                if candidates:
                    if idx > 0:
                        degradation_occurred = True
                        degradation_reason = (
                            f"Primary solver '{solvers_to_try[0]}' failed; "
                            f"degraded to '{solver_name}'"
                        )
                    break
            except Exception as exc:
                logger.warning(
                    "Solver '%s' failed: %s. Trying next in chain.",
                    solver_name,
                    exc,
                )
                degradation_occurred = True
                degradation_reason = (
                    f"Solver '{solver_name}' raised {type(exc).__name__}: {exc}"
                )
                continue

        solve_time = time.monotonic() - start_time
        timed_out = solve_time >= timeout

        # If no candidates at all → infeasible report (Req 4.9)
        if not candidates:
            return [self._build_infeasible_plan(
                strategy_type=strategy_type,
                solver_name=actual_solver_name,
                bundle=bundle,
                solve_time=solve_time,
                degradation_occurred=degradation_occurred,
                degradation_reason=degradation_reason,
            )]

        # Stamp metadata on each candidate
        for plan in candidates:
            plan.solver_metadata.solve_time_seconds = round(solve_time, 3)
            plan.solver_metadata.degradation_occurred = degradation_occurred
            plan.solver_metadata.degradation_reason = degradation_reason
            if timed_out and plan.feasibility_status == "feasible":
                plan.feasibility_status = "timeout_partial"

        logger.info(
            "HybridSolver.solve completed: %d candidate(s), %.2fs, "
            "timeout=%s, degradation=%s (module v%s)",
            len(candidates),
            solve_time,
            timed_out,
            degradation_occurred,
            MODULE_VERSION,
        )

        return candidates[:_TOP_K]

    # ── Core solver pipeline ────────────────────────────────────────

    async def _run_solver(
        self,
        solver_name: str,
        bundle: "SolverPolicyBundle",
        impact_report: ImpactReport,
        snapshot: ScheduleSnapshot,
        strategy_type: StrategyType,
        affected_op_ids: list[str],
        timeout_seconds: float,
        start_time: float,
    ) -> list[CandidatePlan]:
        """Execute a single solver pass: heuristic init → LNS → validate.

        Returns validated CandidatePlan list (may be empty).
        """
        if self._is_cp_sat_solver(solver_name):
            return await self._run_cp_sat_solver(
                solver_name=solver_name,
                bundle=bundle,
                impact_report=impact_report,
                snapshot=snapshot,
                strategy_type=strategy_type,
                affected_op_ids=affected_op_ids,
                timeout_seconds=timeout_seconds,
            )

        rules = bundle.rules
        repair_config = bundle.repair_config

        # Rule names for SolverChain recording
        rule_names = ", ".join(r.rule_name for r in rules) if rules else "default"

        # 1. Generate heuristic initial solution (Req 4.6)
        initial_schedule = self._generate_initial_solution(
            snapshot=snapshot,
            strategy_type=strategy_type,
            affected_op_ids=affected_op_ids,
            rules=rules,
        )

        # 2. LNS optimization loop (Req 4.6, 4.12)
        best_schedules, iteration_count, objective_trajectory, neighborhood_log = (
            await self._lns_optimize(
                initial_schedule=initial_schedule,
                bundle=bundle,
                impact_report=impact_report,
                snapshot=snapshot,
                strategy_type=strategy_type,
                affected_op_ids=affected_op_ids,
                timeout_seconds=timeout_seconds,
                start_time=start_time,
            )
        )

        # 3. Validate constraints and build CandidatePlans (Req 4.7)
        candidates: list[CandidatePlan] = []
        for schedule in best_schedules:
            report = self._validate_constraints(schedule, snapshot, strategy_type, affected_op_ids)
            feasibility = "feasible" if report.is_feasible else "infeasible"

            chain = SolverChain(
                strategy_type=strategy_type.value if isinstance(strategy_type, StrategyType) else strategy_type,
                rule_selection=rule_names,
                neighborhood_selection=neighborhood_log,
                repair_policy=repair_config.repair_mode.value if hasattr(repair_config.repair_mode, "value") else str(repair_config.repair_mode),
                solver_name=solver_name,
                key_parameters={
                    "timeout_seconds": timeout_seconds,
                    "max_iterations": _MAX_LNS_ITERATIONS,
                    "stagnation_limit": _STAGNATION_LIMIT,
                    "candidate_target": repair_config.candidate_count_target,
                },
                search_budget_seconds=timeout_seconds,
                constraint_validation_result=feasibility,
                stages=[
                    "规则选择",
                    "初解生成",
                    "邻域选择",
                    "LNS修复",
                    "约束校验",
                ],
            )

            metadata = SolverMetadata(
                solve_time_seconds=0.0,  # stamped later
                iteration_count=iteration_count,
                objective_trajectory=objective_trajectory,
            )

            plan = CandidatePlan(
                plan_id=uuid4(),
                strategy_type=strategy_type.value if isinstance(strategy_type, StrategyType) else strategy_type,
                schedule_detail=schedule,
                gantt_version="1.0",
                solver_chain=chain,
                feasibility_status=feasibility,
                solver_metadata=metadata,
                constraint_report=report,
                created_at=datetime.now(tz=timezone.utc),
            )
            candidates.append(plan)

        # Filter to feasible only (unless none are feasible)
        feasible = [c for c in candidates if c.feasibility_status == "feasible"]
        return feasible if feasible else candidates

    async def _run_cp_sat_solver(
        self,
        solver_name: str,
        bundle: "SolverPolicyBundle",
        impact_report: ImpactReport,
        snapshot: ScheduleSnapshot,
        strategy_type: StrategyType,
        affected_op_ids: list[str],
        timeout_seconds: float,
    ) -> list[CandidatePlan]:
        """Run the real OR-Tools CP-SAT FJSP backend.

        The backend produces detailed feasible schedules. HybridSolver wraps
        them into CandidatePlan objects and keeps the existing fallback
        behavior if CP-SAT cannot find a feasible solution.
        """
        rules = bundle.rules
        repair_config = bundle.repair_config
        rule_names = ", ".join(r.rule_name for r in rules) if rules else "default"

        neighborhood_log = "cp_sat_model"
        if bundle.get_neighborhood_config is not None:
            try:
                # Invoke once so the policy layer still records runtime
                # neighborhood intent for CP-SAT/LNS portfolio calls.
                temp_schedule = ScheduleDetail(work_orders=[wo.model_copy(deep=True) for wo in snapshot.work_orders])
                temp_plan = CandidatePlan(
                    plan_id=uuid4(),
                    strategy_type=strategy_type.value,
                    schedule_detail=temp_schedule,
                    gantt_version="1.0",
                    solver_chain=SolverChain(
                        strategy_type=strategy_type.value,
                        rule_selection=rule_names,
                        neighborhood_selection="pending",
                        repair_policy=str(repair_config.repair_mode),
                        solver_name=solver_name,
                        key_parameters={},
                        search_budget_seconds=timeout_seconds,
                        constraint_validation_result="pending",
                    ),
                    feasibility_status="pending",
                    solver_metadata=SolverMetadata(
                        solve_time_seconds=0.0,
                        iteration_count=0,
                    ),
                    constraint_report=ConstraintValidationReport(
                        is_feasible=True,
                        violations=[],
                        checked_constraints=[],
                    ),
                )
                configs = await bundle.get_neighborhood_config(
                    temp_plan,
                    affected_op_ids,
                    0,
                    timeout_seconds,
                    bundle.strategy,
                    0.5,
                )
                if configs:
                    neighborhood_log = ", ".join(
                        c.neighborhood_type.value
                        if hasattr(c.neighborhood_type, "value")
                        else str(c.neighborhood_type)
                        for c in configs
                    )
            except Exception as exc:
                logger.warning("CP-SAT neighborhood policy callback failed: %s", exc)

        scheduler = CpSatFjspScheduler()
        candidate_target = max(1, repair_config.candidate_count_target)
        per_candidate_timeout = max(0.1, timeout_seconds / min(candidate_target, 3))
        candidates: list[CandidatePlan] = []

        for candidate_index in range(min(candidate_target, _TOP_K)):
            result = scheduler.solve(
                snapshot=snapshot,
                impact_report=impact_report,
                strategy_type=strategy_type,
                affected_op_ids=affected_op_ids,
                frozen_operation_ids=repair_config.frozen_operation_ids,
                timeout_seconds=per_candidate_timeout,
                candidate_index=candidate_index,
            )
            if not result.is_feasible or result.schedule_detail is None:
                if candidate_index == 0:
                    logger.info("CP-SAT backend did not find feasible plan: %s", result.status_name)
                break

            report = self._validate_constraints(
                result.schedule_detail,
                snapshot,
                strategy_type,
                affected_op_ids,
            )
            feasibility = "feasible" if report.is_feasible else "infeasible"
            repair_mode = repair_config.repair_mode
            repair_mode_value = repair_mode.value if hasattr(repair_mode, "value") else str(repair_mode)
            chain = SolverChain(
                strategy_type=strategy_type.value,
                rule_selection=rule_names,
                neighborhood_selection=neighborhood_log,
                repair_policy=repair_mode_value,
                solver_name=solver_name,
                key_parameters={
                    "backend": "ortools_cp_sat",
                    "timeout_seconds": per_candidate_timeout,
                    "candidate_index": candidate_index,
                    "objective_value": result.objective_value,
                    "cp_sat_status": result.status_name,
                    "branches": result.branches,
                    "conflicts": result.conflicts,
                    "variable_operation_ids": result.variable_operation_ids,
                    **result.solver_log,
                },
                search_budget_seconds=per_candidate_timeout,
                constraint_validation_result=feasibility,
                stages=[
                    "规则选择",
                    "CP-SAT建模",
                    "可选设备选择",
                    "资源NoOverlap",
                    "前后序约束",
                    "约束校验",
                ],
            )
            metadata = SolverMetadata(
                solve_time_seconds=result.wall_time_seconds,
                iteration_count=result.branches,
                objective_trajectory=[
                    result.objective_value
                    if result.objective_value is not None
                    else 0.0
                ],
            )
            candidates.append(
                CandidatePlan(
                    plan_id=uuid4(),
                    strategy_type=strategy_type.value,
                    schedule_detail=result.schedule_detail,
                    gantt_version="1.0",
                    solver_chain=chain,
                    feasibility_status=feasibility,
                    solver_metadata=metadata,
                    constraint_report=report,
                    created_at=datetime.now(tz=timezone.utc),
                )
            )

        feasible = [c for c in candidates if c.feasibility_status == "feasible"]
        return feasible if feasible else candidates

    # ── Heuristic initial solution ──────────────────────────────────

    def _generate_initial_solution(
        self,
        snapshot: ScheduleSnapshot,
        strategy_type: StrategyType,
        affected_op_ids: list[str],
        rules: list,
    ) -> ScheduleDetail:
        """Generate a heuristic initial solution (Req 4.3, 4.4, 4.5, 4.6).

        Strategy-specific behaviour:
        - WAIT_AND_REPAIR: shift affected ops forward by estimated delay
        - LOCAL_REPAIR: re-sequence affected + downstream ops
        - GLOBAL_RESCHEDULE: re-sequence all ops
        """
        affected_set = set(affected_op_ids)

        # Deep-copy work orders from snapshot
        new_work_orders: list[WorkOrder] = []
        for wo in snapshot.work_orders:
            new_ops: list[Operation] = []
            for op in wo.operations:
                new_op = op.model_copy(deep=True)
                if op.operation_id in affected_set:
                    new_op.is_affected = True
                    new_op.is_adjusted = True
                    # Apply heuristic: shift start/end by a small delta
                    from datetime import timedelta
                    shift = timedelta(minutes=15)
                    if strategy_type == StrategyType.WAIT_AND_REPAIR:
                        shift = timedelta(minutes=30)
                    elif strategy_type == StrategyType.GLOBAL_RESCHEDULE:
                        shift = timedelta(minutes=10)
                    new_op.start_time = op.start_time + shift
                    new_op.end_time = op.end_time + shift
                elif strategy_type == StrategyType.LOCAL_REPAIR:
                    # Shift downstream ops (those with predecessors in affected set)
                    if affected_set & set(op.predecessor_ids):
                        from datetime import timedelta
                        new_op.is_adjusted = True
                        new_op.start_time = op.start_time + timedelta(minutes=10)
                        new_op.end_time = op.end_time + timedelta(minutes=10)
                elif strategy_type == StrategyType.GLOBAL_RESCHEDULE:
                    # Global: small perturbation on all ops
                    from datetime import timedelta
                    new_op.is_adjusted = True
                    new_op.start_time = op.start_time + timedelta(minutes=5)
                    new_op.end_time = op.end_time + timedelta(minutes=5)
                new_ops.append(new_op)

            new_wo = wo.model_copy(deep=True)
            new_wo.operations = new_ops
            new_work_orders.append(new_wo)

        return ScheduleDetail(work_orders=new_work_orders)

    # ── LNS optimization loop ───────────────────────────────────────

    async def _lns_optimize(
        self,
        initial_schedule: ScheduleDetail,
        bundle: "SolverPolicyBundle",
        impact_report: ImpactReport,
        snapshot: ScheduleSnapshot,
        strategy_type: StrategyType,
        affected_op_ids: list[str],
        timeout_seconds: float,
        start_time: float,
    ) -> tuple[list[ScheduleDetail], int, list[float], str]:
        """Run LNS optimization loop with dynamic neighborhood selection.

        Calls bundle.get_neighborhood_config() each iteration (Req 4.12).
        Returns (best_schedules, iteration_count, objective_trajectory, neighborhood_log).
        """
        candidate_target = bundle.repair_config.candidate_count_target
        best_schedules: list[ScheduleDetail] = [initial_schedule]
        best_objective = self._evaluate_objective(initial_schedule)
        objective_trajectory: list[float] = [best_objective]
        neighborhood_types_used: list[str] = []
        stagnation_count = 0
        iteration = 0

        for iteration in range(1, _MAX_LNS_ITERATIONS + 1):
            elapsed = time.monotonic() - start_time
            remaining = timeout_seconds - elapsed
            if remaining <= 0:
                logger.info("LNS timeout at iteration %d", iteration)
                break

            # Dynamic neighborhood selection via bundle callback (Req 4.12)
            neighborhood_configs = []
            if bundle.get_neighborhood_config is not None:
                try:
                    # Build a temporary CandidatePlan for the callback
                    temp_plan = CandidatePlan(
                        plan_id=uuid4(),
                        strategy_type=strategy_type.value if isinstance(strategy_type, StrategyType) else strategy_type,
                        schedule_detail=best_schedules[0],
                        gantt_version="1.0",
                        solver_chain=SolverChain(
                            strategy_type=strategy_type.value if isinstance(strategy_type, StrategyType) else strategy_type,
                            rule_selection="",
                            neighborhood_selection="",
                            repair_policy="",
                            solver_name="",
                            key_parameters={},
                            search_budget_seconds=remaining,
                            constraint_validation_result="pending",
                        ),
                        feasibility_status="pending",
                        solver_metadata=SolverMetadata(
                            solve_time_seconds=0.0,
                            iteration_count=iteration,
                        ),
                        constraint_report=ConstraintValidationReport(
                            is_feasible=True,
                            violations=[],
                            checked_constraints=[],
                        ),
                    )

                    perturbation = 0.5
                    if hasattr(bundle.repair_config, "allowed_perturbation_scope"):
                        scope_len = len(bundle.repair_config.allowed_perturbation_scope)
                        perturbation = min(1.0, scope_len / max(len(affected_op_ids), 1))

                    neighborhood_configs = await bundle.get_neighborhood_config(
                        temp_plan,
                        affected_op_ids,
                        stagnation_count,
                        remaining,
                        bundle.strategy,
                        perturbation,
                    )
                except Exception as exc:
                    logger.warning("Neighborhood callback failed: %s", exc)

            # Record which neighborhoods were used
            for nc in neighborhood_configs:
                nh_type = nc.neighborhood_type
                nh_val = nh_type.value if hasattr(nh_type, "value") else str(nh_type)
                if nh_val not in neighborhood_types_used:
                    neighborhood_types_used.append(nh_val)

            # Apply neighborhood perturbation to generate a new schedule
            new_schedule = self._apply_neighborhood(
                current=best_schedules[0],
                neighborhood_configs=neighborhood_configs,
                affected_op_ids=affected_op_ids,
                strategy_type=strategy_type,
                iteration=iteration,
            )

            new_objective = self._evaluate_objective(new_schedule)
            objective_trajectory.append(new_objective)

            if new_objective < best_objective:
                best_objective = new_objective
                best_schedules.insert(0, new_schedule)
                stagnation_count = 0
                # Keep up to candidate_target diverse schedules
                if len(best_schedules) > candidate_target:
                    best_schedules = best_schedules[:candidate_target]
            else:
                stagnation_count += 1
                # Still collect diverse solutions
                if len(best_schedules) < candidate_target:
                    best_schedules.append(new_schedule)

            if stagnation_count >= _STAGNATION_LIMIT:
                logger.info(
                    "LNS stagnation limit reached at iteration %d", iteration
                )
                break

            # Yield control to event loop
            await asyncio.sleep(0)

        neighborhood_log = ", ".join(neighborhood_types_used) if neighborhood_types_used else "default"

        return best_schedules[:candidate_target], iteration, objective_trajectory, neighborhood_log

    # ── Neighborhood application ────────────────────────────────────

    def _apply_neighborhood(
        self,
        current: ScheduleDetail,
        neighborhood_configs: list,
        affected_op_ids: list[str],
        strategy_type: StrategyType,
        iteration: int,
    ) -> ScheduleDetail:
        """Apply neighborhood perturbation to produce a new schedule variant.

        Uses the neighborhood configs to decide perturbation type and scope.
        For MVP, applies heuristic time shifts and resource swaps.
        """
        from datetime import timedelta

        affected_set = set(affected_op_ids)
        new_work_orders: list[WorkOrder] = []

        # Determine shift magnitude from neighborhood intensity
        base_shift_minutes = 5
        if neighborhood_configs:
            avg_intensity = sum(
                nc.intensity for nc in neighborhood_configs
            ) / len(neighborhood_configs)
            base_shift_minutes = max(1, int(avg_intensity * 20))

        # Vary shift by iteration to produce diverse solutions
        shift_minutes = base_shift_minutes + (iteration % 5) - 2
        shift = timedelta(minutes=shift_minutes)

        for wo in current.work_orders:
            new_ops: list[Operation] = []
            for op in wo.operations:
                new_op = op.model_copy(deep=True)

                should_perturb = False
                if strategy_type == StrategyType.GLOBAL_RESCHEDULE:
                    should_perturb = True
                elif strategy_type == StrategyType.LOCAL_REPAIR:
                    should_perturb = (
                        op.operation_id in affected_set
                        or bool(affected_set & set(op.predecessor_ids))
                    )
                elif strategy_type == StrategyType.WAIT_AND_REPAIR:
                    should_perturb = op.operation_id in affected_set

                if should_perturb:
                    new_op.is_adjusted = True
                    # Alternate between forward and backward shifts
                    if iteration % 2 == 0:
                        new_op.start_time = op.start_time + shift
                        new_op.end_time = op.end_time + shift
                    else:
                        new_op.start_time = op.start_time - timedelta(minutes=max(1, shift_minutes // 2))
                        new_op.end_time = op.end_time - timedelta(minutes=max(1, shift_minutes // 2))

                new_ops.append(new_op)

            new_wo = wo.model_copy(deep=True)
            new_wo.operations = new_ops
            new_work_orders.append(new_wo)

        return ScheduleDetail(work_orders=new_work_orders)

    # ── Objective evaluation ────────────────────────────────────────

    @staticmethod
    def _evaluate_objective(schedule: ScheduleDetail) -> float:
        """Compute a simple objective score (lower is better).

        For MVP, uses total adjusted-operation time shift as proxy.
        """
        total_shift = 0.0
        for wo in schedule.work_orders:
            for op in wo.operations:
                if op.is_adjusted:
                    # Penalize large time shifts
                    duration = (op.end_time - op.start_time).total_seconds()
                    total_shift += abs(duration)
        return total_shift

    # ── Constraint validation ───────────────────────────────────────

    def _validate_constraints(
        self,
        schedule: ScheduleDetail,
        snapshot: ScheduleSnapshot,
        strategy_type: StrategyType,
        affected_op_ids: list[str],
    ) -> ConstraintValidationReport:
        """Validate hard constraints on a schedule (Req 4.7, 20.1–20.5).

        Checks:
        1. Process order constraints (predecessor end <= successor start)
        2. Resource mutual exclusion (no overlapping ops on same resource)
        3. Local-repair invariance (unaffected ops unchanged)
        """
        violations: list[ConstraintViolation] = []
        checked: list[str] = []

        # Build operation lookup
        op_map: dict[str, Operation] = {}
        for wo in schedule.work_orders:
            for op in wo.operations:
                op_map[op.operation_id] = op

        # 1. Process order constraint (Req 20.2)
        checked.append("process_order")
        for wo in schedule.work_orders:
            for op in wo.operations:
                for pred_id in op.predecessor_ids:
                    pred = op_map.get(pred_id)
                    if pred and pred.end_time > op.start_time:
                        violations.append(ConstraintViolation(
                            constraint_type="process_order",
                            operation_id=op.operation_id,
                            resource_id=op.resource_id,
                            detail=(
                                f"Predecessor '{pred_id}' ends at {pred.end_time} "
                                f"but successor '{op.operation_id}' starts at {op.start_time}"
                            ),
                        ))

        # 2. Resource mutual exclusion (Req 20.3)
        checked.append("resource_mutual_exclusion")
        resource_ops: dict[str, list[Operation]] = {}
        for wo in schedule.work_orders:
            for op in wo.operations:
                resource_ops.setdefault(op.resource_id, []).append(op)

        for resource_id, ops in resource_ops.items():
            sorted_ops = sorted(ops, key=lambda o: o.start_time)
            for i in range(len(sorted_ops) - 1):
                if sorted_ops[i].end_time > sorted_ops[i + 1].start_time:
                    violations.append(ConstraintViolation(
                        constraint_type="resource_mutual_exclusion",
                        operation_id=sorted_ops[i + 1].operation_id,
                        resource_id=resource_id,
                        detail=(
                            f"Operation '{sorted_ops[i].operation_id}' on resource "
                            f"'{resource_id}' ends at {sorted_ops[i].end_time} "
                            f"overlapping with '{sorted_ops[i + 1].operation_id}' "
                            f"starting at {sorted_ops[i + 1].start_time}"
                        ),
                    ))

        # 3. Local-repair invariance (Req 20.5)
        affected_set = set(affected_op_ids)
        if strategy_type == StrategyType.LOCAL_REPAIR:
            checked.append("local_repair_invariance")
            snapshot_op_map: dict[str, Operation] = {}
            for wo in snapshot.work_orders:
                for op in wo.operations:
                    snapshot_op_map[op.operation_id] = op

            for op_id, op in op_map.items():
                if op_id not in affected_set and not op.is_adjusted:
                    snap_op = snapshot_op_map.get(op_id)
                    if snap_op:
                        if op.start_time != snap_op.start_time or op.end_time != snap_op.end_time:
                            violations.append(ConstraintViolation(
                                constraint_type="local_repair_invariance",
                                operation_id=op_id,
                                resource_id=op.resource_id,
                                detail=(
                                    f"Unaffected operation '{op_id}' was modified: "
                                    f"start {snap_op.start_time}→{op.start_time}, "
                                    f"end {snap_op.end_time}→{op.end_time}"
                                ),
                            ))

        return ConstraintValidationReport(
            is_feasible=len(violations) == 0,
            violations=violations,
            checked_constraints=checked,
        )

    # ── Infeasible plan builder ─────────────────────────────────────

    def _build_infeasible_plan(
        self,
        strategy_type: StrategyType,
        solver_name: str,
        bundle: "SolverPolicyBundle",
        solve_time: float,
        degradation_occurred: bool,
        degradation_reason: str | None,
    ) -> CandidatePlan:
        """Build an infeasible report plan when no solution found (Req 4.9)."""
        st_val = strategy_type.value if isinstance(strategy_type, StrategyType) else strategy_type
        repair_mode = bundle.repair_config.repair_mode
        rm_val = repair_mode.value if hasattr(repair_mode, "value") else str(repair_mode)

        chain = SolverChain(
            strategy_type=st_val,
            rule_selection="none",
            neighborhood_selection="none",
            repair_policy=rm_val,
            solver_name=solver_name,
            key_parameters={"degradation_occurred": degradation_occurred},
            search_budget_seconds=bundle.repair_config.search_time_budget_seconds,
            constraint_validation_result="infeasible",
            stages=["规则选择", "初解生成", "求解失败"],
        )

        metadata = SolverMetadata(
            solve_time_seconds=round(solve_time, 3),
            iteration_count=0,
            objective_trajectory=[],
            degradation_occurred=degradation_occurred,
            degradation_reason=degradation_reason,
        )

        report = ConstraintValidationReport(
            is_feasible=False,
            violations=[
                ConstraintViolation(
                    constraint_type="solver_infeasibility",
                    operation_id="*",
                    resource_id=None,
                    detail=(
                        "No feasible solution found within time budget. "
                        f"Degradation: {degradation_reason or 'none'}"
                    ),
                )
            ],
            checked_constraints=["solver_feasibility"],
        )

        return CandidatePlan(
            plan_id=uuid4(),
            strategy_type=st_val,
            schedule_detail=ScheduleDetail(),
            gantt_version="1.0",
            solver_chain=chain,
            feasibility_status="infeasible",
            solver_metadata=metadata,
            constraint_report=report,
            created_at=datetime.now(tz=timezone.utc),
        )

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _resolve_strategy_type(value) -> StrategyType:
        """Safely resolve a strategy type value."""
        if isinstance(value, StrategyType):
            return value
        try:
            return StrategyType(value)
        except (ValueError, KeyError):
            return StrategyType.LOCAL_REPAIR

    @staticmethod
    def _is_cp_sat_solver(solver_name: str) -> bool:
        normalized = solver_name.lower().replace("-", "_")
        return "cp_sat" in normalized or "cpsat" in normalized or "ortools" in normalized
