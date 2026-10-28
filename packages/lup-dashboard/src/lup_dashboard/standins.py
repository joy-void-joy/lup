"""The demo's views: each module's own view, laid out by its own code, over the demo's stand-in records and items.

`docs/dashboard.md`, *The page*, its demo. Only `lup_dev` imports a module's
environment side, so the demo makes each repository's modules as the
repository's process does (`RepositoryModules`), from lup's default
declaration, and asks them each view as the host would (`Viewing`). What a
module reads is stood in for: each runtime's records are files the demo writes
as its conversations stand, read back as written (`StandInRecords`,
`StandInReader`), and the items a conversation exchanged are the demo's
(`StandInExchanges`). So the page draws the view the real module answers, its
layout, its fold kinds and its tones, over the demo's data.
"""

from collections.abc import Callable
from functools import cached_property
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, override

from pydantic import Field

from lup.types import Model, MutableModel
from lup_dev import Project
from lup_dev.declaration.resolve import Resolved, resolve
from lup_dev.host.homes import Found
from lup_dev.host.records import Call, Reader, Record, Recorded, Records, Transcript
from lup_dev.inbox.exchanges import Exchanges
from lup_dev.inbox.protocol import Exchanged
from lup_dev.inbox.store import Conversation
from lup_dev.layout import Layout
from lup_dev.worker import RepositoryModules

if TYPE_CHECKING:
    from lup.blocks import OfAgent
    from lup_dev.host.protocol import Looks
    from lup_dev.host.workers import Viewed, Viewing


class StoodIn(Model):
    """A stand-in conversation's record as the demo writes it: what it holds, and each of its calls read whole."""

    transcript: Transcript
    calls: list[Call] = []


class StandInRecords(Model, Records):
    """One runtime's records of the demo's conversations, each a file under `directory`."""

    directory: Path

    @override
    def kept(self, under: list[Path], repository: Path) -> list[Record]:
        return []

    @override
    def held(self, session: str) -> bool:
        return False

    @override
    def conversation(self, session: str, agent: str | None) -> Found | None:
        record = self.place(session, agent)
        return Found(record=record, root=self.directory) if record.is_file() else None

    def place(self, session: str, agent: str | None) -> Path:
        """Return where the record of `session`, or of its subagent `agent`, is written."""
        return self.directory / session / f"{agent or session}.json"


class StandInReader(Model, Reader):
    """Reads a stand-in record as the demo wrote it."""

    @override
    def sessions(self, copies: Path) -> list[Path]:
        return []

    @override
    def read(self, record: Path, root: Path | None = None) -> Transcript:
        return StoodIn.model_validate_json(record.read_text()).transcript

    @override
    def calls(
        self, record: Path, ids: list[str], root: Path | None = None
    ) -> list[Call]:
        wholes = {
            each.id: each
            for each in StoodIn.model_validate_json(record.read_text()).calls
        }
        return [wholes[each] for each in ids if each in wholes]


class StandInExchanges(Model, Exchanges, arbitrary_types_allowed=True):
    """The demo's items a conversation of one repository exchanged."""

    repository: Path
    exchanged_by: Callable[[Conversation], Exchanged]

    @override
    async def exchanged(self, viewed: OfAgent) -> Exchanged:
        return self.exchanged_by(
            Conversation(
                repository=self.repository,
                runtime=viewed.runtime,
                session=viewed.session,
                agent=viewed.agent,
            )
        )


class StandInViews(MutableModel, arbitrary_types_allowed=True):
    """Each repository's modules, made as its process makes them from lup's default declaration, over the demo's records, written in a directory of their own for as long as the demo runs, and its items."""

    runtimes: list[str]
    """The runtimes whose records the views read, by name."""
    exchanged: Callable[[Conversation], Exchanged]
    """The demo's items a conversation exchanged."""
    resolved: Resolved = Field(default_factory=lambda: resolve(Project()))
    kept: TemporaryDirectory[str] = Field(default_factory=TemporaryDirectory)
    """Where the records are written, removed as the demo ends."""
    made: dict[Path, RepositoryModules] = {}
    """Each repository's modules, by its git directory, once asked."""

    @cached_property
    def directory(self) -> Path:
        """Where the records and the modules' own data are."""
        return Path(self.kept.name)

    def records(self, runtime: str) -> StandInRecords:
        """Return `runtime`'s records."""
        return StandInRecords(directory=self.directory / "records" / runtime)

    def record(self, of: OfAgent, transcript: Transcript, calls: list[Call]) -> None:
        """Write the record of the conversation `of` names, as it stands."""
        place = self.records(of.runtime).place(of.session, of.agent)
        place.parent.mkdir(parents=True, exist_ok=True)
        place.write_text(StoodIn(transcript=transcript, calls=calls).model_dump_json())

    def modules(self, repository: Path) -> RepositoryModules:
        """Return `repository`'s modules, made once."""
        found = self.made.get(repository)
        if found is not None:
            return found
        reader = StandInReader()
        made = RepositoryModules(
            repository=repository,
            resolved=self.resolved,
            recorded={
                runtime: Recorded(records=self.records(runtime), reader=reader)
                for runtime in self.runtimes
            },
            layout=Layout(state=self.directory, data=self.directory / "data"),
            exchanges=StandInExchanges(
                repository=repository, exchanged_by=self.exchanged
            ),
        )
        self.made = {**self.made, repository: made}
        return made

    async def view(self, viewing: Viewing) -> Viewed:
        """Answer the view as the repository's process would.

        Raise `LupDevError` where it can't, as the process does.
        """
        return await self.modules(viewing.repository).view(viewing)

    def looks(self) -> Looks:
        """Return how the modules' views look."""
        return self.resolved.looks
