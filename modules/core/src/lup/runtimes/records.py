"""A conversation as its runtime's record keeps it, read as lup's own model: what was said and by whom, and each call with what it returned.

A runtime writes a record of every conversation it holds, a line of JSON at a
time, and only ever adds to it: Claude Code a `.jsonl` file for a session and
one for each subagent, Codex a rollout for each thread. Each runtime's reader
(`Records`, filled in its own module) finds the records in one of its homes, or
in a copy kept of one, which keeps its layout, and reads a record into steps, in
the order the record has them, from where an earlier read stopped. So a record
is never read whole again as it grows, and whoever reads conversations reads
them in one shape, whichever runtime held them.

A record is the room's to write, so it's read where a link planted in it
reaches nothing of the operator's: in a container, never on the machine itself.
"""

import hashlib
import os
import stat
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Annotated, BinaryIO, Literal
lazy from collections.abc import Iterator

from pydantic import AwareDatetime, Field, JsonValue

from lup.types import JsonObject, Model

type Speaker = Literal["operator", "agent", "lup", "conversation", "runtime"]
"""Who said something in a conversation: the operator, in the runtime's own
terminal; the agent; lup, writing into the session as it holds it (a turn it
started, a hook's context); another conversation, a subagent's parent briefing
them or a peer's message; or the runtime itself (an interruption, a command's
output, a compaction's summary)."""


class Place(Model):
    """Where a step is in its record: the line holding it, by the byte that line starts at, and its place among the steps that line holds.

    A record only grows, so a step's place never moves: it's how a step is
    named from one read to the next.
    """

    line: Annotated[int, Field(ge=0)]
    index: Annotated[int, Field(ge=0)] = 0


class Step(Model):
    """One thing in a conversation, as its record has it: where it is, when, and the runtime's own id for it."""

    kind: str
    place: Place
    at: AwareDatetime | None = None
    """When the runtime wrote it; none where its line doesn't say."""
    key: str | None = None
    """The runtime's own id for the step, where it gives one: the same on a
    fork's copy of a parent's line as on the parent's, so a reader can tell the
    history a fork carries from what it adds."""


class Said(Step):
    """Words said in the conversation, and who said them."""

    kind: Literal["said"] = "said"
    by: Speaker
    text: str
    queued: bool = False
    """Whether they were sent while the agent worked, to reach them at their
    next call rather than as a turn of their own."""


class Called(Step):
    """A tool called: the runtime's id for the call, the tool as lup's events name it, and what it was given."""

    kind: Literal["called"] = "called"
    call: str
    """The runtime's id for the call, the one its hooks carry, which its
    result names."""
    tool: str
    """The tool, named as the runtime's hooks name it, and lup's events with
    them: `mcp__lup__ask`, a server's tool, on every runtime."""
    given: JsonValue = None
    within: str | None = None
    """The call it ran inside, where a tool calls tools: Codex's code mode, whose
    `exec` cell calls each tool the model asks for."""


class Returned(Step):
    """What a call returned, whole: its text, each part that isn't text named where it stood."""

    kind: Literal["returned"] = "returned"
    call: str
    output: str
    failed: bool | None = None
    """Whether the call failed, where the runtime says; none where it doesn't."""


class Refused(Step):
    """A call refused before it ran, by a hook answering for lup: what it returned says why."""

    kind: Literal["refused"] = "refused"
    call: str


class Ended(Step):
    """The agent's turn ended: their last words said, or the turn cut short."""

    kind: Literal["ended"] = "ended"
    interrupted: bool = False


class Compacted(Step):
    """The conversation went on from a summary of itself: what came before is out of what the agent reads from here on."""

    kind: Literal["compacted"] = "compacted"


class Titled(Step):
    """The conversation was named: by the operator or lup, by the runtime for its agent, or guessed by the runtime from what was said."""

    kind: Literal["titled"] = "titled"
    title: str
    how: Literal["named", "agent", "guessed"]
    """Who named it: `named` is the operator's or lup's own name for it, which
    wins over the others; `agent`, the runtime's name for its agent; `guessed`,
    a title the runtime made of what was said."""


class Forked(Step):
    """The conversation goes on from another's history, which its record names rather than copies."""

    kind: Literal["forked"] = "forked"
    session: str
    """The runtime's id for the session forked from."""
    through: str | None = None
    """The key of the last step of that session's the fork goes on from."""


