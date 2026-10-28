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
(`Recording`). Shown, the drawer is answered again at its agent's turns and
calls and a minute apart at most; a call read whole, open in it, as a call of
the agent's finishes, so one still running shows what it returned once it has.
"""

import asyncio
import shutil
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

import lup
from lup.blocks import OfAgent
from lup.types import Model
from lup_dev.declaration.serving import Lup, ModuleServing, Operator, Room
from lup_dev.git import Git
from lup_dev.host.protocol import HostError
from lup_dev.inbox.context import Recording
from lup_transcripts.environment import views
from lup_transcripts.environment.conversation import (
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
    """Copy each file of `records` into `target` where it's stale, and return how many were copied."""
    pairs = [
        (each, target / record.place / each.relative_to(record.source))
        for record in records
        for each in (
            [record.source]
            if record.source.is_file()
            else sorted(path for path in record.source.rglob("*") if path.is_file())
        )
    ]
    stale_pairs = [(source, copy) for source, copy in pairs if stale(source, copy)]
    for source, copy in stale_pairs:
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, copy)
    return len(stale_pairs)


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

    @lup.view(
        place=lup.Drawer(letter="v", called="the conversation", colour="cyan"),
        watch=lup.Watch(
            on=[
                lup.TurnStarted,
                lup.CallFinished,
                lup.TurnEnded,
                lup.ConversationEnded,
            ],
            longest=timedelta(minutes=1),
        ),
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
        )

    @lup.view
    async def exchange(self, viewed: OfExchange) -> lup.Blocks:
        """Show one earlier exchange of an agent's conversation, from your words that opened it to your next."""
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
            call=TranscriptsServing.call,
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
