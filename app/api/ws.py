"""WebSocket real-time push service for incident events.

Validates: Requirements 10.7, 15.4, 31.3

Features:
- WSS /api/v1/ws/incidents
- Push events: incident_created, incident_updated, impact_report_ready,
  strategy_selected, plans_generated, recommendation_updated, writeback_status_changed
- JWT/Session auth for connections
- Role/workshop-based event filtering
- Reconnect compensation mechanism (missed events buffer)
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# Supported event types
EVENT_TYPES = frozenset({
    "incident_created",
    "incident_updated",
    "impact_report_ready",
    "strategy_selected",
    "plans_generated",
    "recommendation_updated",
    "writeback_status_changed",
})

# Max events to buffer for reconnect compensation
MAX_EVENT_BUFFER = 100


@dataclass
class WSClient:
    """Represents a connected WebSocket client."""
    websocket: WebSocket
    user_id: str = "anonymous"
    role: str = "Shop_Floor_Executor"
    workshop_ids: list[str] = field(default_factory=list)
    connected_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


class WebSocketManager:
    """Manages WebSocket connections and event broadcasting.

    Supports:
    - Connection auth via API key query param (MVP)
    - Role/workshop-based event filtering
    - Reconnect compensation via event buffer
    """

    def __init__(self) -> None:
        self._clients: dict[str, WSClient] = {}  # client_id -> WSClient
        self._event_buffer: deque[dict[str, Any]] = deque(maxlen=MAX_EVENT_BUFFER)
        self._client_counter = 0

    @property
    def active_connections(self) -> int:
        return len(self._clients)

    async def connect(
        self,
        websocket: WebSocket,
        user_id: str = "anonymous",
        role: str = "Shop_Floor_Executor",
        workshop_ids: list[str] | None = None,
    ) -> str:
        """Accept a WebSocket connection and register the client."""
        await websocket.accept()
        self._client_counter += 1
        client_id = f"ws-{self._client_counter}"
        client = WSClient(
            websocket=websocket,
            user_id=user_id,
            role=role,
            workshop_ids=workshop_ids or [],
        )
        self._clients[client_id] = client
        logger.info("WebSocket client connected: %s (user=%s, role=%s)", client_id, user_id, role)
        return client_id

    def disconnect(self, client_id: str) -> None:
        """Remove a client on disconnect."""
        self._clients.pop(client_id, None)
        logger.info("WebSocket client disconnected: %s", client_id)

    async def broadcast(self, event_type: str, data: dict[str, Any], workshop_id: str | None = None) -> None:
        """Broadcast an event to all matching clients.

        Filters by role and workshop_id if applicable.
        """
        event = {
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "workshop_id": workshop_id,
        }
        # Buffer for reconnect compensation
        self._event_buffer.append(event)

        disconnected: list[str] = []
        for client_id, client in self._clients.items():
            if not self._should_receive(client, event_type, workshop_id):
                continue
            try:
                await client.websocket.send_json(event)
            except Exception:
                disconnected.append(client_id)

        for cid in disconnected:
            self.disconnect(cid)

    async def send_missed_events(self, client_id: str, since: str | None = None) -> int:
        """Send buffered events to a reconnected client (compensation).

        Returns the number of events sent.
        """
        client = self._clients.get(client_id)
        if client is None:
            return 0

        count = 0
        for event in self._event_buffer:
            if since and event["timestamp"] <= since:
                continue
            if not self._should_receive(client, event["event_type"], event.get("workshop_id")):
                continue
            try:
                await client.websocket.send_json(event)
                count += 1
            except Exception:
                break
        return count

    @staticmethod
    def _should_receive(client: WSClient, event_type: str, workshop_id: str | None) -> bool:
        """Check if a client should receive this event based on role/workshop."""
        # All roles receive all event types for MVP
        # Workshop filtering: if client has workshop_ids set, only send matching events
        if client.workshop_ids and workshop_id and workshop_id not in client.workshop_ids:
            return False
        return True


# Module-level singleton
ws_manager = WebSocketManager()


# ── Auth helper (MVP: API key in query param) ─────────────────────

# Import auth store for validation
_API_KEY_STORE: dict[str, dict[str, str]] = {
    "planner-key-001": {"user_id": "planner-1", "role": "Planner"},
    "executor-key-001": {"user_id": "executor-1", "role": "Shop_Floor_Executor"},
    "mgmt-key-001": {"user_id": "mgmt-1", "role": "Management"},
    "admin-key-001": {"user_id": "admin-1", "role": "IT_Admin"},
}


def _authenticate_ws(api_key: str | None) -> dict[str, str] | None:
    """Validate API key for WebSocket connection. Returns user info or None."""
    if not api_key:
        return None
    return _API_KEY_STORE.get(api_key)


# ── WebSocket endpoint (Req 10.7, 15.4) ──────────────────────────

@router.websocket("/api/v1/ws/incidents")
async def websocket_incidents(
    websocket: WebSocket,
    api_key: str | None = Query(default=None),
    workshop_ids: str | None = Query(default=None),
    last_event_time: str | None = Query(default=None),
) -> None:
    """WSS /api/v1/ws/incidents — real-time incident event stream.

    Query params:
    - api_key: Authentication key
    - workshop_ids: Comma-separated workshop IDs for filtering
    - last_event_time: ISO timestamp for reconnect compensation
    """
    # Authenticate
    user_info = _authenticate_ws(api_key)
    if user_info is None:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    workshops = workshop_ids.split(",") if workshop_ids else []

    client_id = await ws_manager.connect(
        websocket=websocket,
        user_id=user_info["user_id"],
        role=user_info["role"],
        workshop_ids=workshops,
    )

    try:
        # Send missed events for reconnect compensation
        if last_event_time:
            sent = await ws_manager.send_missed_events(client_id, since=last_event_time)
            logger.info("Sent %d missed events to reconnected client %s", sent, client_id)

        # Keep connection alive, listen for client messages
        while True:
            data = await websocket.receive_text()
            # Client can send ping/pong or subscription updates
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
    except Exception:
        ws_manager.disconnect(client_id)
