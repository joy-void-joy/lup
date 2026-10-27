"""Holds: a change waiting inside the hook for the operator's answer.

A change that asks is held: the agent waits inside the hook, a file tool's write
before it lands and anything else at the checkpoint, while the operator answers
the item it is in their inbox (`Announcing`), in the dashboard's review or with
`lup-dev inbox answer`, the answer written back to the hold (`answer`)
(`docs/judging-writes.md`, *Asking the operator*). A decline puts the change
back, or never lets it land, and saves it, with the comment beside it; an
approval with a comment passes the comment on. Unanswered within the patience,
the change is put back and saved, and the hold stays open.

The call waiting holds a lock for as long as it waits (`Holds.waiting`), which
the OS frees where its process ends, so a hold whose call is gone is told from
one still waited on (`Holds.waited_on`). The host service stopping, or the
repository's process ending, takes the call's wait with it: such a hold is settled
at a later checkpoint in its worktree, as its call would have settled it, and
its session told (`docs/judging-writes.md`, *Asking the operator*). A call its
runtime ends while it waits, the operator interrupting it, or whose launch ends
meanwhile, gives up on the hold as on one unanswered in time, telling its
conversation at its next call.

What a move of `HEAD` asks is already committed, and isn't put back, so on every
runtime it's kept as a hold no agent waits on, with the commit it came from
(*A move's asks, after the fact*). Its answer is logged when it's given, and told
to the session that found the move at its next checkpoint; a decline changes no
file.

Nobody answers their own hold: answering refuses to run inside an agent's session,
as each runtime's adapter recognizes it. That stops a mistake, not a determined
agent; the real separation comes with containers.
"""

import difflib
import secrets
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, override

from filelock import FileLock, Timeout

from lup.types import Model
from lup_dev.clock import Clock
from lup_dev.errors import LupDevError
from lup_dev.git import Git
from lup_dev.host.client import Detached, HostClient
from lup_dev.host.protocol import Holding, HostError, ShowHolding
from lup_dev.inbox.protocol import AskHold, Shown
from lup_dev.inbox.store import ChangedFile, Conversation, HeldChange, Reading
from lup_dev.layout import HostLayout, Layout, StoreLayout
from lup_dev.policy.roles import Role
from lup_dev.policy.verdicts import Verdict, VerdictLog
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator

    from lup_dev.policy.runtime import Runtime


class HoldError(LupDevError):
    """A hold can't be answered: unknown, already answered, or asked from a session."""


class Response(Model):
    """What the operator answers a hold: approved or declined, and their comment."""

    approved: bool
    comment: str = ""


class Answer(Response):
    """The operator's answer to a hold, and when they gave it."""

    time: datetime


class HeldFile(Model):
    """One file a hold waits on."""

    path: Path
    role: Role
    blob: str
    """The held content's object id in the store, empty where the change deletes the file."""
    reasons: list[str]
    """The kinds of ask, as the verdict log records them."""
    asks: list[str]
    """What the change asks, one line each, for the operator."""
    reading: Reading | None = None
    """The judge's reading of the change to it, which the review opens it by;
    none where none was kept."""


class Hold(Model):
    """A change waiting for the operator."""

    key: str
    worktree: Path
    session: str
    """The session that made the change, or for a move's, that found it."""
    agent: str | None = None
    """The runtime's id for the subagent whose call made the change; none for
    the session's own conversation, and for a move's."""
    call: str | None = None
    """The runtime's id for the call that made the change, or whose finish found
    it: its moment in the conversation's record; none where no call did, as at a
    turn's end or for a move."""
    created: datetime
    files: list[HeldFile]
    diff: str
    """The change as a unified diff, for the operator to read."""
    commit: str | None = None
    """The commit a move of `HEAD` reached, for a hold no agent waits on; none for
    one an agent waits on."""
    verdicts: list[Verdict] = []
    """The verdicts logged on its files, which its answer is logged against."""
    proposed: bool = False
    """Whether it holds a file tool's write before it lands, which isn't on disk
    until it's let through; a checkpoint's change is there already."""
    answer: Answer | None = None
    abandoned: bool = False
    """Whether the wait ran out, or its call was interrupted: the change was put
    back, or never landed, and the hold stays open."""
    interrupted: bool = False
    """Whether its call was interrupted while it waited, its runtime ending the
    hook."""
    orphaned: bool = False
    """Whether the call waiting on it was gone when its answer came, as when the
    host service restarted mid-wait: a later checkpoint acted on the answer."""
    delivered: bool = False
    """Whether an answer given while no agent waited reached the session."""

    def waited(self) -> bool:
        """Say whether an agent waits inside its hook for the answer, or did until its process ended."""
        return self.commit is None and not self.abandoned and not self.orphaned


class Announcing(ABC):
    """Where a hold is put before the operator: their inbox, whose answer is written back to the hold (`answer`)."""

    @abstractmethod
    def announced(
        self, hold: Hold, runtime: str, repository: Path, files: list[ChangedFile]
    ) -> None:
        """Put `hold` before the operator, from the session of `runtime` that made the change, in `repository`, with each file it holds whole (`files`)."""

    @abstractmethod
    def holding(self, runtime: str, session: str, agent: str | None) -> bool:
        """Say whether the operator holds each flagged write of a conversation of `runtime`: its session's own, or its subagent `agent`'s."""


