"""What `Transcripts` serves: copying each session's record of the repository and of each related repository when a launch opens, when it stops and before a room reads them, and reading the copies.

The launch's runtime says which of its records are the repository's sessions'
(`Records.kept`), from the directories they ran in: the repository's git
directory, and each of its worktrees; and in which of its homes each is: the
operator's own directory, the repository's rooms' home, or the one every
project's rooms share. Each record is copied into the module's own data
directory for the repository, under the runtime's name and then whose home it
was kept in (`host/`, `rooms/`, `shared/`), so a room's record and the host's
never meet, laid out as the runtime lays them out. Each repository the
declaration names beside the project has its sessions' copies under
`related/<its name>/`, laid out the same (`TranscriptsServing.places`). A file
is copied where the copy is missing, or differs in size or time from the
record, so what the runtime has added or grown since the last copy is copied,
and what's unchanged isn't read again; a room's file matching the host's copy
at the same place, as a record moved or copied into a room's home from the
operator's directory does, is that copy, and nothing a room's home holds moves
or changes one of the host's (`copied`). A runtime only adds to its records,
so a copy taken when a launch opens catches whatever an earlier launch that
never stopped left.

Its commands read the copies (`packages/lup-transcripts/README.md`, *Reading
them*): `list` every kept session, `show` one, the operator's words first,
`search` what the operator said; each through its runtime's reading of its
records, for the operator or a room, saying whose home each was kept from. In a
room, each asks the host to keep first (`Keep`), one request, so what it reads
is what the host holds as it asks.

Its views read a conversation live, from the runtime's own record as it grows
(`conversation`, the drawer under each agent's banner; `exchange`, one earlier
exchange; `call`, one call read whole), laid out in lup's blocks
(`environment/conversation.py`), each record read again only once it changed
(`Recording`). The drawer keeps open at most the agent's last words its fold
kind of what came earlier keeps (`FoldKind.keeps_open`, 20 unless a person's
layer says), as the module's layers leave it. Shown, the drawer and each
exchange opened in it are answered again at their agent's turns and calls and
a minute apart at most; a call read whole, open in it, as a call of the
agent's finishes, so one still running shows what it returned once it has.
"""

import asyncio
import os
import shutil
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal, get_args

from pydantic import Field

import lup
from lup.blocks import FoldKind, OfAgent
from lup.rooms.homes import plain
from lup.types import Model
from lup_dev.confined import Confined
from lup_dev.declaration.serving import Lup, ModuleServing, Operator, Related, Room
from lup_dev.git import Git, GitError
from lup_dev.host.client import FromRoom, RoomClient
from lup_dev.host.protocol import HostError, Reply, Request
from lup_dev.host.records import Home, Whose
from lup_dev.inbox.context import Recording
from lup_dev.layout import digest
from lup_transcripts.environment import views
from lup_transcripts.environment.conversation import (
    EARLIER_KIND,
    FOLD_KINDS,
    OfCall,
    OfExchange,
    call_blocks,
    conversation_blocks,
    exchange_blocks,
)

if TYPE_CHECKING:
    from lup_dev.host.records import Record, Records
    from lup_transcripts.environment.module import Transcripts


GROWING = lup.Watch(
    on=[lup.TurnStarted, lup.CallFinished, lup.TurnEnded, lup.ConversationEnded],
    longest=timedelta(minutes=1),
)
"""When a view of a conversation as it grows is answered again, shown: at its
agent's turns and calls, and a minute apart at most. The drawer's, and an
exchange's, since what came before the agent's last words in the latest one
moves on with each of its words."""


class Every(Model):
    """Nothing to choose: every kept session."""


class Chosen(Model, populate_by_name=True):
    """One kept session, and how much of it."""

    session: str = Field(
        description="The session: its id, the start of its id, or its name."
    )
    everything: bool = Field(
        default=False,
        alias="all",
        description="Everything said, the agent's words too, each run of tool calls a line.",
    )
    home: Whose | None = Field(
        default=None,
        alias="from",
        description="Whose home its record was kept from, where it was kept from several: `host`, `rooms` or `shared`.",
    )


class Searched(Model):
    """Words the operator said, and how much of what each answered."""

    words: list[str] = Field(description="Words you said, all of them.")
    whole: bool = Field(
        default=False,
        description="What each time answered whole, rather than its first line.",
    )


class Keep(Request, reads=False):
    """A room's ask that the host keep what the repository's sessions' records added or grew, before the room reads the copies."""

    kind: Literal["transcripts-keep"] = "transcripts-keep"


class Kept(Reply):
    """What the host kept: how many files it copied."""

    kind: Literal["transcripts-kept"] = "transcripts-kept"
    copied: int


