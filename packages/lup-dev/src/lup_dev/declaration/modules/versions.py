"""`Versions`: the optional module that runs another branch than the one work is integrated on, and what the operator sees and does of that in the review.

`docs/trust.md`, *What the host runs while it's on trial*; `docs/dashboard.md`, *What
runs*. What's on trial and what runs are the host service's, which no room reaches,
so what's here asks it as the operator does (`ModuleServing.host`): `what_runs` lays
out what it answers, each branch and each version offering what can be done with it,
and each action is the host's own request. The page draws the blocks and keeps no
rule of its own: which branches a pick holds, what it would take, and who a comment
on a branch reaches are all said here.
"""

from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import Field

from lup.blocks import (
    Block,
    Blocks,
    Drawer,
    Line,
    OfAgent,
    Offer,
    Span,
    Tally,
    Ticking,
    Tone,
    Verb,
    Watch,
)
from lup.doors import ActionRefusedError, action, view
from lup.types import Model
from lup_dev.declaration.kinds import Serving, Tones, Verbs
from lup_dev.declaration.module import Module
from lup_dev.declaration.serving import ModuleServing, Operator
from lup_dev.host.on_trial import (
    AcceptBranch,
    BranchListed,
    CopySwitching,
    DropBranch,
    ListTrial,
    PickBranches,
    SwitchCopy,
    TrialListed,
    TrialSaid,
    VersionListed,
)
from lup_dev.host.protocol import BranchName, HostError, Listed, ListLaunches

if TYPE_CHECKING:
    from lup_ledger.parties import Conversation

RUN = Verb(name="run", key="r", called="run")
"""Space `r`: run a branch beside what runs, stop running it, or run a version
again. Its own verb rather than `done`, since a mark of `done` strikes its line
through, and a branch about to run isn't going anywhere."""

TICKED = Tone(name="versions-ticked", colour="ok")
"""What runs: a branch's box ticked, a version's star."""

KEPT_OUT = Tone(name="versions-kept-out", colour="warn")
"""What keeps a branch out, or what the operator should know before a key."""

ASKS = "needs your yes, then minutes to build"
"""What running a set takes that the operator hasn't said yes to: a build runs its
code on this machine (`docs/trust.md`, *What it asks, and what it builds*)."""


class WhatRuns(Model):
    """What's viewed: what runs of the repository whose process answers, which is all it takes to say."""


class PickedBranch(Model):
    """One branch's box as a mark sets it: in what runs, or out of it."""

    branch: str = Field(description="The branch on trial.")
    on: bool = Field(default=True, description="Whether it runs; --no-on takes it out.")


class Merging(Model):
    """The branches a mark merges onto the integration branch, with the tip each was shown at, where a key marked it."""

    branches: list[str] = Field(description="The branches on trial to merge.")
    tips: list[str] = Field(
        default=[],
        description="The tip each was seen at, in their order: one landed since is left.",
    )


class Dropping(Model):
    """The branch a mark takes off trial, and the tip it was shown at, where a key marked it."""

    branch: str = Field(description="The branch to take off trial.")
    tip: str | None = Field(
        default=None, description="The tip it was seen at: landed since, it's left."
    )


class RunningAgain(Model):
    """A version a mark runs again: the copy kept of it; and, where it's on the integration branch as it stands, each branch at the tip it's on trial at, the branches picking it brings back, `live` with them."""

    commit: str = Field(description="The commit of the copy kept of it.")
    current: bool = Field(
        default=False,
        description="Pick it as it stands, rather than move to the copy alone.",
    )
    branches: list[str] = Field(default=[], description="The branches it holds.")


class Standing(Model):
    """Where a branch stands, in words and the tone they're drawn in."""

    said: str
    tone: str


class Lander(Model):
    """Who landed a branch, as the operator's words on it find them: their name, and whether they're at work to read them."""

    name: str
    at_work: bool


class Seeing(Model):
    """What the view reads: what's on trial, who's running, and whether any of them is of this repository, whose room a merge runs in."""

    listed: TrialListed
    launches: Listed
    rooms: bool


