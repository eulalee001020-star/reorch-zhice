"""Prepare everything a recovery needs from an incident and the data on hand.

One entry point, :func:`prepare_recovery`, is used by impact analysis, solving
and confirmation so that all three see the same facts:

* the recovery context (decision time, blocked machine, frozen history);
* material release times from a kit check, when supply data is available;
* for a supply incident, the kit check after the event has been applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.models.enums import IncidentType
from app.models.incident import Incident
from app.models.schedule import Operation, ScheduleDetail, ScheduleSnapshot, WorkOrder
from app.models.solver import CandidatePlan, SolverChain, SolverMetadata
from app.models.supply import MaterialImpact, MaterialShortageEvent, SupplySnapshot
from app.services.constraints.operational_constraint_validator import (
    OperationalConstraintValidator,
)
from app.services.intake.recovery_context import (
    RecoveryContext,
    apply_recovery_context,
    build_recovery_context,
)
from app.services.intake.right_shift import right_shift
from app.services.supply.kitting import check_kits, material_availability_rows
from app.services.supply.shortage import assess

MATERIAL_OPTION_WAIT = "wait_for_supply"
MATERIAL_OPTION_SUBSTITUTE = "approved_substitute"


@dataclass(frozen=True)
class PreparedRecovery:
    context: RecoveryContext | None
    snapshot: ScheduleSnapshot
    material_impact: MaterialImpact | None = None
    material_option: str | None = None

    @property
    def frozen_operation_ids(self) -> list[str]:
        return self.context.frozen_operation_ids if self.context else []


def is_material_incident(incident: Incident) -> bool:
    return str(incident.incident_type) == IncidentType.MATERIAL_SHORTAGE.value


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def material_event_from_incident(incident: Incident) -> MaterialShortageEvent:
    """Read the supply event from a material incident.

    ``resource_id`` carries the item. The rest comes from ``raw_payload``:
    ``kind``, ``order_id``, ``line_id``, ``new_promised_at`` and
    ``short_quantity``.
    """
    payload = incident.raw_payload or {}
    short = payload.get("short_quantity")
    return MaterialShortageEvent(
        item_id=str(payload.get("item_id") or incident.resource_id),
        kind=payload.get("kind") or "eta_slip",
        order_id=payload.get("order_id") or None,
        line_id=payload.get("line_id") or None,
        new_promised_at=_parse_datetime(payload.get("new_promised_at")),
        short_quantity=float(short) if short not in (None, "") else None,
    )


def prepare_recovery(
    incident: Incident,
    snapshot: ScheduleSnapshot,
    supply: SupplySnapshot | None,
    *,
    allow_substitutes: bool = False,
) -> PreparedRecovery:
    """Build the context and the snapshot the solvers should plan against.

    Without a context (nothing left to replan) the original snapshot is
    returned unchanged and callers fall back to their legacy behaviour.
    """
    material_rows: list[dict] | None = None
    material_impact: MaterialImpact | None = None
    material_option: str | None = None
    reference = incident.occurred_at

    if supply is not None:
        effective_supply = supply
        if is_material_incident(incident):
            event = material_event_from_incident(incident)
            material_impact, effective_supply = assess(
                supply, snapshot, event, reference_time=reference
            )
            material_option = (
                MATERIAL_OPTION_SUBSTITUTE if allow_substitutes else MATERIAL_OPTION_WAIT
            )
        kit = check_kits(
            effective_supply,
            snapshot,
            reference_time=reference,
            allow_substitutes=allow_substitutes,
        )
        material_rows = material_availability_rows(kit)

    context = build_recovery_context(incident, snapshot, material_rows=material_rows)
    if context is None:
        return PreparedRecovery(context=None, snapshot=snapshot)
    return PreparedRecovery(
        context=context,
        snapshot=apply_recovery_context(snapshot, context),
        material_impact=material_impact,
        material_option=material_option,
    )


BASELINE_SOLVER_NAME = "right_shift_baseline"


def baseline_candidate(prepared: PreparedRecovery) -> CandidatePlan | None:
    """The do-nothing plan: every operation keeps its machine and only moves later.

    It is the reference a re-plan has to beat. It is returned only when it
    passes the same independent validation as any other candidate; with a
    material shortage that has no date there is no such plan.
    """
    context = prepared.context
    if context is None:
        return None
    snapshot = prepared.snapshot
    shifted = right_shift(
        snapshot,
        decision_time=context.decision_time,
        resource_windows=context.windows_by_resource(),
        material_release=context.material_release_by_operation(),
        frozen_operation_ids=set(context.frozen_operation_ids),
    )
    work_orders: list[WorkOrder] = []
    moved = 0
    for work_order in snapshot.work_orders:
        operations: list[Operation] = []
        for operation in work_order.operations:
            item = shifted[operation.operation_id]
            changed = item.new_start != operation.start_time
            moved += changed
            operations.append(
                operation.model_copy(
                    update={
                        "start_time": item.new_start,
                        "end_time": item.new_end,
                        "is_affected": item.is_direct,
                        "is_adjusted": changed,
                    }
                )
            )
        work_orders.append(work_order.model_copy(update={"operations": operations}))
    schedule = ScheduleDetail(work_orders=work_orders)
    report = OperationalConstraintValidator().validate(
        schedule, snapshot, frozen_operation_ids=context.frozen_operation_ids
    )
    if not report.is_feasible:
        return None
    return CandidatePlan(
        plan_id=uuid4(),
        strategy_type="wait_and_repair",
        schedule_detail=schedule,
        gantt_version="1.0",
        solver_chain=SolverChain(
            strategy_type="wait_and_repair",
            rule_selection="keep_machine_and_sequence",
            neighborhood_selection="none",
            repair_policy="right_shift",
            solver_name=BASELINE_SOLVER_NAME,
            key_parameters={
                "decision_time": context.decision_time.isoformat(),
                "moved_operations": moved,
                "role": "reference",
            },
            search_budget_seconds=0.0,
            constraint_validation_result="feasible",
            stages=["只顺延不调整", "独立全量约束校验"],
        ),
        feasibility_status="feasible",
        solver_metadata=SolverMetadata(solve_time_seconds=0.0, iteration_count=0),
        constraint_report=report,
        created_at=datetime.now(tz=UTC),
    )
