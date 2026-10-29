"""Moving a repository's sessions from the operator's own runtime directories into its rooms' home: `lup-dev account migrate` (`docs/launch.md`, *Moving over*).

Before rooms had homes of their own (#324), each room mounted the operator's
own runtime directory read-write, so every session launched then is recorded
there, where a room on a home of its own doesn't find it to resume. Every record
there was where every room could write, so none can be certified as the host's:
each record of the repository's directories moves, whoever wrote it, into the
home its rooms run on, and the rest stays.

What moves is what the runtime's adapter calls the repository's records
(`Records.kept`), each laid out in the home as in the operator's directory. A
running room of another project could still write there, so each is reached a
directory at a time, by descriptor, from the operator's directory and from the
home, never through a link on the way:
- a file moves as a second name for it in the home, then its first name
  removed, so its content, mode and times are kept and nothing is copied; where
  the home is on another filesystem, or the file isn't the operator's to link,
  as a copy keeping its mode and times, then the original removed;
- a link aimed inside what moves is made again at its place in the home, aimed
  at the same place there, as a runtime links a resumed session's subagents to
  the first session's records; any other is left;
- a directory moves as what's in it does, removed once empty;
- what the home holds already where something would go is left as it is, and
  so is what would go there, and what isn't a file, a directory or a link.

Nothing is removed that isn't moved: a name only once the home holds what it
named, a directory only empty. Each thing left is said, with why. A dry run walks
the same way, changes nothing, and says what would move.

A move marks the runtime's records of the repository moved. Rooms on homes of
their own don't write the operator's directory, so what a host session run in
the repository writes there after is the host's, and a launch, which offers the
move where something would move (`lup_dev.launch.moving`), doesn't offer it
again. The command still moves whatever's there when it's run.
"""

import errno
import os
import shutil
import stat
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from lup.rooms.homes import entered, regular
from lup.types import Model
from lup_dev.errors import LupDevError
from lup_dev.gate import running
from lup_dev.git import Git
from lup_dev.host.homes import kept
from lup_dev.host.protocol import Register
from lup_dev.host.records import Record, Records
from lup_dev.host.written import Checked, Places, counted
from lup_dev.layout import Layout
from lup_dev.stored import read_model

if TYPE_CHECKING:
    from collections.abc import Iterator


class MigrationError(LupDevError):
    """A migration that can't go on: a launch of the repository still runs, or the rooms' home it would move into isn't a directory of its own."""


type Kind = Literal["directory", "file", "link", "other"]
"""What an entry is, as the walk treats it."""


def kind(mode: int) -> Kind:
    """Say what an entry of `mode` is, its links never followed."""
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISLNK(mode):
        return "link"
    return "other"


class Step(Model):
    """One thing of a record's the walk moved, or would: a file and its size, a link, or something left and why."""

    kind: Literal["file", "link", "left"]
    place: PurePosixPath
    """Its path in the operator's directory, as in the home."""
    size: int = 0
    why: str | None = None


class Left(Model):
    """Something of a record's that stays where it is, and why."""

    place: PurePosixPath
    why: str


class Moved(Model):
    """One record's move, or what it would be: how much of it moves, and what's left."""

    place: PurePosixPath
    files: int = 0
    size: int = 0
    """The bytes its files hold."""
    links: int = 0
    left: list[Left] = []
    placed: list[PurePosixPath] = []
    """Each file of it moved, or that would be, at its place in the home."""

    def said(self) -> str:
        """Say what of the record moves, in a line.

        >>> Moved(place=PurePosixPath("projects", "-w"), files=2, size=2048, links=1).said()
        'projects/-w: 2 files, 2.0 KiB, 1 link'
        """
        links = f", {counted(self.links, 'link', 'links')}" if self.links else ""
        return (
            f"{self.place}: {counted(self.files, 'file', 'files')}, "
            f"{sized(self.size)}{links}"
        )

    @classmethod
    def of(cls, place: PurePosixPath, steps: list[Step]) -> Moved:
        """Sum up what was done of the record at `place`, step by step."""
        return cls(
            place=place,
            files=sum(1 for each in steps if each.kind == "file"),
            size=sum(each.size for each in steps if each.kind == "file"),
            links=sum(1 for each in steps if each.kind == "link"),
            placed=[each.place for each in steps if each.kind == "file"],
            left=[
                Left(place=each.place, why=each.why or "left")
                for each in steps
                if each.kind == "left"
            ],
        )


