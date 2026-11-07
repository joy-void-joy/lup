"""What's on trial in a repository: the branches landed and not yet accepted, and `live`, computed from `dev` and those picked.

`docs/trust.md`, *What the host runs while it's on trial*. `live` is never merged
into. Whenever what's in it changes, `dev` and each branch in it are merged apart
(`lup_dev.composing`) and that's committed as its next commit, its first parent the
one before, so it only moves forward and a branch leaves it by being left out. The
record is the host's alone, in lup's state, which no room mounts (`Layout.trial`),
so a room's writes decide nothing of what runs:
- **each branch is held at the tip it landed with,** never its ref's, which a room
  writes, so a commit added since doesn't run until it's landed, and passed what a
  landing holds;
- **`live`'s tip is read here,** by trust among others (`running_tip`), never from
  its ref, which is moved for whoever reads it there.

Every branch on trial is in `live` where it merges cleanly, the first to land
first, unless the operator took it out (`OnTrial.out`), which a landing again
leaves as it is. One that doesn't merge stays on trial, out of it, saying what
with (`OnTrial.conflict`), and comes back where it merges again. Accepted, a branch
is in `dev`'s history, and leaves the record as it's next read against it (`plan`).

What's kept per version (`Version`) is how a copy built for one stays kept
(`pins`, `Copies.pin`), and how `live`'s history reads as a list of them.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from lup.types import Model
from lup_dev.approval import approved, approved_branches
from lup_dev.composing import Apart, Composed, Unmerged, dedupe
from lup_dev.git import Git, GitError, refs_astray
from lup_dev.host.courier import Conversation as Caller
from lup_dev.host.on_trial import BranchListed, TrialListed, VersionListed
from lup_dev.stored import read_model, write_model
from lup_ledger.parties import Conversation

if TYPE_CHECKING:
    from lup_dev.copies import Kept
    from lup_dev.host.protocol import Branches
    from lup_dev.layout import Layout


class OnTrial(Model):
    """A branch landed and not yet accepted, and what's kept of its landing."""

    branch: str
    tip: str
    """The commit it landed at: what `live` holds of it, whatever its ref says."""
    subject: str = ""
    """The first line of what it says it does, printable alone, since a room wrote
    it: its commit's, to tell it apart by."""
    message: str = ""
    """The merge commit's message its landing gave, which accepting it uses."""
    remote: str = "origin"
    landed: datetime
    out: bool = False
    """The operator took it out, which only they undo: it isn't in `live` though
    it may merge."""
    conflict: str = ""
    """What keeps it out of `live`, said, where it doesn't merge with what's in
    it; empty where it does."""
    launch: str | None = None
    """The launch that landed it, whose room accepting it runs in where that's
    still served."""
    caller: Caller | None = None
    """Who landed it, as that launch's service knew them."""
    party: Conversation | None = None
    """Who landed it, as the inbox knows them: where the operator's words on
    dropping it go."""


class Version(Model):
    """One of `live`'s commits: the commit of `dev` it's on, and each branch in it."""

    commit: str
    dev: str
    tips: dict[str, str] = {}
    at: datetime
    fingerprint: str | None = None
    """The fingerprint of the host zone it holds, where it was read as it was made,
    which says whether it's what's approved, or what a copy of another commit
    holds; none where it wasn't, as a landing's."""


class Trial(Model):
    """A repository's branches on trial, and `live` as lup last computed it."""

    live: str | None = None
    """Its tip; none until the first landing or pick, when it starts from `dev`'s."""
    dev: str | None = None
    """The commit of `dev` that's on."""
    branches: list[OnTrial] = []
    """Each on trial, oldest landing first."""
    versions: list[Version] = []
    """Each commit of `live` whose branches are still on trial, oldest first."""

    def on(self, branch: str) -> OnTrial | None:
        """Return `branch` as it's kept on trial; none where it isn't."""
        return next((each for each in self.branches if each.branch == branch), None)

    @property
    def latest(self) -> Version | None:
        """Return the version `live` is at; none before its first."""
        return next(
            (each for each in reversed(self.versions) if each.commit == self.live),
            None,
        )

    @property
    def tips(self) -> dict[str, str]:
        """Return each branch in `live`, with the commit of it there."""
        latest = self.latest
        return {} if latest is None else latest.tips


class AcceptingTools(ABC):
    """What accepting a branch needs beyond what's on trial: a session's room, for its gate and its worktree's removal."""

    @abstractmethod
    def ready(self, repository: Path, on: OnTrial) -> None:
        """Raise `HostError` where accepting `on` can't start: no session of the repository runs."""

    @abstractmethod
    async def accepted(self, repository: Path, on: OnTrial) -> str:
        """Merge `on` onto the integration branch, at the tip it landed with, cleaning up after it, and say what came of it, which needn't be that it landed: a failed gate is said, not raised. Raise `HostError` where it can't be tried."""


