"""pyright's source, which lup's engine is built from: the release a lock pins, where it's kept, and how it's fetched.

The engine is built against pyright's own source (`packages/lup-dev/checker/build.py`),
at the release the worktree's `uv.lock` pins, so it answers as the gate's pyright
does. Three places keep it, a directory per release (`PyrightLayout`), each read
only where it's kept:
- **the host's cache** (`Layout.pyright_source`), which the host's builds fetch
  into and read: trust on launch building the copy the operator approves, and
  the operator's own. No room mounts it, so nothing a room writes is bundled
  into the host's engine;
- **the room's image** (`RoomPaths.pyright`), where the declaration holds a
  `PyrightSource`, as lup's own does: cloned and installed in the image's build,
  inside the build's own container, at the release the launch's worktree's lock
  pins (`launch/images.py`). Its files are root's, so the room reads them and
  can't write them; a branch changing the release gets an image of its own at
  its launch, since the image's definition changes with it;
- **the project's rooms' own directory** (`RoomsLayout.pyright`), where the
  engine's build in a room fetches a release its image doesn't carry: a
  worktree pinning another release than the launch's, or a merge bringing one.
  Once for the project's rooms, which share it; never read on the host.

Which of them a build reads is the room's variables' (`Sources.of`): a room whose
image carries the source names its project's rooms' directory, and the host
names none, so the host's build reads its own cache alone.

A fetch is one recipe everywhere (`Fetching`): a shallow clone of the release's
tag, then pyright's dependencies installed by pnpm from its lockfile as it
stands (`PnpmManager.install`), pnpm switching to the release pyright's manifest
names; what it downloads is kept beside the source and removed once it's
installed. pnpm holds the install to the package age its user-level settings
keep (`PnpmManager.aged`), which pnpm 11 checks a frozen lockfile's entries
against too: in a room, the settings the launch mounts, as for every package
manager its image holds; in the image's build, the same settings, written into
the home the fetch makes there; on the host, the operator's own
(`docs/field-notes.md`, *pyright's source in the room's image*).
"""

import tomllib
from datetime import timedelta
from typing import TYPE_CHECKING

from packaging.version import InvalidVersion, Version

from lup.types import Model
from lup_dev.declaration.package_managers.pnpm import PnpmManager
from lup_dev.errors import LupDevError
from lup_dev.layout import PyrightLayout, RoomPaths

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dev.layout import Layout, PyrightDownloads
    from lup_dev.settings import LupDevSettings


class PyrightSourceError(LupDevError):
    """A lock pinning no one plain release of pyright, whose source can't be fetched."""


class Locked(Model):
    """One package `uv.lock` pins."""

    name: str
    version: str | None = None


class Lock(Model):
    """The part of `uv.lock` read: its packages."""

    package: list[Locked] = []


def pinned(lock: Path) -> str:
    """Return the pyright release `lock`, a `uv.lock`, pins, which the gate runs.

    It names the tag cloned and the directory kept, and joins a room's image's
    definition, so it's taken only as a version written plainly, which neither
    a shell nor git reads as anything else. Raise `PyrightSourceError` where the
    lock is missing, pins pyright other than once, or pins what isn't a plain
    version.
    """
    try:
        text = lock.read_text()
    except FileNotFoundError as missing:
        message = f"there's no `{lock.name}` at {lock.parent}, to pin pyright's release"
        raise PyrightSourceError(message) from missing
    packages = Lock.model_validate(tomllib.loads(text)).package
    releases = [each.version for each in packages if each.name == "pyright"]
    if len(releases) != 1 or releases[0] is None:
        message = f"`{lock}` pins pyright {len(releases)} times, not once"
        raise PyrightSourceError(message)
    release = releases[0]
    try:
        plain = str(Version(release)) == release
    except InvalidVersion:
        plain = False
    if not plain:
        message = f"`{lock}` pins pyright at {release!r}, which isn't a plain version"
        raise PyrightSourceError(message)
    return release


