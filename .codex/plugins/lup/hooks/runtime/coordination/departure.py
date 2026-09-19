"""A session leaving, recorded by the hook its runtime fires as it ends.

The roster's row for a session ends with the record that session writes on
its way out, and nothing wrote it: a session that exited cleanly read as
running forever, the same as one that was killed. Both runtimes fire an event
when a session ends — a clean exit, a cleared conversation, a terminal closed,
a termination signal — and this is what runs under it: the one line that says
the member is finished, appended to the roster every reader folds.

Shipped into each plugin's ``hooks/runtime/coordination/``, so everything
here resolves on a bare interpreter: standard library, and the fold beside it
in the same package. A departure that cannot be written is not worth stopping
an exit for, so every failure is silence — the pulse retires the row within
its window either way, and this only makes the ending exact.

**The record is the fold's.** Both the test — is this member standing? — and
the line appended live in :mod:`.store`, beside every other reader of that
file, so the row that arrives and the row that leaves cannot be written to
two different understandings of the same record. What is here is the hook:
which arguments a runtime hands over, and the rule that nothing it does may
be allowed to fail.

The member is the launcher-proven id where one was minted, and otherwise the
id the runtime hands the hook — the same fallback the prompt-time fold takes,
so the row that arrives and the row that leaves are one row.
"""

import json
import sys
from pathlib import Path
from typing import TypedDict

from .store import depart


class Ending(TypedDict, total=False):
    """What the runtime hands the hook on stdin, as far as this reads it."""

    session_id: str


def main() -> None:
    """Write the departure, or say nothing and let the session end.

    The store root and this member's launcher-proven id (blank where nothing
    launched it) arrive as arguments; the ending payload on stdin supplies
    the session's own id as the fallback. The event name the guard passes
    beside them is not read here — an ending is an ending, and only the
    prompt fold has an envelope to name it in.

    Every failure is silence, because an exit is not something a broken
    roster may hold up.
    """
    try:
        root, member = Path(sys.argv[1]), sys.argv[2]
        ending: Ending = json.load(sys.stdin)
        depart(root, member or ending.get("session_id", ""))
    except Exception:
        return


if __name__ == "__main__":
    main()
