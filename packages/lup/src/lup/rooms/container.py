"""What a room's wall is made of: its image, what's mounted, its variables, its network.

A room runs its agent in a container (`DESIGN.md`, *Rooms*). Everything is mounted
at its host path unless a mount names a target: a linked worktree's `.git` file and
an environment's links hold absolute paths, and the runtimes key their history on
the working directory's path (`docs/launch.md`, *The mounts*).
"""

import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator

from lup.types import Model

REPOSITORY = "localhost/lup-room"
"""Where every image lup builds is tagged, each under the digest of what it's built from."""


def absolute(path: Path) -> Path:
    """Return `path`, refusing one that isn't absolute, since a container places a mount by its absolute path."""
    if not path.is_absolute():
        message = f"`{path}` isn't an absolute path"
        raise ValueError(message)
    return path


type AbsolutePath = Annotated[Path, AfterValidator(absolute)]
"""A path a container can place: absolute, on the host or in the room."""


class Image(Model):
    """A room's image: a Containerfile's text, built for one project, tagged by its digest."""

    definition: str
    """The Containerfile, as text. It's built with an empty context, so it copies nothing in."""
    project: str
    """The project the image is built for, which its label names, so the project's
    older images can be found and removed."""

    @property
    def tag(self) -> str:
        """Return the image's tag: the digest of its definition and its project.

        A changed definition is a different tag, so a build is needed exactly when
        the tag is missing.
        """
        digest = hashlib.sha256(self.model_dump_json().encode()).hexdigest()
        return f"{REPOSITORY}:{digest}"


class Mount(Model):
    """A host path mounted into the room, at its own path unless `target` says otherwise.

    >>> Mount(source=Path("/srv/repository")).destination
    PosixPath('/srv/repository')
    """

    source: AbsolutePath
    target: AbsolutePath | None = None
    """Where it appears in the room; none for the source's own path."""
    read_only: bool = False

    @property
    def destination(self) -> Path:
        """Return where the mount appears in the room."""
        return self.source if self.target is None else self.target


class Mask(Model):
    """An empty tmpfs over a path in the room, hiding what a mount would show there.

    It's mounted without copying up what it hides (`notmpcopyup`): otherwise podman
    copies the hidden files into the tmpfs, and nothing is hidden.
    """

    target: AbsolutePath


class Container(Model):
    """A room's wall: the image it runs, what's mounted, its variables and its network."""

    image: Image
    mounts: list[Mount | Mask] = []
    """Mounted in order of their paths, so a mask or a mount inside another mount lands on top of it."""
    env: dict[str, str] = {}
    """The variables set in the room, beside `HOME`, which the run sets."""
    network: Literal["host", "own"] = "own"
    """The host's network, sharing its localhost both ways, or the room's own."""
    name: str | None = None
    """The container's name while it runs, which podman gives one container at a
    time, so whoever started it can ask whether it's still there; none lets podman
    pick one."""
