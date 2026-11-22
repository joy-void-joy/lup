"""`Landings`: the machine's part keeping each project's landings and what's on trial, computing what runs, and accepting a branch onto the integration branch.

A landing is a branch an agent says is done: it holds the integration branch's
tip and the gate passed on its files. It waits on the operator's review; their
yes puts it on trial, and the project runs `live`, the integration branch with
each branch on trial they picked merged in, at the tip they reviewed. Once
they've lived with it, they accept it onto the integration branch, which this
part pushes as they would. It's the machine's own, since only the machine's
parts read the repository's store hash-checked, record an approval and restart
a project's containers (`README.md` here).
"""

import asyncio
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import TypeAdapter

import lup
from lup.code_rules import Defer, changed_deferrals
from lup.declaration.layout import local_layer
from lup.doors.door import RefusedError
from lup.doors.parties import Agent, Codebase, Operator
from lup.doors.parts import Data, Part, Program
from lup.gate.checking import Run, keyed, last, passed
from lup.gate.findings import Finding
from lup.gate.layout import GateLayout
from lup.hosting.approvals import Approvals, Approving, Asking
from lup.hosting.projects import Opening, Projects
from lup.hosting.trees import Commit
from lup.inbox.part import Inboxes
from lup.inbox.records import Item, Laid
from lup.inbox.said import FrictionSaid, Posting, Settling, Spoken
from lup.landing.merging import Composed, Unmerged, apart
from lup.programs.git import Entry, Git, Store
from lup.remote import remotes
from lup.remote.remotes import (
    Fetching,
    Lease,
    Listing,
    Remotes,
    Update,
    Updates,
)
from lup.running.plan import Name
from lup.shell.blocks import (
    Blocks,
    Diff,
    FileBytes,
    FileText,
    Fold,
    Line,
    Markdown,
    Offer,
    Span,
    Ticking,
    Viewing,
)
from lup.types import Model

LUP = "lup <lup@localhost>"
"""Who a commit of `live` is by: lup's own, never pushed."""


class LandingAsked(Model):
    """A branch an agent lands: who, which branch, what its merge says, and the integration branch and remote it lands on, as the project's landing module says."""

    agent: Agent
    branch: str
    message: str
    """What the merge onto the integration branch will say: what changed and
    why, how it was tested."""
    integration: str = "dev"
    remote: str = "origin"
    released: str = "main"
    """The branch a release lands on, which only the operator merges into, so
    no branch of that name lands."""


class Wanted(Model):
    """An agent asking the operator to accept a branch on trial, and why."""

    agent: Agent
    why: str


class Deferred(Model):
    """A `# lup: defer` a landing adds, removes or rewords: the work left undone that lands with it, in its file."""

    path: str
    """The file, from the repository's root."""
    how: Literal["adds", "removes", "rewords"]
    defer: Defer
    """The deferral as the branch's tip says it; as the integration branch did,
    where the branch removes it."""

    def said(self) -> str:
        """Say it in a line: what the branch does to it, where, what tracks it, and why.

        >>> Deferred(path="a.py", how="adds", defer=Defer(line=3, column=1, why="later", issue=12)).said()
        'adds a.py:3, #12: later'
        """
        tracked = (
            f"#{self.defer.issue}"
            if isinstance(self.defer.issue, int)
            else self.defer.issue or f"when {self.defer.when}"
        )
        return f"{self.how} {self.path}:{self.defer.line}, {tracked}: {self.defer.why}"


class Landed(Model):
    """A branch landed, as this part keeps it."""

    branch: str
    tip: Commit
    """The commit it landed at, last."""
    onto: Commit
    """The integration branch's tip it holds, as it landed."""
    agent: Agent
    message: str
    at: datetime
    reviewed: Commit | None = None
    """The tip the operator said yes to, which `live` runs; none before."""
    picked: bool = True
    """Whether `live` runs it while it's on trial: the operator's toggle."""
    wanted: list[Wanted] = []
    ended: Literal["accepted", "dropped"] | None = None
    item: int | None = None
    """The number of the item that waits on the operator in the agent's
    conversation for its last landing; none before it's posted."""
    deferrals: list[Deferred] = []
    """The `# lup: defer` comments its tip adds, removes and rewords against
    the integration branch's tip it holds, in its Python files."""
    findings: list[Finding] = []
    """What the gate's steps found without failing on its tip, which its
    landing files as frictions."""
    filed: list[str] = []
    """What came of filing each of `findings` as its landing came, a line
    each: kept with nothing, said to the agent landing it."""

    def waiting(self) -> bool:
        """Say whether it waits on the operator's review: landed at a tip they haven't said yes to."""
        return self.ended is None and self.tip != self.reviewed

    def on_trial(self) -> bool:
        """Say whether it's on trial: said yes to, and neither accepted nor dropped."""
        return self.ended is None and self.reviewed is not None


