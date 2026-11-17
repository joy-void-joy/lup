"""The store's database: every repository's nodes and edges, in one SQLite file.

`README.md` here, *The database*. Its tables are declared once, as SQLAlchemy's
`Table`s, and every query is built from them, so no statement is put together
from strings and the queries can't drift from the tables.
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
  name; its versions by its key; an edge by the node it's drawn to or from, or
  its kind.
- **One connection, behind one lock:** every call is one transaction,
  `writing` holds one across several so they're kept together or not at all,
  each inside it a savepoint, and `together` holds the lock across several
  reads, so they see one state.
- **Plain records** beside the graph: what's rewritten in place by its name,
  with no version and no key, such as a draft that changes at every pause in
  typing (`plain`, `rewritten`).
"""

import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import (
    Column,
    Connection,
    Index,
    Integer,
    MetaData,
    Row,
    Select,
    String,
    Table,
    Text,
    create_engine,
    event,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.pool import StaticPool

from lup.store.errors import StoreError
from lup.store.records import Edge, Kinds, Node, Record
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path
    from sqlite3 import Connection as Driver

    from sqlalchemy.pool import ConnectionPoolEntry

TABLES = MetaData()
"""The store's tables, version 1 of them."""

SEQUENCE = Table("sequence", TABLES, Column("next", Integer, nullable=False))
"""The next number cited, one row."""

VERSIONS = Table(
    "versions",
    TABLES,
    Column("version", Integer, primary_key=True),
    Column("key", Integer, nullable=False),
    Column("kind", String, nullable=False),
    Column("record", Text, nullable=False),
    Index("versions_of", "key", "version"),
)
"""Each version of each node, in the order kept."""

NODES = Table(
    "nodes",
    TABLES,
    Column("key", Integer, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("kind", String, nullable=False),
    Column("repository", String, nullable=False),
    Column("number", Integer, unique=True),
    Column("name", String),
    Index("nodes_of", "repository", "kind", "key"),
    Index("nodes_kinds", "kind", "key"),
    Index(
        "nodes_named",
        "repository",
        "name",
        unique=True,
        sqlite_where=Column("name").is_not(None),
    ),
)
"""Each node's latest version, with what it's found by."""

EDGES = Table(
    "edges",
    TABLES,
    Column("drawn", Integer, primary_key=True),
    Column("kind", String, nullable=False),
    Column("source", Integer),
    Column("target", Integer, nullable=False),
    Column("record", Text, nullable=False),
    Index("edges_to", "target", "drawn"),
    Index("edges_from", "source", "drawn"),
    Index("edges_kinds", "kind", "drawn"),
)
"""Each edge, in the order drawn."""

PLAIN = Table(
    "records",
    TABLES,
    Column("name", String, primary_key=True),
    Column("record", Text, nullable=False),
)
"""The plain records, each by its name."""


def latest() -> Select[str, str]:
    """Return the query reading each node's latest version, kind and record, which a read narrows by what `nodes` indexes."""
    return select(VERSIONS.c.kind, VERSIONS.c.record).join(
        NODES, VERSIONS.c.version == NODES.c.version
    )


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

    Safe to share between threads: each call takes the lock, and is one
    transaction. A record of a kind `kinds` doesn't declare reads as the base
    class, every field it held kept.

    >>> from datetime import UTC, datetime
    >>> store = Database.opened(":memory:", Kinds())
    >>> node = Node(kind="example:note", repository="lup", by=None, at=datetime(2026, 1, 1, tzinfo=UTC))
    >>> kept = store.kept(node)
    >>> kept.key, kept.number, store.found(kept.key) == kept
    (1, None, True)
    """

    connection: Connection
    kinds: Kinds
    lock: threading.RLock = Field(default_factory=threading.RLock)
    """Held for each call, and across several by `together`; reentrant, so a
    kind's refusal reads the store while a write holds it."""

    @classmethod
    def opened(cls, database: Path | str, kinds: Kinds, schema: int = 1) -> Database:
        """Open the store kept at `database`, making it where there's none, its records read as `kinds` declares them; `":memory:"` for one kept nowhere.

        `schema` is the version of the tables this code reads, kept in the
        database's `user_version`: a database at none of them gets them, and
        one at a later one is refused with `StoreError`.

        Its write-ahead log is synced at each checkpoint rather than at each
        transaction (`synchronous = NORMAL`): a transaction may be lost to a
        power cut, never to the program's crash.
        """
        engine = create_engine(
            f"sqlite:///{database}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine, "connect")
        def connected(driver: Driver, _entry: ConnectionPoolEntry) -> None:
            """Leave beginning each transaction to SQLAlchemy, so savepoints nest, and set the journal."""
            driver.isolation_level = None
            driver.execute("PRAGMA journal_mode = WAL")
            driver.execute("PRAGMA synchronous = NORMAL")

        @event.listens_for(engine, "begin")
        def began(connection: Connection) -> None:
            """Begin each transaction holding the write lock, so two never read a state the other is about to change."""
            connection.exec_driver_sql("BEGIN IMMEDIATE")

        connection = engine.connect()
        with connection.begin():
            found = connection.exec_driver_sql("PRAGMA user_version").scalar_one()
            if found == 0:
                TABLES.create_all(connection)
                connection.execute(insert(SEQUENCE).values(next=1))
                connection.exec_driver_sql(f"PRAGMA user_version = {schema}")
        if found > schema:
            connection.close()
            message = (
                f"the store at {database} is at version {found} of its tables, and "
                f"this lup reads version {schema}"
            )
            raise StoreError(message)
        return cls(connection=connection, kinds=kinds)

    def close(self) -> None:
        """Close the database, and what opened it; the store can't be used after."""
        with self.lock:
            self.connection.close()
            self.connection.engine.dispose()

    @contextmanager
    def together(self) -> Generator[None]:
        """Hold the lock and one transaction across several calls, so what they read is one state: none is written between them."""
        with self.writing():
            yield

    @contextmanager
    def writing(self) -> Generator[Connection]:
        """Hold the lock and a transaction across a write, or several: committed where it ends, rolled back where it raises.

        Within another, it's a savepoint of that one: what's written inside is
        undone alone where it raises, and kept or rolled back with the rest
        where the outer one ends.
        """
        with self.lock:
            begun = (
                self.connection.begin_nested()
                if self.connection.in_transaction()
                else self.connection.begin()
            )
            with begun:
                yield self.connection

    def node_read(self, row: Row[str, str]) -> Node:
        """Read a node from its row, kind and record, as the class declaring its kind, or `Node`; raise `StoreError` where it doesn't read."""
        kind, record = row
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

    def one(self, query: Select[str, str]) -> Node | None:
        """Return the node `query` finds, as it stands; none where it finds none."""
        with self.writing() as database:
            row = database.execute(query).first()
        return None if row is None else self.node_read(row)

    def found(self, key: int) -> Node | None:
        """Return node `key` as it stands, its latest version; none where the store holds none."""
        return self.one(latest().where(NODES.c.key == key))

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

    def numbered(self, number: int, beyond: int = 2**63) -> Node | None:
        """Return the node cited `@number` as it stands; none where none is, a number from `beyond`, past what SQLite keeps as an integer, among them."""
        if not 1 <= number < beyond:
            return None
        return self.one(latest().where(NODES.c.number == number))

    def named(self, repository: str, name: str) -> Node | None:
        """Return the node of `repository` named `name`, as it stands; none where none is."""
        return self.one(
            latest().where(NODES.c.repository == repository, NODES.c.name == name)
        )

    def repositories(self) -> list[str]:
        """Return every repository the store holds a node of, in the order first kept."""
        query = (
            select(NODES.c.repository)
            .group_by(NODES.c.repository)
            .order_by(func.min(NODES.c.key))
        )
        with self.writing() as database:
            return list(database.execute(query).scalars())

    def versions(self, key: int) -> list[Node]:
        """Return every version of node `key`, oldest first; none where the store holds none."""
        query = (
            select(VERSIONS.c.kind, VERSIONS.c.record)
            .where(VERSIONS.c.key == key)
            .order_by(VERSIONS.c.version)
        )
        with self.writing() as database:
            rows = database.execute(query).all()
        return [self.node_read(row) for row in rows]

    def nodes[N: Node](self, repository: str, kind: type[N]) -> list[N]:
        """Return each node of `repository` of `kind` as it stands, in the order first kept: those of each kind it or a class the store reads derived from it declares, or every node for `Node`."""
        query = latest().where(NODES.c.repository == repository).order_by(NODES.c.key)
        if kind.declared() is not None:
            query = query.where(NODES.c.kind.in_(declared(kind, self.kinds.nodes)))
        with self.writing() as database:
            rows = database.execute(query).all()
        found = [self.node_read(row) for row in rows]
        return [each for each in found if isinstance(each, kind)]

    def every[N: Node](self, kind: type[N]) -> list[N]:
        """Return each node of `kind` as it stands, of every repository, in the order first kept."""
        query = (
            latest()
            .where(NODES.c.kind.in_(declared(kind, self.kinds.nodes)))
            .order_by(NODES.c.key)
        )
        with self.writing() as database:
            rows = database.execute(query).all()
        found = [self.node_read(row) for row in rows]
        return [each for each in found if isinstance(each, kind)]

    def kept[N: Node](self, node: N) -> N:
        """Keep `node`, as a new node where its key is 0, or as the latest version of its key, and return it as kept.

        A new node is given the next key, and the next number where its kind is
        numbered. Raise `StoreError`, keeping nothing, where the version can't
        follow the one before (another kind, another repository, a time before
        it, a key the store doesn't hold), its name is another node's, or its
        kind refuses it (`Node.refused`).
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
                        update(SEQUENCE)
                        .values(next=SEQUENCE.c.next + 1)
                        .returning(SEQUENCE.c.next - 1)
                    ).scalar_one()
                key = database.execute(
                    insert(NODES)
                    .values(
                        version=0,
                        kind=node.kind,
                        repository=node.repository,
                        number=number,
                        name=node.name,
                    )
                    .returning(NODES.c.key)
                ).scalar_one()
                node = node.model_copy(update={"key": key, "number": number})
            else:
                node = node.model_copy(update={"number": earlier.number})
            version = database.execute(
                insert(VERSIONS)
                .values(key=node.key, kind=node.kind, record=node.model_dump_json())
                .returning(VERSIONS.c.version)
            ).scalar_one()
            database.execute(
                update(NODES)
                .where(NODES.c.key == node.key)
                .values(version=version, name=node.name)
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
                insert(EDGES).values(
                    kind=edge.kind,
                    source=edge.source,
                    target=edge.target,
                    record=edge.model_dump_json(),
                )
            )
        return edge

    def placed(self, query: Select[int, str, str]) -> list[Drawn]:
        """Return the edges `query` finds, each with its place, in the order drawn."""
        with self.writing() as database:
            rows = database.execute(query.order_by(EDGES.c.drawn)).all()
        return [
            Drawn(place=place, edge=self.edge_read(kind, record))
            for place, kind, record in rows
        ]

    def drawn_to[E: Edge](
        self, target: int, kind: type[E], *, current: bool = False
    ) -> list[E]:
        """Return the edges of `kind` drawn to node `target`, in the order drawn: `Edge` for every edge.

        With `current`, those a later edge from the same node replaced
        (`Edge.replaces`) are left out: a concern moved to another party is
        under that one alone.
        """
        query = select(EDGES.c.drawn, EDGES.c.kind, EDGES.c.record).where(
            EDGES.c.target == target
        )
        with self.writing():
            found = self.placed(query)
            held = [each for each in found if not current or self.holds(each)]
        return [each.edge for each in held if isinstance(each.edge, kind)]

    def drawn_from[E: Edge](
        self, source: int, kind: type[E], *, current: bool = False
    ) -> list[E]:
        """Return the edges of `kind` drawn from node `source`, in the order drawn: `Edge` for every edge.

        With `current`, those a later one replaced (`Edge.replaces`) are left out.
        """
        with self.writing():
            found = self.later(source, 0)
            held = [each for each in found if not current or self.holds(each)]
        return [each.edge for each in held if isinstance(each.edge, kind)]

    def drawn_of[E: Edge](self, kind: type[E]) -> list[E]:
        """Return every edge of `kind`, to any node of any repository, in the order drawn."""
        query = select(EDGES.c.drawn, EDGES.c.kind, EDGES.c.record).where(
            EDGES.c.kind.in_(declared(kind, self.kinds.edges))
        )
        return [each.edge for each in self.placed(query) if isinstance(each.edge, kind)]

    def later(self, source: int, place: int) -> list[Drawn]:
        """Return the edges drawn from node `source` after `place` in the order drawn, in that order."""
        return self.placed(
            select(EDGES.c.drawn, EDGES.c.kind, EDGES.c.record).where(
                EDGES.c.source == source, EDGES.c.drawn > place
            )
        )

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
        with self.writing() as database:
            record = database.execute(
                select(PLAIN.c.record).where(PLAIN.c.name == name)
            ).scalar_one_or_none()
        if record is None:
            return None
        try:
            return model.model_validate_json(record)
        except ValidationError as unread:
            message = f"the store's record `{name}` doesn't read: {unread}"
            raise StoreError(message) from unread

    def rewritten(self, name: str, value: BaseModel) -> None:
        """Keep `value` as the plain record named `name`, in place of the one before: no version of it stays."""
        with self.writing() as database:
            changed = database.execute(
                update(PLAIN)
                .where(PLAIN.c.name == name)
                .values(record=value.model_dump_json())
            )
            if changed.rowcount == 0:
                database.execute(
                    insert(PLAIN).values(name=name, record=value.model_dump_json())
                )
