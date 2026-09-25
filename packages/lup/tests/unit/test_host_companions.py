"""A companion runs on the host for exactly as long as the session beside it.

Real processes, because what is pinned is process lifetime: started when the
launch is cleared to open, still running while the session runs, and gone —
with whatever it started — once the session ends. A program this machine
does not have is said and skipped rather than failing the launch.
"""

import time
from pathlib import Path, PurePosixPath
from unittest.mock import Mock

import pytest
import sh

import lup.devtools.harness.launch as launch
from lup.devtools.harness.companions import companions_running
from lup.harness.companions import HostCompanion
from lup.harness.image import Image


def alive(pid: int) -> bool:
    """Whether a process with this id still exists and has not been reaped as a zombie."""
    status = Path(f"/proc/{pid}/stat")
    if not status.exists():
        return False
    return status.read_text(encoding="utf-8").split()[2] != "Z"


def eventually(condition: object, seconds: float = 5.0) -> bool:
    """Whether a condition becomes true within a few seconds, polling briefly."""
    assert callable(condition)
    deadline = time.monotonic() + seconds
    for _ in iter(lambda: time.monotonic() < deadline, False):
        if condition():
            return True
        time.sleep(0.05)
    return bool(condition())


def test_a_companion_runs_while_the_session_does_and_stops_after(
    tmp_path: Path,
) -> None:
    """What it started stops with it: the signal reaches its whole group."""
    pidfile = tmp_path / "child.pid"
    serving = HostCompanion(
        name="preview",
        command=["sh", "-c", f"sleep 60 & echo $! > {pidfile}; wait"],
        url="http://127.0.0.1:8080",
    )

    with companions_running([serving], tmp_path, tmp_path / "logs") as said:
        assert eventually(pidfile.exists)
        child = int(pidfile.read_text(encoding="utf-8"))
        assert alive(child)
        assert said[0].text.startswith(
            "Companion preview: http://127.0.0.1:8080 (log: "
        )

    assert eventually(lambda: not alive(child))


def test_a_companion_runs_where_it_is_declared_and_logs_beside_the_launch(
    tmp_path: Path,
) -> None:
    (tmp_path / "studio").mkdir()
    printing = HostCompanion(
        name="where", command=["pwd"], directory=PurePosixPath("studio")
    )

    with companions_running([printing], tmp_path, tmp_path / "logs"):
        log = tmp_path / "logs" / "where.log"
        assert eventually(
            lambda: log.exists() and log.read_text(encoding="utf-8") != ""
        )

    assert log.read_text(encoding="utf-8").strip() == str(tmp_path / "studio")


def test_a_program_this_machine_lacks_is_said_and_skipped(tmp_path: Path) -> None:
    missing = HostCompanion(name="missing", command=["no-such-program-anywhere"])
    present = HostCompanion(name="present", command=["sleep", "60"])

    with companions_running([missing, present], tmp_path, tmp_path / "logs") as said:
        texts = [notice.text for notice in said]

    assert texts[0] == (
        "Companion missing: no-such-program-anywhere is not installed here, "
        "so it was not started"
    )
    assert texts[1].startswith("Companion present: (log: ")


def test_a_companion_directory_stays_inside_the_checkout() -> None:
    with pytest.raises(ValueError, match="inside the checkout"):
        HostCompanion(name="away", command=["true"], directory=PurePosixPath("../x"))


def test_the_launch_starts_companions_once_cleared_and_stops_them_after_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleared to open, then the companion, then the session, then the stop."""
    events: list[str] = []
    composition = Mock()
    plugin = Mock()
    plugin.name = "lup"
    composition.recipe.source.plugins = [plugin]
    composition.recipe.source.image = Image()
    composition.recipe.source.companions = [
        HostCompanion(name="preview", command=["sleep", "60"])
    ]

    class Recording:
        """Stands in for the runner, recording when it starts and stops."""

        def __init__(self, *args: object) -> None:
            events.append("companions started")

        def __enter__(self) -> list[object]:
            return []

        def __exit__(self, *args: object) -> None:
            events.append("companions stopped")

    def cleared(*args: object, **kwargs: object) -> launch.LaunchOpening:
        events.append("cleared")
        return launch.LaunchOpening()

    monkeypatch.setattr(launch, "ready_to_open", cleared)
    monkeypatch.setattr(launch, "companions_running", Recording)
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)
    monkeypatch.setattr(launch, "ambient_config_home", lambda *a, **k: tmp_path)
    monkeypatch.setattr(launch, "session_argv", lambda name, *a, **k: [name])
    monkeypatch.setattr(launch, "session_defaults", lambda: {})
    monkeypatch.setattr(launch, "accessible_roots", lambda: [])
    monkeypatch.setattr(launch, "apply_sandbox_environment", lambda *a, **k: None)
    monkeypatch.setattr(launch, "start_harness_transcript", lambda *a, **k: Mock())
    monkeypatch.setattr(launch, "ClaudeTranscripts", lambda _home: Mock())
    monkeypatch.setattr(
        sh, "Command", lambda _name: lambda *a, **k: events.append("session")
    )
    profiles = Mock()
    profiles.launch_home.return_value = None

    launch.launch_claude(composition, [], profiles, None, None, False)

    assert events == ["cleared", "companions started", "session", "companions stopped"]


def test_nothing_starts_when_nothing_is_declared(tmp_path: Path) -> None:
    with companions_running([], tmp_path, tmp_path / "logs") as said:
        assert said == []
    assert not (tmp_path / "logs").exists()
