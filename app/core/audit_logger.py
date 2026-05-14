"""Audit Logger — records all user operations and system config changes.

Validates: Requirements 16.3, 26.8

Records:
- User operations: login, plan confirmation, Override, template publish
- Includes: operator, time, content, result
- Strategy module version changes
- Solver_Portfolio config change audit logs
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    """Types of auditable actions."""
    LOGIN = "login"
    PLAN_CONFIRM = "plan_confirm"
    PLAN_ADJUST = "plan_adjust"
    PLAN_OVERRIDE = "plan_override"
    TEMPLATE_CREATE = "template_create"
    TEMPLATE_EDIT = "template_edit"
    TEMPLATE_PUBLISH = "template_publish"
    MODULE_VERSION_CHANGE = "module_version_change"
    SOLVER_PORTFOLIO_CHANGE = "solver_portfolio_change"
    INCIDENT_CREATE = "incident_create"
    MES_WRITEBACK = "mes_writeback"
    EXPERIMENT_CREATE = "experiment_create"
    EXPERIMENT_ROLLBACK = "experiment_rollback"


class AuditResult(str, Enum):
    """Outcome of an audited action."""
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


@dataclass
class AuditEntry:
    """A single audit log entry."""
    entry_id: str
    action: AuditAction
    operator: str
    timestamp: datetime
    content: dict[str, Any]
    result: AuditResult
    resource_type: str = ""
    resource_id: str = ""
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "action": self.action.value,
            "operator": self.operator,
            "timestamp": self.timestamp.isoformat(),
            "content": self.content,
            "result": self.result.value,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
        }


class AuditLogger:
    """In-memory audit logger for MVP.

    In production, this would write to the audit_logs DB table
    and optionally forward to an external SIEM system.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"audit-{self._counter:06d}"

    def log(
        self,
        action: AuditAction,
        operator: str,
        content: dict[str, Any],
        result: AuditResult = AuditResult.SUCCESS,
        resource_type: str = "",
        resource_id: str = "",
        details: str = "",
    ) -> AuditEntry:
        """Record an audit log entry."""
        entry = AuditEntry(
            entry_id=self._next_id(),
            action=action,
            operator=operator,
            timestamp=datetime.now(tz=timezone.utc),
            content=content,
            result=result,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        self._entries.append(entry)
        logger.info(
            "AUDIT: %s by %s on %s/%s → %s",
            action.value, operator, resource_type, resource_id, result.value,
        )
        return entry

    # ── Convenience methods ────────────────────────────────────────

    def log_plan_confirm(self, operator: str, incident_id: str, plan_id: str, action_type: str) -> AuditEntry:
        return self.log(
            action=AuditAction.PLAN_CONFIRM,
            operator=operator,
            content={"incident_id": incident_id, "plan_id": plan_id, "action_type": action_type},
            resource_type="incident",
            resource_id=incident_id,
        )

    def log_override(self, operator: str, incident_id: str, original_plan_id: str, selected_plan_id: str, reason: str) -> AuditEntry:
        return self.log(
            action=AuditAction.PLAN_OVERRIDE,
            operator=operator,
            content={
                "incident_id": incident_id,
                "original_plan_id": original_plan_id,
                "selected_plan_id": selected_plan_id,
                "reason": reason,
            },
            resource_type="incident",
            resource_id=incident_id,
        )

    def log_template_publish(self, operator: str, template_id: str) -> AuditEntry:
        return self.log(
            action=AuditAction.TEMPLATE_PUBLISH,
            operator=operator,
            content={"template_id": template_id},
            resource_type="case_template",
            resource_id=template_id,
        )

    def log_module_version_change(self, operator: str, module_name: str, old_version: str, new_version: str) -> AuditEntry:
        return self.log(
            action=AuditAction.MODULE_VERSION_CHANGE,
            operator=operator,
            content={"module_name": module_name, "old_version": old_version, "new_version": new_version},
            resource_type="strategy_module",
            resource_id=module_name,
        )

    def log_solver_portfolio_change(self, operator: str, change_description: str, config: dict[str, Any]) -> AuditEntry:
        return self.log(
            action=AuditAction.SOLVER_PORTFOLIO_CHANGE,
            operator=operator,
            content={"description": change_description, "config": config},
            resource_type="solver_portfolio",
            resource_id="global",
        )

    # ── Query ──────────────────────────────────────────────────────

    def get_entries(
        self,
        action: AuditAction | None = None,
        operator: str | None = None,
        resource_type: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query audit entries with optional filters."""
        entries = self._entries
        if action:
            entries = [e for e in entries if e.action == action]
        if operator:
            entries = [e for e in entries if e.operator == operator]
        if resource_type:
            entries = [e for e in entries if e.resource_type == resource_type]
        return list(reversed(entries))[:limit]

    def get_all_entries(self) -> list[AuditEntry]:
        return list(self._entries)


# Module-level singleton
audit_logger = AuditLogger()
