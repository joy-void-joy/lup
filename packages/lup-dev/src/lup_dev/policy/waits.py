"""The landings waiting on the operator: each file a landing holds on, shown in its writer's "since you approved" drawer and answered there.

`docs/judging-writes.md`, *Landing a branch*. A landing waits on each file it
changes that's flagged on a branch it lands, the flags not approved
(`lup_dev.policy.landing`). It makes no item of the inbox for it: each file is
a state of the file in its writer's drawer (`lup_dev.policy.since`), held at
landing, where Space `d` marks it reviewed, approving its flags, and Space `x`
declines its landing. So a landing's wait is kept here, in the host service's
memory, for as long as its call waits: the drawer reads it, the page watches
it (`ShowLandings`), and the call waits on what it says. A call replayed after
the service starts again (`docs/host.md`, *Restarts and the sweep*) waits
again, so nothing of a wait needs to outlast the process: the flags are the
inbox's, and an answer the operator gave reached them.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal, override

from lup.types import Model, MutableModel
from lup_dev.host.protocol import Reply, Request
from lup_dev.host.service import Reading, Route
from lup_dev.host.watch import Changes, Touched
from lup_ledger.parties import Conversation


class Declined(Model):
    """The operator's decline of one file's landing: when, and what they said on the file in the reply that declined it."""

    at: datetime
    words: str = ""
    """Their comments on the file, each quoting its lines, as the reply sent
    them to its writer; empty where they said nothing."""


class Awaited(Model):
    """One file a landing waits on: flagged on a branch it lands, not approved; who flagged it; and the operator's decline, once they declined it."""

    path: Path
    """From the repository's root."""
    flags: list[int]
    """The flagged writes on it the landing waits on, each approved by marking
    the file reviewed."""
    writers: list[Conversation]
    """The conversations that wrote it, the flags' senders: whose "since you
    approved" shows it."""
    declined: Declined | None = None


class Wait(Model):
    """One landing waiting on the operator: who lands, what, where to, and each file it waits on."""

    key: str
    """Names it among the landings waiting: its call's id, else its tip and
    when it began."""
    repository: Path
    """The repository's git directory."""
    lander: Conversation
    """The conversation landing, whose call waits."""
    onto: str
    """The gated branch it moves, by its full name: `refs/heads/dev`."""
    old: str | None
    """That branch's tip on the remote, which a file the operator saw none of is
    shown from; none where it isn't there yet."""
    tip: str
    """The commit it lands, whose version of each file is what's shown and
    approved."""
    branches: list[str]
    """The branches it lands whose flags it waits on, by their short names."""
    files: list[Awaited]
    began: datetime

    def on(self, branch: str | None, path: Path) -> Awaited | None:
        """Return the file at `path` it waits on for `branch`, where it lands that branch and waits on that file; none else."""
        if branch is None or branch not in self.branches:
            return None
        return next((each for each in self.files if each.path == path), None)

    @property
    def named(self) -> str:
        """Say what lands where, as a line names it, the branches landed and where to.

        >>> Wait(key="k", repository=Path("/r.git"), lander=Conversation(repository=Path("/r.git"),
        ...     runtime="r", session="s"), onto="refs/heads/dev", old=None, tip="abc",
        ...     branches=["feat", "fix"], files=[], began=datetime(2026, 1, 1)).named
        '`feat` and `fix` on `dev`'
        """
        names = [f"`{each}`" for each in self.branches]
        landed = (
            names[0]
            if len(names) == 1
            else f"{', '.join(names[:-1])} and {names[-1]}"
            if names
            else "it"
        )
        return f"{landed} on `{self.onto.removeprefix('refs/heads/')}`"


