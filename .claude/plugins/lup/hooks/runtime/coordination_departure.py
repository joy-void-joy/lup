# lup: ignore[constant-declaration]
# The store's file name and the member's kind are restated because a verbatim
# copy cannot import them, and pinned back to the typed writers by a test.
"""A session leaving, recorded by the hook its runtime fires as it ends.

The roster's row for a session ends with the record that session writes on
its way out, and nothing wrote it: a session that exited cleanly read as
running forever, the same as one that was killed. Both runtimes fire an event
when a session ends — a clean exit, a cleared conversation, a terminal closed,
a termination signal — and this is what runs under it: the one line that says
the member is finished, appended to the roster the typed writers keep.

Shipped verbatim into each plugin's ``hooks/runtime/``, so everything here
resolves on a bare interpreter: standard library only, no ``lup`` import.
A departure that cannot be written is not worth stopping an exit for, so every
failure is silence — the pulse retires the row within its window either way,
and this only makes the ending exact.

**A writer of one record and a reader of none.** The record's shape is the
typed roster's ``ActorFinished`` as pydantic serializes it, and a test folds
what this wrote with the typed reader so the two cannot part. A session that
never joined leaves nothing: the roster is read once to see whether this
member is standing, because a finish for nobody is a line every fold ignores
and a store should not carry.

The member is the launcher-proven id where one was minted, and otherwise the
id the runtime hands the hook — the same fallback the prompt-time fold takes,
so the row that arrives and the row that leaves are one row.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

ROSTER_FILE = "roster.jsonl"
MEMBER_KIND = "session"


class Actor(TypedDict, total=False):
    """Whom a record attributes itself to, as the roster spells it."""

    kind: str
    id: str


class RosterRecord(TypedDict, total=False):
    """One record on the roster stream, as far as ending a row needs to know."""

    type: str
    actor: Actor


class Finished(TypedDict):
    """The record that ends a row, as the typed roster serializes its own."""

    type: str
    actor: Actor
    at: str
    summary: str
    error: str


class Ending(TypedDict, total=False):
    """What the runtime hands the hook on stdin, as far as this reads it."""

    session_id: str


def member_of(record: RosterRecord) -> str:
    """The session id a record is about, blank where it is about no session."""
    actor = record.get("actor")
    if not isinstance(actor, dict) or actor.get("kind") != MEMBER_KIND:
        return ""
    held = actor.get("id")
    return held if isinstance(held, str) else ""


def standing(roster: Path, member_id: str) -> bool:
    """Whether this member's newest arrival has no finish after it."""
    try:
        lines = roster.read_text("utf-8").splitlines()
    except OSError:
        return False

    def parsed(line: str) -> RosterRecord | None:
        try:
            record: RosterRecord = json.loads(line)
        except ValueError:
            return None
        return record if isinstance(record, dict) else None

    running = False
    for record in map(parsed, lines):
        if record is None or member_of(record) != member_id:
            continue
        match record.get("type", ""):
            case "spawned" | "joined":
                running = True
            case "finished":
                running = False
            case _:
                continue
    return running


def depart(root: Path, member_id: str) -> bool:
    """Append this member's finish where it is standing; say whether one was written."""
    roster = root / ROSTER_FILE
    if not member_id or not standing(roster, member_id):
        return False
    record = Finished(
        type="finished",
        actor=Actor(kind=MEMBER_KIND, id=member_id),
        at=datetime.now(UTC).isoformat(),
        summary="",
        error="",
    )
    with roster.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record) + "\n")
    return True


def main() -> None:
    """Write the departure, or say nothing and let the session end.

    The store root and this member's launcher-proven id (blank where nothing
    launched it) arrive as arguments; the ending payload on stdin supplies
    the session's own id as the fallback. Every failure is silence, because
    an exit is not something a broken roster may hold up.
    """
    try:
        root, member = Path(sys.argv[1]), sys.argv[2]
        ending: Ending = json.load(sys.stdin)
        depart(root, member or ending.get("session_id", ""))
    except Exception:
        return


if __name__ == "__main__":
    main()
