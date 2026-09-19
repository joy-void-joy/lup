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

from lup.providers.claude.identity import claude_session_id
from lup.providers.codex.identity import codex_session_id


def native_session_id(runtime: str) -> str:
    """The session id *runtime* set for this process, or blank where it set none."""
    match runtime:
        case "claude":
            return claude_session_id()
        case "codex":
            return codex_session_id()
        case _:
            return ""
