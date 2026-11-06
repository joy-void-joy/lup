"""The operator's side of what's on trial: picking what `live` holds, accepting and dropping a branch, and what follows `dev` moving.

`docs/trust.md`, *What the host runs while it's on trial*. A branch goes on trial by
landing (`Lander.on_trial`), in a room; the rest of what moves `live` comes from no
room, so it's here, in the host service: the operator asks through their terminal
or the plain page, on the control socket, which no room reaches.

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
from collections.abc import Callable
from pathlib import Path
from typing import override

from lup.types import Model
from lup_dev.approval import approved, approved_branches
from lup_dev.clock import Clock
from lup_dev.composing import Composed, Unmerged, apart
from lup_dev.copies import Copies
from lup_dev.errors import LupDevError
from lup_dev.git import Git
from lup_dev.host.protocol import Branches, HostError, Reply
from lup_dev.host.service import Handler
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.store import cited
from lup_dev.layout import CopyLayout, Layout
from lup_dev.policy.landing import LandingTools, Turns
from lup_dev.snapshots import Snapshots
from lup_dev.switching import (
    CopySwitching,
    TrialSaid,
    host_copies,
    last_switch,
    needs_ledger,
    own_repository,
)
from lup_dev.trial import (
    AcceptBranch,
    DropBranch,
    ListTrial,
    OnTrial,
    Origin,
    PickBranches,
    Plan,
    Trial,
    TrialListed,
    Trials,
    accepted,
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

    def computed(
        self, git: Git, trial: Trial, branches: Branches, dev: str
    ) -> Computed:
        """Compute `live` from `trial` on the commit `dev`, each branch `dev` holds off trial, and make its next commit, no ref naming it yet."""
        now = accepted(git, dev, trial)
        with apart(git) as store:
            found = plan(store, dev, branches.integration, now)
            commit = next_commit(
                store, now, dev, branches.integration, found, at=self.clock.now()
            )
        return Computed(trial=now, plan=found, dev=dev, commit=commit)

    def kept(
        self, repository: Path, git: Git, computed: Computed, remote: str
    ) -> list[str]:
        """Keep `computed`, naming its commit where lup's asked and on `remote`, and say what's left undone: `live` still moves where a ref can't, or the network's down, as what's kept is what reads."""
        branches = approved_branches(self.layout, repository)
        commit = computed.commit or computed.trial.live or computed.dev
        stands = moved_on(
            computed.trial, commit, computed.dev, computed.plan, self.clock.now()
        )
        Trials.of(self.layout, repository).write(stands)
        Copies(layout=self.layout.judge(repository)).pin(pins(stands))
        if computed.commit is None:
            return []
        left = move_ref(git, branches, commit)
        said = [] if left is None else [f"{left}."]
        try:
            Origin(git=git, remote=remote).pushed(commit, branches.running_ref)
        except LupDevError as failed:
            said.append(f"`{branches.running}` isn't on `{remote}` yet: {failed}")
        return said

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
        said = self.kept(repository, git, found, remote)
        return [*said, *self.fell_out(found), *self.asked(repository, found)]

    def fell_out(self, computed: Computed) -> list[str]:
        """Say each branch that stopped merging as `live` moved, keeping it out, a line each."""
        return [
            f"`{each.branch}` left `live`: {computed.plan.conflicts[each.branch]}."
            for each in computed.trial.branches
            if each.branch in computed.plan.conflicts
            and each.branch in computed.trial.tips
        ]

    def asked(self, repository: Path, computed: Computed) -> list[str]:
        """Ask the operator about `computed`'s commit, where it runs what isn't approved; say so. It's asked nothing where that's the same."""
        if computed.commit is None:
            return []
        fingerprint = self.fingerprint(repository, computed.commit)
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

    async def picked(self, asked: Path | None, names: list[str]) -> TrialSaid:
        """Run `dev` plus exactly `names`, as the operator asked: at once where it's what's approved, or a copy of it is kept; else asking their yes. Refused where a name isn't on trial or they conflict, or its copy needs the ledger restored, nothing having moved."""
        repository = self.repository(asked)
        async with self.turns.of(repository):
            return await asyncio.to_thread(self.picking, repository, names)

    def picking(self, repository: Path, names: list[str]) -> TrialSaid:
        """Do what `picked` says, off the event loop."""
        branches = approved_branches(self.layout, repository)
        trial = Trials.of(self.layout, repository).read()
        unknown = [each for each in names if trial.on(each) is None]
        if unknown:
            message = f"{named(unknown)} isn't on trial: `lup-dev live` lists what is"
            raise HostError(message)
        git = Git.pinned(repository)
        remote = next((each.remote for each in trial.branches), "origin")
        dev = self.dev_tip(git, branches, trial, remote)
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

    def refuse_conflict(
        self, git: Git, trial: Trial, names: list[str], dev: str, branches: Branches
    ) -> None:
        """Refuse, with `HostError`, branches `names` that can't be picked together, naming what conflicts in what."""
        tips = {
            each.branch: each.tip for each in trial.branches if each.branch in names
        }
        with apart(git) as store:
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
            said = self.kept(repository, git, found, remote)
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
            said = self.kept(repository, git, found, remote)
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
        self.kept(repository, git, found, remote)
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
        """Return what's on trial in `repository`, as a page lists it."""
        kept = Copies(layout=self.layout.judge(repository)).kept()
        return trial_listed(self.layout, repository, [each.commit for each in kept])


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
        return await self.trying.picked(request.repository, request.branches)


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


class TrialAccepting(Model, Handler[AcceptBranch]):
    """Answers `AcceptBranch`: the branch merged onto `dev`, in a room, and cleaned up after, as a landing is, then `live` computed on what that leaves."""

    trying: Trying
    tools: LandingTools

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
        landed = await self.tools.accepted(repository, on)
        moved = await self.trying.moved_dev(repository, on.remote)
        return await asyncio.to_thread(self.trying.said, repository, [landed, *moved])