def landing(name: str, holding: int | None, *, dry: bool) -> int | None:
    """Open the directory `name` of the home's directory whose descriptor is `holding`, made first where it's missing, never through a link; in a dry run, opened only where it's there, none where it isn't, and none below a directory that isn't.

    Raise `OSError` where what's there isn't a directory: a link, a file, or
    anything else a room left.
    """
    if holding is None:
        return None
    if dry:
        try:
            return entered(name, holding)
        except FileNotFoundError:
            return None
    try:
        # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
        os.mkdir(name, 0o700, dir_fd=holding)
    except FileExistsError:
        pass
    return entered(name, holding)


def taken(name: str, holding: int | None) -> os.stat_result | None:
    """Return what's at `name` in the home's directory whose descriptor is `holding`, its link never followed; none where nothing is."""
    if holding is None:
        return None
    try:
        # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
        return os.stat(name, dir_fd=holding, follow_symlinks=False)
    except FileNotFoundError:
        return None


def copied(name: str, source: int, target: int) -> str | None:
    """Copy the file `name` from the directory whose descriptor is `source` into the one whose descriptor is `target`, its mode and times kept, then remove the original; return why it's left where it couldn't be, none where it moved.

    A copy that fails partway is removed: it's the copy's alone, made here.
    """
    reading = regular(name, source)
    if reading is None:
        return "it stopped being a file as it moved: left"
    with ExitStack() as stack:
        stack.callback(os.close, reading)
        seen = os.fstat(reading)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            writing = os.open(name, flags, 0o600, dir_fd=target)
        except FileExistsError:
            return "the rooms' home holds one there already: left"
        try:
            with (
                open(reading, "rb", closefd=False) as read,
                open(writing, "wb", closefd=False) as written,
            ):
                shutil.copyfileobj(read, written)
            os.fchmod(writing, stat.S_IMODE(seen.st_mode))
            os.utime(writing, ns=(seen.st_atime_ns, seen.st_mtime_ns))
            os.fsync(writing)
        except OSError as failed:
            # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
            os.unlink(name, dir_fd=target)
            return f"its copy failed, {failed.strerror}: left"
        finally:
            os.close(writing)
    # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
    os.unlink(name, dir_fd=source)
    return None


def linked(name: str, source: int, target: int) -> str | None:
    """Move the file `name` from the directory whose descriptor is `source` into the one whose descriptor is `target` as a second name for it, then remove the first; return why it's left where it couldn't be, none where it moved.

    The file itself never moves, so its content, mode and times are kept. Where
    the home is on another filesystem, or the file isn't the operator's to link,
    it's copied (`copied`). What landed is checked to be a file: one swapped for
    a link as it moved lands as that link, which is removed, its original left.
    """
    try:
        # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
        os.link(name, name, src_dir_fd=source, dst_dir_fd=target, follow_symlinks=False)
    except FileExistsError:
        return "the rooms' home holds one there already: left"
    except OSError as failed:
        if failed.errno not in [errno.EXDEV, errno.EPERM]:
            return f"it couldn't move, {failed.strerror}: left"
        return copied(name, source, target)
    landed = taken(name, target)
    if landed is None or not stat.S_ISREG(landed.st_mode):
        # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
        os.unlink(name, dir_fd=target)
        return "it stopped being a file as it moved: left"
    # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
    os.unlink(name, dir_fd=source)
    return None


