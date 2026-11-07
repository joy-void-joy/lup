"""The operator's side of what's on trial: picking what `live` holds, accepting and dropping a branch, and what follows `dev` moving.

`docs/trust.md`, *What the host runs while it's on trial*. A branch goes on trial by
landing (`Lander.on_trial`), in a room; the rest of what moves `live` comes from no
room, so it's here, in the host service: the operator asks through their terminal
or the plain page, on the control socket, which no room reaches.

Accepting a branch runs the gate on its merge, in a room, which takes minutes: asked
apart (`AcceptBranch.apart`), as the review asks, it's answered at once, merges one at
a time, and what it comes to is said where what's on trial is listed, while anything
moving the host waits, since a restart would stop the gate (`Merges`).

A new `live` commit is what any of these comes to. It's computed from the record, in
a store apart (`lup_dev.trial`, `lup_dev.composing`), and what happens next depends on
what it runs, by the fingerprint of its host zone, which says what the operator
approved whatever commit holds it:
- **the same as what's approved:** nothing the host runs changes, so nothing is asked
  and nothing restarts: a branch accepted that was in `live` comes to this;
- **a copy kept, approved at that fingerprint:** the operator asked for that set, and
  has said yes to it, so the host moves to it at once (`CopySwitch`, whose process
  `lup-dev restore` is), which the operator chose by asking;
- **anything else:** the approval, as a push moving the running branch asks it, whose
  yes installs the copy, keeps it, and moves there. Nothing is built before that yes,
  since a build runs the branch's own steps on the host.

A copy that would need the ledger restored is refused before anything moves, as the
plain page refuses it, sending that to the terminal.

Each is held to one at a time in a repository, with a landing's merge (`Turns`).
"""

import asyncio
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, override

from pydantic import Field

from lup.types import Model, MutableModel
from lup_dev.approval import approved, approved_branches
from lup_dev.clock import Clock
from lup_dev.composing import Apart, Composed, Unmerged, apart
from lup_dev.copies import Copies
from lup_dev.errors import LupDevError
from lup_dev.git import Git
from lup_dev.host.on_trial import (
    AcceptBranch,
    ChangeBranches,
    CopySwitching,
    DropBranch,
    ListTrial,
    PickBranches,
    TrialListed,
    TrialSaid,
)
from lup_dev.host.protocol import Branches, HostError, Reply
from lup_dev.host.service import Companion, Handler
from lup_dev.host.watch import Changes, TrialMoved
from lup_dev.host.workers import Listing, RepositoryAsking
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.store import cited
from lup_dev.layout import CopyLayout, Layout
from lup_dev.policy.landing import Turns
from lup_dev.snapshots import Snapshots
from lup_dev.switching import host_copies, last_switch, needs_ledger, own_repository
from lup_dev.trial import (
    AcceptingTools,
    OnTrial,
    Origin,
    Plan,
    Trial,
    Trials,
    accepted,
    computed_ref,
    files_said,
    move_ref,
    moved_on,
    named,
    next_commit,
    pins,
    plan,
    trial_listed,
)
from lup_ledger.environment.layout import LedgerLayout

if TYPE_CHECKING:
    from contextlib import AbstractContextManager


class RepositoryMerges(MutableModel, arbitrary_types_allowed=True):
    """One repository's merges under way, and what the last ones said, in the service's memory: a merge's gate outlasts the request, and the page that asked for it."""

    turn: asyncio.Lock = Field(default_factory=asyncio.Lock)
    """Held while one merges: each reads the integration branch's tip as it starts, so
    two together would have the second refused as it moved."""
    underway: list[str] = []
    """Each merging or waiting its turn, by its branch's name."""
    failed: dict[str, str] = {}
    """What the last try at each said, where it didn't land, by its branch's name."""
    landed: list[str] = []
    """What the last few that landed said, the latest last."""
    remembering: int = 3
    """How many of them it keeps: each is what its branch's own line would have
    said, and the review's own says it's gone."""
    tasks: list[asyncio.Task[None]] = []
    """What's running apart, kept so it isn't collected as it runs."""

    def ended(self, branch: str, said: str, *, landed: bool) -> None:
        """Say `branch` is done merging, what came of it `said`."""
        self.underway = [each for each in self.underway if each != branch]
        others = {name: each for name, each in self.failed.items() if name != branch}
        self.failed = others if landed else {**others, branch: said}
        if landed:
            self.landed = [*self.landed, said][-self.remembering :]


