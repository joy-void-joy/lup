"""What's on trial in the stand-in demo: the host's own handlers (`lup_dev.trying`) over what stands in for git.

`docs/dashboard.md`, *The demo*. What's on trial is computed with git, in a store
apart, and a demo runs no program: so the planning, the words, what a pick runs and
what it asks are `Trying`'s own, as the record (`Trials`) and the copies are the
host's, and only the merges stand in (`Trees`): which branches conflict is a table,
a tree says what it holds, and a commit is named from what it's made of. Moving the
host is `withheld_switch`'s, as for a copy. What accepting asks of a room stands in
too, its gate and its merge (`StoodAccepting`): the host's own handler runs over it,
apart and one at a time, as long as a gate stands in as taking, what stops it said
rather than raised.
"""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

from lup.types import Model, MutableModel
from lup_dev.composing import Apart, Composed, Unmerged
from lup_dev.host.protocol import HostError
from lup_dev.host.service import Route
from lup_dev.layout import Layout
from lup_dev.policy.landing import Turns, no_room, served_launches
from lup_dev.trial import AcceptingTools, OnTrial, Trial, Trials
from lup_dev.trying import (
    TrialAccepting,
    TrialChanging,
    TrialDropping,
    TrialListing,
    TrialPicking,
    Trying,
)

if TYPE_CHECKING:
    from datetime import datetime

    from lup_dev.clock import Clock
    from lup_dev.git import Git
    from lup_dev.host.protocol import Branches
    from lup_dev.host.watch import Changes
    from lup_dev.inbox.delivery import Delivery
    from lup_dev.layout import CopyLayout


class Conflict(Model):
    """Two of the demo's branches that don't merge together, and the file they conflict in."""

    one: str
    other: str
    file: Path


class Trees(MutableModel):
    """What stands in for git's merges: which branches conflict, what each commit of `dev` holds, and what tree each commit made is of, so a branch accepted makes the tree it made on trial."""

    conflicts: list[Conflict] = []
    holding: dict[str, list[str]] = {}
    """The branches each commit of `dev` holds, by its commit."""
    made: dict[str, str] = {}
    """The tree of each commit made, by its commit."""

    def tree(self, dev: str, names: list[str]) -> str:
        """Return the tree of the branches `names` on the commit `dev`: named from what it holds alone, as git's is."""
        held = sorted(dict.fromkeys([*self.holding.get(dev, []), *names]))
        return "tree of " + " ".join(held)

    def commit(self, tree: str, parents: list[str], message: str) -> str:
        """Make a commit of `tree`, with `parents` and `message`, and return its name."""
        named = hashlib.sha256(
            "\n".join([tree, *parents, message]).encode()
        ).hexdigest()
        self.made = {**self.made, named: tree}
        return named

    def conflicting(self, names: list[str]) -> Unmerged | None:
        """Return the first of `names` that conflicts with one before it, by their names' order, as git's merges find it; none where they all merge."""
        ordered = sorted(names)
        for at, each in enumerate(ordered):
            for before in ordered[:at]:
                pair = sorted([each, before])
                for conflict in self.conflicts:
                    if sorted([conflict.one, conflict.other]) == pair:
                        return Unmerged(branch=each, files=[conflict.file])
        return None


class StoodMerges(Apart):
    """A store apart that's no store: what the host's planning asks of one, answered by `Trees`, running nothing."""

    stood: Trees

    @override
    def merged(self, onto: str, tips: dict[str, str]) -> Composed | Unmerged:
        held = self.stood.holding.get(onto, [])
        names = [each for each in tips if each not in held]
        found = self.stood.conflicting(names)
        return Composed(tree=self.stood.tree(onto, names)) if found is None else found

    @override
    def committed(
        self, tree: str, parents: list[str], message: str, at: datetime
    ) -> str:
        del at
        return self.stood.commit(tree, parents, message)


