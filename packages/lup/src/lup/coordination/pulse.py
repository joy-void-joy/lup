"""How often a live session beats, and how long a silence reads as absence.

The roster records arrivals and departures, and a departure is a record a
session writes on its way out. A session that is killed, or whose container
stops, writes nothing, and its row reads as present until somebody notices —
which nobody does, because the row is what they would notice it by. So
presence is not left to the record alone: a session beats while it lives, and
a row whose last beat is older than the window reads as gone whatever its
records say. Beating again is enough to read as back, and the session's next
join makes that durable.

The stamps themselves, and the window they are read against, belong to
:mod:`lup.coordination.bare.store`: every process reading this store reads
them, and only one of those processes can import anything of lup's. What is
left here is the knob a typed caller turns — how often the tool server ticks,
which nothing outside this library has to know.
"""

from datetime import datetime

from pydantic import BaseModel

from lup.coordination.bare.store import STALE_AFTER_SECONDS, stale


class Pulse(BaseModel, frozen=True):
    """How often a live session beats, and how long a silence reads as absence.

    The window is a few beats wide rather than one, so a stalled scheduler or
    a slow disk does not read as a departure; it is short because the roster
    is read to decide whether a path is safe to write, and a dead session
    holding that decision open for an hour is the failure this closes.

    Both figures are defaults a caller may turn — a test wants a window it can
    cross, and a population beating in-process wants its own tick. The
    window's default is the store's own, because a reader that cannot import
    this model still has to reach the same verdict about the same silence.
    """

    interval_seconds: float = 30.0
    stale_after_seconds: float = STALE_AFTER_SECONDS

    def stale(self, heard: datetime, now: datetime) -> bool:
        """Whether a member last heard at *heard* reads as gone at *now*.

        The store's own test, over this caller's window: a hook and a tool
        server reading one session's silence reach the same verdict, and a
        caller that moved the window changed how long a silence is tolerated
        rather than what tolerating it means.
        """
        return stale(heard, now, self.stale_after_seconds)
