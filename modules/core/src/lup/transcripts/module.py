"""`Transcripts`: every session's record on the machine, read where the runtimes keep it, indexed with what the operator said through lup, and searched, among lup's default modules.

`README.md` here. Its index is one part for the whole machine (`Transcribing`),
which reads before each answer what every record added since, and copies the
operator's own records so a runtime's cleanup can't lose them; what a session
is told of it is a part of its own (`Telling`), since a part holding something
tells nothing.
"""

from pathlib import Path
lazy from collections.abc import Iterator
lazy from string.templatelib import Template

import lup
from lup.declaration.module import Module
from lup.doors.door import RefusedError
from lup.doors.events import Stopping
from lup.doors.parts import Data, Declared, Part, Parts
from lup.inbox.part import Inboxes
from lup.inbox.said import Since
from lup.runtimes.records import Records, copied
from lup.runtimes.runtime import Runtimes
from lup.shell.blocks import Blocks
from lup.shell.kinds import Folds
from lup.transcripts.index import Home, Index, Listing, Searching, Showing
from lup.transcripts.layout import ARCHIVE, HOMES, INDEX, KEPT, LEDGER, LEDGER_COPY
from lup.transcripts.promises import TranscriptsPromises
from lup.transcripts.views import (
    FOLDS,
    Opens,
    listed_blocks,
    searched_blocks,
    shown_blocks,
)


class Transcribing(Part, shared=True):
    """The index of every conversation on the machine, every project's, on both runtimes, with what the operator said through lup: caught up before each answer with what was added since, the first time with everything."""

    module: Transcripts
    data: Data
    """Where the index, and lup's copies of the operator's own records and of
    the second lup's ledger, are kept."""
    declared: Declared
    """The project's modules, whose runtimes say how each runtime's records are
    read and where the operator's own are."""
    index: Index | None = None
    """The index, opened the first time it's needed."""

    def opened(self) -> Index:
        """Return the index, opening it the first time."""
        if self.index is None:
            self.index = Index.opened(self.data.path / INDEX)
        return self.index

    def homes(self) -> list[Home]:
        """Return every home the index reads: the operator's own runtime directories and lup's copy of them, the rooms' homes, and the second lup's copies."""
        homes = self.module.homes.expanduser()
        archive = self.module.archive.expanduser() if self.module.archive else None

        def each() -> Iterator[Home]:
            """Yield each runtime's homes, in the order a conversation kept in several is read from."""
            for runtime in self.declared.held(Runtimes):
                records = runtime.records
                yield from (
                    Home(
                        runtime=runtime.name, path=path, whose="rooms", records=records
                    )
                    for path in [
                        *sorted(homes.glob(f"projects/*/{runtime.name}")),
                        homes / "shared" / runtime.name,
                    ]
                    if path.is_dir()
                )
                if self.module.own:
                    yield Home(
                        runtime=runtime.name,
                        path=records.own.expanduser(),
                        whose="operator",
                        records=records,
                    )
                    yield Home(
                        runtime=runtime.name,
                        path=self.data.path / KEPT / runtime.name,
                        whose="kept",
                        records=records,
                    )
                if archive is not None:
                    yield from (
                        Home(
                            runtime=runtime.name,
                            path=path,
                            whose="archive",
                            records=records,
                        )
                        for path in archived(archive, runtime.name)
                    )

        return list(each())

    def kept(self) -> None:
        """Copy what the operator's own records added since into lup's copy of them, so a runtime's cleanup can't lose them."""
        if not self.module.own:
            return
        for runtime in self.declared.held(Runtimes):
            records: Records = runtime.records
            own = records.own.expanduser()
            if own.is_dir():
                copied(records, own, self.data.path / KEPT / runtime.name)

    async def caught_up(self) -> None:
        """Read what was added since the index was last caught up: each record's new lines, the second lup's ledger where it changed, and the inbox's new items."""
        index = self.opened()
        self.kept()
        index.caught_up(self.homes())
        if self.module.ledger is not None:
            index.ledger_caught_up(
                self.module.ledger.expanduser(), self.data.path / LEDGER_COPY
            )
        said = await Inboxes.said(Since(after=index.inbox_after()))
        index.inbox_caught_up(said)

    @lup.on(Stopping)
    async def closed(self, stopping: Stopping) -> None:
        """Close the index."""
        del stopping
        if self.index is not None:
            self.index.close()

    def opens(self) -> Opens:
        """Return the views a block opens."""
        return Opens(show=Transcribing.show)

    @lup.view
    async def sessions(self, listing: Listing) -> Blocks:
        """List the conversations kept, the latest first.

        List the conversations kept on the machine, the latest first: each with its
        name, when it last moved, where it ran, and how often the operator spoke in it.
        """
        await self.caught_up()
        return listed_blocks(self.opened().listed(listing), self.opens())

    @lup.view
    async def show(self, showing: Showing) -> Blocks:
        """Show a conversation, or what was said around a step.

        Show a conversation: the operator's words, each after the agent's last words
        before them; or what was said around a step; or, `--whole`, every step.
        """
        await self.caught_up()
        index = self.opened()
        named = index.named_by(showing.session, showing.subagent)
        match named:
            case [conversation]:
                return shown_blocks(index.shown(conversation, showing), showing)
            case []:
                message = f"no conversation kept is `{showing.session}`"
                raise RefusedError(message)
            case _:
                listed = ", ".join(
                    f"{each.runtime} {each.session} ({each.title or 'untitled'})"
                    for each in named
                )
                message = f"`{showing.session}` names several conversations: {listed}"
                raise RefusedError(message)

    @lup.view
    async def search(self, searching: Searching) -> Blocks:
        """Find each time words were said, the latest first.

        Find each time words were said, the operator's by default, each under what it
        answered, the latest first: in every session's record and in what was said
        through lup.
        """
        await self.caught_up()
        found = self.opened().searched(searching)
        return searched_blocks(found, self.opens(), whole=searching.whole)


