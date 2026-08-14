"""Answering whether a run is alive, and what it last did.

"Is it still running, or did it stop?" is the most common question about a
resolver run, because the resolver is built to be left alone: it parks,
persists, and is resumed later. The answer used to come from reading a
journal's mtime and hand-parsing its last event — a technique reinvented
each session and easy to get wrong in both directions, since a run can
legitimately print nothing for tens of minutes while a planner works.

Everything here is derived from the run directory alone. Under a sandbox
`/proc` is PID-isolated, so `ps` and `pgrep` list nothing outside the
current shell and a healthy run is indistinguishable from a dead one; a
liveness answer that consults the process table is therefore no answer at
all on the host the resolver most often runs on.
"""

from collections import Counter
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from lup.channels.models import utc_now
from lup.resolver.journal import journal_tail
from lup.resolver.models import FROZEN, ConcernStatus, ResolvePhase, ResolveState
from lup.resolver.state import ResolverStateRepository


class StatusCount(BaseModel):
    """How many concerns stand at one status."""

    model_config = FROZEN

    status: ConcernStatus
    concerns: int


class LastRecorded(BaseModel):
    """The run's most recent journal entry, as a reader needs to see it."""

    model_config = FROZEN

    event: str
    actor: str
    at: datetime

    def quiet_for(self, now: datetime | None = None) -> timedelta:
        """How long since the run recorded anything."""
        return (now if now is not None else utc_now()) - self.at


def elapsed_per_item(
    completions: list[datetime], gap: timedelta = timedelta(hours=1)
) -> timedelta | None:
    """The mean time one item took, over the stretches actually worked.

    A run is resumed, so consecutive samples can be separated by however
    long nobody was driving it — this one holds an interval of twenty-eight
    hours between two joins a minute of work apart. Averaged in, a single
    such gap makes every later estimate meaningless, so an interval longer
    than ``gap`` is read as the run having been away rather than as work.

    None until two samples on one stretch exist, because one timestamp is a
    when and not a duration. A bar with no rate yet prints without one.
    """
    intervals = [
        later - earlier
        for earlier, later in zip(completions, completions[1:], strict=False)
        if later - earlier <= gap
    ]
    if not intervals:
        return None
    return sum(intervals, timedelta()) / len(intervals)


class PhaseProgress(BaseModel):
    """One phase's iterator, as far through it as the run has got.

    Per phase rather than one figure for the run, because the phases do not
    share a rate: a join is a merge and a verification, while the re-check
    that follows the last of them is a reviewer turn per concern. One
    estimate spanning both would be wrong for whichever phase it was not
    measured on, and wrong most of the time.
    """

    model_config = FROZEN

    label: str
    done: int
    total: int
    per_item: timedelta | None = None

    def remaining(self) -> timedelta | None:
        """How long the rest of this phase should take at the observed rate."""
        if self.per_item is None or self.done >= self.total:
            return None
        return self.per_item * (self.total - self.done)

    def render(self, width: int = 16) -> str:
        """The bar, its count, and the two figures a reader plans around."""
        filled = round(width * self.done / self.total) if self.total else 0
        eta = self.remaining()
        return " · ".join(
            [
                f"{'█' * filled}{'░' * (width - filled)} {self.done}/{self.total}",
                *(
                    [f"{compact_interval(self.per_item)}/it"]
                    if self.per_item is not None
                    else []
                ),
                *([f"ETA {compact_interval(eta)}"] if eta is not None else []),
            ]
        )


