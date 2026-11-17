"""The store's database: every repository's nodes and edges, in one SQLite file.

`lup/store/README.md`, *The store*.
- **Two sequences.** Every node gets a key, the store's own, which edges and
  other nodes name it by. A node of a numbered kind also gets a number from one
  sequence for every repository, cited `@12`, so a party made never moves the
  numbers the operator reads.
- **Every version kept.** A change appends the node again, at its own time,
  never before the version it follows (`kept`); a read takes the latest, and
  `versions` reads them all. Order is the store's own: what came after what is
  read from keys and the order drawn, never from times, which say when.
- **Edges are drawn, never changed** (`drawn`), each read in the order drawn.
- **Indexed, so no read walks the store:** a node's latest version is one row
  of `nodes`, found by its key, its number, its repository and kind, or its
  name; its versions by its key; an edge by the node it's drawn to or from.
- **One connection, behind one lock:** a write is one transaction, `writing`
  holds one across several writes so they're kept together or not at all, and
  `together` holds the lock across several reads so they see one state.
- **Plain records** beside the graph: what's rewritten in place by its name,
  with no version and no key, such as a draft that changes at every pause in
  typing (`plain`, `rewritten`).
"""

import sqlite3
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError

from lup.store.errors import StoreError
from lup.store.records import Edge, Kinds, Node, Record
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

SCHEMA = """
CREATE TABLE sequence (next INTEGER NOT NULL);
INSERT INTO sequence (next) VALUES (1);
CREATE TABLE versions (
    version INTEGER PRIMARY KEY,
    key INTEGER NOT NULL,
    kind TEXT NOT NULL,
    record TEXT NOT NULL
);
CREATE INDEX versions_of ON versions (key, version);
CREATE TABLE nodes (
    key INTEGER PRIMARY KEY,
    version INTEGER NOT NULL,
    kind TEXT NOT NULL,
    repository TEXT NOT NULL,
    number INTEGER UNIQUE,
    name TEXT
);
CREATE INDEX nodes_of ON nodes (repository, kind, key);
CREATE INDEX nodes_kinds ON nodes (kind, key);
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
CREATE INDEX edges_kinds ON edges (kind, drawn);
CREATE TABLE records (name TEXT PRIMARY KEY, record TEXT NOT NULL);
"""
"""The tables of version 1: the next number cited; each version of each node, in
the order kept; each node's latest version, with what it's found by; each edge,
in the order drawn; and the plain records, each by its name."""

LATEST = (
    "SELECT versions.kind, versions.record FROM nodes "
    "JOIN versions ON versions.version = nodes.version"
)
"""Each node's latest version, which a read narrows by what `nodes` indexes."""

EDGES = "SELECT kind, record FROM edges"
"""Each edge, which a read narrows by what `edges` indexes."""


def upgrade(found: int) -> str | None:
    """Return what makes a database at version `found` of the tables the one after it; none where no version follows.

    >>> upgrade(0) == SCHEMA, upgrade(1)
    (True, None)
    """
    match found:
        case 0:
            return SCHEMA
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
    """An edge as the store holds it: where it is in the order drawn, and the edge."""

    place: int
    edge: Edge


