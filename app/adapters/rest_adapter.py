"""Generic REST adapter for ERP/MES/APS sandbox and customer APIs."""

from __future__ import annotations

from typing import Any

import httpx

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
    extract_payload_list,
    map_incident,
    map_machine,
    map_operation,
    map_work_order,
)
from app.models.schedule import ScheduleSnapshot


class RESTEndpointConfig:
    """Endpoint paths for one REST-backed adapter."""

    def __init__(
        self,
        *,
        work_orders: str = "/api/work-orders",
        operations: str = "/api/operations",
        machines: str = "/api/machines",
        current_schedule: str = "/api/current-schedule",
        incidents: str = "/api/incidents",
        writeback: str = "/api/reschedule-plan",
        execution_feedback: str = "/api/execution-feedback",
        health: str = "/health",
    ) -> None:
        self.work_orders = work_orders
        self.operations = operations
        self.machines = machines
        self.current_schedule = current_schedule
        self.incidents = incidents
        self.writeback = writeback
        self.execution_feedback = execution_feedback
        self.health = health


class RESTAdapter(BaseCustomerAdapter):
    """Adapter for customer sandbox/staging APIs using JSON over HTTP."""

    adapter_name = "rest"
    capabilities = AdapterCapabilities(can_writeback=True)

    def __init__(
        self,
        base_url: str,
        *,
        source_system: str = "customer_rest",
        api_key: str | None = None,
        endpoints: RESTEndpointConfig | None = None,
        mapping: AdapterMappingProfile | None = None,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.source_system = source_system
        self._base_url = base_url
        self._api_key = api_key
        self._endpoints = endpoints or RESTEndpointConfig()
        self._mapping = mapping or AdapterMappingProfile(source_system=source_system)
        self._timeout = timeout_seconds
        self._transport = transport

    async def fetch_work_orders(self) -> list[CanonicalWorkOrder]:
        payload = await self._get_json(self._endpoints.work_orders)
        return [
            map_work_order(row, self._mapping)
            for row in extract_payload_list(payload, self._mapping.work_orders_path)
        ]

    async def fetch_operations(self) -> list[CanonicalOperation]:
        payload = await self._get_json(self._endpoints.operations)
        return [
            map_operation(row, self._mapping)
            for row in extract_payload_list(payload, self._mapping.operations_path)
        ]

    async def fetch_machines(self) -> list[CanonicalMachine]:
        payload = await self._get_json(self._endpoints.machines)
        return [
            map_machine(row, self._mapping)
            for row in extract_payload_list(payload, self._mapping.machines_path)
        ]

    async def fetch_current_schedule(self, workshop_id: str = "WS-01") -> ScheduleSnapshot:
        try:
            payload = await self._get_json(self._endpoints.current_schedule)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            payload = None
        if isinstance(payload, dict) and "work_orders" in payload and "captured_at" in payload:
            return ScheduleSnapshot.model_validate(payload)
        return await super().fetch_current_schedule(workshop_id=workshop_id)

    async def fetch_incidents(self) -> list[CanonicalIncident]:
        payload = await self._get_json(self._endpoints.incidents)
        return [
            map_incident(row, self._mapping)
            for row in extract_payload_list(payload, self._mapping.incidents_path)
        ]

    async def writeback_reschedule_plan(
        self, plan: RescheduleWritebackPlan
    ) -> AdapterWritebackResult:
        payload = plan.model_dump(mode="json")
        headers = {"Idempotency-Key": plan.idempotency_key}
        response = await self._post_json(self._endpoints.writeback, payload, extra_headers=headers)
        status_value = str(response.get("status", "accepted"))
        accepted = bool(response.get("accepted", status_value in {"accepted", "success"}))
        return AdapterWritebackResult(
            plan_id=plan.plan_id,
            idempotency_key=plan.idempotency_key,
            accepted=accepted,
            status=status_value,
            message=response.get("message"),
            raw_response=response,
        )

    async def fetch_execution_feedback(self) -> list[dict[str, Any]]:
        payload = await self._get_json(self._endpoints.execution_feedback)
        if isinstance(payload, dict):
            data = payload.get("execution_feedback", payload.get("items", []))
            return data if isinstance(data, list) else []
        return payload if isinstance(payload, list) else []

    async def health_check(self) -> dict[str, Any]:
        try:
            payload = await self._get_json(self._endpoints.health)
            remote_ok = True
        except Exception as exc:
            payload = {"error": str(exc)}
            remote_ok = False
        return {
            "system": self.source_system,
            "adapter": self.adapter_name,
            "available": remote_ok,
            "mode": "customer_rest",
            "base_url": self._base_url,
            "remote": payload,
        }

    async def _get_json(self, path: str) -> Any:
        async with self._client() as client:
            response = await client.get(path)
        response.raise_for_status()
        return response.json()

    async def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        async with self._client(extra_headers=extra_headers) as client:
            response = await client.post(path, json=payload)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"accepted": True, "status": "accepted"}

    def _client(self, *, extra_headers: dict[str, str] | None = None) -> httpx.AsyncClient:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        if extra_headers:
            headers.update(extra_headers)
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers=headers,
            transport=self._transport,
        )