class Trial(Model):
    """A project's landings, and what it runs.

    Its integration branch, remote and release branch are set by its first
    landing, and a later one naming others is refused: the code asking is the
    project's, whatever runs in its container, so it doesn't move where the
    operator's accept pushes.
    """

    integration: str = "dev"
    remote: str = "origin"
    released: str = "main"
    landings: list[Landed] = []
    accepted: Commit | None = None
    """The integration branch's tip this part last pushed, which the operator
    accepted; none before their first accept."""
    live: Commit | None = None
    """What the project runs: the integration branch with each branch on trial
    picked merged in; none before the first yes."""
    out: list[Unmerged] = []
    """Each branch on trial and picked that `live` leaves out, as it doesn't
    merge with what's before it."""

    def landing(self, branch: str) -> Landed:
        """Return the landing of `branch`, which hasn't ended; raise `RefusedError` where there's none."""
        found = next(
            (
                each
                for each in self.landings
                if each.branch == branch and each.ended is None
            ),
            None,
        )
        if found is None:
            message = f"no landing of {branch} waits or is on trial"
            raise RefusedError(message, about=[branch])
        return found

    def with_landing(self, landed: Landed) -> Trial:
        """Return this trial with `landed` in place of the landing of its branch that hasn't ended, or added."""
        kept = [
            each
            for each in self.landings
            if each.branch != landed.branch or each.ended is not None
        ]
        return self.model_copy(update={"landings": [*kept, landed]})


TRIALS = TypeAdapter(Trial)


class Naming(Model):
    """A landing, by its project and its branch."""

    project: Name
    branch: str


class Reviewing(Model):
    """A landing the operator says yes to, at the tip whose review they read: a tip landed since is another review."""

    project: Name
    branch: str
    tip: Commit


class TrialOf(Model):
    """A project whose landings to show."""

    project: Name


class Wanting(Model):
    """An agent asking for a branch on trial to be accepted, and why."""

    agent: Agent
    branch: str
    why: str


class Live(Model):
    """What a project runs once `live` is computed: its commit, the branches merged into it, and those left out."""

    commit: Commit
    merged: list[str] = []
    out: list[Unmerged] = []


