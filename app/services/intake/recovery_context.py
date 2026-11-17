"""Turn an incident into the constraints a recovery plan must respect.

An incident changes three things that the schedule snapshot does not know:

* **When replanning starts.** Work that had already started at the incident
  time is history. It is frozen, except the operation that was running on a
  failed machine, which was interrupted and must run again.
* **What is unavailable.** A failed machine is blocked for its repair time.
* **When material is usable.** A supply disruption moves kit-complete times.

The context expresses these in the row formats the schedulers and validators
already read from ``snapshot.raw_data``, so no solver needs to know what kind
of incident it is recovering from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.models.enums import IncidentType
from app.models.incident import Incident
from app.models.schedule import ScheduleSnapshot
from app.services.agent.incident_parsing import _extract_duration_minutes

SOURCE_REF_PREFIX = "incident"


@dataclass(frozen=True)
class RecoveryContext:
    incident_id: str
    decision_time: datetime
    resource_windows: list[dict] = field(default_factory=list)
    release_rows: list[dict] = field(default_factory=list)
    material_rows: list[dict] = field(default_factory=list)
    frozen_operation_ids: list[str] = field(default_factory=list)
    interrupted_operation_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def windows_by_resource(self) -> dict[str, list[tuple[datetime, datetime]]]:
        windows: dict[str, list[tuple[datetime, datetime]]] = {}
        for row in self.resource_windows:
            windows.setdefault(row["resource_id"], []).append(
                (
                    datetime.fromisoformat(row["window_start"]),
                    datetime.fromisoformat(row["window_end"]),
                )
            )
        return windows

    def material_release_by_operation(self) -> dict[str, datetime | None]:
        """Latest release time per operation; ``None`` when any need is uncovered."""
        release: dict[str, datetime | None] = {}
        for row in self.material_rows:
            short = float(row["available_quantity"]) < float(row["required_quantity"])
            moment = None if short or not row.get("available_at") else row["available_at"]
            moment = datetime.fromisoformat(moment) if isinstance(moment, str) else moment
            for operation_id in row["operation_ids"]:
                if operation_id in release and release[operation_id] is None:
                    continue
                if moment is None:
                    release[operation_id] = None
                else:
                    current = release.get(operation_id)
                    release[operation_id] = moment if current is None else max(current, moment)
        return release


def incident_duration_minutes(incident: Incident) -> int | None:
    """Expected outage length: the payload field first, then the description."""
    payload = incident.raw_payload or {}
    value = payload.get("estimated_duration_minutes")
    try:
        if value is not None and int(float(value)) > 0:
            return int(float(value))
    except (TypeError, ValueError):
        pass
    return _extract_duration_minutes(incident.description or "")


def build_recovery_context(
    incident: Incident,
    snapshot: ScheduleSnapshot,
    *,
    material_rows: list[dict] | None = None,
) -> RecoveryContext | None:
    """Build the context, or ``None`` when the schedule has nothing left to replan."""
    operations = [op for wo in snapshot.work_orders for op in wo.operations]
    decision_time = incident.occurred_at
    if not operations or all(op.end_time <= decision_time for op in operations):
        return None

    notes: list[str] = []
    windows: list[dict] = []
    is_equipment = str(incident.incident_type) == IncidentType.EQUIPMENT_FAILURE.value
    window_end: datetime | None = None
    if is_equipment:
        duration = incident_duration_minutes(incident)
        if duration is None:
            notes.append("repair_time_unknown:no_resource_window")
        else:
            window_end = decision_time + timedelta(minutes=duration)
            windows.append(
                {
                    "resource_id": incident.resource_id,
                    "availability_type": "unavailable",
                    "window_start": decision_time.isoformat(),
                    "window_end": window_end.isoformat(),
                    "source_ref": f"{SOURCE_REF_PREFIX}:{incident.incident_id}",
                }
            )

    frozen: list[str] = []
    interrupted: list[str] = []
    for op in operations:
        if op.start_time >= decision_time:
            continue
        running = op.end_time > decision_time
        on_failed_machine = is_equipment and op.resource_id == incident.resource_id
        if running and on_failed_machine and window_end is not None:
            interrupted.append(op.operation_id)
        else:
            frozen.append(op.operation_id)

    frozen_set = set(frozen)
    release_rows = [
        {
            "operation_id": op.operation_id,
            "release_at": decision_time.isoformat(),
            "source_ref": f"{SOURCE_REF_PREFIX}:{incident.incident_id}",
        }
        for op in operations
        if op.operation_id not in frozen_set
    ]
    return RecoveryContext(
        incident_id=str(incident.incident_id),
        decision_time=decision_time,
        resource_windows=windows,
        release_rows=release_rows,
        material_rows=list(material_rows or []),
        frozen_operation_ids=sorted(frozen),
        interrupted_operation_ids=sorted(interrupted),
        notes=notes,
    )


def apply_recovery_context(
    snapshot: ScheduleSnapshot, context: RecoveryContext
) -> ScheduleSnapshot:
    """Return a copy of ``snapshot`` whose raw data carries the context's rows.

    Rows already present from the source system are kept. Material rows from
    the context replace earlier rows for the same operation and material,
    because the context was computed from newer supply data.
    """
    raw = dict(snapshot.raw_data or {})
    raw["resource_calendar"] = [*(raw.get("resource_calendar") or []), *context.resource_windows]
    raw["operation_release_constraints"] = [
        *(raw.get("operation_release_constraints") or []),
        *context.release_rows,
    ]
    if context.material_rows:
        replaced = {
            (operation_id, row["material_id"])
            for row in context.material_rows
            for operation_id in row["operation_ids"]
        }
        kept = [
            row
            for row in raw.get("material_availability") or []
            if not any(
                (str(operation_id), row.get("material_id")) in replaced
                for operation_id in row.get("operation_ids") or []
            )
        ]
        raw["material_availability"] = [*kept, *context.material_rows]
    raw["recovery_context"] = {
        "incident_id": context.incident_id,
        "decision_time": context.decision_time.isoformat(),
        "frozen_operation_ids": context.frozen_operation_ids,
        "interrupted_operation_ids": context.interrupted_operation_ids,
        "notes": context.notes,
    }
    return snapshot.model_copy(update={"raw_data": raw})