class Merges(MutableModel, arbitrary_types_allowed=True):
    """Each repository's merges under way, by its git directory."""

    repositories: dict[Path, RepositoryMerges] = {}

    def of(self, repository: Path) -> RepositoryMerges:
        """Return the merges of the repository at `repository`."""
        return self.repositories.setdefault(repository, RepositoryMerges())


class Computed(Model):
    """`live` computed afresh: the record as it would stand, what it holds, and its next commit, none where it's that already."""

    trial: Trial
    plan: Plan
    dev: str
    commit: str | None


class Trying(Model, arbitrary_types_allowed=True):
    """What's on trial in each repository the service serves, moved by what the operator asks."""

    layout: Layout
    clock: Clock
    say: Callable[[str], None]
    turns: Turns
    """One at a time in each repository, with a landing's merge."""
    fingerprint: Callable[[Path, str], str]
    """Says the fingerprint of the host zone at a commit of the repository at the
    path given, by what's approved, reading no code of it (`Trust.zone_at`)."""
    propose: Callable[[Path], int | None]
    """Puts the approval of the running branch's tip in the operator's inbox where
    it isn't what's approved, as a push moving it does, and says its number
    (`Trust.proposed`)."""
    start: Callable[[CopyLayout, str], None]
    """Starts the copy's `lup-dev restore`, in a session of its own, given where
    it's installed and the commit: it stops this service."""
    merges: Merges = Field(default_factory=Merges)
    """Each repository's merges under way, and what the last ones said."""

    def refuse_merging(self, repository: Path) -> None:
        """Raise `HostError` where a branch of `repository` is merging: moving the host would stop its gate."""
        underway = self.merges.of(repository).underway
        if underway:
            message = (
                f"{named(underway)} is merging, whose gate runs in a session's room, "
                "and moving the host now would stop it: ask this again once it's done"
            )
            raise HostError(message)

    def repository(self, asked: Path | None) -> Path:
        """Return the repository asked for, or lup's own, which the service runs from: raise `HostError` where it's not known, or computes no running branch."""
        copies = host_copies(self.layout)
        found = asked or (None if copies is None else own_repository(copies))
        if found is None:
            message = (
                "no copy of `lup-dev` is kept yet, so which repository's trial isn't "
                "known: run this in its checkout"
            )
            raise HostError(message)
        branches = approved_branches(self.layout, found)
        if branches.running == branches.integration:
            message = (
                f"{found} runs `{branches.running}` itself, with nothing on trial: "
                "a project selects that with `Versions`"
            )
            raise HostError(message)
        return found

    def dev_tip(self, git: Git, branches: Branches, trial: Trial, remote: str) -> str:
        """Return the integration branch's tip on `remote`, in the store, so a pick needs no room; where it can't be reached, what's kept of it, a pick being what a network down mustn't stop. Raise `HostError` where neither says."""
        try:
            found = Origin(git=git, remote=remote).tip(branches.integration_ref)
        except LupDevError as unreached:
            if trial.dev is None:
                message = f"`{remote}` can't say where `{branches.integration}` is: {unreached}"
                raise HostError(message) from unreached
            return trial.dev
        if found is not None:
            return found
        if trial.dev is not None:
            return trial.dev
        message = f"`{remote}` has no `{branches.integration}` to compute from"
        raise HostError(message)

    def composing(self, git: Git) -> AbstractContextManager[Apart]:
        """Hold what `live` is merged in, for the repository `git` is pinned to: a store apart (`lup_dev.composing`), which a demo's stand-in answers for (`lup_dashboard/trialed.py`)."""
        return apart(git)

    def holds(self, git: Git, dev: str, trial: Trial) -> Trial:
        """Return `trial` without each branch the commit `dev` holds, as git says (`accepted`)."""
        return accepted(git, dev, trial)

    def moved_to(
        self, git: Git, branches: Branches, commit: str, remote: str
    ) -> list[str]:
        """Name `commit` where lup's asked and on `remote`, and say what's left undone: `live` still moves where a ref can't, or the network's down, as what's kept is what reads."""
        left = move_ref(git, branches, commit)
        said = [] if left is None else [f"{left}."]
        try:
            Origin(git=git, remote=remote).pushed(commit, branches.running_ref)
        except LupDevError as failed:
            said.append(f"`{branches.running}` isn't on `{remote}` yet: {failed}")
        return said

    def computed(
        self, git: Git, trial: Trial, branches: Branches, dev: str
    ) -> Computed:
        """Compute `live` from `trial` on the commit `dev`, each branch `dev` holds off trial, and make its next commit, no ref naming it yet."""
        now = self.holds(git, dev, trial)
        with self.composing(git) as store:
            found = plan(store, dev, branches.integration, now)
            commit = next_commit(
                store, now, dev, branches.integration, found, at=self.clock.now()
            )
        return Computed(trial=now, plan=found, dev=dev, commit=commit)

    def kept(
        self,
        repository: Path,
        git: Git,
        computed: Computed,
        remote: str,
        fingerprint: str | None = None,
    ) -> list[str]:
        """Keep `computed`, whose host zone has `fingerprint`, where it's been read, naming its commit (`moved_to`), and say what's left undone."""
        branches = approved_branches(self.layout, repository)
        commit = computed.commit or computed.trial.live or computed.dev
        stands = moved_on(
            computed.trial,
            commit,
            computed.dev,
            computed.plan,
            self.clock.now(),
            fingerprint=fingerprint,
        )
        Trials.of(self.layout, repository).write(stands)
        Copies(layout=self.layout.judge(repository)).pin(pins(stands))
        if computed.commit is None:
            return []
        return self.moved_to(git, branches, commit, remote)

    async def moved_dev(self, repository: Path, remote: str = "origin") -> list[str]:
        """Follow `dev` having moved, a landing or an accepting moved it, as `live` holds it: compute it again, asking nothing where nothing the host runs changes, and the approval where something does; say what came of it, a line each."""
        branches = approved_branches(self.layout, repository)
        if branches.running == branches.integration:
            return []
        async with self.turns.of(repository):
            return await asyncio.to_thread(self.following, repository, branches, remote)

    def following(self, repository: Path, branches: Branches, remote: str) -> list[str]:
        """Do what `moved_dev` says, off the event loop."""
        git = Git.pinned(repository)
        trial = Trials.of(self.layout, repository).read()
        dev = self.dev_tip(git, branches, trial, remote)
        found = self.computed(git, trial, branches, dev)
        fingerprint = (
            None if found.commit is None else self.fingerprint(repository, found.commit)
        )
        said = self.kept(repository, git, found, remote, fingerprint)
        return [
            *said,
            *self.fell_out(found),
            *self.asked(repository, found, fingerprint),
        ]

    def fell_out(self, computed: Computed) -> list[str]:
        """Say each branch that stopped merging as `live` moved, keeping it out, a line each."""
        return [
            f"`{each.branch}` left `live`: {computed.plan.conflicts[each.branch]}."
            for each in computed.trial.branches
            if each.branch in computed.plan.conflicts
            and each.branch in computed.trial.tips
        ]

    def asked(
        self, repository: Path, computed: Computed, fingerprint: str | None
    ) -> list[str]:
        """Ask the operator about `computed`'s commit, whose host zone has `fingerprint`, where it runs what isn't approved; say so. It's asked nothing where that's the same."""
        if computed.commit is None:
            return []
        approval = approved(self.layout, repository)
        if approval is not None and approval.fingerprint == fingerprint:
            return []
        number = self.propose(repository)
        if number is None:
            return []
        return [
            (
                f"{cited(number)} in your inbox asks about it: a yes builds that copy "
                "and moves the host there."
            )
        ]

    async def picked(
        self,
        asked: Path | None,
        names: list[str],
        *,
        seen: dict[str, str] | None = None,
        dev: str | None = None,
    ) -> TrialSaid:
        """Run `dev` plus exactly `names`, as the operator asked: at once where it's what's approved, or a copy of it is kept; else asking their yes. Refused where a name isn't on trial or they conflict, or its copy needs the ledger restored, or, what they saw of it being `seen` and `dev`, where that moved since, or a merge is under way, nothing having moved."""
        repository = self.repository(asked)
        async with self.turns.of(repository):
            self.refuse_merging(repository)
            return await asyncio.to_thread(
                self.picking, repository, names, seen or {}, dev
            )

    def refuse_unseen(self, trial: Trial, seen: dict[str, str]) -> None:
        """Raise `HostError` where a branch of `seen` has landed again since it was seen at the tip it says."""
        moved = [
            name
            for name, tip in seen.items()
            if (on := trial.on(name)) is not None and on.tip != tip
        ]
        if moved:
            message = (
                f"{named(moved)} landed again since you marked it: look at it again"
            )
            raise HostError(message)

    def picking(
        self,
        repository: Path,
        names: list[str],
        seen: dict[str, str],
        seen_dev: str | None,
    ) -> TrialSaid:
        """Do what `picked` says, off the event loop."""
        branches = approved_branches(self.layout, repository)
        trial = Trials.of(self.layout, repository).read()
        unknown = [each for each in names if trial.on(each) is None]
        if unknown:
            message = f"{named(unknown)} isn't on trial: `lup-dev live` lists what is"
            raise HostError(message)
        self.refuse_unseen(trial, seen)
        git = Git.pinned(repository)
        remote = next((each.remote for each in trial.branches), "origin")
        dev = self.dev_tip(git, branches, trial, remote)
        if seen_dev is not None and dev != seen_dev:
            message = (
                f"`{branches.integration}` moved since you marked it: look at it again"
            )
            raise HostError(message)
        self.refuse_conflict(git, trial, names, dev, branches)
        chosen = trial.model_copy(
            update={
                "branches": [
                    each.model_copy(update={"out": each.branch not in names})
                    for each in trial.branches
                ]
            }
        )
        found = self.computed(git, chosen, branches, dev)
        return self.running(repository, git, found, remote)

    async def changed(
        self,
        asked: Path | None,
        taking: list[str],
        leaving: list[str],
        seen: dict[str, str],
    ) -> TrialSaid:
        """Put `taking` in what runs and leave `leaving` out, each other branch as it stands, one kept out by a conflict still coming back where it merges; run that as `picked` does. Refused, nothing having moved, where they conflict, where one moved since it was `seen`, or a merge is under way; a branch off trial since is said, there being nothing left to do with it."""
        repository = self.repository(asked)
        async with self.turns.of(repository):
            self.refuse_merging(repository)
            return await asyncio.to_thread(
                self.changing, repository, taking, leaving, seen
            )

    def changing(
        self,
        repository: Path,
        taking: list[str],
        leaving: list[str],
        seen: dict[str, str],
    ) -> TrialSaid:
        """Do what `changed` says, off the event loop, under the repository's turn: what's in what runs is read here, so a branch landing meanwhile joins it rather than being left out unseen."""
        branches = approved_branches(self.layout, repository)
        trial = Trials.of(self.layout, repository).read()
        self.refuse_unseen(trial, seen)
        gone = [
            f"`{each}` isn't on trial any more."
            for each in dict.fromkeys([*taking, *leaving])
            if trial.on(each) is None
        ]
        taken = [each for each in taking if trial.on(each) is not None]
        left = [each for each in leaving if trial.on(each) is not None]
        if not taken and not left:
            return self.said(repository, gone)
        git = Git.pinned(repository)
        remote = next((each.remote for each in trial.branches), "origin")
        dev = self.dev_tip(git, branches, trial, remote)
        wanted = [each for each in trial.tips if each not in left]
        self.refuse_conflict(
            git, trial, list(dict.fromkeys([*wanted, *taken])), dev, branches
        )
        chosen = trial.model_copy(
            update={
                "branches": [
                    each.model_copy(
                        update={
                            "out": each.branch in left
                            or (each.out and each.branch not in taken)
                        }
                    )
                    for each in trial.branches
                ]
            }
        )
        found = self.computed(git, chosen, branches, dev)
        reply = self.running(repository, git, found, remote)
        return reply.model_copy(update={"said": "\n".join([*gone, reply.said])})

    def refuse_conflict(
        self, git: Git, trial: Trial, names: list[str], dev: str, branches: Branches
    ) -> None:
        """Refuse, with `HostError`, branches `names` that can't be picked together, naming what conflicts in what."""
        tips = {
            each.branch: each.tip for each in trial.branches if each.branch in names
        }
        with self.composing(git) as store:
            match store.merged(dev, tips):
                case Composed():
                    return
                case Unmerged(branch=branch, files=files):
                    pass
        message = (
            f"{named(sorted(tips))} can't be picked together: `{branch}` conflicts "
            f"with what's before it on `{branches.integration}`, {files_said(files)}. "
            "Nothing moved."
        )
        raise HostError(message)

    def running(
        self, repository: Path, git: Git, found: Computed, remote: str
    ) -> TrialSaid:
        """Move `live` to `found`'s commit, and the host with it, by what it runs: nothing at all where that's approved; a switch where a copy of it is kept; else the approval.

        Which of them is read before anything is kept, so a copy that would need
        the ledger restored moves nothing.
        """
        commit = found.commit or found.trial.live or found.dev
        fingerprint = self.fingerprint(repository, commit)
        approval = approved(self.layout, repository)
        if approval is not None and approval.fingerprint == fingerprint:
            said = self.kept(repository, git, found, remote, fingerprint)
            return self.said(
                repository,
                [
                    *said,
                    (
                        f"`live` is at {commit}, and what the host runs doesn't "
                        "change: nothing restarts."
                    ),
                ],
            )
        copies = Copies(layout=self.layout.judge(repository))
        copy = next(
            (
                each
                for each in copies.kept()
                if each.approval.fingerprint == fingerprint
            ),
            None,
        )
        if copy is None:
            said = self.kept(repository, git, found, remote, fingerprint)
            number = self.propose(repository)
            return self.said(
                repository,
                [
                    *said,
                    (
                        f"`live` is at {commit}. No copy of it is built, and a build "
                        "runs its code on this machine, so it waits on your yes: "
                        f"{'' if number is None else f'{cited(number)} in your inbox. '}"
                        "A yes builds it, which takes minutes, and moves the host there."
                    ),
                ],
            )
        snapshots = Snapshots(
            home=self.layout.snapshots, ledger=LedgerLayout.of(self.layout)
        )
        if needs_ledger(snapshots, copy.name) is not None:
            message = (
                f"{copy.commit} can't read the ledger as it stands, and restoring what "
                "it left loses what happened since, so nothing moved: `lup-dev restore "
                f"{copy.commit} --ledger`, in a terminal, says how much, and asks"
            )
            raise HostError(message)
        self.kept(repository, git, found, remote, fingerprint)
        last = last_switch(self.layout)
        running = copies.running()
        from_copy = copy if copy.answered is not None or running is None else running
        self.start(copies.place(from_copy), copy.commit)
        return TrialSaid(
            said=f"The host moves to {copy.commit}, in a few seconds.",
            listed=self.listed(repository),
            switching=CopySwitching(
                commit=copy.commit, log=self.layout.host.log, last=last
            ),
        )

    async def dropped(
        self, asked: Path | None, branch: str, words: str, delivery: Delivery
    ) -> TrialSaid:
        """Take `branch` off trial, its branch and its worktree left, leaving what the operator said on it for who landed it, told at their next call whenever that is; where it was in `live`, what runs moves as a pick does."""
        repository = self.repository(asked)
        async with self.turns.of(repository):
            self.refuse_merging(repository)
            trial = await asyncio.to_thread(Trials.of(self.layout, repository).read)
            on = trial.on(branch)
            if on is None:
                message = f"`{branch}` isn't on trial: `lup-dev live` lists what is"
                raise HostError(message)
            reply = await asyncio.to_thread(self.dropping, repository, trial, on)
            told = self.told(delivery, on, words)
        if told:
            return reply.model_copy(update={"said": f"{reply.said}\n{told}"})
        return reply

    def dropping(self, repository: Path, trial: Trial, on: OnTrial) -> TrialSaid:
        """Do what `dropped` says, off the event loop, but what's left for who landed it, which the inbox keeps on the event loop."""
        branches = approved_branches(self.layout, repository)
        left = trial.model_copy(
            update={"branches": [each for each in trial.branches if each != on]}
        )
        if on.branch not in trial.tips:
            Trials.of(self.layout, repository).write(left)
            return self.said(repository, [f"`{on.branch}` is off trial."])
        git = Git.pinned(repository)
        dev = self.dev_tip(git, branches, left, on.remote)
        found = self.computed(git, left, branches, dev)
        return self.running(repository, git, found, on.remote)

    def told(self, delivery: Delivery, on: OnTrial, words: str) -> str:
        """Leave what the operator said on dropping `on` for who landed it; say so, where there's anything to say and someone to say it to."""
        if not words or on.party is None:
            return ""
        delivery.left(
            on.party,
            f"lup: the operator dropped `{on.branch}` from trial, saying: {words}",
        )
        return "Your words wait for who landed it, beside their next call."

    def said(self, repository: Path, lines: list[str]) -> TrialSaid:
        """Return `lines`, and what's on trial then."""
        return TrialSaid(said="\n".join(lines), listed=self.listed(repository))

    def listed(self, repository: Path) -> TrialListed | None:
        """Return what's on trial in `repository`, as a page lists it, with what's merging apart, and what came of the last switch where it's lup's own, whose copy that moved."""
        kept = Copies(layout=self.layout.judge(repository)).kept()
        listed = trial_listed(self.layout, repository, kept)
        if listed is None:
            return None
        merges = self.merges.of(repository)
        copies = host_copies(self.layout)
        own = None if copies is None else own_repository(copies)
        return listed.model_copy(
            update={
                "last": last_switch(self.layout) if own == repository else None,
                "merged": merges.landed,
                "branches": [
                    each.model_copy(
                        update={
                            "merging": each.branch in merges.underway,
                            "merge_said": merges.failed.get(each.branch, ""),
                        }
                    )
                    for each in listed.branches
                ],
            }
        )


