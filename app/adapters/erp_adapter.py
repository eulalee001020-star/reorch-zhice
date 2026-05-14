"""ERP/APS Data Import Adapter — schedule data import and master data sync.

Validates: Requirements 18.4

Key capabilities:
- Import ScheduleSnapshot from APS systems
- Sync resource, work order, and operation master data
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import settings
from app.models.schedule import (
    Operation,
    Resource,
    ScheduleSnapshot,
    WorkOrder,
)

logger = logging.getLogger(__name__)


class ERPAdapter:
    """Adapter for importing data from ERP/APS systems.

    Provides schedule data import (ScheduleSnapshot from APS) and
    master data synchronization for resources, work orders, and operations.
    """

    def __init__(self) -> None:
        self._available = True
        self._base_url = settings.integration.erp_aps_base_url
        self._api_key = settings.integration.erp_aps_api_key
        self._timeout = settings.integration.request_timeout_seconds
        # In-memory master data stores for MVP
        self._resources: dict[str, Resource] = {}
        self._work_orders: dict[str, WorkOrder] = {}
        self._snapshots: dict[str, ScheduleSnapshot] = {}

    @property
    def is_available(self) -> bool:
        return self._available

    def set_available(self, available: bool) -> None:
        self._available = available

    # ── Schedule import (Req 18.4) ─────────────────────────────────

    async def import_schedule_snapshot(
        self, raw_data: dict[str, Any], workshop_id: str
    ) -> ScheduleSnapshot:
        """Import a ScheduleSnapshot from APS raw data.

        Parses the raw APS payload into structured WorkOrder/Operation
        objects and creates an immutable ScheduleSnapshot.
        """
        source_payload = raw_data
        if self._base_url and not raw_data:
            source_payload = await self._fetch_json(
                settings.integration.erp_aps_snapshot_path,
                params={"workshop_id": workshop_id},
            )

        work_orders = self._parse_work_orders(source_payload.get("work_orders", []))
        snapshot = ScheduleSnapshot(
            snapshot_id=uuid4(),
            captured_at=datetime.now(tz=timezone.utc),
            workshop_id=workshop_id,
            work_orders=work_orders,
            source_system="ERP_APS",
            raw_data=source_payload,
        )
        self._snapshots[str(snapshot.snapshot_id)] = snapshot
        logger.info(
            "Imported schedule snapshot %s for workshop %s with %d work orders",
            snapshot.snapshot_id, workshop_id, len(work_orders),
        )
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> ScheduleSnapshot | None:
        return self._snapshots.get(snapshot_id)

    # ── Master data sync (Req 18.4) ────────────────────────────────

    async def sync_resources(self, raw_resources: list[dict[str, Any]]) -> list[Resource]:
        """Sync resource master data from ERP."""
        if self._base_url and not raw_resources:
            data = await self._fetch_json(settings.integration.erp_aps_resources_path)
            raw_resources = data.get("resources", data if isinstance(data, list) else [])
        resources: list[Resource] = []
        for raw in raw_resources:
            resource = Resource(
                resource_id=raw.get("resource_id", ""),
                name=raw.get("name", ""),
                capabilities=raw.get("capabilities", []),
                is_bottleneck=raw.get("is_bottleneck", False),
                has_redundancy=raw.get("has_redundancy", False),
                criticality=raw.get("criticality", "general"),
            )
            self._resources[resource.resource_id] = resource
            resources.append(resource)
        logger.info("Synced %d resources from ERP", len(resources))
        return resources

    async def sync_work_orders(self, raw_orders: list[dict[str, Any]]) -> list[WorkOrder]:
        """Sync work order master data from ERP."""
        if self._base_url and not raw_orders:
            data = await self._fetch_json(settings.integration.erp_aps_work_orders_path)
            raw_orders = data.get("work_orders", data if isinstance(data, list) else [])
        orders: list[WorkOrder] = []
        for raw in raw_orders:
            wo = WorkOrder(
                work_order_id=raw.get("work_order_id", ""),
                product_name=raw.get("product_name", ""),
                due_date=raw.get("due_date", datetime.now(tz=timezone.utc)),
                operations=self._parse_operations(raw.get("operations", [])),
                priority=raw.get("priority", 0),
            )
            self._work_orders[wo.work_order_id] = wo
            orders.append(wo)
        logger.info("Synced %d work orders from ERP", len(orders))
        return orders

    def get_resource(self, resource_id: str) -> Resource | None:
        return self._resources.get(resource_id)

    def get_work_order(self, work_order_id: str) -> WorkOrder | None:
        return self._work_orders.get(work_order_id)

    # ── Health check ───────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        remote_ok: bool | None = None
        if self._base_url:
            try:
                await self._fetch_json(settings.integration.erp_aps_health_path)
                remote_ok = True
            except Exception:
                remote_ok = False
        return {
            "system": "ERP/APS",
            "available": self._available,
            "mode": "customer_http" if self._base_url else "local_poc",
            "remote_ok": remote_ok,
            "resources_count": len(self._resources),
            "work_orders_count": len(self._work_orders),
            "snapshots_count": len(self._snapshots),
        }

    # ── Internal parsing ───────────────────────────────────────────

    @staticmethod
    def _parse_work_orders(raw_list: list[dict[str, Any]]) -> list[WorkOrder]:
        orders: list[WorkOrder] = []
        for raw in raw_list:
            ops = ERPAdapter._parse_operations(raw.get("operations", []))
            wo = WorkOrder(
                work_order_id=raw.get("work_order_id", ""),
                product_name=raw.get("product_name", ""),
                due_date=raw.get("due_date", datetime.now(tz=timezone.utc)),
                operations=ops,
                priority=raw.get("priority", 0),
            )
            orders.append(wo)
        return orders

    @staticmethod
    def _parse_operations(raw_list: list[dict[str, Any]]) -> list[Operation]:
        ops: list[Operation] = []
        for raw in raw_list:
            op = Operation(
                operation_id=raw.get("operation_id", ""),
                work_order_id=raw.get("work_order_id", ""),
                resource_id=raw.get("resource_id", ""),
                required_capabilities=raw.get("required_capabilities", []),
                start_time=raw.get("start_time", datetime.now(tz=timezone.utc)),
                end_time=raw.get("end_time", datetime.now(tz=timezone.utc)),
                predecessor_ids=raw.get("predecessor_ids", []),
                successor_ids=raw.get("successor_ids", []),
            )
            ops.append(op)
        return ops

    async def _fetch_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        headers = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers=headers,
        ) as client:
            response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()
