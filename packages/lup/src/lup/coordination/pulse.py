# lup: ignore[constant-declaration]
# The directory name is where a session's pulse is found by every other
# process of its repository — a hook, a tool server, a console — and two that
# spelled it differently would each read the other as silent, so it is an
# identity of the store's layout rather than a choice a caller can make.
"""A session's pulse: proof it is still there, written by nobody but itself.

The roster records arrivals and departures, and a departure is a record a
session writes on its way out. A session that is killed, or whose container
stops, writes nothing, and its row reads as present until somebody notices —
which nobody does, because the row is what they would notice it by. So
presence is not left to the record alone: a session beats while it lives, and
a row whose last beat is older than the window reads as gone whatever its
records say. Beating again is enough to read as back, and the session's next
join makes that durable.

One file per member, its modification time the beat: nothing to fold, nothing
that grows, and a reader that cannot import lup — the prompt-time hook — reads
it with a stat. The coordination tool server beats on a timer for as long as it
runs, and the prompt hook beats at each prompt, so a session without the
server still pulses at the pace it is used.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

HEARTBEATS_DIR = "heartbeats"


class Pulse(BaseModel, frozen=True):
    """How often a live session beats, and how long a silence reads as absence.

    The window is a few beats wide rather than one, so a stalled scheduler or
    a slow disk does not read as a departure; it is short because the roster
    is read to decide whether a path is safe to write, and a dead session
    holding that decision open for an hour is the failure this closes.
    """

    interval_seconds: float = 30.0
    stale_after_seconds: float = 120.0

    def stale(self, heard: datetime, now: datetime) -> bool:
        """Whether a member last heard at *heard* reads as gone at *now*."""
        return now - heard > timedelta(seconds=self.stale_after_seconds)


def beat_path(root: Path, member_id: str) -> Path:
    """Where one member's pulse is kept, under the coordination store."""
    return root / HEARTBEATS_DIR / member_id


def beat(root: Path, member_id: str) -> None:
    """Record that this member is here now."""
    path = beat_path(root, member_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def heard_at(root: Path, member_id: str) -> datetime | None:
    """When this member last beat, or nothing where it never has."""
    try:
        stamp = beat_path(root, member_id).stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(stamp, UTC)
