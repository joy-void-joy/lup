"""Watching what the host service holds: a request's reply, sent again each time it changes.

`docs/host.md`, *Watching*. What the service holds changes in a few places
alone: a request answered on one of its sockets, a hook answered, an item of the
inbox written. Each tells `Changes`. A watch is a connection on the service's
watch socket carrying one control request (`Dispatcher.watching`): it's answered
at once, then again at each change, its reply sent where it differs from the one
sent last. So a watcher sees only what a request fetches, as the operator's
commands do, and nothing is polled.

A hook and an item also say which conversation they touched, and how
(`Touched`): a module's view of one agent is answered again at that agent's
touches alone (`host/views.py`), since each answer asks its repository's
process, where answering every watch at every change anywhere would ask it at
each hook of every agent.
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from lup.events import EventName
from lup.types import Model, MutableModel

if TYPE_CHECKING:
    from collections.abc import Iterable


class Touched(Model):
    """A conversation a change touched, by its repository and its runtime's ids, and how: at one of its hooks, by its event's name, or by an item of the inbox it sent or was sent (`item`)."""

    repository: Path
    """The repository's git directory, as its launch registered it."""
    runtime: str
    session: str
    """The runtime's id for the session."""
    agent: str | None = None
    """The runtime's id for the subagent; none for the session's own conversation."""
    by: Literal["item"] | EventName


class Changes(MutableModel, arbitrary_types_allowed=True):
    """How many times what the service holds may have changed, which conversations each change touched, and a wait for the next.

    Told and waited on from the service's event loop alone.
    """

    count: int = 0
    next: asyncio.Event = Field(default_factory=asyncio.Event)
    """Set at the next change, and replaced by a fresh one."""
    touches: dict[Touched, int] = {}
    """The count at the last change touching each conversation so, a conversation
    and how: one each, however many times it's touched."""

    def changed(self, touched: Iterable[Touched] = ()) -> None:
        """Say that what the service holds may have changed, touching `touched`, waking each wait."""
        self.count += 1
        self.touches = {**self.touches, **dict.fromkeys(touched, self.count)}
        fired = self.next
        self.next = asyncio.Event()
        fired.set()

    async def after(self, seen: int) -> int:
        """Wait until the count is past `seen`, and return it."""
        while self.count == seen:
            await self.next.wait()
        return self.count

    async def touching(self, wanted: list[Touched], seen: int) -> int:
        """Wait until a change after the count `seen` touched one of `wanted`, and return the count then; none wanted waits for ever."""
        while all(self.touches.get(each, 0) <= seen for each in wanted):
            await self.next.wait()
        return self.count
