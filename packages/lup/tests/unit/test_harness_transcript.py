"""A native CLI launch has to leave a transcript behind.

This is the guard whose absence let the feature die quietly. The wiring that
built a journal and started a watcher around an interactive launch was deleted
with the file holding it, and nothing failed: no test asserted that a launch
records anything, so the only signal was a directory that stopped filling up.
A trace nobody wrote reads exactly like a session nobody ran, which is why the
assertion has to be that the transcript exists rather than that it is correct.
"""

import logging
from pathlib import Path

import pytest

from lup.adapters.claude.transcripts import ClaudeTranscripts
from lup.devtools.harness import launch
from lup.observability.audit import read_observable_events


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project root the launcher would write its harness transcript under."""
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)
    monkeypatch.setattr(
        launch, "harness_runs_path", lambda: tmp_path / "notes" / "harness"
    )
    return tmp_path


def started(project: Path) -> launch.HarnessTranscript:
    """One transcript, as a launcher starts it."""
    return launch.start_harness_transcript(
        "claude",
        ClaudeTranscripts(project / "config"),
        model="claude-fable-5",
        profile=None,
        arguments=["--model", "claude-fable-5"],
    )


def test_starting_a_launch_opens_a_transcript(project: Path) -> None:
    transcript = started(project)
    transcript.close(succeeded=True)

    written = list((project / "notes" / "harness" / "claude").rglob("observable.jsonl"))
    assert len(written) == 1


def test_the_transcript_records_the_run_starting_and_ending(project: Path) -> None:
    transcript = started(project)
    transcript.close(succeeded=True)

    journal = next((project / "notes" / "harness").rglob("observable.jsonl"))
    kinds = [event.kind for event in read_observable_events(journal)]
    assert kinds[0] == "run_start"
    assert kinds[-1] == "run_end"


def test_a_failed_launch_is_recorded_as_one(project: Path) -> None:
    transcript = started(project)
    transcript.close(succeeded=False)

    journal = next((project / "notes" / "harness").rglob("observable.jsonl"))
    ending = read_observable_events(journal)[-1]
    assert ending.payload == {"succeeded": False}


def test_the_launch_starts_a_watcher_that_stops_on_close(project: Path) -> None:
    transcript = started(project)
    assert transcript.watcher.thread is not None
    assert transcript.watcher.thread.is_alive()

    transcript.close(succeeded=True)

    assert not transcript.watcher.thread.is_alive()


def test_the_watcher_is_scoped_to_this_project(project: Path) -> None:
    """Unscoped, it would mirror every concurrent project's sessions in here."""
    transcript = started(project)
    transcript.close(succeeded=True)

    assert transcript.watcher.scope == project


def test_a_credential_passed_on_the_command_line_is_not_recorded(
    project: Path,
) -> None:
    transcript = launch.start_harness_transcript(
        "claude",
        ClaudeTranscripts(project / "config"),
        model=None,
        profile=None,
        arguments=["--api-key", "hunter2", "--model=claude-fable-5"],
    )
    transcript.close(succeeded=True)

    journal = next((project / "notes" / "harness").rglob("observable.jsonl"))
    assert "hunter2" not in journal.read_text(encoding="utf-8")


def test_watcher_diagnostics_land_in_a_file_rather_than_the_terminal(
    project: Path,
) -> None:
    """The launcher hands its terminal to a CLI drawing over the whole screen.

    A recovered polling error reaching the last-resort handler prints a
    traceback into that UI and reads as a crash.
    """
    transcript = started(project)
    launch.watcher_logger().error("a recovered polling failure")
    transcript.close(succeeded=True)

    written = next((project / "notes" / "harness").rglob("watcher.log"))
    assert "a recovered polling failure" in written.read_text(encoding="utf-8")


def test_closing_releases_the_diagnostics_handler(project: Path) -> None:
    """Left attached, every launch in one process would stack another handler."""
    transcript = started(project)
    transcript.close(succeeded=True)

    assert transcript.diagnostics not in launch.watcher_logger().handlers


def test_the_diagnostics_logger_does_not_propagate(project: Path) -> None:
    transcript = started(project)
    try:
        assert launch.watcher_logger().propagate is False
    finally:
        transcript.close(succeeded=True)


def test_a_second_launch_reuses_no_stale_handler(project: Path) -> None:
    first = started(project)
    first.close(succeeded=True)
    before = len(launch.watcher_logger().handlers)

    second = started(project)
    second.close(succeeded=True)

    assert len(launch.watcher_logger().handlers) == before


def test_the_watcher_reports_its_failures_on_the_captured_logger() -> None:
    """The handler is attached by module name, so the two must agree."""
    from lup.observability.native import NativeTranscriptWatcher

    assert launch.watcher_logger().name == NativeTranscriptWatcher.__module__
    assert logging.getLogger("lup.observability.native") is launch.watcher_logger()