WHOSE: list[Whose] = list(get_args(Whose.__value__))
"""Each home a record is kept from, in the order its copies are read."""


def stale(source: Path, copy: Path) -> bool:
    """Say whether `copy` is missing, or differs in size or time from `source`."""
    if not copy.is_file():
        return True
    held, kept = source.stat(), copy.stat()
    return (held.st_size, held.st_mtime_ns) != (kept.st_size, kept.st_mtime_ns)


def copied(
    records: list[Record], target: Path, besides: list[Path] | None = None
) -> int:
    """Copy each file of `records` into `target` where it's stale, and return how many were copied.

    A file is kept already where the copy at its place under any of `besides`
    isn't stale either: what's copied from a room's home is kept already where
    the host's copy matches it, as a record moved into the home from the
    operator's directory, its time kept, or copied there from the host does,
    so it's kept once, as the host's, until a room changes it. Nothing under
    `besides` is ever changed.

    A room writes the records copied, and every room of the project reads the
    copies, so a link a room left there would copy what it names, a key in
    `~/.ssh` say, where every room reads it. So each file is read as the host
    reads a worktree's (`Confined`): a regular file, opened without waiting on
    a pipe, only where it resolves inside its record's folder; a record reached
    through a link below the runtime's home, the part a room writes, is left
    out whole, while a link in the home's own path (a home kept in a dotfiles
    checkout, `/home` itself a link) is the machine's and is followed. A link
    the runtime made between its own files in the folder, as a runtime may
    link a resumed session's subagents to the session it resumed, is copied as
    the file it names. Each copy keeps its file's time, which `stale` compares.
    """
    others = besides or []
    count = 0
    for record in records:
        source = record.source
        if source.resolve() != record.home.resolve().joinpath(*record.place.parts):
            continue
        whole = source.is_dir(follow_symlinks=False)
        folder = Confined(root=source if whole else source.parent)
        files = (
            sorted(
                each
                for each in source.rglob("*")
                if not each.is_dir(follow_symlinks=False)
            )
            if whole
            else [source]
        )
        for each in files:
            place = record.place / each.relative_to(source)
            copy = target / place
            try:
                if not stale(each, copy) or any(
                    not stale(each, other / place) for other in others
                ):
                    continue
                held = each.stat()
            except OSError:
                continue
            content = folder.read(each.relative_to(folder.root))
            if content is None:
                continue
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(content)
            os.utime(copy, ns=(held.st_atime_ns, held.st_mtime_ns))
            count += 1
    return count


def moved(entry: Path, to: Path) -> None:
    """Move `entry` to `to`, a directory into one there already entry by entry; a file there already is the later copy, and `entry`'s is dropped."""
    if not to.exists():
        to.parent.mkdir(parents=True, exist_ok=True)
        entry.rename(to)
        return
    if entry.is_dir() and to.is_dir():
        for each in sorted(entry.iterdir()):
            moved(each, to / each.name)
        entry.rmdir()
        return
    if entry.is_dir():
        shutil.rmtree(entry)
        return
    entry.unlink()


def relaid(copies: Path) -> None:
    """Move what's kept at `copies` itself, a runtime's copies as they were kept before each home's had its own place, under `host/`: they were all copied from the operator's own directory."""
    if not copies.is_dir():
        return
    for entry in sorted(copies.iterdir()):
        if entry.name not in WHOSE:
            moved(entry, copies / "host" / entry.name)


def into(records: list[Record], copies: Path) -> int:
    """Copy `records`, a runtime's, into `copies`, each under whose home it's kept in, where it's stale; a room's where the host's copy is stale too. Return how many files were copied."""
    relaid(copies)
    host = copies / "host"
    return sum(
        copied(
            [each for each in records if each.whose == whose],
            copies / whose,
            besides=[] if whose == "host" else [host],
        )
        for whose in WHOSE
    )


class Place(Model):
    """A repository whose sessions' records are kept, and where their copies go."""

    repository: Path
    """Its git directory."""
    under: list[Path]
    """The directories its sessions run in: its git directory and each of its
    worktrees."""
    copies: Path
    """Where its records' copies are kept, a directory per runtime."""


def related_place(other: Related, copies: Path) -> Place:
    """Return where the records of `other`, a repository the declaration names beside the project, are kept: under `copies`, by its name where that's a plain name, else by its path's digest.

    Its git directory is its `.git` where it's a clone's working tree, else
    its own directory, as a bare repository's is. Where git can't list its
    worktrees, as for one that isn't on the host, its sessions are those that
    ran under its path, which the records the host still holds of it may name.
    """
    dotted = other.path / ".git"
    repository = dotted if dotted.is_dir() else other.path
    try:
        under = [repository, *Git.pinned(repository).worktrees()]
    except GitError:
        under = [repository, other.path]
    named = other.name if plain(other.name) else digest(other.path)
    return Place(repository=repository, under=under, copies=copies / named)


