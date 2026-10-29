"""Threads on the ledger, read: one by its number or its name, a repository's, what's in one, and where it stands.

`packages/lup-ledger/README.md`, *Threads*. A thread is kept as any node is
(`Ledger.kept`, with its repository's agents' names as `taken`), and what's in
it drawn as any edge is (`Ledger.drawn`); this reads them. A thread's
sub-threads are read from its repository's threads, by their `parent`, so a
read walks one repository's threads at most, never the ledger.
"""

from typing import TYPE_CHECKING

from lup.types import Model
from lup_ledger.environment.store import Ledger
from lup_ledger.records import Edge, Node
from lup_ledger.threads import In, Member, Moved, Refers, Standing, Thread

if TYPE_CHECKING:
    from pathlib import Path

    from lup_ledger.parties import Conversation


class Threads(Model, arbitrary_types_allowed=True):
    """The threads of every repository, as the ledger holds them."""

    ledger: Ledger

    def thread(self, number: int) -> Thread:
        """Return thread `number` as it stands; raise `LupLedgerError` where the ledger holds no thread by that number."""
        return self.ledger.node(number, Thread)

    def named(self, repository: Path, name: str) -> Thread | None:
        """Return the thread of `repository` named `name`; none where none is."""
        found = self.ledger.named(repository, name)
        return found if isinstance(found, Thread) else None

    def of(self, repository: Path) -> list[Thread]:
        """Return every thread of `repository`, by number."""
        return self.ledger.nodes(repository, Thread)

    def under(self, number: int) -> list[Thread]:
        """Return the threads right under thread `number`, by number."""
        with self.ledger.together():
            thread = self.thread(number)
            return [
                each for each in self.of(thread.repository) if each.parent == number
            ]

    def answering(self, number: int) -> Conversation | None:
        """Return who answers for thread `number`: its holder, or, where nobody holds it, the nearest thread above it that somebody holds; none where nobody does."""
        with self.ledger.together():
            thread = self.thread(number)
            while thread.holder is None and thread.parent is not None:
                thread = self.thread(thread.parent)
        return thread.holder

    def members(self, number: int) -> list[Member]:
        """Return what's in thread `number`, in the order it came in: each node in it, and each part moved into it, with the edges drawn to its node."""
        with self.ledger.together():
            entries = self.ledger.drawn_to(number, Edge, current=True)

            def member(entry: Edge) -> Member | None:
                match entry:
                    case In(source=source):
                        part = None
                    case Moved(source=source, part=moved):
                        part = moved
                    case _:
                        return None
                return Member(
                    node=self.ledger.node(source, Node),
                    part=part,
                    drawn=self.ledger.drawn_to(source, Edge),
                )

            found = [member(each) for each in entries]
        return [each for each in found if each is not None]

    def references(self, number: int) -> list[Refers]:
        """Return the references to thread `number` from items of other threads that touch it, in the order drawn."""
        return self.ledger.drawn_to(number, Refers)

    def standing(self, number: int) -> Standing:
        """Return where thread `number` stands, read from the edges drawn to it and to what's in it (`Standing.read`)."""
        with self.ledger.together():
            thread = self.thread(number)
            drawn = self.ledger.drawn_to(number, Edge)
            members = self.members(number)
        return Standing.read(thread, drawn, members)
