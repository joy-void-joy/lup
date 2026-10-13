"""`Room`: an agent behind a wall, opened in a terminal.

    room = Room(agent=agent, container=Container(image=image, mounts=mounts))
    status = room.launch(arguments=["--resume"], settings=settings)

A launch compiles the agent for a terminal (`Declaration.terminal`), writes the
files it needs, builds the room's image if it's missing, and runs the CLI in the
container in the foreground, in the directory it's launched from, with the
room's home a tmpfs at the host's home path. It returns the CLI's exit status.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from lup.rooms.container import Container, Mount
from lup.rooms.engine import ContainerEngine, ContainerError, Invocation, Podman
from lup.sessions.declaration import Declaration
from lup.types import Model

if TYPE_CHECKING:
    from lup.sessions.terminal import TerminalSettings


class Room(Model, arbitrary_types_allowed=True):
    """An agent and the container it works in."""

    agent: Declaration
    container: Container
    engine: ContainerEngine = Podman()
    """Builds the image and runs the container; a test gives a recording one."""

    def launch(self, arguments: list[str], settings: TerminalSettings) -> int:
        """Open the agent's CLI in the room, in this terminal, and return its exit status.

        `arguments` go to the CLI after lup's own, so `["--resume"]` resumes. The
        working directory must be inside a mount, and the room's variables can't
        disagree with the ones the CLI needs.
        """
        terminal = self.agent.terminal(settings)
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
        for path, text in terminal.files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.engine.ensure(container.image)
        return self.engine.run(
            Invocation(
                container=container,
                command=[*terminal.command, *arguments],
                workdir=workdir,
                home=Path.home(),
                terminal=sys.stdin.isatty(),
            )
        )
