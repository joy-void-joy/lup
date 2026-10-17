"""The host service, as the dashboard reaches it: a request asked, or watched as its reply changes.

`docs/dashboard.md`, *The API*. `Host` is the seam the server talks through, so
its tests give their own; `Sockets` reaches the running service on its control
and watch sockets (`lup_dev/host/client.py`, which holds how each is spoken).
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, override

from pydantic import TypeAdapter

from lup.types import Model
from lup_dashboard.api import Asked, Replied
from lup_dev.host.client import answer, replies
from lup_dev.host.protocol import Refused
from lup_dev.layout import HostLayout

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator


class Host(ABC):
    """The host service, as the dashboard asks it."""

    @abstractmethod
    async def ask(self, request: Asked) -> Replied:
        """Return the host's reply to `request`, a refusal among them.

        Raise `HostError` where the host service can't be reached.
        """

    @abstractmethod
    def watch(self, request: Asked) -> AsyncIterator[Replied]:
        """Yield the host's reply to `request` at once, then again each time it changes, until closed; a refusal is the last.

        Raise `HostError` where the host service can't be reached, or closes the
        watch, as a service stopping does.
        """


class Sockets(Model, Host):
    """The host service on its own sockets, as `layout` places them."""

    layout: HostLayout

    @override
    async def ask(self, request: Asked) -> Replied:
        return read(await answer(self.layout.control, request))

    @override
    async def watch(self, request: Asked) -> AsyncGenerator[Replied]:
        async for line in replies(self.layout.watch, request):
            replied = read(line)
            yield replied
            if isinstance(replied, Refused):
                return


def read(written: bytes) -> Replied:
    """Read one reply of the host's, as it wrote it."""
    return TypeAdapter[Replied](Replied).validate_json(written)
