"""Unit tests for the ModuleVersionRegistry service.

Covers:
- Independent version management for strategy modules (Req 26.1)
- Invocation recording with params, result, and degradation (Req 22.6, 26.2)
- Scenario-based version resolution via configuration (Req 22.4)
- Auto-fallback on module failure with degradation logging (Req 22.7)
- Version listing and history retrieval (Req 22.5)
"""

from datetime import datetime, timezone

import pytest

from app.services.module_version_registry import (
    ModuleInvocationRecord,
    ModuleVersionRegistry,
    ScenarioVersionConfig,
)


# ── Fixtures ────────────────────────────────────────────────────────


def _make_registry(**kwargs) -> ModuleVersionRegistry:
    return ModuleVersionRegistry(**kwargs)


def _populated_registry() -> ModuleVersionRegistry:
    """Registry with all three strategy modules registered."""
    reg = _make_registry(
        fallback_versions={
            ModuleVersionRegistry.RULE_SELECTOR: "0.9.0",
            ModuleVersionRegistry.NEIGHBORHOOD_SELECTOR: "0.9.0",
            ModuleVersionRegistry.REPAIR_POLICY_ADVISOR: "0.9.0",
        },
    )
    reg.register_module(ModuleVersionRegistry.RULE_SELECTOR, "1.0.0")
    reg.register_module(ModuleVersionRegistry.NEIGHBORHOOD_SELECTOR, "1.0.0")
    reg.register_module(ModuleVersionRegistry.REPAIR_POLICY_ADVISOR, "1.0.0")
    return reg


# ── Version management ──────────────────────────────────────────────


class TestVersionManagement:
    """Req 26.1: independent version numbers per module."""

    def test_register_and_get_version(self):
        reg = _make_registry()
        reg.register_module("Rule_Selector", "1.0.0")
        assert reg.get_version("Rule_Selector") == "1.0.0"

    def test_get_version_unregistered_raises(self):
        reg = _make_registry()
        with pytest.raises(KeyError, match="not registered"):
            reg.get_version("Unknown_Module")

    def test_set_version_updates(self):
        reg = _make_registry()
        reg.register_module("Rule_Selector", "1.0.0")
        reg.set_version("Rule_Selector", "1.1.0")
    
        assert reg.get_version("Rule_Selector") == "1.1.0"

    def test_set_version_unregistered_raises(self):
        reg = _make_registry()
        with pytest.raises(KeyError, match="not registered"):
            reg.set_version("Rule_Selector", "2.0.0")

    def test_list_versions(self):
        reg = _populated_registry()
        versions = reg.list_versions()
        assert len(versions) == 3
        assert versions["Rule_Selector"] == "1.0.0"
        assert versions["Neighborhood_Selector"] == "1.0.0"
        assert versions["Repair_Policy_Advisor"] == "1.0.0"

    def test_list_versions_empty(self):
        reg = _make_registry()
        assert reg.list_versions() == {}

    def test_independent_versions(self):
        """Each module maintains its own version independently."""
        reg = _populated_registry()
        reg.set_version("Rule_Selector", "2.0.0")
        assert reg.get_version("Rule_Selector") == "2.0.0"
        assert reg.get_version("Neighborhood_Selector") == "1.0.0"
        assert reg.get_version("Repair_Policy_Advisor") == "1.0.0"


# ── Invocation recording ───────────────────────────────────────────


class TestInvocationRecording:
    """Req 22.6, 26.2: record module name, version, params, result."""

    def test_record_invocation(self):
        reg = _populated_registry()
        record = reg.record_invocation(
            module_name="Rule_Selector",
            version="1.0.0",
            params_summary={"strategy": "local_repair", "incident_id": "abc"},
            result_summary="Selected 2 rules",
            success=True,
        )
        assert isinstance(record, ModuleInvocationRecord)
        assert record.module_name == "Rule_Selector"
        assert record.version == "1.0.0"
        assert record.success is True
        assert record.degraded is False
        assert record.degradation_reason is None

    def test_record_with_custom_timestamp(self):
        reg = _populated_registry()
        ts = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        record = reg.record_invocation(
            module_name="Rule_Selector",
            version="1.0.0",
            params_summary={},
            result_summary="ok",
            success=True,
            timestamp=ts,
        )
        assert record.timestamp == ts

    def test_get_invocation_history_newest_first(self):
        reg = _populated_registry()
        for i in range(3):
            reg.record_invocation(
                module_name="Rule_Selector",
                version="1.0.0",
                params_summary={"call": i},
                result_summary=f"call-{i}",
                success=True,
            )
        history = reg.get_invocation_history("Rule_Selector")
        assert len(history) == 3
        # newest first
        assert history[0].result_summary == "call-2"
        assert history[2].result_summary == "call-0"

    def test_get_invocation_history_with_limit(self):
        reg = _populated_registry()
        for i in range(5):
            reg.record_invocation(
                module_name="Rule_Selector",
                version="1.0.0",
                params_summary={},
                result_summary=f"call-{i}",
                success=True,
            )
        history = reg.get_invocation_history("Rule_Selector", limit=2)
        assert len(history) == 2
        assert history[0].result_summary == "call-4"

    def test_get_invocation_history_empty(self):
        reg = _make_registry()
        assert reg.get_invocation_history("Unknown") == []

    def test_record_degraded_invocation(self):
        reg = _populated_registry()
        record = reg.record_invocation(
            module_name="Rule_Selector",
            version="1.0.0",
            params_summary={},
            result_summary="Failed, degraded",
            success=False,
            degraded=True,
            degradation_reason="Timeout after 3s",
        )
        assert record.success is False
        assert record.degraded is True
        assert "Timeout" in record.degradation_reason


