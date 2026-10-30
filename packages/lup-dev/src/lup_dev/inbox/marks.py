"""Review marks: how far the operator has reviewed each thing a module shows, as the module names it, kept on the ledger as edges they draw.

`docs/dashboard.md`, *Review marks*. Every scope of the review (a thread, a
file, a drawer, an agent's group) has one mark: how far the operator has
reviewed it. What came after it is open and new; what came before folds under
one line saying how much, through the one helper every module shares
(`lup.blocks.kept_open`). Space `d` moves it, at send, as every mark in the
draft is applied. A module names what a mark is on by a key of its own, a JSON
object (the judge's file `{branch, path}`, Transcripts' conversation
`{runtime, session, agent}`, a thread `{node}`), never by where it's shown,
since one file shows in an approval and in "since you approved" alike; and
says how far in its own terms (`ReviewMark.up_to`: a file's version as git
names its content, a conversation's step, a thread's last node read).

Each mark moved is an edge the operator draws on the ledger (`Reviewed`), so
every move stays, a record of what they reviewed when, and the latest drawn for
a key is its mark. It's drawn to the node it's on where it's on one, a thread
keyed `{"node": 12}`; else to the node standing for its module's marks in its
repository (`Reviewing`), since a file of a branch or a conversation is no node
of the ledger, and a node of their own would take a number of the sequence the
operator reads at each thing first marked. The host service holds each
module's latest marks in memory, read at its start, and writes each move
through to the ledger before its copy changes (`MarkStore`), as it holds the
inbox's items.

The ledger is in lup's state on the host, which no room mounts, so an agent
never marks their own work reviewed. Moving one is the operator's alone
(`MoveMarks`), as their reply is sent; reading them is the operator's and, for
its own repository, a room's (`ReadMarks`), so a view's command in a room folds
where the operator's page does. A module's views read their own module's marks
through their context (`ReviewMarks`), which also makes the offer moving one
(`ReviewMarks.offer`), and records which they read: a view the page shows is
answered again as one of them moves (`Remarked`, `host/watch.py`).

An earlier lup kept a repository's marks in a file of each module's
(`MarksFile`, `MarksLayout`), converted once onto the ledger
(`lup_dev.inbox.conversion`).
"""

import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, override

from pydantic import Field, JsonValue

from lup.blocks import OfAgent, Offer
from lup.types import Model, MutableModel
from lup_dev.clock import Clock
from lup_dev.host.protocol import HostError, Reply, Request
from lup_dev.host.service import Handler, Reading, Route
from lup_dev.host.watch import Changes, Remarked
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.errors import LupLedgerError
from lup_ledger.parties import Lup, Operator
from lup_ledger.records import Edge, Kinds, Node
from lup_ledger.threads import KINDS as THREADS

if TYPE_CHECKING:
    from lup_dev.layout import Layout
    from lup_ledger.parties import Conversation


CORE = "core"
"""The module whose marks the review's own scopes' are: a thread, read up to
the last of what's in it shown, and an agent's group, seen up to the last of its
items shown (`seen`)."""


def seen(conversation: Conversation) -> Key:
    """Return the key of the core's mark on `conversation`'s group: its runtime's ids, which a rename never changes."""
    return OfAgent(
        runtime=conversation.runtime,
        session=conversation.session,
        agent=conversation.agent,
    ).model_dump(mode="json")


def on_node(number: int) -> Key:
    """Return the key of a mark on node `number` of the ledger, a thread: drawn to that node.

    >>> on_node(12)
    {'node': 12}
    """
    return {"node": number}


type Key = Mapping[str, JsonValue]
"""What a mark is on, as its module names it: a JSON object, `{"branch": "feat",
"path": "a.py"}`; `{"node": 12}` for a node of the ledger."""


