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

from pydantic import BaseModel

from lup.channels.models import utc_now
from lup.resolver.journal import journal_tail
from lup.resolver.models import ConcernStatus, ResolvePhase
from lup.resolver.state import ResolverStateRepository


class StatusCount(BaseModel, frozen=True):
    """How many concerns stand at one status."""

    status: ConcernStatus
    concerns: int


class LastRecorded(BaseModel, frozen=True):
    """The run's most recent journal entry, as a reader needs to see it."""

    event: str
    actor: str
    at: datetime

    def quiet_for(self, now: datetime | None = None) -> timedelta:
        """How long since the run recorded anything."""
        return (now if now is not None else utc_now()) - self.at


class RunStatus(BaseModel, frozen=True):
    """Where a run stands, and whether anything is driving it."""

    run_id: str
    exists: bool
    held: bool
    """Whether a process holds the run lock — the liveness answer."""

    phase: ResolvePhase | None = None
    counts: list[StatusCount] = []
    unanswered: int = 0
    last: LastRecorded | None = None

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
        """
        if not self.exists:
            return True
        if self.phase is not None and self.phase.terminal():
            return True
        return running_yet and not self.held


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
        last=None
        if entry is None
        else LastRecorded(
            event=entry.event.type,
            actor=f"{entry.actor.kind}:{entry.actor.id}",
            at=entry.at,
        ),
    )
