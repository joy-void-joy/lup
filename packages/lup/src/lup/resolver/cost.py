# lup: ignore[own-model-dispatch]
# Timing is a projection of the journal vocabulary; session and run events
# do not depend on this reporting layer or carry its aggregation policy.
"""Read-only timing evidence derived from a resolver's ordered journal."""

from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field, computed_field

from lup.channels.stream import Stream
from lup.coordination.refs import ActorRef
from lup.resolver.journal import (
    ENTRY_ADAPTER,
    JOURNAL_FILE,
    JournalEntry,
    RunFailedEvent,
)
from lup.sessions.events import TurnCompletedEvent, TurnIdentifiers, TurnStartedEvent


class TurnKey(BaseModel, frozen=True):
    """Native turn identity qualified by the actor whose stream recorded it."""

    actor: ActorRef
    identifiers: TurnIdentifiers


class ActorCost(BaseModel):
    """Completed turn durations and incomplete evidence for one actor kind."""

    kind: str
    completed: int = 0
    unfinished: int = 0
    interrupted: int = 0
    total_seconds: float = 0
    maximum_seconds: float = 0
    peak_concurrency: int = 0

    @computed_field
    @property
    def mean_seconds(self) -> float | None:
        return self.total_seconds / self.completed if self.completed else None


class IdleGap(BaseModel, frozen=True):
    """An interval with no recorded turn in flight, and its preceding event."""

    started_at: datetime
    ended_at: datetime
    preceding: JournalEntry

    @computed_field
    @property
    def seconds(self) -> float:
        return (self.ended_at - self.started_at).total_seconds()


class FailureCount(BaseModel, frozen=True):
    """One exact recorded failure reason, with no heuristic classification."""

    reason: str
    count: int


class CostReport(BaseModel, frozen=True):
    """The observed journal window, distinguishing wall time from actor time."""

    started_at: datetime | None = None
    ended_at: datetime | None = None
    wall_seconds: float = 0
    active_seconds: float = 0
    idle_seconds: float = 0
    peak_concurrency: int = 0
    actors: list[ActorCost] = []
    failures: list[FailureCount] = []
    idle_gaps: list[IdleGap] = []
    gap_threshold_seconds: float = Field(default=600, ge=0)
    anomalies: list[str] = []


def cost_report(
    entries: Iterable[JournalEntry], gap: timedelta = timedelta(minutes=10)
) -> CostReport:
    """Fold the journal once, counting overlapping turns once as active time.

    The window ends at the last recorded timestamp, never at the reader's
    clock. An unfinished turn contributes observed activity but no completed
    duration; a run failure ends all in-flight intervals as interrupted.
    """
    if gap < timedelta():
        raise ValueError("the idle-gap threshold must be nonnegative")
    active: dict[TurnKey, datetime] = {}  # lup: ignore[empty-collection] — event fold
    actors: dict[str, ActorCost] = {}  # lup: ignore[empty-collection] — event fold
    failures: Counter[str] = Counter()
    gaps: list[IdleGap] = []  # lup: ignore[empty-collection] — event fold
    anomalies: list[str] = []  # lup: ignore[empty-collection] — event fold
    first: JournalEntry | None = None
    previous: JournalEntry | None = None
    idle_start: JournalEntry | None = None
    active_seconds = 0.0
    peak = 0
    for entry in entries:
        if previous is not None:
            if entry.at < previous.at:
                raise ValueError(
                    f"journal timestamp moved backward at sequence {entry.seq}"
                )
            if active:
                active_seconds += (entry.at - previous.at).total_seconds()
        else:
            first = entry
            idle_start = entry
        match entry.event:
            case TurnStartedEvent(identifiers=identifiers):
                key = TurnKey(actor=entry.actor, identifiers=identifiers)
                actor = actors.setdefault(
                    entry.actor.kind, ActorCost(kind=entry.actor.kind)
                )
                if key in active:
                    anomalies.append(f"duplicate turn start at sequence {entry.seq}")
                else:
                    if not active and idle_start is not None:
                        if entry.at - idle_start.at > gap:
                            gaps.append(
                                IdleGap(
                                    started_at=idle_start.at,
                                    ended_at=entry.at,
                                    preceding=idle_start,
                                )
                            )
                        idle_start = None
                    active[key] = entry.at
                    peak = max(peak, len(active))
                    actor.peak_concurrency = max(
                        actor.peak_concurrency,
                        sum(key.actor.kind == actor.kind for key in active),
                    )
            case TurnCompletedEvent(identifiers=identifiers):
                key = TurnKey(actor=entry.actor, identifiers=identifiers)
                started = active.pop(key, None)
                if started is None:
                    anomalies.append(
                        f"turn completion without a start at sequence {entry.seq}"
                    )
                else:
                    actor = actors[entry.actor.kind]
                    seconds = (entry.at - started).total_seconds()
                    actor.completed += 1
                    actor.total_seconds += seconds
                    actor.maximum_seconds = max(actor.maximum_seconds, seconds)
                    if not active:
                        idle_start = entry
            case RunFailedEvent(reason=reason):
                failures[reason] += 1
                if active:
                    idle_start = entry
                for key in active:
                    actors[key.actor.kind].interrupted += 1
                active.clear()
        previous = entry
    for key in active:
        actors[key.actor.kind].unfinished += 1
    if first is None or previous is None:
        return CostReport(gap_threshold_seconds=gap.total_seconds())
    if idle_start is not None and previous.at - idle_start.at > gap:
        gaps.append(
            IdleGap(
                started_at=idle_start.at, ended_at=previous.at, preceding=idle_start
            )
        )
    wall = (previous.at - first.at).total_seconds()
    return CostReport(
        started_at=first.at,
        ended_at=previous.at,
        wall_seconds=wall,
        active_seconds=active_seconds,
        idle_seconds=wall - active_seconds,
        peak_concurrency=peak,
        actors=[actors[kind] for kind in sorted(actors)],
        failures=[
            FailureCount(reason=reason, count=count)
            for reason, count in sorted(failures.items())
        ],
        idle_gaps=gaps,
        gap_threshold_seconds=gap.total_seconds(),
        anomalies=anomalies,
    )


def read_cost(root: Path, gap: timedelta = timedelta(minutes=10)) -> CostReport:
    """Read the existing journal without opening a writer or taking the run lock."""
    path = root / JOURNAL_FILE
    if not path.is_file():
        raise FileNotFoundError(f"no resolver journal at {path}")
    return cost_report(Stream(path, ENTRY_ADAPTER).read_all(), gap)
