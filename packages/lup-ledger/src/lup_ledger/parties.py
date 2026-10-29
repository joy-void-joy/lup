"""Who writes the ledger's records: the operator, a conversation of a session, or lup itself.

The operator and a conversation are the inbox's parties, what an item is from
and for (`lup_dev.inbox.store` takes them from here), so a record and an item
say who they're from alike, and a conversation's key (`Conversation.key`) is
the one the inbox's files were named by. lup writes what it does of its own
accord, such as telling an item, and is a writer, never a party.
"""

import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from lup.types import Model


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
"""Who speaks: what an item is from and for, and who holds a thread."""


class Lup(Model):
    """lup itself, writing what it does of its own accord: an item told, put back, or taken back at a landing."""

    party: Literal["lup"] = "lup"


type Writer = Annotated[Operator | Conversation | Lup, Field(discriminator="party")]
"""Who wrote a record: a party, or lup."""
