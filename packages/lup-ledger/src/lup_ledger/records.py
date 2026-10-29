"""What the ledger holds: nodes, the edges between them, and the kinds each is read as.

`packages/lup-ledger/README.md`, *Records*. A node is something the ledger
keeps and `@` cites by its number: a thread, a check, an item once the inbox's
are nodes. An edge joins two nodes, or says something of one: an item in a
thread, a thread settled. Each kind is a subclass of `Node` or `Edge` whose
`kind` field's default is a namespaced name (`ledger:thread`), stored on the
record, so a reader that loaded no class for it still says what it met: such a
record reads as the base class, every field it held kept, never refused or
dropped.

Where a node stands is read from the edges drawn to it, never stored on it
(`lup_ledger.threads.Standing`): a status kept on a record outlives what
justified it.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Self

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from lup.types import Model
from lup_ledger.parties import Writer

if TYPE_CHECKING:
    from collections.abc import Callable


def named(name: str, longest: int = 64) -> str:
    """Return `name` if a node can take it: letters, digits, `-`, `_` and `.`, a letter among them, not starting with `-`, at most `longest` long.

    A launch's name is the same but for the letter (`lup_dev.host.protocol.handle`).
    The letter is what lets `@` take a name or a number alike: no name reads as
    an item's number or a part's id.

    >>> named("dashboard-lag")
    'dashboard-lag'
    >>> named("2159.3")
    Traceback (most recent call last):
    ...
    ValueError: a node's name is letters, digits, `-`, `_` and `.`, a letter among them, not starting with `-`, at most 64 long: not '2159.3'
    """
    allowed = all(each.isalnum() or each in "-_." for each in name)
    lettered = any(each.isalpha() for each in name)
    if not allowed or not lettered or name.startswith("-") or len(name) > longest:
        message = (
            "a node's name is letters, digits, `-`, `_` and `.`, a letter among "
            f"them, not starting with `-`, at most {longest} long: not {name!r}"
        )
        raise ValueError(message)
    return name


type Name = Annotated[str, AfterValidator(named)]
"""A node's name, which `@` takes beside its number: unique among the names of its repository's nodes."""


class Record(Model, extra="allow"):
    """What every node and edge carries: its kind, its repository, who wrote it, and when.

    A field a record holds that its class doesn't declare is kept, so a record
    read as a base class, its kind's class not loaded, is written back whole.
    """

    kind: str
    """Its kind's name, namespaced by whoever declares it: `ledger:thread`."""
    repository: Path
    """The git directory of the repository it's of."""
    by: Writer
    """Who wrote it: a party, or lup."""
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
    class declares reads as.
    """

    number: Annotated[int, Field(ge=1)]
    """Its number, one sequence for every node of every repository, from 1, cited `@12`."""
    name: Name | None
    """Its short name, which `@` takes beside its number; none where it has none.
    A kind gives it its default, or requires it."""

    def refused(self, found: Callable[[int], Node | None]) -> str | None:
        """Say why the ledger can't keep this version, reading the nodes it names through `found`; none where it can.

        Called as it's kept, so a kind refuses what its fields alone can't tell,
        such as a parent that isn't there. The base refuses nothing.
        """
        del found
        return None

    def waiting(self, drawn: list[Edge]) -> bool:
        """Say whether it waits on the operator, given the edges drawn to it, oldest first.

        A thread asks it of each of its members to say whether it waits on the
        operator (`lup_ledger.threads.Standing`). The base never waits.
        """
        del drawn
        return False


class Edge(Record):
    """An edge: from one node to another, or said of one node alone.

    Never changed once drawn, and never numbered: what's later is drawn after
    it, in the order the ledger keeps.
    """

    target: int
    """The number of the node it's drawn to."""
    source: int | None
    """The number of the node it's drawn from; none where it's said of its
    target alone, as a thread settled, where no node says it. A kind gives it
    its default, or requires it."""

    def refused(self, source: Node | None, target: Node) -> str | None:
        """Say why it can't join `source` to `target`, as the ledger holds them; none where it can.

        An edge is the one thing that sees both its ends, so a kind refuses here
        an end it can't take. The base refuses nothing.
        """
        del source, target
        return None

    def replaces(self, earlier: Edge) -> bool:
        """Say whether it takes the place of `earlier`, an edge drawn before it from the same node.

        An item moved to another thread is a later edge in place of the one
        before, not a changed one. The base replaces nothing: edges add up.
        """
        del earlier
        return False

    def cites(self, part: int) -> bool:
        """Say whether its source cites part `part` of its target: a part of the operator's words moved into a thread is answered once something in the thread cites it (`lup_ledger.threads.Standing`).

        The base cites nothing: the kind that cites says so, as the inbox's
        citation does.
        """
        del part
        return False


class Kinds(Model):
    """The classes the ledger reads its records as, each by the kind it declares.

    A record whose kind none of them declares reads as the base class, `Node`
    or `Edge`.
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
            message = f"{', '.join(undeclared)} declare no kind: a kind's class gives `kind` its name as its default"
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
