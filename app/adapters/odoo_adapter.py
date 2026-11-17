"""Odoo adapter: manufacturing orders, work orders, work centres and supply.

Odoo exposes its data through two external protocols, and an integration has
to speak the one the customer's version supports:

* **JSON-2** (Odoo 19 and later): ``POST /json/2/<model>/<method>`` with an
  API key as a bearer token and named arguments in the JSON body.
* **JSON-RPC** (Odoo 18 and earlier, deprecated from 19): ``POST /jsonrpc``
  with ``execute_kw`` and positional arguments.

:class:`OdooClient` hides that difference. :class:`OdooAdapter` maps Odoo's
manufacturing models onto the canonical adapter objects:

==========================  ==========================================
Odoo model                  Canonical object
==========================  ==========================================
``mrp.production``          work order
``mrp.workorder``           operation
``mrp.workcenter``          machine
``stock.move`` (raw)        operation material requirement
``stock.quant``             inventory record
``purchase.order.line``     inbound supply line
``mrp.bom.line``            BOM line
==========================  ==========================================

Field names differ between Odoo versions (for example planned dates were
renamed in 17). The defaults follow 17 and later and can be overridden with
:class:`OdooFieldNames`.

Writeback only ever sends the dates and work centre of operations in a
human-confirmed plan, and only when ``allow_writeback`` is set. Otherwise the
call returns the payload it would have sent.

This adapter is tested against recorded request and response shapes. It has
not been run against a live Odoo instance.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from pydantic import Field

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
from app.models.base import ReOrchModel
from app.models.schedule import ScheduleSnapshot
from app.models.supply import (
    BomLine,
    InventoryRecord,
    OperationRequirement,
    SupplyOrderLine,
    SupplySnapshot,
)

OdooProtocol = Literal["json2", "jsonrpc"]
ODOO_DATETIME = "%Y-%m-%d %H:%M:%S"
ACTIVE_PRODUCTION_STATES = ("confirmed", "progress", "to_close")
CLOSED_WORKORDER_STATES = ("done", "cancel")


class OdooError(RuntimeError):
    """Odoo rejected a call or returned something unexpected."""


class OdooFieldNames(ReOrchModel):
    """Field names that changed between Odoo versions."""

    production_start: str = "date_start"
    production_deadline: str = "date_deadline"
    production_finish: str = "date_finished"
    workorder_start: str = "date_start"
    workorder_finish: str = "date_finished"
    workorder_predecessors: str | None = "blocked_by_workorder_ids"
    workcenter_alternatives: str | None = "alternative_workcenter_ids"


def parse_odoo_datetime(value: Any) -> datetime | None:
    """Odoo sends naive UTC strings and ``False`` for empty values."""
    if not value:
        return None
    return datetime.strptime(str(value)[:19], ODOO_DATETIME).replace(tzinfo=UTC)


def format_odoo_datetime(value: datetime | str) -> str:
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.strftime(ODOO_DATETIME)


def many2one_id(value: Any) -> int | None:
    """A many2one comes back as ``[id, display_name]`` or ``False``."""
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def many2one_name(value: Any) -> str | None:
    if isinstance(value, (list, tuple)) and len(value) > 1:
        return str(value[1])
    return None


class OdooClient:
    """Minimal read/write client for Odoo's external API."""

    def __init__(
        self,
        base_url: str,
        *,
        database: str,
        api_key: str | None = None,
        login: str | None = None,
        protocol: OdooProtocol = "json2",
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if protocol == "json2" and not api_key:
            raise ValueError("JSON-2 needs an API key")
        if protocol == "jsonrpc" and not (login and api_key):
            raise ValueError("JSON-RPC needs a login and an API key or password")
        self._base_url = base_url.rstrip("/")
        self._database = database
        self._api_key = api_key
        self._login = login
        self._protocol: OdooProtocol = protocol
        self._timeout = timeout_seconds
        self._transport = transport
        self._uid: int | None = None
        self._request_id = 0

    @property
    def protocol(self) -> OdooProtocol:
        return self._protocol

    async def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str],
        *,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        options: dict[str, Any] = {"fields": fields}
        if order:
            options["order"] = order
        if limit:
            options["limit"] = limit
        if self._protocol == "json2":
            result = await self._json2(model, "search_read", {"domain": domain, **options})
        else:
            result = await self._execute_kw(model, "search_read", [domain], options)
        if not isinstance(result, list):
            raise OdooError(f"{model}.search_read returned {type(result).__name__}, not a list")
        return result

    async def write(self, model: str, ids: list[int], values: dict[str, Any]) -> bool:
        if self._protocol == "json2":
            result = await self._json2(model, "write", {"ids": ids, "vals": values})
        else:
            result = await self._execute_kw(model, "write", [ids, values], {})
        return bool(result)

    async def probe(self) -> dict[str, Any]:
        """Health probe: one authenticated read of a manufacturing model.

        It checks the three things an adapter needs at once: the server
        answers, the credentials work, and the manufacturing app is readable.
        """
        rows = await self.search_read("mrp.workcenter", [], ["name"], limit=1)
        return {"readable": True, "sample_count": len(rows)}

    # ── transports ──────────────────────────────────────────────────

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        try:
            body = response.json()
            message = body.get("message") or body.get("name") or response.text
        except ValueError:
            message = response.text
        raise OdooError(f"HTTP {response.status_code}: {str(message)[:300]}")

    async def _json2(self, model: str, method: str, body: dict[str, Any]) -> Any:
        headers = {
            "Authorization": f"bearer {self._api_key}",
            "X-Odoo-Database": self._database,
        }
        async with self._http() as http:
            response = await http.post(
                f"{self._base_url}/json/2/{model}/{method}", json=body, headers=headers
            )
        self._raise_for_status(response)
        return response.json()

    async def _jsonrpc(
        self, http: httpx.AsyncClient, service: str, method: str, args: list[Any]
    ) -> Any:
        self._request_id += 1
        response = await http.post(
            f"{self._base_url}/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "id": self._request_id,
                "params": {"service": service, "method": method, "args": args},
            },
        )
        self._raise_for_status(response)
        payload = response.json()
        if payload.get("error"):
            error = payload["error"]
            detail = (error.get("data") or {}).get("message") or error.get("message")
            raise OdooError(str(detail)[:300])
        return payload.get("result")

    async def _execute_kw(
        self, model: str, method: str, args: list[Any], kwargs: dict[str, Any]
    ) -> Any:
        async with self._http() as http:
            if self._uid is None:
                uid = await self._jsonrpc(
                    http, "common", "authenticate", [self._database, self._login, self._api_key, {}]
                )
                if not uid:
                    raise OdooError("authentication failed")
                self._uid = int(uid)
            return await self._jsonrpc(
                http,
                "object",
                "execute_kw",
                [self._database, self._uid, self._api_key, model, method, args, kwargs],
            )


