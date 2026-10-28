"""Review marks: how far the operator has reviewed each thing a module shows, as the module names it, in one store the core keeps.

`docs/dashboard.md`, *Review marks*. Every scope of the review (a file, a
drawer, an agent's group) has one mark: how far the operator has reviewed it.
What came after it is open and new; what came before folds under one line
saying how much, through the one helper every module shares
(`lup.blocks.kept_open`). Space `d` moves it, at send, as every mark in the
draft is applied. A module names what a mark is on by a key of its own, a JSON
object (the judge's file `{branch, path}`, Transcripts' conversation
`{runtime, session, agent}`), never by where it's shown, since one file shows in
an approval and in "since you approved" alike; and says how far in its own terms
(`ReviewMark.up_to`: a file's version as git names its content, a
conversation's step).

A repository's marks are kept in lup's state on the host, one file of each
module's (`MarkStore`), which no room mounts, so an agent never marks its own
work reviewed. Moving one is the operator's alone (`MoveMarks`), as their reply
is sent; reading them is the operator's and, for its own repository, a room's
(`ReadMarks`), so a view's command in a room folds where the operator's page
does. A module's views read their own module's marks through their context
(`ReviewMarks`), which also makes the offer moving one (`ReviewMarks.offer`),
and records which they read: a view the page shows is answered again as one
of them moves (`Remarked`, `host/watch.py`).
"""

import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, override

from filelock import FileLock
from pydantic import Field, JsonValue

from lup.blocks import OfAgent, Offer
from lup.types import Model, MutableModel
from lup_dev.clock import Clock
from lup_dev.host.protocol import Reply, Request
from lup_dev.host.service import Handler, Reading, Route
from lup_dev.host.watch import Changes, Remarked
from lup_dev.inbox.store import Conversation, InboxError
from lup_dev.layout import Layout, MarksLayout
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from collections.abc import Callable


CORE = "core"
"""The module whose marks the review's own scopes' are: an agent's group, seen up
to the last of its items shown (`seen`)."""


def seen(conversation: Conversation) -> Key:
    """Return the key of the core's mark on `conversation`'s group: its runtime's ids, which a rename never changes."""
    return OfAgent(
        runtime=conversation.runtime,
        session=conversation.session,
        agent=conversation.agent,
    ).model_dump(mode="json")


type Key = Mapping[str, JsonValue]
"""What a mark is on, as its module names it: a JSON object, `{"branch": "feat",
"path": "a.py"}`."""


