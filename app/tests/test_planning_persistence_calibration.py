"""Supply/dispatch durability and parameter calibration regression tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api.dispatch import create_dispatch_snapshot, current_dispatch
from app.api.supply import create_supply_snapshot, current_supply
from app.models.dispatch import DispatchCostWeights, DispatchSnapshot
from app.models.supply import SupplySnapshot
from app.services.dispatch.planner import build_problem
from app.services.storage.operational_store import RelationalOperationalStore
from app.services.storage.runtime_backup import RuntimeBackupService
from app.services.validation.parameter_calibration import calibrate


@pytest.mark.asyncio
async def test_import_survives_store_restart_and_backup(monkeypatch, tmp_path):
    from app.api import production_runtime

    url = f"sqlite+pysqlite:///{tmp_path}/planning.db"
    store = RelationalOperationalStore(url)
    monkeypatch.setattr(production_runtime, "_store", store)
    supply = SupplySnapshot(captured_at=datetime.now(UTC), workshop_id="test")
    dispatch = DispatchSnapshot(
        captured_at=datetime.now(UTC), cost_weights=DispatchCostWeights(late=12)
    )
    await create_supply_snapshot(supply)
    await create_dispatch_snapshot(dispatch)
    store.engine.dispose()
    reopened = RelationalOperationalStore(url)
    monkeypatch.setattr(production_runtime, "_store", reopened)
    assert current_supply() == supply
    assert current_dispatch() == dispatch
    target = RelationalOperationalStore()
    result = RuntimeBackupService().drill(reopened, target, tmp_path / "backup.json")
    assert result["restore_verified"]
    assert target.latest_planning_snapshot("dispatch") == dispatch.model_dump(mode="json")
    target.engine.dispose()


@pytest.mark.asyncio
async def test_idempotent_import_and_id_collision_leave_head_unchanged():
    from fastapi import HTTPException

    first = SupplySnapshot(captured_at=datetime.now(UTC), workshop_id="first")
    second = SupplySnapshot(captured_at=datetime.now(UTC), workshop_id="second")
    await create_supply_snapshot(first)
    await create_supply_snapshot(second)
    await create_supply_snapshot(first)
    assert current_supply() == second
    with pytest.raises(HTTPException) as error:
        await create_supply_snapshot(first.model_copy(update={"workshop_id": "changed"}))
    assert error.value.status_code == 409
    assert current_supply() == second


@pytest.mark.asyncio
async def test_failed_commit_never_reports_success(monkeypatch):
    from app.api.production_runtime import get_operational_store

    def unavailable(*args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(get_operational_store(), "save_planning_snapshot", unavailable)
    with pytest.raises(RuntimeError, match="database unavailable"):
        await create_dispatch_snapshot(DispatchSnapshot(captured_at=datetime.now(UTC)))
    assert current_dispatch() is None


def observations():
    return json.loads(Path("data/calibration/test_observations.json").read_text())


def test_calibration_uses_holdout_and_flows_into_routing():
    report = calibrate(observations())
    assert report["dispatch_parameters"]["speed_kmh"] == 30
    assert report["travel_validation"]["holdout_mae_minutes"] == 1
    assert report["supplier_buffer_validation"]["holdout_coverage"] == 0.6
    snapshot = DispatchSnapshot(captured_at=datetime.now(UTC), **report["dispatch_parameters"])
    problem = build_problem(snapshot, {})
    assert problem.speed_kmh == 30 and problem.weights.late == 10
    assert problem.weights.vehicle == 60


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_costs_reject_invalid_values(value):
    with pytest.raises(ValidationError):
        DispatchCostWeights(late=value)


def test_calibration_rejects_missing_holdout_or_invalid_observations():
    data = observations()
    data["drives"] = [row for row in data["drives"] if row["split"] == "train"]
    with pytest.raises(ValueError, match="holdout"):
        calibrate(data)
    data = observations()
    data["drives"][0]["minutes"] = 0
    with pytest.raises(ValueError):
        calibrate(data)


def test_additive_migration_roundtrip():
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    spec = importlib.util.spec_from_file_location(
        "planning_migration", "alembic/versions/005_planning_snapshots.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()  # safe after runtime create_all
        assert inspect(connection).has_table("planning_snapshots")
        migration.downgrade()
        assert not inspect(connection).has_table("planning_snapshots")
    engine.dispose()