class Landings(Part, machine=True, shared=True):
    """The machine's part keeping each project's landings and what's on trial, computing what it runs, and accepting a branch onto its integration branch."""

    git: Program = Program(
        name="git",
        optional=True,
        why="reads and merges a project's commits, and pushes what the operator accepts",
        install="https://git-scm.com/downloads",
    )
    records: Data
    """Each project's trial, a JSON file each."""
    changing: dict[str, asyncio.Lock] = {}
    """Each project's lock, held while its landings or trial change, so two
    changes never read the same trial and keep it one over the other, and one
    project's wait on git or its remote holds no other's."""

    def lock(self, project: str) -> asyncio.Lock:
        """Return `project`'s lock, made the first time it's asked for."""
        found = self.changing.get(project)
        if found is None:
            found = asyncio.Lock()
            self.changing = {**self.changing, project: found}
        return found

    def kept(self, project: str) -> Trial:
        """Return `project`'s trial, as kept; an empty one before its first landing."""
        file = self.records.path / f"{project}.json"
        return TRIALS.validate_json(file.read_bytes()) if file.exists() else Trial()

    def keep(self, project: str, trial: Trial) -> None:
        """Keep `trial` as `project`'s, written beside its place and moved there whole."""
        file = self.records.path / f"{project}.json"
        writing = file.with_suffix(".writing")
        writing.write_bytes(TRIALS.dump_json(trial))
        writing.replace(file)

    def repository(self, opening: Opening) -> Store:
        """Return the store of the project at `opening`'s repository, git pinned to it, read hash-checked."""
        return Git.pinned(opening.common, through=self.git)

    async def remote_tip(self, project: str, trial: Trial) -> Commit:
        """Return the integration branch's tip on the remote, fetched into the repository's store: the remote's word, never a ref a room writes, read through the project's `remote`, which holds the operator's credentials.

        Raise `RefusedError` where the remote hasn't the branch, or `remote`
        can't reach it.
        """
        ref = f"refs/heads/{trial.integration}"
        with lup.within(project):
            listed = await Remotes.listed(Listing(remote=trial.remote, for_push=True))
        tip = next((each.object for each in listed.refs if each.name == ref), None)
        if tip is None:
            message = f"{trial.remote} has no branch {trial.integration} to land on"
            raise RefusedError(message)
        with lup.within(project):
            await Remotes.fetched(
                Fetching(
                    remote=trial.remote, wanted=[remotes.Wanted(object=tip, name=ref)]
                )
            )
        return tip

    async def pushed(
        self, project: str, remote: str, update: Update, lease: str
    ) -> None:
        """Push `update` through the project's `remote`, as the machine's, leased on the tip `lease` it read, so it's refused where the remote moved since.

        Raise `RefusedError` where it's refused or fails, saying why.
        """
        with lup.within(project):
            pushed = await Remotes.pushed(
                Updates(
                    remote=remote,
                    updates=[update],
                    leases=[Lease(ref=update.destination, expected=lease)],
                )
            )
        failed = [each.error for each in pushed.updates if each.error is not None]
        if failed:
            message = "\n".join([*([pushed.said] if pushed.said else []), *failed])
            raise RefusedError(message)

    @lup.service
    async def lands(self, landing: LandingAsked, by: Codebase) -> Landed:
        """Land an agent's branch for the operator's review: its tip holds the integration branch's tip on the remote, and the gate passed on its files.

        Landing a branch again, as after the operator's comment, puts its new
        tip before them. Raise `RefusedError` where the project isn't
        registered, the branch isn't there, the integration branch moved since
        it was merged into it, or the gate didn't pass on its files, each
        saying what to do.
        """
        project = by.repository
        async with self.lock(project):
            opening = await Projects.registered(Asking(project=project))
            git = self.repository(opening)
            if landing.branch in [landing.integration, landing.released]:
                message = (
                    f"{landing.branch} is the integration branch or the release "
                    "branch, which only the operator moves: land a branch of your own"
                )
                raise RefusedError(message)
            kept = self.kept(project)
            asked = [landing.integration, landing.remote, landing.released]
            if kept.landings and asked != [
                kept.integration,
                kept.remote,
                kept.released,
            ]:
                message = (
                    f"{project} lands on {kept.integration} at {kept.remote}, "
                    f"{kept.released} its release branch: a landing naming others "
                    "is refused, as where the operator's accept pushes is theirs"
                )
                raise RefusedError(message)
            tip = await git.branch(landing.branch)
            trial = kept.model_copy(
                update={
                    "integration": landing.integration,
                    "remote": landing.remote,
                    "released": landing.released,
                }
            )
            onto = await self.remote_tip(project, trial)
            if not await git.holds(onto, tip):
                message = (
                    f"{landing.integration} moved since {landing.branch} last held it: "
                    f"merge it in (`git merge {landing.remote}/{landing.integration}`), "
                    "run the gate (`lup gate check`), and land again"
                )
                raise RefusedError(message)
            tree = await git.tree(tip)
            main = opening.common if await git.bare() else opening.common.parent
            local = local_layer(main, opening.declaration)
            run = passed(GateLayout(common=opening.common), keyed(tree, local))
            if run is None:
                message = (
                    f"the gate hasn't passed on {landing.branch}'s files at {tip}: commit "
                    "everything, run `lup gate check` in its worktree, and land again"
                )
                raise RefusedError(message)
            before = next(
                (
                    each
                    for each in trial.landings
                    if each.branch == landing.branch and each.ended is None
                ),
                None,
            )
            landed = Landed(
                branch=landing.branch,
                tip=tip,
                onto=onto,
                agent=landing.agent,
                message=landing.message,
                at=datetime.now(UTC),
                deferrals=await deferred(git, onto, tip),
                findings=[found for step in run.steps for found in step.findings],
                reviewed=None if before is None else before.reviewed,
                picked=True if before is None else before.picked,
                wanted=[] if before is None else before.wanted,
            )
            if before is not None and before.item is not None:
                await self.settled(project, before, f"landed again, at {tip}")
            posted = await Inboxes.post(
                Posting.of(
                    WaitsOnReview,
                    Waited(branch=landing.branch, tip=tip),
                    by=landing.agent,
                    repository=project,
                    text=f"`{landing.branch}` waits on your review.\n\n{landing.message}",
                )
            )
            landed = landed.model_copy(update={"item": posted.number})
            self.keep(project, trial.with_landing(landed))
            filed = [
                await filed_as(project, each, landing.agent) for each in landed.findings
            ]
            return landed.model_copy(update={"filed": filed})

    @lup.service
    async def wants(self, wanting: Wanting, by: Codebase) -> str:
        """Ask the operator to accept a branch on trial, saying why: it shows on the branch's line.

        Raise `RefusedError` where the branch isn't on trial.
        """
        project = by.repository
        async with self.lock(project):
            trial = self.kept(project)
            landed = trial.landing(wanting.branch)
            if not landed.on_trial():
                message = f"{wanting.branch} isn't on trial: it waits on the operator's review"
                raise RefusedError(message, about=[wanting.branch])
            asked = landed.model_copy(
                update={
                    "wanted": [
                        *landed.wanted,
                        Wanted(agent=wanting.agent, why=wanting.why),
                    ]
                }
            )
            self.keep(project, trial.with_landing(asked))
            return f"asked to accept {wanting.branch}"

    @lup.command(verb="done", says="put it on trial")
    async def yes(self, reviewing: Reviewing, by: Operator) -> str:
        """Say yes to a landing's review: the branch goes on trial at the tip whose review you read, and your lup runs it.

        Refused where the branch landed again since, at a tip whose review you
        haven't read.
        """
        del by
        async with self.lock(reviewing.project):
            trial = self.kept(reviewing.project)
            landed = trial.landing(reviewing.branch)
            if landed.tip != reviewing.tip:
                message = (
                    f"{reviewing.branch} landed again since, at {landed.tip}: read "
                    "its review there before saying yes"
                )
                raise RefusedError(message, about=[reviewing.branch])
            trial = trial.with_landing(
                landed.model_copy(update={"reviewed": landed.tip})
            )
            said = await self.ran(
                reviewing.project, trial, f"{reviewing.branch} is on trial"
            )
            await self.settled(reviewing.project, landed, said)
            return said

    @lup.command(verb="toggle", says="run it or not")
    async def toggle(self, naming: Naming, by: Operator) -> str:
        """Take a branch on trial out of what your lup runs, or put it back, and run what's left."""
        del by
        async with self.lock(naming.project):
            trial = self.kept(naming.project)
            landed = trial.landing(naming.branch)
            picked = not landed.picked
            trial = trial.with_landing(landed.model_copy(update={"picked": picked}))
            said = "runs again" if picked else "is taken out of what runs"
            return await self.ran(naming.project, trial, f"{naming.branch} {said}")

    @lup.command(verb="decline", says="take it off trial")
    async def drop(self, naming: Naming, by: Operator) -> str:
        """Take a branch off trial, or decline a landing waiting on you: nothing of it runs, and it's left as it is."""
        del by
        async with self.lock(naming.project):
            trial = self.kept(naming.project)
            landed = trial.landing(naming.branch)
            trial = trial.with_landing(landed.model_copy(update={"ended": "dropped"}))
            said = await self.ran(
                naming.project, trial, f"{naming.branch} is off trial"
            )
            await self.settled(naming.project, landed, said)
            return said

    @lup.command(verb="accept", says="accept it onto the integration branch")
    async def accept(self, naming: Naming, by: Operator) -> str:
        """Accept a branch on trial onto the integration branch, at the tip you reviewed: merge it, push it as you would, and delete the branch on the remote where it's there at that tip.

        Refused where it landed again since your yes, at a tip whose review
        you haven't said yes to; where the integration branch doesn't hold
        what its review was read against; where it doesn't merge onto the
        integration branch as it stands, naming the files; or where the push
        fails. Where the integration branch holds it already, nothing is
        pushed.
        """
        del by
        async with self.lock(naming.project):
            trial = self.kept(naming.project)
            landed = trial.landing(naming.branch)
            reviewed = landed.reviewed
            if reviewed is None:
                message = f"{naming.branch} waits on your review: say yes to it first"
                raise RefusedError(message, about=[naming.branch])
            if landed.tip != reviewed:
                message = (
                    f"{naming.branch} landed again since your yes, at {landed.tip}: "
                    "say yes to its review there first, or take it off trial"
                )
                raise RefusedError(message, about=[naming.branch])
            opening = await Projects.registered(Asking(project=naming.project))
            git = self.repository(opening)
            dev = await self.remote_tip(naming.project, trial)
            if not await git.holds(landed.onto, dev):
                message = (
                    f"{trial.integration} doesn't hold {landed.onto}, which "
                    f"{naming.branch}'s review was read against: its agent merges "
                    f"{trial.integration} in and lands it again"
                )
                raise RefusedError(message, about=[naming.branch])
            merge = (
                dev
                if await git.holds(reviewed, dev)
                else await self.merged(opening, trial, landed, dev)
            )
            if merge != dev:
                await self.pushed(
                    naming.project,
                    trial.remote,
                    Update(source=merge, destination=f"refs/heads/{trial.integration}"),
                    dev,
                )
            trial = trial.with_landing(
                landed.model_copy(update={"ended": "accepted"})
            ).model_copy(update={"accepted": merge})
            self.keep(naming.project, trial)
            cleaned = await self.cleaned(naming.project, git, trial, landed, merge)
            said = await self.ran(
                naming.project,
                trial,
                f"{naming.branch} is accepted onto {trial.integration} as {merge}{cleaned}",
            )
            await self.settled(naming.project, landed, said)
            return said

    async def settled(self, project: str, landed: Landed, said: str) -> None:
        """Tell the agent who landed `landed` what came of it, in `said`, answering its item so it waits no more; nothing where it has none."""
        if landed.item is not None:
            await Inboxes.settle(
                Settling(repository=project, item=landed.item, text=said)
            )

    async def merged(
        self, opening: Opening, trial: Trial, landed: Landed, dev: Commit
    ) -> Commit:
        """Return the merge of `landed`'s reviewed tip onto `dev`, by the operator, with its message, in the repository's store; raise `RefusedError` where it doesn't merge."""
        reviewed = landed.reviewed or landed.tip
        async with apart(self.git, opening.common) as store:
            composed = await store.merged(dev, {landed.branch: reviewed})
            match composed:
                case Unmerged(files=files, why=why):
                    named = ", ".join(str(each) for each in files)
                    message = (
                        f"{landed.branch} doesn't merge onto {trial.integration} as it "
                        f"stands, {named or why}: its agent merges {trial.integration} "
                        "in and lands it again"
                    )
                    raise RefusedError(message, about=[landed.branch])
                case Composed(merged=[]):
                    return dev
                case Composed(tree=tree):
                    kept = await store.kept(tree)
                    return await store.committed(
                        kept,
                        [dev, reviewed],
                        await self.who(),
                        landed.message,
                        datetime.now(UTC),
                    )

    async def cleaned(
        self, project: str, git: Store, trial: Trial, landed: Landed, merge: Commit
    ) -> str:
        """Move the repository's tracking ref of the integration branch to `merge`, as `git push` would, and delete `landed`'s branch on the remote through the project's `remote` where it's there at its reviewed tip, leased on it; say what of it failed, the accept standing."""
        said: list[str] = []
        try:
            await git.moved(f"refs/remotes/{trial.remote}/{trial.integration}", merge)
        except RefusedError as unmoved:
            said = [*said, f"; the tracking ref stays where it was: {unmoved}"]
        branch = f"refs/heads/{landed.branch}"
        try:
            with lup.within(project):
                listed = await Remotes.listed(
                    Listing(remote=trial.remote, for_push=True)
                )
            there = next(
                (each.object for each in listed.refs if each.name == branch), None
            )
            if there is not None and there == landed.reviewed:
                await self.pushed(
                    project,
                    trial.remote,
                    Update(source=None, destination=branch),
                    there,
                )
        except RefusedError as kept:
            said = [*said, f"; {landed.branch} stays on {trial.remote}: {kept}"]
        return "".join(said)

    async def who(self) -> str:
        """Return who a merge the operator accepts is by: their own name and address, as their git is configured, else lup's."""
        name = await self.git.ran("config", "--global", "--get", "user.name")
        email = await self.git.ran("config", "--global", "--get", "user.email")
        if name.status != 0 or email.status != 0:
            return LUP
        return f"{name.text().strip()} <{email.text().strip()}>"

    async def ran(self, project: str, trial: Trial, said: str) -> str:
        """Keep `trial`, compute what `project` runs from it, approve that where it's made of what the operator accepted and reviewed alone, open the project at it, and say what came of it after `said`.

        `trial` is kept first, so a change stands where what runs can't be
        computed, the remote unreachable say, which is said.
        """
        self.keep(project, trial)
        opening = await Projects.registered(Asking(project=project))
        git = self.repository(opening)
        try:
            base = await self.remote_tip(project, trial)
            live = await self.live(opening, trial, base)
        except RefusedError as uncomputed:
            return f"{said}. What runs stays as it was: {uncomputed}"
        trial = trial.model_copy(update={"live": live.commit, "out": live.out})
        self.keep(project, trial)
        approved = await Approvals.approval(Asking(project=project))
        accepted = base == trial.accepted or (
            approved.commit is not None and await git.holds(base, approved.commit)
        )
        out = "".join(
            f"; {each.branch} is left out of what runs, as it "
            + (
                f"conflicts in {', '.join(str(path) for path in each.files)}"
                if each.files
                else each.why
            )
            for each in live.out
        )
        if not accepted:
            return (
                f"{said}{out}. {trial.integration} moved to {base} without your "
                "review, so lup asks you before running it: nothing restarted"
            )
        if approved.commit != live.commit:
            await Approvals.landed(Approving(project=project, commit=live.commit))
        try:
            await Projects.opened(opening)
        except RefusedError as unopened:
            return (
                f"{said}{out}. {project} runs {live.commit} once it opens: {unopened}"
            )
        return f"{said}{out}. {project} runs {live.commit}"

    async def live(self, opening: Opening, trial: Trial, base: Commit) -> Live:
        """Return what the project at `opening` runs from `trial`: the integration branch's tip, `base`, with each branch on trial and picked merged in, by name, at the tip the operator reviewed, each that doesn't merge with what's before it left out."""
        git = self.repository(opening)
        trying = [
            each
            for each in trial.landings
            if each.on_trial() and each.picked and each.reviewed is not None
        ]
        held = [await git.holds(each.onto, base) for each in trying]
        tips = {
            each.branch: each.reviewed
            for each, holds in zip(trying, held, strict=True)
            if holds and each.reviewed is not None
        }
        unheld = [
            Unmerged(
                branch=each.branch,
                why=(
                    f"its review was read against {each.onto}, which "
                    f"{trial.integration} doesn't hold: its agent lands it again"
                ),
            )
            for each, holds in zip(trying, held, strict=True)
            if not holds
        ]
        async with apart(self.git, opening.common) as store:

            async def composed(tips: dict[str, str], out: list[Unmerged]) -> Live:
                found = await store.merged(base, tips)
                match found:
                    case Unmerged(branch=branch):
                        left = {
                            name: tip for name, tip in tips.items() if name != branch
                        }
                        return await composed(left, [*out, found])
                    case Composed(merged=[]):
                        return Live(commit=base, out=out)
                    case Composed(tree=tree, merged=merged):
                        kept = await store.kept(tree)
                        commit = await store.committed(
                            kept,
                            [base, *(tips[name] for name in merged)],
                            LUP,
                            f"live: {trial.integration} with {', '.join(merged)}",
                            datetime.now(UTC),
                        )
                        return Live(commit=commit, merged=merged, out=out)

            return await composed(tips, unheld)

    @lup.view
    async def trial(self, of: TrialOf, by: Operator) -> Blocks:
        """Show a project's landings: each waiting on your review or on trial, with who landed it, since when, who wants it accepted, and its review under it."""
        del by
        trial = self.kept(of.project)
        out = [each.branch for each in trial.out]
        approved = await Approvals.approval(Asking(project=of.project))
        running = (
            f"{of.project} runs {approved.commit}"
            if approved.commit is not None
            else f"nothing of {of.project} is approved to run yet"
        )
        waiting = (
            f"; {trial.live} waits on your approval, as {trial.integration} moved "
            "without your review"
            if trial.live is not None and trial.live != approved.commit
            else ""
        )
        return Blocks.of(
            Line.of("live", f"{running}{waiting}"),
            *(
                landing_fold(of.project, each, left_out=each.branch in out)
                for each in trial.landings
                if each.ended is None
            ),
        )

    @lup.view
    async def review(self, naming: Naming, by: Operator) -> Blocks:
        """Show a landing's change: how the gate went on its tip, what a step that tells said, then each file its tip changes since the integration branch's tip it holds, read from each object's own bytes."""
        del by
        trial = self.kept(naming.project)
        landed = trial.landing(naming.branch)
        opening = await Projects.registered(Asking(project=naming.project))
        git = self.repository(opening)
        main = opening.common if await git.bare() else opening.common.parent
        local = local_layer(main, opening.declaration)
        run = last(
            GateLayout(common=opening.common),
            keyed(await git.tree(landed.tip), local),
        )
        before = {str(each.path): each for each in await git.held(landed.onto)}
        after = {str(each.path): each for each in await git.held(landed.tip)}
        changed = sorted(
            path
            for path in before.keys() | after.keys()
            if before.get(path) != after.get(path)
        )

        async def side(entry: Entry | None) -> FileText | FileBytes | None:
            if entry is None or entry.kind != "blob":
                return None
            [content] = await git.verified("blob", [entry.object])
            try:
                return FileText(text=content.decode())
            except UnicodeDecodeError:
                return FileBytes(size=len(content))

        return Blocks.of(
            *gate_lines(run),
            *deferral_lines(landed.deferrals),
            *[
                Diff(
                    id=path,
                    path=path,
                    before=await side(before.get(path)),
                    after=await side(after.get(path)),
                )
                for path in changed
            ],
        )


