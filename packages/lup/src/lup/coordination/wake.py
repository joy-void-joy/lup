"""Making a peer look, when leaving mail for it is not enough.

Mail is the durable record and it is always written; a wake sits on top of it,
never instead of it. That ordering is the whole safety property here — a wake
that fails costs a peer some latency, and never a message.

**The runtimes differ, and the difference is not ours to paper over.** Codex
serves `codex queue`, which reaches a session from any process on the machine.
Claude serves no such command: its only path to a running session is a tool
inside another session, so nothing this library runs can take it. Measured
against Claude Code's own `--help`, which lists `agents`, `attach`, `logs`,
`respawn`, `rm` and `stop` and no verb that speaks to a live session, and
against the environment a session holds — the handle its peers address it by
appears in none of the variables it is given.

So this reports what would wake a member rather than always doing it. Where
lup can act it acts; where only the caller can, it says so in the words the
caller needs, and the caller is a skill running inside a session that has the
tool. A member nothing can wake is an honest third answer, not a failure.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from lup.execution.shell import LazyCommand

# lup: ignore[constant-declaration] — the provider's own executable name,
# which is what `codex queue` is spelled as and not a choice a caller makes
CODEX_COMMAND = LazyCommand("codex")


class WakePath(BaseModel, frozen=True):
    """How one member can be made to look, and by whom.

    A runtime and a handle rather than a command line, because who can run the
    command differs by runtime: one is a process anybody may start and the
    other is a tool only a session holds. A caller that was handed a command
    would have no way to tell those apart.
    """

    runtime: Literal["", "claude", "codex"] = ""
    """Which runtime's path this is, empty where the member declared none.

    Empty is the honest default. A session that never said how to reach it
    still has a durable inbox, and a sender is told that nothing will wake it
    rather than being told a wake was attempted.
    """

    handle: str = ""
    """What that runtime addresses this member by, in its own spelling.

    A thread id or session name for Codex, which `codex queue --thread` takes
    verbatim. For Claude it is the name its peers address it by, which only
    the session itself can learn — nothing in the environment carries it.
    """


class Woken(BaseModel, frozen=True):
    """What happened when somebody tried to make a member look.

    Three outcomes rather than a boolean, because they need different things
    of the caller: one is done, one is the caller's to finish with a tool this
    library does not have, and one is nothing anybody can do. A boolean would
    collapse the middle into the last and lose a peer that was reachable.
    """

    reached: bool
    """Whether the member has been made to look, by this call."""

    instruction: str = ""
    """What the caller must do to finish it, empty where nothing is left.

    Filled for a runtime whose only path is a tool the caller holds and this
    library does not, which is Claude's whole case: the words name the tool and
    the address, so a skill can act on them without knowing the asymmetry.
    """

    reason: str = ""
    """Why nothing happened, for a member nothing can wake."""


def wake(path: WakePath, message: str, cwd: Path | None = None) -> Woken:
    """Make one member look at what is waiting, as far as this process can.

    Never raises on a failed wake. The mail is already written by the time
    anything calls this, so a runtime that is missing, a session that has since
    exited, or a handle that no longer resolves all leave the record intact and
    the peer merely un-nudged — which is the state a member with no wake path
    is in permanently and which the system is built to tolerate.
    """
    match path.runtime:
        case "codex" if path.handle:
            return queued(path.handle, message, cwd)
        case "claude" if path.handle:
            return Woken(
                reached=False,
                instruction=(
                    f"send this to {path.handle!r} with your SendMessage tool —"
                    " Claude serves no command that speaks to a running session,"
                    " so only a session holding the tool can carry it"
                ),
            )
        case _:
            return Woken(
                reached=False,
                reason=(
                    "this member declared no wake path, so the mail waits until"
                    " it next looks"
                ),
            )


def queued(thread: str, message: str, cwd: Path | None = None) -> Woken:
    """Hand one message to a Codex session through its own queue.

    The one runtime where this library can finish the job, so it does.
    """
    try:
        CODEX_COMMAND(
            "queue",
            "--thread",
            thread,
            "--message",
            message,
            _cwd=str(cwd) if cwd else None,
        )
    except Exception as failure:
        return Woken(
            reached=False,
            reason=f"codex queue did not reach {thread!r}: {failure}",
        )
    return Woken(reached=True)
