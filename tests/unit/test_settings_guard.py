"""Capability-driven settings validation (core.check_settings_supported).

The guard's whole contract is the explicit/default distinction: settings
provided through the environment must be rejected on backends that cannot
honor them, while untouched defaults must pass — otherwise Claude-tier
defaults (permission_mode, max_thinking_tokens) would break every
Codex/OpenAI run.
"""

import pytest
from pydantic_settings import SettingsConfigDict

from lup.adapters.common import AdapterCapabilities
from lup_template.agent import core
from lup_template.agent.config import Settings

GUARDED_ENV = (
    "AGENT_MAX_TURNS",
    "AGENT_PERMISSION_MODE",
    "AGENT_MAX_THINKING_TOKENS",
    "AGENT_TURN_TIMEOUT_SECONDS",
)


class EnvOnlySettings(Settings):
    """Settings built from the process env only — no .env/.env.local files."""

    model_config = SettingsConfigDict(env_file=None)


def intersection_capabilities() -> AdapterCapabilities:
    return AdapterCapabilities(
        hooks=False,
        native_subagents=False,
        streaming="post_hoc",
        interrupt=False,
        stop_event=False,
        cost_reporting="none",
        duration_reporting=False,
        permission_modes=False,
        max_turns=False,
        max_thinking_tokens=False,
        background_tools=False,
        realtime="relay",
        turn_timeout=False,
    )


def full_capabilities() -> AdapterCapabilities:
    return AdapterCapabilities(
        hooks=True,
        native_subagents=True,
        streaming="live",
        interrupt=True,
        stop_event=True,
        cost_reporting="native",
        duration_reporting=True,
        permission_modes=True,
        max_turns=True,
        max_thinking_tokens=True,
        background_tools=True,
        realtime="in_process",
        turn_timeout=True,
    )


def fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Build Settings from the current process env only (no .env files)."""
    built = EnvOnlySettings()
    monkeypatch.setattr(core, "settings", built)
    return built


def clear_guarded_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in GUARDED_ENV:
        monkeypatch.delenv(name, raising=False)


def test_defaults_pass_on_intersection_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_guarded_env(monkeypatch)
    fresh_settings(monkeypatch)
    core.check_settings_supported(intersection_capabilities())


def test_explicit_max_turns_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_guarded_env(monkeypatch)
    monkeypatch.setenv("AGENT_MAX_TURNS", "5")
    fresh_settings(monkeypatch)
    with pytest.raises(ValueError, match="AGENT_MAX_TURNS"):
        core.check_settings_supported(intersection_capabilities())


def test_explicit_permission_mode_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_guarded_env(monkeypatch)
    monkeypatch.setenv("AGENT_PERMISSION_MODE", "plan")
    fresh_settings(monkeypatch)
    with pytest.raises(ValueError, match="AGENT_PERMISSION_MODE"):
        core.check_settings_supported(intersection_capabilities())


def test_explicit_turn_timeout_rejected_without_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_guarded_env(monkeypatch)
    monkeypatch.setenv("AGENT_TURN_TIMEOUT_SECONDS", "120")
    fresh_settings(monkeypatch)
    with pytest.raises(ValueError, match="AGENT_TURN_TIMEOUT_SECONDS"):
        core.check_settings_supported(intersection_capabilities())


def test_all_offenders_listed_together(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_guarded_env(monkeypatch)
    monkeypatch.setenv("AGENT_MAX_TURNS", "5")
    monkeypatch.setenv("AGENT_MAX_THINKING_TOKENS", "1024")
    fresh_settings(monkeypatch)
    with pytest.raises(ValueError) as excinfo:
        core.check_settings_supported(intersection_capabilities())
    assert "AGENT_MAX_TURNS" in str(excinfo.value)
    assert "AGENT_MAX_THINKING_TOKENS" in str(excinfo.value)


def test_explicit_settings_pass_on_full_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_guarded_env(monkeypatch)
    monkeypatch.setenv("AGENT_MAX_TURNS", "5")
    monkeypatch.setenv("AGENT_PERMISSION_MODE", "plan")
    fresh_settings(monkeypatch)
    core.check_settings_supported(full_capabilities())
