"""`Containers`: the machine's part holding podman, which starts and stops every container lup runs, each behind the same walls.

Whatever runs podman can mount anything of the operator's, so it's as powerful as
they are: this part runs on their machine, from the home repository's approved
commit, and only the machine's own parts may call it (`Machine`). Every
container it starts is walled the same way, whatever asked for it (`walls`): the
operator's uid inside, so what it writes is theirs; every capability dropped and
no privileges gained; a limit on processes; `--init`, reaping what exits;
removed when it ends; no image fetched by a short name; no log kept of what it
prints. These are the second lup's room's walls, measured with rootless podman
6.1 (`docs/field-notes.md`, *the engine's command lines*).
"""

import csv
import hashlib
import io
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

import lup
from lup.doors.door import RefusedError
from lup.doors.parties import Machine
from lup.doors.parts import Finished, Part, Program
from lup.running.plan import Name
from lup.types import Model


class ContainerError(RefusedError):
    """podman couldn't build, start or stop a container as it was asked: its call is refused, saying why."""


type Pinned = Annotated[str, StringConstraints(pattern=r"@sha256:[0-9a-f]{64}$")]
"""An image named by its digest, so what's fetched under its name can't change:
`docker.io/library/archlinux@sha256:4bf3…`."""


class Image(Model):
    """An image lup builds: a Containerfile's text, from a base image named by its digest, for one project, tagged by its digest, so a changed definition is a new tag."""

    base: Pinned
    """The image it's built from, which its definition names: fetched by its
    digest where it isn't there, so the build itself fetches nothing."""
    definition: str
    """The Containerfile, built with an empty context, so it copies nothing in."""
    project: Name
    """The project it's built for, which its label names."""

    def tag(self) -> str:
        """Return its tag: the digest of its definition and its project.

        >>> pinned = "docker.io/library/archlinux@sha256:" + "4b" * 32
        >>> Image(
        ...     base=pinned,
        ...     definition=f"FROM {pinned}",
        ...     project="harmon",
        ... ).tag().startswith("localhost/lup:")
        True
        """
        digest = hashlib.sha256(self.model_dump_json().encode()).hexdigest()
        return f"localhost/lup:{digest}"


class Bind(Model):
    """A directory or file of the machine's mounted into a container, at its own path unless `target` says, read-only unless it says."""

    source: Path
    target: Path | None = None
    read_only: bool = True

    def destination(self) -> Path:
        """Return where it appears in the container."""
        return self.source if self.target is None else self.target


class Spec(Model):
    """A container to start: its name, its image, what it runs, what's mounted, its variables and its network."""

    name: Name
    """Its name while it runs, one container's at a time."""
    image: Image
    command: list[str]
    workdir: Path
    binds: list[Bind] = []
    hidden: list[Path] = []
    """Paths inside a bind hidden behind an empty directory held in memory."""
    env: dict[str, str] = {}
    network: Literal["host", "private"] = "host"
    """The machine's network, as rooms share it, or one of its own."""
    gpu: bool = False

    def linked(self) -> list[Path]:
        """Return each directory or file it mounts whose path isn't its own: relative, or through a link, which podman would follow to wherever the link points."""
        return [
            each.source for each in self.binds if each.source.resolve() != each.source
        ]


class Run(Model):
    """A container this part started: what was asked, and the command line podman was given."""

    spec: Spec
    command: list[str]


class Walls(Model):
    """The walls every container lup starts stands behind, the same whatever asked for it."""

    pids_limit: int = 16_384
    """How many processes and threads it may hold at once: well above podman's
    default of 2,048, which a gate alone neared, and a limit still, which stops
    a fork bomb taking the machine down."""

    def options(self) -> list[str]:
        """Return podman's options for them.

        >>> "--cap-drop=all" in Walls().options()
        True
        """
        return [
            "--rm",
            "--init",
            "--pull=never",
            "--log-driver=none",
            "--userns=keep-id",
            "--cap-drop=all",
            "--security-opt=no-new-privileges",
            f"--pids-limit={self.pids_limit}",
        ]


def mount_option(fields: list[str]) -> str:
    """Return podman's `--mount` value for these `key=value` fields: one CSV record, so a path holding a comma is quoted rather than split.

    >>> mount_option(["type=bind", "source=/a,b"])
    'type=bind,"source=/a,b"'
    """
    record = io.StringIO()
    csv.writer(record, lineterminator="").writerow(fields)
    return record.getvalue()


