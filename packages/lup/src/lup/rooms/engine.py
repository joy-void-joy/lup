"""Running containers: the engine a room runs on, and podman, its one implementation.

A run is in the foreground and removed when it exits, and every run is walled the
same way (`docs/launch.md`, *The user, the process, the network*):
- `--userns=keep-id`: the operator's uid inside, so what the agent writes is
  theirs on the host;
- `--init`, which reaps exited processes: without it the first lup piled up 4,045
  zombies against its pids limit;
- `--cap-drop=all` and `no-new-privileges`, so no capability carries in;
- the home a directory of the host's the run is given, mounted at the path it
  gives, with `HOME` set to it: keep-id otherwise sets `HOME` to the working
  directory, where the runtimes would write their state. On disk rather than a
  tmpfs, which would hold what the room writes there in the host's memory;
- each directory and file a mount inside the home lands on made there by the
  run before podman starts, owned by the operator (`Invocation.landings`):
  podman makes the missing ones owned by root, which the operator can't
  remove, and uv refused a root-owned `~/.cache`. Not one inside another
  mount, a worktree above its hidden `.venv`: that's the host's own;
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
- a directory or file podman makes for a mount is owned by root, a subordinate
  uid on the host, and one the operator made before is theirs and is mounted
  over (podman 6.1.4, `docs/field-notes.md`, *The room's home on disk*);
- a tmpfs inside a bind mount is filled with a copy of what the mount holds at
  its path, unless it's `notmpcopyup`, as a mask is (podman 6.1.4,
  `docs/field-notes.md`, *A tmpfs inside a bind mount*);
- `podman build --file -` reads the Containerfile from its input, with the
  context given apart; `podman image exists` answers 0 or 1;
- `podman images --format json` lists each image's `Id`, `Names`, `Created`,
  `Size` and `Containers`, the containers using it;
- `podman run` answers 125 when podman itself fails, and the program's own status
  otherwise.

`podman container exists` answers 0 when a container of that name or id exists,
1 when none does, and 125 when podman itself fails (its man page,
`podman-container-exists(1)`); a run's `--name` names its container while it
runs, and `--rm` removes it when it exits. `podman rename` renames a container in
any state, running included, freeing its old name (`podman-rename(1)`).

A container a run created and never started stays, `created`, holding its
name: a launch that took the host down before its container started left two,
which the next launch's run met as "the container name … is already in use"
(podman 6.1.4). `podman ps --all --format json` lists each container's `Names`
and its `State`, `created` for that one.
"""

import csv
import io
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Literal, get_args, override

from pydantic import TypeAdapter, model_validator
from pydantic.alias_generators import to_pascal

from lup.errors import LupError
from lup.programs import ProgramMissingError, Ran, run
from lup.rooms.container import AbsolutePath, Container, Image, Mask, Mount
from lup.sessions.contract import guarded
from lup.sessions.errors import RealCallInTestError
from lup.types import Model

if TYPE_CHECKING:
    from pathlib import Path

PROJECT_LABEL = "lup.project"
"""The label naming the project an image is built for."""
type Stopped = Literal["configured", "created", "initialized", "exited", "stopped"]
"""The states of a container that isn't running, as podman names them: a run's
container in one was left by a launch that ended before it started or before
`--rm` removed it, and nothing runs in it."""


class ContainerError(LupError):
    """A container that couldn't be built or run as it was given."""