class Trials(Model):
    """Where a repository's trial is kept, in lup's state."""

    path: Path

    @classmethod
    def of(cls, layout: Layout, repository: Path) -> Trials:
        """Return the trial of the repository whose git directory is `repository`."""
        return cls(path=layout.trial(repository))

    def read(self) -> Trial:
        """Return what's kept; nothing on trial where nothing is."""
        return read_model(self.path, Trial) or Trial()

    def write(self, trial: Trial) -> None:
        """Keep `trial`, replacing what was there in one step."""
        write_model(self.path, trial)


def computed_ref(layout: Layout, repository: Path) -> str | None:
    """Return the full name of the branch lup computes for the repository at `repository`, as the declaration approved names it: the running branch where it isn't the integration branch; none where they're one."""
    branches = approved_branches(layout, repository)
    return None if branches.running == branches.integration else branches.running_ref


def running_tip(layout: Layout, repository: Path) -> str | None:
    """Return the commit of the running branch lup last computed for the repository at `repository`, where it computes one and has; none for whatever reads the branch's ref instead, as where what's kept doesn't read, as what a later lup kept might not."""
    if computed_ref(layout, repository) is None:
        return None
    try:
        return Trials.of(layout, repository).read().live
    except ValidationError:
        return None


class Plan(Model):
    """What `live` would hold: each branch in it with the commit of it, the tree they make in the store apart, and what keeps each other out."""

    tips: dict[str, str]
    tree: str
    conflicts: dict[str, str] = {}


def named(branches: list[str]) -> str:
    """Say `branches` in a sentence.

    >>> named(["a"]), named(["a", "b"]), named(["a", "b", "c"])
    ('`a`', '`a` and `b`', '`a`, `b` and `c`')
    """
    quoted = [f"`{each}`" for each in branches]
    *first, last = quoted
    return f"{', '.join(first)} and {last}" if first else last


def files_said(files: list[Path]) -> str:
    """Say the files a branch conflicts in, or that they've no history in common, where there are none.

    >>> files_said([Path("a.py"), Path("b.py")])
    'in `a.py` and `b.py`'
    >>> files_said([])
    'having no history in common'
    """
    if not files:
        return "having no history in common"
    return f"in {named([str(each) for each in files])}"


def conflict_with(
    apart: Apart, dev: str, integration: str, on: OnTrial, tips: dict[str, str]
) -> str:
    """Say what keeps the branch `on` from merging onto the commit `dev`, named `integration`, with `tips`; empty where nothing does.

    Each is tried alone, so what's named is what it conflicts with, not whichever
    came first of several.
    """
    match apart.merged(dev, {on.branch: on.tip}):
        case Unmerged(files=files):
            return f"it conflicts with `{integration}`, {files_said(files)}"
        case Composed():
            pass
    said = [
        f"`{name}`, {files_said(found.files)}"
        for name, tip in tips.items()
        if isinstance(
            found := apart.merged(dev, {name: tip, on.branch: on.tip}), Unmerged
        )
    ]
    if said:
        return f"it conflicts with {'; with '.join(said)}"
    together = apart.merged(dev, {**tips, on.branch: on.tip})
    if isinstance(together, Unmerged):
        return (
            f"it conflicts with {named(sorted(tips))} together, "
            f"{files_said(together.files)}"
        )
    return ""


def plan(apart: Apart, dev: str, integration: str, trial: Trial) -> Plan:
    """Return what `live` holds on the commit `dev`, named `integration`: each branch of `trial` that isn't out and merges cleanly with those before it, by the order they landed, and what keeps each other out.

    A branch `dev` holds, accepted, isn't asked of (`accepted`).
    """
    tips: dict[str, str] = {}
    for each in trial.branches:
        if each.out:
            continue
        match apart.merged(dev, {**tips, each.branch: each.tip}):
            case Composed():
                tips = {**tips, each.branch: each.tip}
            case Unmerged():
                pass
    conflicts = {
        each.branch: said
        for each in trial.branches
        if each.branch not in tips
        and (said := conflict_with(apart, dev, integration, each, tips))
    }
    match apart.merged(dev, tips):
        case Composed(tree=tree):
            return Plan(tips=tips, tree=tree, conflicts=conflicts)
        case Unmerged(branch=branch, files=files):
            message = (
                f"`{branch}` merged with those before it, and not once they were "
                f"in their order, {files_said(files)}"
            )
            raise GitError(message)