def command_of(spec: Spec, walls: Walls, *, detached: bool = True) -> list[str]:
    """Return the arguments that start `spec`'s container behind `walls`: detached, or run to its end, its input given."""
    binds = [
        "--mount="
        + mount_option(
            [
                "type=bind",
                f"source={each.source}",
                f"destination={each.destination()}",
                *(["ro=true"] if each.read_only else []),
            ]
        )
        for each in spec.binds
    ]
    hidden = [
        "--mount=" + mount_option(["type=tmpfs", f"destination={each}", "notmpcopyup"])
        for each in spec.hidden
    ]
    return [
        "run",
        "--detach" if detached else "--interactive",
        *walls.options(),
        f"--name={spec.name}",
        f"--network={spec.network}",
        f"--workdir={spec.workdir}",
        *(["--device=nvidia.com/gpu=all"] if spec.gpu else []),
        *(f"--env={name}={value}" for name, value in spec.env.items()),
        *binds,
        *hidden,
        spec.image.tag(),
        *spec.command,
    ]


class Once(Model):
    """A container run to its end: what it runs, and what's given on its input."""

    spec: Spec
    given: str | None = None


class Named(Model):
    """A container, by its name."""

    name: Name


class Built(Model):
    """Whether an image was built, rather than found already there."""

    built: bool


class Containers(Part, machine=True, shared=True):
    """The machine's part holding podman: it builds images, and starts and stops every container lup runs, each behind the same walls."""

    podman: Program = Program(
        name="podman",
        version=">=5",
        probe=["--version", "--format={{.Client.Version}}"],
        why="starts every container lup runs",
        install="https://podman.io/docs/installation",
    )
    walls: Walls = Field(default_factory=Walls)
    running: list[Run] = []
    """Each container this part started that hasn't stopped, in order."""

    @lup.service
    async def built(self, image: Image, by: Machine) -> Built:
        """Build `image` where its tag isn't there yet, its base fetched by its digest first where it isn't there either, and say whether it was built.

        Raise `ContainerError` where podman can't say, fetch or build.
        """
        del by
        if await self.there(image.tag()):
            return Built(built=False)
        if not await self.there(image.base):
            pulled = await self.podman.ran("pull", "--quiet", image.base)
            if pulled.status != 0:
                message = f"podman couldn't fetch {image.base}: {pulled.said()}"
                raise ContainerError(message)
        made = await self.podman.ran(
            "build",
            "--pull=never",
            "--tag",
            image.tag(),
            "--label",
            f"lup.project={image.project}",
            "--file",
            "-",
            "/var/empty",
            given=image.definition,
        )
        if made.status != 0:
            message = f"podman couldn't build {image.tag()}: {made.said()}"
            raise ContainerError(message)
        return Built(built=True)

    async def there(self, image: str) -> bool:
        """Say whether the image named `image` is there.

        Raise `ContainerError` where podman can't say.
        """
        exists = await self.podman.ran("image", "exists", image)
        match exists.status:
            case 0:
                return True
            case 1:
                return False
            case status:
                message = (
                    f"podman couldn't say whether {image} is there (status {status})"
                )
                raise ContainerError(message)

    def walled(self, spec: Spec) -> None:
        """Refuse a container mounting a path that isn't its own, which podman would follow wherever a link points.

        Raise `ContainerError` where one does.
        """
        linked = spec.linked()
        if linked:
            named = ", ".join(str(each) for each in linked)
            message = (
                f"{spec.name} would mount {named} through a link or by a relative "
                "path: lup mounts a path only as it is, resolved"
            )
            raise ContainerError(message)

    @lup.service
    async def started(self, spec: Spec, by: Machine) -> Run:
        """Start `spec`'s container, detached, behind the walls every container stands behind, and say how.

        Raise `ContainerError` where podman fails to.
        """
        del by
        self.walled(spec)
        command = command_of(spec, self.walls)
        ran = await self.podman.ran(*command)
        if ran.status != 0:
            message = (
                f"podman couldn't start {spec.name} (status {ran.status}): {ran.said()}"
            )
            raise ContainerError(message)
        run = Run(spec=spec, command=command)
        self.running = [*self.running, run]
        return run

    @lup.service
    async def ran(self, once: Once, by: Machine) -> Finished:
        """Run `once`'s container to its end, behind the same walls, what it's given on its input, and say how it ended, as a declaration is planned.

        Raise `ContainerError` where podman itself fails (status 125).
        """
        del by
        self.walled(once.spec)
        command = command_of(once.spec, self.walls, detached=False)
        finished = await self.podman.ran(*command, given=once.given)
        if finished.status == 125:
            message = f"podman couldn't run {once.spec.name}: {finished.said()}"
            raise ContainerError(message)
        return finished

    @lup.service
    async def stopped(self, named: Named, by: Machine) -> None:
        """Stop the container named so, its program asked to end and made to after a while; nothing where none is.

        Raise `ContainerError` where podman fails otherwise.
        """
        del by
        ran = await self.podman.ran("stop", "--ignore", "--time=10", named.name)
        if ran.status != 0:
            message = f"podman couldn't stop {named.name}: {ran.said()}"
            raise ContainerError(message)
        self.running = [each for each in self.running if each.spec.name != named.name]
