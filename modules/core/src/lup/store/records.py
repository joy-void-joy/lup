"""What the store holds: nodes, the edges between them, and the kinds each is read as.

A node is something a module keeps: a concern, an item, a party. Every version
of it is kept, the latest being the node as it stands. An edge joins two nodes,
or says something of one: an item in a concern, a concern cleared. Each kind is
a subclass of `Node` or `Edge` whose `kind` field's default is a namespaced name
(`inbox:concern`), stored on the record, so a reader that loaded no class for it
still says what it met: such a record reads as the base class, every field it
held kept, never refused or dropped.

Where a node stands is read from the edges drawn to it, never stored on it: a
status kept on a record outlives what justified it (`README.md` here, *Records*).
"""

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Annotated, ClassVar, Self, override

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from lup.declaration.grammar import Named
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Callable


def named(name: str, longest: int = 64) -> str:
    """Return `name` if a node can take it: segments of letters, digits, `-`, `_` and `.`, each holding a letter and not starting with `-`, joined by `/`, at most `longest` long.

    A segment's letter is what lets `@` take a name or a number alike: no name
    reads as a node's number or a part's id. `/` nests a name under another's,
    as a pile is named under the party holding it.

    >>> named("frictions/dashboard-lag")
    'frictions/dashboard-lag'
    >>> named("2159.3")
    Traceback (most recent call last):
    ...
    ValueError: a name is segments of letters, digits, `-`, `_` and `.`, each holding a letter and not starting with `-`, joined by `/`, at most 64 long: not '2159.3'
    """
    parsed = PurePosixPath(name)
    segments = parsed.parts
    fit = all(
        segment
        and all(each.isalnum() or each in "-_." for each in segment)
        and any(each.isalpha() for each in segment)
        and not segment.startswith("-")
        for segment in segments
    )
    if not fit or str(parsed) != name or parsed.is_absolute() or len(name) > longest:
        message = (
            "a name is segments of letters, digits, `-`, `_` and `.`, each holding "
            "a letter and not starting with `-`, joined by `/`, at most "
            f"{longest} long: not {name!r}"
        )
        raise ValueError(message)
    return name


type Name = Annotated[str, AfterValidator(named)]
"""A node's name, which `@` takes beside a number: unique among its repository's names."""


class Record(Model, extra="allow"):
    """What every node and edge carries: its kind, its repository, who wrote it, and when.

    A field a record holds that its class doesn't declare is kept, so a record
    read as a base class, its kind's class not loaded, is written back whole.
    """

    kind: str
    """Its kind's name, namespaced by the module declaring it: `inbox:concern`."""
    repository: str
    """The repository it's of, by the name lup knows it by."""
    by: Name | None
    """The party who wrote it, by its name in the repository; none where lup
    wrote it, of its own accord."""
    at: AwareDatetime
    """When it was written: for a node, this version of it."""

    @classmethod
    def declared(cls) -> str | None:
        """Return the kind the class declares, its `kind` field's default; none for a base class, which declares none.

        >>> Record.declared() is None
        True
        """
        # lup: ignore("dict-literal-key", why="pydantic's table of the class's own fields, read for `kind`, which `Record` declares, so the key always holds")
        default = cls.model_fields["kind"].default
        return default if isinstance(default, str) else None


class Node(Record):
    """One version of a node: a later one is the node changed, and the latest is the node as it stands.

    It's the base every node kind extends, and what a node of a kind no loaded
    class declares reads as. A node kept for the first time has no key yet; the
    store gives it one, and a number where its kind is cited by one.
    """

    numbered: ClassVar[bool] = False
    """Whether nodes of the kind are cited by a number, `@12`: an item or a
    concern is, a party isn't, so a party made never moves the numbers the
    operator reads."""

    key: Annotated[int, Field(ge=0)] = 0
    """The store's own key for it, which edges and other nodes name it by; 0
    until it's first kept."""
    number: Annotated[int, Field(ge=1)] | None = None
    """Its number, cited `@12`, one sequence for every numbered node of every
    repository; none for a kind that isn't numbered, and until it's first kept."""
    name: Name | None = None
    """Its name, which `@` takes beside a number; none where it has none. A kind
    gives it its default, or requires it."""

    def refused(self, found: Callable[[int], Node | None]) -> str | None:
        """Say why the store can't keep this version, reading the nodes it names by their keys through `found`; none where it can.

        Called as it's kept, so a kind refuses what its fields alone can't tell,
        such as a parent that isn't there. The base refuses nothing.
        """
        del found
        return None


class Edge(Record):
    """An edge: from one node to another, or said of one node alone.

    Never changed once drawn, and never numbered: what's later is drawn after
    it, in the order the store keeps.
    """

    target: int
    """The key of the node it's drawn to."""
    source: int | None = None
    """The key of the node it's drawn from; none where it's said of its target
    alone, as a concern cleared, where no node says it."""

    def refused(self, source: Node | None, target: Node) -> str | None:
        """Say why it can't join `source` to `target`, as the store holds them; none where it can.

        An edge is the one thing that sees both its ends, so a kind refuses here
        an end it can't take. The base refuses nothing.
        """
        del source, target
        return None

    def replaces(self, earlier: Edge) -> bool:
        """Say whether it takes the place of `earlier`, an edge of its kind drawn before it from the same node.

        A concern moved to another party is a later edge in place of the one
        before, not a changed one: reading where it is takes the latest. The
        base replaces nothing: edges add up.
        """
        del earlier
        return False


class Kinds(Model):
    """The classes the store reads its records as, each by the kind it declares.

    A record whose kind none of them declares reads as the base class, `Node` or
    `Edge`, every field it held kept.
    """

    nodes: list[type[Node]] = []
    edges: list[type[Edge]] = []

    @model_validator(mode="after")
    def distinct(self) -> Self:
        """Refuse a class that declares no kind, and two declaring one alike."""
        classes: list[type[Record]] = [*self.nodes, *self.edges]
        kinds = [each.declared() for each in classes]
        undeclared = [
            each.__name__
            for each, kind in zip(classes, kinds, strict=True)
            if kind is None
        ]
        if undeclared:
            message = (
                f"{', '.join(undeclared)} declare no kind: a kind's class gives "
                "`kind` its name as its default"
            )
            raise ValueError(message)
        repeated = list(
            dict.fromkeys(
                each for each in kinds if each is not None and kinds.count(each) > 1
            )
        )
        if repeated:
            message = (
                f"two classes declare {', '.join(repeated)}: a kind is one class's"
            )
            raise ValueError(message)
        return self

    def node(self, kind: str) -> type[Node]:
        """Return the class a node of `kind` reads as: the one declaring it, or `Node`."""
        return next((each for each in self.nodes if each.declared() == kind), Node)

    def edge(self, kind: str) -> type[Edge]:
        """Return the class an edge of `kind` reads as: the one declaring it, or `Edge`."""
        return next((each for each in self.edges if each.declared() == kind), Edge)


class Recorded(Named[type[Node] | type[Edge]]):
    """The kinds of record a module keeps in the store, each named by the kind it declares.

    `Recorded.of(Concern, Under)`: resolving a declaration gathers every
    module's, and the store reads its records as them; a kind two modules
    declare fails the load, naming both.
    """

    @override
    def named(self, entry: type[Node | Edge]) -> str:
        return entry.declared() or entry.__name__
