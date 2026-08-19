"""One ordered record file: sequenced, appended durably, read back by either end.

Two records ride this. The resolver's decision log carries a typed event union
a supervisor dispatches on; the observable transcript carries whatever payload
a provider produced, hashed into a chain so an edit is visible rather than
silent. Those are different products, and neither collapses into the other.

What they share is the mechanism — take the next sequence, append, read back
from a byte offset or from a sequence number, page backwards from one. Sharing
it is what lets any reader tail either record the same way, and what stops the
next thing that needs a record from arriving with a third implementation.

How a record reaches the disk is a :class:`RecordWriter` rather than a flag,
because the two ways differ in more than a boolean: a transcript re-reads the
chain head under a cross-process lock and hashes onto it, while a decision log
with one writer keeps its sequence in memory and appends. A flag would name
the difference without carrying it, and every caller would set every flag the
same way forever.
"""

import fcntl
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field, TypeAdapter

from lup.channels.stream import Stream


class JournalRecord[A](BaseModel, frozen=True):
    """The minimum a journal needs of a record: its place, and whose it is.

    Generic over the actor because attribution is the consumer's vocabulary:
    a transcript attributes to a span in an agent tree, a decision log to a
    mail address that outlives its round. The journal never reads inside
    either — it orders records and hands back the ones matching a value the
    caller already holds.
    """

    seq: int = Field(ge=0)
    actor: A


class JournalTail[R](BaseModel, frozen=True):
    """What one follower read, and where it should resume."""

    entries: list[R]
    offset: int


type Finalize[R] = Callable[[int, R | None], R]
"""Complete one record given its sequence and the record before it.

The predecessor is passed rather than fetched because only the writer knows
when it is safe to look: a chained record reads its head inside the lock it
writes under, and a caller reading it beforehand would chain onto a head
another process had already moved.
"""


class RecordWriter[R: JournalRecord](ABC):
    """How one record is sequenced and put on disk.

    Abstract rather than parameterized, because the two implementations
    disagree about where the sequence comes from — memory or the file — and
    that is the decision, not a detail underneath one.
    """

    @abstractmethod
    def append(self, stream: Stream[R], finalize: Finalize[R]) -> R:
        """Assign this record its place in the order and write it."""


class AppendWriter[R: JournalRecord](RecordWriter[R]):
    """Append under a sequence held in memory, for a log with one writer.

    The count is taken from the file once, on the first append rather than at
    construction, so opening a journal to read it costs nothing. It is read
    from the last record rather than by counting them, because a torn line in
    a log a live process is still writing makes the count and the last
    sequence disagree — and the sequence is the one a reader pages by.
    """

    def __init__(self) -> None:
        self.next_seq: int | None = None

    def append(self, stream: Stream[R], finalize: Finalize[R]) -> R:
        if self.next_seq is None:
            last = stream.last()
            self.next_seq = last.seq + 1 if last is not None else 0
        record = finalize(self.next_seq, None)
        stream.append(record)
        self.next_seq += 1
        return record


class ChainedWriter[R: JournalRecord](RecordWriter[R]):
    """Append under a file lock, chaining each record onto the one before it.

    The head is re-read from the file inside the lock rather than trusted from
    memory: a second process appending to the same transcript would otherwise
    leave both writers chaining from a head that is no longer last, and the
    chain would fail to verify with nothing having been tampered with.

    The thread lock is held around the file lock because ``flock`` is granted
    per open file description rather than per thread — two threads in one
    process would both hold it and interleave inside the region it exists to
    make exclusive.
    """

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self.lock = threading.Lock()

    def append(self, stream: Stream[R], finalize: Finalize[R]) -> R:
        with self.lock:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    last = stream.last()
                    record = finalize(
                        last.seq + 1 if last is not None else 0,
                        last,
                    )
                    stream.append(record)
                    return record
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Journal[A, R: JournalRecord]:
    """One run's ordered record, appended by a writer and read from both ends.

    Reads go through the stream whatever wrote the file, so a chained
    transcript and a plain decision log are paged by the same code. Only the
    write differs, which is the whole reason the writer is the seam.
    """

    def __init__(
        self,
        path: Path,
        adapter: TypeAdapter[R],
        writer: RecordWriter[R] | None = None,
    ) -> None:
        self.stream: Stream[R] = Stream(path, adapter, durable=writer is not None)
        self.writer: RecordWriter[R] = writer or AppendWriter()

    @property
    def path(self) -> Path:
        return self.stream.path

    def write(self, finalize: Finalize[R]) -> R:
        """Put one record in the file, stamped with the place the writer gives it.

        The seam a consumer builds its own verb on: a decision log appends an
        event for an actor, a transcript emits a kind and a payload, and both
        reach the order through here. Deliberately not named for either of
        them, so neither reads as the one this is really for.

        Writing reaches no await, so concurrent actors draining their own
        sessions into one journal interleave between records and never within
        one. That is what keeps a single ordered record true once every actor
        holds a live session instead of taking turns.
        """
        return self.writer.append(self.stream, finalize)

    def read(self, after_seq: int = -1) -> list[R]:
        """Every record after ``after_seq``, which is what an SSE resume wants.

        Reconnecting replays from ``seq + 1`` rather than from zero, so a page
        open all run does not re-render the whole run whenever its connection
        blinks.
        """
        return [record for record in self.stream.read_all() if record.seq > after_seq]

    def tail(self, offset: int) -> JournalTail[R]:
        """Whatever arrived after ``offset``, and where to resume.

        A follower reads by byte offset rather than by sequence number so that
        watching a run costs the size of what is new. Filtering by ``seq``
        re-parses the whole file on every poll, which turns a long run into
        quadratic work exactly as it becomes interesting.
        """
        found = self.stream.read_from(offset)
        if not found:
            return JournalTail(entries=[], offset=offset)
        return JournalTail(
            entries=[pair.item for pair in found], offset=found[-1].commit_offset
        )

    def entry(self, seq: int) -> R | None:
        """One record whole, for a reader expanding a truncated block."""
        return next(
            (record for record in self.stream.read_all() if record.seq == seq), None
        )

    def before(self, seq: int, count: int) -> list[R]:
        """The ``count`` records just before ``seq``, oldest first.

        A fresh follower starts from a bounded tail of the record, so the run
        older than that tail is reached from here one page at a time — on
        demand, rather than by replaying the whole run into the reader the
        bound exists to protect.
        """
        if count <= 0:
            return []
        earlier = [record for record in self.stream.read_all() if record.seq < seq]
        return earlier[-count:]

    def last(self) -> R | None:
        """The most recent record, without paying for the whole journal."""
        return self.stream.last()

    def actors(self) -> list[A]:
        """Every actor that has produced a record, in first-seen order."""
        return list(dict.fromkeys(record.actor for record in self.stream.read_all()))

    def for_actor(self, actor: A, after_seq: int = -1) -> list[R]:
        """One actor's slice of the record, which is its whole trace."""
        return [record for record in self.read(after_seq) if record.actor == actor]


def last_record[R: JournalRecord](path: Path, adapter: TypeAdapter[R]) -> R | None:
    """A journal's most recent record, without constructing one to ask.

    A status view asks this against a file that reaches tens of megabytes in
    one run, and a journal that counted its records to know its next sequence
    would charge that reader for a writer's question.
    """
    return Stream(path, adapter).last()
