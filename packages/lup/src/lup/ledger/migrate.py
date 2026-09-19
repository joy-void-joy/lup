"""Settling the journals with the placement a project now declares for a kind.

A project places each kind committed or local, and the journal a record lands
in is decided once, at the moment it is appended. Move a kind after records
exist and the old ones stay where they were. Nothing is lost — the fold reads
a record wherever it sits, and every id, edge and standing still answers — but
the two journals no longer say what the mapping says: a kind declared
committed has half its records outside the tree, so a diff of the committed
half shows less than the declaration promises, and a clone that has only the
commits reads only that half.

This is the deliberate act that settles them. Every record whose kinds place
it in the other journal is copied into the journal the mapping now declares,
and the blobs those records attach are copied beside it, so the destination
half holds the kind whole.

**The source lines stay.** Nothing in this log is ever rewritten in place:
every write is one append, every read folds files that only grow, and two
sessions appending at once produce a longer log rather than a lost record. A
rewrite that dropped lines is the one operation that can lose a record another
process appended between the read and the write, and it would be doing that to
the only copy. The committed journal is merged by git's ``union`` driver
besides, which keeps every line any side holds, so a deletion there is undone
by the next merge of a branch that still has it. And a read already folds the
two copies into one: :meth:`~lup.ledger.journal.LedgerStore.stored` breaks the
tie by putting the copy in the journal the kind now declares last, so that copy
is the one every read takes and the duplicate is invisible above this layer.
What copying buys over moving is that the source half alone still reads exactly
what it read before — every line it held, and every blob those lines name —
which is what a checkout that has not taken this declaration sees.

Running it again copies nothing: a record whose copy is already in the
destination journal is left alone, and a blob is stored under the digest of
its own bytes, so a half that holds it already holds the right bytes.
"""

from collections.abc import Iterator, Sequence

from pydantic import BaseModel, TypeAdapter

from lup.ledger.journal import LedgerStore
from lup.ledger.models import Placement
from lup.types import JsonObject


class Misplaced(BaseModel, frozen=True):
    """One stored record sitting in a journal its kinds no longer place it in."""

    line: JsonObject
    held: Placement
    """The journal the record is in."""

    declared: Placement
    """The journal the project's mapping now places it in."""

    kinds: list[str]
    """Which kinds decide that: a node's own, an edge's two ends'."""


class Attachment(BaseModel, frozen=True):
    """One blob a record names, and the journal half it now belongs beside."""

    digest: str
    placement: Placement


class Carried(Attachment, frozen=True):
    """One blob a migration put beside the journal its record now belongs to."""

    stored: bool
    """Whether the bytes landed; false where no half of the store held them."""


class Migration(BaseModel, frozen=True):
    """What one run copied across, and what it found already settled."""

    copied: list[Misplaced] = []
    """Records written into the journal their kinds declare."""

    settled: list[Misplaced] = []
    """Records whose copy was already there, which is what a second run finds."""

    carried: list[Carried] = []
    """Blobs the run tried to put beside the destination journal."""

    def blobs(self) -> list[str]:
        """The digests whose bytes now sit beside the destination journal."""
        return [each.digest for each in self.carried if each.stored]

    def missing(self) -> list[str]:
        """The digests no half of the store holds, so nothing could be copied."""
        return [each.digest for each in self.carried if not each.stored]

    def kinds(self) -> list[str]:
        """Every kind this run moved a record of, in the order first seen."""
        return list(
            dict.fromkeys(
                kind
                for each in (*self.copied, *self.settled)
                for kind in each.kinds
                if kind
            )
        )


def deciding_kinds(store: LedgerStore, line: JsonObject) -> list[str]:
    """The kinds whose placement decides which journal one stored line goes to.

    Read off the raw record rather than off a validated one, because a
    migration is about every line in the log and the type that would validate
    a given line need not be declared in the build running this. The record's
    own shape says which question to ask, exactly as
    :meth:`~lup.ledger.models.LedgerEdge.deciding_kinds` does for a validated
    one: a line naming both ends is an edge, placed by its two ends' kinds, and
    anything else is a node, placed by its own.
    """
    match line:
        case {"source": source, "target": target}:
            return [store.kind_at(str(source)), store.kind_at(str(target))]
        case {"kind": kind}:
            return [str(kind)]
        case _:
            return []


def attached(line: JsonObject) -> list[str]:
    """The blob digests one stored record names, read off the raw line."""
    match line:
        case {"attachments": list() as digests}:
            return [str(digest) for digest in digests]
        case _:
            return []


def misplaced(
    store: LedgerStore, kinds: Sequence[str] | None = None
) -> list[Misplaced]:
    """Every record in a journal its kinds no longer place it in, oldest first.

    Narrowed to the records one of *kinds* decides where any are named, and
    every misplaced record where none is. An edge is decided by its two ends,
    so naming a node kind reaches the edges at it — which is what keeps git
    from carrying a reference to a record it does not hold once a kind moves.
    """

    def wanted(deciding: Sequence[str]) -> bool:
        return kinds is None or any(kind in kinds for kind in deciding)

    def found() -> Iterator[Misplaced]:
        with store.batch():
            for each in store.stored():
                deciding = deciding_kinds(store, each.line)
                declared = store.layout.placement_of(deciding)
                if declared == each.placement or not wanted(deciding):
                    continue
                yield Misplaced(
                    line=each.line,
                    held=each.placement,
                    declared=declared,
                    kinds=deciding,
                )

    return list(found())


def carry(store: LedgerStore, records: Sequence[Misplaced]) -> Iterator[Carried]:
    """Put the blobs these records attach beside the journal they now belong to.

    Each digest once per destination: the store is content-addressed, so the
    same bytes under one name are one blob however many records attach them,
    and a half that already holds the digest already holds those bytes. Bytes
    no half holds are reported rather than raised — an attachment that was
    never on this machine is a record worth copying anyway, and the source
    half could not read it either.
    """
    wanted = dict.fromkeys(
        Attachment(digest=digest, placement=record.declared)
        for record in records
        for digest in attached(record.line)
    )
    for each in wanted:
        if store.blobs.halves[each.placement].holds(each.digest):
            continue
        content = store.blobs.read(each.digest)
        if content is not None:
            store.blobs.store(content, each.placement)
        yield Carried(
            digest=each.digest, placement=each.placement, stored=content is not None
        )


def migrate(store: LedgerStore, kinds: Sequence[str] | None = None) -> Migration:
    """Copy every misplaced record, and what it attaches, to the journal declaring it.

    The lines are appended in the order the fold reads them, so the
    destination journal's own order stays the log's order; a read sorts by the
    records' timestamps regardless, and the copy in the declared journal is the
    one it takes.
    """
    line_json = TypeAdapter[JsonObject](JsonObject)

    def spelled(line: JsonObject) -> str:
        """One record as a journal holds it: compact JSON, one line."""
        return line_json.dump_json(line).decode("utf-8")

    with store.batch():
        moving = misplaced(store, kinds)
        present = {
            placement: {
                spelled(each.line)
                for each in store.stored()
                if each.placement == placement
            }
            for placement in store.roots
        }
    copied = [
        each for each in moving if spelled(each.line) not in present[each.declared]
    ]
    for placement in store.roots:
        landing = [each for each in copied if each.declared == placement]
        if landing:
            with store.journal(placement).open("a", encoding="utf-8") as log:
                log.writelines(spelled(each.line) + "\n" for each in landing)
    return Migration(
        copied=copied,
        settled=[each for each in moving if each not in copied],
        carried=list(carry(store, moving)),
    )
