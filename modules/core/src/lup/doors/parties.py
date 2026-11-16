"""Who calls a module's method: the parties its `by` is written as.

A party is a class deriving from `Party`, which any module may declare, and a
method's `by` both says who may call it (`by: Agent`, `by: Agent | Operator`)
and hands it the caller (`README.md` here, *Who calls*). The core's parties
carry only what identifies them: what an agent is, beyond lup's id for them, is
the pieces' that start sessions and hold concerns, which give the id its type.
"""

from lup.types import Model


class Party(Model):
    """Someone a module's method is called by: each a class of its own, which a method's `by` is typed as, and which any module may declare."""


class Agent(Party):
    """An agent: a session's own conversation, or one of their subagents', calling one of their tools, or running code in their room that sends a request or runs a command.

    Identified by lup's id for them, which stays put as they're renamed; the id
    becomes the conversation's own type, with the session it's in, once lup
    starts sessions (#5).
    """

    id: str
    """lup's id for the agent."""


class Operator(Party):
    """The operator, from the dashboard or from a terminal on their machine, where a command carries their authority."""


def said(parties: list[type[Party]]) -> str:
    """Name `parties` as a type naming them does, a union for several.

    >>> said([Agent, Operator])
    '`Agent | Operator`'
    """
    return f"`{' | '.join(each.__name__ for each in parties)}`"
