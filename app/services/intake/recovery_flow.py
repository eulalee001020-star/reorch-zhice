"""Impact analysis and solving that respect an incident's physical facts.

The REST routes and the agent workflow both go through these two functions,
so a recovery looks the same whichever way it is started.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.enums import StrategyType
from app.models.impact import ImpactReport
from app.models.incident import Incident
from app.models.schedule import ScheduleSnapshot
from app.models.solver import CandidatePlan
from app.models.supply import SupplySnapshot
from app.services.intake.impact_analysis_engine import ImpactAnalysisEngine
from app.services.intake.recovery_context import incident_duration_minutes
from app.services.intake.recovery_planning import (
    MATERIAL_OPTION_SUBSTITUTE,
    PreparedRecovery,
    baseline_candidate,
    is_material_incident,
    prepare_recovery,
)

if TYPE_CHECKING:
    from app.services.solver.hybrid_solver import HybridSolver
    from app.services.solver.solver_policy_orchestrator import SolverPolicyBundle


def _current_supply() -> SupplySnapshot | None:
    from app.api.supply import current_supply

    return current_supply()


def prepare_for_incident(
    incident: Incident,
    snapshot: ScheduleSnapshot,
    *,
    allow_substitutes: bool = False,
) -> PreparedRecovery:
    """Recovery context and planning snapshot, using the supply data on hand."""
    return prepare_recovery(
        incident, snapshot, _current_supply(), allow_substitutes=allow_substitutes
    )


DEFAULT_WAIT_MINUTES = 60.0


def expected_wait_minutes(incident: Incident, impact_report: ImpactReport | None) -> float:
    """How long waiting would take, for the wait-or-replan decision.

    A machine failure waits for the repair. Any other incident waits as long
    as its most delayed directly affected operation. Without either figure
    the long-standing default of one hour is used.
    """
    duration = incident_duration_minutes(incident)
    if duration is not None:
        return float(duration)
    if impact_report is not None:
        direct = [
            item.estimated_delay_minutes
            for item in impact_report.affected_operations
            if item.is_direct
        ]
        if direct and max(direct) > 0:
            return float(max(direct))
    return DEFAULT_WAIT_MINUTES


async def analyze_incident_impact(
    incident: Incident, snapshot: ScheduleSnapshot | None
) -> ImpactReport:
    """Impact against the right-shift baseline when the facts are known.

    Falls back to the engine's legacy estimate when there is no schedule or
    nothing left to replan.
    """
    engine = ImpactAnalysisEngine()
    if snapshot is None or not snapshot.work_orders:
        return await engine.analyze(incident, snapshot)
    prepared = prepare_for_incident(incident, snapshot)
    if prepared.context is None:
        return await engine.analyze(incident, snapshot)
    return await engine.analyze_recovery(incident, snapshot, prepared.context)


async def solve_with_recovery(
    *,
    incident: Incident,
    snapshot: ScheduleSnapshot,
    impact_report: ImpactReport,
    bundle: SolverPolicyBundle,
    solver: HybridSolver,
) -> list[CandidatePlan]:
    """Solve on the snapshot that carries the incident's constraints.

    With a recovery context the solver gets the blocked machine window, the
    frozen history and material release times as explicit constraints, so the
    per-operation delay estimates are cleared: they describe waiting, and a
    plan that moves work to another machine should not inherit them.

    A supply incident with an approved substitute is solved twice, once
    waiting for the supply and once using the substitute, so the planner can
    compare the two. The do-nothing plan is kept as the last candidate: it is
    the reference a re-plan has to beat.
    """
    base_frozen = list(bundle.repair_config.frozen_operation_ids)
    prepared = prepare_for_incident(incident, snapshot)
    if prepared.context is None:
        return await solver.solve(bundle=bundle, impact_report=impact_report, snapshot=snapshot)

    # Waiting is exactly the right-shift baseline; no search is needed.
    if bundle.strategy.strategy_type in (StrategyType.WAIT_AND_REPAIR, "wait_and_repair"):
        waiting = baseline_candidate(prepared)
        if waiting is not None:
            return [waiting]

    variants = [prepared]
    if (
        is_material_incident(incident)
        and prepared.material_impact is not None
        and prepared.material_impact.approved_substitutes
    ):
        with_substitute = prepare_for_incident(incident, snapshot, allow_substitutes=True)
        if (
            with_substitute.context is not None
            and with_substitute.context.material_rows != prepared.context.material_rows
        ):
            variants.append(with_substitute)

    solver_impact = impact_report.model_copy(
        update={
            "affected_operations": [
                item.model_copy(update={"estimated_delay_minutes": 0.0})
                for item in impact_report.affected_operations
            ]
        }
    )
    per_variant: list[list[CandidatePlan]] = []
    try:
        for variant in variants:
            bundle.repair_config.frozen_operation_ids = sorted(
                set(base_frozen) | set(variant.frozen_operation_ids)
            )
            plans = await solver.solve(
                bundle=bundle, impact_report=solver_impact, snapshot=variant.snapshot
            )
            for plan in plans:
                parameters = plan.solver_chain.key_parameters
                parameters["decision_time"] = variant.context.decision_time.isoformat()
                parameters["frozen_history_operations"] = len(variant.frozen_operation_ids)
                if variant.material_option:
                    parameters["material_option"] = variant.material_option
                    if variant.material_option == MATERIAL_OPTION_SUBSTITUTE:
                        plan.solver_chain.stages.append("已批准替代料")
            per_variant.append(plans)
    finally:
        bundle.repair_config.frozen_operation_ids = base_frozen

    baseline = baseline_candidate(prepared)
    if baseline is not None and prepared.material_option:
        baseline.solver_chain.key_parameters["material_option"] = prepared.material_option

    if len(per_variant) == 1:
        merged = [plan for plan in per_variant[0] if plan.feasibility_status == "feasible"]
        merged = merged or per_variant[0]
    else:
        # Interleave so that both material options are represented.
        merged = []
        for rank in range(3):
            for plans in per_variant:
                if rank < len(plans):
                    merged.append(plans[rank])
    if baseline is None:
        return merged[:3]
    return [*merged[:2], baseline]
