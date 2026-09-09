"""One append-only log per repository, read back as whichever type you ask for.

The store is one file and the types in it are many and unrelated. Those two
facts are separate, and running them together is the mistake this shape
avoids: a `Task` and a `Claim` share a log, not a class, and nothing outside
this module ever sees them unioned.

**Reads are per type.** ``store.read(Task)`` hands back ``list[Task]`` with
every field typed, ``store.read(Claim)`` hands back ``list[Claim]``, and a
record of the wrong type is simply not in the answer. The base class surfaces
in exactly two places — resolving an edge's endpoint, whose type the asker
does not know, and a reader showing everything — and both are the boundary
where stored JSON becomes objects again.

**Why one log rather than one per subject.** Standing is computed by asking
what points at a node: corrections superseding it, evidence supporting it,
verifications checking it. Split by subject, that question spans several files
which can change between reads, needs a resolver that knows every one of them,
and has to be snapshotted consistently across all of them. Git keeps commits,
trees and blobs in one object store for the same reason, and those are no more
alike than these.

Nothing is ever rewritten in place, so two sessions appending at once produce
a longer log rather than a lost record.
"""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from lup.channels.models import utc_now
from lup.coordination.refs import ActorRef
from lup.ledger.blobs import Blobs
from lup.ledger.models import LedgerEdge, LedgerNode, Standing, Surroundings
from lup.ledger.store import JOURNAL_FILE, ledger_root
from lup.types import JsonObject, JsonValue


def latest[N: LedgerNode](nodes: Iterator[N]) -> list[N]:
    """Each id once, as it was last recorded, in the order it first appeared.

    Two readings of one sequence because the halves disagree and both matter:
    the value is the last record for an id, so an amendment wins, and the
    position is the first, so a node amended twice stays where a reader last
    saw it. Written as one pass each rather than a fold, so neither reading
    has to be held in a variable the other is also changing.
    """
    seen = list(nodes)
    current = {node.id: node for node in seen}
    return [current[node_id] for node_id in dict.fromkeys(node.id for node in seen)]


class LedgerRefusal(Exception):
    """Something declined to be recorded, in the words the writer is shown.

    An exception rather than a returned refusal because recording is the
    caller's whole purpose in the call: a writer that ignored a returned
    refusal would carry on as though the record existed, and every reader
    after it would be reading a DAG missing what the code says is in it.
    """