async def filed_as(project: str, finding: Finding, by: Agent) -> str:
    """File what the gate found on a landing's tip as a friction of the agent landing it, in `project`, under `frictions/` and the finding's subject, and say what came of it in a line; where it can't be filed, why, the landing standing."""
    said = FrictionSaid(
        text=finding.text,
        title=finding.title,
        under=f"frictions/{finding.about}",
        repository=project,
    )
    try:
        await Inboxes.friction(Spoken(agent=by, said=said))
    except RefusedError as unfiled:
        return f"What the gate found, {finding.title}, isn't filed: {unfiled}"
    return (
        f"What the gate found is filed under frictions/{finding.about}: {finding.title}"
    )


async def deferred(git: Store, onto: Commit, tip: Commit) -> list[Deferred]:
    """Return the `# lup: defer` comments `tip` adds, removes and rewords against `onto`, in each Python file it changes, read from each object's own bytes; a deferral moved to another line is neither."""
    before = {str(each.path): each for each in await git.held(onto)}
    after = {str(each.path): each for each in await git.held(tip)}
    changed = [
        path
        for path in sorted(before.keys() | after.keys())
        if PurePosixPath(path).suffix == ".py" and before.get(path) != after.get(path)
    ]

    async def text(entry: Entry | None) -> str | None:
        if entry is None or entry.kind != "blob":
            return None
        [content] = await git.verified("blob", [entry.object])
        return content.decode(errors="replace")

    async def of(path: str) -> list[Deferred]:
        deferrals = changed_deferrals(
            await text(before.get(path)), await text(after.get(path))
        )
        return [
            *(Deferred(path=path, how="adds", defer=each) for each in deferrals.added),
            *(
                Deferred(path=path, how="removes", defer=each)
                for each in deferrals.removed
            ),
            *(
                Deferred(path=path, how="rewords", defer=each.after)
                for each in deferrals.reworded
            ),
        ]

    per = [await of(path) for path in changed]
    return [each for found in per for each in found]


