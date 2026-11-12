"""Threads on the ledger, read: one by its number or its name, a repository's, what's in one, and where it stands.

`packages/lup-ledger/README.md`, *Threads*. A thread is kept as any node is
(`Ledger.kept`, with its repository's agents' names as `taken`), and what's in
it drawn as any edge is (`Ledger.drawn`); this reads them. A thread's
sub-threads are read from its repository's threads, by their `parent`, so a
read walks one repository's threads at most, never the ledger.

A root an earlier lup kept for a session is read as absent (`Thread.root`): no
read here finds one, and a thread right under one reads as at the top.
"""

from typing import TYPE_CHECKING

from lup.types import Model
from lup_ledger.environment.store import Ledger
from lup_ledger.errors import LupLedgerError
from lup_ledger.records import Edge, Node
from lup_ledger.threads import (
    Body,
    In,
    Marks,
    Member,
    Moved,
    Parked,
    Refers,
    Standing,
    Status,
    Thread,
    without_roots,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from lup_ledger.parties import Conversation


def holding(conversation: Conversation) -> bool:
    """Say that `conversation` still holds what they hold: every holder does, where nothing says who has ended."""
    del conversation
    return True


class Threads(Model, arbitrary_types_allowed=True):
    """The threads of every repository, as the ledger holds them."""

    ledger: Ledger

    def thread(self, number: int) -> Thread:
        """Return thread `number` as it stands, at the top where it's right under a root; raise `LupLedgerError` where the ledger holds no thread by that number, or a root."""
        found = self.ledger.node(number, Thread)
        if found.root:
            message = f"the ledger holds no thread @{number}"
            raise LupLedgerError(message)
        above = None if found.parent is None else self.ledger.found(found.parent)
        return (
            found.model_copy(update={"parent": None})
            if isinstance(above, Thread) and above.root
            else found
        )

    def named(self, repository: Path, name: str) -> Thread | None:
        """Return the thread of `repository` named `name`; none where none is, but a root."""
        found = self.ledger.named(repository, name)
        return (
            self.thread(found.number)
            if isinstance(found, Thread) and not found.root
            else None
        )

    def of(self, repository: Path) -> list[Thread]:
        """Return every thread of `repository`, by number."""
        return without_roots(self.ledger.nodes(repository, Thread))

    def under(self, number: int) -> list[Thread]:
        """Return the threads right under thread `number`, by number."""
        with self.ledger.together():
            thread = self.thread(number)
            return [
                each for each in self.of(thread.repository) if each.parent == number
            ]

    def answering(
        self, number: int, live: Callable[[Conversation], bool] = holding
    ) -> Conversation | None:
        """Return who answers for thread `number`: its holder, or, where nobody holds it, the nearest thread above it that somebody holds; none where nobody does.

        A holder `live` says has ended holds nothing: whoever holds the thread
        above answers for it.
        """

        def held(thread: Thread) -> Conversation | None:
            return (
                thread.holder
                if thread.holder is not None and live(thread.holder)
                else None
            )

        with self.ledger.together():
            thread = self.thread(number)
            while held(thread) is None and thread.parent is not None:
                thread = self.thread(thread.parent)
        return held(thread)

    def members(self, number: int) -> list[Member]:
        """Return what's in thread `number`, in the order it came in: each node in it, and each part or item moved into it, with the edges drawn to its node that stand, none a later one replaced."""
        with self.ledger.together():
            entries = self.ledger.drawn_to(number, Edge, current=True)

            def member(entry: Edge) -> Member | None:
                match entry:
                    case In(source=source):
                        part, moved = None, False
                    case Moved(source=source, part=part):
                        moved = True
                    case _:
                        return None
                return Member(
                    node=self.ledger.node(source, Node),
                    part=part,
                    moved=moved,
                    drawn=self.ledger.drawn_to(source, Edge, current=True),
                )

            found = [member(each) for each in entries]
        return [each for each in found if each is not None]

    def references(self, number: int) -> list[Refers]:
        """Return the references to thread `number` from items of other threads that touch it, in the order drawn."""
        return self.ledger.drawn_to(number, Refers)

    def parked(self, repository: Path | None = None) -> list[Parked]:
        """Return what each parked thread waits for, the agent's mark it stands at, of `repository`, or of every one where it's none, in the order each was parked; none the operator cleared, nor of a root.

        Only the latest `Parked` drawn to each thread is read against its
        marks, so a thread parked many times costs one read.
        """
        with self.ledger.together():
            found = [
                each
                for each in self.ledger.drawn_of(Parked)
                if repository is None or each.repository == repository
            ]
            latest = {each.target: place for place, each in enumerate(found)}
            return [
                found[place]
                for place in sorted(latest.values())
                if self.marks(found[place].target) == Marks(agent=found[place])
                and not self.ledger.node(found[place].target, Thread).root
            ]

    def body(self, number: int) -> Body | None:
        """Return thread `number`'s body, the latest drawn to it; none where none was, or the latest cleared it."""
        bodies = self.ledger.drawn_to(number, Body)
        return bodies[-1] if bodies and bodies[-1].text.strip() else None

    def status(self, number: int) -> Status | None:
        """Return the latest edge saying where thread `number` stands; none where nothing has."""
        statuses = self.ledger.drawn_to(number, Status)
        return statuses[-1] if statuses else None

    def marks(self, number: int) -> Marks:
        """Return thread `number`'s two marks, each read apart (`Marks`)."""
        return Marks.read(self.ledger.drawn_to(number, Status))

    def standing(
        self, number: int, live: Callable[[Conversation], bool] = holding
    ) -> Standing:
        """Return where thread `number` stands, read from the edges drawn to it and to what's in it (`Standing.read`), and whoever answers for it, a holder `live` says has ended holding nothing."""
        with self.ledger.together():
            thread = self.thread(number)
            drawn = self.ledger.drawn_to(number, Edge)
            members = self.members(number)
            answering = self.answering(number, live)
        return Standing.read(thread, drawn, members, running=answering is not None)
