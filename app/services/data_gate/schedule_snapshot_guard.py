"""ScheduleSnapshot Immutability Guard.

Validates: Requirements 17.3

Ensures that ScheduleSnapshot objects remain immutable after creation
during the entire decision flow. Schedule changes do not affect
already-created snapshots.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from typing import Any
from uuid import UUID

from app.models.schedule import ScheduleSnapshot

logger = logging.getLogger(__name__)


class SnapshotImmutabilityError(Exception):
    """Raised when an attempt is made to modify a frozen snapshot."""

    def __init__(self, snapshot_id: str) -> None:
        self.snapshot_id = snapshot_id
        super().__init__(f"ScheduleSnapshot {snapshot_id} is immutable and cannot be modified")


class ScheduleSnapshotGuard:
    """Guards ScheduleSnapshot immutability during decision flows.

    Once a snapshot is registered (frozen), any attempt to modify it
    raises SnapshotImmutabilityError. The guard stores a deep copy
    and a content hash to detect tampering.
    """

    def __init__(self) -> None:
        # snapshot_id → (frozen deep copy, content hash)
        self._frozen: dict[str, tuple[ScheduleSnapshot, str]] = {}

    @staticmethod
    def _compute_hash(snapshot: ScheduleSnapshot) -> str:
        """Compute a deterministic hash of snapshot content."""
        data = snapshot.model_dump(mode="json")
        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def freeze(self, snapshot: ScheduleSnapshot) -> str:
        """Freeze a snapshot — makes it immutable for the decision flow.

        Returns the content hash.
        """
        sid = str(snapshot.snapshot_id)
        frozen_copy = snapshot.model_copy(deep=True)
        content_hash = self._compute_hash(frozen_copy)
        self._frozen[sid] = (frozen_copy, content_hash)
        logger.info("Snapshot %s frozen with hash %s", sid, content_hash[:12])
        return content_hash

    def is_frozen(self, snapshot_id: str | UUID) -> bool:
        """Check if a snapshot is frozen."""
        return str(snapshot_id) in self._frozen

    def verify_integrity(self, snapshot: ScheduleSnapshot) -> bool:
        """Verify that a snapshot has not been modified since freezing.

        Returns True if the snapshot matches its frozen state.
        Raises SnapshotImmutabilityError if tampered.
        """
        sid = str(snapshot.snapshot_id)
        if sid not in self._frozen:
            return True  # Not frozen, no integrity check needed

        _, original_hash = self._frozen[sid]
        current_hash = self._compute_hash(snapshot)

        if current_hash != original_hash:
            raise SnapshotImmutabilityError(sid)
        return True

    def get_frozen_snapshot(self, snapshot_id: str | UUID) -> ScheduleSnapshot | None:
        """Retrieve the frozen (immutable) copy of a snapshot."""
        entry = self._frozen.get(str(snapshot_id))
        if entry is None:
            return None
        return entry[0].model_copy(deep=True)

    def unfreeze(self, snapshot_id: str | UUID) -> None:
        """Remove a snapshot from the frozen registry (e.g., after decision closes)."""
        self._frozen.pop(str(snapshot_id), None)


# Module-level singleton
snapshot_guard = ScheduleSnapshotGuard()
