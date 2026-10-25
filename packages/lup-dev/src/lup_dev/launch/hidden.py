"""Paths hidden from a room: each, inside every worktree of the repository, mounted over by something empty and read-only of the launch's own, so the room neither reads nor writes what's there.

`docs/launch.md`, *The project's environment, the room's own*. The host's
environment, `.venv` under `Uv()`, is the first: the operator's own `uv run`
runs it, so what a room wrote there would run on the host. Each path that's a
directory or a file as the room starts is mounted over, read-only, at its host
path, by the launch's empty directory or empty file (`LaunchLayout`), as the git
directory's `config` and `hooks/` are, over the tree's own mount. A link isn't:
podman would follow it to place the mount. In the room, a hidden directory lists
nothing, writing into it fails ("Read-only file system"), and removing or
moving it fails ("Device or resource busy"), so a worktree holding one can't be
removed there either (`docs/field-notes.md`, *Paths hidden from a room*).

What's hidden is told apart by its identity at the start, its device and inode,
so a path found later with another (one the room made after moving a worktree
aside, since the mount moves with the directory holding it) is one the room may
have made (`Hidden.appeared`). Everything the host reads or removes of the tree
is walked from the tree's root a directory at a time, never following a link
(`removed`), since the room writes the tree and could swap a link in to aim the
host elsewhere.
"""

import os
import shutil
import stat
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

from lup.rooms.container import Mount
from lup.types import Model

if TYPE_CHECKING:
    from lup_dev.layout import LaunchLayout


class Found(Model):
    """A path hidden from the room as it started, and what it was then."""

    path: Path
    """Where it is, absolute."""
    directory: bool
    """A directory, rather than a file."""
    device: int
    inode: int


class Hidden(Model):
    """The paths a launch hides from its room, inside each worktree, and what each was as the room started."""

    tree: Path
    """The nearest directory holding the repository's git directory and every
    worktree, which the room mounts whole: nothing outside it is hidden, read
    or removed."""
    paths: list[Path]
    """Each path hidden, relative to a worktree's root."""
    worktrees: list[Path] = []
    """The root of each worktree inside the tree as the room started."""
    found: list[Found] = []
    """Each one there as the room started, in some worktree."""

    @classmethod
    def of(cls, tree: Path, worktrees: list[Path], paths: list[Path]) -> Hidden:
        """Find each of `paths` in each of the repository's `worktrees`, inside `tree`, as the room is about to start."""
        inside = [root for root in worktrees if root.is_relative_to(tree)]
        found = [
            Found(
                path=root / path,
                directory=stat.S_ISDIR(seen.st_mode),
                device=seen.st_dev,
                inode=seen.st_ino,
            )
            for root in inside
            for path in paths
            if (seen := status(tree, root / path)) is not None
            and (stat.S_ISDIR(seen.st_mode) or stat.S_ISREG(seen.st_mode))
        ]
        return cls(tree=tree, paths=paths, worktrees=inside, found=found)

    def mounts(self, launch: LaunchLayout) -> list[Mount]:
        """Mount the launch's empty directory, or its empty file, read-only over each path found."""
        return [
            Mount(
                source=launch.empty_directory if each.directory else launch.empty_file,
                target=each.path,
                read_only=True,
            )
            for each in self.found
        ]

    def write(self, launch: LaunchLayout) -> None:
        """Make the launch's empty directory and empty file, which the mounts need as their sources."""
        launch.empty_directory.mkdir(parents=True, exist_ok=True)
        launch.empty_file.touch()

    def appeared(self, worktrees: list[Path]) -> list[Path]:
        """Return each of the paths, in each worktree there as the room started and each of `worktrees` inside the tree, that wasn't there as the room started: none found then, or another in its place."""

        def known(seen: os.stat_result) -> bool:
            return any(
                each.device == seen.st_dev and each.inode == seen.st_ino
                for each in self.found
            )

        return [
            root / path
            for root in dict.fromkeys([*self.worktrees, *worktrees])
            if root.is_relative_to(self.tree)
            for path in self.paths
            if (seen := status(self.tree, root / path)) is not None and not known(seen)
        ]


def walked(tree: Path, path: Path, stack: ExitStack) -> int | None:
    """Open the directory holding `path`, inside `tree`, walking from `tree` a directory at a time without following a link, and return its descriptor, closed with `stack`; none where a directory on the way isn't one, or is gone."""
    if path == tree or not path.is_relative_to(tree):
        return None
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        current = os.open(tree, flags)
    except OSError:
        return None
    stack.callback(os.close, current)
    for part in path.relative_to(tree).parent.parts:
        try:
            current = os.open(part, flags, dir_fd=current)
        except OSError:
            return None
        stack.callback(os.close, current)
    return current


def entry(holding: int, name: str) -> os.stat_result | None:
    """Return what's at `name` in the directory whose descriptor is `holding`, not following a link there; none where nothing is."""
    try:
        # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link the room swaps in on the way from aiming the host elsewhere")
        return os.stat(name, dir_fd=holding, follow_symlinks=False)
    except FileNotFoundError:
        return None


def status(tree: Path, path: Path) -> os.stat_result | None:
    """Return what's at `path`, inside `tree`, without following a link there or on the way; none where nothing is."""
    with ExitStack() as stack:
        holding = walked(tree, path, stack)
        return None if holding is None else entry(holding, path.name)


def removed(tree: Path, path: Path) -> bool:
    """Remove what's at `path`, inside `tree`, never following a link: a directory with everything in it, else the file or the link itself; say whether anything was there.

    Walked from `tree` a directory at a time (`walked`), and removed through
    the descriptor of the directory holding it, so a link swapped in on the way
    can't aim the removal elsewhere: `shutil.rmtree` given that descriptor
    removes nothing beyond a link inside either.
    """
    with ExitStack() as stack:
        holding = walked(tree, path, stack)
        seen = None if holding is None else entry(holding, path.name)
        if holding is None or seen is None:
            return False
        if stat.S_ISDIR(seen.st_mode):
            shutil.rmtree(path.name, dir_fd=holding)
        else:
            # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link the room swaps in on the way from aiming the host elsewhere")
            os.unlink(path.name, dir_fd=holding)
        return True