def short(commit: str) -> str:
    """Say a commit as git abbreviates one.

    >>> short("d38dbd2c0ffee")
    'd38dbd2'
    """
    # lup: ignore("string-slice", why="a commit's id is hex of a fixed width, with no layout to read: its first seven are git's own abbreviation, and asking git for each would run a program at each answer")
    return commit[:7]


def set_said(listed: TrialListed, dev: str | None, tips: list[str]) -> str:
    """Say what a version holds: the integration branch at its commit, and each branch in it.

    >>> trial = TrialListed(integration="dev", running="live")
    >>> set_said(trial, "d38dbd2c0ffee", ["b", "a"])
    'dev d38dbd2 + a b'
    >>> set_said(trial, None, [])
    'dev'
    """
    head = listed.integration if dev is None else f"{listed.integration} {short(dev)}"
    return " ".join([head, "+", *sorted(tips)]) if tips else head


def within(listed: TrialListed) -> list[str]:
    """Return the branches in what runs, by their names."""
    return [each.branch for each in listed.branches if each.within]


def takes(listed: TrialListed, names: list[str]) -> str:
    """Say what running exactly the branches `names` on the integration branch as it stands takes, from what ran before: nothing where that's what runs; seconds where a copy of it is kept; else the operator's yes and a build."""
    tips = {each.branch: each.tip for each in listed.branches if each.branch in names}
    found = [
        each for each in listed.versions if each.dev == listed.dev and each.tips == tips
    ]
    if any(each.running for each in found):
        return "restarts nothing"
    if any(each.copy_kept is not None for each in found):
        return "moves the host in seconds"
    return ASKS


def lander_of(party: Conversation | None, launches: Listed) -> Lander:
    """Return who landed a branch: by their path where the host still has them, and whether they're at work, a comment reaching them rather than waiting for their session."""
    if party is None:
        return Lander(name="nobody known", at_work=False)
    talkers = [each for said in launches.talkers.values() for each in said]
    found = next(
        (
            each
            for each in talkers
            if each.session == party.session and each.agent == party.agent
        ),
        None,
    )
    if found is None:
        return Lander(name=party.agent or party.session, at_work=False)
    ended = found.activity is not None and found.activity.state == "ended"
    return Lander(name=found.path, at_work=not ended)


def standing_of(listed: TrialListed, branch: BranchListed) -> Standing:
    """Say where `branch` stands: in what runs; kept out by what it conflicts with; or out, and what running it would take."""
    if branch.within:
        return Standing(said="on trial", tone="muted")
    if branch.conflict:
        return Standing(said=branch.conflict.removeprefix("it "), tone=KEPT_OUT.name)
    out = "out, by you" if branch.out else "not in yet"
    cost = takes(listed, [*within(listed), branch.branch])
    return Standing(said=f"{out} · {cost}", tone="muted")


def run_said(listed: TrialListed, branch: BranchListed) -> str:
    """Say what Space `r` does on `branch`, and what that would take, as the line of keys says it before it's pressed."""
    others = [each for each in within(listed) if each != branch.branch]
    if branch.within:
        return f"take it out: {takes(listed, others)}"
    if branch.conflict:
        return "put it in: refused while what it conflicts with stays in"
    return f"put it in: {takes(listed, [*others, branch.branch])}"


def merge_said(seeing: Seeing) -> str:
    """Say what Space `d` does on a branch, and where no session runs that it's refused until one does."""
    merging = f"merge it onto {seeing.listed.integration}"
    if seeing.rooms:
        return merging
    return f"{merging}: refused until a session of this repository runs, whose room it merges in"


def drop_said(listed: TrialListed, branch: BranchListed) -> str:
    """Say what Space `x` does on `branch`, and what that takes where it's in what runs."""
    dropping = "drop it, leaving its branch"
    if not branch.within:
        return dropping
    others = [each for each in within(listed) if each != branch.branch]
    return f"{dropping}: {takes(listed, others)}"


