"""Regression floor for incident understanding without a model."""

from __future__ import annotations

from app.services.agent.incident_eval import load_cases, score


def test_dev_cases_stay_exact() -> None:
    dev = score(load_cases())["dev"]
    assert dev.exact == dev.total, dev.misses


def test_holdout_floor_and_no_unsafe_errors() -> None:
    scores = score(load_cases())
    holdout = scores["holdout"]
    assert holdout.total >= 12
    assert holdout.exact_rate >= 0.8, holdout.misses
    for item in scores.values():
        assert not item.unsafe_errors, item.unsafe_errors
