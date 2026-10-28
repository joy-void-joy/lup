"""Where a runtime keeps each session's record on this machine, as lup finds the ones of a repository.

Each runtime keeps its sessions' records in its own home, laid out its own way,
so only its adapter knows where they are and which session ran where. A
runtime has several homes here (`homes`): the operator's own directory, and the
homes of the rooms' own, the repository's and the one every project's rooms
share. Given the directories a repository's sessions run in, `Records.kept`
answers which of the runtime's records in each are theirs: each a file or a
directory, the home it's in and whose that is, and where it goes in a copy, so
a copy keeps the runtime's own layout under each home. A record's session is
read off the record itself, the directory it says it ran in, never guessed from
where the runtime filed it; where the runtime files by directory, a record
filed where that directory's never would be isn't taken for its.

A room writes a home of the rooms' own, and wrote the operator's directory
while rooms mounted it, so what the host reads there is data alone, read as
the host reads a worktree's file (`lup_dev.confined`): a record only where it's
reached from its home without a link and resolves inside its folder, a regular
file, never waited on as a pipe would be, and its first lines only where that's
all that's wanted (`head`).
"""

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, JsonValue, ValidationInfo, field_validator

from lup.blocks import Drawer, Tone, Verb
from lup.types import JsonObject, Model
from lup_dev.confined import Confined

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lup_dev.layout import HomesLayout

type Whose = Literal["host", "rooms", "shared"]
"""Whose home a runtime keeps a record in: `host`, the operator's own
directory; `rooms`, the home a repository's rooms keep theirs in; `shared`,
the one every project's rooms share, where their profile chooses it
(`HomesLayout`). A room writes the last two, so what a record kept there says
is a room's word."""


class Home(Model):
    """One of the homes a runtime keeps its records in on this machine: its directory, and whose it is."""

    directory: Path
    whose: Whose


def homes(
    own: Path, rooms: HomesLayout | None, repository: Path, runtime: str
) -> list[Home]:
    """Return each home runtime `runtime` keeps the records of the repository whose git directory is `repository` in: the operator's own directory, `own`, then, where `rooms` places the rooms' own homes, the repository's and the one every project shares.

    >>> from lup_dev.layout import HomesLayout
    >>> [(each.whose, str(each.directory)) for each in homes(Path("/o"), HomesLayout(home=Path("/h")), Path("/r.git"), "agent")][::2]
    [('host', '/o'), ('shared', '/h/shared/agent')]
    """
    if rooms is None:
        return [Home(directory=own, whose="host")]
    return [
        Home(directory=own, whose="host"),
        Home(directory=rooms.project(repository, runtime), whose="rooms"),
        Home(directory=rooms.shared(runtime), whose="shared"),
    ]


def reached(home: Path, path: Path) -> bool:
    """Say whether `path`, inside `home`, is there and reached from it without a link: none of its parts below `home` is one, while what's above it, the operator's own, may be.

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as scratch:
    ...     home = Path(scratch)
    ...     (home / "projects").mkdir()
    ...     (home / "linked").symlink_to(home / "projects")
    ...     [reached(home, home / each) for each in ["projects", "linked", "missing"]]
    [True, False, False]
    """
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return False
    return resolved == home.resolve() / path.relative_to(home)


def head(file: Path, reach: int = 4 * 1024 * 1024) -> Iterator[str]:
    """Yield the lines of the first `reach` bytes of the record `file`, as text, a byte that isn't UTF-8 replaced, each as it's read, where it's a regular file resolving inside its folder (`Confined`); none where it isn't.

    A room may have written it, so it's read only so far: a line with no end
    would take the host's memory, where what's read of a record's head, the
    directory its session ran in, is on its first few lines, and a reader
    stops at the line it wants. The last line may be cut at `reach`, and then
    reads as no line a runtime writes.
    """
    with Confined(root=file.parent).opened(Path(file.name)) as reading:
        if reading is None:
            return
        left = reach
        while left > 0 and (line := reading.readline(left)):
            left -= len(line)
            yield line.decode(errors="replace")


if TYPE_CHECKING:
    from lup_dev.host.homes import Found


class Record(Model):
    """One of a runtime's records: a file or a directory it keeps in one of its homes, and where it goes in a copy of that home's records."""

    home: Path
    """The directory of the home it's kept in."""
    whose: Whose
    """Whose home that is: what a copy keeps it under, and says of it."""
    place: PurePosixPath
    """Its path in that home, as the runtime lays it out: where it goes under
    the copy of that home's records."""

    @property
    def source(self) -> Path:
        """Where it is on this machine."""
        return self.home / self.place