def branch_line(seeing: Seeing, branch: BranchListed, width: int) -> Line:
    """Return a branch's line: its box, what it is and where it stands, who a comment on it reaches, and what can be done with it."""
    listed = seeing.listed
    standing = standing_of(listed, branch)
    lander = lander_of(branch.party, seeing.launches)
    party = branch.party
    return Line(
        id=f"branch {branch.branch}",
        version=branch.tip,
        by=None
        if party is None
        else OfAgent(runtime=party.runtime, session=party.session, agent=party.agent),
        offers=[
            Offer.of(
                VersionsServing.pick,
                PickedBranch(branch=branch.branch, on=not branch.within),
                says=run_said(listed, branch),
            ),
            Offer.of(
                VersionsServing.merge,
                Merging(branches=[branch.branch], tips=[branch.tip]),
                says=merge_said(seeing),
            ),
            Offer.of(
                VersionsServing.drop,
                Dropping(branch=branch.branch, tip=branch.tip),
                says=drop_said(listed, branch),
            ),
        ],
        spans=[
            Span(
                text=f"[{'x' if branch.within else ' '}] ",
                tone=TICKED.name if branch.within else "muted",
            ),
            Span(text=branch.branch.ljust(width), tone="strong"),
            Span(text=f"  {standing.said}", tone=standing.tone),
            Span(text=f" · {branch.subject}" if branch.subject else ""),
            Span(
                text=""
                if lander.at_work
                else f" · {lander.name} has ended: a comment waits for their session",
                tone="muted",
            ),
        ],
    )


def version_status(version: VersionListed) -> Span:
    """Say how a version stands: running, and for how long; ran, and how long ago; kept and never run; or with no copy, what running it would take. What ticks the page says again as the time passes."""
    if version.running:
        return Span(
            text="running",
            tone=TICKED.name,
            ticking=Ticking(
                since=version.ran or version.at,
                said="running {}",
                first="just started",
            ),
        )
    if version.copy_kept is None:
        return Span(text=f"no copy kept · {ASKS}", tone="muted")
    if version.ran is None:
        return Span(text="built, never run", tone="muted")
    return Span(
        text="ran",
        tone="muted",
        ticking=Ticking(since=version.ran, said="ran {} ago", first="ran just now"),
    )


def is_current(listed: TrialListed, version: VersionListed) -> bool:
    """Say whether `version` is on the integration branch as it stands, each branch at the tip it's on trial at: picking its branches comes to what it holds."""
    tips = {each.branch: each.tip for each in listed.branches}
    return version.dev == listed.dev and all(
        tips.get(name) == tip for name, tip in version.tips.items()
    )


def version_line(listed: TrialListed, version: VersionListed, width: int) -> Line:
    """Return a version's line: whether it runs, what it holds, how it stands, and what can be done with it."""
    named = sorted(version.tips)
    offers = [
        *(
            [
                Offer.of(
                    VersionsServing.run_again,
                    RunningAgain(
                        commit=version.copy_kept,
                        current=is_current(listed, version),
                        branches=named,
                    ),
                    says="run this version again: moves the host in seconds",
                )
            ]
            if version.copy_kept is not None and not version.running
            else []
        ),
        *(
            [
                Offer.of(
                    VersionsServing.merge,
                    Merging(
                        branches=named, tips=[version.tips[each] for each in named]
                    ),
                    says=f"merge it: each of its branches onto {listed.integration}",
                )
            ]
            if named
            else []
        ),
    ]
    return Line(
        id=f"version {version.commit}",
        version=version.commit,
        offers=offers,
        spans=[
            Span(text=" *  " if version.running else "    ", tone=TICKED.name),
            Span(text=set_said(listed, version.dev, named).ljust(width + 2)),
            version_status(version),
        ],
    )


def said_now(listed: TrialListed) -> str:
    """Say what runs, for the summary line: the version the host runs, or what's approved where none says; and the version picked that waits on the operator's yes, where there's one."""
    running = next((each for each in listed.versions if each.running), None)
    latest = next(
        (each for each in listed.versions if each.commit == listed.live), None
    )
    now = (
        set_said(listed, listed.runs, [])
        if running is None
        else set_said(listed, None, sorted(running.tips))
    )
    if latest is None or latest is running:
        return now
    picked = set_said(listed, None, sorted(latest.tips))
    if latest.copy_kept is None:
        return f"{now} · {picked} waits on your yes"
    return f"{now} · {listed.running} holds {picked}"


