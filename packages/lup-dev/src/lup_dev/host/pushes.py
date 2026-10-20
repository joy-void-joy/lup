"""Each launch's open connections to lup's tool server: where what's pushed to its session goes.

`docs/host-tools.md`, *How an agent is told*. The host service keeps each
connection on a launch's `mcp.sock` here while it serves it (`tools_served`),
and the inbox pushes to the newest of a launch's (`Delivery.wake`): a session
holds one connection, and its bridge connects again once the service restarts,
the connection before it closed.
"""

from lup.tools.serving import Notice, Outbox
from lup.types import MutableModel


class Pushes(MutableModel, arbitrary_types_allowed=True):
    """Each launch's open connections to lup's tool server, oldest first, by launch id."""

    open: dict[str, list[Outbox]] = {}

    def opened(self, launch: str, outbox: Outbox) -> None:
        """Keep `outbox`, a connection of `launch`'s just opened."""
        self.open = {**self.open, launch: [*self.open.get(launch, []), outbox]}

    def closed(self, launch: str, outbox: Outbox) -> None:
        """Forget `outbox`, a connection of `launch`'s just closed."""
        kept = [each for each in self.open.get(launch, []) if each is not outbox]
        self.open = {**self.open, launch: kept}

    def push(self, launch: str, notice: Notice) -> bool:
        """Push `notice` on `launch`'s newest open connection, and say whether it had one."""
        outboxes = self.open.get(launch, [])
        if not outboxes:
            return False
        outboxes[-1].put(notice)
        return True
