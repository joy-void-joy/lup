"""Where a runtime keeps each session's record on this machine, as lup finds the ones of a repository.

Each runtime keeps its sessions' records in its own home, laid out its own way,
so only its adapter knows where they are and which session ran where. Given the
directories a repository's sessions run in, `Records.kept` answers which of the
runtime's records are theirs: each a file or a directory, and where it goes in a
copy, so a copy keeps the runtime's own layout. A record's session is read off
the record itself, the directory it says it ran in, never guessed from where the
runtime filed it.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import Field

from lup.types import Model


class Record(Model):
    """One of a runtime's records: a file or a directory it keeps, and where it goes in a copy."""

    source: Path
    place: PurePosixPath
    """Where it goes, under the copy of the runtime's records: its path in the
    runtime's own home."""


class Records(ABC):
    """A runtime's records of its sessions on this machine."""

    @abstractmethod
    def kept(self, under: list[Path]) -> list[Record]:
        """Return each record of a session the runtime ran in one of `under`, or in a directory inside one."""


class Said(Model):
    """Something said in a session: the operator's words, or the agent's."""

    kind: Literal["said"] = "said"
    by: Literal["operator", "agent"]
    text: str
    at: datetime | None = None


class Called(Model):
    """A tool the agent called, by its runtime's name for it."""

    kind: Literal["called"] = "called"
    tool: str
    at: datetime | None = None


type Entry = Annotated[Said | Called, Field(discriminator="kind")]
"""One step of a session, in order: something said, or a tool called."""


class Transcript(Model):
    """One session as it was recorded: who said what, and the tools called between, in order."""

    runtime: str
    session: str
    """The runtime's id for the session."""
    title: str | None = None
    """Its name, as the operator or lup gave it, or the runtime's own title;
    none where it has none."""
    directory: Path | None = None
    """Where it ran, as its record says."""
    entries: list[Entry] = []

    def started(self) -> datetime | None:
        """Return when its first timed step happened; none where none is timed."""
        timed = [each.at for each in self.entries if each.at is not None]
        return min(timed) if timed else None

    def operators(self) -> list[Said]:
        """Return what the operator said, in order."""
        return [
            each
            for each in self.entries
            if isinstance(each, Said) and each.by == "operator"
        ]

    def replied(self, said: Said) -> Said | None:
        """Return what the agent last said before `said`: what the operator was answering; none where the agent had said nothing yet."""
        before = self.entries[: self.entries.index(said)]
        agents = [
            each for each in before if isinstance(each, Said) and each.by == "agent"
        ]
        return agents[-1] if agents else None


class Reader(ABC):
    """A runtime's records of its sessions, read: which of a copy's files are sessions, and what was said in each."""

    @abstractmethod
    def sessions(self, copies: Path) -> list[Path]:
        """Return the record of each session under `copies`, laid out as the runtime lays out its own home; none where there's nothing there."""

    @abstractmethod
    def read(self, record: Path) -> Transcript:
        """Read one session's record: what was said, the tools called, its name and where it ran.

        Lines the runtime writes that this doesn't know are passed over.
        """


def within(directory: Path, under: list[Path]) -> bool:
    """Say whether `directory` is one of `under`, or inside one.

    >>> within(Path("/w/lup.git/tree/dev"), [Path("/w/lup.git")])
    True
    >>> within(Path("/w/other"), [Path("/w/lup.git")])
    False
    """
    return any(directory.is_relative_to(each) for each in under)
