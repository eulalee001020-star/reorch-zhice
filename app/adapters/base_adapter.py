"""Base contract for customer-system adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import Field

from app.adapters.mapping_schema import (
    CanonicalIncident,
    CanonicalMachine,
    CanonicalOperation,
    CanonicalWorkOrder,
    RescheduleWritebackPlan,
    build_schedule_snapshot,
)
from app.models.base import ReOrchModel
from app.models.schedule import ScheduleSnapshot


class AdapterCapabilities(ReOrchModel):
    """What one adapter can do safely in the current environment."""

    can_read_work_orders: bool = True
    can_read_operations: bool = True
    can_read_machines: bool = True
    can_read_current_schedule: bool = True
    can_read_incidents: bool = True
    can_writeback: bool = False
    supports_idempotency: bool = True
    supports_audit_log: bool = True


class AdapterWritebackResult(ReOrchModel):
    """Result returned by a customer-system writeback call."""

    plan_id: str
    idempotency_key: str
    accepted: bool
    status: str
    message: str | None = None
    attempt_count: int = 1
    raw_response: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


class BaseCustomerAdapter(ABC):
    """Contract every ERP/MES/APS adapter must satisfy.

    Adapters translate customer-specific protocols into canonical ReOrch
    objects. They must not call solvers, mutate schedules directly, or bypass
    human-confirmed writeback.
    """

    adapter_name: str = "base"
    source_system: str = "generic"
    capabilities: AdapterCapabilities = AdapterCapabilities()

    @abstractmethod
    async def fetch_work_orders(self) -> list[CanonicalWorkOrder]:
        """Read released or active work orders."""

    @abstractmethod
    async def fetch_operations(self) -> list[CanonicalOperation]:
        """Read routing operations for active work orders."""

    @abstractmethod
    async def fetch_machines(self) -> list[CanonicalMachine]:
        """Read machines/resources and capabilities."""

    async def fetch_current_schedule(self, workshop_id: str = "WS-01") -> ScheduleSnapshot:
        """Build a ScheduleSnapshot from canonical work orders and operations."""
        work_orders = await self.fetch_work_orders()
        operations = await self.fetch_operations()
        machines = await self.fetch_machines()
        return build_schedule_snapshot(
            workshop_id=workshop_id,
            work_orders=work_orders,
            operations=operations,
            machines=machines,
            source_system=self.source_system,
        )

    @abstractmethod
    async def fetch_incidents(self) -> list[CanonicalIncident]:
        """Read open incidents or anomaly events."""

    @abstractmethod
    async def writeback_reschedule_plan(
        self, plan: RescheduleWritebackPlan
    ) -> AdapterWritebackResult:
        """Write back a human-confirmed plan to the customer system."""

    @abstractmethod
    async def fetch_execution_feedback(self) -> list[dict[str, Any]]:
        """Read execution feedback after a plan is released."""

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Return adapter and upstream connectivity health."""
