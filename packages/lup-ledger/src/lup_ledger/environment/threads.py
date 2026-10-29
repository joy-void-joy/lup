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
from lup_ledger.threads import (
    In,
    Member,
    Moved,
    Parked,
    Refers,
    Standing,
    Status,
    Thread,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
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
        """Return what's in thread `number`, in the order it came in: each node in it, and each part moved into it, with the edges drawn to its node that stand, none a later one replaced."""
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
                    drawn=self.ledger.drawn_to(source, Edge, current=True),
                )

            found = [member(each) for each in entries]
        return [each for each in found if each is not None]

    def references(self, number: int) -> list[Refers]:
        """Return the references to thread `number` from items of other threads that touch it, in the order drawn."""
        return self.ledger.drawn_to(number, Refers)

    def answering_at(self, number: int, at: datetime) -> Conversation | None:
        """Return who answered for thread `number` at `at`: its holder then, as its version then says, or, where nobody held it, the holder then of the nearest thread above; none where nobody did, or it wasn't opened yet.

        Whether a holder had ended by then isn't on the ledger, so one who had
        still holds here: whoever answered above them only counts once
        nobody holds it.
        """

        def then(each: int) -> Thread | None:
            versions = [
                version
                for version in self.ledger.versions(each)
                if isinstance(version, Thread) and version.at <= at
            ]
            return versions[-1] if versions else None

        with self.ledger.together():
            thread = then(number)
            while thread is not None and thread.holder is None:
                thread = None if thread.parent is None else then(thread.parent)
        return None if thread is None else thread.holder

    def parked(self, repository: Path | None = None) -> list[Parked]:
        """Return what each parked thread waits for, the status it stands at, of `repository`, or of every one where it's none, in the order each was parked."""
        with self.ledger.together():
            return [
                each
                for each in self.ledger.drawn_of(Parked)
                if (repository is None or each.repository == repository)
                and self.status(each.target) == each
            ]

    def status(self, number: int) -> Status | None:
        """Return the latest edge saying where thread `number` stands; none where nothing has."""
        statuses = self.ledger.drawn_to(number, Status)
        return statuses[-1] if statuses else None

    def standing(self, number: int) -> Standing:
        """Return where thread `number` stands, read from the edges drawn to it and to what's in it (`Standing.read`), who answered for it at each citation's time read from its versions and those above it (`answering_at`)."""
        with self.ledger.together():
            thread = self.thread(number)
            drawn = self.ledger.drawn_to(number, Edge)
            members = self.members(number)
            return Standing.read(
                thread,
                drawn,
                members,
                answering=lambda at: self.answering_at(number, at),
            )