class Fetching(Model):
    """How pyright's source is fetched at one release, wherever it's kept: the clone, then the install.

    >>> from pathlib import Path
    >>> fetching = Fetching(release="1.1.414")
    >>> fetching.clone(Path("/opt/lup/pyright/1.1.414"))[-3:]
    ['1.1.414', 'https://github.com/microsoft/pyright', '/opt/lup/pyright/1.1.414']
    >>> from lup_dev.layout import PyrightDownloads
    >>> fetching.install(PyrightDownloads(home=Path("/d")))[-5:]
    ['pnpm', 'install', '--frozen-lockfile', '--filter', 'pyright-internal']
    """

    release: str
    age: timedelta | None = None
    """The package age written into the home the fetch makes, where it runs
    with none of its own: the image's build. None where pnpm reads its user's
    own settings, a room's or the host's."""
    repository: str = "https://github.com/microsoft/pyright"
    """Where it's cloned from, at the release's tag."""

    def clone(self, target: Path) -> list[str]:
        """Return the command cloning the release's tag into `target`, its history left behind."""
        return [
            "git",
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--branch",
            self.release,
            self.repository,
            str(target),
        ]

    def install(self, downloads: PyrightDownloads) -> list[str]:
        """Return the command installing pyright's dependencies, run in its source: only what `pyright-internal`, the part the engine builds against, needs, with what pnpm downloads kept in `downloads`."""
        return [
            "env",
            f"XDG_DATA_HOME={downloads.data}",
            f"XDG_CACHE_HOME={downloads.cache}",
            f"XDG_STATE_HOME={downloads.state}",
            *PnpmManager().install("--filter", "pyright-internal"),
        ]


class Sources(Model):
    """Where the engine's build finds pyright's source, and where it fetches a release none of them holds."""

    kept: PyrightLayout | None = None
    """The room's image's, where the build runs in a room whose image carries it."""
    fetched: PyrightLayout
    """Where a release none holds is fetched: the host's cache, or in a room its
    project's rooms' directory."""

    @staticmethod
    def room(fetched: PyrightLayout) -> dict[str, str]:
        """Return the variables of a room whose image carries pyright's source, which `of` reads there: where its project's rooms fetch a release.

        >>> from pathlib import Path
        >>> Sources.room(PyrightLayout(home=Path("/rooms/pyright")))
        {'LUP_ROOM_PYRIGHT': '/rooms/pyright'}
        """
        return {"LUP_ROOM_PYRIGHT": str(fetched.home)}

    @classmethod
    def of(cls, settings: LupDevSettings, layout: Layout) -> Sources:
        """Return the room's places where its variables name its project's rooms' directory (`room`), and the host's cache alone otherwise."""
        if settings.lup_room_pyright is None:
            return cls(fetched=layout.pyright_source)
        return cls(
            kept=PyrightLayout(home=RoomPaths().pyright),
            fetched=PyrightLayout(home=settings.lup_room_pyright),
        )

    def found(self, release: str) -> Path | None:
        """Return the source of `release` where a place holds it whole, the image's first; none where none does."""
        places = [*([] if self.kept is None else [self.kept]), self.fetched]
        return next(
            (
                each.release(release)
                for each in places
                if each.installed(release).is_file()
            ),
            None,
        )

    def why(self, release: str) -> str:
        """Say what a fetch of `release` fetches and where, and in a room why its image's won't do."""
        where = self.fetched.release(release)
        if self.kept is None:
            return f"fetching pyright {release} into {where}"
        home = self.kept.home
        carried = (
            sorted(
                each.name
                for each in home.iterdir()
                if self.kept.installed(each.name).is_file()
            )
            if home.is_dir()
            else []
        )
        image = f"pyright {', '.join(carried)}" if carried else "no release of pyright"
        return (
            f"the room's image carries {image}, and `uv.lock` pins {release}: "
            f"fetching it into the project's rooms' own directory, {where}, once "
            "for all their rooms. A room launched from a worktree pinning it "
            "carries it in its image"
        )
