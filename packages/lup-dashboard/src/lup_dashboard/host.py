"""The host service, as the dashboard reaches it: a request asked, or watched as its reply changes.

`docs/dashboard.md`, *The API*. `Host` is the seam the server talks through, so
its tests give their own; `Sockets` reaches the running service on its control
and watch sockets (`lup_dev/host/client.py`, which holds how each is spoken).

An approval of a host zone the operator approves on the page is acted on as
their terminal acts on it (`settle`): the copy installed and the host service
restarted on it, by `lup-dev inbox answer <n> --approve` in a process of its
own, which outlives the service it restarts, and this dashboard with it.
"""

import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, override

from pydantic import TypeAdapter

from lup.programs import detached
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

    @abstractmethod
    async def settle(self, number: int) -> None:
        """Act on approval `number`, approved on the page, as the operator's terminal does: install the copy it approves, and restart the host service on it where it's lup's own, in a process that outlives this one."""


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

    @override
    async def settle(self, number: int) -> None:
        # The `lup-dev` installed with this dashboard, in the same environment.
        command = Path(sys.executable).parent / "lup-dev"
        arguments = ["inbox", "answer", str(number), "--approve"]
        detached(command, *arguments, log=self.layout.log)


def read(written: bytes) -> Replied:
    """Read one reply of the host's, as it wrote it."""
    return TypeAdapter[Replied](Replied).validate_json(written)
