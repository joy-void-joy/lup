"""What a runtime gives a session to be known by, asked of the adapter that knows.

A tool server started by a native runtime is the first process of its session
to run, and it is handed nothing about the session but the runtime's name.
The identity a session joins the roster under is the launcher's where one
minted it, and otherwise whatever the runtime itself gave the process — a
fact spelled differently by each runtime, or not at all, so each adapter
answers for its own and this asks the right one.

Blank is an answer. A runtime that hands its servers no session id leaves an
unlaunched session with nothing to join under, and the tool server serves no
coordination verbs rather than inventing a member on every call or answering
to a name every session in the worktree would share.
"""

from lup.coordination.wake import WakePath
from lup.providers.claude.identity import claude_session_id, claude_wake
from lup.providers.codex.identity import codex_session_id, codex_wake


def native_session_id(runtime: str) -> str:
    """The session id *runtime* set for this process, or blank where it set none."""
    match runtime:
        case "claude":
            return claude_session_id()
        case "codex":
            return codex_session_id()
        case _:
            return ""


def native_wake(runtime: str, cli_name: str) -> WakePath:
    """How *runtime* would have this session made to look, where anything can.

    Asked of the adapter for the same reason the session id is: what wakes a
    session is one runtime's own arrangement -- a name a tool inside another
    session resolves, or a thread a command takes -- and a caller that knew
    one of those spellings would answer wrongly for the other.

    *cli_name* is what the launcher called this session, which one adapter
    hands its runtime and the other has nowhere to put. Passing it to both
    keeps the asking here rather than making this module know which of them
    has a use for it.
    """
    match runtime:
        case "claude":
            return claude_wake(cli_name)
        case "codex":
            return codex_wake(cli_name)
        case _:
            return WakePath()
