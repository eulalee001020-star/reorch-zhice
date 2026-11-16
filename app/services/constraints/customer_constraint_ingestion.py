"""Load customer non-equipment constraint rows into solver-ready raw data."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.models.customer_constraints import (
    BatchGenealogyRow,
    BufferFlowRow,
    CustomerConstraintPack,
    LaborSkillCapacityRow,
    MaterialAvailabilityRow,
    OutsourcingApprovalRow,
    QmsReleaseGateRow,
    QualityHoldRow,
    SubstituteMaterialApprovalRow,
    ToolingCalendarRow,
    TransportLaneRow,
    UrgentOrderConstraintRow,
)
from app.models.schedule import ScheduleSnapshot


class CustomerConstraintIngestionService:
    """Normalizes WMS/QMS/tooling/labor/rush-order rows for replay."""

    def build_pack(
        self,
        *,
        material_availability: list[dict[str, Any]] | None = None,
        quality_holds: list[dict[str, Any]] | None = None,
        tooling_calendar: list[dict[str, Any]] | None = None,
        labor_skill_capacity: list[dict[str, Any]] | None = None,
        urgent_order_constraints: list[dict[str, Any]] | None = None,
        transport_lanes: list[dict[str, Any]] | None = None,
        buffer_flows: list[dict[str, Any]] | None = None,
        outsourcing_approvals: list[dict[str, Any]] | None = None,
        substitute_material_approvals: list[dict[str, Any]] | None = None,
        batch_genealogy: list[dict[str, Any]] | None = None,
        qms_release_gates: list[dict[str, Any]] | None = None,
    ) -> CustomerConstraintPack:
        return CustomerConstraintPack(
            material_availability=[
                MaterialAvailabilityRow.model_validate(_normalize_lists(row))
                for row in material_availability or []
            ],
            quality_holds=[
                QualityHoldRow.model_validate(_normalize_lists(row))
                for row in quality_holds or []
            ],
            tooling_calendar=[
                ToolingCalendarRow.model_validate(_normalize_lists(row))
                for row in tooling_calendar or []
            ],
            labor_skill_capacity=[
                LaborSkillCapacityRow.model_validate(_normalize_lists(row))
                for row in labor_skill_capacity or []
            ],
            urgent_order_constraints=[
                UrgentOrderConstraintRow.model_validate(_normalize_lists(row))
                for row in urgent_order_constraints or []
            ],
            transport_lanes=[
                TransportLaneRow.model_validate(_normalize_lists(row))
                for row in transport_lanes or []
            ],
            buffer_flows=[
                BufferFlowRow.model_validate(_normalize_lists(row))
                for row in buffer_flows or []
            ],
            outsourcing_approvals=[
                OutsourcingApprovalRow.model_validate(_normalize_lists(row))
                for row in outsourcing_approvals or []
            ],
            substitute_material_approvals=[
                SubstituteMaterialApprovalRow.model_validate(_normalize_lists(row))
                for row in substitute_material_approvals or []
            ],
            batch_genealogy=[
                BatchGenealogyRow.model_validate(_normalize_lists(row))
                for row in batch_genealogy or []
            ],
            qms_release_gates=[
                QmsReleaseGateRow.model_validate(_normalize_lists(row))
                for row in qms_release_gates or []
            ],
        )

    def load_csv_dir(self, directory: Path) -> CustomerConstraintPack:
        return self.build_pack(
            material_availability=_read_optional_csv(directory / "material_availability.csv"),
            quality_holds=_read_optional_csv(directory / "quality_holds.csv"),
            tooling_calendar=_read_optional_csv(directory / "tooling_calendar.csv"),
            labor_skill_capacity=_read_optional_csv(directory / "labor_skill_capacity.csv"),
            urgent_order_constraints=_read_optional_csv(directory / "urgent_order_constraints.csv"),
            transport_lanes=_read_optional_csv(directory / "transport_lanes.csv"),
            buffer_flows=_read_optional_csv(directory / "buffer_flows.csv"),
            outsourcing_approvals=_read_optional_csv(directory / "outsourcing_approvals.csv"),
            substitute_material_approvals=_read_optional_csv(
                directory / "substitute_material_approvals.csv"
            ),
            batch_genealogy=_read_optional_csv(directory / "batch_genealogy.csv"),
            qms_release_gates=_read_optional_csv(directory / "qms_release_gates.csv"),
        )

    def attach_to_snapshot(
        self,
        snapshot: ScheduleSnapshot,
        pack: CustomerConstraintPack,
    ) -> ScheduleSnapshot:
        raw_data = dict(snapshot.raw_data or {})
        raw_data.update(pack.as_raw_data())
        return snapshot.model_copy(update={"raw_data": raw_data}, deep=True)


def _read_optional_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _normalize_lists(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for key in (
        "operation_ids",
        "work_order_ids",
        "blocked_operation_ids",
        "parent_operation_ids",
        "batch_ids",
        "required_approvals",
        "approvals",
        "capability_codes",
    ):
        value = normalized.get(key)
        if isinstance(value, str):
            normalized[key] = [
                item.strip()
                for item in value.replace("|", ",").replace(";", ",").split(",")
                if item.strip()
            ]
    return normalized