def accepted(git: Git, dev: str, trial: Trial) -> Trial:
    """Return `trial` without each branch the commit `dev` holds in its history: it's been accepted, however it got there."""

    def holds(each: OnTrial) -> bool:
        found = git.run("merge-base", "--is-ancestor", each.tip, dev, ok=[0, 1])
        return found.status == 0

    return trial.model_copy(
        update={"branches": [each for each in trial.branches if not holds(each)]}
    )


def message_of(integration: str, dev: str, tips: dict[str, str]) -> str:
    r"""Return the message of `live`'s commit of `tips` on the commit `dev`, named `integration`: what it holds, a line each, so its history reads as the versions it was.

    >>> print(message_of("dev", "d1", {"b": "t2", "a": "t1"}))
    live: `dev` with `a` and `b`
    <BLANKLINE>
    dev: d1
    a: t1
    b: t2
    >>> print(message_of("dev", "d1", {}))
    live: `dev` alone
    <BLANKLINE>
    dev: d1
    """
    what = f"with {named(sorted(tips))}" if tips else "alone"
    lines = [f"{name}: {tips[name]}" for name in sorted(tips)]
    return "\n".join([f"live: `{integration}` {what}", "", f"dev: {dev}", *lines])


def next_commit(
    apart: Apart,
    trial: Trial,
    dev: str,
    integration: str,
    plan_: Plan,
    *,
    at: datetime,
) -> str | None:
    """Make `live`'s next commit of `plan_` on the commit `dev`, its first parent the tip before, so it only moves forward; return it, or none where `live` is that already.

    Before its first commit, `live` starts at `dev`'s tip, which needs no commit
    of its own where nothing's in it. Its other parents are `dev` and each
    branch in it: what's read as its history, and what keeps each reachable.
    """
    latest = trial.latest
    if latest is not None and latest.dev == dev and latest.tips == plan_.tips:
        return None
    if trial.live is None and not plan_.tips:
        return dev
    parents = dedupe(
        [trial.live or dev, dev, *(plan_.tips[name] for name in sorted(plan_.tips))]
    )
    return apart.committed(
        plan_.tree, parents, message_of(integration, dev, plan_.tips), at
    )


def pins(trial: Trial) -> list[str]:
    """Return the commits whose copies stay kept while `trial` stands: each version holding a branch on trial at the tip it's on trial at, and `dev` alone at the commit that's on."""
    current = {each.branch: each.tip for each in trial.branches}
    return dedupe(
        [
            each.commit
            for each in trial.versions
            if any(current.get(name) == tip for name, tip in each.tips.items())
            or (each.dev == trial.dev and not each.tips)
        ]
    )


def moved_on(
    trial: Trial,
    commit: str,
    dev: str,
    plan_: Plan,
    at: datetime,
    *,
    keeping: int = 50,
    fingerprint: str | None = None,
) -> Trial:
    """Return `trial` with `live` at `commit`, what `plan_` holds and what keeps each other out, keeping the last `keeping` of the versions still pinned, and this one, whose host zone has `fingerprint`, where it was read: `live` staying at a commit it holds, nothing's read of it, and what was stays."""
    known = next(
        (each.fingerprint for each in trial.versions if each.commit == commit), None
    )
    version = Version(
        commit=commit,
        dev=dev,
        tips=plan_.tips,
        at=at,
        fingerprint=fingerprint or known,
    )
    branches = [
        each.model_copy(update={"conflict": plan_.conflicts.get(each.branch, "")})
        for each in trial.branches
    ]
    stands = trial.model_copy(
        update={
            "live": commit,
            "dev": dev,
            "branches": branches,
            "versions": [
                *(each for each in trial.versions if each.commit != commit),
                version,
            ],
        }
    )
    held = pins(stands)
    versions = [each for each in stands.versions if each.commit in held]
    if version not in versions:
        versions = [*versions, version]
    return stands.model_copy(update={"versions": versions[-keeping:]})


def move_ref(git: Git, branches: Branches, commit: str) -> str | None:
    """Move the local running branch of `branches` to `commit`, for whoever reads it there; say why it didn't, or none where it did.

    Left where a worktree has it checked out, whose files it would leave behind,
    and where a link under `refs/` would have git write elsewhere (`refs_astray`).
    What reads what runs reads the record, so neither changes that.
    """
    running = branches.running
    swayed = refs_astray(git)
    if swayed:
        return f"`{running}` here still names what it did: {swayed}"
    if git.checkout(running) is not None:
        return (
            f"`{running}` here still names what it did: a worktree has it checked out"
        )
    git.run("update-ref", branches.running_ref, commit)
    return None


