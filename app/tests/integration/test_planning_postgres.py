"""Opt-in PostgreSQL restart, backup/restore and sequence regression."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.services.storage.operational_store import RelationalOperationalStore
from app.services.storage.runtime_backup import RuntimeBackupService

pytestmark = pytest.mark.skipif(
    not os.getenv("PLANNING_TEST_DATABASE_URL"), reason="isolated PostgreSQL not configured"
)


def test_postgres_snapshot_recovery_and_backup_sequence(tmp_path):
    url = os.environ["PLANNING_TEST_DATABASE_URL"]
    assert make_url(url).database == "reorch_runtime_test", "dedicated test database required"
    store = RelationalOperationalStore(url)
    store.clear_runtime_state()
    try:
        store.save_planning_snapshot("supply", "s1", {"item": "test"})
        store.save_planning_snapshot("dispatch", "d1", {"weights": {"late": 10}})
        store.engine.dispose()
        store = RelationalOperationalStore(url)
        assert store.latest_planning_snapshot("supply") == {"item": "test"}
        backup = RuntimeBackupService()
        path = tmp_path / "postgres-backup.json"
        backup.create_backup(store, path)
        store.clear_runtime_state()
        with store.engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('planning_snapshots', 'sequence'), 1, false)"
                )
            )
        assert backup.restore_backup(store, path)["restore_verified"]
        store.save_planning_snapshot("dispatch", "d2", {"weights": {"late": 20}})
        assert store.latest_planning_snapshot("dispatch") == {"weights": {"late": 20}}
    finally:
        store.clear_runtime_state()
        store.engine.dispose()