def distinct(versions: list[VersionListed]) -> list[VersionListed]:
    """Return one of `versions` for each thing they hold, the integration branch at a commit and its branches at their tips, the latest first: each pick of a set makes a commit of `live`, and to the operator it's the one version, running where any of its commits is, with what a copy of any says.

    >>> from datetime import datetime
    >>> at = datetime(2026, 11, 7)
    >>> ran = VersionListed(commit="a", dev="d", at=at, copy_kept="a", ran=at)
    >>> again = VersionListed(commit="b", dev="d", at=at, running=True)
    >>> [(each.commit, each.copy_kept, each.running) for each in distinct([ran, again])]
    [('b', 'a', True)]
    """

    def holding(version: VersionListed) -> str:
        tips = sorted(version.tips.items())
        return "\n".join([version.dev, *(f"{name} {tip}" for name, tip in tips)])

    def one(same: list[VersionListed]) -> VersionListed:
        [latest, *_] = same
        return latest.model_copy(
            update={
                "running": any(each.running for each in same),
                "copy_kept": next(
                    filter(None, (each.copy_kept for each in same)), None
                ),
                "ran": next(filter(None, (each.ran for each in same)), None),
            }
        )

    newest = list(reversed(versions))
    return [
        one([each for each in newest if holding(each) == held])
        for held in dict.fromkeys(holding(each) for each in newest)
    ]


def versions_part(listed: TrialListed) -> list[Block]:
    """Return what lists each version, the latest first: nothing where none ran."""
    versions = distinct(listed.versions)
    if not versions:
        return []
    width = max(len(set_said(listed, each.dev, sorted(each.tips))) for each in versions)
    return [
        Line.of("gap versions", ""),
        Line.of("versions", "versions", "strong"),
        *(version_line(listed, each, width) for each in versions),
    ]


def fell_back(listed: TrialListed) -> list[Block]:
    """Return what says the last switch fell back, where it did: `live` names what was picked, and the copy before runs."""
    last = listed.last
    if last is None or last.answered:
        return []
    said = f"The last switch, to {short(last.commit)}, didn't answer: {last.said}"
    return [Line.of("fell back", said, KEPT_OUT.name)]


def laid_out(seeing: Seeing) -> Blocks:
    """Return what runs as blocks: what it is on the summary line; why the last switch fell back, where it did; each branch on trial; what running a set and merging take; each version."""
    listed = seeing.listed
    width = max((len(each.branch) for each in listed.branches), default=0)
    branches: list[Block] = [
        branch_line(seeing, each, width) for each in listed.branches
    ]
    empty = f"Nothing is on trial: {listed.integration} runs."
    no_room = (
        "Merging runs the gate in a session's room, and no session of this repository "
        "is running: start one first."
    )
    return Blocks(
        summary=[Span(text=f"what runs · {said_now(listed)}")],
        tally=Tally(flagged=sum(1 for each in listed.branches if each.conflict)),
        blocks=[
            *fell_back(listed),
            *(branches or [Line.of("nothing on trial", empty, "muted")]),
            Line.of("gap on trial", ""),
            Line.of(
                "takes",
                (
                    "Ctrl+Enter runs what's marked: a set you've run moves the host in "
                    f"seconds, restarting it; one you haven't {ASKS}."
                ),
                "muted",
            ),
            *(
                []
                if seeing.rooms or not listed.branches
                else [Line.of("no session", no_room, KEPT_OUT.name)]
            ),
            *versions_part(listed),
        ],
    )


