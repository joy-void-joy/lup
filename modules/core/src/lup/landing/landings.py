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
from typing import Literal

from pydantic import Field, TypeAdapter

import lup
from lup.declaration.layout import local_layer
from lup.doors.door import RefusedError
from lup.doors.parties import Agent, Codebase, Operator
from lup.doors.parts import Data, Part, Program
from lup.gate.checking import Run, keyed, last, passed
from lup.gate.layout import GateLayout
from lup.hosting.approvals import Approvals, Approving, Asking
from lup.hosting.git import Git
from lup.hosting.projects import Opening, Projects
from lup.hosting.trees import Commit, Entry, Objects
from lup.landing.merging import Composed, Unmerged, apart
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


class Wanted(Model):
    """An agent asking the operator to accept a branch on trial, and why."""

    agent: Agent
    why: str


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

    def waiting(self) -> bool:
        """Say whether it waits on the operator's review: landed at a tip they haven't said yes to."""
        return self.ended is None and self.tip != self.reviewed

    def on_trial(self) -> bool:
        """Say whether it's on trial: said yes to, and neither accepted nor dropped."""
        return self.ended is None and self.reviewed is not None


class Trial(Model):
    """A project's landings, and what it runs."""

    integration: str = "dev"
    remote: str = "origin"
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
    changing: asyncio.Lock = Field(default_factory=asyncio.Lock, exclude=True)
    """Held while a landing or a trial changes, so two changes never read the
    same trial and keep it one over the other."""

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

    def repository(self, opening: Opening) -> Git:
        """Return git on the project at `opening`'s repository."""
        return Git(program=self.git, common=opening.common)

    async def remote_tip(self, git: Git, trial: Trial) -> Commit:
        """Return the integration branch's tip on the remote, fetched into the repository's store: the remote's word, never a ref a room writes.

        Raise `RefusedError` where the remote hasn't the branch.
        """
        url = await git.url(trial.remote)
        ref = f"refs/heads/{trial.integration}"
        tip = await git.remote_tip(url, ref)
        if tip is None:
            message = f"{trial.remote} has no branch {trial.integration} to land on"
            raise RefusedError(message)
        await git.fetched(url, ref)
        return tip

    @lup.service
    async def lands(self, landing: LandingAsked, by: Codebase) -> Landed:
        """Land an agent's branch for the operator's review: its tip holds the integration branch's tip on the remote, and the gate passed on its files.

        Landing a branch again, as after the operator's comment, puts its new
        tip before them. Raise `RefusedError` where the project isn't
        registered, the branch isn't there, the integration branch moved since
        it was merged into it, or the gate didn't pass on its files, each
        saying what to do.
        """
        async with self.changing:
            project = by.repository
            opening = await Projects.registered(Asking(project=project))
            git = self.repository(opening)
            if landing.branch == landing.integration:
                message = (
                    f"{landing.branch} is the integration branch, which only the "
                    "operator's accept moves: land a branch of your own"
                )
                raise RefusedError(message)
            tip = await git.branch(landing.branch)
            trial = self.kept(project).model_copy(
                update={"integration": landing.integration, "remote": landing.remote}
            )
            onto = await self.remote_tip(git, trial)
            if not await git.holds(onto, tip):
                message = (
                    f"{landing.integration} moved since {landing.branch} last held it: "
                    f"merge it in (`git merge {landing.remote}/{landing.integration}`), "
                    "run the gate (`lup gate check`), and land again"
                )
                raise RefusedError(message)
            tree = await Objects(git=self.git, common=opening.common).tree(tip)
            main = opening.common if await git.bare() else opening.common.parent
            local = local_layer(main, opening.declaration)
            if passed(GateLayout(common=opening.common), keyed(tree, local)) is None:
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
                reviewed=None if before is None else before.reviewed,
                picked=True if before is None else before.picked,
                wanted=[] if before is None else before.wanted,
            )
            # lup: defer(issue=8, why="the landing's item waiting on the operator in the agent's conversation, once the inbox takes a module's item")
            self.keep(project, trial.with_landing(landed))
            return landed

    @lup.service
    async def wants(self, wanting: Wanting, by: Codebase) -> str:
        """Ask the operator to accept a branch on trial, saying why: it shows on the branch's line.

        Raise `RefusedError` where the branch isn't on trial.
        """
        async with self.changing:
            project = by.repository
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
    async def yes(self, naming: Naming, by: Operator) -> str:
        """Say yes to a landing's review: the branch goes on trial at the tip you reviewed, and your lup runs it."""
        del by
        async with self.changing:
            trial = self.kept(naming.project)
            landed = trial.landing(naming.branch)
            trial = trial.with_landing(
                landed.model_copy(update={"reviewed": landed.tip})
            )
            return await self.ran(naming.project, trial, f"{naming.branch} is on trial")

    @lup.command(verb="toggle", says="run it or not")
    async def toggle(self, naming: Naming, by: Operator) -> str:
        """Take a branch on trial out of what your lup runs, or put it back, and run what's left."""
        del by
        async with self.changing:
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
        async with self.changing:
            trial = self.kept(naming.project)
            landed = trial.landing(naming.branch)
            trial = trial.with_landing(landed.model_copy(update={"ended": "dropped"}))
            return await self.ran(
                naming.project, trial, f"{naming.branch} is off trial"
            )

    @lup.command(verb="accept", says="accept it onto the integration branch")
    async def accept(self, naming: Naming, by: Operator) -> str:
        """Accept a branch on trial onto the integration branch, at the tip you reviewed: merge it, push it as you would, and delete the branch on the remote where it's there at that tip.

        Refused where it doesn't merge onto the integration branch as it
        stands, naming the files, or the push fails.
        """
        del by
        async with self.changing:
            trial = self.kept(naming.project)
            landed = trial.landing(naming.branch)
            reviewed = landed.reviewed
            if reviewed is None:
                message = f"{naming.branch} waits on your review: say yes to it first"
                raise RefusedError(message, about=[naming.branch])
            opening = await Projects.registered(Asking(project=naming.project))
            git = self.repository(opening)
            dev = await self.remote_tip(git, trial)
            async with apart(self.git, opening.common) as store:
                composed = await store.merged(dev, {naming.branch: reviewed})
                match composed:
                    case Unmerged(files=files):
                        message = (
                            f"{naming.branch} doesn't merge onto {trial.integration} as it "
                            f"stands, in {', '.join(str(each) for each in files) or 'its history'}: "
                            f"its agent merges {trial.integration} in and lands it again"
                        )
                        raise RefusedError(message, about=[naming.branch])
                    case Composed(tree=tree):
                        kept = await store.kept(tree)
                        merge = await store.committed(
                            kept,
                            [dev, reviewed],
                            await self.who(),
                            landed.message,
                            datetime.now(UTC),
                        )
            url = await git.url(trial.remote)
            await git.pushed(url, merge, f"refs/heads/{trial.integration}", dev)
            await git.moved(f"refs/remotes/{trial.remote}/{trial.integration}", merge)
            branch = f"refs/heads/{naming.branch}"
            if await git.remote_tip(url, branch) == reviewed:
                await git.pushed(url, "", branch, reviewed)
            trial = trial.with_landing(landed.model_copy(update={"ended": "accepted"}))
            trial = trial.model_copy(update={"accepted": merge})
            return await self.ran(
                naming.project,
                trial,
                f"{naming.branch} is accepted onto {trial.integration} as {merge}",
            )

    async def who(self) -> str:
        """Return who a merge the operator accepts is by: their own name and address, as their git is configured, else lup's."""
        name = await self.git.ran("config", "--global", "--get", "user.name")
        email = await self.git.ran("config", "--global", "--get", "user.email")
        if name.status != 0 or email.status != 0:
            return LUP
        return f"{name.text().strip()} <{email.text().strip()}>"

    async def ran(self, project: str, trial: Trial, said: str) -> str:
        """Compute what `project` runs from `trial`, approve it where it's made of what the operator accepted and reviewed alone, open the project at it, keep `trial`, and say what came of it after `said`."""
        opening = await Projects.registered(Asking(project=project))
        git = self.repository(opening)
        base = await self.remote_tip(git, trial)
        live = await self.live(opening, trial, base)
        trial = trial.model_copy(update={"live": live.commit, "out": live.out})
        self.keep(project, trial)
        approved = await Approvals.approval(Asking(project=project))
        accepted = base == trial.accepted or (
            approved.commit is not None and await git.holds(base, approved.commit)
        )
        out = "".join(
            f"; {each.branch} doesn't merge with what's before it, so it's left out"
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
        tips = {
            each.branch: each.reviewed
            for each in trial.landings
            if each.on_trial() and each.picked and each.reviewed is not None
        }
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

            return await composed(tips, [])

    @lup.view
    async def trial(self, of: TrialOf) -> Blocks:
        """Show a project's landings: each waiting on your review or on trial, with who landed it, since when, who wants it accepted, and its review under it."""
        trial = self.kept(of.project)
        out = [each.branch for each in trial.out]
        return Blocks.of(
            Line.of(
                "live",
                f"{of.project} runs "
                + (
                    trial.live
                    if trial.live is not None
                    else f"{trial.integration}'s tip"
                ),
            ),
            *(
                landing_fold(of.project, each, left_out=each.branch in out)
                for each in trial.landings
                if each.ended is None
            ),
        )

    @lup.view
    async def review(self, naming: Naming) -> Blocks:
        """Show a landing's change: how the gate went on its tip, what a step that tells said, then each file its tip changes since the integration branch's tip it holds, read from each object's own bytes."""
        trial = self.kept(naming.project)
        landed = trial.landing(naming.branch)
        opening = await Projects.registered(Asking(project=naming.project))
        objects = Objects(git=self.git, common=opening.common)
        git = self.repository(opening)
        main = opening.common if await git.bare() else opening.common.parent
        local = local_layer(main, opening.declaration)
        run = last(
            GateLayout(common=opening.common),
            keyed(await objects.tree(landed.tip), local),
        )
        before = {str(each.path): each for each in await objects.held(landed.onto)}
        after = {str(each.path): each for each in await objects.held(landed.tip)}
        changed = sorted(
            path
            for path in before.keys() | after.keys()
            if before.get(path) != after.get(path)
        )

        async def side(entry: Entry | None) -> FileText | FileBytes | None:
            if entry is None or entry.kind != "blob":
                return None
            [content] = await objects.verified("blob", [entry.object])
            try:
                return FileText(text=content.decode())
            except UnicodeDecodeError:
                return FileBytes(size=len(content))

        return Blocks.of(
            *gate_lines(run),
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


def gate_lines(run: Run | None) -> list[Line | Markdown]:
    """Return how the gate went on a landing's tip, a line each step, what a step that failed or tells said under it, indented as code; or that it never ran there."""
    if run is None:
        return [Line.of("gate", "The gate hasn't run on these files.", "muted")]
    outcome = "passed" if run.passed else "failed"
    return [
        Line.of("gate", f"The gate {outcome} on these files.", "strong"),
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


def landing_fold(project: str, landed: Landed, *, left_out: bool) -> Fold:
    """Return a landing's fold in a project's trial: its branch, how it stands, who landed it and since when, who wants it accepted, and its review under it, offering what can be done with it."""
    naming = Naming(project=project, branch=landed.branch)
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
        [Offer.of(Landings.yes, naming), Offer.of(Landings.drop, naming)]
        if landed.waiting() and landed.reviewed is None
        else [
            *([Offer.of(Landings.yes, naming)] if landed.waiting() else []),
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
