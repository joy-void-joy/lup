"""The items of lup's inbox one conversation exchanged, as a module's view reads them: the core keeps them, and a view weaves them in.

A conversation's view (`Transcripts`' drawer) shows each item the conversation
sent or was sent where it happened. The items are the inbox's, which the host
service holds, and no module owns: the core never imports a module, so a view
asks the core for them (`Exchanges`), and the core answers from the host
service, as `inbox-list-items` does (`HostExchanges`, in the repository's
process, `lup_dev.worker`). Only the interface is here, so a module's context
imports nothing of the host's client.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lup.blocks import OfAgent
    from lup_dev.inbox.protocol import Exchanged


class Exchanges(ABC):
    """Where a module's views read the items of lup's inbox a conversation of their repository exchanged."""

    @abstractmethod
    async def exchanged(self, viewed: OfAgent) -> Exchanged:
        """Return the items the conversation `viewed` names sent, as it wrote them, and those it was sent, as it's told them, each oldest first."""
