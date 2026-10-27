"""Where a runtime keeps each session's record on this machine, as lup finds the ones of a repository.

Each runtime keeps its sessions' records in its own home, laid out its own way,
so only its adapter knows where they are and which session ran where. Given the
directories a repository's sessions run in, `Records.kept` answers which of the
runtime's records are theirs: each a file or a directory, and where it goes in a
copy, so a copy keeps the runtime's own layout. A record's session is read off
the record itself, the directory it says it ran in, never guessed from where the
runtime filed it.
"""

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, JsonValue, ValidationInfo, field_validator

from lup.types import JsonObject, Model


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

    @abstractmethod
    def conversation(self, session: str, agent: str | None) -> Path | None:
        """Return the record of one conversation as the runtime keeps it, growing while it runs: session `session`'s own, or its subagent `agent`'s; none where there's none."""


class Said(Model):
    """Something said in a session: the operator's words, or the agent's."""

    kind: Literal["said"] = "said"
    by: Literal["operator", "agent"]
    text: str
    at: datetime | None = None


class Called(Model):
    """A tool the agent called, by its runtime's name for it, and what the call did, in a line."""

    kind: Literal["called"] = "called"
    tool: str
    gist: str | None = None
    """What the call did, in a line, read from its input by its runtime's
    reader: a command's description or the command, the file read or written, a
    search's pattern, else its first argument; none where its input says
    nothing. The input and what the call returned are read whole on asking
    (`Reader.calls`), so a conversation read at each hook carries a line a
    call."""
    id: str | None = None
    """The runtime's id for the call, where its record keeps one: what an inbox
    item made by the call is anchored to, and what reads the call whole."""
    at: datetime | None = None


class Call(Model):
    """One call whole, as its runtime recorded it: its input, and what it returned."""

    id: str
    input: JsonValue
    """Its arguments as the agent wrote them: an object of them, or the text a
    tool taking text was given, as a patch or a cell of code."""
    output: str | None = None
    """What the call returned, whole, as the agent was given it, or as the
    runtime kept it beside the record where it gave the agent only its start;
    none while the call runs, or where the record keeps none."""
    failed: bool = False
    """Whether the runtime recorded the call as failed."""


type Entry = Annotated[Said | Called, Field(discriminator="kind")]
"""One step of a session, in order: something said, or a tool called."""


class Usage(Model):
    """What a conversation's context holds, as its runtime last recorded a reply: the tokens in use, and the window they're in where it's known."""

    used: int
    """The tokens in the context at the last reply: its input, the cached part
    of it included, and on a runtime that counts it the output it added."""
    window: int | None = None
    """The model's context window, in tokens; none where it isn't known, or
    where fewer tokens fit in it than are in use (`holding`)."""
    model: str | None = None
    """The model, as the record names it."""

    @field_validator("window")
    @classmethod
    def holding(cls, window: int | None, info: ValidationInfo) -> int | None:
        """Return the window, or none where it's smaller than the tokens in use: a context never holds more than its window, so that window was read wrong (#282), and shown it would read as a context past full.

        >>> Usage(used=269_000, window=200_000).window, Usage(used=112_000, window=1_000_000).window
        (None, 1000000)
        """
        match info.data:
            case {"used": int() as used} if window is not None and used > window:
                return None
            case _:
                return window


type Status = Literal["pending", "in_progress", "completed"]
"""Where an entry of a task list stands: both runtimes name the three states
so."""


class Task(Model):
    """One entry of a conversation's task list, as its runtime keeps it."""

    id: str
    subject: str
    status: Status
    active: str | None = None
    """What the entry says while it's in progress, where the runtime keeps a
    present-tense form of it beside the subject; none where it keeps none."""


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
    usage: Usage | None = None
    """What its context held at its last reply; none where the record says
    nothing of it."""
    tasks: list[Task] = []
    """Its task list as it stands at the record's end, replayed from the calls
    that wrote it; empty where it keeps none."""

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

    @abstractmethod
    def calls(self, record: Path, ids: list[str]) -> list[Call]:
        """Read calls of one conversation's record whole, by the runtime's ids for them: each the record holds, in the order asked."""


class Recorded(Model, arbitrary_types_allowed=True):
    """A runtime's records on this machine, and how they're read: what reads a conversation's record without naming the runtime."""

    records: Records
    reader: Reader


type Queuing = Literal["typed", "task", "subagent", "message"]
"""What a runtime holds for a conversation while its call runs: the operator's
words typed in its terminal, and anything the record doesn't say is another's,
so it's never taken for less; a task the conversation started in the
background, a command ending or a Monitor's event; a subagent it started ending,
or its report; another session's message."""


class Queued(Model):
    """Something a runtime holds for one conversation of a session, which it hands the agent once its running call returns, as the session's record says while it runs."""

    id: str
    """Which it is, as the runtime's record places it, so it's told once."""
    kind: Queuing
    summary: str | None = None
    """What the runtime says it is, in a line, where it says: a command's end
    and its exit code, a Monitor's event, a subagent finishing; none for the
    operator's words, which the agent reads whole from the runtime."""


class Queues(ABC):
    """What a runtime holds queued for each conversation of its sessions on this machine, read from their records as they grow."""

    @abstractmethod
    def queued(self, session: str, agent: str | None) -> list[Queued]:
        """Return what the runtime holds for session `session`'s own conversation, or for its subagent `agent`, to hand it once its running call returns, oldest first; none where nothing is, or the session's record isn't on this machine.

        Each look reads only what the records gained since the last.
        """


def gist(value: JsonValue, width: int = 160) -> str | None:
    r"""Say `value` in a line, as a call's gist says what it did: a string's first line with words in it, any other value as JSON; cut at `width` characters, marked `…`, where it's longer; none where it says nothing.

    The call's input is kept whole beside it (`Reader.calls`), so a cut line
    points at the whole rather than standing for it.

    >>> gist("cd /w\nuv run pytest")
    'cd /w'
    >>> gist({"a": 1}), gist(""), gist(None)
    ('{"a": 1}', None, None)
    >>> gist("x" * 9, width=4)
    'xxxx…'
    """
    match value:
        case None:
            return None
        case str():
            said = next(
                (line.strip() for line in value.splitlines() if line.strip()), ""
            )
        case _:
            said = json.dumps(value, ensure_ascii=False)
    if said == "":
        return None
    if len(said) <= width:
        return said
    # lup: ignore("string-slice", why="a gist's line cut for the page to show, marked, the call's input kept whole and read when its fold opens")
    return f"{said[:width]}…"


def first(arguments: JsonObject) -> JsonValue:
    """Return a call's first argument, as its input names them in order; none where it has none.

    >>> first({"pattern": "def ", "path": "src"}), first({})
    ('def ', None)
    """
    return next(iter(arguments.values()), None)


def within(directory: Path, under: list[Path]) -> bool:
    """Say whether `directory` is one of `under`, or inside one.

    >>> within(Path("/w/lup.git/tree/dev"), [Path("/w/lup.git")])
    True
    >>> within(Path("/w/other"), [Path("/w/lup.git")])
    False
    """
    return any(directory.is_relative_to(each) for each in under)