class VersionsServing(ModuleServing):
    """What runs, in the review: what it is, and what the operator's keys do with each branch and version."""

    module: Versions

    async def on_trial(self) -> TrialListed:
        """Return what's on trial, as the host lists it.

        Raise `HostError` where it can't say, or `ActionRefusedError` where it's nothing to list.
        """
        said = await self.host.asked(ListTrial(repository=self.repository), TrialSaid)
        if said.listed is None:
            message = f"{self.repository} computes no running branch"
            raise ActionRefusedError(message)
        return said.listed

    @view(
        place=Drawer(under="repository", letter="V", called="what runs", colour="cyan"),
        watch=Watch(longest=timedelta(seconds=15)),
    )
    async def what_runs(self, viewed: WhatRuns, by: Operator) -> Blocks:
        """Say what runs: each branch on trial, what each would take to run, and each version that ran."""
        del viewed, by
        try:
            listed = await self.on_trial()
            launches = await self.host.asked(ListLaunches(), Listed)
        except (HostError, ActionRefusedError) as unread:
            said = f"What's on trial can't be read: {unread}"
            return Blocks(
                summary=[Span(text="what runs · can't be read")],
                blocks=[Line.of("unread", said, KEPT_OUT.name)],
            )
        rooms = any(each.repository == self.repository for each in launches.launches)
        return laid_out(Seeing(listed=listed, launches=launches, rooms=rooms))

    @action(verb=RUN.name, says="run it, or stop running it")
    async def pick(self, picked: list[PickedBranch]) -> str:
        """Run a branch on trial beside what runs, or stop running it: every box of a send makes one pick, and one restart at most."""
        listed = await self.on_trial()
        kept = [
            each
            for each in within(listed)
            if all(one.branch != each or one.on for one in picked)
        ]
        running = [each.branch for each in picked if each.on]
        asked = PickBranches(
            branches=sorted(dict.fromkeys([*kept, *running])),
            repository=self.repository,
        )
        return (await self.host.asked(asked, TrialSaid)).said

    @action(verb="done", says="merge it onto the integration branch")
    async def merge(self, merging: Merging) -> str:
        """Merge branches on trial onto the integration branch, at the tips they landed with, and clean up after each, as a landing does."""
        listed = await self.on_trial()
        tips = {each.branch: each.tip for each in listed.branches}
        moved = [
            each
            for each, seen in zip(merging.branches, merging.tips, strict=False)
            if tips.get(each, seen) != seen
        ]
        if moved:
            message = (
                f"{', '.join(moved)} landed again since you marked it: look at it again"
            )
            raise ActionRefusedError(message)
        answers = [
            await self.host.asked(
                AcceptBranch(branch=each, repository=self.repository), TrialSaid
            )
            for each in merging.branches
        ]
        return "\n".join(each.said for each in answers if each.said)

    @action(verb="decline", says="drop it, leaving its branch")
    async def drop(self, dropping: Dropping) -> str:
        """Take a branch off trial, leaving it and its worktree: landing it again puts it back."""
        listed = await self.on_trial()
        tips = {each.branch: each.tip for each in listed.branches}
        seen = dropping.tip
        if seen is not None and tips.get(dropping.branch, seen) != seen:
            message = (
                f"{dropping.branch} landed again since you marked it: look at it again"
            )
            raise ActionRefusedError(message)
        asked = DropBranch(branch=dropping.branch, repository=self.repository)
        return (await self.host.asked(asked, TrialSaid)).said

    @action(verb=RUN.name, says="run this version again")
    async def run_again(self, going: RunningAgain) -> str:
        """Run a version again: picked, where it's on the integration branch as it stands, so the running branch holds it too; else the host moved to its copy alone, the running branch staying as it is."""
        if going.current:
            asked = PickBranches(branches=going.branches, repository=self.repository)
            return (await self.host.asked(asked, TrialSaid)).said
        moving = await self.host.asked(SwitchCopy(commit=going.commit), CopySwitching)
        return f"The host moves to {moving.commit}, in a few seconds."


class Versions(Module):
    """Running another branch than the integration branch, so what lands can be tried on the operator's machine before it's accepted."""

    name = "versions"

    running: BranchName | None = None
    """The branch the host runs, trust reads and `land` lands on; none for the
    integration branch (`Core.integration`). Where it's another, the host computes
    it, from the integration branch and what's on trial (`docs/trust.md`, *What the
    host runs while it's on trial*). It's read from the declaration approved, so a
    change to it takes effect once approved (`docs/trust.md`, *Which branch*), and
    it's gated (`Credentials.gated`), so `delete-merged` never deletes it. Naming
    one doesn't make it: until the first landing or pick, trust reads the
    integration branch's tip."""

    serving: Serving = Serving.of(VersionsServing)
    tones: Tones = Tones.of(TICKED, KEPT_OUT)
    verbs: Verbs = Verbs.of(RUN)
