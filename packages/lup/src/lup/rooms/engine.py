"""Running containers: the engine a room runs on, and podman, its one implementation.

A run is in the foreground and removed when it exits, and every run is walled the
same way (`docs/launch.md`, *The user, the process, the network*):
- `--userns=keep-id`: the operator's uid inside, so what the agent writes is
  theirs on the host;
- `--init`, which reaps exited processes: without it the first lup piled up 4,045
  zombies against its pids limit;
- `--cap-drop=all` and `no-new-privileges`, so no capability carries in;
- the home a tmpfs at the path the run gives, owned by the operator, with `HOME`
  set to it: keep-id otherwise sets `HOME` to the working directory, where the
  runtimes would write their state;
- each directory between the home and a mount inside it a tmpfs owned by the
  operator too: podman makes the missing ones owned by root, and uv refused a
  root-owned `~/.cache`;
- with a terminal, `-it` and no detach keys, so Ctrl+P reaches the program rather
  than podman, whose default detach sequence starts with it;
- no log driver, so the session's output isn't kept in podman's logs, which go to
  the journal on a host using journald;
- `--pull=never`, so a run uses the image `ensure` built and never fetches one by
  a short name.

Each mount is written as podman's `--mount` option, a CSV record, so a path holding
a comma is quoted rather than split.

What this relies on, measured with rootless podman 6.1.3 (`docs/field-notes.md`,
*Rooms*, the engine's command lines):
- a quoted CSV field in `--mount` (`"source=/a,b"`) mounts a path holding a comma;
- a tmpfs mounted with `U=true` and `tmpfs-mode=0700` is owned by the operator
  under keep-id, and runs programs (unlike `--tmpfs`, whose default is `noexec`),
  while a directory podman makes for a mount inside it is owned by root;
- `podman build --file -` reads the Containerfile from its input, with the
  context given apart; `podman image exists` answers 0 or 1;
- `podman images --format json` lists each image's `Id`, `Names`, `Created`,
  `Size` and `Containers`, the containers using it;
- `podman run` answers 125 when podman itself fails, and the program's own status
  otherwise.
"""

import csv
import io
import subprocess  # lup: ignore("subprocess", why="the library runs podman through the standard library, since `sh` isn't one of its dependencies (`docs/launch.md`, *The library*)")
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import override

from pydantic import TypeAdapter, model_validator
from pydantic.alias_generators import to_pascal

from lup.errors import LupError
from lup.rooms.container import AbsolutePath, Container, Image, Mask, Mount
from lup.sessions.contract import guarded
from lup.sessions.errors import RealCallInTestError
from lup.types import Model

PROJECT_LABEL = "lup.project"
"""The label naming the project an image is built for."""


class ContainerError(LupError):
    """A container that couldn't be built or run as it was given."""


class Invocation(Model):
    """One foreground run of a command in a container."""

    container: Container
    command: list[str]
    workdir: AbsolutePath
    home: AbsolutePath
    """The room's home: an empty tmpfs owned by the operator, and `HOME`."""
    terminal: bool = False
    """Whether the run is attached to a terminal, with its input kept open."""

    @model_validator(mode="after")
    def home_is_the_runs(self) -> Invocation:
        """Refuse a container setting `HOME` itself, since the run sets it to the room's home."""
        if "HOME" in self.container.env:
            message = (
                "the container sets `HOME`, which the run sets to the room's home "
                f"({self.home}): leave it out of the container's variables"
            )
            raise ValueError(message)
        return self


class ContainerEngine(ABC):
    """Builds a room's image and runs its container."""

    @abstractmethod
    def ensure(self, image: Image) -> bool:
        """Build `image` if its tag is missing, and say whether it was built."""

    @abstractmethod
    def run(self, invocation: Invocation) -> int:
        """Run the invocation's container in the foreground until it exits, and return its exit status."""


class Process(Model):
    """A program to run: its arguments, the text on its input, and whether its output is kept."""

    arguments: list[str]
    input: str | None = None
    """Written to its input, which is closed after; none leaves this process's own."""
    capture: bool = False
    """Keep what it prints, rather than letting it reach this process's output."""


class Exited(Model):
    """How a program ended: its exit status, and what it printed where that was kept."""

    status: int
    output: str = ""


def run_process(process: Process) -> Exited:
    """Run `process` to its end, unless real runs are refused, as in tests."""
    if guarded.get():
        message = (
            "a test reached podman: give the engine a recording `execute`, or the "
            "room a recording engine"
        )
        raise RealCallInTestError(message)
    completed = subprocess.run(
        process.arguments,
        input=process.input,
        stdout=subprocess.PIPE if process.capture else None,
        text=True,
        check=False,
    )
    return Exited(status=completed.returncode, output=completed.stdout or "")