class LedgerStore:
    """The one log this repository records into, and the blobs beside it.

    Holds nothing open and locks nothing: every read folds the file and every
    write appends a line, so a hook, a console and a tool server may all reach
    it at once and none of them has to be running for the others to work.
    """

    def __init__(self, root: Path, author: ActorRef) -> None:
        self.root = ledger_root(root)
        self.project = root
        """The tree this store was opened from, which evidence stands against."""
        self.author = author
        self.blobs = Blobs(self.root)

    @property
    def path(self) -> Path:
        """The log itself, created on first use rather than at construction."""
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / JOURNAL_FILE

    def lines(self) -> list[JsonObject]:
        """Every record as it was stored, oldest first.

        Raw rather than validated, because what a record should be read *as*
        is the caller's question and this cannot answer it: one log holds every
        vocabulary, and the same line is a ``Task`` to one reader and a record
        of an unknown type to the next.

        A malformed line is skipped rather than fatal. One bad record must not
        poison a log a live session is still appending to.
        """
        adapter = TypeAdapter[JsonObject](JsonObject)

        def parsed() -> Iterator[JsonObject]:
            try:
                raw = self.path.read_text(encoding="utf-8")
            except OSError:
                return
            for line in raw.splitlines():
                if not line.strip():
                    continue
                try:
                    yield adapter.validate_json(line)
                except ValidationError:
                    continue

        return list(parsed())

    def append(self, record: LedgerNode | LedgerEdge) -> None:
        """Put one record at the end of the log, atomically enough to share.

        One ``write`` of one line opened for append, which the platform does
        not interleave below the pipe buffer, so a concurrent writer produces
        a longer file rather than a torn line.
        """
        with self.path.open("a", encoding="utf-8") as log:
            log.write(record.model_dump_json() + "\n")

    def read[N: LedgerNode](self, node: type[N]) -> list[N]:
        """Every node of this type as it now stands, in the order first recorded.

        The typed read, and the one nearly every caller wants. A record of
        another type fails validation and is left out, which is what makes
        this a filter rather than a cast: nothing comes back as an ``N`` that
        is not one.

        **The latest record for an id wins.** Nodes are immutable and the log
        only grows, so changing one is appending it again — which is the only
        way a task can ever be finished, and it keeps every earlier version
        readable rather than overwriting anything. Position is the first
        appearance, so amending a node does not move it to the end of a
        listing somebody is reading.
        """
        adapter = TypeAdapter[N](node)

        def matching() -> Iterator[N]:
            for line in self.lines():
                try:
                    yield adapter.validate_python(line)
                except ValidationError:
                    continue

        return list(latest(matching()))

    def edges[E: LedgerEdge](self, edge: type[E] = LedgerEdge) -> list[E]:
        """Every edge of one type, or every edge at all as the base.

        The base is the honest default here in a way it is not for nodes: a
        reader asking what points at something wants all of it, and an edge
        carries its meaning in three fields the base already declares.
        """
        adapter = TypeAdapter[E](edge)

        def matching() -> Iterator[E]:
            for line in self.lines():
                if "source" not in line:
                    continue
                try:
                    yield adapter.validate_python(line)
                except ValidationError:
                    continue

        return list(matching())

    def around(self, node: LedgerNode, classes: list[type[LedgerNode]]) -> Surroundings:
        """One node's neighbourhood, resolved once for whoever is asking it.

        The far ends come back as the most specific declared class that
        accepts them, so a neighbour is asked its own answer rather than the
        base's — a blocker reads as finished because it is a ``Task`` and
        knows what that means.
        """
        incoming = self.into(node.id)
        outgoing = self.out_of(node.id)
        wanted = {edge.source for edge in incoming} | {edge.target for edge in outgoing}
        return Surroundings(
            incoming=incoming,
            outgoing=outgoing,
            neighbours=[
                found
                for other in wanted
                if (found := self.resolve(other, classes)) is not None
            ],
            root=self.project,
        )

    def into(self, node_id: str) -> list[LedgerEdge]:
        """Every edge pointing at one node, which is what standing is read from.

        One pass over one file, which is the property that decides the whole
        shape: split the log by subject and this spans several of them, each
        able to change between reads.
        """
        return [edge for edge in self.edges() if edge.target == node_id]

    def out_of(self, node_id: str) -> list[LedgerEdge]:
        """Every edge this node is the source of."""
        return [edge for edge in self.edges() if edge.source == node_id]

    def amend[N: LedgerNode](self, node: N) -> N:
        """Record a changed node under the id it already has.

        The only way anything in the log changes, and it changes nothing that
        is already written: the earlier record stays where it was and a read
        takes the last one. So finishing a task, or correcting a title, leaves
        the history of that node readable instead of overwriting it — which is
        what an append-only log is for and what a mutable store would cost.

        The author is stamped again, so a node amended by somebody other than
        whoever wrote it says who last touched it.
        """
        restamped = node.model_copy(update={"author": self.author})
        self.append(restamped)
        return restamped

    def resolve(
        self, node_id: str, classes: list[type[LedgerNode]]
    ) -> LedgerNode | None:
        """One node as the first of these classes that accepts it, or the base.

        The deserialization boundary, and the one place a list of types is
        needed: an edge names an id and not what is at the other end, so
        something has to try. A record no class accepts comes back as the base
        — which happens for a type this build does not declare, and is why it
        is a fallback rather than a failure.
        """

        def versions() -> Iterator[LedgerNode]:
            for line in self.lines():
                if "id" not in line or line["id"] != node_id:
                    continue
                for declared in classes:
                    try:
                        yield declared.model_validate(line)
                        break
                    except ValidationError:
                        continue
                else:
                    try:
                        yield LedgerNode.model_validate(line)
                    except ValidationError:
                        continue

        # The last record for this id, for the reason `read` takes it: a node
        # is amended by being appended again, so an earlier match is a version
        # somebody has already moved on from.
        found = list(versions())
        return found[-1] if found else None

    def all_nodes(self, classes: list[type[LedgerNode]]) -> list[LedgerNode]:
        """Every node in the log, each as the most specific class that fits.

        For a reader whose subject is the log rather than any one type — the
        console, above all. Everything else asks :meth:`read` for what it
        actually wants.
        """

        def resolved() -> Iterator[LedgerNode]:
            for line in self.lines():
                if "source" in line:
                    continue
                for declared in classes:
                    try:
                        yield declared.model_validate(line)
                        break
                    except ValidationError:
                        continue
                else:
                    try:
                        yield LedgerNode.model_validate(line)
                    except ValidationError:
                        continue

        return latest(resolved())

    def standing(
        self, node: LedgerNode, classes: list[type[LedgerNode]] | None = None
    ) -> Standing:
        """Where one node stands right now, asked of the node itself.

        The classes resolve its neighbours, and omitting them is honest rather
        than lossy: a caller that names none gets a neighbourhood of base
        nodes, which decline every question a type would have answered. That
        is the reading a build lacking the declaring module would get anyway.
        """
        return node.standing(self.around(node, classes or []))

    def record[N: LedgerNode](
        self,
        node: type[N],
        title: str,
        text: str = "",
        attachments: list[bytes] | None = None,
        at: datetime | None = None,
        **payload: JsonValue,
    ) -> N:
        """Mint one node of this type, store what it attaches, and log it.

        The id, the author and the timestamp are stamped here rather than
        taken, which is what makes provenance a fact about the record instead
        of a claim by its writer. Everything else is the type's own field set,
        validated by the type — so what used to want a gate is a declaration.

        Attachments are stored before the node is, so a node that lands always
        points at bytes already on disk; the other order leaves a window where
        the record names a blob nothing can read.
        """
        return self.record_fields(
            node, title, dict(payload), text=text, attachments=attachments, at=at
        )

    def record_fields[N: LedgerNode](
        self,
        node: type[N],
        title: str,
        fields: JsonObject,
        text: str = "",
        attachments: list[bytes] | None = None,
        at: datetime | None = None,
    ) -> N:
        """Mint one node with its type's own fields arriving as one object.

        The shape a generic caller has — a console or a tool that read the
        fields rather than spelled them as keywords. The stamps are laid over
        the fields rather than under them, so a payload naming an author or
        an id is overruled: provenance a writer cannot spell is provenance a
        writer cannot get wrong, and that has to hold for a writer handing
        over a whole object as much as for one naming keywords.
        """
        held = [self.blobs.store(item) for item in attachments or []]
        built = node.model_validate(
            {
                "title": title,
                "text": text,
                **fields,
                "id": uuid4().hex[:12],
                "author": self.author.model_dump(),
                "at": at or utc_now(),
                "attachments": held,
            }
        )
        # Derived fields are filled after validation and before the append,
        # so a type reads the tree exactly once and what lands is complete.
        prepared = built.prepared(self.project)
        self.append(prepared)
        return prepared

    def relate[E: LedgerEdge](
        self,
        edge: type[E],
        source: LedgerNode,
        target: LedgerNode,
        at: datetime | None = None,
        **payload: JsonValue,
    ) -> E:
        """Draw one edge between two nodes, whatever types they are.

        Both ends are passed as nodes rather than ids, because the refusal
        needs them: the one rule this library keeps about who may say what is
        that a relation may decline an author who wrote the thing at the other
        end, and only the edge sees both.
        """
        return self.relate_fields(edge, source, target, dict(payload), at=at)

    def relate_fields[E: LedgerEdge](
        self,
        edge: type[E],
        source: LedgerNode,
        target: LedgerNode,
        fields: JsonObject,
        at: datetime | None = None,
    ) -> E:
        """Draw one edge with its type's own fields arriving as one object.

        The endpoints and the stamps are laid over the fields, so an object
        naming a different source or author is overruled — the caller passed
        the nodes, and the nodes are what the edge is between.
        """
        built = edge.model_validate(
            {
                **fields,
                "source": source.id,
                "target": target.id,
                "author": self.author.model_dump(),
                "at": at or utc_now(),
            }
        )
        refusal = built.refusal(source, target)
        if refusal:
            raise LedgerRefusal(refusal)
        self.append(built)
        return built
