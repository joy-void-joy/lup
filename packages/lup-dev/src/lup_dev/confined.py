"""Reading and writing what a room writes, on the host, without following a link out of it.

A room writes the worktree, so a link there may point anywhere on the host, and
what the host reads of a file can reach the agent: ruff's findings, the engine's
reading of a file's parse. So the host reads a worktree's file only where it
resolves inside the worktree, its links followed (`docs/judging-writes.md`, *The
engine: one typed tree*), as the engine confines what pyright reads
(`packages/lup-dev/checker/src/confined.ts`).

What the host writes and removes there, with the operator's permissions, is
reached a directory at a time from the root, each through the descriptor of the
one before and never through a link, so nothing a room swaps in while it happens
aims it elsewhere (`lup.rooms.homes`). A new file is only ever made, so nothing
already at its name is written through.
"""

import errno
import os
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from lup.rooms.homes import cleared, entered, made, opened
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Generator


def gone(holding: int, name: str) -> None:
    """Remove what's at `name` in the directory whose descriptor is `holding`, whatever it is, a link itself and never what it points at; nothing where nothing is."""
    cleared(holding, name, directory=True)
    cleared(holding, name, directory=False)


def made_new(holding: int, name: str, content: bytes, mode: int) -> None:
    """Make the file at `name` in the directory whose descriptor is `holding`, holding `content`, in a mode the process's umask applies to: never over anything there, nor through a link there."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    with os.fdopen(os.open(name, flags, mode, dir_fd=holding), "wb") as writing:
        writing.write(content)


class Confined(Model):
    r"""A directory whose files the host reads only where they resolve inside it, their links followed, and writes and removes only inside it, following none: a worktree.

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as scratch:
    ...     root = Path(scratch) / "worktree"
    ...     root.mkdir()
    ...     _ = (root / "a.py").write_text("x = 1\n")
    ...     _ = (Path(scratch) / "host.py").write_text("secret = 1\n")
    ...     (root / "b.py").symlink_to(Path(scratch) / "host.py")
    ...     Confined(root=root).text(Path("a.py")), Confined(root=root).text(Path("b.py"))
    ('x = 1\n', None)
    """

    root: Path
    descriptors: Path = Path("/proc/self/fd")
    """Where the kernel names the file each of the process's open descriptors
    has open. Where it isn't there, as off Linux, a path is resolved before it's
    opened instead."""
    above: Path | None = None
    """A directory holding the root that a room can't move, as a room's mount
    can't be, the root reached from it without following a link where it's
    inside it: what's between them, a bare repository's `tree/` and each worktree
    there, a room can swap. None has the root opened as it's named."""

    def read(self, path: Path) -> bytes | None:
        """Return the content of the regular file at `path`, from the root, where it resolves inside the root; none where it isn't there, or resolves outside (`opened`)."""
        with self.opened(path) as reading:
            return None if reading is None else reading.read()

    @contextmanager
    def opened(self, path: Path) -> Generator[BinaryIO | None]:
        """Open the regular file at `path`, from the root, for reading as much of it as is wanted, where it resolves inside the root; none where it isn't there, or resolves outside.

        It's opened as the host opens any file a room may have written
        (`lup.rooms.homes.opened`): the check made on the file opened, through
        `descriptors`, so a link swapped between the check and the read can't
        win, without blocking, and only where it's a regular file, so a named
        pipe can't hold the host.
        """
        reading = opened(self.root, self.root / path, self.descriptors)
        if reading is None:
            yield None
            return
        with reading:
            yield reading

    def inside(self, path: Path) -> bool:
        """Say whether `path` names something under the root, by its parts alone.

        >>> worktree = Confined(root=Path("/w"))
        >>> [worktree.inside(Path(p)) for p in ["a/b", "../a", "a/../../b", "/a", "."]]
        [True, False, False, False, False]
        """
        return bool(path.parts) and not (path.is_absolute() or ".." in path.parts)

    def reached(self, stack: ExitStack) -> int:
        """Open the root, closed as `stack` ends, from `above` where it's inside it, and return its descriptor: raise `OSError` where a link or a file is on the way, or it's gone."""
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        inside = self.above is not None and self.root.is_relative_to(self.above)
        start = self.above if self.above is not None and inside else self.root
        current = os.open(start, flags)
        stack.callback(os.close, current)
        for part in self.root.relative_to(start).parts:
            current = entered(part, current)
            stack.callback(os.close, current)
        return current

    def cleared_for(self, path: Path, stack: ExitStack) -> int:
        """Return the descriptor of the directory to hold `path`, closed as `stack` ends: each directory on the way made, a link or a file in the way replaced, and what's at its name removed. Raise `ValueError` where `path` isn't under the root, and `OSError` where the root can't be reached."""
        if not self.inside(path):
            message = f"{path} isn't a path inside {self.root}"
            raise ValueError(message)
        current = self.reached(stack)
        for part in path.parent.parts:
            made(current, part, directory=True)
            current = entered(part, current)
            stack.callback(os.close, current)
        gone(current, path.name)
        return current

    def laid(self, path: Path, content: bytes, *, executable: bool = False) -> None:
        """Put `content` at `path`, from the root, as what's lup's to keep there: what's in its way is replaced (`cleared_for`), never followed, the link and not what it points at."""
        with ExitStack() as stack:
            holding = self.cleared_for(path, stack)
            made_new(holding, path.name, content, 0o777 if executable else 0o666)

    def linked(self, path: Path, target: bytes) -> None:
        """Make `path`, from the root, a link to `target`, as what's lup's to keep there: what's in its way is replaced (`cleared_for`). It's made through the descriptor's name, as pathlib has no call relative to one."""
        with ExitStack() as stack:
            holding = self.cleared_for(path, stack)
            at = self.descriptors / str(holding) / path.name
            at.symlink_to(os.fsdecode(target))

    def written(self, path: Path, content: bytes) -> bool:
        """Write `content` at `path`, from the root, where only directories are on the way, those missing made, and nothing or a regular file is at its name, keeping its mode; say whether it did. A link or a file in the way is left, and nothing is written: what's there isn't lup's to replace."""
        if not self.inside(path):
            return False
        with ExitStack() as stack:
            try:
                current = self.reached(stack)
                for part in path.parent.parts:
                    try:
                        current = entered(part, current)
                    except FileNotFoundError:
                        made(current, part, directory=True)
                        current = entered(part, current)
                    stack.callback(os.close, current)
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
                mode = 0o666
                try:
                    there = os.open(path.name, flags, dir_fd=current)
                except FileNotFoundError:
                    made_new(current, path.name, content, mode)
                    return True
                seen = os.fstat(there)
                os.close(there)
                if not stat.S_ISREG(seen.st_mode):
                    return False
                gone(current, path.name)
                made_new(current, path.name, content, stat.S_IMODE(seen.st_mode))
            except OSError as refused:
                unreachable = [errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.EEXIST]
                if refused.errno in unreachable:
                    return False
                raise
        return True

    def removed(self, path: Path) -> bool:
        """Remove what's at `path`, from the root, a directory with everything in it, and a link itself, never what it points at; say whether `path` is gone: not where a link or a file is on the way, through which nothing is removed."""
        if not self.inside(path):
            return False
        with ExitStack() as stack:
            try:
                current = self.reached(stack)
                for part in path.parent.parts:
                    current = entered(part, current)
                    stack.callback(os.close, current)
            except FileNotFoundError:
                return True
            except OSError as refused:
                if refused.errno in [errno.ENOTDIR, errno.ELOOP]:
                    return False
                raise
            gone(current, path.name)
        return True

    def text(self, path: Path) -> str | None:
        """Return the file at `path`, as `read` reads it, as text; a byte that isn't UTF-8 is replaced."""
        content = self.read(path)
        return None if content is None else content.decode(errors="replace")

    def outside(self, path: Path) -> bool:
        r"""Say whether `path`, from the root, resolves outside the root, its links followed: a file the host doesn't read, there or not.

        A path that isn't there resolves as its nearest parent that is, so a new
        file is inside; a link looping is outside, since nothing reads it.

        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as scratch:
        ...     root = Path(scratch) / "worktree"
        ...     root.mkdir()
        ...     (root / "out.py").symlink_to(Path(scratch) / "missing.py")
        ...     (root / "in.py").symlink_to(root / "new.py")
        ...     worktree = Confined(root=root)
        ...     [worktree.outside(Path(each)) for each in ["out.py", "in.py", "new.py"]]
        [True, False, False]
        """
        try:
            return not (self.root / path).resolve().is_relative_to(self.root.resolve())
        except OSError, RuntimeError:
            return True
