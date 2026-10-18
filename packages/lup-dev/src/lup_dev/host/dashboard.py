"""The dashboard, as the host service runs it: its child, on localhost, for as long as the service serves.

`docs/dashboard.md`, *Running*. `lup_dev` never imports the dashboard
(`lup_dashboard`, which imports `lup_dev`): it runs its command, `lup-dashboard
serve <port>`, found beside the interpreter running the service, where the
dashboard is installed with it. The service writes the token its API wants as
its input's first line, reads the address it listens on from its output's
first line, and keeps its input open: the dashboard ends when that input
closes, so it goes with the service, however the service ends.

The token is kept in the host's state, which no room mounts, so a page left open
reconnects with the cookie it holds once the service, and the dashboard with it,
start again on the same port. `lup-dev dashboard` asks the service for the
address, the token in its fragment (`ShowDashboard`), starting the dashboard
again where it's gone.
"""

import asyncio
import secrets
import shlex
from pathlib import Path
from typing import Literal, override

from lup.types import MutableModel
from lup_dev.host.protocol import HostError, Reply, Request
from lup_dev.host.service import Companion, Handler


class ShowDashboard(Request):
    """Return the dashboard's address, its token in the fragment, starting it where it isn't running."""

    kind: Literal["dashboard"] = "dashboard"


class DashboardShown(Reply):
    """Where the operator opens the dashboard: its address, the token its page trades for a cookie in the fragment."""

    kind: Literal["dashboard-shown"] = "dashboard-shown"
    address: str


class DashboardProcess(MutableModel, Companion, arbitrary_types_allowed=True):
    """The dashboard as a process of its own: `command`, the port appended, the service's child, begun and ended with it."""

    command: list[str]
    """Its command without the port: `[<bin>/lup-dashboard, "serve"]`."""
    port: int
    """The port it listens on, on localhost: the same each time it starts, so a
    page left open finds it again."""
    token: Path
    """The file keeping its token, made the first time, readable by its owner alone."""
    process: asyncio.subprocess.Process | None = None
    address: str | None = None

    @override
    async def begin(self) -> None:
        await self.start()

    @override
    async def end(self) -> None:
        process = self.process
        if process is None or process.returncode is not None:
            return
        if process.stdin is not None:
            process.stdin.close()
        await process.wait()

    async def start(self) -> str:
        """Start the dashboard where it isn't running, and return the address it's opened at, its token in the fragment.

        Raise `HostError` where it can't start, saying why.
        """
        if self.process is None or self.process.returncode is not None:
            self.address = await self.spawned()
        return f"{self.address}/#token={self.kept()}"

    async def spawned(self) -> str:
        """Start the dashboard, its token its input's first line, and return the address its output's first line says it listens on."""
        command = [*self.command, str(self.port)]
        try:
            # lup: ignore("subprocess", why="the host service keeps the dashboard running beside its event loop, its input held open so it ends with the service, which sh can't: it forks, and holds a thread per program")
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
            )
        except OSError as missing:
            message = f"`{shlex.join(command)}` doesn't run: {missing}"
            raise HostError(message) from missing
        if process.stdin is None or process.stdout is None:
            message = f"`{shlex.join(command)}` started without its pipes"
            raise HostError(message)
        process.stdin.write(f"{self.kept()}\n".encode())
        await process.stdin.drain()
        listening = (await process.stdout.readline()).decode().strip()
        if not listening:
            status = await process.wait()
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
    """Answers `ShowDashboard`: the dashboard's address, starting it where it's gone; where it isn't installed, why."""

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
        return DashboardShown(address=await self.dashboard.start())
