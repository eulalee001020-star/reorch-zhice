"""Deterministic digital-twin data for scale and recovery validation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.production_runtime import (
    DecompositionExecutionRequest,
    RuntimeIncident,
)
from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder


class ProductionDigitalTwinFactory:
    """Generate feasible customer-like schedules without claiming customer provenance."""

    def build_snapshot(
        self,
        operation_count: int,
        *,
        resource_count: int = 24,
        operations_per_work_order: int = 4,
    ) -> ScheduleSnapshot:
        if operation_count <= 0:
            raise ValueError("operation_count must be positive")
        resource_count = max(4, min(resource_count, operation_count))
        operations_per_work_order = max(1, operations_per_work_order)
        captured_at = datetime(2026, 7, 12, 0, 0, tzinfo=timezone.utc)
        resource_ids = [f"M-{index + 1:03d}" for index in range(resource_count)]
        available_at = {resource_id: captured_at for resource_id in resource_ids}
        work_orders: list[WorkOrder] = []
        raw_work_orders: list[dict] = []

        remaining = operation_count
        work_order_index = 0
        global_index = 0
        while remaining > 0:
            work_order_index += 1
            count = min(operations_per_work_order, remaining)
            work_order_id = f"WO-{work_order_index:05d}"
            previous_end = captured_at
            operations: list[Operation] = []
            raw_operations: list[dict] = []
            for sequence in range(count):
                global_index += 1
                operation_id = f"OP-{global_index:06d}"
                resource_index = (work_order_index * 7 + sequence * 5) % resource_count
                resource_id = resource_ids[resource_index]
                alternative = resource_ids[(resource_index + 1) % resource_count]
                duration = 8 + (global_index % 5)
                start = max(previous_end, available_at[resource_id])
                end = start + timedelta(minutes=duration)
                predecessor_ids = [operations[-1].operation_id] if operations else []
                operation = Operation(
                    operation_id=operation_id,
                    work_order_id=work_order_id,
                    resource_id=resource_id,
                    required_capabilities=["flex_process"],
                    start_time=start,
                    end_time=end,
                    predecessor_ids=predecessor_ids,
                )
                if operations:
                    operations[-1].successor_ids = [operation_id]
                operations.append(operation)
                raw_operations.append(
                    {
                        "operation_id": operation_id,
                        "eligible_resources": [resource_id, alternative],
                        "product_family": f"PF-{work_order_index % 6}",
                        "raw_payload": {},
                    }
                )
                available_at[resource_id] = end + timedelta(minutes=5)
                previous_end = end
            work_orders.append(
                WorkOrder(
                    work_order_id=work_order_id,
                    product_name=f"PF-{work_order_index % 6}",
                    due_date=previous_end + timedelta(hours=8),
                    priority=work_order_index % 5,
                    operations=operations,
                )
            )
            raw_work_orders.append(
                {
                    "work_order_id": work_order_id,
                    "product_family": f"PF-{work_order_index % 6}",
                    "operations": raw_operations,
                }
            )
            remaining -= count

        resources = [
            {
                "resource_id": resource_id,
                "name": f"Flexible resource {resource_id}",
                "capabilities": ["flex_process"],
                "is_bottleneck": index < 3,
                "has_redundancy": True,
            }
            for index, resource_id in enumerate(resource_ids)
        ]
        return ScheduleSnapshot(
            captured_at=captured_at,
            workshop_id="DIGITAL-TWIN-FLEX",
            source_system="deterministic_digital_twin",
            schema_version="production-twin-v1",
            work_orders=work_orders,
            raw_data={
                "resources": resources,
                "work_orders": raw_work_orders,
                "evidence_scope": "digital_twin",
                "generator": "ProductionDigitalTwinFactory",
                "operation_count": operation_count,
            },
        )

    def build_incidents(
        self,
        snapshot: ScheduleSnapshot,
        *,
        incident_count: int = 5,
        include_joint_pair: bool = True,
    ) -> list[RuntimeIncident]:
        operations = [op for wo in snapshot.work_orders for op in wo.operations]
        if not operations:
            return []
        incident_count = max(1, min(incident_count, len(operations)))
        incidents: list[RuntimeIncident] = []
        used_resources: set[str] = set()
        used_work_orders: set[str] = set()

        if include_joint_pair and incident_count >= 2 and len(snapshot.work_orders[0].operations) >= 2:
            first, second = snapshot.work_orders[0].operations[:2]
            incidents.extend(
                [
                    RuntimeIncident(
                        incident_id="DT-INC-001",
                        incident_type="equipment_failure",
                        affected_operation_ids=[first.operation_id],
                        delay_minutes=2,
                        resource_id=first.resource_id,
                        work_order_id=first.work_order_id,
                        severity="P1",
                        occurred_at=snapshot.captured_at,
                    ),
                    RuntimeIncident(
                        incident_id="DT-INC-002",
                        incident_type="quality_exception",
                        affected_operation_ids=[second.operation_id],
                        delay_minutes=2,
                        resource_id=second.resource_id,
                        work_order_id=second.work_order_id,
                        severity="P2",
                        occurred_at=snapshot.captured_at,
                    ),
                ]
            )
            used_resources.update([first.resource_id, second.resource_id])
            used_work_orders.add(first.work_order_id)

        for op in operations:
            if len(incidents) >= incident_count:
                break
            if op.resource_id in used_resources or op.work_order_id in used_work_orders:
                continue
            index = len(incidents) + 1
            incidents.append(
                RuntimeIncident(
                    incident_id=f"DT-INC-{index:03d}",
                    incident_type=(
                        "material_shortage" if index % 2 else "labor_absence"
                    ),
                    affected_operation_ids=[op.operation_id],
                    delay_minutes=2,
                    resource_id=op.resource_id,
                    work_order_id=op.work_order_id,
                    severity="P2",
                    occurred_at=snapshot.captured_at,
                )
            )
            used_resources.add(op.resource_id)
            used_work_orders.add(op.work_order_id)
        return incidents

    def build_solve_request(
        self,
        operation_count: int,
        *,
        tenant_id: str = "digital-twin",
        incident_count: int = 5,
        max_subproblem_operations: int = 40,
        max_parallelism: int = 2,
    ) -> DecompositionExecutionRequest:
        snapshot = self.build_snapshot(operation_count)
        return DecompositionExecutionRequest(
            tenant_id=tenant_id,
            snapshot=snapshot,
            incidents=self.build_incidents(snapshot, incident_count=incident_count),
            max_subproblem_operations=max_subproblem_operations,
            neighborhood_hops=2,
            max_parallelism=max_parallelism,
            timeout_seconds=30,
        )
