"""Holds: a change waiting inside the hook for the operator's answer.

On a runtime that can't ask before a call, an ask is held at the checkpoint: the
agent waits inside the hook while the operator answers with `lup-dev holds approve
<key>` or `lup-dev holds decline <key> --comment …` (`docs/judging-writes.md`,
*Asking the operator*). A decline puts the change back and saves it, with the
comment beside it; an approval with a comment passes the comment on. Unanswered
within the patience, the change is put back and saved, and the hold stays open.

What a move of `HEAD` asks is already committed, and isn't put back, so on every
runtime it's kept as a hold no agent waits on, with the commit it came from
(*A move's asks, after the fact*). Its answer is logged when it's given, and told
to the session that found the move at its next checkpoint; a decline changes no
file.

Nobody answers their own hold: answering refuses to run inside an agent's session,
as each runtime's adapter recognizes it. That stops a mistake, not a determined
agent; the real separation comes with containers.
"""

import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from lup.types import Model
from lup_dev.errors import LupDevError
from lup_dev.layout import Layout, StoreLayout
from lup_dev.policy.roles import Role
from lup_dev.policy.store import Git, read_model, write_model
from lup_dev.policy.verdicts import Verdict, VerdictLog

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lup_dev.clock import Clock
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
    """The held content's object id in the store."""
    reasons: list[str]
    """The kinds of ask, as the verdict log records them."""
    asks: list[str]
    """What the change asks, one line each, for the operator."""


class Hold(Model):
    """A change waiting for the operator."""

    key: str
    worktree: Path
    session: str
    """The session that made the change, or for a move's, that found it."""
    created: datetime
    files: list[HeldFile]
    diff: str
    """The change as a unified diff, for the operator to read."""
    commit: str | None = None
    """The commit a move of `HEAD` reached, for a hold no agent waits on; none for
    one an agent waits on."""
    verdicts: list[Verdict] = []
    """The verdicts logged on its files, which its answer is logged against."""
    answer: Answer | None = None
    abandoned: bool = False
    """Whether the wait ran out: the change was put back, and the hold stays open."""
    delivered: bool = False
    """Whether an answer given while no agent waited reached the session."""

    def waited(self) -> bool:
        """Say whether an agent waits inside its hook for the answer."""
        return self.commit is None and not self.abandoned


def answered(
    hold: Hold, outcome: Literal["approved", "declined", "unanswered"]
) -> list[Verdict]:
    """Return the verdicts on a hold's files again, with how it was answered."""
    return [verdict.model_copy(update={"answer": outcome}) for verdict in hold.verdicts]


class Holds(Model):
    """The holds kept in one worktree's store."""

    layout: StoreLayout

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

    def wait(
        self,
        key: str,
        clock: Clock,
        patience: timedelta = timedelta(hours=24),
        poll: timedelta = timedelta(seconds=2),
    ) -> Answer | None:
        """Wait for the operator to answer hold `key`; none if `patience` runs out.

        The first lup held calls for 4 hours without trouble; a day leaves room
        for an operator away overnight.
        """
        deadline = clock.now() + patience
        while True:
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
        self, key: str, *, abandoned: bool = False, delivered: bool = False
    ) -> None:
        """Note that hold `key` was given up on, or that its late answer was told."""
        hold = self.get(key)
        if hold is None:
            return
        marked = hold.model_copy(
            update={
                "abandoned": hold.abandoned or abandoned,
                "delivered": hold.delivered or delivered,
            }
        )
        write_model(self.layout.hold(key), marked)

    def late(self) -> list[Hold]:
        """Return the holds answered while no agent waited, not yet told.

        Those whose wait ran out, and a move's, which nobody waits on.
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


def answer(
    layout: Layout,
    key: str,
    response: Response,
    runtimes: list[Runtime],
    clock: Clock,
) -> Hold:
    """Answer hold `key`, wherever it's kept, unless this runs inside a session."""
    inside = [runtime.name() for runtime in runtimes if runtime.inside()]
    if inside:
        message = (
            f"this runs inside a {inside[0]} session, and an agent doesn't answer "
            "its own hold: answer from your own terminal"
        )
        raise HoldError(message)
    holding = [holds for holds in stores(layout) if holds.get(key) is not None]
    if not holding:
        message = f"no hold {key} is waiting"
        raise HoldError(message)
    hold = holding[0].answer(key, response, clock)
    if not hold.waited():
        common = Git(cwd=hold.worktree).text(
            "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        log = VerdictLog(path=layout.verdicts(Path(common)))
        log.append(answered(hold, "approved" if response.approved else "declined"))
    return hold
