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
- where the room has `man-db`, it keeps the English man pages, which the base's
  `pacman.conf` extracts from no package. A `NoExtract` line appended to it
  takes them back: the file ends in its `[options]`, and the last pattern a
  path matches decides. The base's own packages are installed already, so
  `--needed` skips them and their man pages would stay missing; `pacman -Qk`
  lists each package whose files are missing, `pacman -Sw` downloads those
  packages and checks their signatures, and `bsdtar` takes only their man pages
  out, about 11 MiB where reinstalling them would add up to 0.4 GB to the layer.
  `mandb` then indexes them, since no pacman hook does, so `apropos` and
  `whatis` find them;
- the locale is generated from the sources the base keeps for English (its
  `pacman.conf` extracts no other), so `LANG=en_US.UTF-8` is a locale in the
  room, beside the base's `C.UTF-8` (checked in a room: `locale -a` lists it);
- the package cache is emptied in the same step, so the layer keeps none.

Where the declaration holds a `PyrightSource`, as lup's own does, a second step
puts pyright's source in the image, for the engine's build in the room
(`lup_dev/pyright_source.py`): cloned at the release the launch's worktree's
`uv.lock` pins, its dependencies installed by pnpm from its lockfile, in a home
of the step's own holding the package age as a room's pnpm settings hold it
(`PnpmManager.aged`), that home and what pnpm downloaded removed in the same
step, and the release marked whole last. A step of its own, after the packages
it runs (git, pnpm), so a change of release builds that layer alone, podman
keeping the one before it. It runs in the image's build, inside its own
container, never on the host, and its files are root's, so the room reads them
and can't write them.

Building goes through the library's engine, podman, which tags the image by its
definition's digest and labels it with its project. Each build is recorded with
its duration and size, one JSON line in lup's state, and after it the project's
older lup images that no container uses are removed (`docs/launch.md`, *The
image*): the first lup left 46 images of about 5 GB behind.
"""

from datetime import datetime, timedelta
from shlex import join, quote
from typing import TYPE_CHECKING

from lup.types import Model
from lup_dev.declaration.package_managers.manager import HomeSettings
from lup_dev.declaration.package_managers.pnpm import PnpmManager
from lup_dev.errors import LupDevError
from lup_dev.layout import PyrightLayout, RoomPaths

if TYPE_CHECKING:
    from pathlib import Path

    from lup.rooms.container import Image
    from lup.rooms.engine import Podman
    from lup_dev.catalog.room import RoomBase
    from lup_dev.clock import Clock
    from lup_dev.declaration.kinds import Package
    from lup_dev.pyright_source import Fetching


class ImageError(LupDevError):
    """A room's image that was built but can't be found among its project's images."""