def compact_interval(span: timedelta) -> str:
    """A duration as a reader says it out loud, to two units at most."""
    seconds = int(span.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"


class RunStatus(BaseModel):
    """Where a run stands, and whether anything is driving it."""

    model_config = FROZEN

    run_id: str
    exists: bool
    held: bool
    """Whether a process holds the run lock — the liveness answer."""

    phase: ResolvePhase | None = None
    counts: list[StatusCount] = Field(default_factory=list)
    unanswered: int = 0
    last: LastRecorded | None = None
    progress: PhaseProgress | None = None
    """The current phase's iterator, where the phase has one worth drawing."""

    def verdict(self) -> str:
        """One line a reader can act on without interpreting the rest.

        The held lock is the fact; quiet time is context on top of it, never
        the verdict on its own. Judging by silence produced a confident
        wrong "it crashed" about a run that was mid-turn, because a long
        model turn looks exactly like a stall from outside.
        """
        if not self.exists:
            return "no such run under this project's .lup/resolve"
        if not self.held:
            return f"not running — parked or finished in phase {self.phase}"
        if self.last is None:
            return "running — a process holds the lock, nothing recorded yet"
        return (
            "running — a process holds the lock, last recorded "
            f"{int(self.last.quiet_for().total_seconds())}s ago"
        )

    def watched(self) -> str:
        """The part of this projection a watch reports a change in.

        Deliberately not the last journal entry. A run records tens of
        thousands of events, so watching that field would emit on each one
        and drown the four facts a reader is actually waiting for — the
        phase moving, a concern changing status, a question arriving, and
        the run stopping.
        """
        return "|".join(
            [
                str(self.held),
                str(self.phase),
                str(self.unanswered),
                # A join is one of the four facts a reader waits on, and the
                # statuses above do not move for it: every concern is already
                # `integrating` and stays there until the last one lands.
                str(self.progress.done if self.progress else 0),
                *(f"{count.status}={count.concerns}" for count in self.counts),
            ]
        )

    def settled(self, running_yet: bool) -> bool:
        """Whether nothing more will happen until somebody acts.

        A watch that outlives what it watches is the loop this replaces, so
        it ends where a reader has to do something: a terminal phase, or a
        run whose lock nobody holds — a park, which is waiting on an answer.

        ``running_yet`` is what keeps a watch from ending on the run it was
        started for. A detached run is spawned and returns immediately, so
        for the seconds its interpreter takes to start there is no lock to
        hold and an unheld run is indistinguishable from a parked one. The
        caller answers whether that window has closed — by seeing the lock
        held, or by waiting long enough that an unheld run is not one that
        is still starting. Both, because either alone is wrong in one
        direction: a flag alone spins forever on a run parked before the
        watch began, and a timer alone ends a slow start.

        It gates the phase for the same reason it gates the lock. Until the
        resuming process persists one, the phase on disk is whatever the
        last one left — and what a resume is most often started from is a
        terminal phase, because failing is what stopped the run. Read inside
        the startup window that reads as finished, so a watch armed on a
        just-relaunched run announced the failure it was resuming from and
        ended, having never polled once.
        """
        if not self.exists:
            return True
        if not running_yet:
            return False
        if self.phase is not None and self.phase.terminal():
            return True
        return not self.held


def phase_progress(state: ResolveState) -> PhaseProgress | None:
    """The iterator the current phase is working through, where it has one.

    Only the join sequence so far. A phase earns a bar by knowing both how
    many items it faces and when each one landed; the worker phase knows the
    first and not the second, and drawing a bar that cannot say a rate would
    promise an estimate the run has no way to make.
    """
    progress = state.join_progress
    if progress is None or not progress.planned:
        return None
    return PhaseProgress(
        label="joins",
        done=len(progress.joined),
        total=progress.planned,
        per_item=elapsed_per_item(progress.completions),
    )


def run_status(repository: ResolverStateRepository, run_id: str) -> RunStatus:
    """Everything the run directory can say about where this run stands."""
    held = repository.held()
    if not repository.exists():
        return RunStatus(run_id=run_id, exists=False, held=held)
    state = repository.load()
    tally = Counter(item.status for item in state.progress)
    entry = journal_tail(repository.root)
    answered = {
        answer.question_id
        for answer in (state.answers.answers if state.answers else [])
    }
    return RunStatus(
        run_id=run_id,
        exists=True,
        held=held,
        phase=state.phase,
        counts=[
            StatusCount(status=status, concerns=count)
            for status, count in sorted(
                tally.items(), key=lambda pair: (-pair[1], pair[0])
            )
        ],
        unanswered=sum(
            1
            for question in (state.questions.questions if state.questions else [])
            if question.id not in answered
        ),
        progress=phase_progress(state),
        last=None
        if entry is None
        else LastRecorded(
            event=entry.event.type,
            actor=f"{entry.actor.kind}:{entry.actor.id}",
            at=entry.at,
        ),
    )
