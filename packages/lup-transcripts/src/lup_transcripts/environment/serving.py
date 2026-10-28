"""What `Transcripts` serves: copying each session's record of the repository when a launch opens and when it stops, and reading the copies.

The launch's runtime says which of its records are the repository's sessions'
(`Records.kept`), from the directories they ran in: the repository's git
directory, and each of its worktrees; and in which of its homes each is: the
operator's own directory, the repository's rooms' home, or the one every
project's rooms share. Each record is copied into the module's own data
directory for the repository, under the runtime's name and then whose home it
was kept in (`host/`, `rooms/`, `shared/`), so a room's record and the host's
never meet, laid out as the runtime lays them out. A file is copied where the
copy is missing, or differs in size or time from the record, so what the
runtime has added or grown since the last copy is copied, and what's unchanged
isn't read again; a room's file matching the host's copy at the same place, as
a record moved or copied into a room's home from the operator's directory does,
is that copy, and nothing a room's home holds moves or changes one of the
host's (`copied`). A runtime only adds to its records, so a copy taken when a
launch opens catches whatever an earlier launch that never stopped left.

Its commands read the copies (`packages/lup-transcripts/README.md`, *Reading
them*): `list` every kept session, `show` one, the operator's words first,
`search` what the operator said; each through its runtime's reading of its
records, for the operator or a room, saying whose home each was kept from.

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
from typing import TYPE_CHECKING, ClassVar, get_args

from pydantic import Field

import lup
from lup.blocks import FoldKind, OfAgent
from lup.types import Model
from lup_dev.confined import Confined
from lup_dev.declaration.serving import Lup, ModuleServing, Operator, Room
from lup_dev.git import Git
from lup_dev.host.protocol import HostError
from lup_dev.host.records import Home, Whose
from lup_dev.inbox.context import Recording
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
    from pathlib import Path

    from lup_dev.host.records import Record
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


class TranscriptsServing(ModuleServing):
    """Keeping the repository's sessions' records: what the runtime added or grew, when a launch opens and when it stops."""

    module: Transcripts
    recording: ClassVar[Recording] = Recording()
    """Each conversation's record as last read, kept across calls in the
    repository's process, so a record unchanged since isn't read again."""

    def keeping(self, repository: Path, runtimes: list[str]) -> int:
        """Copy what each of `runtimes` added or grew of its records of the repository whose git directory is `repository` since the last copy; return how many files were copied."""
        under = [repository, *Git.pinned(repository).worktrees()]
        return sum(
            into(
                self.recorded[runtime].records.kept(under, repository),
                self.data / runtime,
            )
            for runtime in runtimes
        )

    @lup.on(lup.Launched)
    @lup.on(lup.Stopped)
    async def keep(self, event: lup.Launched | lup.Stopped, by: Lup) -> None:
        """Copy every record of the repository's sessions the launch's runtime added or grew since the last copy."""
        del event
        launch = by.launch
        await asyncio.to_thread(self.keeping, launch.repository, [launch.runtime])

    def kept(self) -> list[views.Session]:
        """Read every session kept of the repository, of every runtime whose records the module reads, each with whose home its record was kept from: under its runtime's name and whose home it was kept in, or kept there as each runtime's were before each home's had its own place, as the host's."""

        def held(runtime: str) -> list[Home]:
            folder = self.data / runtime
            return [
                *(Home(directory=folder / whose, whose=whose) for whose in WHOSE),
                # lup: defer(issue=324, why="copies an approved copy from before kept flat are read as the host's, from a room on newer code, until that host keeps them by home (`relaid`)")
                Home(directory=folder, whose="host"),
            ]

        return [
            views.Session(transcript=each.reader.read(record), whose=home.whose)
            for runtime, each in self.recorded.items()
            for home in held(runtime)
            for record in each.reader.sessions(home.directory)
        ]

    @lup.command
    async def list(self, asked: Every, by: Operator | Room) -> str:
        """List this repository's kept sessions, newest first: when each started, its name and id, how often you spoke, where it ran, and whose home its record was kept from."""
        del asked, by
        lines = views.listed(await asyncio.to_thread(self.kept))
        return (
            "\n".join(lines) if lines else "No session of this repository is kept yet."
        )

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
        del by
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
                f"{unasked}\n"
            )
        items = len(exchanged.sent) + len(exchanged.received)
        if not items:
            return said
        command = f"lup-dev inbox --conversation {session.session} --every --whole"
        counted = "1 item" if items == 1 else f"{items} items"
        return (
            f"{said}\nIts exchange with you through lup, which this leaves out, is "
            f"{counted} in lup's inbox: `{command}` reads it.\n"
        )

    @lup.command
    async def search(self, asked: Searched, by: Operator | Room) -> str:
        """Find each time you said all of `words`, in any kept session: when, your words, and the first line of what they answered, or with `--whole` all of it."""
        del by
        sessions = await asyncio.to_thread(self.kept)
        return views.found(sessions, asked.words, whole=asked.whole)

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
        found = await asyncio.to_thread(reader.calls, read.record, [viewed.id])
        return call_blocks(viewed, found[0] if found else None)
