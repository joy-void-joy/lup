"""The demo's records: each conversation's as it stands, written where the host's handlers and each module's views read it.

`docs/dashboard.md`, *The demo*. No runtime runs behind the demo, so each runtime's
records are files the demo writes as each conversation stands, as they're asked
for, and reads back as written (`StandInRecords`, `StandInReader`), by the host's
own handlers (`ShowConversation`, `ShowContext`) and by each module's own views
alike. So the page draws the view the real module answers, its layout, its fold
kinds and its tones, and an item's moment as the host reads it, over the demo's
data.
"""

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import override

from lup.types import Model
from lup_dev.host.homes import Found
from lup_dev.host.records import Call, Reader, Record, Records, Transcript


class StoodIn(Model):
    """A stand-in conversation's record as the demo writes it: what it holds, and each of its calls read whole."""

    transcript: Transcript
    calls: list[Call] = []


class StandInRecords(Model, Records):
    """One runtime's records of the demo's conversations, each a file under `directory`, written as it stands each time it's asked for."""

    runtime: str
    directory: Path
    stands: Callable[[str, str, str | None], StoodIn]
    """Says how a conversation stands, by their runtime's name and ids."""

    @override
    def kept(self, under: list[Path], repository: Path) -> list[Record]:
        return []

    @override
    def held(self, session: str) -> bool:
        return False

    @override
    def conversation(self, session: str, agent: str | None) -> Found | None:
        """Write the record of `session`, or of their subagent `agent`, as it stands, in one step, so a read on another thread reads it whole, and return where it is."""
        record = self.place(session, agent)
        stood = self.stands(self.runtime, session, agent)
        record.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=record.parent, prefix=f".{record.name}.", delete=False
        ) as partial:
            partial.write(stood.model_dump_json())
        Path(partial.name).replace(record)
        return Found(record=record, root=self.directory)

    def place(self, session: str, agent: str | None) -> Path:
        """Return where the record of `session`, or of their subagent `agent`, is written."""
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
