"""The dashboard, as the host service runs it: its child, on localhost and on the addresses the operator names, for as long as the service serves.

`docs/dashboard.md`, *Running* and *Access*. `lup_dev` never imports the
dashboard (`lup_dashboard`, which imports `lup_dev`): it runs its command,
`lup-dashboard serve <port> [--address <address>]…`, found beside the
interpreter running the service, where the dashboard is installed with it. The
service writes the token its API wants as its input's first line, reads the
address it listens on from its output's first line, and keeps its input open:
the dashboard ends when that input closes, so it goes with the service, however
the service ends.

The token is kept in the host's state, which no room mounts, so a page left open
reconnects with the cookie it holds once the service, and the dashboard with it,
start again on the same port. `lup-dev dashboard` asks the service for the
address, the token in its fragment (`ShowDashboard`), starting the dashboard
again where it's gone, and draws the address another device opens as a QR code
(`QrCode`).
"""

import secrets
import shlex
from ipaddress import IPv6Address
from pathlib import Path
from typing import Literal, override
from urllib.parse import urlsplit

from lup.programs import ProgramError, Running, started
from lup.types import MutableModel
from lup_dev.host.protocol import HostError, Reply, Request
from lup_dev.host.service import Companion, Handler
from lup_dev.settings import Address


def hosted(address: Address) -> str:
    """Return `address` as a URL and a `Host` header write it: an IPv6 address in brackets.

    >>> from ipaddress import ip_address
    >>> hosted(ip_address("10.8.0.2")), hosted(ip_address("fd00::2"))
    ('10.8.0.2', '[fd00::2]')
    """
    return f"[{address}]" if isinstance(address, IPv6Address) else str(address)


class ShowDashboard(Request, reads=False):
    """Return the dashboard's addresses, its token in each fragment, starting it where it isn't running."""

    kind: Literal["dashboard"] = "dashboard"


class DashboardShown(Reply):
    """Where the dashboard is opened: its address on localhost and on each other address it listens on, the token its page trades for a cookie in each fragment."""

    kind: Literal["dashboard-shown"] = "dashboard-shown"
    address: str
    """On localhost: where the operator's browser opens it."""
    elsewhere: list[str] = []
    """On each address bound beyond localhost (`LUP_DASHBOARD_ADDRESSES`), in
    their order: what another device opens, a phone over WireGuard."""

    def chosen(self, host: str | None) -> str:
        """Return the address to show: the one on `host`, or the first beyond localhost, since that's what another device needs, else localhost's.

        Raise `HostError` where the dashboard listens on no `host`.

        >>> shown = DashboardShown(address="http://127.0.0.1:8766/#token=t",
        ...     elsewhere=["http://10.8.0.2:8766/#token=t", "http://[fd00::2]:8766/#token=t"])
        >>> shown.chosen(None)
        'http://10.8.0.2:8766/#token=t'
        >>> shown.chosen("fd00::2")
        'http://[fd00::2]:8766/#token=t'
        >>> shown.chosen("10.8.0.3")
        Traceback (most recent call last):
        ...
        lup_dev.host.protocol.HostError: the dashboard doesn't listen on 10.8.0.3: it listens on 127.0.0.1, 10.8.0.2, fd00::2
        """
        if host is None:
            return self.elsewhere[0] if self.elsewhere else self.address
        wanted = "127.0.0.1" if host == "localhost" else host
        every = [self.address, *self.elsewhere]
        listening = [urlsplit(each).hostname or "" for each in every]
        found = [
            each for each, on in zip(every, listening, strict=True) if on == wanted
        ]
        if found:
            return found[0]
        message = (
            f"the dashboard doesn't listen on {host}: it listens on "
            f"{', '.join(listening)}"
        )
        raise HostError(message)


class DashboardProcess(MutableModel, Companion, arbitrary_types_allowed=True):
    """The dashboard as a process of its own: `command`, the port and each address appended, the service's child, begun and ended with it."""

    command: list[str]
    """Its command without the port: `[<bin>/lup-dashboard, "serve"]`."""
    port: int
    """The port it listens on, on every address: the same each time it starts,
    so a page left open finds it again."""
    addresses: list[Address] = []
    """The addresses it listens on beyond localhost (`LUP_DASHBOARD_ADDRESSES`),
    each passed as `--address`."""
    token: Path
    """The file keeping its token, made the first time, readable by its owner alone."""
    process: Running | None = None
    address: str | None = None
    """Where it listens on localhost, as its output's first line said."""

    @override
    async def begin(self) -> None:
        await self.start()

    @override
    async def end(self) -> None:
        process = self.process
        if process is None or process.status is not None:
            return
        await process.ended()

    async def start(self) -> DashboardShown:
        """Start the dashboard where it isn't running, and return where it's opened: on localhost, and on each other address, the token in each fragment.

        The port the other addresses are opened at is the one localhost's
        address says, since port 0 takes a free one. Raise `HostError` where
        it can't start, saying why.
        """
        if self.process is None or self.process.status is not None:
            self.address = await self.spawned()
        token = self.kept()
        port = urlsplit(self.address).port
        return DashboardShown(
            address=f"{self.address}/#token={token}",
            elsewhere=[
                f"http://{hosted(each)}:{port}/#token={token}"
                for each in self.addresses
            ],
        )

    async def spawned(self) -> str:
        """Start the dashboard, its token its input's first line, and return the address its output's first line says it listens on, on localhost."""
        bound = [word for each in self.addresses for word in ["--address", str(each)]]
        command = [*self.command, str(self.port), *bound]
        try:
            process = await started(*command)
        except ProgramError as unstarted:
            raise HostError(str(unstarted)) from unstarted
        process.input.write(f"{self.kept()}\n".encode())
        await process.input.drain()
        listening = (await process.output.readline()).decode().strip()
        if not listening:
            status = await process.ended()
            message = (
                f"`{shlex.join(command)}` ended with status {status} before listening, "
                f"as on a port another program holds ({self.port}, "
                "`LUP_DASHBOARD_PORT`); what it said is in the host service's output"
            )
            raise HostError(message)
        self.process = process
        return listening

    def kept(self) -> str:
        """Return the dashboard's token, making it the first time."""
        if not self.token.is_file():
            self.token.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.token.touch(mode=0o600)
            self.token.write_text(secrets.token_urlsafe(32))
        return self.token.read_text()


class Showing(MutableModel, Handler[ShowDashboard], arbitrary_types_allowed=True):
    """Answers `ShowDashboard`: the dashboard's addresses, starting it where it's gone; where it isn't installed, why."""

    dashboard: DashboardProcess | None
    missing: str
    """Why there's no dashboard, where there's none: said when it's asked for."""

    @override
    def request(self) -> type[ShowDashboard]:
        return ShowDashboard

    @override
    async def answer(self, request: ShowDashboard) -> Reply:
        if self.dashboard is None:
            raise HostError(self.missing)
        return await self.dashboard.start()
