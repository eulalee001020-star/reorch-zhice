"""Mock customer-system adapter for demos, CI, and sandbox integration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.adapters.base_adapter import (
    AdapterCapabilities,
    AdapterWritebackResult,
    BaseCustomerAdapter,
)
from app.adapters.mapping_schema import (
    CanonicalIncident,
    CanonicalMachine,
    CanonicalOperation,
    CanonicalWorkOrder,
    RescheduleWritebackPlan,
)


class MockAdapter(BaseCustomerAdapter):
    """Deterministic in-memory adapter implementing the full contract."""

    adapter_name = "mock"
    source_system = "mock_erp_mes_aps"
    capabilities = AdapterCapabilities(can_writeback=True)

    def __init__(
        self,
        *,
        work_orders: list[CanonicalWorkOrder] | None = None,
        operations: list[CanonicalOperation] | None = None,
        machines: list[CanonicalMachine] | None = None,
        incidents: list[CanonicalIncident] | None = None,
    ) -> None:
        self._work_orders = work_orders or _default_work_orders()
        self._operations = operations or _default_operations()
        self._machines = machines or _default_machines()
        self._incidents = incidents or _default_incidents()
        self._writebacks: dict[str, AdapterWritebackResult] = {}

    async def fetch_work_orders(self) -> list[CanonicalWorkOrder]:
        return [item.model_copy(deep=True) for item in self._work_orders]

    async def fetch_operations(self) -> list[CanonicalOperation]:
        return [item.model_copy(deep=True) for item in self._operations]

    async def fetch_machines(self) -> list[CanonicalMachine]:
        return [item.model_copy(deep=True) for item in self._machines]

    async def fetch_incidents(self) -> list[CanonicalIncident]:
        return [item.model_copy(deep=True) for item in self._incidents]

    async def writeback_reschedule_plan(
        self, plan: RescheduleWritebackPlan
    ) -> AdapterWritebackResult:
        existing = self._writebacks.get(plan.idempotency_key)
        if existing is not None:
            return existing.model_copy(
                update={
                    "status": "duplicate_ignored",
                    "message": "idempotency key already processed",
                }
            )

        result = AdapterWritebackResult(
            plan_id=plan.plan_id,
            idempotency_key=plan.idempotency_key,
            accepted=True,
            status="accepted",
            message=f"{len(plan.instructions)} instruction(s) accepted by mock MES",
            raw_response={"instruction_count": len(plan.instructions)},
        )
        self._writebacks[plan.idempotency_key] = result
        return result

    async def fetch_execution_feedback(self) -> list[dict[str, Any]]:
        return [
            {
                "work_order_id": "WO-20260514-001",
                "operation_id": "OP-001",
                "status": "completed",
                "actual_end_time": "2026-05-14T11:05:00+08:00",
            }
        ]

    async def health_check(self) -> dict[str, Any]:
        return {
            "system": self.source_system,
            "adapter": self.adapter_name,
            "available": True,
            "mode": "mock",
            "work_orders": len(self._work_orders),
            "operations": len(self._operations),
            "machines": len(self._machines),
            "incidents": len(self._incidents),
            "writebacks": len(self._writebacks),
        }


def _default_work_orders() -> list[CanonicalWorkOrder]:
    return [
        CanonicalWorkOrder(
            work_order_id="WO-20260514-001",
            product_id="P001",
            product_name="PCR Kit A",
            quantity=100,
            priority=3,
            due_time=datetime(2026, 5, 15, 18, 0, tzinfo=timezone.utc),
            status="released",
        ),
        CanonicalWorkOrder(
            work_order_id="WO-20260514-002",
            product_id="P002",
            product_name="PCR Kit B",
            quantity=80,
            priority=1,
            due_time=datetime(2026, 5, 16, 18, 0, tzinfo=timezone.utc),
            status="released",
        ),
    ]


def _default_operations() -> list[CanonicalOperation]:
    return [
        CanonicalOperation(
            operation_id="OP-001",
            work_order_id="WO-20260514-001",
            sequence=10,
            required_capability="PCR",
            required_capabilities=["PCR"],
            processing_time_min=45,
            machine_id="M-PCR-01",
            start_time=datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 5, 14, 10, 45, tzinfo=timezone.utc),
            successors=["OP-002"],
        ),
        CanonicalOperation(
            operation_id="OP-002",
            work_order_id="WO-20260514-001",
            sequence=20,
            required_capability="PACK",
            required_capabilities=["PACK"],
            processing_time_min=30,
            machine_id="M-PACK-01",
            start_time=datetime(2026, 5, 14, 10, 50, tzinfo=timezone.utc),
            end_time=datetime(2026, 5, 14, 11, 20, tzinfo=timezone.utc),
            predecessors=["OP-001"],
        ),
        CanonicalOperation(
            operation_id="OP-003",
            work_order_id="WO-20260514-002",
            sequence=10,
            required_capability="PCR",
            required_capabilities=["PCR"],
            processing_time_min=40,
            machine_id="M-PCR-02",
            start_time=datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 5, 14, 11, 40, tzinfo=timezone.utc),
        ),
    ]


def _default_machines() -> list[CanonicalMachine]:
    return [
        CanonicalMachine(
            machine_id="M-PCR-01",
            name="PCR Line 01",
            capabilities=["PCR"],
            status="available",
            is_bottleneck=True,
            criticality="critical",
        ),
        CanonicalMachine(
            machine_id="M-PCR-02",
            name="PCR Line 02",
            capabilities=["PCR"],
            status="available",
            has_redundancy=True,
        ),
        CanonicalMachine(
            machine_id="M-PACK-01",
            name="Packing Line 01",
            capabilities=["PACK"],
            status="available",
        ),
    ]


def _default_incidents() -> list[CanonicalIncident]:
    return [
        CanonicalIncident(
            incident_id="INC-20260514-001",
            incident_type="machine_down",
            machine_id="M-PCR-01",
            start_time=datetime(2026, 5, 14, 10, 30, tzinfo=timezone.utc),
            severity="P1-Critical",
            description="M-PCR-01 down for planned mock integration test",
        )
    ]
