"""Watching what the host service holds: a request's reply, sent again each time it changes.

`docs/host-tools.md`, *Watching*. What the service holds changes in a few places
alone: a request answered on one of its sockets, a hook answered, an item of the
inbox written. Each tells `Changes`. A watch is a connection on the service's
watch socket carrying one control request (`Dispatcher.watching`): it's answered
at once, then again at each change, its reply sent where it differs from the one
sent last. So a watcher sees only what a request fetches, as the operator's
commands do, and nothing is polled.
"""

import asyncio

from pydantic import Field

from lup.types import MutableModel


class Changes(MutableModel, arbitrary_types_allowed=True):
    """How many times what the service holds may have changed, and a wait for the next.

    Told and waited on from the service's event loop alone.
    """

    count: int = 0
    next: asyncio.Event = Field(default_factory=asyncio.Event)
    """Set at the next change, and replaced by a fresh one."""

    def changed(self) -> None:
        """Say that what the service holds may have changed, waking each wait."""
        self.count += 1
        fired = self.next
        self.next = asyncio.Event()
        fired.set()

    async def after(self, seen: int) -> int:
        """Wait until the count is past `seen`, and return it."""
        while self.count == seen:
            await self.next.wait()
        return self.count