def keyed(key: Key) -> str:
    """Say a mark's key in one canonical form, its fields in order, so two keys naming one thing are one.

    >>> keyed({"path": "a.py", "branch": "feat"})
    '{"branch":"feat","path":"a.py"}'
    """
    return json.dumps(key, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def noded(key: Key) -> int | None:
    """Return the number of the node of the ledger `key` names, `{"node": 12}`; none for a key naming anything else.

    >>> noded({"node": 12}), noded({"branch": "feat", "path": "a.py"})
    (12, None)
    """
    match dict(key):
        case {"node": int() as number} if len(key) == 1:
            return number
        case _:
            return None


class ReviewMark(Model):
    """One review mark: what its module's key names, how far the operator reviewed it, and when they moved it there."""

    key: Key
    """What it's on, as its module names it: `{"branch": "feat", "path":
    "a.py"}`."""
    up_to: str | None = None
    """How far, in its module's own terms: a file's version as git names its
    content, a conversation's last step read, a group's last item seen, a
    thread's last node read; none where its module says only when, or a file
    was reviewed deleted."""
    at: datetime
    """When the operator moved it there: as their reply was sent."""


class ModuleMarks(Model):
    """The review marks one module keeps of one repository: each key's latest."""

    module: str
    marks: list[ReviewMark] = []
    """Each key's latest, in the order each key was first marked."""

    def of(self, key: Key) -> ReviewMark | None:
        """Return the mark on what `key` names; none where the operator never marked it."""
        wanted = keyed(key)
        return next((each for each in self.marks if keyed(each.key) == wanted), None)

    def with_marks(self, marks: list[ReviewMark]) -> ModuleMarks:
        """Return these marks with each of `marks` in place of the one on its key, a key not marked yet after the rest."""
        latest = {keyed(each.key): each for each in [*self.marks, *marks]}
        return self.model_copy(update={"marks": list(latest.values())})


class MarksFile(ModuleMarks):
    """One module's marks of one repository as an earlier lup kept them, a file of its own (`MarksLayout.module`), converted once onto the ledger."""

    carried: list[str] = []
    """The older stores carried into it, by name, each once: `reviewed
    branches`, the judge's marks of files before the file held them."""


class Reviewing(Node):
    """What the operator reviews of one module in one repository, where what a mark is on is no node of the ledger: a file of a branch, a conversation.

    Each mark they move on such a thing is an edge drawn to it (`Reviewed`),
    carrying the module's key. Made by lup at the module's first mark there.
    """

    kind: Literal["inbox:reviewing"] = "inbox:reviewing"
    name: None = None
    module: str


class Reviewed(Edge):
    """A review mark the operator moved: what it's on, as its module names it, and how far they reviewed it, at `at`.

    Drawn to the node it's on, where its key names one (`noded`), else to its
    module's `Reviewing` node of the repository. The latest drawn for a key is
    its mark; the earlier ones stay, the record of what was reviewed when.
    """

    kind: Literal["inbox:reviewed"] = "inbox:reviewed"
    source: None = None
    by: Operator
    module: str
    key: Key
    up_to: str | None = None

    @override
    def refused(self, source: Node | None, target: Node) -> str | None:
        """Refuse a target that isn't the node its key names, or else its module's marks."""
        number = noded(self.key)
        if number is not None:
            if target.number == number and not isinstance(target, Reviewing):
                return None
            return f"a mark keyed {keyed(self.key)} is drawn to @{number}"
        if isinstance(target, Reviewing) and target.module == self.module:
            return None
        return (
            f"a mark of `{self.module}`'s is drawn to its module's marks, and "
            f"@{target.number} is a `{target.kind}`"
        )

    def mark(self) -> ReviewMark:
        """Return it as the mark it says."""
        return ReviewMark(key=self.key, up_to=self.up_to, at=self.at)


KINDS = Kinds(nodes=[Reviewing], edges=[Reviewed])
"""The kinds review marks are kept as on the ledger."""


class MarkStore(MutableModel, arbitrary_types_allowed=True):
    """Every repository's review marks, as the ledger keeps them, each module's latest held in memory.

    Read whole as it's opened (`opened`), and each move written through to the
    ledger, in one transaction, before its copy here changes (`moved`). The
    copies held are replaced whole at each move, never changed in place, so a
    reader on another thread holds the one it took.
    """

    ledger: Ledger
    held: dict[Path, dict[str, ModuleMarks]] = {}
    """By repository, then module."""
    anchors: dict[Path, dict[str, int]] = {}
    """The number of each module's `Reviewing` node, by repository, then module."""

    @classmethod
    def opened(cls, ledger: Ledger) -> MarkStore:
        """Read the marks `ledger` keeps: each module's `Reviewing` node, and each mark drawn, the latest of each key held.

        Raise `HostError` where a record doesn't read.
        """
        try:
            with ledger.together():
                anchors = ledger.every(Reviewing)
                drawn = ledger.drawn_of(Reviewed)
        except LupLedgerError as unread:
            message = f"the review marks on the ledger don't read: {unread}"
            raise HostError(message) from unread
        held = {
            repository: {
                module: ModuleMarks(module=module).with_marks(
                    [
                        each.mark()
                        for each in drawn
                        if each.repository == repository and each.module == module
                    ]
                )
                for module in dict.fromkeys(
                    each.module for each in drawn if each.repository == repository
                )
            }
            for repository in dict.fromkeys(each.repository for each in drawn)
        }
        found = {
            repository: {
                each.module: each.number
                for each in anchors
                if each.repository == repository
            }
            for repository in dict.fromkeys(each.repository for each in anchors)
        }
        return cls(ledger=ledger, held=held, anchors=found)

    @classmethod
    def kept_in(cls, layout: Layout) -> MarkStore:
        """Open the marks on the ledger in lup's state at `layout`, made where there's none, reading only what marks are kept as: for a store of a test or the demo, beside no inbox.

        Raise `HostError` where the ledger doesn't open, or a record doesn't read.
        """
        try:
            ledger = Ledger.opened(
                LedgerLayout.of(layout),
                Kinds(
                    nodes=[*THREADS.nodes, *KINDS.nodes],
                    edges=[*THREADS.edges, *KINDS.edges],
                ),
            )
        except LupLedgerError as unread:
            message = f"the review marks' ledger doesn't open: {unread}"
            raise HostError(message) from unread
        return cls.opened(ledger)

    def kept(self, repository: Path, module: str) -> ModuleMarks:
        """Return `module`'s marks of `repository`; none, where it has kept none."""
        return self.held.get(repository, {}).get(module, ModuleMarks(module=module))

    def of(self, repository: Path, module: str, key: Key) -> ReviewMark | None:
        """Return `module`'s mark on what `key` names in `repository`; none where the operator never marked it."""
        return self.kept(repository, module).of(key)

    def moved(
        self, repository: Path, module: str, marks: list[ReviewMark]
    ) -> ModuleMarks:
        """Draw each of `marks` on the ledger in place of `module`'s mark on its key in `repository`, in one transaction, and return its marks after.

        A mark keyed by a node is drawn to it; any other to the module's
        `Reviewing` node of the repository, made by lup at its first. The copy
        held changes under the ledger's lock, so two moves at once each keep
        the other's. Raise `HostError`, drawing none, where the ledger refuses
        one: a node it names isn't on the ledger, or is another repository's.
        """
        loose = [each for each in marks if noded(each.key) is None]

        def drawn(mark: ReviewMark, target: int) -> None:
            self.ledger.drawn(
                Reviewed(
                    target=target,
                    repository=repository,
                    by=Operator(),
                    at=mark.at,
                    module=module,
                    key=mark.key,
                    up_to=mark.up_to,
                )
            )

        try:
            with self.ledger.writing():
                anchors = self.anchors.get(repository, {})
                anchor = anchors.get(module)
                for each in marks:
                    number = noded(each.key)
                    if number is not None:
                        drawn(each, number)
                if loose:
                    if anchor is None:
                        anchor = self.ledger.kept(
                            Reviewing(
                                number=self.ledger.numbered(),
                                repository=repository,
                                by=Lup(),
                                at=min(each.at for each in loose),
                                module=module,
                            )
                        ).number
                    for each in loose:
                        drawn(each, anchor)
                after = self.kept(repository, module).with_marks(marks)
                self.held = {
                    **self.held,
                    repository: {**self.held.get(repository, {}), module: after},
                }
                if anchor is not None:
                    self.anchors = {
                        **self.anchors,
                        repository: {**anchors, module: anchor},
                    }
        except LupLedgerError as refused:
            raise HostError(str(refused)) from refused
        return after


class ReadMarks(Request, reads=True):
    """Read one module's review marks of a repository: those on what `keys` name, or every one of the module's where none is named."""

    kind: Literal["review-marks"] = "review-marks"
    repository: Path
    """The repository's git directory."""
    module: str
    keys: Sequence[Key] | None = None
    """What the marks wanted are on, as the module names each; none for every
    one it keeps."""


class Moving(Model):
    """One mark to move: what it's on, as its module names it, and how far the operator reviewed it, as the page showed it."""

    key: Key
    up_to: str | None = None


class MoveMarks(Request, reads=False):
    """Move review marks of one module of a repository, as the operator's reply is sent: each to how far they reviewed what it's on, as the page showed it, at the host's time; the operator's alone."""

    kind: Literal["review-mark"] = "review-mark"
    repository: Path
    """The repository's git directory."""
    module: str
    marks: list[Moving] = Field(min_length=1)


class MarksRead(Reply):
    """A module's review marks of a repository, as kept: those asked for that the operator ever made."""

    kind: Literal["review-marked"] = "review-marked"
    marks: list[ReviewMark] = []


class MarksMoved(Reply):
    """The review marks moved, as kept once moved."""

    kind: Literal["review-moved"] = "review-moved"
    marks: list[ReviewMark]


class MarksReading(Model, Reading[ReadMarks], arbitrary_types_allowed=True):
    """Answers `ReadMarks`: the operator any repository's, a room its own repository's alone."""

    store: MarkStore
    """Every repository's marks, as the host service holds them."""

    @override
    def request(self) -> type[ReadMarks]:
        return ReadMarks

    @override
    async def answer(self, request: ReadMarks) -> Reply:
        return self.read(request)

    @override
    async def scoped(self, request: ReadMarks, repository: Path) -> Reply:
        if request.repository != repository:
            message = "the marks asked for aren't this repository's"
            raise HostError(message)
        return await self.answer(request)

    def read(self, request: ReadMarks) -> MarksRead:
        """Read the marks `request` asks for, as kept."""
        kept = self.store.kept(request.repository, request.module)
        if request.keys is None:
            return MarksRead(marks=kept.marks)
        found = [kept.of(each) for each in request.keys]
        return MarksRead(marks=[each for each in found if each is not None])


class MarksMoving(Model, Handler[MoveMarks], arbitrary_types_allowed=True):
    """Answers `MoveMarks`: each mark moved at the host's time, and each view that read one told, so it's answered again; a room never reaches it."""

    store: MarkStore
    """Every repository's marks, as the host service holds them."""
    clock: Clock
    changes: Changes | None = None
    """Told of each mark moved, so a view the page shows that read it is
    answered again (`host/views.py`); none tells nothing."""

    @override
    def request(self) -> type[MoveMarks]:
        return MoveMarks

    @override
    async def answer(self, request: MoveMarks) -> Reply:
        """Move the marks, refusing one of the core's that isn't up to a node, an item or what's in a thread, by its number, which the review reads it as."""
        unnumbered = [
            each
            for each in request.marks
            if request.module == CORE
            and (each.up_to is None or not each.up_to.isdecimal())
        ]
        if unnumbered:
            message = (
                "a thread is read, and an agent's group seen, up to what's in it, by "
                f"its number, not {', '.join(repr(each.up_to) for each in unnumbered)}"
            )
            raise HostError(message)
        at = self.clock.now()
        marks = [
            ReviewMark(key=each.key, up_to=each.up_to, at=at) for each in request.marks
        ]
        await asyncio.to_thread(
            self.store.moved, request.repository, request.module, marks
        )
        if self.changes is not None:
            self.changes.changed(
                Remarked(
                    repository=request.repository,
                    module=request.module,
                    key=keyed(each.key),
                )
                for each in marks
            )
        return MarksMoved(marks=marks)


class Marks(ABC):
    """Where a module's review marks of a repository are read: from the host service, in the repository's process or a room, or from a store held in this process."""

    @abstractmethod
    async def kept(
        self, repository: Path, module: str, keys: Sequence[Key]
    ) -> list[ReviewMark]:
        """Return `module`'s marks of `repository` on what `keys` name, those the operator ever made, as the core keeps them.

        Raise `HostError` where they can't be read, saying why.
        """


class StoredMarks(Model, Marks, arbitrary_types_allowed=True):
    """The marks as a store held in this process keeps them: as the demo keeps its own, and a test."""

    store: MarkStore

    @override
    async def kept(
        self, repository: Path, module: str, keys: Sequence[Key]
    ) -> list[ReviewMark]:
        found = self.store.kept(repository, module)
        return [mark for each in keys if (mark := found.of(each)) is not None]


class ReviewMarks(MutableModel, arbitrary_types_allowed=True):
    """Where a module's views read their own module's review marks of their repository, as the core keeps them (`Marks`), and offer to move one, the operator's done on what it's on.

    Each mark read is recorded (`read`), so the view reading it is answered
    again as it moves, where the page shows it. Made afresh for each call of a
    module's method, as its context is.
    """

    marks: Marks
    repository: Path
    """The repository's git directory."""
    module: str
    """The module whose marks these are, by its name."""
    read: list[Remarked] = []
    """Each mark read so far, in the order first read."""

    async def of(self, keys: Sequence[Key]) -> list[ReviewMark | None]:
        """Return the mark on what each of `keys` names, in order, none for one never marked, recording each as read.

        Raise `HostError` where they can't be read, saying why.
        """
        kept = await self.marks.kept(self.repository, self.module, keys)
        found = {keyed(each.key): each for each in kept}
        named = [keyed(each) for each in keys]
        self.read = list(
            dict.fromkeys(
                [
                    *self.read,
                    *(
                        Remarked(
                            repository=self.repository, module=self.module, key=each
                        )
                        for each in named
                    ),
                ]
            )
        )
        return [found.get(each) for each in named]

    async def mark(self, key: Key) -> ReviewMark | None:
        """Return the mark on what `key` names, recording it as read; none where the operator never marked it.

        Raise `HostError` where it can't be read, saying why.
        """
        [found] = await self.of([key])
        return found

    def offer(self, key: Key, up_to: str | None, says: str) -> Offer:
        """Return the offer of moving the mark on what `key` names to `up_to`, Space `d` on what it's shown on, applied as the reply is sent: the core's request (`MoveMarks`), so a module names no action of its own for it.

        >>> class Nowhere(Marks):
        ...     async def kept(self, repository, module, keys): return []
        >>> marks = ReviewMarks(marks=Nowhere(), repository=Path("/r.git"), module="transcripts")
        >>> offered = marks.offer({"session": "s"}, "12", "mark it read")
        >>> offered.action, offered.verb, offered.argument["up_to"]
        ('review-mark', 'done', '12')
        """
        return Offer(
            action=MoveMarks.named(),
            argument={
                "repository": str(self.repository),
                "module": self.module,
                "key": dict(key),
                "up_to": up_to,
            },
            verb="done",
            says=says,
        )


def routes(store: MarkStore, clock: Clock, changes: Changes | None) -> list[Route]:
    """Route reading and moving review marks to their handlers, over every repository's marks as `store` holds them, each move at `clock`'s time and told to `changes`."""
    return [
        Route.reading(MarksReading(store=store)),
        Route.to(MarksMoving(store=store, clock=clock, changes=changes)),
    ]