class Migration(Model):
    """One runtime's records of a repository, and the rooms' home they move into."""

    runtime: str
    """The runtime, by its adapter's name."""
    directory: Path
    """The operator's own directory for the runtime, the records' place."""
    home: Path
    """The rooms' home they move into."""
    records: list[Record]
    """The repository's records in `directory`, the operator's own (`whose`
    `host`), each at its place there."""

    def moved(self, *, dry: bool) -> list[Moved]:
        """Move each record into the home, or, `dry`, change nothing; return what was done of each, or what would be.

        Raise `MigrationError` where the home isn't a directory of its own.
        """
        return [
            Moved.of(record.place, list(self.steps(record, dry=dry)))
            for record in self.records
        ]

    def opened_home(self, *, dry: bool) -> int | None:
        """Open the home, made first where it's missing, as a launch makes it; in a dry run, opened where it's there, none where it isn't."""
        if not dry:
            self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            return entered(self.home)
        except FileNotFoundError:
            if dry:
                return None
            raise
        except OSError as failed:
            message = (
                f"the rooms' home at {self.home} isn't a directory of its own, "
                f"{failed.strerror}: nothing moves into it"
            )
            raise MigrationError(message) from failed

    def steps(self, record: Record, *, dry: bool) -> Iterator[Step]:
        """Walk one record from the operator's directory and from the home, a directory at a time, moving what's in it unless `dry`, and yield each thing done, or left."""
        if record.whose != "host" or record.home != self.directory:
            yield Step(
                kind="left",
                place=record.place,
                why=f"it isn't in {self.directory}, where it's listed: left",
            )
            return
        *parents, name = record.place.parts
        with ExitStack() as stack:
            # The operator's own directory: a room mounted it, and couldn't replace it.
            source = os.open(
                self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
            )
            stack.callback(os.close, source)
            target = self.opened_home(dry=dry)
            if target is not None:
                stack.callback(os.close, target)
            for part in parents:
                try:
                    source = entered(part, source)
                except OSError:
                    yield Step(
                        kind="left",
                        place=record.place,
                        why=f"`{part}` on its way isn't a directory of its own: left",
                    )
                    return
                stack.callback(os.close, source)
                try:
                    target = landing(part, target, dry=dry)
                except OSError:
                    yield Step(
                        kind="left",
                        place=record.place,
                        why=(
                            f"the rooms' home holds something other than a "
                            f"directory at `{part}`: left"
                        ),
                    )
                    return
                if target is not None:
                    stack.callback(os.close, target)
            yield from self.entry(
                name, source, target, PurePosixPath(record.place), dry=dry
            )

    def entry(
        self,
        name: str,
        source: int,
        target: int | None,
        place: PurePosixPath,
        *,
        dry: bool,
    ) -> Iterator[Step]:
        """Move what's at `name` in the directory whose descriptor is `source` to the same name in the one whose descriptor is `target`, by what it is, and yield each thing done, or left."""
        try:
            # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
            seen = os.stat(name, dir_fd=source, follow_symlinks=False)
        except FileNotFoundError:
            return
        match kind(seen.st_mode):
            case "directory":
                yield from self.folder(name, source, target, place, dry=dry)
            case "file":
                yield from self.file(name, source, target, place, seen, dry=dry)
            case "link":
                yield from self.link(name, source, target, place, dry=dry)
            case "other":
                yield Step(
                    kind="left",
                    place=place,
                    why="not a file, a directory or a link, as no record is: left",
                )

    def folder(
        self,
        name: str,
        source: int,
        target: int | None,
        place: PurePosixPath,
        *,
        dry: bool,
    ) -> Iterator[Step]:
        """Move a directory as what's in it moves, and remove it once that leaves it empty."""
        with ExitStack() as stack:
            try:
                inner = entered(name, source)
            except OSError:
                yield Step(kind="left", place=place, why="it changed as it moved: left")
                return
            stack.callback(os.close, inner)
            try:
                within = landing(name, target, dry=dry)
            except OSError:
                yield Step(
                    kind="left",
                    place=place,
                    why=(
                        "the rooms' home holds something other than a directory "
                        "there: left, with what's in it"
                    ),
                )
                return
            if within is not None:
                stack.callback(os.close, within)
            # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
            for each in sorted(os.listdir(inner)):
                yield from self.entry(each, inner, within, place / each, dry=dry)
        if dry:
            return
        try:
            # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
            os.rmdir(name, dir_fd=source)
        except OSError as failed:
            if failed.errno != errno.ENOTEMPTY:
                yield Step(
                    kind="left",
                    place=place,
                    why=f"emptied, it couldn't be removed, {failed.strerror}: left",
                )

    def file(
        self,
        name: str,
        source: int,
        target: int | None,
        place: PurePosixPath,
        seen: os.stat_result,
        *,
        dry: bool,
    ) -> Iterator[Step]:
        """Move a file into the home, unless the home holds one there: the same file, where a move before stopped between its two names, finishes."""
        there = taken(name, target)
        same = there is not None and (there.st_dev, there.st_ino) == (
            seen.st_dev,
            seen.st_ino,
        )
        if there is not None and not same:
            yield Step(
                kind="left",
                place=place,
                why="the rooms' home holds one there already: left",
            )
            return
        if dry:
            yield Step(kind="file", place=place, size=seen.st_size)
            return
        if same:
            # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
            os.unlink(name, dir_fd=source)
            yield Step(kind="file", place=place, size=seen.st_size)
            return
        if target is None:
            return
        why = linked(name, source, target)
        if why is not None:
            yield Step(kind="left", place=place, why=why)
            return
        yield Step(kind="file", place=place, size=seen.st_size)

    def link(
        self,
        name: str,
        source: int,
        target: int | None,
        place: PurePosixPath,
        *,
        dry: bool,
    ) -> Iterator[Step]:
        """Move a link aimed inside what moves, aimed at the same place in the home; leave any other, never following it."""
        # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
        aimed = os.readlink(name, dir_fd=source)
        # lup: ignore("os-path", why="where a link aims, read without following any link on the way, which `Path.resolve` would")
        reached = Path(os.path.normpath(self.directory / place.parent / aimed))
        within = [self.directory / each.place for each in self.records]
        if not any(reached.is_relative_to(each) for each in within):
            yield Step(
                kind="left",
                place=place,
                why=(
                    f"a link to {aimed}, out of what moves: left, never followed, "
                    "as a room could have made it"
                ),
            )
            return
        again = (
            str(self.home / reached.relative_to(self.directory))
            if Path(aimed).is_absolute()
            else aimed
        )
        if taken(name, target) is not None:
            yield Step(
                kind="left",
                place=place,
                why="the rooms' home holds one there already: left",
            )
            return
        if dry:
            yield Step(kind="link", place=place)
            return
        if target is None:
            return
        try:
            # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
            os.symlink(again, name, dir_fd=target)
        except FileExistsError:
            yield Step(
                kind="left",
                place=place,
                why="the rooms' home holds one there already: left",
            )
            return
        # lup: ignore("os-file-ops", why="pathlib has no call relative to a directory's descriptor, which is what keeps a link a room left on the way from aiming the host elsewhere")
        os.unlink(name, dir_fd=source)
        yield Step(kind="link", place=place)