def asked(hold: Hold) -> HeldChange:
    """Return what a hold asks the operator, as an item of their inbox: let the change land, or keep what a commit brought, and what each file asks."""
    paths = [str(each.path) for each in hold.files]
    named = paths[0] if len(paths) == 1 else f"{len(paths)} files"
    text = (
        f"Keep what commit {hold.commit} brought to {named}?"
        if hold.commit is not None
        else f"Let the change to {named} land?"
    )
    summary = "\n".join(
        f"{each.path}: {ask}" for each in hold.files for ask in each.asks
    )
    return HeldChange(
        text=text,
        summary=summary,
        worktree=hold.worktree,
        key=hold.key,
        commit=hold.commit,
    )


class InboxAnnouncing(Model, Announcing, arbitrary_types_allowed=True):
    """Holds put in the operator's inbox through the host service, which writes their answer back."""

    layout: HostLayout
    clock: Clock

    @override
    def announced(
        self, hold: Hold, runtime: str, repository: Path, files: list[ChangedFile]
    ) -> None:
        sender = Conversation(
            repository=repository,
            runtime=runtime,
            session=hold.session,
            agent=hold.agent,
        )
        host = HostClient(layout=self.layout, clock=self.clock, starter=Detached())
        asking = AskHold(
            change=asked(hold),
            sender=sender,
            diff=hold.diff,
            files=files,
            call=hold.call,
        )
        host.ask(asking, Shown)

    @override
    def holding(self, runtime: str, session: str, agent: str | None) -> bool:
        """Ask the host service, which keeps the switch; where none runs there's no switch, and nothing is held for it."""
        host = HostClient(layout=self.layout, clock=self.clock, starter=Detached())
        asked = ShowHolding(runtime=runtime, session=session, agent=agent)
        try:
            return host.ask(asked, Holding).on
        except HostError:
            return False


def answered(
    hold: Hold, outcome: Literal["approved", "declined", "unanswered"]
) -> list[Verdict]:
    """Return the verdicts on a hold's files again, with how it was answered."""
    return [verdict.model_copy(update={"answer": outcome}) for verdict in hold.verdicts]


class Holds(Model):
    """The holds kept in one worktree's store."""

    layout: StoreLayout
    patience: timedelta = timedelta(hours=24)
    """How long a call waits for the operator's answer to a hold before the
    change is put back, and a hold no call waits on any more is kept: the first
    lup held calls for 4 hours without trouble; a day leaves room for an
    operator away overnight."""

    def unused(self) -> str:
        """Return a short key no hold here has, which the operator can type."""
        taken = [hold.key for hold in self.all()]

        def candidates() -> Iterator[str]:
            while True:
                yield secrets.token_hex(3)

        return next(candidate for candidate in candidates() if candidate not in taken)

    def put(self, hold: Hold) -> Hold:
        """Keep a hold, whose key `unused` gave."""
        write_model(self.layout.hold(hold.key), hold)
        return hold

    def get(self, key: str) -> Hold | None:
        """Return the hold with `key`, or none where this store has none."""
        return read_model(self.layout.hold(key), Hold)

    def all(self) -> list[Hold]:
        """Return every hold this store keeps, the oldest first."""
        if not self.layout.holds.is_dir():
            return []
        found = [
            Hold.model_validate_json(path.read_text())
            for path in self.layout.holds.glob("*.json")
        ]
        return sorted(found, key=lambda hold: hold.created)

    @contextmanager
    def waiting(self, key: str) -> Generator[None]:
        """Hold the lock of the call waiting on hold `key` while the context is open."""
        self.layout.holds.mkdir(parents=True, exist_ok=True)
        with FileLock(self.layout.waiter(key)):
            yield

    def waited_on(self, key: str) -> bool:
        """Say whether a call waits on hold `key`: whether its lock is held."""
        self.layout.holds.mkdir(parents=True, exist_ok=True)
        probe = FileLock(self.layout.waiter(key), timeout=0)
        try:
            probe.acquire()
        except Timeout:
            return True
        probe.release()
        return False

    def wait(
        self,
        key: str,
        clock: Clock,
        poll: timedelta = timedelta(seconds=2),
        ended: Callable[[], bool] | None = None,
    ) -> Answer | None:
        """Wait for the operator to answer hold `key`; none if the patience runs out, or once `ended` says the call waiting was interrupted, whether or not they answered meanwhile: nothing would hear it."""
        deadline = clock.now() + self.patience
        while True:
            if ended is not None and ended():
                return None
            hold = self.get(key)
            if hold is None:
                message = f"hold {key} vanished while waiting for its answer"
                raise HoldError(message)
            if hold.answer is not None:
                return hold.answer
            if clock.now() >= deadline:
                return None
            clock.sleep(poll.total_seconds())

    def mark(
        self,
        key: str,
        *,
        abandoned: bool = False,
        delivered: bool = False,
        interrupted: bool = False,
        orphaned: bool = False,
    ) -> None:
        """Note that hold `key` was given up on, its call interrupted, or settled with no call waiting, or that its late answer was told."""
        hold = self.get(key)
        if hold is None:
            return
        marked = hold.model_copy(
            update={
                "abandoned": hold.abandoned or abandoned,
                "delivered": hold.delivered or delivered,
                "interrupted": hold.interrupted or interrupted,
                "orphaned": hold.orphaned or orphaned,
            }
        )
        write_model(self.layout.hold(key), marked)

    def late(self) -> list[Hold]:
        """Return the holds answered while no agent waited, not yet told.

        Those whose wait ran out or whose call was interrupted, those settled
        with no call waiting, and a move's, which nobody waits on.
        """
        return [
            hold
            for hold in self.all()
            if not hold.waited() and hold.answer is not None and not hold.delivered
        ]

    def answer(self, key: str, response: Response, clock: Clock) -> Hold:
        """Record the operator's answer to hold `key`."""
        hold = self.get(key)
        if hold is None:
            message = f"no hold {key} in this store"
            raise HoldError(message)
        if hold.answer is not None:
            message = f"hold {key} is already answered"
            raise HoldError(message)
        answered = hold.model_copy(
            update={
                "answer": Answer(
                    approved=response.approved,
                    comment=response.comment,
                    time=clock.now(),
                )
            }
        )
        write_model(self.layout.hold(key), answered)
        return answered