class Invocation(Model):
    """One foreground run of a command in a container."""

    container: Container
    command: list[str]
    workdir: AbsolutePath
    home: AbsolutePath
    """The room's home, and `HOME`."""
    home_source: AbsolutePath
    """The host's directory that's the room's home, mounted read-write at `home`:
    the run makes it, and in it what each mount inside the home lands on
    (`landings`); whoever gives it removes it."""
    terminal: bool = False
    """Whether the run is attached to a terminal, with its input kept open."""

    @property
    def landings(self) -> dict[Path, bool]:
        """Each path inside the home a mount lands on, and each directory on the way there, by its path in the room, with whether it's a directory: what the run makes in `home_source` first.

        A mount's own path is a directory where its source is one, else a file,
        and a mask's is a directory. A mount inside another mount lands on that
        mount's paths, the host's or a mask's tmpfs, and nothing is made for it.
        """
        home = self.home
        places = {
            (each.destination if isinstance(each, Mount) else each.target): (
                each.source.is_dir() if isinstance(each, Mount) else True
            )
            for each in self.container.mounts
        }
        landing = {
            target: directory
            for target, directory in places.items()
            if target != home
            and target.is_relative_to(home)
            and not any(
                target != each and target.is_relative_to(each) for each in places
            )
        }
        on_the_way = {
            parent: True
            for target in landing
            for parent in target.parents
            if parent != home and parent.is_relative_to(home)
        }
        return dict(sorted({**on_the_way, **landing}.items()))

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
    """Written to its input, which is closed after; none leaves it this
    process's own where its output isn't kept, and gives it none where it is."""
    capture: bool = False
    """Keep what it prints and what it says beside, rather than letting them
    reach this process's terminal."""


def run_process(process: Process) -> Ran:
    """Run `process` to its end through `lup.programs`, whatever its status, unless real runs are refused, as in tests.

    Raise `ContainerError` where the program isn't there, as where podman isn't
    installed.
    """
    if guarded.get():
        message = (
            "a test reached podman: give the engine a recording `execute`, or the "
            "room a recording engine"
        )
        raise RealCallInTestError(message)
    program, *arguments = process.arguments
    try:
        return run(
            program,
            *arguments,
            stdin=process.input,
            checked=False,
            shown=not process.capture,
        )
    except ProgramMissingError as missing:
        raise ContainerError(str(missing)) from missing


def stopped(state: str) -> bool:
    """Say whether a container in `state` isn't running (`Stopped`).

    >>> stopped("created"), stopped("running")
    (True, False)
    """
    return state in get_args(Stopped.__value__)


