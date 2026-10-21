"""Each repository's approved copies of `lup-dev`: each installed in a directory of its own, the one that judges named by a link switched in one rename.

Trust on launch installs the copy the operator approves into a directory no
process runs (`Copies.installing`), and once the install has finished points
the repository's link at it in one rename (`Copies.switch`): the repository's
command, found through the link, is always a whole copy, never one an install
is still writing. The host service starts each launch's process from the copy
the link names as it asks, and a process keeps the copy it started from
(`host/workers.py`); a copy the link doesn't name, which no process runs, is
removed by the service's sweep (`removable`).

An install holds the repository's lock from the moment its copy's directory is
made until the link names it, and choosing the copies to remove takes the same
lock, so a copy being installed is never chosen.
"""

import secrets
import shutil
from contextlib import contextmanager
from typing import TYPE_CHECKING

from filelock import FileLock, Timeout

from lup.types import Model
from lup_dev.layout import CopyLayout, JudgeLayout

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


class Copies(Model):
    """One repository's approved copies, and the link naming the one that judges."""

    layout: JudgeLayout

    @contextmanager
    def installing(self) -> Generator[CopyLayout]:
        """Hold the repository's lock while the context is open, giving a directory no process runs for a copy to be installed in, and switched to before the context closes (`switch`)."""
        self.layout.home.mkdir(parents=True, exist_ok=True)
        with FileLock(self.layout.lock):
            yield self.layout.named(secrets.token_hex(8))

    def switch(self, copy: CopyLayout) -> None:
        """Point the link at `copy`'s commands in one rename, so a command found through it is the copy before, or this one whole.

        A copy installed at the repository's home itself has its commands
        where the link goes, a directory a rename can't replace: they're
        removed first, and its environment stays until no process runs it.
        """
        link = self.layout.home / f"{self.layout.bin.name}.{secrets.token_hex(4)}"
        link.symlink_to(copy.bin.relative_to(self.layout.home))
        if self.layout.bin.is_dir() and not self.layout.bin.is_symlink():
            shutil.rmtree(self.layout.bin)
        link.replace(self.layout.bin)

    def current(self) -> Path | None:
        """Return the directory of the copy the link names, its links followed; none where it names none."""
        if not self.layout.bin.is_symlink():
            return None
        return self.layout.bin.resolve().parent

    def unused(self, running: list[Path]) -> list[Path]:
        """List the directories of the copies to remove: each the link doesn't name, which no command in `running`, its links followed, is of.

        None while a copy is being installed, and none while the link names no
        copy, where the one installed at the repository's home judges.
        """
        lock = FileLock(self.layout.lock, timeout=0)
        try:
            lock.acquire()
        except Timeout:
            return []
        try:
            current = self.current()
            if current is None:
                return []
            copies = (
                sorted(self.layout.copies.iterdir())
                if self.layout.copies.is_dir()
                else []
            )
            in_place = (
                [self.layout.in_place.resolve()]
                if self.layout.in_place.is_dir()
                else []
            )
            return [
                each
                for each in [*(copy.resolve() for copy in copies), *in_place]
                if each != current
                and not any(command.is_relative_to(each) for command in running)
            ]
        finally:
            lock.release()


def removable(judges: Path, running: list[Path]) -> list[Path]:
    """List every repository's copies under `judges` to remove (`Copies.unused`), `running` being the commands of the processes that run one."""
    homes = sorted(judges.iterdir()) if judges.is_dir() else []
    return [
        each
        for home in homes
        if home.is_dir()
        for each in Copies(layout=JudgeLayout(home=home)).unused(running)
    ]