def running_launches(layout: Layout, repository: Path) -> list[Register]:
    """Return each launch of the repository whose git directory is `repository` whose launcher still runs, holding its lock: its session could still write a record as it moves."""
    host = layout.host
    # Each launch's conversations are kept beside its record, and aren't a record.
    records = [
        read_model(path, Register)
        for path in sorted(host.launches.glob("*.json"))
        if path != host.conversations(path.stem.removesuffix(".conversations"))
    ]
    return [
        each
        for each in records
        if each is not None
        and each.repository == repository
        and layout.launch(each.launch).lock.is_file()
        and running(layout.launch(each.launch).lock)
    ]


def sized(size: int) -> str:
    """Say a count of bytes as a person reads it.

    >>> sized(0), sized(2_048), sized(1_150_000_000)
    ('0 B', '2.0 KiB', '1.1 GiB')
    """
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    exponent = 0
    amount = float(size)
    while amount >= 1024 and exponent < len(units) - 1:
        amount /= 1024
        exponent += 1
    if exponent == 0:
        return f"{size} B"
    return f"{amount:.1f} {units[exponent]}"


class HostRuntime(Model, arbitrary_types_allowed=True):
    """One runtime as the migration takes it, from its adapter: its name, the operator's own directory for it, its records there, and its check of what a host session acts on there."""

    name: str
    directory: Path
    records: Records
    written: Callable[[Places], Checked]
    recorded: Callable[[PurePosixPath], str | None]
    """The session whose own record is at a place, by the runtime's name for
    it there; none for any other place."""


