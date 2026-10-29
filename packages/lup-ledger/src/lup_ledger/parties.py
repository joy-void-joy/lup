"""Who writes the ledger's records: the operator, or a conversation of a session.

Each is the inbox's party of the same name, field for field and tag for tag, so a
record and an item say who they're from alike, stored and sent, and a
conversation's key (`Conversation.key`) names the same file either way.
"""

import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from lup.types import Model


# lup: defer(issue=345, why="the inbox keeps its own `Operator` and `Conversation` (`lup_dev.inbox.store`) until its items are nodes; then it imports these and drops its own")
class Operator(Model):
    """The operator."""

    party: Literal["operator"] = "operator"


class Conversation(Model):
    """A conversation of a session, within a repository: the session's main one, or one of their subagents.

    Known by the runtime's ids, which never change, rather than by a name, which
    `rename` changes.
    """

    party: Literal["conversation"] = "conversation"
    repository: Path
    """The repository's git directory, as the launch registered it."""
    runtime: str
    session: str
    """The runtime's id for the session."""
    agent: str | None = None
    """The runtime's id for the subagent; none for the session's main conversation."""

    def key(self) -> str:
        """Name the conversation as a file name, from what keys it.

        >>> len(Conversation(repository=Path("/work/lup.git"), runtime="r", session="a1").key())
        64
        """
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()

    def main(self) -> Conversation:
        """Return its session's main conversation."""
        return self.model_copy(update={"agent": None})


type Party = Annotated[Operator | Conversation, Field(discriminator="party")]
"""Who wrote a record."""
