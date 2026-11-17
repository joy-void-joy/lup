"""Who calls a module's method: the parties its `by` is written as.

A party is a class deriving from `Party`, which any module may declare, and a
method's `by` both says who may call it (`by: Agent`, `by: Agent | Operator`)
and hands it the caller (`README.md` here, *Who calls*). The core's parties
carry only what identifies them: what an agent is, beyond lup's id for them, is
the pieces' that start sessions and hold concerns, which give the id its type.
"""

from typing import Literal

from lup.types import Model


class Party(Model):
    """Someone a module's method is called by: each a class of its own, which a method's `by` is typed as, and which any module may declare."""


class Agent(Party):
    """An agent: a session's own conversation, or one of their subagents', calling one of their tools, or running a command from their room.

    Identified by lup's id for them, which stays put as they're renamed; the id
    becomes the conversation's own type, with the session it's in, once lup
    starts sessions (#5).
    """

    party: Literal["agent"] = "agent"
    """Which of the core's parties it is, as a call across containers names it."""
    id: str
    """lup's id for the agent."""


class Operator(Party):
    """The operator, from the dashboard or from a terminal on their machine, where a command carries their authority."""

    party: Literal["operator"] = "operator"
    """Which of the core's parties it is, as a call across containers names it."""


class Code(Party):
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


def said(parties: list[type[Party]]) -> str:
    """Name `parties` as a type naming them does, a union for several.

    >>> said([Agent, Operator])
    '`Agent | Operator`'
    """
    return f"`{' | '.join(each.__name__ for each in parties)}`"