class Walked(Model):
    """One runtime's records of a repository in the operator's own directory, and what was done of them, or would be."""

    runtime: str
    home: Path
    """The rooms' home they move into."""
    moved: list[Moved]
    """What of each record moved, or would."""
    sessions: list[str]
    """Each session whose own record moved, or would, by its id."""

    @property
    def files(self) -> int:
        """How many files moved, or would."""
        return sum(each.files for each in self.moved)

    @property
    def size(self) -> int:
        """The bytes the files that moved, or would, hold."""
        return sum(each.size for each in self.moved)

    @property
    def left(self) -> list[Left]:
        """What of the records stays where it is, and why."""
        return [part for each in self.moved for part in each.left]

    def moves(self) -> bool:
        """Say whether anything moved, or would: a file or a link.

        >>> from pathlib import Path
        >>> Walked(runtime="agent", home=Path("/h"), moved=[], sessions=[]).moves()
        False
        """
        return any(each.files or each.links for each in self.moved)

    def amount(self) -> str:
        """Say how much of the repository's moved, or would, in a few words: its sessions, else its records, and their size.

        >>> from pathlib import Path, PurePosixPath
        >>> moved = [Moved(place=PurePosixPath("projects", "-w"), files=3, size=2048)]
        >>> Walked(runtime="agent", home=Path("/h"), moved=moved, sessions=["a", "b"]).amount()
        '2 sessions of this repository, 2.0 KiB'
        >>> Walked(runtime="agent", home=Path("/h"), moved=moved, sessions=[]).amount()
        "1 record of this repository's sessions, 2.0 KiB"
        """
        counting = (
            f"{counted(len(self.sessions), 'session', 'sessions')} of this repository"
            if self.sessions
            else (
                f"{counted(len(self.moved), 'record', 'records')} of this "
                "repository's sessions"
            )
        )
        return f"{counting}, {sized(self.size)}"