class StoredContainer(Model, alias_generator=to_pascal, populate_by_name=True):
    """A container podman holds, as `podman ps --all` lists it."""

    names: list[str]
    state: str


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
    execute: Callable[[Process], Ran] = run_process
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

        def option(mount: Mount | Mask) -> str:
            match mount:
                case Mount(read_only=read_only, receives=receives):
                    fields = [
                        "type=bind",
                        f"source={mount.source}",
                        f"destination={mount.destination}",
                        *(["ro=true"] if read_only else []),
                        *(["bind-propagation=rslave"] if receives else []),
                    ]
                    return mount_option(fields)
                case Mask(target=target):
                    return mount_option(
                        ["type=tmpfs", f"destination={target}", "notmpcopyup"]
                    )

        terminal = (
            ["--interactive", "--tty", "--detach-keys="] if invocation.terminal else []
        )
        network = "host" if container.network == "host" else "private"
        variables = {**container.env, "HOME": str(home)}
        named = [] if container.name is None else [f"--name={container.name}"]
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
            *named,
            *terminal,
            f"--network={network}",
            f"--workdir={invocation.workdir}",
            *(f"--env={name}={value}" for name, value in variables.items()),
            "--mount="
            + mount_option(
                [
                    "type=bind",
                    f"source={invocation.home_source}",
                    f"destination={home}",
                ]
            ),
            *(f"--mount={option(mount)}" for mount in container.mounts),
            container.image.tag,
            *invocation.command,
        ]

    @override
    def run(self, invocation: Invocation) -> int:
        """Run the invocation's container in the foreground, and return the program's exit status.

        Its home is made first, with what each mount inside it lands on
        (`Invocation.landings`). A status of 125 is podman's own failure, not the
        program's, and raises.
        """
        source = invocation.home_source
        source.mkdir(mode=0o700, parents=True, exist_ok=True)
        for path, directory in invocation.landings.items():
            landing = source / path.relative_to(invocation.home)
            if directory:
                landing.mkdir(exist_ok=True)
            else:
                landing.touch()
        exited = self.execute(Process(arguments=self.command(invocation)))
        if exited.status == 125:
            message = (
                f"podman couldn't run {invocation.container.image.tag} (status 125); "
                "what it said is above"
            )
            raise ContainerError(message)
        return exited.status

    def unshared(self, *arguments: str) -> None:
        """Run a command in podman's own user and mount namespace, where its rootless containers' mounts come from (`podman unshare`).

        Raise `ContainerError` where it fails.
        """
        ran = self.execute(Process(arguments=[self.program, "unshare", *arguments]))
        if ran.status != 0:
            message = (
                f"`podman unshare {' '.join(arguments)}` failed (status {ran.status}); "
                "what it said is above"
            )
            raise ContainerError(message)

    def shared(self, directory: Path) -> None:
        """Make `directory` a shared mount in podman's namespace, before a container mounts it, so what's mounted under it later reaches that container (`Mount.receives`)."""
        self.unshared("mount", "--bind", str(directory), str(directory))
        self.unshared("mount", "--make-shared", str(directory))

    def private(self, directory: Path) -> None:
        """Make `directory` a private mount in podman's namespace, where nothing mounted under it reaches anywhere: `lend`'s stage."""
        self.unshared("mount", "--bind", str(directory), str(directory))
        self.unshared("mount", "--make-private", str(directory))

    def lend(self, source: Path, at: Path, stage: Path, *, read_only: bool) -> None:
        """Mount the host's `source` at `at`, a directory under one made shared (`shared`), so it reaches the containers mounting that one, while they run.

        A read-only one is mounted first in `stage`, a private directory
        (`private`), made read-only there, and only then mounted at `at`: a
        mount made read-only after it reached a container stays writable there
        (measured, `docs/field-notes.md`, *Lending to a running room*). Both
        directories exist; `at` is empty.
        """
        if not read_only:
            self.unshared("mount", "--bind", str(source), str(at))
            return
        staged = stage / at.name
        staged.mkdir(exist_ok=True)
        self.unshared("mount", "--bind", str(source), str(staged))
        self.unshared("mount", "-o", "remount,bind,ro", str(staged))
        self.unshared("mount", "--bind", str(staged), str(at))
        self.unshared("umount", str(staged))
        staged.rmdir()

    def released(self, directory: Path) -> None:
        """Unmount `directory` in podman's namespace, with everything mounted under it."""
        self.unshared("umount", "--recursive", str(directory))

    def exists(self, container: str) -> bool:
        """Say whether a container named `container` is there, running or stopped.

        A run's container is removed when it exits, so one that's there runs, is
        just ending, or never started (`state` tells them apart).
        """
        asked = self.execute(
            Process(arguments=[self.program, "container", "exists", container])
        )
        match asked.status:
            case 0:
                return True
            case 1:
                return False
            case status:
                message = (
                    f"podman couldn't say whether the container {container} exists "
                    f"(status {status})"
                )
                raise ContainerError(message)

    def state(self, container: str) -> str | None:
        """Return the state of the container named `container`, as podman names it (`running`, or one of `Stopped`); none where no container has that name."""
        listed = self.execute(
            Process(
                arguments=[self.program, "ps", "--all", "--format", "json"],
                capture=True,
            )
        )
        if listed.status != 0:
            message = (
                f"podman couldn't say how the container {container} is "
                f"(status {listed.status})"
            )
            raise ContainerError(message)
        held = TypeAdapter(list[StoredContainer]).validate_json(listed.output)
        return next((each.state for each in held if container in each.names), None)

    def discard(self, container: str) -> None:
        """Remove the container named `container`, one that isn't running (`Stopped`)."""
        removed = self.execute(
            Process(arguments=[self.program, "rm", container], capture=True)
        )
        if removed.status != 0:
            said = removed.said()
            told = f": {said}" if said else ""
            message = (
                f"podman couldn't remove the container {container} "
                f"(status {removed.status}){told}"
            )
            raise ContainerError(message)

    def rename(self, container: str, name: str) -> None:
        """Rename the container named `container` to `name`, while it runs as well.

        Raise `ContainerError` where podman can't, as where no container is
        named `container`, or another is named `name`.
        """
        renamed = self.execute(
            Process(arguments=[self.program, "rename", container, name])
        )
        if renamed.status != 0:
            message = (
                f"podman couldn't rename the container {container} to {name} "
                f"(status {renamed.status})"
            )
            raise ContainerError(message)

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
            said = listed.said()
            told = f": {said}" if said else ""
            message = (
                f"podman couldn't list {project}'s images (status {listed.status})"
                f"{told}"
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
