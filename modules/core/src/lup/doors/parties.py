"""Who calls a module's method: the parties its `by` is written as.

A party is a class deriving from `Party`, which any module may declare, and a
method's `by` both says who may call it (`by: Agent`, `by: Agent | Operator`)
and hands it the caller (`README.md` here, *Who calls*). The core's parties
carry only what identifies them: what an agent is beyond their ids, their name
and what they hold, is the inbox's.
"""

from typing import Literal

from lup.types import Model


class Party(Model, extra="allow"):
    """Someone a module's method is called by: each a class of its own, which a method's `by` is typed as, and which any module may declare.

    Read back from JSON as a party, where whoever reads it doesn't know the
    class that wrote it (a block's `reaches` crossing from a project's
    container), it keeps every field it came with, so it says whom it is as it
    was written.
    """


class Agent(Party):
    """An agent: a session's own conversation, or one of their subagents', calling one of their tools, or running a command from their room.

    Identified by lup's id for them, which stays put as they're renamed, and by
    the session they're in, which the room they call from vouches for: a room
    is one session's, so a call from it can speak for that session's own
    conversation or one of its subagents, never another session's (`of`).
    """

    party: Literal["agent"] = "agent"
    """Which of the core's parties it is, as a call across containers names it."""
    id: str
    """lup's id for the agent: their session's own, for the session's own
    conversation, or one made from it, for a subagent of it."""
    session: str
    """lup's id for the session they're in."""

    @classmethod
    def of(cls, session: str, conversation: str | None = None) -> Agent:
        """Return the session's own conversation, or the one the runtime calls `conversation` in it, a subagent's: its id made from the session's, so no other session's room can be vouched as it.

        >>> Agent.of("s1") == Agent(id="s1", session="s1")
        True
        >>> Agent.of("s1", "a7").id
        's1/a7'
        """
        if conversation is None:
            return cls(id=session, session=session)
        return cls(id=f"{session}/{conversation}", session=session)


class Operator(Party):
    """The operator, from the dashboard or from a terminal on their machine, where a command carries their authority."""

    party: Literal["operator"] = "operator"
    """Which of the core's parties it is, as a call across containers names it."""


class Codebase(Party):
    """A project's own code, calling a service of a module's as a plain call: a method of one of its classes, or a program of its own.

    Identified by its repository, which whoever carries the call vouches for
    from where the call came, never what the caller says of itself: the
    container a call came from runs one project's code, so lup can tell
    projects apart, not the classes of one project.
    """

    party: Literal["code"] = "code"
    """Which of the core's parties it is, as a call across containers names it."""
    repository: str
    """The repository whose code calls, as lup names it."""


class Machine(Party):
    """The operator's machine's own parts: the home repository's code, from the commit the operator approved, running on their machine, calling each other.

    Only a call made where those parts run is by `Machine`: nothing carrying a
    call from a container names it, so code a container runs, the home
    repository's own branch among it, never is.
    """

    party: Literal["machine"] = "machine"
    """Which of the core's parties it is, as a call across containers names it."""


def said(parties: list[type[Party]]) -> str:
    """Name `parties` as a type naming them does, a union for several.

    >>> said([Agent, Operator])
    '`Agent | Operator`'
    """
    return f"`{' | '.join(each.__name__ for each in parties)}`"
