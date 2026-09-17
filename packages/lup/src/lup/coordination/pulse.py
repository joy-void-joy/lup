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
RESETS_DIR = "resets"
"""Where a session's conversation reset is kept, beside its pulse.

A runtime that rewinds or clears a conversation keeps the process, the session
id and the tool server, and signals none of it, so the row would go on
carrying what the discarded conversation said it was doing under a pulse the
same server keeps beating. The prompt-time fold is the one process that sees
the transcript, so it is the one that notices the conversation move and stamps
this file; every reader then treats a description older than the stamp as
unsaid — derived at the read, like absence, so describing again is enough to
read as current.
"""


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
    stamp(beat_path(root, member_id))


def heard_at(root: Path, member_id: str) -> datetime | None:
    """When this member last beat, or nothing where it never has."""
    return stamped_at(beat_path(root, member_id))


def reset_path(root: Path, member_id: str) -> Path:
    """Where one member's conversation reset is kept, under the coordination store."""
    return root / RESETS_DIR / member_id


def reset(root: Path, member_id: str) -> None:
    """Record that the conversation this member's row described is gone."""
    stamp(reset_path(root, member_id))


def reset_at(root: Path, member_id: str) -> datetime | None:
    """When this member's conversation last moved, or nothing where it never has."""
    return stamped_at(reset_path(root, member_id))


def stamp(path: Path) -> None:
    """Mark this moment on one file, creating what is missing on the way."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def stamped_at(path: Path) -> datetime | None:
    """The moment one stamp file was last marked, or nothing where there is none."""
    try:
        marked = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(marked, UTC)