class Database(Model, arbitrary_types_allowed=True):
    """The store's database, open: every repository's nodes and edges.

    Safe to share between threads: each call takes the lock, and a write is one
    transaction. A record of a kind `kinds` doesn't declare reads as the base
    class, every field it held kept.

    >>> from datetime import UTC, datetime
    >>> store = Database.opened(":memory:", Kinds())
    >>> node = Node(kind="example:note", repository="lup", by=None, at=datetime(2026, 1, 1, tzinfo=UTC))
    >>> kept = store.kept(node)
    >>> kept.key, kept.number, store.found(kept.key) == kept
    (1, None, True)
    """

    connection: sqlite3.Connection
    kinds: Kinds
    lock: threading.RLock = Field(default_factory=threading.RLock)
    """Held for each call, and across several by `together`; reentrant, so a
    kind's refusal reads the store while a write holds it."""

    @classmethod
    def opened(cls, database: Path | str, kinds: Kinds, schema: int = 1) -> Database:
        """Open the store kept at `database`, making it where there's none, its records read as `kinds` declares them; `":memory:"` for one kept nowhere.

        `schema` is the version of the tables this code reads, kept in the
        database's `user_version`: a database at an earlier one is brought to
        it in one transaction (`upgrade`). Raise `StoreError` where the
        database is at a later one.

        Its write-ahead log is synced at each checkpoint rather than at each
        transaction (`synchronous = NORMAL`): a transaction may be lost to a
        power cut, never to the program's crash.
        """
        connection = sqlite3.connect(database, autocommit=True, check_same_thread=False)
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
                f"the store at {database} is at version {found} of its tables, and "
                f"this lup reads version {schema}"
            )
            raise StoreError(message)
        return cls(connection=connection, kinds=kinds)

    def close(self) -> None:
        """Close the database; the store can't be used after."""
        with self.lock:
            self.connection.close()

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
        where the outer one ends.
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

    def node_read(self, kind: str, record: str) -> Node:
        """Read a node's `record`, of `kind`, as the class declaring its kind, or `Node`; raise `StoreError` where it doesn't read."""
        try:
            return self.kinds.node(kind).model_validate_json(record)
        except ValidationError as unread:
            message = f"a `{kind}` the store holds doesn't read: {unread}"
            raise StoreError(message) from unread

    def edge_read(self, kind: str, record: str) -> Edge:
        """Read an edge's `record`, of `kind`, as the class declaring its kind, or `Edge`; raise `StoreError` where it doesn't read."""
        try:
            return self.kinds.edge(kind).model_validate_json(record)
        except ValidationError as unread:
            message = f"a `{kind}` the store holds doesn't read: {unread}"
            raise StoreError(message) from unread

    def found(self, key: int) -> Node | None:
        """Return node `key` as it stands, its latest version; none where the store holds none."""
        with self.lock:
            row = self.connection.execute(
                f"{LATEST} WHERE nodes.key = ?", (key,)
            ).fetchone()
        return None if row is None else self.node_read(row[0], row[1])

    def node[N: Node](self, key: int, kind: type[N]) -> N:
        """Return node `key` as it stands, as `kind`: `Node` for any.

        Raise `StoreError` where the store holds none, or one of another kind.
        """
        found = self.found(key)
        if found is None:
            message = f"the store holds no node of key {key}"
            raise StoreError(message)
        if not isinstance(found, kind):
            message = f"node {key} is a `{found.kind}`, not a `{kind.declared()}`"
            raise StoreError(message)
        return found

    def numbered(self, number: int) -> Node | None:
        """Return the node cited `@number` as it stands; none where none is."""
        with self.lock:
            row = self.connection.execute(
                f"{LATEST} WHERE nodes.number = ?", (number,)
            ).fetchone()
        return None if row is None else self.node_read(row[0], row[1])

    def named(self, repository: str, name: str) -> Node | None:
        """Return the node of `repository` named `name`, as it stands; none where none is."""
        with self.lock:
            row = self.connection.execute(
                f"{LATEST} WHERE nodes.repository = ? AND nodes.name = ?",
                (repository, name),
            ).fetchone()
        return None if row is None else self.node_read(row[0], row[1])

    def versions(self, key: int) -> list[Node]:
        """Return every version of node `key`, oldest first; none where the store holds none."""
        with self.lock:
            rows = self.connection.execute(
                "SELECT kind, record FROM versions WHERE key = ? ORDER BY version",
                (key,),
            ).fetchall()
        return [self.node_read(kind, record) for kind, record in rows]

    def nodes[N: Node](self, repository: str, kind: type[N]) -> list[N]:
        """Return each node of `repository` of `kind` as it stands, in the order first kept: those of each kind it or a class the store reads derived from it declares."""
        with self.lock:
            rows = self.connection.execute(
                f"{LATEST} WHERE nodes.repository = ? ORDER BY nodes.key",
                (repository,),
            ).fetchall()
        kinds = declared(kind, self.kinds.nodes)
        found = [
            self.node_read(each, record)
            for each, record in rows
            if kind.declared() is None or each in kinds
        ]
        return [each for each in found if isinstance(each, kind)]

    def every[N: Node](self, kind: type[N]) -> list[N]:
        """Return each node of `kind` as it stands, of every repository, in the order first kept."""
        kinds = declared(kind, self.kinds.nodes)
        marks = ", ".join("?" for _ in kinds)
        with self.lock:
            rows = self.connection.execute(
                f"{LATEST} WHERE nodes.kind IN ({marks}) ORDER BY nodes.key", kinds
            ).fetchall()
        found = [self.node_read(each, record) for each, record in rows]
        return [each for each in found if isinstance(each, kind)]

    def kept[N: Node](self, node: N) -> N:
        """Keep `node`, as a new node where its key is 0, or as the latest version of its key, and return it as kept.

        A new node is given the next key, and the next number where its kind is
        numbered. Raise `StoreError`, keeping nothing, where the version can't
        follow the one before (another kind, another repository, a time before
        it, a key the store doesn't hold), its name is another node's, or
        its kind refuses it (`Node.refused`).
        """
        with self.writing() as database:
            earlier = None if node.key == 0 else self.found(node.key)
            refused = self.refusal(node, earlier)
            if refused is not None:
                message = f"the store can't keep this `{node.kind}`: {refused}"
                raise StoreError(message, about=[node.kind])
            if earlier is None:
                number = None
                if type(node).numbered:
                    number = database.execute(
                        "UPDATE sequence SET next = next + 1 RETURNING next - 1"
                    ).fetchone()[0]
                key = database.execute(
                    "INSERT INTO nodes (version, kind, repository, number, name) "
                    "VALUES (0, ?, ?, ?, ?) RETURNING key",
                    (node.kind, node.repository, number, node.name),
                ).fetchone()[0]
                node = node.model_copy(update={"key": key, "number": number})
            else:
                node = node.model_copy(update={"number": earlier.number})
            version = database.execute(
                "INSERT INTO versions (key, kind, record) VALUES (?, ?, ?) "
                "RETURNING version",
                (node.key, node.kind, node.model_dump_json()),
            ).fetchone()[0]
            database.execute(
                "UPDATE nodes SET version = ?, name = ? WHERE key = ?",
                (version, node.name, node.key),
            )
        return node

    def refusal(self, node: Node, earlier: Node | None) -> str | None:
        """Say why `node` can't be kept after `earlier`, its last version; none where it can."""
        if node.key != 0 and earlier is None:
            return f"the store holds no node of key {node.key} to keep a version of"
        if earlier is not None and earlier.kind != node.kind:
            return f"it's a `{earlier.kind}`, and stays one"
        if earlier is not None and earlier.repository != node.repository:
            return f"it's of {earlier.repository}, and stays there"
        if earlier is not None and node.at < earlier.at:
            return (
                f"this version is at {node.at.isoformat()}, before its last, at "
                f"{earlier.at.isoformat()}: a version is never older than the one "
                "it follows"
            )
        if node.name is not None:
            holder = self.named(node.repository, node.name)
            if holder is not None and holder.key != node.key:
                return f"`{node.name}` names another node in {node.repository}"
        return node.refused(self.found)

    def drawn[E: Edge](self, edge: E) -> E:
        """Draw `edge`, after every edge drawn before it, and return it.

        Its ends may be of different repositories, as a friction said in one
        project's session lands in another's pile; who may write into which is
        the store's caller's to check. Raise `StoreError`, drawing nothing,
        where an end isn't in the store or its kind refuses it (`Edge.refused`).
        """

        def refusal() -> str | None:
            target = self.found(edge.target)
            if target is None:
                return f"its target, node {edge.target}, isn't kept"
            source = None if edge.source is None else self.found(edge.source)
            if edge.source is not None and source is None:
                return f"its source, node {edge.source}, isn't kept"
            return edge.refused(source, target)

        with self.writing() as database:
            refused = refusal()
            if refused is not None:
                message = f"the store can't draw a `{edge.kind}`: {refused}"
                raise StoreError(message, about=[edge.kind])
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
        (`Edge.replaces`) are left out: a concern moved to another party is
        under that one alone.
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
        """Return every edge of `kind`, to any node of any repository, in the order drawn."""
        kinds = declared(kind, self.kinds.edges)
        marks = ", ".join("?" for _ in kinds)
        with self.lock:
            rows = self.connection.execute(
                f"{EDGES} WHERE kind IN ({marks}) ORDER BY drawn",
                kinds,
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

        Raise `StoreError` where the one kept doesn't read as `model`.
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
            message = f"the store's record `{name}` doesn't read: {unread}"
            raise StoreError(message) from unread

    def rewritten(self, name: str, value: BaseModel) -> None:
        """Keep `value` as the plain record named `name`, in place of the one before: no version of it stays."""
        with self.writing() as database:
            database.execute(
                "INSERT INTO records (name, record) VALUES (?, ?) "
                "ON CONFLICT (name) DO UPDATE SET record = excluded.record",
                (name, value.model_dump_json()),
            )
