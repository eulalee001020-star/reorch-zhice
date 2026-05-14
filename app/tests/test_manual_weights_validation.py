"""Tests for ManualWeightsValidator — Requirement 30.11.

Covers:
- Value range validation (each weight 0-1)
- Sum constraint validation (weights should sum to ~1.0)
- Default value fallback mechanism
- Invalid input returns structured error and preserves last valid config
"""

import pytest

from app.services.manual_weights_validator import (
    DEFAULT_WEIGHTS,
    VALID_WEIGHT_KEYS,
    ManualWeightsValidator,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _balanced_weights() -> dict[str, float]:
    """Return a valid weight dict that sums to 1.0."""
    return dict(DEFAULT_WEIGHTS)


def _custom_valid_weights() -> dict[str, float]:
    return {
        "delayed_order_count": 0.30,
        "max_delay_minutes": 0.10,
        "spi": 0.20,
        "resource_utilization_delta": 0.10,
        "changeover_count_delta": 0.10,
        "critical_order_otd_impact": 0.20,
    }


# ── Value range tests ────────────────────────────────────────────────

class TestValueRange:
    def test_valid_weights_accepted(self):
        v = ManualWeightsValidator()
        result = v.validate(_balanced_weights())
        assert all(0 <= val <= 1 for val in result.values())

    def test_negative_value_rejected(self):
        v = ManualWeightsValidator()
        w = _balanced_weights()
        w["spi"] = -0.1
        with pytest.raises(ValueError, match="negative_value"):
            v.validate(w)

    def test_value_above_one_rejected(self):
        v = ManualWeightsValidator()
        w = _balanced_weights()
        w["spi"] = 1.5
        with pytest.raises(ValueError, match="out_of_range"):
            v.validate(w)

    def test_zero_weight_accepted(self):
        v = ManualWeightsValidator()
        w = _balanced_weights()
        w["changeover_count_delta"] = 0.0
        w["spi"] = 0.30  # keep sum ~1.0
        result = v.validate(w)
        assert result["changeover_count_delta"] == 0.0

    def test_boundary_one_accepted(self):
        v = ManualWeightsValidator()
        # All zero except one = 1.0 → sum = 1.0
        w = {k: 0.0 for k in VALID_WEIGHT_KEYS}
        w["delayed_order_count"] = 1.0
        result = v.validate(w)
        assert result["delayed_order_count"] == 1.0


# ── Sum constraint tests ─────────────────────────────────────────────

class TestSumConstraint:
    def test_exact_sum_one(self):
        v = ManualWeightsValidator()
        result = v.validate(_balanced_weights())
        assert abs(sum(result.values()) - 1.0) < 1e-9

    def test_sum_within_tolerance_low(self):
        """Sum = 0.90 should be accepted."""
        v = ManualWeightsValidator()
        w = {k: 0.15 for k in VALID_WEIGHT_KEYS}  # 6 * 0.15 = 0.90
        result = v.validate(w)
        assert abs(sum(result.values()) - 0.90) < 1e-9

    def test_sum_within_tolerance_high(self):
        """Sum ≈ 1.10 should be accepted."""
        v = ManualWeightsValidator()
        keys = sorted(VALID_WEIGHT_KEYS)
        w = {k: 1.10 / 6 for k in keys}
        # Adjust to get exactly 1.10
        diff = 1.10 - sum(w.values())
        w[keys[0]] += diff
        result = v.validate(w)
        assert sum(result.values()) <= 1.1 + 1e-9

    def test_sum_too_low_rejected(self):
        v = ManualWeightsValidator()
        w = {k: 0.1 for k in VALID_WEIGHT_KEYS}  # 6 * 0.1 = 0.6
        with pytest.raises(ValueError, match="sum_out_of_range"):
            v.validate(w)

    def test_sum_too_high_rejected(self):
        v = ManualWeightsValidator()
        w = {k: 0.5 for k in VALID_WEIGHT_KEYS}  # 6 * 0.5 = 3.0
        with pytest.raises(ValueError, match="sum_out_of_range"):
            v.validate(w)


# ── Default fallback tests ───────────────────────────────────────────

class TestDefaultFallback:
    def test_initial_last_valid_is_defaults(self):
        v = ManualWeightsValidator()
        assert v.last_valid == DEFAULT_WEIGHTS

    def test_defaults_property(self):
        v = ManualWeightsValidator()
        assert v.defaults == DEFAULT_WEIGHTS

    def test_defaults_sum_to_one(self):
        assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9

    def test_defaults_all_in_range(self):
        for val in DEFAULT_WEIGHTS.values():
            assert 0 <= val <= 1


# ── Invalid input preserves last valid config ────────────────────────

class TestPreservesLastValid:
    def test_invalid_does_not_update_last_valid(self):
        v = ManualWeightsValidator()
        good = _custom_valid_weights()
        v.validate(good)
        assert v.last_valid == good

        bad = _balanced_weights()
        bad["spi"] = -1.0
        with pytest.raises(ValueError):
            v.validate(bad)

        # last_valid should still be the good config
        assert v.last_valid == good

    def test_successive_valid_updates_last_valid(self):
        v = ManualWeightsValidator()
        first = _balanced_weights()
        v.validate(first)
        assert v.last_valid == first

        second = _custom_valid_weights()
        v.validate(second)
        assert v.last_valid == second

    def test_unknown_key_rejected_with_structured_error(self):
        v = ManualWeightsValidator()
        w = _balanced_weights()
        w["bogus_key"] = 0.1
        with pytest.raises(ValueError, match="unknown_keys"):
            v.validate(w)

    def test_structured_error_contains_all_issues(self):
        v = ManualWeightsValidator()
        w = {k: -0.5 for k in VALID_WEIGHT_KEYS}
        w["unknown"] = 0.1
        with pytest.raises(ValueError) as exc_info:
            v.validate(w)
        msg = str(exc_info.value)
        assert "unknown_keys" in msg
        assert "negative_value" in msg
        assert "sum_out_of_range" in msg
