"""build_session_options wiring: limits, served tool servers, REPL overrides.

The in-process assembly produces a backend-agnostic ``LupAgentOptions``; the
Claude builder turns it into native options later. These pin that session
limits reach the neutral object, that the example group never ships as a
session tool server, and that the REPL's assembly overrides (``model``,
``toolless``, ``bare_prompt``) are realized in neutral terms.
"""

from pathlib import Path

import pytest

import lup_template.agent.core as core
from lup.workspace.notes import NotesConfig

from lup_template.agent.config import settings
from lup_template.agent.core import build_session_options


@pytest.fixture
def notes(tmp_path: Path) -> NotesConfig:
    return NotesConfig(
        session=tmp_path / "session",
        output=tmp_path / "outputs" / "task-1",
        trace_log=tmp_path / "logs" / "trace.md",
        rw=[tmp_path / "session"],
        ro=[],
    )


def test_limits_from_settings_reach_options(
    notes: NotesConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "max_turns", 7)
    monkeypatch.setattr(settings, "max_budget_usd", 2.5)

    options = build_session_options(notes)

    assert options.max_turns == 7
    assert options.max_budget_usd == 2.5


def test_limits_default_to_unlimited(
    notes: NotesConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "max_turns", None)
    monkeypatch.setattr(settings, "max_budget_usd", None)

    options = build_session_options(notes)

    assert options.max_turns is None
    assert options.max_budget_usd is None


def test_sandbox_enabled_parses_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from lup_template.agent.config import Settings

    monkeypatch.setenv("AGENT_SANDBOX_ENABLED", "false")
    assert Settings.model_validate({}).sandbox_enabled is False

    monkeypatch.setenv("AGENT_SANDBOX_ENABLED", "true")
    assert Settings.model_validate({}).sandbox_enabled is True


def test_no_sandbox_registers_no_sandbox_server(
    notes: NotesConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "sandbox_enabled", False)

    options = build_session_options(notes)

    # The example group is template sample code, not a session tool group.
    assert set(options.tool_servers) == {"notes"}
    # Sessions persist so `lup run --resume` can continue them.
    assert options.persist_session is True


def test_toolless_assembly_strips_tools_and_their_hooks(notes: NotesConfig) -> None:
    options = build_session_options(notes, toolless=True)

    assert not options.tool_servers
    assert not options.served_tool_groups
    assert not options.allowed_tools
    # The completion guard is the only Stop hook; a toolless session must
    # not be blocked from stopping over a submit tool it does not have.
    assert not options.hooks.stop
    # Permission enforcement stays.
    assert options.hooks.pre_tool_use


def test_toolless_never_builds_the_sandbox(
    notes: NotesConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_notes: NotesConfig) -> None:
        raise AssertionError("sandbox must not be built for a toolless session")

    monkeypatch.setattr(core, "build_session_sandbox", boom)
    build_session_options(notes, toolless=True)


def test_bare_prompt_is_empty_with_preset_off(notes: NotesConfig) -> None:
    options = build_session_options(notes, bare_prompt=True)
    assert options.system_prompt == ""
    assert options.coding_harness_preset is False

    default = build_session_options(notes)
    assert default.system_prompt
    assert default.coding_harness_preset is True


def test_model_override_reaches_options_and_subprocess_relay(
    notes: NotesConfig,
) -> None:
    options = build_session_options(notes, model="claude-sonnet-5")
    assert options.model == "claude-sonnet-5"
    assert options.mcp_env["AGENT_MODEL"] == "claude-sonnet-5"

    unset = build_session_options(notes)
    assert unset.model == settings.model
    assert unset.mcp_env["AGENT_MODEL"] == settings.model