class StoredImage(Model, alias_generator=to_pascal, populate_by_name=True):
    """An image podman holds, as `podman images` lists it."""

    id: str
    names: list[str] = []
    created: datetime
    size: int
    """Its size in bytes."""
    containers: int
    """How many containers use it, running or stopped."""


def mount_option(fields: list[str]) -> str:
    """Return podman's `--mount` value for these `key=value` fields: one CSV record."""
    record = io.StringIO()
    csv.writer(record, lineterminator="").writerow(fields)
    return record.getvalue()


class Podman(Model, ContainerEngine):
    """Runs containers with rootless podman."""

    program: str = "podman"
    execute: Callable[[Process], Exited] = run_process
    """Runs each podman command; a test gives a recording one."""

    @override
    def ensure(self, image: Image) -> bool:
        """Build `image` with its project's label if its tag is missing, and say whether it was built."""
        exists = self.execute(
            Process(arguments=[self.program, "image", "exists", image.tag])
        )
        match exists.status:
            case 0:
                return False
            case 1:
                pass
            case status:
                message = (
                    f"podman couldn't say whether {image.tag} exists (status {status})"
                )
                raise ContainerError(message)
        with tempfile.TemporaryDirectory() as context:
            built = self.execute(
                Process(
                    arguments=[
                        self.program,
                        "build",
                        "--tag",
                        image.tag,
                        "--label",
                        f"{PROJECT_LABEL}={image.project}",
                        "--file",
                        "-",
                        context,
                    ],
                    input=image.definition,
                )
            )
        if built.status != 0:
            message = f"podman couldn't build {image.tag} (status {built.status})"
            raise ContainerError(message)
        return True

    def command(self, invocation: Invocation) -> list[str]:
        """Return the command line that runs the invocation's container."""
        container = invocation.container
        home = invocation.home
        targets = [
            mount.destination if isinstance(mount, Mount) else mount.target
            for mount in container.mounts
        ]
        between = sorted(
            dict.fromkeys(
                parent
                for target in targets
                for parent in target.parents
                if parent != home and parent.is_relative_to(home)
            )
        )
        owned = [home, *(path for path in between if path not in targets)]

        def option(mount: Mount | Mask) -> str:
            match mount:
                case Mount(read_only=read_only):
                    fields = [
                        "type=bind",
                        f"source={mount.source}",
                        f"destination={mount.destination}",
                    ]
                    return mount_option([*fields, "ro=true"] if read_only else fields)
                case Mask(target=target):
                    return mount_option(
                        ["type=tmpfs", f"destination={target}", "notmpcopyup"]
                    )

        terminal = (
            ["--interactive", "--tty", "--detach-keys="] if invocation.terminal else []
        )
        network = "host" if container.network == "host" else "private"
        variables = {**container.env, "HOME": str(home)}
        return [
            self.program,
            "run",
            "--rm",
            "--init",
            "--pull=never",
            "--log-driver=none",
            "--userns=keep-id",
            "--cap-drop=all",
            "--security-opt=no-new-privileges",
            *terminal,
            f"--network={network}",
            f"--workdir={invocation.workdir}",
            *(f"--env={name}={value}" for name, value in variables.items()),
            *(
                "--mount="
                + mount_option(
                    [
                        "type=tmpfs",
                        f"destination={path}",
                        "tmpfs-mode=0700",
                        "U=true",
                    ]
                )
                for path in owned
            ),
            *(f"--mount={option(mount)}" for mount in container.mounts),
            container.image.tag,
            *invocation.command,
        ]

    @override
    def run(self, invocation: Invocation) -> int:
        """Run the invocation's container in the foreground, and return the program's exit status.

        A status of 125 is podman's own failure, not the program's, and raises.
        """
        exited = self.execute(Process(arguments=self.command(invocation)))
        if exited.status == 125:
            message = (
                f"podman couldn't run {invocation.container.image.tag} (status 125); "
                "what it said is above"
            )
            raise ContainerError(message)
        return exited.status

    def images(self, project: str) -> list[StoredImage]:
        """Return the images built for `project`, as podman lists them."""
        listed = self.execute(
            Process(
                arguments=[
                    self.program,
                    "images",
                    "--filter",
                    f"label={PROJECT_LABEL}={project}",
                    "--format",
                    "json",
                ],
                capture=True,
            )
        )
        if listed.status != 0:
            message = (
                f"podman couldn't list {project}'s images (status {listed.status})"
            )
            raise ContainerError(message)
        return TypeAdapter(list[StoredImage]).validate_json(listed.output)

    def remove(self, image: StoredImage) -> None:
        """Remove `image`; podman refuses one a container uses."""
        removed = self.execute(
            Process(arguments=[self.program, "image", "rm", image.id])
        )
        if removed.status != 0:
            message = (
                f"podman couldn't remove the image {image.id} (status {removed.status})"
            )
            raise ContainerError(message)
