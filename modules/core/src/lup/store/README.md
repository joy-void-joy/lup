# The store

Where modules keep what must outlast a call: typed records, every version kept, in one SQLite database for every repository. It's the core's, and a module's records are kinds it declares.

```python
from lup import Module, Node, Recorded


class Note(Node):
    """A note a module keeps."""

    kind: str = "notes:note"
    numbered = True
    text: str


class Notes(Module):
    """Keeping notes."""

    name = "notes"
    kinds: Recorded = Recorded.of(Note)
```

## Records

- **A node** (`Node`) is something kept: every version of it, the latest being the node as it stands. It has a key, the store's own, which edges and other nodes name it by, and a name where its kind gives one, unique in its repository, which `@` takes. A node of a numbered kind (`numbered = True`) also has a number from one sequence for every repository, cited `@12`; other kinds don't take one, so a party made never moves the numbers the operator reads.
- **An edge** (`Edge`) joins two nodes, or says something of one: never changed once drawn, read in the order drawn. A later edge from the same node can take an earlier one's place where its kind says so (`Edge.replaces`), as moving a concern draws a later place rather than changing one. Its ends may be of different repositories, as a friction said in one project's session lands in another's pile.
- **Where a node stands is read from the edges drawn to it, never stored on it:** a status kept on a record outlives what justified it.
- **Each record says** its kind, its repository, who wrote it (a party's name, or none for lup itself) and when. A time says when; what came after what is the store's own order, a key's and an edge's place, so two acts in one moment keep their order.
- **A kind** is a subclass whose `kind` field's default names it, namespaced by its module (`inbox:concern`). A record of a kind no loaded class declares reads as the base class, every field it held kept, never refused or dropped, so an earlier lup, or one without the module, reads it and writes it back whole.
- **A kind refuses what it can't be:** a node as it's kept (`Node.refused`), an edge, which alone sees both its ends, as it's drawn (`Edge.refused`).

A module lists its kinds in a `Recorded` field, a selection as `Parts` is. Resolving a declaration gathers every module's (`Resolved.kinds`), and a kind two modules declare fails the load, naming both, rather than one reading the other's records as its own.

## The database

`Database` is one SQLite file, or one kept nowhere (`":memory:"`):
- **Every version kept.** `kept` adds a node, giving it its key and, for a numbered kind, its number, or appends a version of one, never older than the one it follows; `versions` reads them all.
- **Indexed, so no read walks it:** a node's latest version is one row, found by its key, its number, its repository and kind, or its name; an edge by the node it's drawn to or from, or by its kind.
- **One connection, behind one lock:** a write is one transaction, `writing` holds one across several so they're kept together or not at all, each inside it a savepoint, and `together` holds the lock across several reads, so they see one state.
- **Synced at checkpoints:** in write-ahead mode with `synchronous = NORMAL`, a transaction can be lost to a power cut, never to the program's crash.
- **Plain records** beside the graph: what's rewritten in place by its name, with no version and no key, as a draft changing at every pause in typing.
- **Its tables' version** is kept in the database: an earlier one is brought up to date as it opens, and a later one is refused.

What runs the database, and how a module's code reaches it from its own container, is #3's: the store is a class holding the database, its methods called through `@lup.service`.
