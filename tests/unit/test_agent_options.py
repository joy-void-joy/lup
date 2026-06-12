"""build_options wiring: limits from settings and optional sandbox server."""

from pathlib import Path

import pytest

from lup.notes import NotesConfig

from lup_template.agent.config import settings
from lup_template.agent.core import build_options


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

    options = build_options(notes, sandbox=None)

    assert options.max_turns == 7
    assert options.max_budget_usd == 2.5


def test_limits_default_to_unlimited(
    notes: NotesConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "max_turns", None)
    monkeypatch.setattr(settings, "max_budget_usd", None)

    options = build_options(notes, sandbox=None)

    assert options.max_turns is None
    assert options.max_budget_usd is None


def test_sandbox_enabled_parses_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from lup_template.agent.config import Settings

    monkeypatch.setenv("AGENT_SANDBOX_ENABLED", "false")
    assert Settings.model_validate({}).sandbox_enabled is False

    monkeypatch.setenv("AGENT_SANDBOX_ENABLED", "true")
    assert Settings.model_validate({}).sandbox_enabled is True


def test_no_sandbox_registers_no_sandbox_server(notes: NotesConfig) -> None:
    options = build_options(notes, sandbox=None)

    servers = options.mcp_servers
    assert isinstance(servers, dict)
    # The example group is template sample code, not a session tool group.
    assert set(servers) == {"notes"}
