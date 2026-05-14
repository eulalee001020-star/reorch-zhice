"""CSV adapter for customer historical data and offline PoC imports."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.adapters.base_adapter import (
    AdapterCapabilities,
    AdapterWritebackResult,
    BaseCustomerAdapter,
)
from app.adapters.mapping_schema import (
    AdapterMappingProfile,
    CanonicalIncident,
    CanonicalMachine,
    CanonicalOperation,
    CanonicalWorkOrder,
    RescheduleWritebackPlan,
    map_incident,
    map_machine,
    map_operation,
    map_work_order,
)


class CSVAdapter(BaseCustomerAdapter):
    """Reads canonical data from CSV files in a directory."""

    adapter_name = "csv"
    source_system = "csv_import"
    capabilities = AdapterCapabilities(can_writeback=False)

    def __init__(
        self,
        data_dir: str | Path,
        *,
        mapping: AdapterMappingProfile | None = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._mapping = mapping or AdapterMappingProfile(source_system=self.source_system)

    async def fetch_work_orders(self) -> list[CanonicalWorkOrder]:
        return [map_work_order(row, self._mapping) for row in self._read_csv("work_orders.csv")]

    async def fetch_operations(self) -> list[CanonicalOperation]:
        return [map_operation(row, self._mapping) for row in self._read_csv("operations.csv")]

    async def fetch_machines(self) -> list[CanonicalMachine]:
        return [map_machine(row, self._mapping) for row in self._read_csv("machines.csv")]

    async def fetch_incidents(self) -> list[CanonicalIncident]:
        path = self._data_dir / "incidents.csv"
        if not path.exists():
            return []
        return [map_incident(row, self._mapping) for row in self._read_csv("incidents.csv")]

    async def writeback_reschedule_plan(
        self, plan: RescheduleWritebackPlan
    ) -> AdapterWritebackResult:
        return AdapterWritebackResult(
            plan_id=plan.plan_id,
            idempotency_key=plan.idempotency_key,
            accepted=False,
            status="unsupported",
            message="CSVAdapter is read-only; use RESTAdapter or MESAdapter for writeback.",
        )

    async def fetch_execution_feedback(self) -> list[dict[str, Any]]:
        path = self._data_dir / "execution_feedback.csv"
        if not path.exists():
            return []
        return self._read_csv("execution_feedback.csv")

    async def health_check(self) -> dict[str, Any]:
        files = {
            name: (self._data_dir / name).exists()
            for name in ("work_orders.csv", "operations.csv", "machines.csv", "incidents.csv")
        }
        required_ok = all(files[name] for name in ("work_orders.csv", "operations.csv", "machines.csv"))
        return {
            "system": self.source_system,
            "adapter": self.adapter_name,
            "available": required_ok,
            "mode": "csv",
            "data_dir": str(self._data_dir),
            "files": files,
        }

    def _read_csv(self, file_name: str) -> list[dict[str, Any]]:
        path = self._data_dir / file_name
        if not path.exists():
            raise FileNotFoundError(f"CSV adapter file not found: {path}")
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
