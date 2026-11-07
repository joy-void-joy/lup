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
    Fold,
    FoldKind,
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
from lup_dev.declaration.kinds import Folds, Serving, Tones, Verbs
from lup_dev.declaration.module import Module
from lup_dev.declaration.serving import ModuleServing, Operator
from lup_dev.host.on_trial import (
    AcceptBranch,
    BranchListed,
    ChangeBranches,
    CopySwitching,
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

MERGE = Verb(name="merge", key="m", called="merge")
"""Space `m`: merge a branch or a version onto the integration branch. Its own verb,
since on a box and a version done means yes, take it in, as decline means no: what
each key means is held in the actions and `branch_offers`, so changing one is a line."""

OUT = FoldKind(
    name="versions-out",
    letter="O",
    called="what's folded out of the way",
    one="what's folded out of the way",
    level=1,
    colour="muted",
)
"""What's under a line: the branches left out of what runs, and the whole of what a
merge said where that's more than its line holds."""

TICKED = Tone(name="versions-ticked", colour="ok")
"""What runs: a branch's box ticked, a version's star."""

KEPT_OUT = Tone(name="versions-kept-out", colour="warn")
"""What keeps a branch out, or what the operator should know before a key."""

ASKS = "needs your yes, then minutes to build"
"""What running a set takes that's run before with no copy kept: a build runs its
code on this machine (`docs/trust.md`, *What it asks, and what it builds*)."""

NEVER_RUN = "never run: likely your yes, then minutes to build"
"""What running a set takes that's never run, which only the merge of it would say
for sure, since its host zone may be one a copy holds."""


class WhatRuns(Model):
    """What's viewed: what runs of the repository whose process answers, which is all it takes to say."""


class PickedBranch(Model):
    """One branch's box as a mark sets it: in what runs, or out of it, and the tip it was shown at, where a key marked it."""

    branch: str = Field(description="The branch on trial.")
    on: bool = Field(
        default=True, description="Whether it runs; --no-on leaves it out."
    )
    tip: str | None = Field(
        default=None, description="The tip it was seen at: landed since, it's left."
    )


class Merging(Model):
    """The branches a mark merges onto the integration branch, with the tip each was shown at, where a key marked it."""

    branches: list[str] = Field(description="The branches on trial to merge.")
    tips: list[str] = Field(
        default=[],
        description="The tip each was seen at, in their order: one landed since is left.",
    )


class RunningAgain(Model):
    """A version a mark runs again: the copy kept of it; and, where it's on the integration branch as it stands, each branch at the tip it's on trial at, what picking it comes to, `live` with them."""

    commit: str = Field(description="The commit of the copy kept of it.")
    current: bool = Field(
        default=False,
        description="Pick it as it stands, rather than move to the copy alone.",
    )
    branches: list[str] = Field(default=[], description="The branches it holds.")
    tips: list[str] = Field(
        default=[], description="The tip of each it was seen at, in their order."
    )
    dev: str | None = Field(
        default=None, description="The commit of the integration branch it was seen on."
    )


class Standing(Model):
    """Where a branch stands, in words and the tone they're drawn in."""

    said: str
    tone: str


class Lander(Model):
    """Who landed a branch, as the operator's words on it find them: their name, and whether they're at work to read them."""

    name: str
    at_work: bool


class MergeAsked(Model):
    """What came of asking the host to merge one branch: what it said, or why it refused."""

    said: str = ""
    refused: str = ""


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
    """Say what running exactly the branches `names` on the integration branch as it stands takes, from what ran before: nothing where that's what runs; seconds where a copy of it is kept; else the operator's yes and a build, where it's run before; likely that, where it never has."""
    tips = {each.branch: each.tip for each in listed.branches if each.branch in names}
    found = [
        each for each in listed.versions if each.dev == listed.dev and each.tips == tips
    ]
    if any(each.running for each in found):
        return "restarts nothing"
    if any(each.copy_kept is not None for each in found):
        return "moves the host in seconds"
    return ASKS if found else NEVER_RUN


def lander_of(party: Conversation | None, launches: Listed) -> Lander:
    """Return who landed a branch: by their path where the host still has them, and whether they're at work, a comment reaching them rather than waiting for their session."""
    if party is None:
        return Lander(name="", at_work=False)
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


def printable(said: str) -> str:
    r"""Return what a room may have written, a name in a conflict or a gate's words, kept to what's printable, on one line.

    >>> printable("a\x1b[31mb\nc")
    'a[31mb c'
    """
    return "".join(each for each in " ".join(said.splitlines()) if each.isprintable())


def lines_of(said: str) -> list[str]:
    """Return the lines of what a room may have written, each printable, none blank."""
    return [printable(each) for each in said.splitlines() if each.strip()]


def standing_of(listed: TrialListed, branch: BranchListed) -> Standing:
    """Say where `branch` stands: merging; in what runs; kept out by what it conflicts with; or out, and what running it would take."""
    if branch.merging:
        return Standing(
            said="merging: its gate runs in a session's room", tone=TICKED.name
        )
    if branch.within:
        return Standing(said="on trial", tone="muted")
    if branch.conflict:
        return Standing(
            said=printable(branch.conflict).removeprefix("it "), tone=KEPT_OUT.name
        )
    out = "out, by you" if branch.out else "not in yet"
    cost = takes(listed, [*within(listed), branch.branch])
    return Standing(said=f"{out} · {cost}", tone="muted")


def coming_in(listed: TrialListed, name: str) -> list[str]:
    """Return what comes in with the branch `name` left out: each it alone keeps out, as its host's words name it, which nobody took out."""
    return [
        each.branch
        for each in listed.branches
        if not each.out and not each.within and f"`{name}`" in each.conflict
    ]


def take_said(listed: TrialListed, branch: BranchListed) -> str:
    """Say what Space `d` does on a box not ticked, and what that would take, as the line of keys says it before it's pressed."""
    if branch.conflict:
        return "take it in: refused while what it conflicts with stays in"
    return f"take it in: {takes(listed, [*within(listed), branch.branch])}"


def leave_said(listed: TrialListed, branch: BranchListed) -> str:
    """Say what Space `x` does on a box, and what that would take: on one ticked, what's left, and what that lets in; on one out by a conflict alone, that it stops coming back by itself."""
    if not branch.within:
        return "leave it out: it stops coming back by itself"
    others = [each for each in within(listed) if each != branch.branch]
    coming = coming_in(listed, branch.branch)
    let_in = f", and {', '.join(coming)} comes in" if coming else ""
    return f"leave it out{let_in}: {takes(listed, [*others, *coming])}"


def merge_said(seeing: Seeing) -> str:
    """Say what Space `m` does on a branch, and where no session runs that it's refused until one does."""
    merging = f"merge it onto {seeing.listed.integration}"
    if seeing.rooms:
        return merging
    return f"{merging}: refused until a session of this repository runs, whose room it merges in"


def branch_offers(seeing: Seeing, branch: BranchListed) -> list[Offer]:
    """Return what a branch offers: yes on a box not ticked, no on one that's ticked, or one out by a conflict alone, which is still trying to come back; and merging it. A box already out marks nothing with no, and one merging offers nothing."""
    if branch.merging:
        return []
    listed = seeing.listed
    tick = PickedBranch(branch=branch.branch, on=True, tip=branch.tip)
    untick = PickedBranch(branch=branch.branch, on=False, tip=branch.tip)
    take = Offer.of(
        VersionsServing.pick, tick, says=take_said(listed, branch), draws="[x]"
    )
    leave = Offer.of(
        VersionsServing.pick,
        untick,
        verb="decline",
        says=leave_said(listed, branch),
        draws="[ ]",
    )
    merge = Offer.of(
        VersionsServing.merge,
        Merging(branches=[branch.branch], tips=[branch.tip]),
        says=merge_said(seeing),
    )
    if branch.within:
        return [leave, merge]
    return [take, merge] if branch.out else [take, leave, merge]


def branch_line(seeing: Seeing, branch: BranchListed, width: int) -> Line:
    """Return a branch's line: its box, what it is and where it stands, what its last merge said, who a comment on it reaches, and what can be done with it."""
    standing = standing_of(seeing.listed, branch)
    lander = lander_of(branch.party, seeing.launches)
    party = branch.party
    failed = lines_of(branch.merge_said)
    return Line(
        id=f"branch {branch.branch}",
        version=branch.tip,
        by=None
        if party is None
        else OfAgent(runtime=party.runtime, session=party.session, agent=party.agent),
        offers=branch_offers(seeing, branch),
        spans=[
            Span(
                text=f"[{'x' if branch.within else ' '}] ",
                tone=TICKED.name if branch.within else "muted",
            ),
            Span(text=branch.branch.ljust(width), tone="strong"),
            Span(text=f"  {standing.said}", tone=standing.tone),
            *([Span(text=f" · {failed[0]}", tone=KEPT_OUT.name)] if failed else []),
            Span(text=f" · {branch.subject}" if branch.subject else ""),
            Span(
                text=" · who landed it isn't known: a comment has nobody to reach"
                if party is None
                else ""
                if lander.at_work
                else f" · {lander.name} has ended: a comment waits for their session",
                tone="muted",
            ),
        ],
    )


def branch_part(seeing: Seeing, branch: BranchListed, width: int) -> list[Block]:
    """Return what shows of a branch: its line, and, where what its last merge said is longer than that holds, the whole of it, folded."""
    said = lines_of(branch.merge_said)
    line = branch_line(seeing, branch, width)
    if len(said) < 2:
        return [line]
    whole = Fold(
        id=f"said {branch.branch}",
        kind=OUT.name,
        summary=[Span(text="    what the merge said, whole", tone="muted")],
        content=[
            Line.of(f"said {branch.branch} {at}", each) for at, each in enumerate(said)
        ],
    )
    return [line, whole]


def is_current(listed: TrialListed, version: VersionListed) -> bool:
    """Say whether `version` is on the integration branch as it stands, each branch at the tip it's on trial at: picking its branches comes to what it holds."""
    return version.dev == listed.dev and holds_as_on_trial(listed, version)


def holds_as_on_trial(listed: TrialListed, version: VersionListed) -> bool:
    """Say whether each branch of `version` is on trial at the tip it holds, and not merging: all merging it asks."""
    tips = {each.branch: each for each in listed.branches}
    return all(
        (on := tips.get(name)) is not None and on.tip == tip and not on.merging
        for name, tip in version.tips.items()
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


def version_line(listed: TrialListed, version: VersionListed, width: int) -> Line:
    """Return a version's line: whether it runs, what it holds, how it stands, and what can be done with it: yes runs it again, where a copy of it is kept, and merge, where each of its branches still stands as it holds them."""
    named = sorted(version.tips)
    tips = [version.tips[each] for each in named]
    offers = [
        *(
            [
                Offer.of(
                    VersionsServing.run_again,
                    RunningAgain(
                        commit=version.copy_kept,
                        current=is_current(listed, version),
                        branches=named,
                        tips=tips,
                        dev=version.dev,
                    ),
                    says="run this version again: moves the host in seconds",
                    draws=" *  ",
                )
            ]
            if version.copy_kept is not None and not version.running
            else []
        ),
        *(
            [
                Offer.of(
                    VersionsServing.merge,
                    Merging(branches=named, tips=tips),
                    says=f"merge it: each of its branches onto {listed.integration}",
                )
            ]
            if named and holds_as_on_trial(listed, version)
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


def merged_part(listed: TrialListed) -> list[Block]:
    """Return what the last merges that landed said, each its first line: its branch is off trial, with no line of its own to say it."""
    return [
        Line.of(f"merged {at}", first, "muted")
        for at, each in enumerate(listed.merged)
        if (first := next(iter(lines_of(each)), None)) is not None
    ]


def shown_above(branch: BranchListed) -> bool:
    """Say whether `branch` shows among those on trial rather than folded under `out`: all but what the operator left out, unless it's merging, or a merge of it failed, which they'd not otherwise see."""
    return not branch.out or branch.merging or bool(branch.merge_said)


def out_part(seeing: Seeing, width: int) -> list[Block]:
    """Return the branches the operator left out, under one line, closed: their boxes still take them back in, and comments reach who landed them."""
    out = [each for each in seeing.listed.branches if not shown_above(each)]
    if not out:
        return []
    return [
        Fold(
            id="out",
            kind=OUT.name,
            summary=[Span(text=f"out · {len(out)}", tone="muted")],
            content=[
                block for each in out for block in branch_part(seeing, each, width)
            ],
        )
    ]


def laid_out(seeing: Seeing) -> Blocks:
    """Return what runs as blocks: what it is on the summary line; why the last switch fell back, where it did; each branch on trial, those left out folded; what the last merges said; what running a set and merging take; each version."""
    listed = seeing.listed
    width = max((len(each.branch) for each in listed.branches), default=0)
    shown = [each for each in listed.branches if shown_above(each)]
    branches = [block for each in shown for block in branch_part(seeing, each, width)]
    empty = f"Nothing is on trial: {listed.integration} runs."
    no_room = (
        "Merging runs the gate in a session's room, and no session of this repository "
        "is running: start one first."
    )
    return Blocks(
        summary=[Span(text=f"what runs · {said_now(listed)}")],
        tally=Tally(
            flagged=sum(1 for each in listed.branches if each.conflict and not each.out)
        ),
        blocks=[
            *fell_back(listed),
            *(
                branches
                or (
                    []
                    if listed.branches
                    else [Line.of("nothing on trial", empty, "muted")]
                )
            ),
            *out_part(seeing, width),
            *merged_part(listed),
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

    @action(verb="done", says="take it in", runs="last")
    async def pick(self, picked: list[PickedBranch]) -> str:
        """Take a branch on trial into what runs, or leave it out: every box of a send makes one change, and one restart at most, each other branch staying as it is."""
        asked = ChangeBranches(
            taking=[each.branch for each in picked if each.on],
            leaving=[each.branch for each in picked if not each.on],
            seen={each.branch: each.tip for each in picked if each.tip is not None},
            repository=self.repository,
        )
        return (await self.host.asked(asked, TrialSaid)).said

    @action(verb=MERGE.name, says="merge it onto the integration branch")
    async def merge(self, merging: Merging) -> str:
        """Merge branches on trial onto the integration branch, at the tips they landed with, and clean up after each, as a landing does: each apart, its line saying what it comes to. A branch off trial since, or merging already, asks nothing more, so sending what was refused again asks only what's left."""
        listed = await self.on_trial()
        on_trial = {each.branch: each for each in listed.branches}
        seen = dict(zip(merging.branches, merging.tips, strict=False))
        came = [
            await self.merging(name, on_trial.get(name), seen.get(name))
            for name in merging.branches
        ]
        said = [each.said for each in came if each.said]
        refused = [each.refused for each in came if each.refused]
        if refused:
            raise ActionRefusedError("\n".join([*refused, *said]))
        return "\n".join(said)

    async def merging(
        self, name: str, found: BranchListed | None, seen: str | None
    ) -> MergeAsked:
        """Ask the host to merge the branch `name`, as it stands (`found`), seen at the tip `seen`, apart from the answer; say what came of asking."""
        if found is None:
            return MergeAsked(said=f"`{name}` isn't on trial any more.")
        if found.merging:
            return MergeAsked(said=f"`{name}` is merging already.")
        asked = AcceptBranch(
            branch=name, repository=self.repository, tip=seen, apart=True
        )
        try:
            return MergeAsked(said=(await self.host.asked(asked, TrialSaid)).said)
        except HostError as failed:
            return MergeAsked(refused=str(failed))

    @action(verb="done", says="run this version again", runs="last")
    async def run_again(self, going: RunningAgain) -> str:
        """Run a version again: picked, where it's on the integration branch as it stands, so the running branch holds it too; else the host moved to its copy alone, the running branch staying as it is. Where it has moved since it was marked, nothing runs, and it says so."""
        listed = await self.on_trial()
        if any(each.merging for each in listed.branches):
            merging = [each.branch for each in listed.branches if each.merging]
            message = (
                f"{', '.join(merging)} is merging, whose gate runs in a session's "
                "room, and moving the host now would stop it: ask this again once it's done"
            )
            raise ActionRefusedError(message)
        if not going.current:
            moving = await self.host.asked(
                SwitchCopy(commit=going.commit), CopySwitching
            )
            return f"The host moves to {moving.commit}, in a few seconds."
        seen = dict(zip(going.branches, going.tips, strict=False))
        tips = {each.branch: each.tip for each in listed.branches}
        if going.dev != listed.dev or any(
            tips.get(name) != tip for name, tip in seen.items()
        ):
            return "That version moved since you marked it, so nothing ran: look at it again."
        asked = PickBranches(
            branches=going.branches,
            repository=self.repository,
            seen=seen,
            dev=going.dev,
        )
        return (await self.host.asked(asked, TrialSaid)).said


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
    verbs: Verbs = Verbs.of(MERGE)
    folds: Folds = Folds.of(OUT)
