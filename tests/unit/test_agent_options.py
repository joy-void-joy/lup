"""build_session_options wiring: limits from settings and the served tool servers.

The in-process assembly produces a backend-agnostic ``LupAgentOptions``; the
Claude builder turns it into native options later. These pin that session
limits reach the neutral object and that the example group never ships as a
session tool server.
"""

from pathlib import Path

import pytest

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
