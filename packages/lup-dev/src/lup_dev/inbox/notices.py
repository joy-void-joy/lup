"""Where the operator is told something at once: the desktop's notices.

The inbox raises one for each item that reaches the operator
(`docs/host-tools.md`, *The operator's face*). `notify-send` is an optional
requirement of the host (`launch/room.py`, `host_needs`): where it isn't
installed, no notice is raised, and a launch says so once.

A notice is raised through asyncio, as the host service runs every program, and
awaited: `sh` forks, running Python in the child before the program starts,
which can deadlock a process with threads (#23), and the service's event loop
mustn't wait on it.
"""

import asyncio
import shutil
from abc import ABC, abstractmethod
from typing import override

import typer

from lup.types import Model


class Notices(ABC):
    """Where the operator is told something at once."""

    @abstractmethod
    async def notify(self, summary: str, body: str) -> None:
        """Tell the operator `summary`, with `body` beneath it."""


class NotifySend(Notices, Model):
    """The desktop's notices, raised through `notify-send` where it's installed."""

    executable: str = "notify-send"
    application: str = "lup"
    """The application the desktop names as raising the notice."""

    @override
    async def notify(self, summary: str, body: str) -> None:
        """Raise the notice; on a machine without `notify-send`, none is shown.

        A notice that fails is said on standard error, the host service's log
        where the service raises it, and what it announced stands all the same.
        """
        program = shutil.which(self.executable)
        if program is None:
            return
        try:
            # lup: ignore("subprocess", why="raised from the host service's event loop, which sh can't share: it forks, which can deadlock a process with threads (#23)")
            process = await asyncio.create_subprocess_exec(
                program,
                f"--app-name={self.application}",
                summary,
                body,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, error = await process.communicate()
        except OSError as unrun:
            typer.echo(f"lup-dev: the desktop notice failed: {unrun}", err=True)
            return
        if process.returncode != 0:
            typer.echo(
                f"lup-dev: the desktop notice failed: {error.decode(errors='replace')}",
                err=True,
            )
