"""The ledger's store: every repository's nodes and edges, in one SQLite database the host service writes.

`packages/lup-ledger/README.md`, *The store*.
- **One sequence of numbers** for every node of every repository (`numbered`),
  as the inbox's items have, so `@12` names one thing on the machine.
- **Every version kept.** A change appends the node again, at its own time,
  which must come after the version before it (`kept`); a read takes the
  latest, and `versions` reads them all. The first lup's amend kept the first
  version's time on every one, so nothing could tell when a task closed.
- **Edges are drawn, never changed** (`drawn`), each read in the order drawn.
- **Indexed, so no read walks the store:** a node's latest version is one row
  of `nodes`, found by its number, its repository and kind, or its name; its
  versions by its number; an edge by the node it's drawn to or from. The first
  lup's ledger folded its whole log at every read, which hung on 85 MB.
- **One connection, behind one lock,** since the host service answers each hook
  in a thread of its own: a write is one transaction, `writing` holds one
  across several writes so they're kept together or not at all, and
  `together` holds the lock across several reads so they see one state.
- **Plain records** beside the graph: what's rewritten in place by its name,
  with no version and no number (`plain`, `rewritten`), such as the operator's
  draft, which changes at every pause in their typing.
- **Attachments** beside the database: what a record carries that's too large
  for a row, such as an item's diff, a file each, named by its content's digest
  (`attached`, `attachment`), so one kept twice is one file.
"""

import hashlib
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError

from lup.types import Model
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.errors import LupLedgerError
from lup_ledger.records import Edge, Kinds, Node, Record
from lup_ledger.threads import KINDS

if TYPE_CHECKING:
    from collections.abc import Collection, Generator

SCHEMA = """
CREATE TABLE sequence (next INTEGER NOT NULL);
INSERT INTO sequence (next) VALUES (1);
CREATE TABLE versions (
    version INTEGER PRIMARY KEY,
    number INTEGER NOT NULL,
    kind TEXT NOT NULL,
    record TEXT NOT NULL
);
CREATE INDEX versions_of ON versions (number, version);
CREATE TABLE nodes (
    number INTEGER PRIMARY KEY,
    version INTEGER NOT NULL,
    kind TEXT NOT NULL,
    repository TEXT NOT NULL,
    name TEXT
);
CREATE INDEX nodes_of ON nodes (repository, kind, number);
CREATE UNIQUE INDEX nodes_named ON nodes (repository, name) WHERE name IS NOT NULL;
CREATE TABLE edges (
    drawn INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    source INTEGER,
    target INTEGER NOT NULL,
    record TEXT NOT NULL
);
CREATE INDEX edges_to ON edges (target, drawn);
CREATE INDEX edges_from ON edges (source, drawn);
"""
"""The tables of version 1: the sequence's next number; each version of each
node, in the order kept; each node's latest version, with what it's found by;
each edge, in the order drawn."""

SECOND = """
CREATE INDEX nodes_kinds ON nodes (kind, number);
CREATE INDEX edges_kinds ON edges (kind, drawn);
CREATE TABLE records (name TEXT PRIMARY KEY, record TEXT NOT NULL);
"""
"""What version 2 adds to version 1: each node and each edge found by its kind,
across repositories, so the host service reads every item at its start
without walking the store; and the plain records, each by its name."""

LATEST = (
    "SELECT versions.kind, versions.record FROM nodes "
    "JOIN versions ON versions.version = nodes.version"
)
"""Each node's latest version, which a read narrows by what `nodes` indexes."""

EDGES = "SELECT kind, record FROM edges"
"""Each edge, which a read narrows by what `edges` indexes."""

KINDS_HELD = "SELECT kind FROM nodes"
"""The kind of each node, which a read narrows by what `nodes` indexes."""


def upgrade(found: int) -> str | None:
    """Return what makes a database at version `found` of the tables the one after it; none where no version follows.

    >>> upgrade(1) == SECOND
    True
    """
    match found:
        case 0:
            return SCHEMA
        case 1:
            return SECOND
        case _:
            return None


def declared(
    kind: type[Record], among: list[type[Node]] | list[type[Edge]]
) -> list[str]:
    """Return the kinds declared by `kind` and each of `among` derived from it: those a read of `kind` finds."""
    return list(
        dict.fromkeys(
            name
            for each in [kind, *among]
            if issubclass(each, kind) and (name := each.declared()) is not None
        )
    )


class Drawn(Model):
    """An edge as the ledger holds it: where it is in the order drawn, and the edge."""

    place: int
    edge: Edge