class TranscriptsServing(ModuleServing):
    """Keeping the repository's sessions' records, and each related repository's: what each runtime added or grew, when a launch opens, when it stops, and before a room reads them."""

    module: Transcripts
    room: FromRoom = Field(default_factory=lambda: FromRoom(room=RoomClient()))
    """Where a command run in a room asks the host to keep first: its launch's
    request socket, a host running a copy from before it could be asked said
    so."""
    recording: ClassVar[Recording] = Recording()
    """Each conversation's record as last read, kept across calls in the
    repository's process, so a record unchanged since isn't read again."""

    def places(self, repository: Path) -> list[Place]:
        """Return the repository whose git directory is `repository`, and each the declaration names beside it, with where each one's copies go."""
        own = Place(
            repository=repository,
            under=[repository, *Git.pinned(repository).worktrees()],
            copies=self.data,
        )
        return [
            own,
            *(related_place(each, self.data / "related") for each in self.related),
        ]

    def keeping(self, repository: Path, runtimes: list[str]) -> int:
        """Copy what each of `runtimes` added or grew of its records of the repository whose git directory is `repository`, and of each related repository, since the last copy; return how many files were copied."""

        def of(records: Records, place: Place, runtime: str) -> int:
            kept = records.kept(place.under, place.repository)
            return into(kept, place.copies / runtime)

        return sum(
            of(self.recorded[runtime].records, place, runtime)
            for place in self.places(repository)
            for runtime in runtimes
        )

    @lup.on(lup.Launched)
    @lup.on(lup.Stopped)
    async def keep(self, event: lup.Launched | lup.Stopped, by: Lup) -> None:
        """Copy every record of the repository's sessions, and of each related repository's, the launch's runtime added or grew since the last copy."""
        del event
        launch = by.launch
        await asyncio.to_thread(self.keeping, launch.repository, [launch.runtime])

    @lup.request
    async def refresh(self, asked: Keep, by: Room) -> Kept:
        """Copy what every runtime added or grew of the records of the room's repository's sessions, and of each related repository's, as a room asks before it reads the copies."""
        del asked
        runtimes = list(self.recorded)
        count = await asyncio.to_thread(self.keeping, by.launch.repository, runtimes)
        return Kept(copied=count)

    async def fresh(self, by: Operator | Room) -> str:
        """Ask the host to keep first, where a room asks, so the copies it reads are what the host holds as it asks; return a line saying why it couldn't, where it couldn't, else nothing.

        On the host, the copies are as the last launch's opening or stop left
        them.
        """
        if not isinstance(by, Room):
            return ""
        try:
            await asyncio.to_thread(self.room.ask, Keep(), Kept)
        except HostError as unkept:
            return (
                "\nThese are the copies as the host last kept them, at a launch's "
                f"opening or stop: asked to keep first, it didn't, since {unkept}.\n"
            )
        return ""

    def kept(self) -> list[views.Session]:
        """Read every session kept of the repository, and of each related repository, of every runtime whose records the module reads, each with whose home its record was kept from."""
        related = self.data / "related"
        others = sorted(related.iterdir()) if related.is_dir() else []
        return [
            *self.read(self.data, None),
            *(each for other in others for each in self.read(other, other.name)),
        ]

    def read(self, copies: Path, repository: str | None) -> list[views.Session]:
        """Read the sessions kept at `copies`, under each runtime's name and whose home each was kept in, and kept there as each runtime's were before each home's had its own place, as the host's; `repository` names the related repository they're of, none for the project's own."""

        def held(runtime: str) -> list[Home]:
            folder = copies / runtime
            return [
                *(Home(directory=folder / whose, whose=whose) for whose in WHOSE),
                # lup: defer(issue=324, why="copies an approved copy from before kept flat are read as the host's, from a room on newer code, until that host keeps them by home (`relaid`)")
                Home(directory=folder, whose="host"),
            ]

        return [
            views.Session(
                transcript=each.reader.read(record),
                whose=home.whose,
                repository=repository,
            )
            for runtime, each in self.recorded.items()
            for home in held(runtime)
            for record in each.reader.sessions(home.directory)
        ]

    @lup.command
    async def list(self, asked: Every, by: Operator | Room) -> str:
        """List this repository's kept sessions, and each related repository's, newest first: when each started, its name and id, how often you spoke, where it ran, and whose home its record was kept from."""
        del asked
        unkept = await self.fresh(by)
        lines = views.listed(await asyncio.to_thread(self.kept))
        listed = (
            "\n".join(lines) if lines else "No session of this repository is kept yet."
        )
        return f"{listed}\n{unkept}" if unkept else listed

    @lup.command
    async def show(self, asked: Chosen, by: Operator | Room) -> str:
        """Show what you said in a session, each time after what the agent last said before it; or, with `--all`, the whole conversation.

        What you typed in its terminal is its record's alone. What reached a
        session through lup, your reviews and answers among it, and what it
        said to you, is its exchange in lup's inbox, which this leaves out:
        where the inbox holds some, the last line says how many items, and the
        `lup-dev inbox --conversation` that reads them; where the host service
        can't be asked, the last line says so.
        """
        unkept = await self.fresh(by)
        kept = await asyncio.to_thread(self.kept)
        chosen = views.chosen(kept, asked.session, asked.home)
        said = views.whole(chosen) if asked.everything else views.answered(chosen)
        session = chosen.transcript
        try:
            exchanged = await self.exchanges.exchanged(
                OfAgent(runtime=session.runtime, session=session.session)
            )
        except HostError as unasked:
            return (
                f"{said}\nlup's inbox wasn't asked for this session's exchange: "
                f"{unasked}\n{unkept}"
            )
        items = len(exchanged.sent) + len(exchanged.received)
        if not items:
            return f"{said}{unkept}"
        command = f"lup-dev inbox --conversation {session.session} --every --whole"
        counted = "1 item" if items == 1 else f"{items} items"
        return (
            f"{said}\nIts exchange with you through lup, which this leaves out, is "
            f"{counted} in lup's inbox: `{command}` reads it.\n{unkept}"
        )

    @lup.command
    async def search(self, asked: Searched, by: Operator | Room) -> str:
        """Find each time you said all of `words`, in any kept session: when, your words, and the first line of what they answered, or with `--whole` all of it."""
        unkept = await self.fresh(by)
        sessions = await asyncio.to_thread(self.kept)
        return views.found(sessions, asked.words, whole=asked.whole) + unkept

    def earlier(self) -> FoldKind:
        """Return the fold kind of what came earlier in a conversation as the module's layers leave it: how many of the agent's last words it keeps open (`FoldKind.keeps_open`), a person's layer setting more or fewer."""
        kinds = self.module.folds.resolve(FOLD_KINDS, FOLD_KINDS)
        return next(
            (each.entry for each in kinds if each.entry.name == EARLIER_KIND.name),
            EARLIER_KIND,
        )

    @lup.view(
        place=lup.Drawer(letter="v", called="the conversation", colour="cyan"),
        watch=GROWING,
    )
    async def conversation(self, viewed: OfAgent) -> lup.Blocks:
        """Show an agent's whole conversation from its runtime's record, live: everything since your last words open, each earlier exchange folded under your words that opened it, each run of calls under one line, and the items of lup's inbox it sent and was sent where they happened."""
        read = await asyncio.to_thread(
            self.recording.read,
            self.recorded,
            viewed.runtime,
            viewed.session,
            viewed.agent,
        )
        exchanged = await self.exchanges.exchanged(viewed)
        return conversation_blocks(
            viewed,
            read.transcript.entries,
            exchanged,
            exchange=TranscriptsServing.exchange,
            call=TranscriptsServing.call,
            earlier=self.earlier(),
        )

    @lup.view(watch=GROWING)
    async def exchange(self, viewed: OfExchange) -> lup.Blocks:
        """Show one earlier exchange of an agent's conversation, from your words that opened it to your next; or, with `--until-last`, what came in it before the agent's last words that many."""
        read = await asyncio.to_thread(
            self.recording.read,
            self.recorded,
            viewed.runtime,
            viewed.session,
            viewed.agent,
        )
        exchanged = await self.exchanges.exchanged(viewed)
        return exchange_blocks(
            viewed,
            read.transcript.entries,
            exchanged,
            exchange=TranscriptsServing.exchange,
            call=TranscriptsServing.call,
            earlier=self.earlier(),
        )

    @lup.view(watch=lup.Watch(on=[lup.CallFinished]))
    async def call(self, viewed: OfCall) -> lup.Blocks:
        """Show one call of an agent's conversation whole: what it was given, and what it returned, or that it hasn't returned yet."""
        read = await asyncio.to_thread(
            self.recording.read,
            self.recorded,
            viewed.runtime,
            viewed.session,
            viewed.agent,
        )
        reader = self.recorded[viewed.runtime].reader
        found = await asyncio.to_thread(
            reader.calls, read.record, [viewed.id], read.root
        )
        return call_blocks(viewed, found[0] if found else None)