class Waits(MutableModel, arbitrary_types_allowed=True):
    """Every landing waiting on the operator, by its key, in the host service's memory: each told to `changes` as it begins, is answered and ends, so the page watching them and the drawers of their files' writers are answered again."""

    waits: dict[str, Wait] = {}
    changes: Changes | None = None

    def began(self, wait: Wait) -> None:
        """Keep `wait`, a landing beginning to wait, in place of one of the same key."""
        self.waits = {**self.waits, wait.key: wait}
        self.told(wait)

    def ended(self, key: str) -> None:
        """Forget the landing kept under `key`, its call done waiting; nothing where none is."""
        wait = self.waits.get(key)
        if wait is None:
            return
        self.waits = {each: kept for each, kept in self.waits.items() if each != key}
        self.told(wait)

    def of(self, repository: Path) -> list[Wait]:
        """Return the landings of `repository` waiting, the oldest first."""
        return sorted(
            (each for each in self.waits.values() if each.repository == repository),
            key=lambda each: each.began,
        )

    def holding(self, flag: int) -> str | None:
        """Say what the landing waiting on the flagged write `flag`, by its number, lands where, the oldest's where several do (`Wait.named`); none where none waits on it: as the inbox's line of a conversation's flags says it (`Delivery.landing`).

        >>> waits = Waits()
        >>> waits.began(Wait(key="k", repository=Path("/r.git"), lander=Conversation(
        ...     repository=Path("/r.git"), runtime="r", session="s"), onto="refs/heads/dev",
        ...     old=None, tip="abc", branches=["feat"], files=[Awaited(path=Path("a.py"),
        ...     flags=[3], writers=[])], began=datetime(2026, 1, 1)))
        >>> waits.holding(3), waits.holding(4)
        ('`feat` on `dev`', None)
        """
        return next(
            (
                wait.named
                for wait in sorted(self.waits.values(), key=lambda each: each.began)
                if any(flag in each.flags for each in wait.files)
            ),
            None,
        )

    def on(self, repository: Path, branch: str | None, path: Path) -> list[Wait]:
        """Return the landings of `repository` waiting on the file at `path` for `branch`."""
        return [
            each for each in self.of(repository) if each.on(branch, path) is not None
        ]

    def declined(
        self, repository: Path, branch: str, path: Path, declined: Declined
    ) -> list[Wait]:
        """Record the operator's decline of the file at `path` on `branch`, on each landing of `repository` waiting on it, and return those: told by the caller (`told`), on the service's loop, since a marking runs off it."""
        found = self.on(repository, branch, path)

        def declining(wait: Wait) -> Wait:
            files = [
                each.model_copy(update={"declined": declined})
                if each.path == path
                else each
                for each in wait.files
            ]
            return wait.model_copy(update={"files": files})

        changed = [declining(each) for each in found]
        self.waits = {**self.waits, **{each.key: each for each in changed}}
        return changed

    def told(self, wait: Wait) -> None:
        """Tell `changes` that `wait` changed, touching its lander and each writer of its files, as an item of theirs would."""
        if self.changes is None:
            return
        parties = dict.fromkeys(
            [wait.lander, *(who for each in wait.files for who in each.writers)]
        )
        self.changes.changed(
            Touched(
                repository=each.repository,
                runtime=each.runtime,
                session=each.session,
                agent=each.agent,
                by="item",
            )
            for each in parties
        )


class ShowLandings(Request, reads=True):
    """Read the landings waiting on the operator, each with the files it waits on."""

    kind: Literal["policy-show-landings"] = "policy-show-landings"


class LandingsWaiting(Reply):
    """The landings waiting on the operator, the oldest first."""

    kind: Literal["policy-landings"] = "policy-landings"
    waiting: list[Wait] = []


class LandingsShowing(Model, Reading[ShowLandings], arbitrary_types_allowed=True):
    """Answers `ShowLandings`: every repository's landings waiting; for a room, its own repository's alone."""

    waits: Waits

    @override
    def request(self) -> type[ShowLandings]:
        return ShowLandings

    @override
    async def answer(self, request: ShowLandings) -> Reply:
        return LandingsWaiting(
            waiting=sorted(self.waits.waits.values(), key=lambda each: each.began)
        )

    @override
    async def scoped(self, request: ShowLandings, repository: Path) -> Reply:
        return LandingsWaiting(waiting=self.waits.of(repository))


def routes(waits: Waits) -> list[Route]:
    """Route reading the landings waiting, kept in `waits`, to its handler."""
    return [Route.reading(LandingsShowing(waits=waits))]