class Continued(Step):
    """The conversation goes on in another record, under another id."""

    kind: Literal["continued"] = "continued"
    session: str


class Counted(Step):
    """How much of the model's context the conversation took at its latest request, of how much it holds."""

    kind: Literal["counted"] = "counted"
    used: Annotated[int, Field(ge=0)]
    """The tokens the request was made in."""
    window: Annotated[int, Field(ge=1)] | None = None
    """The tokens the model holds, where the record says."""
    model: str | None = None
    """The model, as the conversation asked for it where the record says, else
    as the runtime's API named it."""


class Task(Model):
    """One task of the agent's list: its id in the list, what it is, and where it stands."""

    id: str
    subject: str
    status: str
    """Where it stands, as the runtime says: `pending`, `in_progress`,
    `completed`."""
    active: str | None = None
    """What the agent says they're doing while it's under way."""


class Planned(Step):
    """The agent's task list as it stands, whole, after a change to it."""

    kind: Literal["planned"] = "planned"
    tasks: list[Task]


type Stepped = Annotated[
    Said
    | Called
    | Returned
    | Refused
    | Ended
    | Compacted
    | Titled
    | Forked
    | Continued
    | Counted
    | Planned,
    Field(discriminator="kind"),
]
"""Any step a record holds: the one its `kind` names."""


class Record(Model):
    """A record a runtime keeps of one conversation: where it is, whose conversation it is, and where it ran."""

    path: Path
    session: str
    """The runtime's id for the session: the conversation its operator, or
    lup, started, which a subagent's is part of."""
    conversation: str | None = None
    """The runtime's id for a subagent's conversation; none for the session's
    own."""
    spawner: str | None = None
    """The runtime's id for the subagent who spawned this one; none where the
    session's own conversation did, or for the session's own."""
    call: str | None = None
    """The spawner's call that spawned it, where the runtime says."""
    directory: Path | None = None
    """The directory it ran in, as its record first names one."""


class Reading(Model):
    """Where a read of a record stopped: the next read starts there."""

    offset: Annotated[int, Field(ge=0)] = 0
    """The bytes read: each whole line up to there."""
    begins: str | None = None
    """A digest of the record's first line, where a read reached the end of
    it: a record whose first line reads otherwise has been replaced, and is read
    again from its start."""
    carried: JsonObject = {}
    """What the runtime's reader carries from one read to the next, as its own
    model's JSON: a call still open whose result is yet to come, say."""


class Read(Model):
    """The steps a record added since an earlier read, and where this read stopped."""

    steps: list[Stepped]
    reading: Reading
    again: bool = False
    """Whether the record was replaced since the earlier read, or shrank, so
    these are its steps from its start rather than what it added."""


class Records(Model, ABC):
    """A runtime's records: finding them in one of its homes, and reading one into steps from where an earlier read stopped."""

    longest: Annotated[int, Field(ge=1)] = 64 * 2**20
    """The longest line read, in bytes: one longer is skipped as it's read,
    never held, since a record is the room's to write."""
    own: Path
    """The operator's own directory for the runtime, where the sessions they
    run outside lup keep their records: from their home with a leading `~`."""

    @abstractmethod
    def found(self, home: Path, under: list[Path] | None = None) -> list[Record]:
        """Return every record of a conversation in `home`, the runtime's own directory or a copy kept of one: of those that ran in a directory `under` one of these, where given.

        A record not readable as one of the runtime's is left out: a record is
        the room's to write, and may be anything.
        """

    @abstractmethod
    def read(self, record: Record, since: Reading | None = None) -> Read:
        """Read the steps `record` added since the read that stopped at `since`, or from its start.

        Only whole lines are read, a line still being written left for the next
        read, and a line no step could fit in skipped without being held.
        """

    @abstractmethod
    def beside(self, record: Record) -> list[Path]:
        """Return the files reading `record` reads beside it, such as a subagent's spawn or a call's output saved whole: what a copy of the record needs to be read as it is."""


class Line(Model):
    """A line of a record: the byte it starts at, how long it is, and its bytes, its newline among them; none where it was too long to hold."""

    start: Annotated[int, Field(ge=0)]
    length: Annotated[int, Field(ge=1)]
    text: bytes | None