class Records(ABC):
    """A runtime's records of its sessions on this machine."""

    @abstractmethod
    def kept(self, under: list[Path], repository: Path) -> list[Record]:
        """Return each record of a session the runtime ran in one of `under`, or in a directory inside one, from each of its homes keeping the records of the repository whose git directory is `repository` (`homes`).

        Read as data alone: a record only where it's reached from its home
        without a link (`reached`), its head only as far as `head` reads.
        """

    @abstractmethod
    def conversation(self, session: str, agent: str | None) -> Found | None:
        """Return the record of one conversation as the runtime keeps it, growing while it runs, session `session`'s own or their subagent `agent`'s, with the directory it's read inside; none where there's none.

        A launched session's is in the home its launch registered alone, and
        any other's in the operator's own directory alone (`lup_dev.host.homes`).
        """

    @abstractmethod
    def held(self, session: str) -> bool:
        """Say whether the operator's own directory holds a record of session `session`: a session of theirs, which no launch's home may claim (`lup_dev.host.homes.kept`)."""


class Said(Model):
    """Something said in a session: the operator's words, or the agent's."""

    kind: Literal["said"] = "said"
    by: Literal["operator", "agent"]
    text: str
    at: datetime | None = None


class Called(Model):
    """A tool the agent called, by their runtime's name for it, and what the call did, in a line."""

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
    """What a conversation's context holds, as their runtime last recorded a reply: the tokens in use, and the window they're in where it's known."""

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
    """One entry of a conversation's task list, as their runtime keeps it."""

    id: str
    subject: str
    status: Status
    active: str | None = None
    """What the entry says while it's in progress, where the runtime keeps a
    present-tense form of it beside the subject; none where it keeps none."""


TASKS_DRAWER = Drawer(letter="t", called="the tasks", colour="link")
"""Where the dashboard shows an agent's task list, as their runtime keeps it: a
drawer of the runtime adapters', under each agent's banner, its view `tasks`.
Its view is the page's own until the adapters are a module of their own (#113,
step 4); the core's looks place it (`lup_dev.declaration.looks`)."""
TASK_TONE = Tone(name="task", like="plain")
"""A line of an agent's task list in their drawer, each entry marked done, in
progress or to do."""
PAUSE = Verb(name="pause", key="p", called="pause")
"""The runtime adapters' verb: pausing an agent, which their banner will offer
once its host side is designed (#157). `Core` declares it until the adapters
are a module (#113, step 4), so a person's layer may give it another key."""


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
    def read(self, record: Path, root: Path | None = None) -> Transcript:
        """Read one session's record: what was said, the tools called, its name and where it ran.

        Lines the runtime writes that this doesn't know are passed over, and so
        is one too long to hold. With `root`, the directory a room may have
        written the record in, the record and what's read beside it are read
        only where, opened, they're inside it (`lup.rooms.homes.opened`).
        """

    @abstractmethod
    def calls(
        self, record: Path, ids: list[str], root: Path | None = None
    ) -> list[Call]:
        """Read calls of one conversation's record whole, by the runtime's ids for them: each the record holds, in the order asked; confined to `root` as `read` is."""


class Recorded(Model, arbitrary_types_allowed=True):
    """A runtime's records on this machine, and how they're read: what reads a conversation's record without naming the runtime."""

    records: Records
    reader: Reader


type Queuing = Literal["typed", "task", "subagent", "message"]
"""What a runtime holds for a conversation while their call runs: the operator's
words typed in their terminal, and anything the record doesn't say is another's,
so it's never taken for less; a task the conversation started in the
background, a command ending or a Monitor's event; a subagent they started
ending, or reporting; another session's message."""


class Queued(Model):
    """Something a runtime holds for one conversation of a session, which it hands the agent once their running call returns, as the session's record says while it runs."""

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
    def queued(
        self, session: str, agent: str | None, home: Path | None
    ) -> list[Queued]:
        """Return what the runtime holds for session `session`'s own conversation, or for their subagent `agent`, to hand them once their running call returns, oldest first; none where nothing is, or the session's record isn't on this machine, or isn't in `home`.

        `home` is the one the asking conversation's launch registered
        (`Register.home`), where its runtime keeps its own sessions' records:
        a hook's payload, which a room writes, names the session, so a room
        can name a host session's or another project's room's, whose record
        is elsewhere. None, for a launch from before launches kept their home,
        reads the record wherever it's found. Each look reads only what the
        records gained since the last.
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