class Origin(Model):
    """A repository's remote, where what's asked of it comes from no room: the operator's picks, and what follows a branch accepted."""

    git: Git
    """git on the repository, pinned there."""
    remote: str = "origin"

    def url(self, *, push: bool) -> str:
        """Return the remote's URL, as the repository's `config` names it: raise `GitError` where it names none."""
        self.git.run("config", "--local", "--get-all", f"remote.{self.remote}.url")
        return self.git.text(
            "remote", "get-url", *(["--push"] if push else []), self.remote
        )

    def tip(self, ref: str) -> str | None:
        """Return the commit `ref` names on the remote, fetched into the store; none where it holds none. Raise `GitError` where it can't be reached."""
        url = self.url(push=True)
        quiet = self.quiet()
        found = quiet.text("ls-remote", "--end-of-options", url, ref).split()
        if not found:
            return None
        quiet.run(
            "fetch",
            "--no-write-fetch-head",
            "--no-tags",
            "--no-recurse-submodules",
            "--end-of-options",
            url,
            ref,
        )
        return found[0]

    def pushed(self, commit: str, ref: str) -> None:
        """Move `ref` on the remote to `commit`, a fast-forward: raise `GitError` where it can't."""
        self.quiet().run(
            "push",
            "--no-verify",
            "--no-recurse-submodules",
            "--end-of-options",
            self.url(push=True),
            f"{commit}:{ref}",
        )

    def quiet(self) -> Git:
        """Return git on the repository with its own upkeep off, as the host's pushes and fetches run it."""
        return self.git.model_copy(
            update={"arguments": ["-c", "gc.auto=0", "-c", "maintenance.auto=false"]}
        )


def versions_listed(
    versions: list[Version],
    kept: list[Kept],
    runs: str | None,
    fingerprint: str | None,
) -> list[VersionListed]:
    """Return `versions`, in their order, as a page lists them: each with the copy of `kept` that runs it, by its commit, else by the host zone they hold; and the latest of what's approved, the commit `runs` with `fingerprint`, as what runs.

    >>> at = datetime(2026, 11, 7)
    >>> older = Version(commit="a", dev="d", at=at, fingerprint="z")
    >>> newer = Version(commit="b", dev="d", at=at, fingerprint="z")
    >>> [each.running for each in versions_listed([older, newer], [], "c", "z")]
    [False, True]
    """

    def holding(version: Version, commit: str, zone: str | None) -> bool:
        same = version.fingerprint is not None and version.fingerprint == zone
        return version.commit == commit or same

    current = next(
        (
            each.commit
            for each in reversed(versions)
            if runs is not None and holding(each, runs, fingerprint)
        ),
        None,
    )

    def listed(version: Version) -> VersionListed:
        copy = next(
            (
                each
                for each in kept
                if holding(version, each.commit, each.approval.fingerprint)
            ),
            None,
        )
        return VersionListed(
            commit=version.commit,
            dev=version.dev,
            tips=version.tips,
            at=version.at,
            copy_kept=None if copy is None else copy.commit,
            running=version.commit == current,
            ran=None if copy is None else copy.answered,
        )

    return [listed(each) for each in versions]


def trial_listed(
    layout: Layout, repository: Path, kept: list[Kept]
) -> TrialListed | None:
    """Return what's on trial for the repository at `repository`, as a page lists it, `kept` being the copies kept of it; none where it computes no running branch, or what's kept doesn't read, as what a later lup kept might not: the plain page is what's left when things are broken, so it lists the copies whatever this says."""
    if computed_ref(layout, repository) is None:
        return None
    branches = approved_branches(layout, repository)
    try:
        trial = Trials.of(layout, repository).read()
    except ValidationError:
        return None
    within = trial.tips
    approval = approved(layout, repository)
    built = [each.commit for each in kept]

    def alone(each: OnTrial) -> bool:
        return any(
            version.commit in built
            and version.dev == trial.dev
            and version.tips == {each.branch: each.tip}
            for version in trial.versions
        )

    return TrialListed(
        integration=branches.integration,
        running=branches.running,
        dev=trial.dev,
        live=trial.live,
        branches=[
            BranchListed(
                branch=each.branch,
                tip=each.tip,
                subject=each.subject,
                landed=each.landed,
                within=each.branch in within,
                out=each.out,
                conflict=each.conflict,
                built=alone(each),
                party=each.party,
            )
            for each in trial.branches
        ],
        versions=versions_listed(
            trial.versions,
            kept,
            None if approval is None else approval.commit,
            None if approval is None else approval.fingerprint,
        ),
        runs=None if approval is None else approval.commit,
    )
