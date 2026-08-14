"""Answering a run's liveness from its directory, where /proc cannot be read."""

from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter

from lup.channels.models import LOCAL_STAMP_FORMAT, local_stamp, utc_now
from lup.channels.stream import Stream
from lup.resolver.models import ConcernStatus, ResolvePhase
from lup.resolver.state import ResolverStateRepository
from lup.resolver.status import LastRecorded, RunStatus, StatusCount, run_status
from lup.devtools.supervisor.doors import attention_line


def test_an_unheld_run_reads_as_not_running(tmp_path: Path) -> None:
    repository = ResolverStateRepository(tmp_path, "quiet")
    repository.root.mkdir(parents=True)
    (repository.root / ".run.lock").write_text("", encoding="utf-8")

    assert not repository.held()


def test_a_held_run_reads_as_running(tmp_path: Path) -> None:
    """The lock is the liveness answer, and it answers across processes.

    `ps` and `pgrep` cannot: under a sandbox `/proc` is PID-isolated, so
    they list nothing outside the current shell and a healthy long-running
    run is indistinguishable from one that died.
    """
    repository = ResolverStateRepository(tmp_path, "busy")

    with repository.exclusive():
        # A second reader of the same run directory, which is what a status
        # command is. Same process here; the flock is what a separate one
        # would meet too.
        assert ResolverStateRepository(tmp_path, "busy").held()

    assert not ResolverStateRepository(tmp_path, "busy").held()


def test_a_run_that_does_not_exist_says_so_rather_than_answering(
    tmp_path: Path,
) -> None:
    """Silence and "no such run" were indistinguishable, and one is wrong.

    A session in a worktree with no `.lup` read an empty listing as "zero
    pending, so my answer promoted", and reported that. It happened to be
    true; nothing in the output supported it.
    """
    status = run_status(ResolverStateRepository(tmp_path, "absent"), "absent")

    assert not status.exists
    assert "no such run" in status.verdict()


def test_a_log_s_last_record_is_read_without_its_whole_length(tmp_path: Path) -> None:
    """A resolver journal reaches tens of megabytes inside a single run."""
    adapter: TypeAdapter[dict[str, int]] = TypeAdapter(dict[str, int])
    stream = Stream(tmp_path / "log.jsonl", adapter)
    for index in range(500):
        stream.append({"seq": index})

    assert stream.last() == {"seq": 499}
    assert stream.last(window=64) == {"seq": 499}


def test_an_empty_log_has_no_last_record(tmp_path: Path) -> None:
    adapter: TypeAdapter[dict[str, int]] = TypeAdapter(dict[str, int])

    assert Stream(tmp_path / "missing.jsonl", adapter).last() is None


def status_at(
    phase: ResolvePhase, held: bool, unanswered: int = 0, verified: int = 0
) -> RunStatus:
    """One projection, built directly rather than through a run on disk."""
    return RunStatus(
        run_id="watched",
        exists=True,
        held=held,
        phase=phase,
        counts=[StatusCount(status=ConcernStatus.VERIFIED, concerns=verified)],
        unanswered=unanswered,
    )


def test_a_watch_reports_a_change_in_any_of_the_four_facts() -> None:
    """Phase, per-status counts, questions waiting, and the run stopping."""
    running = status_at(ResolvePhase.WORKERS, held=True, verified=3)

    assert (
        running.watched()
        != status_at(ResolvePhase.REVIEW, held=True, verified=3).watched()
    )
    assert (
        running.watched()
        != status_at(ResolvePhase.WORKERS, held=True, verified=4).watched()
    )
    assert (
        running.watched()
        != status_at(
            ResolvePhase.WORKERS, held=True, verified=3, unanswered=1
        ).watched()
    )
    assert (
        running.watched()
        != status_at(ResolvePhase.WORKERS, held=False, verified=3).watched()
    )


def test_a_watch_does_not_report_the_journal_advancing() -> None:
    """A run records tens of thousands of events; each is not a change."""
    quiet = status_at(ResolvePhase.WORKERS, held=True, verified=3)
    noisy = quiet.model_copy(
        update={
            "last": LastRecorded(
                event="message_posted", actor="worker:alpha", at=utc_now()
            )
        }
    )

    assert quiet.watched() == noisy.watched()


def test_a_watch_ends_when_the_run_parks() -> None:
    """A park is waiting on an answer, which is the reader's turn."""
    assert status_at(ResolvePhase.WORKERS, held=False).settled(running_yet=True)


def test_a_watch_ends_when_the_run_finishes() -> None:
    assert status_at(ResolvePhase.COMPLETE, held=True).settled(running_yet=True)


def test_a_watch_survives_the_seconds_before_a_detached_run_takes_its_lock() -> None:
    """Spawning returns immediately; the interpreter takes seconds to start."""
    assert not status_at(ResolvePhase.WORKERS, held=False).settled(running_yet=False)


def test_a_watch_on_a_run_parked_before_it_started_still_ends() -> None:
    """The other direction of the same window, and the one that hung.

    Waiting only for a lock that has been seen means a watch attached to an
    already-parked run never ends: it is unheld, its phase is not terminal,
    and no reading will change either. The caller closes the window on
    elapsed time as well, which is what this asks for.
    """
    parked = status_at(ResolvePhase.WORKERS, held=False)

    assert not parked.settled(running_yet=False)
    assert parked.settled(running_yet=True)


def test_a_watch_on_a_run_that_does_not_exist_ends_at_once() -> None:
    absent = RunStatus(run_id="absent", exists=False, held=False)

    assert absent.settled(running_yet=False)


def test_a_reading_is_dated_in_the_reader_s_own_zone() -> None:
    """A run outlasts the attention of whoever started it.

    The run's own ages say how long a worker has been quiet, which is a
    different question from how long ago the reader was last told anything —
    and a terminal shows how long a turn took, never when it ended.
    """
    stamp = local_stamp()

    assert stamp == datetime.now().astimezone().strftime(LOCAL_STAMP_FORMAT)


def test_the_attention_line_carries_only_what_a_reader_acts_on() -> None:
    """A standing failure is not something to attend to, and displaced one.

    Carrying it put "1 failed" where the changing field goes, so a run
    working quietly through a days-old failure read as though one were
    happening. What is left is whether anybody is held up, and whether
    anything is driving it.
    """
    counts = [
        StatusCount(status=ConcernStatus.VERIFIED, concerns=21),
        StatusCount(status=ConcernStatus.FAILED, concerns=1),
    ]
    working = RunStatus(
        run_id="r", exists=True, held=True, phase=ResolvePhase.WORKERS, counts=counts
    )
    parked = working.model_copy(update={"held": False, "unanswered": 2})
    dead = working.model_copy(update={"held": False})

    assert attention_line(working).endswith("workers · running")
    assert attention_line(parked).endswith("workers · 2 questions waiting")
    assert attention_line(dead).endswith("workers · stopped")
    assert "failed" not in attention_line(working)
    assert "21" not in attention_line(working)


def test_a_caller_wanting_another_shape_passes_one() -> None:
    """The format is this project's judgement, so a default and not a law."""
    assert local_stamp("%Y") == str(datetime.now().astimezone().year)
