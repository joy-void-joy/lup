"""Reading a worktree's file on the host without following a link out of it.

A room writes the worktree, so a link there may point anywhere on the host, and
what the host reads of a file can reach the agent: ruff's findings, the engine's
reading of a file's parse. So the host reads a worktree's file only where it
resolves inside the worktree, its links followed (`docs/judging-writes.md`, *The
engine: one typed tree*), as the engine confines what pyright reads
(`packages/lup-dev/checker/src/confined.ts`).
"""

import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Generator


class Confined(Model):
    r"""A directory whose files the host reads only where they resolve inside it, their links followed: a worktree.

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

    def read(self, path: Path) -> bytes | None:
        """Return the content of the regular file at `path`, from the root, where it resolves inside the root; none where it isn't there, or resolves outside (`opened`)."""
        with self.opened(path) as reading:
            return None if reading is None else reading.read()

    @contextmanager
    def opened(self, path: Path) -> Generator[BinaryIO | None]:
        """Open the regular file at `path`, from the root, for reading as much of it as is wanted, where it resolves inside the root; none where it isn't there, or resolves outside.

        The check is made on the file opened, through `descriptors`, so a link
        swapped between the check and the read can't win. It's opened without
        blocking, and read only where it's a regular file, so a named pipe can't
        hold the host.
        """
        real = self.root.resolve()
        file = self.root / path
        named = self.descriptors.is_dir()
        if not named and not file.resolve().is_relative_to(real):
            yield None
            return
        try:
            descriptor = os.open(file, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError:
            yield None
            return
        try:
            opened = (self.descriptors / str(descriptor)).readlink() if named else real
            if not opened.is_relative_to(real) or not stat.S_ISREG(
                os.fstat(descriptor).st_mode
            ):
                yield None
                return
            with os.fdopen(descriptor, "rb", closefd=False) as reading:
                yield reading
        finally:
            os.close(descriptor)

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