def deferral_lines(deferrals: list[Deferred]) -> list[Line]:
    """Return the work left undone a landing adds, removes and rewords, a line each, or that it touches none."""
    if not deferrals:
        return [Line.of("deferrals", "It adds and removes no `# lup: defer`.", "muted")]
    return [
        Line.of("deferrals", "The `# lup: defer` comments it changes:", "strong"),
        *(
            Line.of(f"deferral-{index}", each.said())
            for index, each in enumerate(deferrals)
        ),
    ]


def gate_lines(run: Run | None) -> list[Line | Markdown]:
    """Return how the gate went on a landing's tip, a line each step, what a step that failed or tells said under it, indented as code; or that it never ran there."""
    if run is None:
        return [Line.of("gate", "The gate hasn't run on these files.", "muted")]
    outcome = "passed" if run.passed else "failed"
    return [
        Line.of("gate", f"The gate {outcome} on these files.", "strong"),
        *(
            Line.of(
                f"gate-found-{index}",
                f"found, about {each.about}: {each.title}. {each.text}",
            )
            for index, each in enumerate(
                found for step in run.steps for found in step.findings
            )
        ),
        *(
            block
            for each in run.steps
            for block in [
                Line.of(
                    f"gate-{each.name}",
                    f"{'passed' if each.passed else 'failed'}  {each.name}  "
                    f"{each.seconds:.1f} s",
                ),
                *(
                    [
                        Markdown(
                            id=f"gate-{each.name}-said",
                            text="".join(
                                f"    {line}\n" for line in each.said.splitlines()
                            ),
                            tone="muted",
                        )
                    ]
                    if each.said
                    else []
                ),
            ]
        ),
    ]


