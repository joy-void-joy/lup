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
from lup.resolver.models import FROZEN, ConcernStatus, ResolvePhase
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
