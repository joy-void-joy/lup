"""Answering a run's liveness from its directory, where /proc cannot be read."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from lup.channels.models import local_stamp, utc_now
from lup.channels.stream import Stream
from lup.resolver.models import ConcernStatus, ResolvePhase
from lup.resolver.state import ResolverStateRepository
from lup.resolver.status import (
    LastRecorded,
    PhaseProgress,
    RunStatus,
    StatusCount,
    elapsed_per_item,
    run_status,
)
from lup.devtools.supervisor.doors import report_status, status_header


def test_a_bar_reports_the_rate_of_the_stretches_actually_worked() -> None:
    """A resume separates two samples by however long nobody was driving it.

    This run holds an interval of twenty-eight hours between two joins a
    minute of work apart. Averaged in, one such gap makes every later
    estimate meaningless — an ETA of days for eight joins of about a minute.
    """
    start = utc_now()
    worked = timedelta(minutes=1)
    away = timedelta(hours=28)
    samples = [
        start,
        start + worked,
        start + worked + away,
        start + worked + away + worked,
    ]

    assert elapsed_per_item(samples) == worked


def test_a_bar_has_no_rate_until_two_samples_share_a_stretch() -> None:
    """One timestamp is a when, not a duration, and neither is a lone gap."""
    start = utc_now()

    assert elapsed_per_item([]) is None
    assert elapsed_per_item([start]) is None
    assert elapsed_per_item([start, start + timedelta(hours=28)]) is None


def test_a_bar_without_a_rate_still_draws_its_count() -> None:
    """The first item of a phase has nothing to estimate from, and says so."""
    rendered = PhaseProgress(label="joins", done=0, total=13).render(width=4)

    assert rendered == "░░░░ 0/13"


def test_a_bar_carries_the_two_figures_a_reader_plans_around() -> None:
    fifth = PhaseProgress(
        label="joins", done=5, total=13, per_item=timedelta(minutes=2, seconds=11)
    )

    assert fifth.render(width=4) == "██░░ 5/13 · 2m11s/it · ETA 17m28s"


def test_a_finished_bar_estimates_nothing_further() -> None:
    """Nothing remains, so an ETA would be a number about no work."""
    done = PhaseProgress(
        label="joins", done=13, total=13, per_item=timedelta(minutes=2)
    )

    assert done.remaining() is None
    assert "ETA" not in done.render()


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


def test_a_watch_survives_the_terminal_phase_a_resume_was_started_from() -> None:
    """The phase on disk is the last process's until this one persists its own.

    A resume is most often started from a terminal phase, because failing is
    what stopped the run. Read inside the startup window that says finished,
    so a watch armed on a just-relaunched run announced the failure it was
    resuming from and ended without polling once — observed against a run
    that was already integrating by the time it printed.
    """
    failed = status_at(ResolvePhase.FAILED, held=False)

    assert not failed.settled(running_yet=False)
    assert failed.settled(running_yet=True)


def test_a_watch_on_a_run_that_does_not_exist_ends_at_once() -> None:
    absent = RunStatus(run_id="absent", exists=False, held=False)

    assert absent.settled(running_yet=False)


def test_a_reading_is_dated_in_the_reader_s_own_zone() -> None:
    """A run outlasts the attention of whoever started it.

    The run's own ages say how long a worker has been quiet, which is a
    different question from how long ago the reader was last told anything —
    and a terminal shows how long a turn took, never when it ended.
    """
    now = datetime.now().astimezone()
    stamp = local_stamp()

    # Against the clock rather than against LOCAL_STAMP_FORMAT: comparing the
    # function to its own constant passes for every format string, including
    # the bare `%H:%M` that reads as today and names no zone.
    assert stamp.startswith(now.strftime("%a"))
    assert now.strftime("%H:%M") in stamp
    assert stamp.endswith(now.strftime("%Z"))


def test_the_header_carries_progress_losses_and_who_is_held_up() -> None:
    """Three facts and no fourth: how far, what was lost, who is waiting.

    A per-status breakdown is progress rather than attention — nobody acts
    on "9 retired" — and finding what needs you among nine figures that do
    not is the reading this replaces.
    """
    counts = [
        StatusCount(status=ConcernStatus.VERIFIED, concerns=21),
        StatusCount(status=ConcernStatus.RETIRED, concerns=9),
        StatusCount(status=ConcernStatus.INELIGIBLE, concerns=7),
        StatusCount(status=ConcernStatus.FAILED, concerns=1),
        StatusCount(status=ConcernStatus.REVISING, concerns=1),
    ]
    working = RunStatus(
        run_id="r", exists=True, held=True, phase=ResolvePhase.WORKERS, counts=counts
    )

    assert status_header(working).endswith(
        "workers · 38/39 settled · 1 failed · running"
    )
    assert status_header(working.model_copy(update={"unanswered": 2})).endswith(
        "38/39 settled · 1 failed · 2 questions waiting · running"
    )
    assert status_header(working.model_copy(update={"held": False})).endswith("stopped")
    assert "retired" not in status_header(working)


def test_the_header_is_the_report_it_heads(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One composition, so the compact form cannot drift from the full one.

    Two renderers over the same projection is what let a flag go on saying
    what it carried after the line it described had moved on.
    """
    working = RunStatus(
        run_id="r",
        exists=True,
        held=True,
        phase=ResolvePhase.INTEGRATION,
        counts=[StatusCount(status=ConcernStatus.VERIFIED, concerns=4)],
        progress=PhaseProgress(label="joins", done=5, total=13),
    )

    report_status(working)

    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == status_header(working)
    assert not any(line.startswith(status_header(working)) for line in printed[1:])


def test_the_header_says_how_much_longer_the_phase_it_is_in_should_take() -> None:
    """The figure a reader plans around, on the line they are handed."""
    joining = RunStatus(
        run_id="r",
        exists=True,
        held=True,
        phase=ResolvePhase.INTEGRATION,
        counts=[StatusCount(status=ConcernStatus.INTEGRATING, concerns=13)],
        progress=PhaseProgress(
            label="joins", done=5, total=13, per_item=timedelta(minutes=2)
        ),
    )

    assert "joins " in status_header(joining)
    assert "5/13" in status_header(joining)
    assert "ETA 16m00s" in status_header(joining)


def test_a_run_that_lost_nothing_says_nothing_about_losses() -> None:
    """The failure field is absent rather than zero, so its presence means it."""
    clean = RunStatus(
        run_id="r",
        exists=True,
        held=True,
        phase=ResolvePhase.WORKERS,
        counts=[StatusCount(status=ConcernStatus.VERIFIED, concerns=4)],
    )

    assert status_header(clean).endswith("workers · 4/4 settled · running")


def test_the_fraction_can_reach_its_own_total() -> None:
    """Counting only what produced work leaves a bar that never completes.

    Measured against the plan it stops short by every concern retired or
    found ineligible, and a progress figure that cannot finish teaches a
    reader to stop believing it.
    """
    ended = RunStatus(
        run_id="r",
        exists=True,
        held=False,
        phase=ResolvePhase.COMPLETE,
        counts=[
            StatusCount(status=ConcernStatus.VERIFIED, concerns=2),
            StatusCount(status=ConcernStatus.RETIRED, concerns=1),
            StatusCount(status=ConcernStatus.INELIGIBLE, concerns=1),
        ],
    )

    assert "4/4 settled" in status_header(ended)


def test_a_caller_wanting_another_shape_passes_one() -> None:
    """The format is this project's judgement, so a default and not a law."""
    assert local_stamp("%Y") == str(datetime.now().astimezone().year)
