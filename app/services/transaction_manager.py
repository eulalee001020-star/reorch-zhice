"""Database Transaction & Rollback Mechanism.

Validates: Requirements 17.2, 17.4

Provides:
- Transaction failure → rollback to consistent state and notify user
- DecisionRecord referential integrity enforcement
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable
from uuid import UUID

logger = logging.getLogger(__name__)


class TransactionError(Exception):
    """Raised when a transaction fails and is rolled back."""

    def __init__(self, operation: str, reason: str, rollback_performed: bool = True) -> None:
        self.operation = operation
        self.reason = reason
        self.rollback_performed = rollback_performed
        super().__init__(f"Transaction failed [{operation}]: {reason} (rollback={'yes' if rollback_performed else 'no'})")


class ReferentialIntegrityError(Exception):
    """Raised when DecisionRecord references are invalid."""

    def __init__(self, record_id: str, missing_refs: list[str]) -> None:
        self.record_id = record_id
        self.missing_refs = missing_refs
        super().__init__(f"DecisionRecord {record_id} has invalid references: {missing_refs}")


@dataclass
class TransactionResult:
    """Result of a managed transaction."""
    success: bool
    operation: str
    data: Any = None
    error: str | None = None
    rolled_back: bool = False
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(tz=timezone.utc).isoformat()


class TransactionManager:
    """In-memory transaction manager for MVP.

    Provides transaction-like semantics with rollback support.
    In production, this wraps SQLAlchemy async sessions.
    """

    def __init__(self) -> None:
        self._transaction_log: list[TransactionResult] = []
        self._rollback_handlers: dict[str, Callable[[], Awaitable[None]]] = {}
        # In-memory entity stores for referential integrity checks
        self._known_incidents: set[str] = set()
        self._known_plans: set[str] = set()
        self._known_decisions: set[str] = set()

    def register_entity(self, entity_type: str, entity_id: str) -> None:
        """Register an entity for referential integrity tracking."""
        store = self._get_store(entity_type)
        if store is not None:
            store.add(entity_id)

    def _get_store(self, entity_type: str) -> set[str] | None:
        stores = {
            "incident": self._known_incidents,
            "plan": self._known_plans,
            "decision": self._known_decisions,
        }
        return stores.get(entity_type)

    # ── Transaction execution ──────────────────────────────────────

    async def execute_transaction(
        self,
        operation: str,
        action: Callable[[], Awaitable[Any]],
        rollback: Callable[[], Awaitable[None]] | None = None,
    ) -> TransactionResult:
        """Execute an action within a transaction boundary.

        On failure, calls the rollback handler and records the failure.
        """
        try:
            result_data = await action()
            tx_result = TransactionResult(success=True, operation=operation, data=result_data)
            self._transaction_log.append(tx_result)
            return tx_result
        except Exception as exc:
            rolled_back = False
            if rollback:
                try:
                    await rollback()
                    rolled_back = True
                except Exception as rb_exc:
                    logger.error("Rollback failed for %s: %s", operation, rb_exc)

            tx_result = TransactionResult(
                success=False,
                operation=operation,
                error=str(exc),
                rolled_back=rolled_back,
            )
            self._transaction_log.append(tx_result)
            logger.error("Transaction failed [%s]: %s (rollback=%s)", operation, exc, rolled_back)
            raise TransactionError(operation, str(exc), rolled_back) from exc

    # ── Referential integrity (Req 17.4) ───────────────────────────

    def validate_decision_record_refs(
        self,
        decision_record_id: str,
        incident_id: str,
        plan_ids: list[str],
    ) -> None:
        """Validate that a DecisionRecord's references are valid.

        Raises ReferentialIntegrityError if any referenced entity is missing.
        """
        missing: list[str] = []
        if incident_id not in self._known_incidents:
            missing.append(f"incident:{incident_id}")
        for pid in plan_ids:
            if pid not in self._known_plans:
                missing.append(f"plan:{pid}")
        if missing:
            raise ReferentialIntegrityError(decision_record_id, missing)

    # ── Query ──────────────────────────────────────────────────────

    def get_transaction_log(self, limit: int = 50) -> list[TransactionResult]:
        return list(reversed(self._transaction_log))[:limit]


# Module-level singleton
transaction_manager = TransactionManager()
