"""Each repository's approved copies of `lup-dev`: each installed in a directory of its own, the one that judges named by a link switched in one rename.

Trust on launch installs the copy the operator approves into a directory no
process runs (`Copies.installing`), and once the install has finished points
the repository's link at it in one rename (`Copies.switch`): the repository's
command, found through the link, is always a whole copy, never one an install
is still writing. The host service starts each repository's process from the
copy the link names as it asks, and a process keeps the copy it started from
(`host/workers.py`); a copy the link doesn't name, which no process runs and
which isn't kept, is removed by the service's sweep (`removable`).

On lup's own repository the copy is what the host service and the person's
`lup-dev` run too, and the copies are kept by their commit (`Kept`,
`Copies.keeping`): the last few that ran, and every commit pinned, as a branch
on trial is (`Copies.pin`). `docs/trust.md`, *The way back*. Going back to one
is a link moved, with nothing built; a release can be fetched again from its
index, so a project's aren't kept. Installing a copy and switching to it are
two steps (`lup_dev/switching.py`), so a copy can be built ahead of its first run.

**The person's `lup-dev` is a launcher, not a copy** (`launcher`): a few lines of
shell that hand every command to the copy the link names and `restore` to the
one that answered before it where that can run it, so `lup-dev restore` works
whatever is wrong with either alone, an import that fails among it, which nothing
written in Python could survive by being a command of that copy.

An install holds the repository's lock from the moment its copy's directory is
made until the link names it, and choosing the copies to remove takes the same
lock, so a copy being installed is never chosen.
"""

import json
import secrets
import shlex
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from filelock import FileLock, Timeout
from pydantic import ValidationError

from lup.types import Model
from lup_dev.approval import Approval
from lup_dev.layout import CopyLayout, JudgeLayout

if TYPE_CHECKING:
    from collections.abc import Generator


class Kept(Model):
    """A copy by its commit: what was approved with it, so going back to it brings back what the operator approved, the person's own layer and their profiles among it."""

    name: str
    """Its directory, under the repository's copies."""
    repository: Path
    """The repository's git directory."""
    approval: Approval
    subject: str = ""
    """The first line of the commit approved, to tell the copies apart by."""
    answered: datetime | None = None
    """When it last answered as the host service and the dashboard
    (`lup_dev/switching.py`); none for one that never has, which is tried on a
    copy of the operator's state before it's run on the real one."""

    @property
    def commit(self) -> str:
        """The commit it's the copy of."""
        return self.approval.commit


def linked(link: Path, target: Path) -> None:
    """Point `link` at `target` in one rename, so what's found through it is what it named, or `target`."""
    made = link.with_name(f"{link.name}.{secrets.token_hex(4)}")
    made.symlink_to(target)
    made.replace(link)


def launcher(home: Path, name: str) -> str:
    r"""Return the person's command for the repository whose copies are at `home`: `restore` handed to the copy that answered before the one that judges, where that can run it, every other command to the one that judges.

    Standard shell alone, so nothing about any copy or any Python stops it
    choosing. Asking for `restore`'s help imports what running it would, so a copy
    that can't is passed over, and one that isn't there, as before any answered.

    >>> print(launcher(Path("/data/judges/abc"), "lup-dev"))
    #!/bin/sh
    # `lup-dev`, as lup writes it (docs/trust.md, The way back): every command runs
    # the copy that judges, and `restore` the one that answered before it where that
    # can, so it works whatever is wrong with the copy that judges.
    home=/data/judges/abc
    if [ "${1-}" = restore ] && "$home/back/lup-dev" restore --help >/dev/null 2>&1; then
        exec "$home/back/lup-dev" "$@"
    fi
    exec "$home/bin/lup-dev" "$@"
    <BLANKLINE>
    """
    return (
        "#!/bin/sh\n"
        f"# `{name}`, as lup writes it (docs/trust.md, The way back): every command runs\n"
        "# the copy that judges, and `restore` the one that answered before it where that\n"
        "# can, so it works whatever is wrong with the copy that judges.\n"
        f"home={shlex.quote(str(home))}\n"
        f'if [ "${{1-}}" = restore ] && "$home/back/{name}" restore --help >/dev/null 2>&1; then\n'
        f'    exec "$home/back/{name}" "$@"\n'
        "fi\n"
        f'exec "$home/bin/{name}" "$@"\n'
    )