class Lined(Model):
    """The whole lines a record added since an earlier read, and where this read stopped."""

    lines: list[Line]
    """Each whole line read, but those too long to hold."""
    end: Annotated[int, Field(ge=0)]
    """The byte after the last whole line read."""
    begins: str | None
    """A digest of the record's first line, where it's whole."""
    again: bool
    """Whether the record was read from its start, though an earlier read
    stopped further on: it shrank, or its first line changed."""


def opened(path: Path) -> BinaryIO:
    """Open the record at `path` to read: a regular file, reached without following a link at its last step and without waiting on a pipe.

    Raise `OSError` for anything else, which a room may have put in a record's
    place.
    """
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        message = f"{path} isn't a regular file"
        raise OSError(message)
    return os.fdopen(descriptor, "rb")


def lined(
    path: Path,
    since: Reading | None = None,
    longest: int = 64 * 2**20,
    chunk: int = 2**20,
) -> Lined:
    """Read the whole lines the record at `path` added since the read that stopped at `since`, or from its start.

    A line longer than `longest` bytes is skipped as it's read, `chunk` bytes at
    a time, never held whole, and the line still being written, which has no
    newline yet, is left for the next read. Where the record is shorter than
    `since` read, or its first line reads otherwise, it's read from its start,
    and `again` says so.
    """
    with opened(path) as record:
        first = record.readline(longest + 1)
        begins = hashlib.sha256(first).hexdigest() if first.endswith(b"\n") else None
        size = os.fstat(record.fileno()).st_size
        start = 0 if since is None else since.offset
        again = since is not None and (
            size < start or (since.begins is not None and since.begins != begins)
        )
        if again:
            start = 0
        record.seek(start)

        def read() -> Iterator[Line]:
            """Yield each whole line from `start`, one too long to hold without its text, and stop at a line still being written."""
            at = start
            while text := record.readline(longest + 1):
                if text.endswith(b"\n"):
                    yield Line(start=at, length=len(text), text=text)
                    at += len(text)
                    continue
                if len(text) <= longest:
                    return
                length = len(text)
                while (rest := record.readline(chunk)) and not rest.endswith(b"\n"):
                    length += len(rest)
                if not rest:
                    return
                yield Line(start=at, length=length + len(rest), text=None)
                at += length + len(rest)

        everything = list(read())
    end = everything[-1].start + everything[-1].length if everything else start
    lines = [each for each in everything if each.text is not None]
    return Lined(lines=lines, end=end, begins=begins, again=again)


def head(path: Path, reach: int = 4 * 2**20) -> Iterator[bytes]:
    """Yield each whole line of the record at `path` within its first `reach` bytes, where what it is and where it ran is said.

    A line reaching past `reach` ends it, so a record that's one long line
    costs no more than `reach` to look at.
    """
    with opened(path) as record:
        while (left := reach - record.tell()) > 0 and (
            text := record.readline(left)
        ).endswith(b"\n"):
            yield text


class Copied(Model):
    """What copying a home's records did: how many files it copied whole, and how many it added to."""

    whole: int = 0
    grown: int = 0


def copied(records: Records, home: Path, into: Path) -> Copied:
    """Copy every record in `home`, and the files reading each reads beside it, into `into` in the same layout: a record that grew has what it added appended to its copy, and any other file whose copy differs is copied whole.

    So the copy is read as the home is, and a runtime's cleanup of the home
    leaves it whole. Nothing is followed through a link, and nothing outside
    `home` is copied.
    """

    def files() -> Iterator[Path]:
        """Yield each file to copy, each once."""
        found = records.found(home)
        yield from dict.fromkeys(
            path
            for record in found
            for path in [record.path, *records.beside(record)]
            if path.is_relative_to(home)
        )

    def one(path: Path) -> Literal["whole", "grown", "same"]:
        """Copy one file of `home`'s into its place under `into`: say how."""
        target = into / path.relative_to(home)
        try:
            source = opened(path)
        except OSError:
            return "same"
        with source:
            size = os.fstat(source.fileno()).st_size
            had = target.stat().st_size if target.is_file() else None
            if had == size:
                return "same"
            target.parent.mkdir(parents=True, exist_ok=True)
            if had is not None and had < size and path.suffix == ".jsonl":
                source.seek(had)
                with target.open("ab") as written:
                    written.write(source.read())
                return "grown"
            target.write_bytes(source.read())
            return "whole"

    done = [one(each) for each in files()]
    return Copied(whole=done.count("whole"), grown=done.count("grown"))