class OwnViewsSaid(MutableModel, Companion, arbitrary_types_allowed=True):
    """Has lup's own repository's process say how its views look as the service starts, where it computes its running branch: the review's row of what runs is placed by what that says, and a switch restarts the service, with no process running until something asks one, a session at work or the page watching what it doesn't yet know to."""

    layout: Layout
    asking: RepositoryAsking
    changes: Changes
    """Told once it has said, so a page's listing is answered again."""
    say: Callable[[str], None]
    saying: asyncio.Task[None] | None = None

    @override
    async def begin(self) -> None:
        copies = host_copies(self.layout)
        repository = None if copies is None else own_repository(copies)
        if repository is None or computed_ref(self.layout, repository) is None:
            return
        self.saying = asyncio.create_task(self.asked(repository))

    @override
    async def end(self) -> None:
        if self.saying is not None:
            self.saying.cancel()

    async def asked(self, repository: Path) -> None:
        """Ask `repository`'s process what it serves, which starts it, and tell whoever watches; say why not, where it can't."""
        try:
            await self.asking.asked(repository, Listing())
        except HostError as failed:
            self.say(f"{repository}: how its views look isn't known yet: {failed}")
            return
        self.changes.changed()


class TrialListing(Model, Handler[ListTrial]):
    """Answers `ListTrial`: what's on trial, changing nothing."""

    trying: Trying

    @override
    def request(self) -> type[ListTrial]:
        return ListTrial

    @override
    async def answer(self, request: ListTrial) -> Reply:
        repository = self.trying.repository(request.repository)
        return await asyncio.to_thread(self.trying.said, repository, [])