class OdooAdapter(BaseCustomerAdapter):
    """Reads an Odoo manufacturing database as canonical schedule and supply data."""

    adapter_name = "odoo"
    source_system = "odoo"

    def __init__(
        self,
        client: OdooClient,
        *,
        fields: OdooFieldNames | None = None,
        allow_writeback: bool = False,
    ) -> None:
        self._client = client
        self._fields = fields or OdooFieldNames()
        self._allow_writeback = allow_writeback
        self.capabilities = AdapterCapabilities(
            can_read_incidents=False, can_writeback=allow_writeback
        )
        self._workorder_ids: dict[str, int] = {}
        self._workcenter_ids: dict[str, int] = {}

    # ── schedule ────────────────────────────────────────────────────

    async def _productions(self) -> list[dict[str, Any]]:
        names = self._fields
        return await self._client.search_read(
            "mrp.production",
            [["state", "in", list(ACTIVE_PRODUCTION_STATES)]],
            [
                "name",
                "product_id",
                "product_qty",
                "priority",
                "state",
                names.production_start,
                names.production_deadline,
                names.production_finish,
            ],
            order="id",
        )

    async def fetch_work_orders(self) -> list[CanonicalWorkOrder]:
        names = self._fields
        work_orders: list[CanonicalWorkOrder] = []
        for row in await self._productions():
            due = parse_odoo_datetime(row.get(names.production_deadline)) or parse_odoo_datetime(
                row.get(names.production_finish)
            )
            if due is None:
                # A manufacturing order with no deadline cannot be assessed for
                # delivery risk; leave it out rather than invent a date.
                continue
            work_orders.append(
                CanonicalWorkOrder(
                    work_order_id=str(row["name"]),
                    product_id=str(many2one_id(row.get("product_id")) or ""),
                    product_name=many2one_name(row.get("product_id")) or str(row["name"]),
                    quantity=float(row.get("product_qty") or 1.0),
                    priority=int(row.get("priority") or 0),
                    due_time=due,
                    status=str(row.get("state") or "confirmed"),
                    raw_payload=row,
                )
            )
        return work_orders

    async def fetch_machines(self) -> list[CanonicalMachine]:
        fields = ["name", "code", "active"]
        if self._fields.workcenter_alternatives:
            fields.append(self._fields.workcenter_alternatives)
        rows = await self._client.search_read("mrp.workcenter", [], fields, order="id")
        self._workcenter_ids = {self._workcenter_key(row): int(row["id"]) for row in rows}
        return [
            CanonicalMachine(
                machine_id=self._workcenter_key(row),
                name=str(row.get("name") or ""),
                capabilities=[self._workcenter_key(row)],
                status="available" if row.get("active", True) else "unavailable",
                raw_payload=row,
            )
            for row in rows
        ]

    @staticmethod
    def _workcenter_key(row: dict[str, Any]) -> str:
        return str(row.get("code") or f"WC-{row['id']}")

    async def fetch_operations(self) -> list[CanonicalOperation]:
        names = self._fields
        centers = await self._client.search_read(
            "mrp.workcenter",
            [],
            ["code", *([names.workcenter_alternatives] if names.workcenter_alternatives else [])],
        )
        center_key = {int(row["id"]): self._workcenter_key(row) for row in centers}
        alternatives = {
            int(row["id"]): [
                center_key[int(other)]
                for other in (row.get(names.workcenter_alternatives or "") or [])
                if int(other) in center_key
            ]
            for row in centers
        }

        fields = [
            "name",
            "production_id",
            "workcenter_id",
            "duration_expected",
            "state",
            "sequence",
            names.workorder_start,
            names.workorder_finish,
        ]
        if names.workorder_predecessors:
            fields.append(names.workorder_predecessors)
        rows = await self._client.search_read(
            "mrp.workorder",
            [["state", "not in", list(CLOSED_WORKORDER_STATES)]],
            fields,
            order="production_id, sequence, id",
        )
        operation_id = {
            int(row["id"]): f"{many2one_name(row['production_id'])}/{row['id']}" for row in rows
        }
        self._workorder_ids = {value: key for key, value in operation_id.items()}

        operations: list[CanonicalOperation] = []
        previous_in_order: dict[str, str] = {}
        for row in rows:
            production = many2one_name(row["production_id"]) or ""
            center_id = many2one_id(row.get("workcenter_id"))
            machine = center_key.get(center_id) if center_id is not None else None
            own_id = operation_id[int(row["id"])]
            if names.workorder_predecessors:
                predecessors = [
                    operation_id[int(other)]
                    for other in (row.get(names.workorder_predecessors) or [])
                    if int(other) in operation_id
                ]
            else:
                # Older versions have no dependency field: operations of one
                # manufacturing order run in sequence.
                predecessors = (
                    [previous_in_order[production]] if production in previous_in_order else []
                )
            previous_in_order[production] = own_id
            eligible = [machine, *alternatives.get(center_id or -1, [])] if machine else []
            operations.append(
                CanonicalOperation(
                    operation_id=own_id,
                    work_order_id=production,
                    sequence=int(row.get("sequence") or 0),
                    required_capability=machine,
                    required_capabilities=[machine] if machine else [],
                    processing_time_min=max(1, math.ceil(float(row.get("duration_expected") or 1))),
                    machine_id=machine,
                    eligible_machine_ids=eligible,
                    start_time=parse_odoo_datetime(row.get(names.workorder_start)),
                    end_time=parse_odoo_datetime(row.get(names.workorder_finish)),
                    predecessors=predecessors,
                    raw_payload=row,
                )
            )
        return operations

    async def fetch_incidents(self) -> list[CanonicalIncident]:
        """Odoo has no incident feed in its manufacturing models."""
        return []

    async def fetch_execution_feedback(self) -> list[dict[str, Any]]:
        return await self._client.search_read(
            "mrp.workorder",
            [["state", "in", ["progress", "done"]]],
            ["name", "production_id", "workcenter_id", "state", "duration"],
            order="id",
        )

    # ── supply ──────────────────────────────────────────────────────

    async def fetch_supply_snapshot(self, schedule: ScheduleSnapshot) -> SupplySnapshot:
        """Material-side state for the operations of ``schedule``.

        Component requirements come from the raw-material moves of each
        manufacturing order, which already carry the exact quantity and, when
        set, the consuming work order. A move with no work order is issued at
        the manufacturing order's first operation.
        """
        first_operation: dict[str, str] = {}
        known_operations: set[str] = set()
        for work_order in schedule.work_orders:
            ordered = sorted(work_order.operations, key=lambda op: op.start_time)
            if ordered:
                first_operation[work_order.work_order_id] = ordered[0].operation_id
            known_operations.update(op.operation_id for op in work_order.operations)

        moves = await self._client.search_read(
            "stock.move",
            [
                ["raw_material_production_id", "!=", False],
                ["state", "not in", ["done", "cancel"]],
            ],
            ["product_id", "product_uom_qty", "raw_material_production_id", "workorder_id"],
        )
        requirements: list[OperationRequirement] = []
        for move in moves:
            production = many2one_name(move.get("raw_material_production_id"))
            item = many2one_id(move.get("product_id"))
            quantity = float(move.get("product_uom_qty") or 0)
            if production not in first_operation or item is None or quantity <= 0:
                continue
            workorder = many2one_id(move.get("workorder_id"))
            operation = f"{production}/{workorder}" if workorder is not None else None
            if operation not in known_operations:
                operation = first_operation[production]
            requirements.append(
                OperationRequirement(
                    work_order_id=production,
                    operation_id=operation,
                    item_id=str(item),
                    quantity=quantity,
                )
            )

        quants = await self._client.search_read(
            "stock.quant",
            [["location_id.usage", "=", "internal"]],
            ["product_id", "quantity", "reserved_quantity"],
        )
        on_hand: dict[str, list[float]] = {}
        for quant in quants:
            item = many2one_id(quant.get("product_id"))
            if item is None:
                continue
            totals = on_hand.setdefault(str(item), [0.0, 0.0])
            totals[0] += float(quant.get("quantity") or 0)
            totals[1] += float(quant.get("reserved_quantity") or 0)

        purchase_lines = await self._client.search_read(
            "purchase.order.line",
            [["state", "in", ["purchase"]]],
            ["order_id", "product_id", "product_qty", "qty_received", "date_planned", "partner_id"],
        )
        supply_orders: list[SupplyOrderLine] = []
        for line in purchase_lines:
            item = many2one_id(line.get("product_id"))
            promised = parse_odoo_datetime(line.get("date_planned"))
            open_quantity = float(line.get("product_qty") or 0) - float(
                line.get("qty_received") or 0
            )
            if item is None or promised is None or open_quantity <= 0:
                continue
            supplier = many2one_id(line.get("partner_id"))
            supply_orders.append(
                SupplyOrderLine(
                    order_id=many2one_name(line.get("order_id")) or str(line["id"]),
                    line_id=str(line["id"]),
                    item_id=str(item),
                    supplier_id=str(supplier) if supplier is not None else None,
                    quantity=open_quantity,
                    promised_at=promised,
                )
            )

        bom_lines = await self._client.search_read(
            "mrp.bom.line", [], ["bom_id", "product_id", "product_qty"]
        )
        boms = await self._client.search_read(
            "mrp.bom", [], ["product_id", "product_tmpl_id", "product_qty"]
        )
        bom_parent = {
            int(bom["id"]): (many2one_id(bom.get("product_id")), float(bom.get("product_qty") or 1))
            for bom in boms
        }
        bom: list[BomLine] = []
        for line in bom_lines:
            parent, batch = bom_parent.get(many2one_id(line.get("bom_id")) or -1, (None, 1.0))
            component = many2one_id(line.get("product_id"))
            quantity = float(line.get("product_qty") or 0)
            # A BOM defined on a product template (no variant) has no single
            # parent item; requirements already come from the stock moves.
            if parent is None or component is None or quantity <= 0 or batch <= 0:
                continue
            bom.append(
                BomLine(
                    parent_item_id=str(parent),
                    component_item_id=str(component),
                    quantity_per=quantity / batch,
                )
            )

        return SupplySnapshot(
            captured_at=schedule.captured_at,
            workshop_id=schedule.workshop_id,
            bom=bom,
            inventory=[
                InventoryRecord(item_id=item, on_hand=max(0.0, totals[0]), allocated=totals[1])
                for item, totals in sorted(on_hand.items())
            ],
            supply_orders=supply_orders,
            operation_requirements=requirements,
        )

    # ── writeback ───────────────────────────────────────────────────

    def _workorder_values(self, instruction: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {
            self._fields.workorder_start: format_odoo_datetime(instruction["start_time"]),
            self._fields.workorder_finish: format_odoo_datetime(instruction["end_time"]),
        }
        center = self._workcenter_ids.get(str(instruction.get("resource_id")))
        if center is not None:
            values["workcenter_id"] = center
        return values

    async def writeback_reschedule_plan(
        self, plan: RescheduleWritebackPlan
    ) -> AdapterWritebackResult:
        """Write the dates and work centre of each instructed operation.

        Operation ids must be the ones this adapter issued, so call
        :meth:`fetch_operations` and :meth:`fetch_machines` first. An unknown
        operation rejects the whole plan before anything is written.
        """
        unknown = [
            str(item.get("operation_id"))
            for item in plan.instructions
            if str(item.get("operation_id")) not in self._workorder_ids
        ]
        if unknown:
            return AdapterWritebackResult(
                plan_id=plan.plan_id,
                idempotency_key=plan.idempotency_key,
                accepted=False,
                status="rejected",
                message=f"unknown operations: {', '.join(unknown[:5])}",
            )
        writes = [
            {
                "model": "mrp.workorder",
                "id": self._workorder_ids[str(item["operation_id"])],
                "values": self._workorder_values(item),
            }
            for item in plan.instructions
        ]
        if not self._allow_writeback:
            return AdapterWritebackResult(
                plan_id=plan.plan_id,
                idempotency_key=plan.idempotency_key,
                accepted=False,
                status="dry_run",
                message="writeback is disabled; nothing was sent",
                raw_response={"writes": writes},
            )
        done: list[int] = []
        try:
            for write in writes:
                await self._client.write(write["model"], [write["id"]], write["values"])
                done.append(write["id"])
        except (OdooError, httpx.HTTPError) as exc:
            return AdapterWritebackResult(
                plan_id=plan.plan_id,
                idempotency_key=plan.idempotency_key,
                accepted=False,
                status="partial" if done else "failed",
                message=str(exc)[:300],
                raw_response={"written_ids": done, "writes": writes},
            )
        return AdapterWritebackResult(
            plan_id=plan.plan_id,
            idempotency_key=plan.idempotency_key,
            accepted=True,
            status="accepted",
            raw_response={"written_ids": done},
        )

    async def health_check(self) -> dict[str, Any]:
        try:
            remote: dict[str, Any] = await self._client.probe()
            available = True
        except (OdooError, httpx.HTTPError, ValueError) as exc:
            remote, available = {"error": str(exc)[:300]}, False
        return {
            "system": self.source_system,
            "adapter": self.adapter_name,
            "available": available,
            "mode": self._client.protocol,
            "writeback_enabled": self._allow_writeback,
            "remote": remote,
        }


class OdooConnectionSettings(ReOrchModel):
    """Connection details, normally read from environment variables."""

    base_url: str
    database: str
    api_key: str = Field(repr=False)
    login: str | None = None
    protocol: OdooProtocol = "json2"
    allow_writeback: bool = False

    def build_adapter(self, *, transport: httpx.AsyncBaseTransport | None = None) -> OdooAdapter:
        client = OdooClient(
            self.base_url,
            database=self.database,
            api_key=self.api_key,
            login=self.login,
            protocol=self.protocol,
            transport=transport,
        )
        return OdooAdapter(client, allow_writeback=self.allow_writeback)
