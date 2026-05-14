"""Helpers for converting planning runs into digital-twin snapshots."""

from __future__ import annotations

from datetime import datetime

from app.models.planning import InitialScheduleOption, InitialScheduleRequest
from app.models.schedule import ScheduleSnapshot


def schedule_snapshot_from_initial_option(
    *,
    request: InitialScheduleRequest,
    option: InitialScheduleOption,
    captured_at: datetime,
) -> ScheduleSnapshot:
    """Build a replayable schedule snapshot from an initial scheduling option."""

    eligible_by_op = {
        op.operation_id: op.eligible_resource_ids
        for wo in request.work_orders
        for op in wo.operations
    }
    input_op_by_id = {
        op.operation_id: op
        for wo in request.work_orders
        for op in wo.operations
    }
    raw_work_orders = []
    for wo in option.candidate_plan.schedule_detail.work_orders:
        raw_ops = []
        for op in wo.operations:
            input_op = input_op_by_id.get(op.operation_id)
            raw_ops.append(
                {
                    "operation_id": op.operation_id,
                    "work_order_id": op.work_order_id,
                    "resource_id": op.resource_id,
                    "product_family": input_op.product_family if input_op else None,
                    "required_capabilities": op.required_capabilities,
                    "eligible_resources": eligible_by_op.get(op.operation_id, [op.resource_id]),
                    "material_requirements": [
                        mat.model_dump(mode="json")
                        for mat in (input_op.material_requirements if input_op else [])
                    ],
                    "start_time": op.start_time.isoformat(),
                    "end_time": op.end_time.isoformat(),
                    "predecessor_ids": op.predecessor_ids,
                    "successor_ids": op.successor_ids,
                }
            )
        raw_work_orders.append(
            {
                "work_order_id": wo.work_order_id,
                "product_name": wo.product_name,
                "product_family": next(
                    (
                        source_wo.product_family
                        for source_wo in request.work_orders
                        if source_wo.work_order_id == wo.work_order_id
                    ),
                    None,
                ),
                "priority": wo.priority,
                "due_date": wo.due_date.isoformat(),
                "operations": raw_ops,
            }
        )

    return ScheduleSnapshot(
        captured_at=captured_at,
        workshop_id=request.workshop_id,
        source_system="digital_twin_initial_scheduler",
        work_orders=option.candidate_plan.schedule_detail.work_orders,
        raw_data={
            "resources": [
                {
                    "resource_id": res.resource_id,
                    "name": res.name or res.resource_id,
                    "capabilities": res.capabilities,
                    "is_bottleneck": res.is_bottleneck,
                    "has_redundancy": res.has_redundancy,
                    "criticality": res.criticality,
                }
                for res in request.resources
            ],
            "resource_calendar": [
                window.model_dump(mode="json") for window in request.resource_calendar
            ],
            "changeover_rules": [
                rule.model_dump(mode="json") for rule in request.changeover_rules
            ],
            "work_orders": raw_work_orders,
        },
    )
