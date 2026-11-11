"""`Room`: an agent behind a wall, opened in a terminal or held with none.

    room = Room(
        agent=agent,
        container=Container(image=image, mounts=mounts),
        home_source=home,
    )
    status = room.launch(arguments=["--resume"], settings=settings)

A launch compiles the agent for a terminal (`Declaration.terminal`), prepares
what it needs (`Terminal.prepare`: its files, directories and copies, and what
each mount inside the runtime's home lands on), builds the room's image if it's
missing, and runs the CLI in the container in the foreground, in the directory
it's launched from, with the room's home the directory it's given, mounted at
the host's home path. It returns the CLI's exit status; what the runtime saved
that a launch carries back (`Terminal.preferences`) is the launch's to carry.

`hold` starts the same room with no terminal, the agent compiled as a session
held over its input and output (`Declaration.held`, `lup.sessions.held`), those
a socket the caller listens on, and returns it running beside the caller's
event loop.
"""

import asyncio
import inspect
import socket
import sys
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from lup.rooms.container import AbsolutePath, Container, Mount
from lup.rooms.engine import (
    Contained,
    ContainerEngine,
    ContainerError,
    Invocation,
    Piped,
    Pipes,
    Podman,
)
from lup.sessions import connected
from lup.sessions.declaration import Declaration
from lup.types import Model

if TYPE_CHECKING:
    from lup.sessions.terminal import Terminal, TerminalSettings


class Room(Model, arbitrary_types_allowed=True):
    """An agent and the container they work in."""

    agent: Declaration
    container: Container
    home_source: AbsolutePath
    """The host's directory that's the room's home, at the host's home path in the
    room: the run makes it (`Invocation.home_source`), and whoever gives it
    removes it."""
    engine: ContainerEngine = Podman()
    """Builds the image and runs the container; a test gives a recording one."""
    before: list[str] = []
    """A program the CLI runs behind, in the room, and its first arguments:
    given the CLI's command after them, it starts what the room starts first,
    then runs the CLI in its own place. None by default."""

    def launch(self, arguments: list[str], settings: TerminalSettings) -> int:
        """Open the agent's CLI in the room, in this terminal, and return its exit status.

        `arguments` go to the CLI after lup's own, so `["--resume"]` resumes. The
        working directory must be inside a mount, and the room's variables can't
        disagree with the ones the CLI needs.
        """
        terminal = self.agent.terminal(settings)
        invocation = self.invocation(terminal, arguments)
        terminal.prepare()
        self.engine.ensure(invocation.container.image)
        return self.engine.run(
            invocation.model_copy(update={"terminal": sys.stdin.isatty()})
        )

    async def hold(
        self,
        arguments: list[str],
        settings: TerminalSettings,
        *,
        listening: Path,
        connecting: Path,
        within: timedelta = timedelta(minutes=1),
    ) -> Piped:
        """Start the agent's runtime in the room as a session held with no terminal (`Declaration.held`), its input and output a socket of the caller's, and return it running.

        The caller listens at `listening`, which the room reaches at
        `connecting`, for one connection: the room's first program's
        (`lup.sessions.connected`), which puts it on its input and output, then
        runs the room's own start and the runtime in its place, `arguments`
        after lup's own, as for `launch`, which checks the same. The listener is
        closed and removed once it's accepted, so nothing in the room that
        starts after can reach it. Raise `ContainerError` where nothing connects
        within `within`, or the room's program ends first, its run made to end.
        """
        held = self.agent.held(settings)
        wrapper = settings.directory / "connected.py"
        held = held.model_copy(
            update={"files": {**held.files, wrapper: inspect.getsource(connected)}}
        )
        invocation = self.invocation(
            held,
            arguments,
            first=["python3", "-I", str(wrapper), str(connecting)],
        )
        held.prepare()
        self.engine.ensure(invocation.container.image)
        listener = listened(listening)
        try:
            run = await self.engine.held(invocation)
            connection = await accepted(listener, run, within)
        finally:
            unlistened(listener, listening)
        reader, writer = await asyncio.open_unix_connection(
            sock=connection, limit=64 * 2**20
        )
        return Piped(run=run, pipes=Pipes(input=writer, output=reader))

    def invocation(
        self, terminal: Terminal, arguments: list[str], first: list[str] | None = None
    ) -> Invocation:
        """Return the run of `terminal`'s command in the room, `arguments` after it, `first` before the room's own start, in the directory it's started from.

        Raise `ContainerError` where the room's variables disagree with the ones
        the command needs, or the working directory isn't inside a mount.
        """
        own = self.container
        clashing = [
            name
            for name, value in terminal.env.items()
            if own.env.get(name, value) != value
        ]
        if clashing:
            message = (
                f"the room sets {', '.join(clashing)} otherwise than "
                f"{self.agent.runtime}'s terminal needs: leave them out of the "
                "container's variables"
            )
            raise ContainerError(message)
        container = Container(
            image=own.image,
            mounts=[*own.mounts, *terminal.mounts],
            env={**own.env, **terminal.env},
            network=own.network,
            name=own.name,
        )
        workdir = Path.cwd()
        mounted = [
            mount.destination for mount in container.mounts if isinstance(mount, Mount)
        ]
        if not any(workdir.is_relative_to(destination) for destination in mounted):
            message = (
                f"the room doesn't mount the working directory {workdir}, so the "
                "session would start in an empty directory: mount it, or launch "
                "from inside a mount"
            )
            raise ContainerError(message)
        return Invocation(
            container=container,
            command=[*(first or []), *self.before, *terminal.command, *arguments],
            workdir=workdir,
            home=Path.home(),
            home_source=self.home_source,
        )


def listened(place: Path) -> socket.socket:
    """Listen at `place`, anything there replaced, for one connection, not blocking."""
    place.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(place))
    listener.listen(1)
    listener.settimeout(0)
    return listener


def unlistened(listener: socket.socket, place: Path) -> None:
    """Stop listening at `place`, and remove it, so nothing reaches what listened there."""
    listener.close()
    place.unlink(missing_ok=True)


async def accepted(
    listener: socket.socket, run: Contained, within: timedelta
) -> socket.socket:
    """Accept the one connection a held room's first program makes on `listener`, a socket listening, not blocking; where none comes within `within`, or the room's program ends first, make the run end, and raise `ContainerError`.

    A line of the runtime's output can be long, a tool's whole result, so its
    reader takes lines of up to 64 MiB.
    """
    loop = asyncio.get_running_loop()
    accepting = asyncio.ensure_future(loop.sock_accept(listener))
    exiting = asyncio.ensure_future(run.waited())
    done, _ = await asyncio.wait(
        [accepting, exiting],
        timeout=within.total_seconds(),
        return_when=asyncio.FIRST_COMPLETED,
    )
    exiting.cancel()
    if accepting in done:
        connection, _ = accepting.result()
        return connection
    accepting.cancel()
    how = (
        f"ended with status {exiting.result()}"
        if exiting in done
        else f"didn't connect within {within}"
    )
    run.signalled("made")
    message = f"the held room's first program {how}, so nothing holds its session"
    raise ContainerError(message)