class Migrating(Model, arbitrary_types_allowed=True):
    """One repository's migration, every runtime's: where its records are, where they go, and what's said of it, a line each."""

    layout: Layout
    repository: Path
    """The repository's git directory."""
    runtimes: list[HostRuntime]
    home: Path
    """The operator's home, to say each path from."""
    shared: bool = False
    """Whether the records go into the home every project shares, as a profile
    with `rooms_home="global"` runs on, rather than the project's."""

    def under(self) -> list[Path]:
        """Return the directories the repository's sessions ran in: its git directory, and each of its worktrees."""
        return [self.repository, *Git.pinned(self.repository).worktrees()]

    def places(self, under: list[Path]) -> Places:
        """Return the directories rooms write, or wrote: each runtime's own of the operator's, the repository's, and lup's own data rooms write."""
        return Places(
            home=self.home,
            written=[
                *(each.directory for each in self.runtimes),
                *under,
                *self.layout.written,
            ],
        )

    def live(self) -> list[Register]:
        """Return each launch of the repository still running, whose session would write on where their record was as it moves (`running_launches`)."""
        return running_launches(self.layout, self.repository)

    def refused(self, live: list[Register]) -> MigrationError:
        """Return why a move can't go on while the launches `live` of the repository run."""
        named = ", ".join(f"`{each.name or each.launch}`" for each in live)
        message = (
            f"a launch of this repository still runs, {named}, whose session "
            "would write on where their record was: end each, and every session "
            "of the repository on the host, then move"
        )
        return MigrationError(message)

    def said(self, *, move: bool) -> list[str]:
        """Move the repository's records of each runtime into its rooms' home, or, without `move`, change nothing; say what was done, or what would be, what's left, and what a host session acts on that rooms could have written.

        Raise `MigrationError` on a move while a launch of the repository runs.
        """
        live = self.live()
        if move and live:
            raise self.refused(live)
        under = self.under()
        places = self.places(under)
        return [
            *(
                []
                if move
                else [
                    (
                        "A dry run: nothing moves until `lup-dev account migrate "
                        "--move`. End every session of this repository first, in a room "
                        "or on the host: one still running writes on where their record "
                        "was."
                    ),
                    *(
                        f"Still running: `{each.name or each.launch}`, "
                        f"{each.runtime} in {each.worktree}, which `--move` waits on."
                        for each in live
                    ),
                ]
            ),
            *(
                line
                for each in self.runtimes
                for line in self.runtime(each, under, places, move=move)
            ),
            *(line for each in self.runtimes for line in self.checked(each, places)),
            (
                "Each account signs in at the first launch on it, in the room, with "
                "a login of its own: no host login is moved into one."
            ),
            *(
                [
                    (
                        "Resume one in a room with `lup-dev launch <runtime> --resume "
                        "<id>`, or `--resume` for the picker."
                    )
                ]
                if move
                else []
            ),
        ]

    def walked(
        self, adapter: HostRuntime, records: list[Record], *, move: bool
    ) -> Walked:
        """Move `records`, one runtime's of the repository in the operator's own directory, into its rooms' home, or, without `move`, change nothing; return what was done of them, or what would be.

        A move keeps the home of each session it moved (`lup_dev.host.homes.kept`),
        so no other room can claim its id, and marks the runtime's records of the
        repository moved (`ToldLayout.migrated`), so a launch doesn't offer to
        move what a host session writes there after: that stays the host's,
        unless the command moves it.
        """
        runtime = adapter.name
        home = self.layout.room_home(self.repository, runtime, shared=self.shared)
        moved = Migration(
            runtime=runtime, directory=adapter.directory, home=home, records=records
        ).moved(dry=not move)
        sessions = [
            session
            for each in moved
            for place in each.placed
            if (session := adapter.recorded(place)) is not None
        ]
        if move:
            for session in sessions:
                kept(self.layout.host, runtime, session, home, adapter.records)
            mark = self.layout.told.migrated(self.repository, runtime)
            mark.parent.mkdir(parents=True, exist_ok=True)
            mark.touch()
        return Walked(runtime=runtime, home=home, moved=moved, sessions=sessions)

    def runtime(
        self, adapter: HostRuntime, under: list[Path], places: Places, *, move: bool
    ) -> list[str]:
        """Move one runtime's records of the repository, or say what would move; say what's left, and, once, the records of other directories that stay."""
        runtime = adapter.name
        directory = adapter.directory
        shown = places.shown(directory)
        if not directory.is_dir():
            return [f"{runtime}: {shown} isn't there, so nothing of it moves."]
        records = self.operators(adapter, under)
        others = [
            each for each in self.operators(adapter, [Path("/")]) if each not in records
        ]
        stay = (
            [
                (
                    f"Records of other directories stay in {shown} as they are, "
                    f"{counted(len(others), 'record', 'records')}: every room could "
                    "write those too, so a session resumed from one on the host "
                    "resumes what a room may have changed."
                )
            ]
            if others
            else []
        )
        walked = self.walked(adapter, records, move=move)
        if not records:
            return [
                f"{runtime}: no record of this repository's sessions is in {shown}.",
                *stay,
            ]
        done = "moved" if move else "would move"
        reads = "The host reads" if move else "The host would read"
        sessions = walked.sessions
        theirs = (
            "its session there from then on, as a room resuming it does."
            if len(sessions) == 1
            else (
                f"its {len(sessions)} sessions there from then on, as a room "
                "resuming one does."
            )
        )
        left = walked.left
        return [
            (
                f"{runtime}: {counted(len(records), 'record', 'records')} of this "
                f"repository's sessions, {counted(walked.files, 'file', 'files')} and "
                f"{sized(walked.size)}, {done} from {shown} into "
                f"{places.shown(walked.home)}, where its rooms resume them:"
            ),
            *(f"- {each.said()}" for each in walked.moved),
            *([f"{reads} {theirs}"] if sessions else []),
            *(
                [
                    f"Left in {shown}, {counted(len(left), 'thing', 'things')}:",
                    *(f"- {each.place}: {each.why}" for each in left),
                ]
                if left
                else []
            ),
            *stay,
        ]

    def operators(self, adapter: HostRuntime, under: list[Path]) -> list[Record]:
        """Return the runtime's records of sessions run under `under` that are in the operator's own directory: what moves, the rooms' homes' being where they go."""
        return [
            each
            for each in adapter.records.kept(under, self.repository)
            if each.whose == "host" and each.home == adapter.directory
        ]

    def found(self, adapter: HostRuntime, places: Places) -> Checked:
        """Check what a host session of one runtime acts on in the operator's own directory, which rooms could have written; nothing where the directory isn't there."""
        if not adapter.directory.is_dir():
            return Checked()
        return adapter.written(places)

    def checked(self, adapter: HostRuntime, places: Places) -> list[str]:
        """Say what a host session of one runtime acts on in the operator's own directory, which rooms could have written."""
        found = self.found(adapter, places).said()
        if not found:
            return []
        return [
            (
                f"In {places.shown(adapter.directory)}, which every room running "
                f"{adapter.name} could write before rooms had homes of "
                "their own, a host session acts on what follows; lup can't tell "
                "what a room wrote there from what you did:"
            ),
            *(f"- {each}" for each in found),
        ]