class Copies(Model):
    """One repository's approved copies, and the link naming the one that judges."""

    layout: JudgeLayout
    keeping: int = 5
    """How many of the copies that answered are kept, the last run: what each
    costs is in `docs/field-notes.md`, *What a kept copy costs*."""

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
        target = copy.bin.relative_to(self.layout.home)
        if self.layout.bin.is_dir() and not self.layout.bin.is_symlink():
            shutil.rmtree(self.layout.bin)
        linked(self.layout.bin, target)

    def back(self, copy: CopyLayout) -> None:
        """Have `lup-dev restore` run from `copy`, in one rename."""
        linked(self.layout.back, copy.bin.relative_to(self.layout.home))

    def commands(self, directory: Path, name: str, host: Path) -> None:
        """Make the person's command `name` in `directory` the launcher of this repository's copies, in one rename, and `host` a link to them; each only where it's otherwise.

        What's there is replaced, uv's own link to the copy it installed at the
        first switch, and nothing touches it again as copies switch.
        """
        directory.mkdir(parents=True, exist_ok=True)
        command = directory / name
        written = launcher(self.layout.home, name)
        if (
            command.is_symlink()
            or not command.is_file()
            or command.read_text() != written
        ):
            made = command.with_name(f"{name}.{secrets.token_hex(4)}")
            made.write_text(written)
            made.chmod(0o755)
            made.replace(command)
        if not host.is_symlink() or host.readlink() != self.layout.home:
            linked(host, self.layout.home)

    def current(self) -> Path | None:
        """Return the directory of the copy the link names, its links followed; none where it names none."""
        if not self.layout.bin.is_symlink():
            return None
        return self.layout.bin.resolve().parent

    def recorded(self, kept: Kept) -> None:
        """Keep how `kept` stands, a line of the repository's history."""
        self.layout.home.mkdir(parents=True, exist_ok=True)
        with self.layout.history.open("a") as appended:
            appended.write(f"{kept.model_dump_json()}\n")

    def history(self) -> list[Kept]:
        """Return each commit's copy recorded, as its last line says it stands, the last to answer first, those that never have after, a copy gone among them.

        A line that doesn't read, as one a later lup wrote otherwise might, is
        passed over: going back reads this from an older copy than wrote it, so
        it must never stop at what it can't read.
        """
        if not self.layout.history.is_file():
            return []

        def read(line: str) -> Kept | None:
            try:
                return Kept.model_validate_json(line)
            except ValidationError:
                return None

        lines = self.layout.history.read_text().splitlines()
        records = [each for each in map(read, lines) if each is not None]
        stands = {each.commit: each for each in records}

        def when(each: Kept) -> datetime:
            return each.answered or each.approval.time

        ran = [each for each in stands.values() if each.answered is not None]
        never = [each for each in stands.values() if each.answered is None]
        return [
            *sorted(ran, key=when, reverse=True),
            *sorted(never, key=when, reverse=True),
        ]

    def place(self, kept: Kept) -> CopyLayout:
        """Say where `kept` is installed."""
        return self.layout.named(kept.name)

    def there(self, kept: Kept) -> bool:
        """Say whether `kept`'s copy is still installed."""
        return self.place(kept).home.is_dir()

    def pin(self, commits: list[str]) -> None:
        """Keep the copies of exactly `commits`, whatever runs after, on top of the last few that ran: what's on trial says which."""
        self.layout.home.mkdir(parents=True, exist_ok=True)
        partial = self.layout.pins.with_name(f"{self.layout.pins.name}.partial")
        partial.write_text(json.dumps(commits))
        partial.replace(self.layout.pins)

    def pinned(self) -> list[str]:
        """Return the commits pinned; none where none are, or their file doesn't read."""
        if not self.layout.pins.is_file():
            return []
        try:
            read = json.loads(self.layout.pins.read_text())
        except ValueError:
            return []
        return [each for each in read if isinstance(each, str)]

    def kept(self) -> list[Kept]:
        """Return the copies kept and still installed, as `history` orders them: the last `keeping` that answered, and every commit pinned."""
        history = self.history()
        ran = [each for each in history if each.answered is not None]
        last = ran[: self.keeping]
        pinned = self.pinned()
        return [
            each
            for each in history
            if (each in last or each.commit in pinned) and self.there(each)
        ]

    def running(self) -> Kept | None:
        """Return the record of the copy the link names; none where it names none, or one from before copies were kept."""
        current = self.current()
        if current is None:
            return None
        recorded = [each for each in self.history() if each.name == current.name]
        return recorded[0] if recorded else None

    def of(self, commit: str) -> Kept | None:
        """Return the record of the commit `commit`, whole; none where it has none."""
        return next((each for each in self.history() if each.commit == commit), None)

    def holding(self) -> list[Path]:
        """List the directories of the copies never to remove while nothing runs them: those kept, and the one `lup-dev restore` runs from."""
        kept = [self.place(each).home.resolve() for each in self.kept()]
        back = (
            [self.layout.back.resolve().parent] if self.layout.back.is_symlink() else []
        )
        return [*kept, *back]

    def unused(self, running: list[Path]) -> list[Path]:
        """List the directories of the copies to remove: each the link doesn't name, which isn't kept, and which no command in `running`, its links followed, is of.

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
            holding = self.holding()
            return [
                each
                for each in [*(copy.resolve() for copy in copies), *in_place]
                if each != current
                and each not in holding
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