class TrialPicking(Model, Handler[PickBranches]):
    """Answers `PickBranches`: `dev` plus those branches, run."""

    trying: Trying

    @override
    def request(self) -> type[PickBranches]:
        return PickBranches

    @override
    async def answer(self, request: PickBranches) -> Reply:
        return await self.trying.picked(
            request.repository,
            request.branches,
            seen=request.seen,
            dev=request.dev,
        )


class TrialChanging(Model, Handler[ChangeBranches]):
    """Answers `ChangeBranches`: those branches in what runs, or out, each other as it stands."""

    trying: Trying

    @override
    def request(self) -> type[ChangeBranches]:
        return ChangeBranches

    @override
    async def answer(self, request: ChangeBranches) -> Reply:
        return await self.trying.changed(
            request.repository, request.taking, request.leaving, request.seen
        )


class TrialDropping(Model, Handler[DropBranch]):
    """Answers `DropBranch`: the branch off trial, and what the operator said on it left for who landed it."""

    trying: Trying
    delivery: Delivery

    @override
    def request(self) -> type[DropBranch]:
        return DropBranch

    @override
    async def answer(self, request: DropBranch) -> Reply:
        return await self.trying.dropped(
            request.repository, request.branch, request.words, self.delivery
        )


class TrialAccepting(Model, Handler[AcceptBranch], arbitrary_types_allowed=True):
    """Answers `AcceptBranch`: the branch merged onto `dev`, in a room, and cleaned up after, as a landing is, then `live` computed on what that leaves; one at a time in a repository, and, asked apart, with its answer at once and what it comes to listed."""

    trying: Trying
    tools: AcceptingTools
    changes: Changes | None = None
    """Told a merge that ran apart finished, so what's shown says what came of it."""

    @override
    def request(self) -> type[AcceptBranch]:
        return AcceptBranch

    @override
    async def answer(self, request: AcceptBranch) -> Reply:
        repository = self.trying.repository(request.repository)
        trial = Trials.of(self.trying.layout, repository).read()
        on = trial.on(request.branch)
        if on is None:
            message = f"`{request.branch}` isn't on trial: `lup-dev live` lists what is"
            raise HostError(message)
        if request.tip is not None:
            self.trying.refuse_unseen(trial, {on.branch: request.tip})
        merges = self.trying.merges.of(repository)
        if on.branch in merges.underway:
            message = f"`{on.branch}` is merging already"
            raise HostError(message)
        self.tools.ready(repository, on)
        merges.underway = [*merges.underway, on.branch]
        if request.apart:
            task = asyncio.create_task(self.apart(repository, on))
            merges.tasks = [*(each for each in merges.tasks if not each.done()), task]
            said = [f"`{on.branch}` is merging: what it comes to shows on its line."]
            return await asyncio.to_thread(self.trying.said, repository, said)
        try:
            words = await self.merged(repository, on)
        except LupDevError as refused:
            merges.ended(on.branch, str(refused), landed=False)
            raise
        merges.ended(on.branch, "\n".join(words), landed=self.gone(repository, on))
        return await asyncio.to_thread(self.trying.said, repository, words)

    def gone(self, repository: Path, on: OnTrial) -> bool:
        """Say whether `on` is off trial, which is what its having landed comes to: a merge says what stopped it in words, as the gate failing."""
        return Trials.of(self.trying.layout, repository).read().on(on.branch) is None

    async def merged(self, repository: Path, on: OnTrial) -> list[str]:
        """Merge `on` at its turn, saying what came of it, a line each. It's refused where it landed again while it waited, and there's nothing to do where it's gone from trial."""
        async with self.trying.merges.of(repository).turn:
            trial = Trials.of(self.trying.layout, repository).read()
            if trial.on(on.branch) is None:
                return [f"`{on.branch}` isn't on trial any more."]
            self.trying.refuse_unseen(trial, {on.branch: on.tip})
            landed = await self.tools.accepted(repository, on)
            moved = await self.trying.moved_dev(repository, on.remote)
            return [landed, *moved]

    async def apart(self, repository: Path, on: OnTrial) -> None:
        """Merge `on` with nobody waiting on the answer, keeping what it comes to for whatever lists what's on trial, and telling whoever watches."""
        try:
            said = "\n".join(await self.merged(repository, on))
        except LupDevError as refused:
            said = str(refused)
        except Exception as failed:
            self.trying.say(traceback.format_exc())
            said = f"it failed, as the host service's log says: {failed}"
        merges = self.trying.merges.of(repository)
        merges.ended(on.branch, said, landed=self.gone(repository, on))
        if self.changes is not None:
            self.changes.changed([TrialMoved(repository=repository)])