class StoodTrying(Trying):
    """`Trying` over the demo's state: nothing of it reaches git, the rest being the host's own."""

    trees: Trees

    @override
    def composing(self, git: Git) -> AbstractContextManager[Apart]:
        return self.composed(git)

    @contextmanager
    def composed(self, git: Git) -> Generator[Apart]:
        """Hold what stands in for a store apart, as `composing` holds the real one."""
        yield StoodMerges(git=git, store=git, root=Path(), stood=self.trees)

    @override
    def holds(self, git: Git, dev: str, trial: Trial) -> Trial:
        del git
        held = self.trees.holding.get(dev, [])
        return trial.model_copy(
            update={
                "branches": [each for each in trial.branches if each.branch not in held]
            }
        )

    @override
    def dev_tip(self, git: Git, branches: Branches, trial: Trial, remote: str) -> str:
        del git, remote
        if trial.dev is None:
            message = f"the demo holds no `{branches.integration}`"
            raise HostError(message)
        return trial.dev

    @override
    def moved_to(
        self, git: Git, branches: Branches, commit: str, remote: str
    ) -> list[str]:
        del git, branches, commit, remote
        return []


class StoodAccepting(Model, AcceptingTools, arbitrary_types_allowed=True):
    """What stands in for accepting in a room, whose gate no demo runs: as the host, it needs a session of the repository running, takes a while, says what stopped it in words rather than raising, and follows `dev` moving as a landing's push does, the host's own handler following it again; what's on `dev` is what `Trees` holds."""

    layout: Layout
    trees: Trees
    takes: timedelta
    """How long the gate stands in as taking."""
    failing: dict[str, str] = {}
    """What the gate says of each branch that doesn't land, by its name."""
    follow: Callable[[Path, str], Awaitable[list[str]]]
    """Follows `dev` having moved, as the host's push does (`Trying.moved_dev`)."""

    @override
    def ready(self, repository: Path, on: OnTrial) -> None:
        if not served_launches(self.layout.host, repository):
            raise HostError(no_room(on.branch))

    @override
    async def accepted(self, repository: Path, on: OnTrial) -> str:
        await asyncio.sleep(self.takes.total_seconds())
        failing = self.failing.get(on.branch)
        if failing is not None:
            return failing
        trials = Trials.of(self.layout, repository)
        trial = trials.read()
        if trial.dev is None:
            message = "the demo holds no `dev`"
            raise HostError(message)
        tree = self.trees.tree(trial.dev, [on.branch])
        made = self.trees.commit(tree, [trial.dev], on.message)
        self.trees.holding = {
            **self.trees.holding,
            made: [*self.trees.holding.get(trial.dev, []), on.branch],
        }
        trials.write(trial.model_copy(update={"dev": made}))
        await self.follow(repository, on.remote)
        return f"Landed `{on.branch}` on `dev`, in the demo's own state."


class TrialStandIn(Model, arbitrary_types_allowed=True):
    """What the demo holds of what's on trial, beside the record: what stands in for git, what's run, and the approval a set never run asks."""

    trees: Trees
    zones: dict[str, str]
    """The host zone of each tree that's run, by the tree: every other zone is its
    own, so no copy holds it."""
    propose: Callable[[Path], int | None]
    """Says the number of the approval a set never run asks."""
    takes: timedelta = timedelta(seconds=4)
    """How long a merge's gate stands in as taking."""
    failing: dict[str, str] = {}
    """What the gate says of each branch that doesn't land, by its name."""

    def routes(
        self,
        lup: Layout,
        delivery: Delivery,
        *,
        clock: Clock,
        say: Callable[[str], None],
        start: Callable[[CopyLayout, str], None],
        changes: Changes,
    ) -> list[Route]:
        """Return the routes of what's on trial, over the demo's state at `lup`: the host's own handlers, `start` moving the host, as far as a demo does."""

        def zone(repository: Path, commit: str) -> str:
            del repository
            tree = self.trees.made.get(commit, commit)
            return self.zones.get(tree, f"the zone at {commit}")

        trying = StoodTrying(
            layout=lup,
            clock=clock,
            say=say,
            turns=Turns(),
            fingerprint=zone,
            propose=self.propose,
            start=start,
            trees=self.trees,
        )
        return [
            Route.to(TrialListing(trying=trying)),
            Route.to(TrialPicking(trying=trying)),
            Route.to(TrialChanging(trying=trying)),
            Route.to(TrialDropping(trying=trying, delivery=delivery)),
            Route.to(
                TrialAccepting(
                    trying=trying,
                    tools=StoodAccepting(
                        layout=lup,
                        trees=self.trees,
                        takes=self.takes,
                        failing=self.failing,
                        follow=trying.moved_dev,
                    ),
                    changes=changes,
                )
            ),
        ]
