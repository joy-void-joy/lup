"""What every channel shares: who may write, and what a read yields.

A channel stores the consumer's own record verbatim. Attribution that
belongs to the decision — which door, under what id, answering what — is the
consumer's to model, because only the consumer knows which of those its
records mean. What the channel owns is the part no consumer can enforce for
itself: which doors it accepts at all.
"""

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

FROZEN = ConfigDict(frozen=True)


class ChannelConflictError(RuntimeError):
    """A write contradicted a record the channel already holds."""


class ChannelCorruptionError(RuntimeError):
    """A channel file could not be read as the record it should hold."""


class ChannelOverflowError(RuntimeError):
    """A capped stream reached its ceiling because nobody is consuming it."""


class Door(StrEnum):
    """Which surface a write came through.

    Attribution is not decoration. Some decisions are a human's to take, and
    naming the doors a channel refuses is the only way to say so
    structurally — an orchestrating agent then cannot write the record that
    would release its own run.
    """

    FLAG = "flag"
    PAGE = "page"
    CONSOLE = "console"
    AGENT = "agent"


class DoorPolicy(BaseModel):
    """Which doors a channel refuses, named as refusals rather than a roster.

    Stating it negatively is what makes the guarantee legible: a resume slot
    excludes ``AGENT``, so the orchestrator physically cannot write the
    record that would release its own run. A roster of allowed doors says the
    same thing and reads as an accident of enumeration.
    """

    model_config = FROZEN

    excluded: list[Door] = Field(default_factory=list)

    def accepts(self, door: Door) -> bool:
        return door not in self.excluded


class Offset[T](BaseModel):
    """One stream record and the offset that consumes exactly it.

    Committing per record is what keeps a crash between two of them from
    dropping the one that had not been applied yet.
    """

    model_config = FROZEN

    item: T
    commit_offset: int


def publish_atomic(path: Path, record: BaseModel) -> None:
    """Write one record so no reader can ever observe it half-written.

    Every channel publishes this way, and so does anything else in a run
    directory that a door may read while the run is writing it. A reader
    holds no lock, so the rename is the whole guarantee.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        record.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    temporary.replace(path)  # lup: ignore[string-replace] — atomic Path rename


def utc_now() -> datetime:
    return datetime.now(UTC)
