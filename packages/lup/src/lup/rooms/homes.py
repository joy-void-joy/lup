"""A directory rooms write, as the host makes and reads what's in it, never following a link a room left there.

A runtime's home of the rooms' own (`lup.sessions.terminal.RuntimeHome`) is
read and written by every room given it, so anything inside it may be a link
a room left to aim the host elsewhere. The host makes only what a mount there
lands on (`landed`), walking from the home a directory at a time and replacing
a link or an entry of the wrong kind in the way, and reads a record there only
where it resolves inside the home (`inside`).

A landing is made by the host, the operator's: podman would make a missing
one itself, owned by a subordinate uid only `podman unshare` removes
(`docs/field-notes.md`, *The room's home on disk*). A room swapping a landing
for a link once it's made moves the mount within its container, where podman
places it, never onto the host.
"""

import os
import shutil
import stat
from contextlib import ExitStack
from typing import TYPE_CHECKING

from lup.rooms.container import Mask, Mount

if TYPE_CHECKING:
    from pathlib import Path


def landings(home: Path, mounts: list[Mount | Mask]) -> dict[Path, bool]:
    """Return each path inside `home` a mount lands on, and each directory on the way there, with whether it's a directory.

    A mount's own path is a directory where its source is one, else a file,
    and a mask's is a directory. One inside another mount inside the home
    lands on that mount's paths, and nothing is made for it.

    >>> from pathlib import Path
    >>> sorted(landings(Path("/h"), [Mount(source=Path("/h")), Mask(target=Path("/h/a/b"))]).items())
    [(PosixPath('/h/a'), True), (PosixPath('/h/a/b'), True)]
    """
    places = {
        (each.destination if isinstance(each, Mount) else each.target): (
            each.source.is_dir() if isinstance(each, Mount) else True
        )
        for each in mounts
    }
    within = [
        target for target in places if target != home and target.is_relative_to(home)
    ]
    landing = {
        target: places[target]
        for target in within
        if not any(target != each and target.is_relative_to(each) for each in within)
    }
    on_the_way = {
        parent: True
        for target in landing
        for parent in target.parents
        if parent != home and parent.is_relative_to(home)
    }
    return dict(sorted({**on_the_way, **landing}.items()))


def entered(path: Path | str, holding: int | None = None) -> int:
    """Open the directory at `path`, in the one whose descriptor is `holding` where it's given, as itself, never through a link, and return its descriptor."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    return os.open(path, flags, dir_fd=holding)


def cleared(holding: int, name: str, *, directory: bool) -> None:
    """Remove what's at `name` in the directory whose descriptor is `holding`, where it isn't what's wanted there: a link, or an entry of the other kind; nothing where it is, or where nothing is."""
    try:
        # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
        seen = os.stat(name, dir_fd=holding, follow_symlinks=False)
    except FileNotFoundError:
        return
    if directory and stat.S_ISDIR(seen.st_mode):
        return
    if not directory and stat.S_ISREG(seen.st_mode):
        return
    if stat.S_ISDIR(seen.st_mode):
        shutil.rmtree(name, dir_fd=holding)
    else:
        # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
        os.unlink(name, dir_fd=holding)


def made(holding: int, name: str, *, directory: bool) -> None:
    """Make a directory or an empty file at `name` in the directory whose descriptor is `holding`, where it isn't there as wanted: what's there of another kind, or a link, removed first."""
    cleared(holding, name, directory=directory)
    if directory:
        try:
            # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
            os.mkdir(name, 0o700, dir_fd=holding)
        except FileExistsError:
            return
        return
    # Never waiting on a pipe a room swapped in meanwhile: opening one fails.
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    os.close(os.open(name, flags, 0o600, dir_fd=holding))


def landed(home: Path, wanted: dict[Path, bool]) -> None:
    """Make each of `wanted` inside `home`, a directory or an empty file by what it says, the operator's, as a mount there needs before the run.

    Each is reached from `home` a directory at a time, never through a link:
    a link, or an entry of the other kind, where one is wanted is removed
    first, and so is what's in it. Raise `NotADirectoryError` where `home`
    itself isn't a directory, a link among it.
    """
    with ExitStack() as stack:
        root = entered(home)
        stack.callback(os.close, root)
        for path, directory in sorted(wanted.items()):
            *parents, name = path.relative_to(home).parts
            with ExitStack() as walk:
                current = root
                for part in parents:
                    made(current, part, directory=True)
                    current = entered(part, current)
                    walk.callback(os.close, current)
                made(current, name, directory=directory)


def regular(
    path: Path | str, holding: int | None = None, *, follow: bool = False
) -> int | None:
    """Open the file at `path`, in the directory whose descriptor is `holding` where it's given, for reading where it's a regular file, and return its descriptor; none where it isn't one, or isn't there: the one way the host opens a file a room may have written.

    Never waiting on a pipe a room left in its place: opening one doesn't
    block, and it's closed as what it is. Never through a link at its end,
    which a room could aim at any file the host reads, `/dev/zero` among them,
    unless `follow`, for a caller that checks where the file opened is itself,
    as `lup_dev.confined` does.
    """
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC
    if not follow:
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, dir_fd=holding)
    except OSError:
        return None
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        return None
    return descriptor


def inside(home: Path, path: Path) -> bool:
    """Say whether `path` resolves inside `home`, every link on the way followed: what a room left as a link elsewhere doesn't.

    >>> from pathlib import Path
    >>> inside(Path("/h"), Path("/h/a")), inside(Path("/h"), Path("/h/../etc"))
    (True, False)
    """
    return path.resolve().is_relative_to(home.resolve())


def plain(name: str) -> bool:
    """Say whether `name` is a plain name for a record by: letters, digits, `-` and `_`, as each runtime's ids for its sessions and subagents are; never a path or a pattern, which an id a room's hook gave could be.

    >>> plain("8f2c-4b1e_a9"), plain("*"), plain("../x"), plain("")
    (True, False, False, False)
    """
    return bool(name) and all(
        char.isascii() and (char.isalnum() or char in "-_") for char in name
    )
