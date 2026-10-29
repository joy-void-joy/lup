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
  in a thread of its own: a write is one transaction, and `together` holds the
  lock across several reads so they see one state.
"""

import sqlite3
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

from pydantic import Field, ValidationError

from lup.types import Model
from lup_ledger.errors import LupLedgerError
from lup_ledger.records import Edge, Kinds, Node
from lup_ledger.threads import KINDS

if TYPE_CHECKING:
    from collections.abc import Collection, Generator
    from pathlib import Path

    from lup_ledger.environment.layout import LedgerLayout

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
"""The tables: the sequence's next number; each version of each node, in the
order kept; each node's latest version, with what it's found by; each edge, in
the order drawn."""

LATEST = (
    "SELECT versions.kind, versions.record FROM nodes "
    "JOIN versions ON versions.version = nodes.version"
)
"""Each node's latest version, which a read narrows by what `nodes` indexes."""


class Drawn(Model):
    """An edge as the ledger holds it: where it is in the order drawn, and the edge."""

    place: int
    edge: Edge


class Ledger(Model, arbitrary_types_allowed=True):
    """The ledger's store, open: every repository's nodes and edges, read and written by the host service.

    Safe to share between threads: each call takes the lock, and a write is one
    transaction. A record of a kind `kinds` doesn't declare reads as the base
    class, every field it held kept.
    """

    connection: sqlite3.Connection
    kinds: Kinds
    lock: threading.RLock = Field(default_factory=threading.RLock)
    """Held for each call, and across several by `together`; reentrant, so a
    kind's refusal reads the ledger while a write holds it."""

    @classmethod
    def opened(
        cls,
        layout: LedgerLayout,
        # lup: defer(issue=343, why="a module's own kinds join the ledger's here, once a module can declare them")
        kinds: Kinds = KINDS,
        schema: int = 1,
    ) -> Ledger:
        """Open the ledger kept at `layout`, making it where there's none, its records read as `kinds` declares them.

        `schema` is the version of the tables this code reads, kept in the
        database's `user_version`. Raise `LupLedgerError` where the database is
        at another.
        """
        layout.home.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            layout.database, autocommit=True, check_same_thread=False
        )
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("BEGIN IMMEDIATE")
        made = False
        try:
            found = connection.execute("PRAGMA user_version").fetchone()[0]
            if found == 0:
                connection.executescript(f"{SCHEMA}PRAGMA user_version = {schema};")
            made = True
        finally:
            connection.execute("COMMIT" if made else "ROLLBACK")
        if found not in (0, schema):
            connection.close()
            message = (
                f"the ledger at {layout.database} is at version {found} of its "
                f"tables, and this lup reads version {schema}"
            )
            raise LupLedgerError(message)
        return cls(connection=connection, kinds=kinds)

    def close(self) -> None:
        """Close the database; the ledger can't be used after."""
        with self.lock:
            self.connection.close()

    @contextmanager
    def together(self) -> Generator[None]:
        """Hold the lock across several calls, so what they read is one state: none is written between them."""
        with self.lock:
            yield

    @contextmanager
    def writing(self) -> Generator[sqlite3.Connection]:
        """Hold the lock and a transaction across a write: committed where it ends, rolled back where it raises."""
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            done = False
            try:
                yield self.connection
                done = True
            finally:
                self.connection.execute("COMMIT" if done else "ROLLBACK")

    def numbered(self) -> int:
        """Take the sequence's next number, for a node about to be kept; none is ever taken twice."""
        # lup: defer(issue=345, why="the inbox numbers its items itself until they're nodes; then they're numbered here, and the items already made keep their numbers, which `kept` moves the sequence past")
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