# ── Scenario-based version resolution ──────────────────────────────


class TestScenarioVersionResolution:
    """Req 22.4: config-driven version selection per scenario."""

    def test_resolve_default_version(self):
        reg = _populated_registry()
        assert reg.resolve_version("Rule_Selector") == "1.0.0"

    def test_resolve_with_scenario_config(self):
        cfg = ScenarioVersionConfig(
            module_name="Rule_Selector",
            scenario_key="workshop=W1,incident_type=equipment_failure",
            version="2.0.0-beta",
        )
        reg = _populated_registry()
        reg.add_scenario_config(cfg)
        resolved = reg.resolve_version(
            "Rule_Selector",
            scenario_key="workshop=W1,incident_type=equipment_failure",
        )
        assert resolved == "2.0.0-beta"

    def test_resolve_falls_back_to_current_when_no_scenario_match(self):
        cfg = ScenarioVersionConfig(
            module_name="Rule_Selector",
            scenario_key="workshop=W2",
            version="2.0.0-beta",
        )
        reg = _populated_registry()
        reg.add_scenario_config(cfg)
        # Different scenario key → falls back to current version
        resolved = reg.resolve_version(
            "Rule_Selector", scenario_key="workshop=W1",
        )
        assert resolved == "1.0.0"

    def test_resolve_falls_back_to_fallback_version(self):
        reg = _make_registry(
            fallback_versions={"Rule_Selector": "0.9.0"},
        )
        # Not registered, but fallback exists
        resolved = reg.resolve_version("Rule_Selector")
        assert resolved == "0.9.0"

    def test_resolve_raises_when_nothing_available(self):
        reg = _make_registry()
        with pytest.raises(KeyError, match="Cannot resolve"):
            reg.resolve_version("Rule_Selector")

    def test_add_and_list_scenario_configs(self):
        reg = _make_registry()
        cfg = ScenarioVersionConfig(
            module_name="Rule_Selector",
            scenario_key="workshop=W1",
            version="2.0.0",
        )
        reg.add_scenario_config(cfg)
        configs = reg.list_scenario_configs()
        assert len(configs) == 1
        assert configs[0].version == "2.0.0"


# ── Fallback / degradation ─────────────────────────────────────────


class TestFallbackDegradation:
    """Req 22.7: auto-switch to fallback on failure + degradation log."""

    def test_handle_module_failure_switches_version(self):
        reg = _populated_registry()
        assert reg.get_version("Rule_Selector") == "1.0.0"

        fallback = reg.handle_module_failure(
            module_name="Rule_Selector",
            error=RuntimeError("solver timeout"),
            params_summary={"strategy": "local_repair"},
        )
        assert fallback == "0.9.0"
        assert reg.get_version("Rule_Selector") == "0.9.0"

    def test_handle_module_failure_records_degradation(self):
        reg = _populated_registry()
        reg.handle_module_failure(
            module_name="Rule_Selector",
            error=ValueError("bad input"),
        )
        history = reg.get_invocation_history("Rule_Selector", limit=1)
        assert len(history) == 1
        record = history[0]
        assert record.success is False
        assert record.degraded is True
        assert "bad input" in record.degradation_reason
        assert "Degraded to fallback" in record.degradation_reason

    def test_handle_module_failure_no_fallback_raises(self):
        reg = _make_registry()
        reg.register_module("Rule_Selector", "1.0.0")
        with pytest.raises(RuntimeError, match="No fallback"):
            reg.handle_module_failure(
                module_name="Rule_Selector",
                error=RuntimeError("fail"),
            )

    def test_set_and_get_fallback_version(self):
        reg = _make_registry()
        reg.set_fallback_version("Rule_Selector", "0.8.0")
        assert reg.get_fallback_version("Rule_Selector") == "0.8.0"

    def test_get_fallback_version_none_when_not_set(self):
        reg = _make_registry()
        assert reg.get_fallback_version("Rule_Selector") is None

    def test_multiple_failures_degrade_and_log(self):
        """Multiple failures should each be recorded."""
        reg = _populated_registry()
        reg.handle_module_failure(
            "Rule_Selector", RuntimeError("err1"),
        )
        reg.handle_module_failure(
            "Rule_Selector", RuntimeError("err2"),
        )
        history = reg.get_invocation_history("Rule_Selector")
        assert len(history) == 2
        assert all(r.degraded for r in history)


# ── Known module constants ──────────────────────────────────────────


class TestKnownModules:
    def test_known_module_constants(self):
        assert ModuleVersionRegistry.RULE_SELECTOR == "Rule_Selector"
        assert ModuleVersionRegistry.NEIGHBORHOOD_SELECTOR == "Neighborhood_Selector"
        assert ModuleVersionRegistry.REPAIR_POLICY_ADVISOR == "Repair_Policy_Advisor"