class Written(Model):
    """How far the ledger has been written: its latest version's place in the order kept, and its latest edge's in the order drawn; 0 where none is."""

    versions: int
    edges: int


class Ledger(Model, arbitrary_types_allowed=True):
    """The ledger's store, open: every repository's nodes and edges, read and written by the host service.

    Safe to share between threads: each call takes the lock, and a write is one
    transaction. A record of a kind `kinds` doesn't declare reads as the base
    class, every field it held kept.
    """

    connection: sqlite3.Connection
    kinds: Kinds
    layout: LedgerLayout
    """Where it's kept: the database, and the attachments beside it."""
    lock: threading.RLock = Field(default_factory=threading.RLock)
    """Held for each call, and across several by `together`; reentrant, so a
    kind's refusal reads the ledger while a write holds it."""

    @classmethod
    def opened(
        cls,
        layout: LedgerLayout,
        # lup: defer(issue=343, why="a module's own kinds join the ledger's here, once a module can declare them")
        kinds: Kinds = KINDS,
        schema: int = 2,
    ) -> Ledger:
        """Open the ledger kept at `layout`, making it where there's none, its records read as `kinds` declares them.

        `schema` is the version of the tables this code reads, kept in the
        database's `user_version`: a database at an earlier one is brought to
        it, each version's tables after the last (`upgrade`), in one
        transaction. Raise `LupLedgerError` where the database is at a later one.

        Its write-ahead log is synced to the disk at each checkpoint rather than
        at each transaction (`synchronous = NORMAL`): a transaction is lost to
        a power cut, never to the service's crash, as the inbox's files were
        written whole without a sync.
        """
        layout.home.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            layout.database, autocommit=True, check_same_thread=False
        )
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("BEGIN IMMEDIATE")
        made = False
        try:
            found = connection.execute("PRAGMA user_version").fetchone()[0]
            for version in range(found, schema):
                script = upgrade(version)
                if script is not None:
                    connection.executescript(
                        f"{script}PRAGMA user_version = {version + 1};"
                    )
            made = True
        finally:
            connection.execute("COMMIT" if made else "ROLLBACK")
        if found > schema:
            connection.close()
            message = (
                f"the ledger at {layout.database} is at version {found} of its "
                f"tables, and this lup reads version {schema}"
            )
            raise LupLedgerError(message)
        return cls(connection=connection, kinds=kinds, layout=layout)

    def close(self) -> None:
        """Close the database; the ledger can't be used after."""
        with self.lock:
            self.connection.close()

    def copied(self) -> bytes:
        """Return the database whole, as one file's bytes, for a copy of it elsewhere, which `opened` reads as it reads this one; the attachments beside it apart.

        Taken through SQLite's backup, under the lock, so it's one state, no
        write landing halfway, and what the write-ahead log holds is in it.
        """
        with self.lock:
            memory = sqlite3.connect(":memory:")
            try:
                self.connection.backup(memory)
                return memory.serialize()
            finally:
                memory.close()

    @contextmanager
    def together(self) -> Generator[None]:
        """Hold the lock across several calls, so what they read is one state: none is written between them."""
        with self.lock:
            yield

    @contextmanager
    def writing(self) -> Generator[sqlite3.Connection]:
        """Hold the lock and a transaction across a write, or several: committed where it ends, rolled back where it raises.

        Within another, it's a savepoint of that one: what's written inside is
        undone alone where it raises, and kept or rolled back with the rest
        where the outer one ends. So `with ledger.writing():` around several
        writes keeps them together, or none of them.
        """
        with self.lock:
            nested = self.connection.in_transaction
            self.connection.execute(
                "SAVEPOINT writing" if nested else "BEGIN IMMEDIATE"
            )
            done = False
            try:
                yield self.connection
                done = True
            finally:
                if nested:
                    if not done:
                        self.connection.execute("ROLLBACK TO writing")
                    self.connection.execute("RELEASE writing")
                else:
                    self.connection.execute("COMMIT" if done else "ROLLBACK")

    def written(self) -> Written:
        """Say how far the ledger has been written: what a reader holding what it made of it compares, to know whether to make it again. Plain records aren't counted, rewritten in place."""
        with self.lock:
            row = self.connection.execute(
                "SELECT (SELECT coalesce(max(version), 0) FROM versions), "
                "(SELECT coalesce(max(drawn), 0) FROM edges)"
            ).fetchone()
        return Written(versions=row[0], edges=row[1])

    def numbered(self) -> int:
        """Take the sequence's next number, for a node about to be kept; none is ever taken twice."""
        with self.writing() as database:
            row = database.execute(
                "UPDATE sequence SET next = next + 1 RETURNING next - 1"
            ).fetchone()
        return row[0]

    def node_read(self, kind: str, record: str) -> Node:
        """Read a node's `record`, of `kind`, as the class declaring its kind, or `Node`; raise `LupLedgerError` where it doesn't read."""
        try:
            return self.kinds.node(kind).model_validate_json(record)
        except ValidationError as unread:
            message = f"a `{kind}` the ledger holds doesn't read: {unread}"
            raise LupLedgerError(message) from unread

    def edge_read(self, kind: str, record: str) -> Edge:
        """Read an edge's `record`, of `kind`, as the class declaring its kind, or `Edge`; raise `LupLedgerError` where it doesn't read."""
        try:
            return self.kinds.edge(kind).model_validate_json(record)
        except ValidationError as unread:
            message = f"a `{kind}` the ledger holds doesn't read: {unread}"
            raise LupLedgerError(message) from unread

    def found(self, number: int) -> Node | None:
        """Return node `number` as it stands, its latest version; none where the ledger holds none."""
        with self.lock:
            row = self.connection.execute(
                f"{LATEST} WHERE nodes.number = ?", (number,)
            ).fetchone()
        return None if row is None else self.node_read(row[0], row[1])

    def node[N: Node](self, number: int, kind: type[N]) -> N:
        """Return node `number` as it stands, as `kind`: `Node` for any.

        Raise `LupLedgerError` where the ledger holds none, or one of another kind.
        """
        found = self.found(number)
        if found is None:
            message = f"the ledger holds no @{number}"
            raise LupLedgerError(message)
        if not isinstance(found, kind):
            message = f"@{number} is a `{found.kind}`, not a `{kind.declared()}`"
            raise LupLedgerError(message)
        return found

    def versions(self, number: int) -> list[Node]:
        """Return every version of node `number`, oldest first; none where the ledger holds none."""
        with self.lock:
            rows = self.connection.execute(
                "SELECT kind, record FROM versions WHERE number = ? ORDER BY version",
                (number,),
            ).fetchall()
        return [self.node_read(kind, record) for kind, record in rows]

    def named(self, repository: Path, name: str) -> Node | None:
        """Return the node of `repository` named `name`, as it stands; none where none is."""
        with self.lock:
            row = self.connection.execute(
                f"{LATEST} WHERE nodes.repository = ? AND nodes.name = ?",
                (str(repository), name),
            ).fetchone()
        return None if row is None else self.node_read(row[0], row[1])

    def nodes[N: Node](self, repository: Path, kind: type[N]) -> list[N]:
        """Return each node of `repository` of `kind` as it stands, by number: `Node` for every node of it."""
        declared = kind.declared()
        with self.lock:
            if declared is None:
                rows = self.connection.execute(
                    f"{LATEST} WHERE nodes.repository = ? ORDER BY nodes.number",
                    (str(repository),),
                ).fetchall()
            else:
                rows = self.connection.execute(
                    f"{LATEST} WHERE nodes.repository = ? AND nodes.kind = ? "
                    "ORDER BY nodes.number",
                    (str(repository), declared),
                ).fetchall()
        found = [self.node_read(each, record) for each, record in rows]
        return [each for each in found if isinstance(each, kind)]

    def every[N: Node](self, kind: type[N]) -> list[N]:
        """Return each node of `kind` as it stands, of every repository, by number: those of each kind it or a class the ledger reads derived from it declares."""
        kinds = declared(kind, self.kinds.nodes)
        marks = ", ".join("?" for _ in kinds)
        with self.lock:
            rows = self.connection.execute(
                f"{LATEST} WHERE nodes.kind IN ({marks}) ORDER BY nodes.number",
                kinds,
            ).fetchall()
        found = [self.node_read(each, record) for each, record in rows]
        return [each for each in found if isinstance(each, kind)]

    def keeps(self, kind: type[Node]) -> bool:
        """Say whether the ledger keeps a node of `kind`, of any repository: of a kind it or a class the ledger reads derived from it declares."""
        kinds = declared(kind, self.kinds.nodes)
        marks = ", ".join("?" for _ in kinds)
        with self.lock:
            row = self.connection.execute(
                f"{KINDS_HELD} WHERE kind IN ({marks}) LIMIT 1", kinds
            ).fetchone()
        return row is not None

    def cited(self, repository: Path, said: str) -> Node:
        """Return the node of `repository` that `said` names as `@` takes it: its number or its name, with `@` or without.

        Raise `LupLedgerError` where no node of `repository` is that.
        """
        bare = said.removeprefix("@")
        try:
            number = int(bare)
        except ValueError:
            found = self.named(repository, bare)
        else:
            found = self.found(number)
        if found is None or found.repository != repository:
            message = f"no node of {repository} is `{said}`"
            raise LupLedgerError(message)
        return found

    def kept[N: Node](self, node: N, taken: Collection[str] = ()) -> N:
        """Keep `node` as the latest version of its number, its first or a later one, and return it.

        A number the sequence hasn't reached moves it past, so a node made
        elsewhere keeps its number here. `taken` is the names a node of its
        repository can't take beside those its nodes hold: its agents'.

        Raise `LupLedgerError`, keeping nothing, where the version can't follow
        the one before (another kind, another repository, a time not after
        it), its name is another's, or its kind refuses it (`Node.refused`).
        """

        def refusal(earlier: Node | None) -> str | None:
            if earlier is not None and earlier.kind != node.kind:
                return f"it's a `{earlier.kind}`, and stays one"
            if earlier is not None and earlier.repository != node.repository:
                return f"it's of {earlier.repository}, and stays there"
            if earlier is not None and node.at <= earlier.at:
                return (
                    f"this version is at {node.at.isoformat()}, not after its last, "
                    f"at {earlier.at.isoformat()}: each version is written at its "
                    "own time"
                )
            if node.name is None:
                return node.refused(self.found)
            holder = self.named(node.repository, node.name)
            if holder is not None and holder.number != node.number:
                return f"`{node.name}` names @{holder.number} in its repository"
            renamed = earlier is None or earlier.name != node.name
            if renamed and node.name in taken:
                return f"`{node.name}` is an agent's name in its repository"
            return node.refused(self.found)

        with self.writing() as database:
            refused = refusal(self.found(node.number))
            if refused is not None:
                message = f"the ledger can't keep @{node.number}: {refused}"
                raise LupLedgerError(message)
            version = database.execute(
                "INSERT INTO versions (number, kind, record) VALUES (?, ?, ?) "
                "RETURNING version",
                (node.number, node.kind, node.model_dump_json()),
            ).fetchone()[0]
            database.execute(
                "INSERT INTO nodes (number, version, kind, repository, name) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (number) DO UPDATE SET "
                "version = excluded.version, name = excluded.name",
                (node.number, version, node.kind, str(node.repository), node.name),
            )
            database.execute(
                "UPDATE sequence SET next = max(next, ?)", (node.number + 1,)
            )
        return node

    def drawn[E: Edge](self, edge: E) -> E:
        """Draw `edge`, after every edge drawn before it, and return it.

        Raise `LupLedgerError`, drawing nothing, where an end isn't on the
        ledger, is another repository's, or its kind refuses it (`Edge.refused`).
        """

        def refusal() -> str | None:
            target = self.found(edge.target)
            if target is None:
                return f"@{edge.target} isn't on the ledger"
            source = None if edge.source is None else self.found(edge.source)
            if edge.source is not None and source is None:
                return f"@{edge.source} isn't on the ledger"
            ends = [target] if source is None else [source, target]
            strangers = [each for each in ends if each.repository != edge.repository]
            if strangers:
                return (
                    f"@{strangers[0].number} is of {strangers[0].repository}, and "
                    f"the edge of {edge.repository}"
                )
            return edge.refused(source, target)

        with self.writing() as database:
            refused = refusal()
            if refused is not None:
                message = (
                    f"the ledger can't draw a `{edge.kind}` to @{edge.target}: "
                    f"{refused}"
                )
                raise LupLedgerError(message)
            database.execute(
                "INSERT INTO edges (kind, source, target, record) VALUES (?, ?, ?, ?)",
                (edge.kind, edge.source, edge.target, edge.model_dump_json()),
            )
        return edge

    def drawn_to[E: Edge](
        self, target: int, kind: type[E], *, current: bool = False
    ) -> list[E]:
        """Return the edges of `kind` drawn to node `target`, in the order drawn: `Edge` for every edge.

        With `current`, those a later edge from the same node replaced
        (`Edge.replaces`) are left out: a node moved to another thread is in
        that one alone.
        """
        with self.lock:
            rows = self.connection.execute(
                "SELECT drawn, kind, record FROM edges WHERE target = ? ORDER BY drawn",
                (target,),
            ).fetchall()
            found = [
                Drawn(place=place, edge=self.edge_read(each, record))
                for place, each, record in rows
            ]
            held = [each for each in found if not current or self.holds(each)]
        return [each.edge for each in held if isinstance(each.edge, kind)]

    def drawn_from[E: Edge](
        self, source: int, kind: type[E], *, current: bool = False
    ) -> list[E]:
        """Return the edges of `kind` drawn from node `source`, in the order drawn: `Edge` for every edge.

        With `current`, those a later one replaced (`Edge.replaces`) are left out.
        """
        with self.lock:
            found = self.later(source, 0)
            held = [each for each in found if not current or self.holds(each)]
        return [each.edge for each in held if isinstance(each.edge, kind)]

    def drawn_of[E: Edge](self, kind: type[E]) -> list[E]:
        """Return every edge of `kind`, to any node of any repository, in the order drawn: those of each kind it or a class the ledger reads derived from it declares."""
        kinds = declared(kind, self.kinds.edges)
        marks = ", ".join("?" for _ in kinds)
        with self.lock:
            rows = self.connection.execute(
                f"{EDGES} WHERE kind IN ({marks}) ORDER BY drawn", kinds
            ).fetchall()
        found = [self.edge_read(each, record) for each, record in rows]
        return [each for each in found if isinstance(each, kind)]

    def later(self, source: int, place: int) -> list[Drawn]:
        """Return the edges drawn from node `source` after `place` in the order drawn, in that order."""
        rows = self.connection.execute(
            "SELECT drawn, kind, record FROM edges WHERE source = ? AND drawn > ? "
            "ORDER BY drawn",
            (source, place),
        ).fetchall()
        return [
            Drawn(place=each, edge=self.edge_read(kind, record))
            for each, kind, record in rows
        ]

    def holds(self, drawn: Drawn) -> bool:
        """Say whether no edge drawn later from the same node replaced `drawn`."""
        source = drawn.edge.source
        if source is None:
            return True
        return not any(
            each.edge.replaces(drawn.edge) for each in self.later(source, drawn.place)
        )

    def plain[M: BaseModel](self, name: str, model: type[M]) -> M | None:
        """Return the plain record named `name`, as `model`; none where none is kept.

        Raise `LupLedgerError` where the one kept doesn't read as `model`.
        """
        with self.lock:
            row = self.connection.execute(
                "SELECT record FROM records WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            return None
        try:
            return model.model_validate_json(row[0])
        except ValidationError as unread:
            message = f"the ledger's record `{name}` doesn't read: {unread}"
            raise LupLedgerError(message) from unread

    def plains[M: BaseModel](self, prefix: str, model: type[M]) -> dict[str, M]:
        """Return each plain record whose name starts with `prefix`, as `model`, by its name, in its name's order.

        Its names are read as a range of the index, from `prefix` to `prefix`
        followed by the last code point, so no read walks the table. Raise
        `LupLedgerError` where one doesn't read as `model`.
        """
        beyond = f"{prefix}\U0010ffff"
        with self.lock:
            rows = self.connection.execute(
                "SELECT name, record FROM records WHERE name >= ? AND name < ? "
                "ORDER BY name",
                (prefix, beyond),
            ).fetchall()
        try:
            return {name: model.model_validate_json(record) for name, record in rows}
        except ValidationError as unread:
            message = f"a plain record named `{prefix}…` doesn't read: {unread}"
            raise LupLedgerError(message) from unread

    def rewritten(self, name: str, value: BaseModel) -> None:
        """Keep `value` as the plain record named `name`, in place of the one before: no version of it stays."""
        with self.writing() as database:
            database.execute(
                "INSERT INTO records (name, record) VALUES (?, ?) "
                "ON CONFLICT (name) DO UPDATE SET record = excluded.record",
                (name, value.model_dump_json()),
            )

    def attached(self, data: bytes) -> str:
        """Keep `data` beside the database, once however many records attach it, and return its digest, which a record names it by.

        Written whole under another name, then renamed into place, so an
        attachment is never read half written.
        """
        digest = hashlib.sha256(data).hexdigest()
        path = self.layout.attachment(digest)
        if path.is_file():
            return digest
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f"{digest}.", delete=False
        ) as partial:
            partial.write(data)
        Path(partial.name).replace(path)
        return digest

    def attachment(self, digest: str) -> bytes | None:
        """Return the attachment named by `digest`; none where none is kept."""
        path = self.layout.attachment(digest)
        return path.read_bytes() if path.is_file() else None
