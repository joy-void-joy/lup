"""Application checkpoints around both native harness launchers."""

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest
import sh

import lup.devtools.harness.launch as launch


class Transcript:
    """The launch-facing half of a transcript, with observable closure."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.journal = Mock()

    def close(self, *, succeeded: bool) -> None:
        self.events.append(f"close:{succeeded}")


def composition() -> Mock:
    """A composition carrying the one plugin each launcher reads first."""
    plugin = Mock()
    plugin.name = "lup"
    plugin.marketplace = "test"
    built = Mock()
    built.recipe.source.plugins = [plugin]
    return built


def checkpoint(events: list[str]) -> launch.LaunchCheckpoint:
    """Record the provider a project checkpoint receives."""

    def record(*, provider: str) -> None:
        events.append(f"checkpoint:{provider}")

    return record


def test_claude_checkpoints_before_preflight_and_after_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    profiles = Mock()
    profiles.launch_home.return_value = None
    monkeypatch.setattr(
        launch,
        "ready_to_open",
        lambda _composition, _generate_only, _sentinels: events.append("ready") or [],
    )
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)
    monkeypatch.setattr(launch, "ambient_config_home", lambda *a, **k: tmp_path)
    monkeypatch.setattr(launch, "session_argv", lambda name, *a, **k: [name])
    monkeypatch.setattr(
        launch, "claude_sandbox_arguments", lambda _plugin, contained=False: []
    )
    monkeypatch.setattr(launch, "non_interactive_environment", lambda _env: {})
    monkeypatch.setattr(
        launch, "apply_sandbox_environment", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(launch, "ClaudeTranscripts", lambda _home: Mock())
    monkeypatch.setattr(
        launch,
        "start_harness_transcript",
        lambda *args, **kwargs: Transcript(events),
    )
    monkeypatch.setattr(
        sh,
        "Command",
        lambda _name: lambda *args, **kwargs: events.append("cli"),
    )

    launch.launch_claude(
        composition(), [], profiles, None, None, False, checkpoint=checkpoint(events)
    )

    assert events == [
        "checkpoint:claude",
        "ready",
        "cli",
        "close:True",
        "checkpoint:claude",
    ]


def test_codex_checkpoints_before_preflight_and_after_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    home = Mock(path=tmp_path / "home", isolated=False)
    installer = Mock()
    installer.temporary.return_value = nullcontext(Mock(installed_root=tmp_path))
    store = Mock()
    monkeypatch.setattr(
        launch,
        "ready_to_open",
        lambda _composition, _generate_only, _sentinels: events.append("ready") or [],
    )
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)
    monkeypatch.setattr(launch, "ambient_config_home", lambda *a, **k: tmp_path)
    monkeypatch.setattr(launch, "session_argv", lambda name, *a, **k: [name])
    monkeypatch.setattr(launch, "non_interactive_environment", lambda _environment: {})
    monkeypatch.setattr(
        launch,
        "codex_sandbox_arguments",
        lambda _plugin, _environment, _args, contained=False: [],
    )
    monkeypatch.setattr(launch, "CodexWorktreeHomeStore", lambda: store)
    monkeypatch.setattr(launch, "select_codex_home", lambda *args: home)
    monkeypatch.setattr(launch, "codex_login_preflight", lambda *args: None)
    monkeypatch.setattr(launch, "CodexPluginInstaller", lambda _config: installer)
    monkeypatch.setattr(launch, "CodexTranscripts", lambda _home: Mock())
    monkeypatch.setattr(
        launch,
        "start_harness_transcript",
        lambda *args, **kwargs: Transcript(events),
    )
    monkeypatch.setattr(
        sh,
        "Command",
        lambda _name: lambda *args, **kwargs: events.append("cli"),
    )

    launch.launch_codex(
        composition(),
        [],
        None,
        None,
        None,
        False,
        False,
        checkpoint=checkpoint(events),
    )

    assert events == [
        "checkpoint:codex",
        "ready",
        "cli",
        "close:True",
        "checkpoint:codex",
    ]


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_generate_only_never_checkpoints(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    monkeypatch.setattr(launch, "ready_to_open", lambda *args: None)
    if provider == "claude":
        launch.launch_claude(
            composition(),
            [],
            Mock(),
            None,
            None,
            True,
            checkpoint=checkpoint(events),
        )
    else:
        launch.launch_codex(
            composition(),
            [],
            None,
            None,
            None,
            True,
            False,
            checkpoint=checkpoint(events),
        )

    assert events == []