def definition(
    packages: list[Package], base: RoomBase, pyright: Fetching | None = None
) -> str:
    r"""Return the Containerfile of a room holding `packages`, on `base`, and pyright's source where it's fetched by `pyright`.

    The man pages come with `man-db`, which reads them and builds their index,
    so a room without it doesn't carry them.

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
    names = [each.name for each in packages]
    install = join(["pacman", "-Syu", "--noconfirm", "--needed", "--", *names])
    installing = [install]
    if "man-db" in names:
        manuals = "usr/share/man/man"
        kept = quote(f"NoExtract = !{manuals}*")
        unextracted = quote(f'$2 ~ "^/{manuals}" {{ print $1 }}')
        cached = quote("/var/cache/pacman/pkg/%f")
        extract = f"bsdtar -xf {{}} -C / {quote(f'{manuals}*')}"
        installing = [
            f"echo {kept} >> /etc/pacman.conf",
            install,
            f"missing=$(pacman -Qkq | awk {unextracted} | sort -u)",
            "pacman -Sw --noconfirm -- $missing",
            f"pacman -Sp --print-format {cached} -- $missing | xargs -I {{}} {extract}",
            "mandb --quiet",
        ]
    steps = [
        f"echo {quote(mirror)} > /etc/pacman.d/mirrorlist",
        *installing,
        f"echo {quote(f'{base.locale} {base.charmap}')} > /etc/locale.gen",
        "locale-gen",
        "rm -rf /var/cache/pacman/pkg/*",
    ]
    carried = [] if pyright is None else [fetched(pyright)]
    return "".join([f"FROM {base.image}\n", instruction(steps), *carried])


def instruction(steps: list[str]) -> str:
    """Return one `RUN` instruction running `steps` in turn, each only once the one before succeeded."""
    return "RUN " + " \\\n    && ".join(steps) + "\n"


def fetched(fetching: Fetching, kept: PyrightLayout | None = None) -> str:
    r"""Return the `RUN` instruction putting pyright's source in the image, fetched by `fetching`, where `kept` keeps it: the room's image's place (`RoomPaths.pyright`) unless given.

    pnpm runs in a home of the step's own, its downloads' directory, so
    nothing it writes stays in the image beside the source, and the package age
    is written there as a room's pnpm settings hold it, each line printed apart
    since a Containerfile's instruction can't hold a line's end.

    >>> from datetime import timedelta
    >>> from lup_dev.pyright_source import Fetching
    >>> print(fetched(Fetching(release="1.1.414", age=timedelta(days=3))))
    RUN git clone --quiet --depth 1 --branch 1.1.414 https://github.com/microsoft/pyright /opt/lup/pyright/1.1.414 \
        && cd /opt/lup/pyright/1.1.414 \
        && mkdir -p /opt/lup/pyright/1.1.414.downloads/.config/pnpm \
        && printf '%s\n' '# lup'"'"'s package age, from the declaration'"'"'s `Core.package_age`: a project'"'"'s own `pnpm-workspace.yaml` outranks it.' 'minimumReleaseAge: 4320' > /opt/lup/pyright/1.1.414.downloads/.config/pnpm/config.yaml \
        && HOME=/opt/lup/pyright/1.1.414.downloads env XDG_DATA_HOME=/opt/lup/pyright/1.1.414.downloads/data XDG_CACHE_HOME=/opt/lup/pyright/1.1.414.downloads/cache XDG_STATE_HOME=/opt/lup/pyright/1.1.414.downloads/state pnpm install --frozen-lockfile --filter pyright-internal \
        && rm -rf /opt/lup/pyright/1.1.414.downloads \
        && echo 1.1.414 > /opt/lup/pyright/1.1.414/.lup-installed
    <BLANKLINE>
    """
    place = PyrightLayout(home=RoomPaths().pyright) if kept is None else kept
    release = fetching.release
    source = place.release(release)
    downloads = place.downloads(release)
    home = downloads.home
    aged = None if fetching.age is None else PnpmManager().aged(source, fetching.age)
    settings = (
        [
            f"mkdir -p {quote(str((home / aged.path).parent))}",
            join(["printf", "%s\\n", *aged.text.splitlines()])
            + f" > {quote(str(home / aged.path))}",
        ]
        if isinstance(aged, HomeSettings)
        else []
    )
    return instruction(
        [
            join(fetching.clone(source)),
            f"cd {quote(str(source))}",
            *settings,
            f"HOME={quote(str(home))} {join(fetching.install(downloads))}",
            f"rm -rf {quote(str(home))}",
            f"echo {quote(release)} > {quote(str(place.installed(release)))}",
        ]
    )


class Build(Model):
    """One build of a room's image, as lup's state records it."""

    tag: str
    project: str
    finished: datetime
    duration: timedelta
    """From asking podman whether the image exists to the build's end."""
    size: int
    """The image's size in bytes, as podman lists it after the build."""

    def took(self) -> timedelta:
        """Return how long the build took, to the second, as a launch says it.

        >>> from datetime import UTC
        >>> finished = datetime(2026, 10, 13, tzinfo=UTC)
        >>> made = Build(tag="t", project="p", finished=finished, size=1,
        ...     duration=timedelta(seconds=47.665048))
        >>> str(made.took())
        '0:00:48'
        """
        return timedelta(seconds=round(self.duration.total_seconds()))


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