class Telling(Part):
    """What a session is told of past sessions: that they're searchable, and how."""

    @lup.guidance
    async def past(self) -> Template:
        """Tell a session where past sessions are, and how to find what the operator said."""
        return told()


def told() -> Template:
    """Return what a session is told of past sessions."""
    return t"""## Past sessions

Every session on this machine is kept and searchable, every project's, on both runtimes, with what the operator said through lup: their reviews, answers and comments, in the second lup's ledger and in this lup's inbox. The operator's words hold the reasons for the work's shape, so before designing something, read what they said about it, and what was already proposed:
- `lup transcripts search <words>`: each time the operator said all of them, a word matching any word it starts, each under what it answered, the latest first. `--by agent` searches agents' proposals and last words of each turn instead, `--by tools` calls and what they returned, `--by any` everything; `--under <path>`, `--since`, `--until` and `--limit` narrow it, and `--whole` shows all of what each hit answered.
- `lup transcripts show <session>`: the operator's words in one session, each after the agent's last words before them; `--at <step>` what was said around a hit, `--whole` every step.
- `lup transcripts sessions`: every session kept, the latest first.

What you read there is what was said then, not a decision for now: where the operator's view matters, ask them.
"""


def archived(archive: Path, runtime: str) -> list[Path]:
    """Return each home the second lup's copies keep of `runtime`'s records: every repository's, and every related repository's beside it, from each home it was kept from."""
    return sorted(
        path
        for pattern in [f"*/{runtime}/*", f"*/related/*/{runtime}/*"]
        for path in archive.glob(pattern)
        if path.is_dir() and path.name in ("host", "rooms", "shared")
    )


class Transcripts(Module):
    """Every session's record, searched.

    Every session's record on the machine, both runtimes', read where the runtimes keep
    it, indexed with what the operator said through lup, and searched: what the operator
    said, and what it answered.
    """

    name = "transcripts"
    homes: Path = HOMES
    """The rooms' history homes, from the operator's home with `~`."""
    own: bool = True
    """Whether the operator's own runtime directories are read, and copied so a
    runtime's cleanup can't lose them, where each runtime keeps them
    (`Records.own`)."""
    archive: Path | None = ARCHIVE
    """The copies the second lup kept of every session's record, read and never
    written; none to leave them out."""
    ledger: Path | None = LEDGER
    """The second lup's ledger, read and never written; none to leave it out."""
    folds: Folds = Folds.of(*FOLDS)
    """A search's hit, a conversation listed, and a run of calls."""
    parts: Parts = Parts.of(Transcribing, Telling, TranscriptsPromises)