def outcome(
    holds: Holds, key: str, answer: Answer | None
) -> Literal["approved", "declined", "unanswered"]:
    """Say how hold `key` was answered, as its log records it: as its call heard it, or where its call gave up, interrupted, as the operator answered it meanwhile, if they did."""
    given = answer
    if given is None:
        kept = holds.get(key)
        given = None if kept is None else kept.answer
    if given is None:
        return "unanswered"
    return "approved" if given.approved else "declined"


def stores(layout: Layout) -> list[Holds]:
    """Return the holds of every worktree's store."""
    if not layout.worktrees.is_dir():
        return []
    return [
        Holds(layout=StoreLayout(home=home))
        for home in sorted(layout.worktrees.iterdir())
        if home.is_dir()
    ]


def waiting(layout: Layout) -> list[Hold]:
    """Return every hold still waiting for an answer, in every worktree."""
    return [
        hold for holds in stores(layout) for hold in holds.all() if hold.answer is None
    ]


def logged(layout: Layout, verdicts: list[Verdict]) -> list[Hold]:
    """Return the holds whose verdicts are among `verdicts`, one repository's log as read: that repository's holds, open and answered, the oldest first.

    A hold is kept in the store of the worktree its session works in, which for
    a write in the repository's git directory isn't the worktree its verdict
    names, so every store is read. A hold is among them where one of its
    verdicts is, by its key and its worktree: a hold's key is unique within its
    own store alone, and its worktree is its repository's.
    """
    named = {verdict.key: verdict.worktree for verdict in verdicts}
    found = [
        hold
        for holds in stores(layout)
        for hold in holds.all()
        if any(
            each.key in named and named[each.key] == each.worktree
            for each in hold.verdicts
        )
    ]
    return sorted(found, key=lambda hold: hold.created)


def answer(
    layout: Layout,
    key: str,
    response: Response,
    runtimes: list[Runtime],
    clock: Clock,
    *,
    worktree: Path | None = None,
) -> Hold:
    """Answer hold `key`, unless this runs inside a session: in `worktree`'s store, where it's named, else wherever it's kept.

    A key is unique within one store alone, so one kept in more than one store,
    where no worktree is named, is refused, naming them, rather than answered
    in either.
    """
    inside = [runtime.name() for runtime in runtimes if runtime.inside()]
    if inside:
        message = (
            f"this runs inside a {inside[0]} session, and an agent doesn't answer "
            "its own hold: answer from your own terminal"
        )
        raise HoldError(message)
    searched = (
        stores(layout) if worktree is None else [Holds(layout=layout.store(worktree))]
    )
    holding = [holds for holds in searched if holds.get(key) is not None]
    if not holding:
        message = f"no hold {key} is waiting"
        raise HoldError(message)
    if len(holding) > 1:
        kept = ", ".join(str(holds.layout.holds) for holds in holding)
        message = f"hold {key} is kept in more than one worktree's store ({kept}): name its worktree"
        raise HoldError(message)
    hold = holding[0].answer(key, response, clock)
    if not hold.waited():
        common = Git(cwd=hold.worktree).text(
            "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        log = VerdictLog(path=layout.verdicts(Path(common)))
        log.append(answered(hold, "approved" if response.approved else "declined"))
    return hold


def unified(path: Path, before: str | None, after: str | None) -> str:
    """Show a write as a unified diff of `path`, from what it was to what it would be; none on a side where the file isn't."""
    lines = difflib.unified_diff(
        (before or "").splitlines(keepends=True),
        (after or "").splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(lines)