class Waited(Model):
    """What a landing's item says of it beyond its words: the branch, and the tip that landed."""

    branch: str
    tip: Commit


class WaitsOnReview(Item):
    """A branch that waits on the operator's review, as the agent who landed it says in their conversation: opening on its review, and offering the operator's yes on the tip that landed, or declining it."""

    kind: str = "landing:waits-on-review"
    branch: str
    tip: Commit

    def waits(self) -> bool:
        """Say it waits on the operator, until what came of it answers it."""
        return True

    def laid(self) -> Laid:
        """Return its review under a fold of the landing kind, offering a yes to the tip that landed, and declining it."""
        naming = Naming(project=self.repository, branch=self.branch)
        reviewing = Reviewing(project=self.repository, branch=self.branch, tip=self.tip)
        return Laid(
            fold="landing",
            summary=f"{self.branch} at {self.tip}",
            opens=Viewing.of(Landings.review, naming, module="landing"),
            offers=[
                Offer.of(Landings.yes, reviewing, module="landing"),
                Offer.of(Landings.drop, naming, module="landing"),
            ],
        )


def landing_fold(project: str, landed: Landed, *, left_out: bool) -> Fold:
    """Return a landing's fold in a project's trial: its branch, how it stands, who landed it and since when, who wants it accepted, and its review under it, offering what can be done with it."""
    naming = Naming(project=project, branch=landed.branch)
    reviewing = Reviewing(project=project, branch=landed.branch, tip=landed.tip)
    stands = (
        "waits on your review"
        if landed.waiting()
        else "doesn't merge, left out"
        if left_out
        else "on trial"
        if landed.picked
        else "on trial, not running"
    )
    wanted = [
        Span(text=f"  wanted by {each.agent.id}: {each.why}", tone="muted")
        for each in landed.wanted
    ]
    offers = (
        [Offer.of(Landings.yes, reviewing), Offer.of(Landings.drop, naming)]
        if landed.waiting() and landed.reviewed is None
        else [
            *([Offer.of(Landings.yes, reviewing)] if landed.waiting() else []),
            Offer.of(Landings.toggle, naming),
            Offer.of(Landings.accept, naming),
            Offer.of(Landings.drop, naming),
        ]
    )
    return Fold(
        id=f"landing-{landed.branch}",
        kind="landing",
        summary=[
            Span(text=landed.branch, tone="strong"),
            Span(text=f"  {stands}  "),
            Span(text=landed.agent.id, tone="muted"),
            Span(text="  ", ticking=Ticking(since=landed.at, said="{} ago")),
            *wanted,
        ],
        content=Viewing.of(Landings.review, naming),
        offers=offers,
        standing="waiting" if landed.waiting() else None,
    )
