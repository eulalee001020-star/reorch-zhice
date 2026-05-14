"""Module Version Registry for the ReOrch Solver Policy Layer.

Provides centralised version governance for strategy modules:
Rule_Selector, Neighborhood_Selector, Repair_Policy_Advisor.

Key capabilities (Req 22.4, 22.5, 22.6, 22.7, 26.1, 26.2):
- Maintain independent version numbers per module
- Record every invocation: module name, version, key params, result
- Support configuration-driven version selection per scenario
- Auto-fallback to a predefined safe version on module failure
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModuleInvocationRecord:
    """Immutable record of a single strategy-module invocation (Req 22.6)."""

    module_name: str
    version: str
    params_summary: dict[str, Any]
    result_summary: str
    success: bool
    timestamp: datetime
    degraded: bool = False
    degradation_reason: str | None = None


@dataclass
class ScenarioVersionConfig:
    """Maps a scenario key to a specific module version (Req 22.4).

    ``scenario_key`` is a free-form string such as
    ``"workshop=W1,incident_type=equipment_failure"`` that the caller
    builds from the current context.
    """

    module_name: str
    scenario_key: str
    version: str


class ModuleVersionRegistry:
    """In-memory registry for strategy-module version governance.

    Responsibilities:
    - Track current version per module (Req 26.1)
    - Record invocation history per module (Req 22.6, 26.2)
    - Resolve version by scenario config (Req 22.4)
    - Auto-fallback on failure with degradation logging (Req 22.7)
    """

    # Well-known module names
    RULE_SELECTOR = "Rule_Selector"
    NEIGHBORHOOD_SELECTOR = "Neighborhood_Selector"
    REPAIR_POLICY_ADVISOR = "Repair_Policy_Advisor"

    _KNOWN_MODULES = frozenset(
        {RULE_SELECTOR, NEIGHBORHOOD_SELECTOR, REPAIR_POLICY_ADVISOR}
    )

    def __init__(
        self,
        fallback_versions: dict[str, str] | None = None,
        scenario_configs: list[ScenarioVersionConfig] | None = None,
    ) -> None:
        # module_name → current version string
        self._versions: dict[str, str] = {}
        # module_name → ordered list of invocation records
        self._history: dict[str, list[ModuleInvocationRecord]] = {}
        # module_name → fallback version string
        self._fallback_versions: dict[str, str] = fallback_versions or {}
        # scenario configs for version resolution
        self._scenario_configs: list[ScenarioVersionConfig] = (
            scenario_configs or []
        )

    # ── Version management ──────────────────────────────────────────

    def register_module(self, module_name: str, version: str) -> None:
        """Register or update the current version for *module_name*."""
        self._versions[module_name] = version
        self._history.setdefault(module_name, [])
        logger.info(
            "Module registered: %s v%s", module_name, version,
        )

    def get_version(self, module_name: str) -> str:
        """Return the current version string for *module_name*.

        Raises ``KeyError`` if the module has not been registered.
        """
        if module_name not in self._versions:
            raise KeyError(f"Module '{module_name}' is not registered")
        return self._versions[module_name]

    def set_version(self, module_name: str, version: str) -> None:
        """Update the current version for an already-registered module.

        Raises ``KeyError`` if the module has not been registered.
        """
        if module_name not in self._versions:
            raise KeyError(f"Module '{module_name}' is not registered")
        old = self._versions[module_name]
        self._versions[module_name] = version
        logger.info(
            "Module version updated: %s %s → %s",
            module_name, old, version,
        )

    def list_versions(self) -> dict[str, str]:
        """Return a snapshot of ``{module_name: version}`` for all modules."""
        return dict(self._versions)

    # ── Scenario-based version resolution (Req 22.4) ────────────────

    def resolve_version(
        self, module_name: str, scenario_key: str | None = None,
    ) -> str:
        """Resolve the version to use for *module_name* in *scenario_key*.

        Resolution order:
        1. Matching ``ScenarioVersionConfig`` (if *scenario_key* given)
        2. Current registered version
        3. Fallback version (if registered version missing)

        Raises ``KeyError`` when no version can be resolved.
        """
        if scenario_key:
            for cfg in self._scenario_configs:
                if (
                    cfg.module_name == module_name
                    and cfg.scenario_key == scenario_key
                ):
                    return cfg.version

        if module_name in self._versions:
            return self._versions[module_name]

        if module_name in self._fallback_versions:
            return self._fallback_versions[module_name]

        raise KeyError(
            f"Cannot resolve version for module '{module_name}'"
        )

    # ── Invocation recording (Req 22.6, 26.2) ──────────────────────

    def record_invocation(
        self,
        module_name: str,
        version: str,
        params_summary: dict[str, Any],
        result_summary: str,
        success: bool,
        degraded: bool = False,
        degradation_reason: str | None = None,
        timestamp: datetime | None = None,
    ) -> ModuleInvocationRecord:
        """Persist an invocation record and return it."""
        ts = timestamp or datetime.now(tz=timezone.utc)
        record = ModuleInvocationRecord(
            module_name=module_name,
            version=version,
            params_summary=params_summary,
            result_summary=result_summary,
            success=success,
            timestamp=ts,
            degraded=degraded,
            degradation_reason=degradation_reason,
        )
        self._history.setdefault(module_name, []).append(record)
        logger.info(
            "Invocation recorded: %s v%s success=%s degraded=%s",
            module_name, version, success, degraded,
        )
        return record

    def get_invocation_history(
        self, module_name: str, limit: int | None = None,
    ) -> list[ModuleInvocationRecord]:
        """Return invocation records for *module_name*, newest first.

        If *limit* is given, return at most that many records.
        """
        records = list(reversed(self._history.get(module_name, [])))
        if limit is not None:
            records = records[:limit]
        return records

    # ── Fallback / degradation (Req 22.7) ───────────────────────────

    def set_fallback_version(
        self, module_name: str, version: str,
    ) -> None:
        """Define or update the fallback version for *module_name*."""
        self._fallback_versions[module_name] = version

    def get_fallback_version(self, module_name: str) -> str | None:
        """Return the fallback version, or ``None`` if not set."""
        return self._fallback_versions.get(module_name)

    def handle_module_failure(
        self,
        module_name: str,
        error: Exception,
        params_summary: dict[str, Any] | None = None,
    ) -> str:
        """Handle a module invocation failure (Req 22.7).

        1. Switch the module's current version to its fallback version.
        2. Record a degradation invocation log entry.
        3. Return the fallback version string.

        Raises ``RuntimeError`` if no fallback version is configured.
        """
        fallback = self._fallback_versions.get(module_name)
        if fallback is None:
            raise RuntimeError(
                f"No fallback version configured for module '{module_name}'"
            )

        original_version = self._versions.get(module_name, "unknown")
        reason = (
            f"Module '{module_name}' v{original_version} failed: "
            f"{type(error).__name__}: {error}. "
            f"Degraded to fallback v{fallback}."
        )

        # Switch to fallback
        self._versions[module_name] = fallback

        # Record degradation
        self.record_invocation(
            module_name=module_name,
            version=original_version,
            params_summary=params_summary or {},
            result_summary=reason,
            success=False,
            degraded=True,
            degradation_reason=reason,
        )

        logger.warning(reason)
        return fallback

    # ── Scenario config management ──────────────────────────────────

    def add_scenario_config(self, config: ScenarioVersionConfig) -> None:
        """Add a scenario-specific version override."""
        self._scenario_configs.append(config)

    def list_scenario_configs(self) -> list[ScenarioVersionConfig]:
        """Return all scenario version configs."""
        return list(self._scenario_configs)
