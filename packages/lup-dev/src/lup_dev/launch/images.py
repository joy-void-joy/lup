"""The room's image: its definition from lup's base and the modules' packages, its build, and what's kept.

The image is lup's base, Arch Linux's own image, with its mirror set to one day of
the Arch Linux Archive, then one `pacman` transaction installing every package
the selected modules name (`docs/launch.md`, *The image*):
- the mirror is the archive's day the base was made from (`RoomBase`), so every
  package is as old as the base's own and the build reproduces;
- `pacman -Syu`, where the note says `-Sy`: with the base and the day pinned
  together the upgrade finds nothing to do (checked), and if they ever part it
  keeps the image whole, where `-Sy` alone would install packages built against
  libraries newer than the base's, Arch's unsupported partial upgrade. `--needed`
  skips the packages the base already holds, and `--` ends pacman's options, so
  no package name is taken for one;
- the locale is generated from the sources the base keeps for English (its
  `pacman.conf` extracts no other), so `LANG=en_US.UTF-8` is a locale in the
  room, beside the base's `C.UTF-8` (checked in a room: `locale -a` lists it);
- the package cache is emptied in the same step, so the layer keeps none.

Building goes through the library's engine, podman, which tags the image by its
definition's digest and labels it with its project. Each build is recorded with
its duration and size, one JSON line in lup's state, and after it the project's
older lup images that no container uses are removed (`docs/launch.md`,
*Footprint*): the first lup left 46 images of about 5 GB behind.
"""

from datetime import datetime, timedelta
from shlex import join, quote
from typing import TYPE_CHECKING

from lup.types import Model
from lup_dev.errors import LupDevError

if TYPE_CHECKING:
    from pathlib import Path

    from lup.rooms.container import Image
    from lup.rooms.engine import Podman
    from lup_dev.catalog.room import RoomBase
    from lup_dev.clock import Clock
    from lup_dev.declaration.kinds import Package


class ImageError(LupDevError):
    """A room's image that was built but can't be found among its project's images."""


def definition(packages: list[Package], base: RoomBase) -> str:
    r"""Return the Containerfile of a room holding `packages`, on `base`.

    >>> from lup_dev.catalog.room import RoomBase
    >>> from lup_dev.declaration.kinds import Package
    >>> print(definition([Package(name="git", why="version control")], RoomBase()))
    FROM docker.io/library/archlinux:base-20260816.0.574111@sha256:4bf33b21a715aac0b48ce6e9eaed4782a898eae96f88f5da3635572129c2584a
    RUN echo 'Server = https://archive.archlinux.org/repos/2026/08/15/$repo/os/$arch' > /etc/pacman.d/mirrorlist \
        && pacman -Syu --noconfirm --needed -- git \
        && echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen \
        && locale-gen \
        && rm -rf /var/cache/pacman/pkg/*
    <BLANKLINE>
    """
    mirror = f"Server = {base.archive}/{base.snapshot:%Y/%m/%d}/$repo/os/$arch"
    install = ["pacman", "-Syu", "--noconfirm", "--needed", "--"]
    steps = [
        f"echo {quote(mirror)} > /etc/pacman.d/mirrorlist",
        join([*install, *(each.name for each in packages)]),
        f"echo {quote(f'{base.locale} {base.charmap}')} > /etc/locale.gen",
        "locale-gen",
        "rm -rf /var/cache/pacman/pkg/*",
    ]
    return f"FROM {base.image}\nRUN " + " \\\n    && ".join(steps) + "\n"


class Build(Model):
    """One build of a room's image, as lup's state records it."""

    tag: str
    project: str
    finished: datetime
    duration: timedelta
    """From asking podman whether the image exists to the build's end."""
    size: int
    """The image's size in bytes, as podman lists it after the build."""


def build(image: Image, podman: Podman, clock: Clock, record: Path) -> Build | None:
    """Build `image` if its tag is missing, record the build, and remove its project's older images.

    Return the build, or none where the image was already built. The record is
    one JSON line appended to `record`, written at once, so two launches
    building together each add a whole line. An older image of the project is
    removed only while no container, running or stopped, uses it; podman
    refuses one that a container started using since, which raises.
    """
    started = clock.now()
    if not podman.ensure(image):
        return None
    finished = clock.now()
    stored = podman.images(image.project)
    built = next((each for each in stored if image.tag in each.names), None)
    if built is None:
        message = (
            f"podman built {image.tag}, but doesn't list it among the images of "
            f"{image.project}"
        )
        raise ImageError(message)
    done = Build(
        tag=image.tag,
        project=image.project,
        finished=finished,
        duration=finished - started,
        size=built.size,
    )
    record.parent.mkdir(parents=True, exist_ok=True)
    with record.open("a") as log:
        log.write(f"{done.model_dump_json()}\n")
    for older in stored:
        if older.id != built.id and older.containers == 0:
            podman.remove(older)
    return done
