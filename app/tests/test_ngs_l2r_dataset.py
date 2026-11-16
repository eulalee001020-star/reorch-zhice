"""Pin the schema and documented facts of the NGS learning-to-rank set."""

from __future__ import annotations

import csv
from pathlib import Path

DATASET = (
    Path(__file__).resolve().parents[2]
    / "datasets"
    / "ngs_l2r_training"
    / "ngs_training_data.csv"
)
LABEL = "optimal_rank"
CONSTANT_COLUMNS = {"m_versatility_score", "reagent_stock", "m_reliability_factor"}


def _rows() -> list[dict[str, str]]:
    with DATASET.open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_shape_matches_data_card() -> None:
    rows = _rows()
    assert len(rows) == 554
    assert len(rows[0]) == 29
    assert list(rows[0])[-1] == LABEL


def test_values_are_numeric_and_complete() -> None:
    for row in _rows():
        for value in row.values():
            assert value != ""
            float(value)


def test_label_range_and_no_duplicates() -> None:
    rows = _rows()
    labels = [int(row[LABEL]) for row in rows]
    assert min(labels) == 1
    assert max(labels) == 42
    assert len({tuple(row.values()) for row in rows}) == len(rows)


def test_constant_columns_are_the_documented_ones() -> None:
    rows = _rows()
    constant = {
        name for name in rows[0] if len({row[name] for row in rows}) == 1
    }
    assert constant == CONSTANT_COLUMNS
