"""ManualWeightsValidator — validates and normalizes manual_weights dicts.

Ensures each weight is in [0, 1], the sum is within tolerance [0.9, 1.1],
and returns normalized weights.  Falls back to defaults on invalid input.

Requirement: 30.11
"""

from __future__ import annotations

VALID_WEIGHT_KEYS: frozenset[str] = frozenset(
    {
        "delayed_order_count",
        "max_delay_minutes",
        "spi",
        "resource_utilization_delta",
        "changeover_count_delta",
        "critical_order_otd_impact",
    }
)

DEFAULT_WEIGHTS: dict[str, float] = {
    "delayed_order_count": 0.20,
    "max_delay_minutes": 0.15,
    "spi": 0.20,
    "resource_utilization_delta": 0.15,
    "changeover_count_delta": 0.10,
    "critical_order_otd_impact": 0.20,
}

_SUM_LOWER = 0.9
_SUM_UPPER = 1.1


class ManualWeightsValidator:
    """Stateful validator that remembers the last valid configuration."""

    def __init__(self) -> None:
        self._last_valid: dict[str, float] = dict(DEFAULT_WEIGHTS)

    # -- public API --------------------------------------------------------

    def validate(self, weights: dict[str, float]) -> dict[str, float]:
        """Validate *weights* and return normalised copy.

        Raises ``ValueError`` with a structured message when validation fails.
        The internal ``last_valid`` config is **not** updated on failure.
        """
        errors: list[str] = []

        # 1. Check for unknown keys
        unknown = set(weights.keys()) - VALID_WEIGHT_KEYS
        if unknown:
            errors.append(f"unknown_keys: {sorted(unknown)}")

        # 2. Check each value in [0, 1] and no negatives
        for key, val in weights.items():
            if key not in VALID_WEIGHT_KEYS:
                continue
            if not isinstance(val, (int, float)):
                errors.append(f"non_numeric: {key}={val!r}")
                continue
            if val < 0:
                errors.append(f"negative_value: {key}={val}")
            elif val > 1:
                errors.append(f"out_of_range: {key}={val} (must be 0-1)")

        # 3. Sum constraint
        known_vals = [
            v for k, v in weights.items()
            if k in VALID_WEIGHT_KEYS and isinstance(v, (int, float))
        ]
        total = sum(known_vals)
        _eps = 1e-9
        if not (_SUM_LOWER - _eps <= total <= _SUM_UPPER + _eps):
            errors.append(
                f"sum_out_of_range: {total:.4f} (must be in [{_SUM_LOWER}, {_SUM_UPPER}])"
            )

        if errors:
            raise ValueError("; ".join(errors))

        # Build normalised copy (only valid keys)
        normalised = {k: float(weights[k]) for k in VALID_WEIGHT_KEYS if k in weights}
        self._last_valid = normalised
        return normalised

    @property
    def last_valid(self) -> dict[str, float]:
        """Return the last successfully validated weights (or defaults)."""
        return dict(self._last_valid)

    @property
    def defaults(self) -> dict[str, float]:
        return dict(DEFAULT_WEIGHTS)
