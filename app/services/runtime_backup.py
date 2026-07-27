"""Checksummed backup, restore, and verification for runtime state."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.operational_store import RelationalOperationalStore


class RuntimeBackupService:
    def create_backup(
        self, store: RelationalOperationalStore, path: Path
    ) -> dict[str, Any]:
        state = store.export_runtime_state()
        state_hash = _fingerprint(state)
        manifest = {
            "schema_version": "runtime-backup-v1",
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "state_sha256": state_hash,
            "table_counts": {name: len(rows) for name, rows in state.items()},
        }
        document = {"manifest": manifest, "state": state}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=True, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
        return manifest

    def restore_backup(
        self,
        target: RelationalOperationalStore,
        path: Path,
        *,
        clear_existing: bool = True,
    ) -> dict[str, Any]:
        document = json.loads(path.read_text(encoding="utf-8"))
        manifest = document.get("manifest", {})
        state = document.get("state", {})
        if manifest.get("schema_version") != "runtime-backup-v1":
            raise ValueError("unsupported_runtime_backup_schema")
        if _fingerprint(state) != manifest.get("state_sha256"):
            raise ValueError("runtime_backup_checksum_mismatch")
        target.import_runtime_state(state, clear_existing=clear_existing)
        restored = target.export_runtime_state()
        if _fingerprint(restored) != manifest.get("state_sha256"):
            raise ValueError("runtime_restore_verification_failed")
        return {
            **manifest,
            "restore_verified": True,
            "restored_table_counts": {
                name: len(rows) for name, rows in restored.items()
            },
        }

    def drill(
        self,
        source: RelationalOperationalStore,
        target: RelationalOperationalStore,
        path: Path,
    ) -> dict[str, Any]:
        manifest = self.create_backup(source, path)
        restored = self.restore_backup(target, path)
        return {
            "status": "passed",
            "backup_path": str(path),
            "state_sha256": manifest["state_sha256"],
            "table_counts": manifest["table_counts"],
            "restore_verified": restored["restore_verified"],
            "scope": "reorch_operational_runtime_state",
            "claim_boundary": (
                "This drill covers the ReOrch runtime schema. Customer PostgreSQL, "
                "object storage, and infrastructure restore still require an onsite drill."
            ),
        }


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()
