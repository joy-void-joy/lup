"""What `Transcripts` serves: copying each session's record of the repository when a launch opens and when it stops, and reading the copies.

The launch's runtime says which of its records are the repository's sessions'
(`Records.kept`), from the directories they ran in: the repository's git
directory, and each of its worktrees. Each record is copied into the module's own
data directory for the repository, under the runtime's name, laid out as the
runtime lays them out: a file is copied where the copy is missing, or differs in
size or time from the record, so what the runtime has added or grown since the
last copy is copied, and what's unchanged isn't read again. A runtime only adds
to its records, so a copy taken when a launch opens catches whatever an earlier
launch that never stopped left.

Its commands read the copies (`packages/lup-transcripts/README.md`, *Reading
them*): `list` every kept session, `show` one, the operator's words first,
`search` what the operator said; each through its runtime's reading of its
records, for the operator or a room.

Its views read a conversation live, from the runtime's own record as it grows
(`conversation`, the drawer under each agent's banner; `exchange`, one earlier
exchange; `call`, one call read whole), laid out in lup's blocks
(`environment/conversation.py`), each record read again only once it changed
(`Recording`). The drawer opens what came after the operator last read it,
by its review mark (`self.marks`, keyed by the conversation's runtime's ids,
`drawn`) or their own last words, and offers moving the mark to its last step,
Space `d` on its line; it keeps open at most the agent's last words its fold
kind of what came earlier keeps (`FoldKind.keeps_open`, 20 unless a person's
layer says), as the module's layers leave it. Shown, the drawer and each
exchange opened in it are answered again at their agent's turns and calls and
a minute apart at most; a call read whole, open in it, as a call of the
agent's finishes, so one still running shows what it returned once it has.
"""

import asyncio
import os
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

import lup
from lup.blocks import FoldKind, OfAgent
from lup.types import JsonObject, Model
from lup_dev.confined import Confined
from lup_dev.declaration.serving import Lup, ModuleServing, Operator, Room
from lup_dev.git import Git
from lup_dev.host.protocol import HostError
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

    from lup_dev.host.records import Record, Transcript
    from lup_transcripts.environment.module import Transcripts


GROWING = lup.Watch(
    on=[lup.TurnStarted, lup.CallFinished, lup.TurnEnded, lup.ConversationEnded],
    longest=timedelta(minutes=1),
)
"""When a view of a conversation as it grows is answered again, shown: at its
agent's turns and calls, and a minute apart at most. The drawer's, and an
exchange's, since what came before the agent's last words in the latest one
moves on with each of its words."""


def drawn(viewed: OfAgent) -> JsonObject:
    """Return the key of the review mark on the conversation `viewed` names: its runtime's ids, which a rename never changes."""
    return OfAgent(
        runtime=viewed.runtime, session=viewed.session, agent=viewed.agent
    ).model_dump(mode="json")


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


class Searched(Model):
    """Words the operator said, and how much of what each answered."""

    words: list[str] = Field(description="Words you said, all of them.")
    whole: bool = Field(
        default=False,
        description="What each time answered whole, rather than its first line.",
    )


def stale(source: Path, copy: Path) -> bool:
    """Say whether `copy` is missing, or differs in size or time from `source`."""
    if not copy.is_file():
        return True
    held, kept = source.stat(), copy.stat()
    return (held.st_size, held.st_mtime_ns) != (kept.st_size, kept.st_mtime_ns)


def copied(records: list[Record], target: Path) -> int:
    """Copy each file of `records` into `target` where it's stale, and return how many were copied.

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
    count = 0
    for record in records:
        source = record.source
        home = source.parents[len(record.place.parts) - 1]
        if source.resolve() != home.resolve().joinpath(*record.place.parts):
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
            copy = target / record.place / each.relative_to(source)
            try:
                if not stale(each, copy):
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


class TranscriptsServing(ModuleServing):
    """Keeping the repository's sessions' records: what the runtime added or grew, when a launch opens and when it stops."""

    module: Transcripts
    recording: ClassVar[Recording] = Recording()
    """Each conversation's record as last read, kept across calls in the
    repository's process, so a record unchanged since isn't read again."""

    @lup.on(lup.Launched)
    @lup.on(lup.Stopped)
    async def keep(self, event: lup.Launched | lup.Stopped, by: Lup) -> None:
        """Copy every record of the repository's sessions the launch's runtime added or grew since the last copy."""
        del event
        launch = by.launch
        under = [launch.repository, *Git.pinned(launch.repository).worktrees()]
        records = self.recorded[launch.runtime].records.kept(under)
        target = self.data / launch.runtime
        await asyncio.to_thread(copied, records, target)

    def kept(self) -> list[Transcript]:
        """Read every session kept of the repository, of every runtime whose records the module reads."""
        return [
            each.reader.read(record)
            for runtime, each in self.recorded.items()
            for record in each.reader.sessions(self.data / runtime)
        ]

    @lup.command
    async def list(self, asked: Every, by: Operator | Room) -> str:
        """List this repository's kept sessions, newest first: when each started, its name and id, how often you spoke, where it ran."""
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
        chosen = views.chosen(await asyncio.to_thread(self.kept), asked.session)
        said = views.whole(chosen) if asked.everything else views.answered(chosen)
        try:
            exchanged = await self.exchanges.exchanged(
                OfAgent(runtime=chosen.runtime, session=chosen.session)
            )
        except HostError as unasked:
            return (
                f"{said}\nlup's inbox wasn't asked for this session's exchange: "
                f"{unasked}\n"
            )
        items = len(exchanged.sent) + len(exchanged.received)
        if not items:
            return said
        command = f"lup-dev inbox --conversation {chosen.session} --every --whole"
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
        """Show an agent's whole conversation from its runtime's record, live: everything since you last read it open, by its review mark or your last words, each earlier exchange folded under your words that opened it, each run of calls under one line, and the items of lup's inbox it sent and was sent where they happened."""
        read = await asyncio.to_thread(
            self.recording.read,
            self.recorded,
            viewed.runtime,
            viewed.session,
            viewed.agent,
        )
        exchanged = await self.exchanges.exchanged(viewed)
        entries = read.transcript.entries
        key = drawn(viewed)
        return conversation_blocks(
            viewed,
            entries,
            exchanged,
            exchange=TranscriptsServing.exchange,
            call=TranscriptsServing.call,
            earlier=self.earlier(),
            mark=await self.marks.mark(key),
            reading=self.marks.offer(key, str(len(entries) - 1), "mark it read"),
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
            mark=await self.marks.mark(drawn(viewed)),
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