def keyed(key: Key) -> str:
    """Say a mark's key in one canonical form, its fields in order, so two keys naming one thing are one.

    >>> keyed({"path": "a.py", "branch": "feat"})
    '{"branch":"feat","path":"a.py"}'
    """
    return json.dumps(key, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ReviewMark(Model):
    """One review mark: what its module's key names, how far the operator reviewed it, and when they moved it there."""

    key: Key
    """What it's on, as its module names it: `{"branch": "feat", "path":
    "a.py"}`."""
    up_to: str | None = None
    """How far, in its module's own terms: a file's version as git names its
    content, a conversation's last step read, a group's last item seen; none
    where its module says only when, or a file was reviewed deleted."""
    at: datetime
    """When the operator moved it there: as their reply was sent."""


class ModuleMarks(Model):
    """The review marks one module keeps of one repository, as its file holds them, and the older stores carried into it."""

    module: str
    marks: list[ReviewMark] = []
    """Each key's latest, in the order each key was first marked."""
    carried: list[str] = []
    """The older stores carried into it, by name, each once and never again,
    so a mark moved since is never put back by an older one: `reviewed
    branches`, the judge's marks of files before this store held them."""

    def of(self, key: Key) -> ReviewMark | None:
        """Return the mark on what `key` names; none where the operator never marked it."""
        wanted = keyed(key)
        return next((each for each in self.marks if keyed(each.key) == wanted), None)

    def with_marks(self, marks: list[ReviewMark]) -> ModuleMarks:
        """Return these marks with each of `marks` in place of the one on its key, a key not marked yet after the rest."""
        latest = {keyed(each.key): each for each in [*self.marks, *marks]}
        return self.model_copy(update={"marks": list(latest.values())})


class MarkStore(Model):
    """One repository's review marks, a file of each module's, in lup's state on the host, which no room mounts.

    Each file is read whole as it's asked for and replaced whole in one step
    (`write_model`), under a lock of its module's (`MarksLayout.lock`), so a
    reader never sees half a write and two writers never lose one's mark.
    """

    layout: MarksLayout

    def kept(self, module: str) -> ModuleMarks:
        """Return `module`'s marks; none, where it has kept none."""
        return read_model(self.layout.module(module), ModuleMarks) or ModuleMarks(
            module=module
        )

    def of(self, module: str, key: Key) -> ReviewMark | None:
        """Return `module`'s mark on what `key` names; none where the operator never marked it."""
        return self.kept(module).of(key)

    def moved(self, module: str, marks: list[ReviewMark]) -> ModuleMarks:
        """Keep each of `marks` in place of `module`'s mark on its key, and return its marks after."""
        with self.locked(module):
            after = self.kept(module).with_marks(marks)
            write_model(self.layout.module(module), after)
            return after

    def carried(
        self, module: str, older: str, marks: Callable[[], list[ReviewMark]]
    ) -> ModuleMarks:
        """Carry the marks of the older store named `older` into `module`'s, once: those `marks` reads, each kept but where `module` has a mark on its key already, which is the later; and return its marks after.

        Recorded as carried (`ModuleMarks.carried`), so it never runs again,
        and nothing of the older store is changed: an older copy of lup still
        reads it.
        """
        kept = self.kept(module)
        if older in kept.carried:
            return kept
        with self.locked(module):
            kept = self.kept(module)
            if older in kept.carried:
                return kept
            ours = {keyed(each.key): each for each in kept.marks}
            theirs = [each for each in marks() if keyed(each.key) not in ours]
            after = ModuleMarks(
                module=module,
                marks=[*theirs, *kept.marks],
                carried=[*kept.carried, older],
            )
            write_model(self.layout.module(module), after)
            return after

    def locked(self, module: str) -> FileLock:
        """Return the lock `module`'s marks are written under."""
        lock = self.layout.lock(module)
        lock.parent.mkdir(parents=True, exist_ok=True)
        return FileLock(lock)


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

    layout: Layout
    """lup's state on the host, where each repository's marks are kept."""

    @override
    def request(self) -> type[ReadMarks]:
        return ReadMarks

    @override
    async def answer(self, request: ReadMarks) -> Reply:
        return await asyncio.to_thread(self.read, request)

    @override
    async def scoped(self, request: ReadMarks, repository: Path) -> Reply:
        if request.repository != repository:
            message = "the marks asked for aren't this repository's"
            raise InboxError(message)
        return await self.answer(request)

    def read(self, request: ReadMarks) -> MarksRead:
        """Read the marks `request` asks for, as kept."""
        kept = MarkStore(layout=self.layout.marks(request.repository)).kept(
            request.module
        )
        if request.keys is None:
            return MarksRead(marks=kept.marks)
        found = [kept.of(each) for each in request.keys]
        return MarksRead(marks=[each for each in found if each is not None])


class MarksMoving(Model, Handler[MoveMarks], arbitrary_types_allowed=True):
    """Answers `MoveMarks`: each mark moved at the host's time, and each view that read one told, so it's answered again; a room never reaches it."""

    layout: Layout
    clock: Clock
    changes: Changes | None = None
    """Told of each mark moved, so a view the page shows that read it is
    answered again (`host/views.py`); none tells nothing."""

    @override
    def request(self) -> type[MoveMarks]:
        return MoveMarks

    @override
    async def answer(self, request: MoveMarks) -> Reply:
        at = self.clock.now()
        marks = [
            ReviewMark(key=each.key, up_to=each.up_to, at=at) for each in request.marks
        ]
        store = MarkStore(layout=self.layout.marks(request.repository))
        await asyncio.to_thread(store.moved, request.module, marks)
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
    """Where a module's review marks of a repository are read: from the host service, in the repository's process or a room, or from a store where it's kept."""

    @abstractmethod
    async def kept(
        self, repository: Path, module: str, keys: Sequence[Key]
    ) -> list[ReviewMark]:
        """Return `module`'s marks of `repository` on what `keys` name, those the operator ever made, as the core keeps them.

        Raise `HostError` where they can't be read, saying why.
        """


class StoredMarks(Model, Marks, arbitrary_types_allowed=True):
    """The marks as lup's state at `layout` keeps them, read where they're kept: as the demo keeps its own, and a test."""

    layout: Layout

    @override
    async def kept(
        self, repository: Path, module: str, keys: Sequence[Key]
    ) -> list[ReviewMark]:
        found = MarkStore(layout=self.layout.marks(repository)).kept(module)
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

        >>> from lup_dev.layout import Layout
        >>> marks = ReviewMarks(marks=StoredMarks(layout=Layout(state=Path("/s"))),
        ...     repository=Path("/r.git"), module="transcripts")
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


def routes(layout: Layout, clock: Clock, changes: Changes | None) -> list[Route]:
    """Route reading and moving review marks to their handlers, over lup's state on the host at `layout`, each move at `clock`'s time and told to `changes`."""
    return [
        Route.reading(MarksReading(layout=layout)),
        Route.to(MarksMoving(layout=layout, clock=clock, changes=changes)),
    ]
