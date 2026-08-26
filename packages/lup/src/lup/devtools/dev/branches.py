"""Branch analysis: containment, PR status, base detection, freshness, PR bodies."""

import json
import logging
import sys
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from collections.abc import Set as AbstractSet
from itertools import groupby
from operator import attrgetter
from pathlib import Path, PurePosixPath
from typing import Literal, NoReturn, Required, TypedDict
from urllib.parse import urlparse

import sh
import typer
from pydantic import BaseModel, Field

from lup.harness.environment import non_interactive_environment
from lup.harness.process import LaunchRequest, ProcessLauncher
import lup.devtools.dev.traces as traces
from lup.devtools.dev.remote_auth import check_remote_auth, remote_auth_refusal
from lup.resolver.models import HeldLease
from lup.resolver.state import live_lease_branches
from lup.types import StringMap
from lup.workspace.paths import project_root
from lup.devtools.utils import (
    format_table,
    git,
    gh,
    config_lock_diagnosis,
    decode_stderr,
    output_json,
    repository_arguments,
    short_sha,
)

logger = logging.getLogger(__name__)


class PRStatus(BaseModel):
    """One PR row as `gh pr list --json` returns it (aliases are gh's names)."""

    number: int
    title: str = ""
    state: str = ""
    merged_at: str | None = Field(default=None, alias="mergedAt")
    head_ref: str = Field(default="", alias="headRefName")
    url: str = ""

    def reusable(self) -> bool:
        """Whether a retirement can close this rather than opening its own.

        Only one still open. A request that already reached a terminal state
        cannot be closed again — GitHub refuses the transition outright for a
        merged one — so a retirement that reused whichever was most recent
        would push the branch and then fail at the close, leaving the work
        half-moved. A fresh request over the same head is allowed once the
        previous is no longer open, and the old one keeps its own head ref
        regardless, so nothing it preserved is lost by opening another.
        """
        return self.state == "OPEN"


type BranchStatus = Literal[
    "LAND", "DELETE", "STALE", "KEEP", "CURRENT", "UNRELATED", "NOT_FOUND"
]


class Disposition(BaseModel):
    """The one verb a branch resolves to, and the reason it got it."""

    status: BranchStatus
    reason: str


class WorktreeChanges(BaseModel):
    """What a worktree holds that removing it would discard."""

    modified: int = 0
    untracked: int = 0

    def dirty(self) -> bool:
        return bool(self.modified or self.untracked)

    def summary(self) -> str:
        return f"{self.modified} modified, {self.untracked} untracked"

    def compact(self) -> str:
        """The same count in a table cell, where a sentence would not fit."""
        if not self.dirty():
            return "-"
        return " ".join(
            [
                *([f"{self.modified}M"] if self.modified else []),
                *([f"{self.untracked}U"] if self.untracked else []),
            ]
        )


class BranchInfo(BaseModel):
    name: str
    commit: str
    tracking: str | None
    worktree: str | None
    is_current: bool
    contained_in: list[str]
    pr: PRStatus | None
    unique_commits: int
    source_diff_lines: int
    disposition: BranchStatus
    reason: str
    rewritten: int = 0
    """How many unique commits already name a subject in the integration branch.

    Never a disposition, and never subtracted from ``unique_commits``. A
    containment check is decided by patch-id, which a rewrite changes, so a
    commit that landed rebased or reworded reads as unlanded ever after and
    a pre-rewrite snapshot presents its whole history as work at risk. A
    shared subject is the cheapest signal that this happened and is not
    proof it did, so it is carried where a reader will see it and nowhere a
    verb is decided — the wrong direction to be wrong in is the one that
    marks real work landed.
    """
    changes: WorktreeChanges | None = None
    """What this branch's worktree holds uncommitted, where it has one.

    Carried beside the disposition rather than folded into its reason: the
    classifier is shared with `dev survey`, and a verb decided partly on
    working-tree state there would drift from the same verb decided here.
    What this changes is the cost of acting, not the action — a DELETE whose
    worktree is dirty still deletes, but refuses until forced, and a reader
    handed the disposition alone plans a step that will stop.
    """


class RemoteBranchInfo(BaseModel):
    """A branch on a remote that no local branch corresponds to.

    A sweep classifies what ``refs/heads`` holds, so a branch whose local
    copy was deleted once its work landed leaves nothing behind to resolve
    to a verb — it stops being mentioned rather than being reported done.
    The remote keeps it regardless, and the next sweep is blind to it in
    exactly the same way, which is the one shape a sweep exists to surface
    and the one it could not express.

    Kept apart from ``BranchInfo`` rather than folded into it: that model
    answers what to do with a checkout, and its worktree, lease, and
    dirty-state figures describe things a ref on a remote cannot have.
    Reporting one through the other would mean carrying a row whose every
    such column is a placeholder, which reads as measured and is not.
    """

    name: str
    remote: str
    commit: str
    contained_in_integration: bool
    pr: PRStatus | None
    unique_commits: int
    disposition: BranchStatus
    reason: str

    def qualified(self) -> str:
        """How git names this ref, which is also how a comparison must spell it."""
        return f"{self.remote}/{self.name}"

    def delete_command(self) -> str:
        """The push that removes it, for a reader who has to run it.

        Spelled against the branch rather than the tracking ref: a delete
        names what the remote calls the branch, and the ``remote/`` prefix
        that identifies it locally is not part of that name.
        """
        return f"git push {self.remote} --delete {self.name}"


class RunHold(BaseModel):
    """One resolver run and the branches it is still holding out of the sweep.

    A sweep reads this before it reads the branch list. A run that is still
    working answers for its own branches, so they are somebody's business
    already; a run that died answers for nothing, and the branches it holds
    are work with no owner and no verb — the one shape a sweep exists to
    surface and cannot express as a per-branch disposition.
    """

    run_id: str
    alive: bool
    branches: list[str]


class SurveyResult(BaseModel):
    integration_branch: str
    current_branch: str
    branches: list[BranchInfo]
    runs: list[RunHold] = []
    remote_branches: list[RemoteBranchInfo] = []
    """Branches on a remote that no local branch corresponds to.

    Separate from ``branches`` so a consumer reading local dispositions is
    not handed rows it has no verb for, and present at all so the ones whose
    work already landed stop being invisible to the sweep that would clear
    them.
    """


def runs_holding(leased: dict[str, HeldLease]) -> list[RunHold]:
    """Group every held branch under the run answerable for it."""
    ordered = sorted(leased.values(), key=attrgetter("run_id"))
    return [
        RunHold(
            run_id=run_id,
            alive=held[0].alive,
            branches=sorted(lease.branch for lease in held),
        )
        for run_id, group in groupby(ordered, key=attrgetter("run_id"))
        if (held := list(group))
    ]


def leased_on_disk(
    lease_of: Mapping[str, HeldLease], branch_names: Iterable[str]
) -> dict[str, HeldLease]:
    """The held leases a branch survey can say anything about.

    A run records every branch it ever leased, and a completed run keeps
    reporting the ones its cleanup did not delete. Only a branch still in
    ``refs/heads`` can be landed, kept, or dropped, so every reader of the
    lease record meets it through this intersection — one that read the
    record alone would count a run's deleted branches as work still held.
    """
    return {name: lease_of[name] for name in branch_names if name in lease_of}


class BranchClassification(TypedDict, total=False):
    branch: Required[str]
    status: Required[BranchStatus]
    reason: Required[str]
    worktree: str | None
    pr: str | int
    pr_url: str


class ParsedBranch(TypedDict):
    """One local branch row from ``git for-each-ref``."""

    name: str
    commit: str
    tracking: str | None
    is_current: bool


def parse_branches() -> list[ParsedBranch]:
    """Structured local-branch rows via ``git for-each-ref``.

    NUL-separated ``--format`` fields are the machine interface — no marker
    columns or bracket surgery; ``%(HEAD)`` is ``*`` exactly for the branch
    checked out in the current worktree.
    """

    def parse(row: str) -> ParsedBranch:
        name, commit, upstream, head = row.split(  # lup: ignore[string-split] — NUL
            "\x00"
        )
        return {
            "name": name,
            "commit": commit,
            "tracking": upstream or None,
            "is_current": head == "*",
        }

    return [
        parse(row)
        for row in git.lines(
            "for-each-ref",
            "refs/heads",
            "--format=%(refname:short)%00%(objectname:short)"
            "%00%(upstream:short)%00%(HEAD)",
        )
    ]


def parse_worktrees() -> dict[str, str]:  # lup: ignore[dict-str-payload]
    """Map branch name -> worktree path from ``git worktree list --porcelain``.

    Open, data-driven keys (whatever branches have worktrees), folded from
    porcelain records that span multiple lines — the one stateful walk here.
    """
    mapping: dict[str, str] = {}  # lup: ignore[dict-str-payload, empty-collection]
    current_path = ""

    for line in git.lines("worktree", "list", "--porcelain"):
        if line.startswith("worktree "):
            current_path = line.removeprefix("worktree ")
        elif line.startswith("branch refs/heads/"):
            mapping[line.removeprefix("branch refs/heads/")] = current_path

    return mapping


class ParsedRemoteBranch(TypedDict):
    """One remote-tracking ref, split into the remote and the branch on it."""

    remote: str
    name: str
    commit: str


def fetch_remote_tracking() -> None:
    """Refresh remote-tracking refs, naming the refspec rather than assuming one.

    ``git clone --bare`` configures no ``remote.<name>.fetch``, so a plain
    ``git fetch --prune`` in such a clone writes ``FETCH_HEAD`` and nothing
    else: ``refs/remotes`` stays empty, and every branch that exists only on
    the remote is invisible to whatever reads it. The failure is silent in
    the worst direction — the survey that follows looks complete, because a
    branch it cannot see is indistinguishable from one that is not there.

    Naming the standard refspec is what a non-bare clone already does from
    its own configuration, so the repaired clone is the only one whose
    behaviour changes, and nothing is written to the repository's config to
    do it. Failures propagate to the caller, which already logs a fetch it
    could not complete and surveys the refs it has.
    """
    for remote in git.lines("remote"):
        git("fetch", "--prune", remote, f"+refs/heads/*:refs/remotes/{remote}/*")


def parse_remote_branches() -> list[ParsedRemoteBranch]:
    """Structured remote-tracking rows via ``git for-each-ref``, per remote.

    Iterating the remotes and stripping a known prefix length keeps the
    remote and the branch separate without splitting a ref name on ``/`` —
    a branch is allowed to contain one, so surgery on the joined form would
    report ``feat`` for ``origin/feat/x`` and be wrong exactly where branch
    names are most conventional.

    ``%(symref)`` is set for ``origin/HEAD`` alone, which names another ref
    rather than a branch of its own: counting it would report the default
    branch a second time, under a name no push can delete.
    """

    def parse(remote: str, row: str) -> ParsedRemoteBranch | None:
        name, commit, symref = row.split("\x00")  # lup: ignore[string-split] — NUL
        if symref:
            return None
        return {"remote": remote, "name": name, "commit": commit}

    return [
        parsed
        for remote in git.lines("remote")
        for row in git.lines(
            "for-each-ref",
            f"refs/remotes/{remote}",
            "--format=%(refname:lstrip=3)%00%(objectname:short)%00%(symref)",
        )
        if (parsed := parse(remote, row)) is not None
    ]


def build_containment(branch_names: list[str]) -> dict[str, list[str]]:
    """For each branch, find which other branches contain it."""
    containment: dict[str, list[str]] = {b: [] for b in branch_names}

    for branch in branch_names:
        for target in branch_names:
            if branch == target:
                continue
            try:
                git("merge-base", "--is-ancestor", branch, target)
                containment[branch].append(target)
            except sh.ErrorReturnCode:
                pass

    return containment


def fetch_pr_status(branch_names: list[str]) -> dict[str, PRStatus]:
    """Query GitHub for PR status of branches."""
    try:
        rows = json.loads(
            gh.out(
                "pr",
                "list",
                *repository_arguments(),
                "--state",
                "all",
                "--limit",
                "200",
                "--json",
                "number,title,headRefName,state,mergedAt",
            )
        )
    except sh.ErrorReturnCode as e:
        logger.warning("Failed to fetch PR status: %s", decode_stderr(e))
        return {}
    prs = [PRStatus.model_validate(row) for row in rows]
    return {pr.head_ref: pr for pr in prs if pr.head_ref in branch_names}


def count_unique_commits(branch: str, integration: str) -> int:
    """Count commits on branch not cherry-picked into integration (-1: unknown)."""
    try:
        return int(
            git.out(
                "rev-list",
                "--count",
                "--cherry-pick",
                "--left-only",
                f"{branch}...{integration}",
                _ok_code=[0],
            )
        )
    except (sh.ErrorReturnCode, ValueError):
        return -1


def count_source_diff_lines(branch: str, integration: str) -> int:
    """Count lines of source-file diff between branch and integration (-1: unknown).

    ``--numstat`` is the machine format: one ``added<TAB>deleted<TAB>path`` row
    per file (``-`` for binary files, which count no lines).
    """
    try:
        rows = git.lines(
            "diff",
            "--numstat",
            branch,
            integration,
            "--",
            "src/",
            ".claude/",
            "tests/",
            _ok_code=[0, 1],
        )
    except sh.ErrorReturnCode:
        return -1
    total = 0
    for row in rows:
        added, _, rest = row.partition("\t")  # lup: ignore[string-split] — numstat
        deleted = rest.partition("\t")[0]  # lup: ignore[string-split] — numstat
        total += int(added) if added.isdigit() else 0
        total += int(deleted) if deleted.isdigit() else 0
    return total


def get_integration_branch() -> str:
    """Return 'dev' if it exists locally, else 'main'."""
    from lup.devtools.dev.worktree import branch_exists

    if branch_exists("dev"):
        return "dev"
    return "main"


def is_ancestor(ancestor: str, descendant: str) -> bool:
    """Check if ancestor is an ancestor of descendant."""
    try:
        git("merge-base", "--is-ancestor", ancestor, descendant)
        return True
    except sh.ErrorReturnCode:
        return False


def shares_history(branch: str, integration: str) -> bool:
    """Whether the two have any commit in common.

    Asked because neither counter fails without one, so nothing downstream
    reports the difference. ``A...B`` degenerates to both sides entire when
    there is no merge base, and ``--left-only`` then returns a plausible
    small number; the diff is a direct two-tree comparison that never needed
    a merge base, and reports the whole distance between two unrelated trees
    as though it were a divergence. Both figures are then read as one, and a
    branch whose real relationship to the integration branch is *none*
    presents as ordinary unlanded work — which a sweep offers to rebase or
    merge, and both would replay an unrelated tree.
    """
    try:
        git("merge-base", branch, integration)
        return True
    except sh.ErrorReturnCode:
        return False


def never_diverged_from(branch: str, integration: str) -> bool:
    """Whether the branch still stands where it was cut from the integration branch.

    The difference between a branch that never diverged and one whose work
    landed. Both are ancestors, so containment alone reads them alike and
    calls the first spent. What tells them apart is which side of a merge the
    tip sits on: a branch cut from the integration branch and not yet
    committed to points at one of that branch's own commits, so it stands on
    its first-parent history, where a branch whose work landed points at the
    side parent a merge absorbed and never appears there.

    Pointing at the tip exactly answers this for one commit's worth of time
    and stops answering it the moment anything else lands — which during a
    sweep is almost at once, because every merge moves the integration branch
    out from under every workspace reserved against it.
    """
    try:
        head = git.out("rev-parse", branch).strip()
        return head in git.lines("rev-list", "--first-parent", integration)
    except sh.ErrorReturnCode:
        return False


def rewrite_suspects(branch: str, integration: str) -> list[str]:
    """This branch's commits whose subject already names one in *integration*.

    Containment is decided by patch-id, which a rewrite changes: a commit
    rebased, reworded, or squashed before it landed keeps its content and
    reads as unlanded ever after. A branch kept as a pre-rewrite snapshot
    then presents its whole history as work at risk.

    Advisory, and deliberately not a disposition. A subject is not proof —
    two commits may honestly share one — and a classifier that treated it as
    proof would mark real work landed and invite deleting it. What this
    supports is the reader's next question, which is whether to go and
    compare; what it must never do is answer it.

    Counted over the set :func:`count_unique_commits` counts, down to the
    same ``--cherry-pick --left-only`` filter, so this is a subset of that
    figure and the pair reads as "so many of those". Taken over a plain
    range instead it drew from a wider set and reported five suspects
    against four unique commits — a fraction past its own denominator, which
    is the shape a reader stops believing.
    """
    landed = {line for line in git.lines("log", "--format=%s", integration) if line}
    return [
        subject
        for subject in git.lines(
            "log",
            "--format=%s",
            "--cherry-pick",
            "--left-only",
            f"{branch}...{integration}",
        )
        if subject in landed
    ]


def get_branch_worktree(branch: str) -> str | None:
    """Return the worktree path for a branch, or None."""
    return parse_worktrees().get(branch)


def get_pr_info(branch: str) -> PRStatus | None:
    """Get PR info for a branch via gh CLI. None when there is none (or no gh).

    The repository is named rather than inferred. `gh` reads the origin
    remote to decide which repository it is talking about, and a remote
    written through an SSH alias names no host it recognizes — so every
    query failed, and this returned the same ``None`` it returns for a
    branch that genuinely has no pull request. A branch with an open PR
    then classified ``LAND``.
    """
    try:
        items = json.loads(
            gh.out(
                "pr",
                "list",
                *repository_arguments(),
                "--state=all",
                f"--head={branch}",
                "--json=number,title,state,mergedAt,url",
                "--limit=1",
                _ok_code=[0],
            )
        )
    except (sh.ErrorReturnCode, sh.CommandNotFound, json.JSONDecodeError) as error:
        logger.warning("no pull-request status for %s: %s", branch, error)
        return None
    return PRStatus.model_validate(items[0]) if items else None


PROTECTED_BRANCHES = {"main", "master", "dev", "develop"}
"""Branches no workflow here offers to delete, unless a project says otherwise.

The four names cover the two-tier and single-tier conventions in common use;
a project whose trunk is called something else passes its own set rather than
forking the functions that consult this one.
"""


def disposition_for(
    name: str,
    *,
    integration: str,
    current: str,
    contained_in: list[str],
    pr: PRStatus | None,
    unique_commits: int,
    protected: AbstractSet[str] = PROTECTED_BRANCHES,
    held: str = "",
    related: bool = True,
    never_diverged: bool = False,
    worktree: str | None = None,
) -> Disposition:
    """Resolve a branch to its single disposition.

    Every branch resolves to exactly one verb, so unlanded work has no silent
    bucket to sit in: a branch holding commits the integration branch lacks,
    with no open PR driving it, is ``LAND`` rather than ``KEEP``. Containment
    counts as landed only against the integration branch — sitting inside a
    sibling that has not landed either is no reason to drop work.

    ``held`` is why something else is already answerable for this branch, and
    outranks every disposition but the current and protected ones. A resolver
    lease is the case: it reads as abandoned work by every other signal here,
    and both verbs a sweep would offer for it destroy something.

    Two guards sit ahead of containment because containment answers them
    wrongly rather than not at all. A branch sharing no history has no
    divergence to measure, so every figure downstream describes a comparison
    that means nothing. A branch that never diverged has spent nothing — an
    ancestor exactly as a merged branch is, and for the opposite reason — so
    a worktree held open on one is a workspace somebody reserved, not a
    leftover. Which of the two it is comes from where the tip stands, never
    from how far the integration branch has since travelled: a sweep moves
    that branch under every workspace reserved against it, so a guard reading
    distance would protect a workspace only until the sweep's first merge.
    """
    if name == current:
        return Disposition(status="CURRENT", reason="current branch")
    if name in protected:
        return Disposition(status="KEEP", reason="protected branch")
    if held:
        return Disposition(status="KEEP", reason=held)
    if not related:
        return Disposition(
            status="UNRELATED", reason=f"shares no history with {integration}"
        )
    if never_diverged and worktree is not None:
        return Disposition(
            status="KEEP", reason=f"reserved workspace cut from {integration}"
        )
    if integration in contained_in:
        return Disposition(status="DELETE", reason=f"merged into {integration}")
    if pr is not None and pr.state == "MERGED":
        return Disposition(status="DELETE", reason=f"PR #{pr.number} merged")
    if unique_commits == 0:
        return Disposition(
            status="STALE", reason=f"all commits cherry-picked into {integration}"
        )
    if pr is not None and pr.state == "OPEN":
        return Disposition(
            status="KEEP",
            reason=f"PR #{pr.number} open, {unique_commits} unique commits",
        )

    carried = [b for b in contained_in if b != integration]
    also = f"; also carried by {', '.join(carried)}" if carried else ""
    return Disposition(
        status="LAND", reason=f"{unique_commits} unique commits, no PR{also}"
    )


def classify_branch(
    branch: str,
    integration: str,
    current: str,
    *,
    has_remote: bool = True,
    protected: AbstractSet[str] = PROTECTED_BRANCHES,
) -> BranchClassification:
    """Classify a branch as DELETE/STALE/KEEP/CURRENT/NOT_FOUND with reason."""
    from lup.devtools.dev.worktree import branch_exists

    if not branch_exists(branch):
        return {
            "branch": branch,
            "status": "NOT_FOUND",
            "reason": "no such local branch",
        }

    if branch == current or branch in protected:
        guard = disposition_for(
            branch,
            integration=integration,
            current=current,
            contained_in=[],
            pr=None,
            unique_commits=0,
        )
        return {"branch": branch, "status": guard.status, "reason": guard.reason}

    merged_into_integration = is_ancestor(branch, integration)
    worktree = get_branch_worktree(branch)
    pr = get_pr_info(branch) if has_remote else None
    pr_number: str | int = pr.number if pr else ""
    pr_url = pr.url if pr else ""

    counted = count_unique_commits(branch, integration)
    verdict = disposition_for(
        branch,
        integration=integration,
        current=current,
        contained_in=[integration] if merged_into_integration else [],
        pr=pr,
        unique_commits=counted if counted >= 0 else 999,
    )

    return {
        "branch": branch,
        "status": verdict.status,
        "reason": verdict.reason,
        "worktree": worktree,
        "pr": pr_number,
        "pr_url": pr_url,
    }


class UnlandedBranch(BaseModel):
    """A branch holding commits the integration branch does not have.

    ``contained_by`` names the unlanded sibling that already carries every
    commit of this one, when there is such a sibling: the same work under
    two names is one decision, not two lines of backlog.
    """

    name: str
    unique_commits: int
    source_diff_lines: int
    worktree: str | None
    contained_by: str | None = None

    def standing(self) -> str:
        """What this branch holds, as one line reads it."""
        if self.contained_by is not None:
            return f"every commit already inside {self.contained_by}"
        return f"{self.unique_commits} commit(s), {self.source_diff_lines} ln unlanded"


def unlanded_siblings(
    protected: AbstractSet[str] = PROTECTED_BRANCHES,
) -> list[UnlandedBranch]:
    """Local-only scan for branches holding work the integration branch lacks.

    Deliberately offline — no fetch, no PR query — because this runs inside
    every ``dev check``. An open PR driving a branch is therefore invisible
    here, which is why the result is advisory: it reports what has not
    reached integration, and the full sweep decides what to do about it.

    The current branch is excluded: work in hand is not work parked out of
    sight, and reporting it every run would train the reader to skip the line.

    So is any branch a resolver run answers for. A run holds its branches
    out of the sweep deliberately, and its leftovers are one decision about
    the run rather than a list of parked work; a batch of them here is the
    same line repeated until the reader skips it, and reads as a backlog
    nobody is carrying when a run either is carrying it or has finished.
    Reading the run directory keeps this offline, which the rest of it is.

    A branch every commit of which another unlanded sibling already carries
    is reported inside that sibling rather than beside it. Two lines showing
    one line's figures read as twice the backlog, and a reader adding them
    up lands on a number nothing holds.
    """
    integration = get_integration_branch()
    worktrees = parse_worktrees()
    current = git.out("branch", "--show-current")
    leased = live_lease_branches(project_root() / ".lup" / "resolve")

    def measure(name: str) -> UnlandedBranch | None:
        if name == current or name in protected or name in leased:
            return None
        if is_ancestor(name, integration):
            return None
        unique = count_unique_commits(name, integration)
        if unique <= 0:
            return None
        return UnlandedBranch(
            name=name,
            unique_commits=unique,
            source_diff_lines=count_source_diff_lines(name, integration),
            worktree=worktrees.get(name),
        )

    measured = [
        found
        for name in git.lines("branch", "--format=%(refname:short)")
        if (found := measure(name)) is not None
    ]

    def container_of(branch: UnlandedBranch) -> str | None:
        """The sibling that carries all of this branch, if one does.

        The widest strict container wins, so a chain names its top rather
        than its next link. Two names on one commit contain each other, and
        the first by name stands for the group.
        """
        carriers = [
            other
            for other in measured
            if other.name != branch.name and is_ancestor(branch.name, other.name)
        ]
        strict = [
            other for other in carriers if not is_ancestor(other.name, branch.name)
        ]
        if strict:
            return max(strict, key=attrgetter("unique_commits")).name
        same_tip = sorted(other.name for other in carriers)
        if same_tip and same_tip[0] < branch.name:
            return same_tip[0]
        return None

    return [
        branch.model_copy(update={"contained_by": container_of(branch)})
        for branch in measured
    ]


class BaseCandidate(BaseModel):
    """A candidate base branch, measured against the branch under test.

    ``source`` states whether the name came from the base recorded at
    worktree creation or from topological guessing.
    """

    name: str
    distance: int
    merge_base: str
    is_ancestor: bool
    source: Literal["recorded", "guessed"] = "guessed"


def base_config_key(branch: str) -> str:
    """Where the base a worktree was cut from is recorded, for one branch.

    Written at creation and read wherever a branch's origin has to be
    recovered, so the key is named once instead of spelled at each end.
    """
    return f"branch.{branch}.lup-base"


def recorded_base(branch: str) -> str | None:
    """The base recorded at worktree creation, when one was written."""
    try:
        value = git.out("config", "--get", base_config_key(branch), _ok_code=[0])
    except sh.ErrorReturnCode:
        return None
    return value or None


def detect_base_branch(branch: str | None = None) -> BaseCandidate:
    """Detect the base branch for the given (or current) branch.

    A base recorded at worktree creation (``branch.<name>.lup-base``) wins
    outright — topology cannot recover the creation point once the parent
    has merged on. Without a record, prefers ancestor branches (the natural
    parent in a two-tier model) over siblings. Among ancestors, picks the
    one with the fewest commits ahead (``distance``). Falls back to
    non-ancestors when no ancestor exists.
    """
    effective = branch or git.out("branch", "--show-current")

    local_branches = [
        b for b in git.lines("branch", "--format=%(refname:short)") if b != effective
    ]

    if not local_branches:
        typer.echo("No other local branches to compare against.", err=True)
        raise typer.Exit(1)

    def measure(candidate: str) -> BaseCandidate | None:
        try:
            merge_base = git.out("merge-base", effective, candidate, _ok_code=[0])
            distance = int(git.out("rev-list", "--count", f"{merge_base}..{effective}"))
        except sh.ErrorReturnCode:
            return None
        return BaseCandidate(
            name=candidate,
            distance=distance,
            merge_base=merge_base,
            is_ancestor=is_ancestor(candidate, effective),
        )

    recorded = recorded_base(effective)
    if recorded is not None and recorded in local_branches:
        pinned = measure(recorded)
        if pinned is not None:
            return pinned.model_copy(update={"source": "recorded"})

    measured = [m for c in local_branches if (m := measure(c)) is not None]
    ancestors = [m for m in measured if m.is_ancestor]

    # Prefer ancestors — they are the natural base. With none, every measured
    # candidate is a non-ancestor, so `measured` IS the sibling fallback.
    candidates = ancestors or measured

    if not candidates:
        typer.echo("Could not determine base branch.", err=True)
        raise typer.Exit(1)

    ranked = sorted(candidates, key=lambda c: c.distance)
    best = ranked[0]

    tied = [c for c in ranked[1:] if c.distance == best.distance]
    if tied:
        typer.echo("Ambiguous base branch. Candidates:", err=True)
        for c in [best, *tied]:
            typer.echo(f"  {c.name} ({c.distance} commits ahead)", err=True)
        raise typer.Exit(1)

    return best


class RemoteMeasure(BaseModel, ABC, frozen=True):
    """One remote branch, and how many of its commits this checkout is missing.

    The commits arrive by a different route depending on which remote was
    measured, so the route is a property of the reading rather than a setting
    a reader passes alongside it. Each member answers with its own, which is
    what keeps a remedy from being printed beside a count it cannot close.
    """

    tracked: str
    """The remote branch measured against."""

    behind: int = 0
    """Commits that branch holds which this checkout does not."""

    @abstractmethod
    def update_command(self) -> str:
        """What a reader runs to take the commits this reading found missing."""

    @abstractmethod
    def subject(self) -> str:
        """What a report calls the thing that is behind."""

    def stale(self) -> bool:
        """Whether the remote is known to hold commits this checkout does not."""
        return self.behind > 0

    def report(self) -> str:
        """One line naming the count and the way to close it."""
        if not self.behind:
            return f"{self.subject()} is current with {self.tracked}"
        return (
            f"{self.subject()} is {self.behind} commit(s) behind {self.tracked}: "
            f"update with `{self.update_command()}`"
        )


class UpstreamMeasure(RemoteMeasure, frozen=True):
    """The branch's own remote, whose commits arrive by fast-forward."""

    def update_command(self) -> str:
        return "git pull --ff-only"

    def subject(self) -> str:
        return "branch"


class BaseMeasure(RemoteMeasure, frozen=True):
    """The remote of the base a worktree was cut from, taken by merge.

    A feature branch holds commits its base does not, so there is nothing
    here to fast-forward. Naming a pull would name the one command that
    exits non-zero on the only checkout this reading is ever printed for.
    """

    def update_command(self) -> str:
        return f"git merge {self.tracked}"

    def subject(self) -> str:
        return "base"


class BaseFreshness(BaseModel, frozen=True):
    """What the remote says about a checkout: its own branch, and its base.

    Two readings rather than one, because which of them a checkout happens to
    have says nothing about which one a reader wants. Asking only the first
    ref that resolves answers "am I behind my own push" wherever a branch has
    been pushed and "has my base moved" wherever it has not — so the same
    gate called a base three commits gone current, and offered a base
    forty-one commits gone a pull that cannot run there.
    """

    upstream: UpstreamMeasure | None = None
    """The branch's own remote, when it tracks one."""

    base: BaseMeasure | None = None
    """The remote of the base recorded at worktree creation, when one was."""

    unreachable: str = ""
    """Why the remote could not be asked; empty when it answered."""

    def measures(self) -> list[RemoteMeasure]:
        """Every reading taken, in the order a report names them."""
        return [reading for reading in (self.upstream, self.base) if reading]

    def stale(self) -> bool:
        """Whether either remote is known to hold commits this checkout does not."""
        return any(reading.stale() for reading in self.measures())

    def unanswered(self) -> bool:
        """Whether a remote was asked and did not answer.

        The reading a caller has to tell apart from a clean one, because
        every other question here answers the same for both: no measure was
        taken, so nothing is behind, so nothing is stale. What separates
        them is not the count but whether there is one.

        Having nothing to ask is not this. A checkout that answers to no
        remote branch has no base that could have moved out from under it,
        where one whose fetch was refused has exactly the base it had before
        asking and no idea whether it still stands.
        """
        return bool(self.unreachable)

    def report(self) -> str:
        """Every reading on its own line, or the one reason there are none.

        An unknown answer says so rather than reading as a clean bill: a
        checkout that could not reach its remote knows exactly as much about
        its base as it did before asking.
        """
        if self.unreachable:
            return f"base freshness unknown: {self.unreachable}"
        return "\n".join(reading.report() for reading in self.measures()) or (
            "base freshness unknown: this checkout answers to no remote branch"
        )


def git_line(launcher: ProcessLauncher, root: Path, arguments: list[str]) -> str:
    """One git probe's single line of output, empty when it had nothing to say.

    The freshness probe runs through the launcher seam rather than this
    module's own bound git, because one of its steps reaches the network: a
    launcher merges the non-interactive environment every agent spawn point
    uses over the console's, so a credential nobody can supply fails fast
    instead of waiting on a terminal prompt. Each of these probes answers a
    question that has a blank answer — no upstream, no recorded base, no
    branch — so a failure and empty output mean the same thing here.
    """
    status = launcher.launch(
        LaunchRequest(
            arguments=["git", *arguments],
            cwd=root,
            environment=non_interactive_environment({}),
        )
    )
    lines = status.stdout.splitlines()
    return lines[0].strip() if status.code == 0 and lines else ""


def upstream_of(launcher: ProcessLauncher, root: Path, branch: str) -> str:
    """The remote branch a local branch tracks, empty when it tracks none.

    An empty ``branch`` asks about whichever is checked out, which is how a
    detached HEAD answers nothing at all rather than answering for the commit
    it happens to sit on.
    """
    return git_line(
        launcher,
        root,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{branch}@{{upstream}}"],
    )


class TrackedRemotes(BaseModel, frozen=True):
    """Which remote branches a checkout answers to; either may be absent.

    A feature worktree tracks nothing until it is pushed, so the base
    recorded when it was created is asked what *it* tracks — which is how a
    worktree cut from an integration branch is measured against that branch
    on the remote. Both are asked rather than whichever resolves first,
    because they answer different questions and a checkout having one is no
    reason to stop asking the other.
    """

    upstream: str = ""
    """The branch's own remote, when it tracks one."""

    base: str = ""
    """The remote of the base recorded at worktree creation, when one was."""

    def named(self) -> bool:
        """Whether there is any remote here to measure against."""
        return bool(self.upstream or self.base)

    def counted(self, launcher: ProcessLauncher, root: Path) -> BaseFreshness:
        """How far this checkout sits behind each, off refs already fetched.

        Separate from fetching so that a caller which has just moved HEAD can
        re-read the counts without paying for the network a second time.
        """

        def behind(tracked: str) -> int | None:
            answer = git_line(
                launcher, root, ["rev-list", "--count", f"HEAD..{tracked}"]
            )
            return int(answer) if answer.isdigit() else None

        own = behind(self.upstream) if self.upstream else 0
        cut = behind(self.base) if self.base else 0
        if own is None or cut is None:
            return BaseFreshness(
                unreachable=f"git did not count {self.upstream if own is None else self.base}"
            )
        return BaseFreshness(
            upstream=UpstreamMeasure(tracked=self.upstream, behind=own)
            if self.upstream
            else None,
            base=BaseMeasure(tracked=self.base, behind=cut) if self.base else None,
        )


def tracked_remotes(launcher: ProcessLauncher, root: Path) -> TrackedRemotes:
    """Ask git which remote branches this checkout answers to."""
    branch = git_line(launcher, root, ["branch", "--show-current"])
    recorded = (
        git_line(launcher, root, ["config", "--get", base_config_key(branch)])
        if branch
        else ""
    )
    return TrackedRemotes(
        upstream=upstream_of(launcher, root, ""),
        base=upstream_of(launcher, root, recorded) if recorded else "",
    )


def probe_base_freshness(launcher: ProcessLauncher, root: Path) -> BaseFreshness:
    """Fetch, then count what each remote holds and this checkout does not.

    A tree whose base has moved is self-consistent and says nothing about it,
    so only the remote can answer the question — one fetch, then a count per
    ref found. A remote that cannot be reached leaves the answer unknown
    rather than guessing it either way.

    A refusal is asked about again before it is reported, because the fetch
    runs where nothing may prompt and git's own account of that is the least
    useful true thing there is to say: it names the key it was refused for,
    never the one to load. The credential probe knows which identity ssh
    would offer this destination, so where it identifies one that answer
    replaces git's — the same event, re-asked by something that can name the
    way out of it. Where it identifies nothing, git keeps the floor: the
    probe is a second command and can disagree with the first about whether
    the host was reachable at all.
    """
    remotes = tracked_remotes(launcher, root)
    if not remotes.named():
        return BaseFreshness()
    fetched = launcher.launch(
        LaunchRequest(
            arguments=["git", "fetch", "--quiet"],
            cwd=root,
            environment=non_interactive_environment({}),
            stream=True,
        )
    )
    if fetched.code != 0:
        # `ls-remote --get-url` expands `url.<base>.insteadOf` and contacts
        # nothing, so what is probed is the URL the fetch above actually
        # reached rather than the one written in the config beside it.
        origin = git_line(launcher, root, ["ls-remote", "--get-url", "origin"])
        return BaseFreshness(
            unreachable=remote_auth_refusal(origin).diagnoses()
            or fetched.stderr.strip()
            or f"`git fetch` exited {fetched.code}",
        )
    return remotes.counted(launcher, root)


def git_ran(launcher: ProcessLauncher, root: Path, arguments: list[str]) -> str:
    """Run one git command through the same seam, answering with its complaint.

    Empty means it worked. The probes beside this one ask questions with a
    blank answer, where a failure and no output mean the same thing; a
    command run for its effect has to say which of the two happened.

    Shown as it runs, because these are the ones with a network or a hook at
    the other end: working through a slow transfer and having stopped look
    identical from a terminal that is told nothing until the exit. What comes
    back is that exit rather than the stderr already on screen, so a caller
    framing this answer in a line of its own does not print it twice.
    """
    status = launcher.launch(
        LaunchRequest(
            arguments=["git", *arguments],
            cwd=root,
            environment=non_interactive_environment({}),
            stream=True,
        )
    )
    if not status.code:
        return ""
    return f"`git {' '.join(arguments)}` exited {status.code}"


def sync_upstream(
    launcher: ProcessLauncher, root: Path, measure: UpstreamMeasure, *, publish: bool
) -> Iterator[str]:
    """Take what the branch's own remote holds, and say what it still lacks.

    Taking is what a reader would have done by hand and cannot go wrong
    quietly: ``--ff-only`` cannot invent a merge. What makes it safe to do
    unattended is the clean tree, so a checkout with work in it is left
    exactly as it was — the mistake this prevents is smaller than the one it
    would risk.

    Handing back is ``publish``, and happens only where a caller asked for
    it. The two directions read as symmetrical and are not: a pull changes
    this checkout, where a push publishes commits under somebody's name and
    runs whatever the local and remote hooks run — minutes of it, on the
    hook side, with nothing to say it started. A caller that means to push
    says so; one that only wants the checkout current is told the count
    instead and can push it itself. A diverged branch stops after the failed
    pull either way, rather than pushing on top of the divergence it just
    failed to close.
    """
    if git_line(launcher, root, ["status", "--porcelain"]):
        yield f"not synced with {measure.tracked}: the working tree has changes"
        return
    if measure.behind:
        complaint = git_ran(launcher, root, ["pull", "--ff-only"])
        if complaint:
            yield f"not synced with {measure.tracked}: {complaint}"
            return
        yield f"pulled {measure.behind} commit(s) from {measure.tracked}"
    ahead = git_line(
        launcher, root, ["rev-list", "--count", f"{measure.tracked}..HEAD"]
    )
    if not ahead.isdigit() or not int(ahead):
        return
    if not publish:
        yield f"{ahead} commit(s) {measure.tracked} does not have; `git push` sends them"
        return
    complaint = git_ran(launcher, root, ["push"])
    yield (
        f"not pushed to {measure.tracked}: {complaint}"
        if complaint
        else f"pushed {ahead} commit(s) to {measure.tracked}"
    )


def settle_base_freshness(
    launcher: ProcessLauncher, root: Path, *, publish: bool = False
) -> None:
    """Make the checkout current where that is free, and report what is left.

    Being behind is not grounds for refusing a session. A clean checkout is
    brought level with its own remote, which costs nothing and heads off the
    divergence that comes of committing onto a branch the remote has moved
    past; a base that has moved needs a merge, so it is named along with the
    merge that would take it and the session opens either way.

    Free is what decides it, which is why ``publish`` is off unless asked
    for. Taking commits costs a fetch nobody has to think about; handing
    them back costs whatever the hooks on either side cost and puts this
    checkout's work somewhere it can be read, neither of which is a price to
    charge somebody who typed a command about opening a session.

    Being unable to read the base at all is the one part that does put a
    question to whoever is there. A session opened on an unread base is the
    mistake this whole reading exists to prevent, and a line of output does
    not prevent it: the one that reported this arrived under four lines
    saying ready, in the shape of the status lines around it, a moment
    before the terminal was handed to something that draws over all of them.
    """
    # Said before the fetch rather than after it, because this is the first
    # thing here that waits on somebody else's machine, and a line naming the
    # wait is what separates a slow one from a stopped one.
    typer.echo("reading what the remote holds")
    freshness = probe_base_freshness(launcher, root)
    synced = (
        list(sync_upstream(launcher, root, freshness.upstream, publish=publish))
        if freshness.upstream
        else []
    )
    for line in synced:
        typer.echo(line)
    if synced:
        # A pull moves HEAD, which is what the base is measured from, so the
        # counts are re-read — off the refs the probe has already fetched.
        freshness = tracked_remotes(launcher, root).counted(launcher, root)
    typer.echo(freshness.report())
    if freshness.unanswered():
        admit_an_unread_base()


def admit_an_unread_base() -> None:
    """Put an unread base to whoever is at the terminal; open anyway when nobody is.

    Asked rather than refused, because a base that cannot be read is not the
    same as one that has moved, and offline is a way of working rather than
    a fault: the answer belongs to the person who knows which of the two
    they are in. Asked rather than printed, because the alternative was
    tried and is what brought this here.

    Only where somebody can answer. The refusal that used to stand in this
    module fell on exactly the scripted sessions nobody was watching, and a
    prompt on an absent terminal is that refusal wearing a question mark —
    `typer.confirm` reads end-of-file as an abort. So a session with nobody
    in front of it says what it is doing and opens.
    """
    if not sys.stdin.isatty():
        typer.echo("nobody is here to answer, so the session opens on it unread")
        return
    if not typer.confirm("Open the session on a base nothing could read?"):
        raise typer.Abort()


def require_fresh_base(freshness: BaseFreshness) -> None:
    """Refuse to start work that pins this base for everything it hands out.

    A run captures its base once and cuts every lease from it, so following a
    base that has already moved means re-basing each lease, re-deriving each
    diff against the new base, and re-running intake — which can add or drop
    concerns while work is in flight. Refusing before any of that exists
    costs a fetch; discovering it afterwards costs the run.

    A base nothing could read is refused on the same terms rather than
    passed. The session launchers ask about one, because a person is sitting
    in front of them and offline is a way of working; here there is nobody to
    ask and nothing to gain by guessing — a run that pins an unread base has
    committed every lease it will cut to a guess, and it finds out whether
    the guess held at the point where the answer costs the run.
    """
    typer.echo(freshness.report())
    if freshness.stale():
        raise typer.BadParameter(freshness.report())
    if freshness.unanswered():
        raise typer.BadParameter(
            "a run pins one base for every lease it cuts, so it does not start "
            "on a base nothing could read"
        )


# -- CLI functions --


def branch_status(branch: str | None, as_json: bool) -> None:
    """Analyze branch containment, PR status, and worktree info."""
    has_remote = check_remote_auth()

    integration = get_integration_branch()
    current = git.out("branch", "--show-current")

    branch_list = (
        [branch] if branch else git.lines("branch", "--format=%(refname:short)")
    )

    results = [
        classify_branch(b, integration, current, has_remote=has_remote)
        for b in branch_list
    ]

    if as_json:
        output_json(results)
        return

    typer.echo(f"\nIntegration branch: {integration}")
    typer.echo(f"Current branch: {current}\n")
    status_markers: dict[BranchStatus, str] = {
        "LAND": "^",
        "DELETE": "x",
        "STALE": "~",
        "KEEP": " ",
        "CURRENT": "*",
        "NOT_FOUND": "?",
    }

    def row(r: BranchClassification) -> list[str]:
        marker = status_markers[r["status"]]
        wt = " [worktree]" if r.get("worktree") else ""
        return [f"[{marker}] {r['branch']}", r["status"], f"{r['reason']}{wt}"]

    typer.echo(format_table(("Branch", "Status", "Reason"), [row(r) for r in results]))

    typer.echo()
    deletable = [r for r in results if r["status"] in ("DELETE", "STALE")]
    if deletable:
        typer.echo(f"{len(deletable)} branch(es) can be cleaned up")

    landable = [r for r in results if r["status"] == "LAND"]
    if landable:
        typer.echo(f"{len(landable)} branch(es) hold unlanded work")


def base_branch(branch: str | None, as_json: bool) -> None:
    """Detect the base branch for the current (or specified) branch."""
    base = detect_base_branch(branch)
    effective = branch or git.out("branch", "--show-current")

    if as_json:
        output_json(
            {
                "branch": effective,
                "base": base.name,
                "merge_base": base.merge_base,
                "commits_ahead": base.distance,
            }
        )
    else:
        typer.echo(f"Branch: {effective}")
        typer.echo(f"Base: {base.name}")
        typer.echo(f"Merge base: {short_sha(base.merge_base)}")
        typer.echo(f"Commits ahead: {base.distance}")


COMMIT_PREFIX_LABELS = {
    "feat": "Added",
    "fix": "Fixed",
    "refactor": "Refactored",
    "docs": "Updated docs for",
    "test": "Added tests for",
    "chore": "Updated",
    "meta": "Updated",
    "data": "Added data for",
}
"""How a PR body reads each commit type aloud, for a project that uses these.

The types are one convention among several, and the English is a second
choice on top: a project spelling either differently passes its own table
rather than reading someone else's vocabulary back in its summaries.
"""


def pr_body(
    base_override: str | None,
    # Open keys: a prefix is whatever a commit subject happens to start with,
    # read off the log rather than chosen from a set this code knows.
    labels: StringMap = COMMIT_PREFIX_LABELS,
) -> None:
    """Generate a PR body from the current branch's commits against its base."""
    base = base_override or detect_base_branch().name

    log_lines = git.lines(
        "log",
        "--oneline",
        "--no-decorate",
        "--no-merges",
        f"{base}..HEAD",
        _ok_code=[0],
    )
    if not log_lines:
        typer.echo("No commits found since base branch", err=True)
        raise typer.Exit(1)

    groups: dict[str, list[str]] = defaultdict(list)
    for line in log_lines:
        message = line.partition(" ")[2]  # lup: ignore[string-split] — log line
        if not message:
            continue
        head = message.partition("(")[0]  # lup: ignore[string-split] — commit type
        prefix = head.partition(":")[0].lower()  # lup: ignore[string-split] — type
        groups[prefix].append(message)

    def summarize(prefix: str, messages: list[str]) -> str:
        fallback = prefix.capitalize()
        label = labels.get(prefix, fallback)
        first = messages[0].partition(":")[2]  # lup: ignore[string-split] — log line
        desc = (first or messages[0]).lstrip()
        more = f" (+{len(messages) - 1} more)" if len(messages) > 1 else ""
        return f"- {label} {desc}{more}"

    summary_lines = [summarize(p, msgs) for p, msgs in groups.items()]
    body_parts = ["## Summary", *summary_lines, "", "## Commits", *log_lines]
    body_parts.extend(["", "## Test plan", "- [ ] Verify changes work as expected"])

    typer.echo("\n".join(body_parts))


def survey(as_json: bool) -> None:
    """Collect branch, worktree, PR, and containment data."""
    has_remote = check_remote_auth()
    if has_remote:
        if not as_json:
            typer.echo("Fetching and pruning remote...", err=True)
        try:
            fetch_remote_tracking()
        except sh.ErrorReturnCode as e:
            logger.warning("Failed to fetch: %s", decode_stderr(e))

    integration = get_integration_branch()
    cur = git.out("branch", "--show-current")

    raw_branches = parse_branches()
    worktrees = parse_worktrees()
    branch_names = [b["name"] for b in raw_branches]
    containment = build_containment(branch_names)
    # A branch the remote still carries after its local copy is gone is the
    # one shape a local sweep cannot express: nothing in refs/heads names
    # it, so no row is emitted and no verb is owed, and the next sweep is
    # blind in exactly the same way. Matched by name, which is what a local
    # branch and its counterpart on the remote share.
    local_names = {b["name"] for b in raw_branches}
    remote_rows = parse_remote_branches() if has_remote else []
    remote_only = [row for row in remote_rows if row["name"] not in local_names]

    if has_remote and not as_json:
        typer.echo("Querying PR status...", err=True)
    pr_named = branch_names + [row["name"] for row in remote_only]
    pr_map: dict[str, PRStatus] = fetch_pr_status(pr_named) if has_remote else {}
    leased = leased_on_disk(
        live_lease_branches(project_root() / ".lup" / "resolve"), branch_names
    )

    def info(b: ParsedBranch) -> BranchInfo:
        name = b["name"]
        checkout = worktrees.get(name)
        contained_in = containment[name]
        pr_merged = name in pr_map and pr_map[name].state == "MERGED"

        related = name == integration or shares_history(name, integration)
        if integration in contained_in or pr_merged or not related:
            # An unrelated branch reports both figures from comparisons that
            # needed no merge base, so they measure distance between trees
            # rather than divergence. Left at zero rather than shown wrong.
            unique = 0
            diff_lines = 0
        else:
            unique = count_unique_commits(name, integration)
            diff_lines = count_source_diff_lines(name, integration)

        verdict = disposition_for(
            name,
            integration=integration,
            current=cur,
            contained_in=contained_in,
            pr=pr_map.get(name),
            unique_commits=unique,
            held=leased[name].reason() if name in leased else "",
            related=related,
            never_diverged=never_diverged_from(name, integration),
            worktree=checkout,
        )

        return BranchInfo(
            name=name,
            commit=b["commit"],
            tracking=b["tracking"],
            worktree=checkout,
            is_current=b["is_current"],
            contained_in=contained_in,
            pr=pr_map.get(name),
            unique_commits=unique,
            source_diff_lines=diff_lines,
            disposition=verdict.status,
            reason=verdict.reason,
            rewritten=len(rewrite_suspects(name, integration)) if unique else 0,
            changes=worktree_changes(checkout) if checkout else None,
        )

    def remote_info(row: ParsedRemoteBranch) -> RemoteBranchInfo:
        """Resolve one remote-only branch through the same classifier.

        Reusing ``disposition_for`` is the point rather than a convenience:
        a second verb table for remote branches would answer the same
        question a little differently the first time either changed. What a
        ref on a remote cannot have — a worktree, a lease, being the current
        branch — is left at the defaults that say so.
        """
        name = row["name"]
        ref = f"{row['remote']}/{name}"
        related = shares_history(ref, integration)
        contained = related and is_ancestor(ref, integration)
        unique = (
            0 if contained or not related else count_unique_commits(ref, integration)
        )
        verdict = disposition_for(
            name,
            integration=integration,
            current=cur,
            contained_in=[integration] if contained else [],
            pr=pr_map.get(name),
            unique_commits=unique,
            related=related,
        )
        return RemoteBranchInfo(
            name=name,
            remote=row["remote"],
            commit=row["commit"],
            contained_in_integration=contained,
            pr=pr_map.get(name),
            unique_commits=unique,
            disposition=verdict.status,
            reason=verdict.reason,
        )

    branches_list = [info(b) for b in raw_branches]
    remote_list = [remote_info(row) for row in remote_only]

    result = SurveyResult(
        integration_branch=integration,
        current_branch=cur,
        branches=branches_list,
        runs=runs_holding(leased),
        remote_branches=remote_list,
    )

    if as_json:
        output_json(result)
    else:
        typer.echo(f"\nIntegration: {integration} | Current: {cur}\n")

        def display_row(bi: BranchInfo) -> list[str]:
            pr_str = f"#{bi.pr.number} {bi.pr.state}" if bi.pr else "-"
            marker = "* " if bi.is_current else "  "
            return [
                f"{marker}{bi.name}",
                bi.disposition,
                str(bi.unique_commits),
                f"{bi.rewritten}?" if bi.rewritten else "-",
                str(bi.source_diff_lines),
                bi.changes.compact() if bi.changes else "-",
                pr_str,
                bi.reason,
            ]

        headers = (
            "Branch",
            "Disposition",
            "Unique",
            "Rewr",
            "Diff",
            "Dirt",
            "PR",
            "Reason",
        )
        typer.echo(format_table(headers, [display_row(bi) for bi in branches_list]))

        if result.remote_branches:
            typer.echo("\nOn the remote, with no local branch:\n")

            def remote_row(rb: RemoteBranchInfo) -> list[str]:
                pr_str = f"#{rb.pr.number} {rb.pr.state}" if rb.pr else "-"
                return [
                    rb.qualified(),
                    rb.disposition,
                    str(rb.unique_commits),
                    pr_str,
                    rb.reason,
                ]

            typer.echo(
                format_table(
                    ("Remote branch", "Disposition", "Unique", "PR", "Reason"),
                    [remote_row(rb) for rb in result.remote_branches],
                )
            )

        for hold in result.runs:
            if not hold.alive:
                typer.echo(
                    f"\nrun {hold.run_id} is not running and holds "
                    f"{len(hold.branches)} branch(es): nothing will retire them.\n"
                    f"  uv run lup-devtools harness resolve status "
                    f"--run-id {hold.run_id}"
                )


type ActionVerdict = Literal["ok", "forced", "blocked"]


class PlannedAction(BaseModel):
    """One step of a deletion, carrying the verdict a preflight probe gave it.

    ``detail`` says what forcing would discard, or why the step cannot run —
    the annotation is a probe result, never a restatement of the flag.
    """

    description: str
    verdict: ActionVerdict = "ok"
    detail: str = ""

    def render(self) -> str:
        match self.verdict:
            case "ok":
                return f"{self.description} (ok)"
            case "forced":
                return f"{self.description} (force: {self.detail})"
            case "blocked":
                return f"{self.description} (blocked: {self.detail})"


class DeletionPlan(BaseModel):
    """Every step a deletion would take, evaluated without mutating anything."""

    branch: str
    worktree: str | None = None
    stranded: bool = False
    has_remote: bool = False
    delete_remote: bool = False
    """Whether origin's copy goes too, which is a decision, not an observation.

    ``has_remote`` is a fact about the world and this is an intention about
    it. Reading both from one field is what made a remote copy delete itself
    for existing — and a copy that exists is the thing that made deleting
    the local branch survivable in the first place.
    """
    left_upstream_behind: bool = False
    """Whether ``-d`` will refuse over an upstream the branch has outgrown.

    Deleting it is still safe: the branch step reached this only because HEAD
    contains every commit. But git judges a tracking branch against its
    upstream rather than against HEAD, so the plain delete refuses — and it
    refuses at run time, after the worktree removal ahead of it has already
    happened, which is how a preflight promising that a refusal changes
    nothing came to leave a checkout gone and a remote branch orphaned.
    Recorded so the plan predicts what the run will meet.
    """
    actions: list[PlannedAction] = []

    def blocked(self) -> list[PlannedAction]:
        return [action for action in self.actions if action.verdict == "blocked"]


def worktree_changes(path: str) -> WorktreeChanges:
    """Count what a worktree holds, so a report can say what force discards."""
    modified = 0
    untracked = 0
    for line in git.lines("-C", path, "status", "--porcelain"):
        if line.startswith("??"):
            untracked += 1
        else:
            modified += 1
    return WorktreeChanges(modified=modified, untracked=untracked)


def remote_branch_exists(name: str) -> bool:
    """Report whether ``origin`` still carries the branch."""
    try:
        git("rev-parse", "--verify", f"refs/remotes/origin/{name}")
        return True
    except sh.ErrorReturnCode:
        return False


def upstream_ref(name: str) -> str | None:
    """The remote-tracking ref this branch is set to follow, if it has one."""
    try:
        return (
            git.out("rev-parse", "--symbolic-full-name", f"{name}@{{upstream}}").strip()
            or None
        )
    except sh.ErrorReturnCode:
        return None


def outgrew_upstream(name: str) -> bool:
    """Whether the branch holds commits the upstream it tracks does not.

    The question ``git branch -d`` actually asks of a tracking branch, and
    the reason it refuses one every commit of which is already in HEAD. A
    worktree is given an upstream the moment it is created, so this is the
    ordinary shape of a branch that landed by a merge into the integration
    branch rather than by a push of its own: the work is in, and the remote
    copy is simply behind.
    """
    upstream = upstream_ref(name)
    return upstream is not None and not is_ancestor(name, upstream)


def plan_worktree_step(path: str, stranded: bool, force: bool) -> PlannedAction:
    """Judge the worktree removal — the one irreversible step."""
    if stranded:
        return PlannedAction(
            description=f"Prune stranded worktree: {path}",
            detail="checkout already gone",
        )

    changes = worktree_changes(path)
    description = f"Remove worktree: {path}"
    if not changes.dirty():
        return PlannedAction(description=description)

    if force:
        return PlannedAction(
            description=description,
            verdict="forced",
            detail=f"discards {changes.summary()}",
        )
    return PlannedAction(
        description=description,
        verdict="blocked",
        detail=f"holds {changes.summary()}; --force discards them",
    )


def plan_branch_step(name: str, force: bool) -> PlannedAction:
    """Judge the branch deletion the way ``git branch -d`` would.

    Which is not merely whether HEAD contains it. A branch that tracks an
    upstream is judged against that upstream, so one whose every commit is
    already in the integration branch is still refused while its remote copy
    sits behind. Reporting that as forced rather than blocked is the honest
    reading: nothing is discarded, because HEAD holds all of it.
    """
    description = f"Delete local branch: {name}"
    if is_ancestor(name, "HEAD"):
        if outgrew_upstream(name):
            return PlannedAction(
                description=description,
                verdict="forced",
                detail=f"ahead of origin/{name}, which HEAD already contains",
            )
        return PlannedAction(description=description)
    if force:
        return PlannedAction(
            description=description, verdict="forced", detail="branch is unmerged"
        )
    return PlannedAction(
        description=description,
        verdict="blocked",
        detail="branch is unmerged; --force deletes it anyway",
    )


def dependent_pulls(name: str) -> list[int]:
    """Open PRs based on *name*, which deleting origin's copy would close.

    A stacked PR names its parent as its base, and GitHub closes a pull
    request whose base branch is deleted rather than moving it. Landing the
    parent and cleaning up after it is therefore enough to close the child,
    which is the ordinary end of the parent's life and no part of the
    child's — and the branch survives, so the closure reads as work lost
    until somebody recreates the base to reopen it.

    An unanswerable query is no dependents: this refines a deletion the
    caller already asked for, and a network failure is not a reason to
    refuse one.
    """
    try:
        rows = json.loads(
            gh.out(
                "pr",
                "list",
                *repository_arguments(),
                "--base",
                name,
                "--state",
                "open",
                "--json",
                "number",
            )
        )
    except sh.ErrorReturnCode as e:
        logger.warning(
            "Could not check for PRs based on %s: %s", name, decode_stderr(e)
        )
        return []
    return [PRStatus.model_validate(row).number for row in rows]


def plan_remote_step(name: str, force: bool) -> PlannedAction:
    """Judge deleting origin's copy by what else is still pointing at it."""
    description = f"Delete remote branch: origin/{name}"
    dependents = dependent_pulls(name)
    if not dependents:
        return PlannedAction(description=description)
    listed = ", ".join(f"#{number}" for number in dependents)
    if force:
        return PlannedAction(
            description=description,
            verdict="forced",
            detail=f"closes {listed}",
        )
    return PlannedAction(
        description=description,
        verdict="blocked",
        detail=(
            f"{listed} targets this branch and would be closed; "
            "retarget it first, or --force to close it anyway"
        ),
    )


def plan_deletion(name: str, force: bool, remote: bool | None = None) -> DeletionPlan:
    """Evaluate every precondition a deletion depends on, changing nothing.

    A dry run and the real path both read this, so what the dry run promises
    is what the real path went on to check.

    Whether origin's copy goes with it defaults to whether the branch is
    merged, because that is what the answer turns on. Cleaning up after a
    merged branch should take the remote too — the commits are in the
    integration branch and the copy is spent. An unmerged branch is the
    opposite case: origin holds the only copy that outlives this command,
    which is exactly what a push before deleting was for, so it stays
    unless a caller says otherwise in so many words.
    """
    worktree = parse_worktrees().get(name)
    stranded = worktree is not None and not Path(worktree).exists()
    actions: list[PlannedAction] = []

    if worktree is not None:
        actions.append(plan_worktree_step(worktree, stranded=stranded, force=force))

    actions.append(plan_branch_step(name, force=force))

    merged = is_ancestor(name, "HEAD")
    left_upstream_behind = merged and outgrew_upstream(name)
    has_remote = remote_branch_exists(name)
    delete_remote = has_remote and (merged if remote is None else remote)
    if delete_remote:
        actions.append(plan_remote_step(name, force=force))

    return DeletionPlan(
        branch=name,
        worktree=worktree,
        stranded=stranded,
        has_remote=has_remote,
        delete_remote=delete_remote,
        left_upstream_behind=left_upstream_behind,
        actions=actions,
    )


def abort_deletion(plan: DeletionPlan, completed: list[str], failure: str) -> NoReturn:
    """Report a mid-deletion failure, repairing a stranded registration first.

    ``git worktree remove`` clears the checkout before it unregisters, so a
    failure here can leave a worktree git still believes in. Pruning is the
    repair, and the caller cannot be expected to know that.

    Prune, removal, and the branch deletion itself all take the config lock,
    so all three fail alike where the sandbox holds it — and there the repair
    is not a repair, because the prune it prescribes fails the same way. The
    mount state is what says which of the two failures this is.
    """
    typer.echo(f"Failed to delete {plan.branch}: {failure}", err=True)

    diagnosis = config_lock_diagnosis()
    if diagnosis:
        typer.echo(diagnosis, err=True)
    elif plan.worktree is not None and not Path(plan.worktree).exists():
        try:
            git("worktree", "prune")
            typer.echo(
                f"Pruned the stranded registration for {plan.worktree}", err=True
            )
        except sh.ErrorReturnCode as error:
            typer.echo(
                f"The checkout at {plan.worktree} is gone but still registered. "
                f"Recover with `git worktree prune`: {decode_stderr(error)}",
                err=True,
            )

    typer.echo(f"Completed first: {', '.join(completed) or 'nothing'}", err=True)
    raise typer.Exit(1)


def run_deletion(plan: DeletionPlan, force: bool) -> None:
    """Carry out a plan whose preflight passed, reporting what actually ran."""
    completed: list[str] = []

    if plan.stranded:
        try:
            git("worktree", "prune")
            typer.echo(f"Pruned stranded worktree: {plan.worktree}")
            completed.append("pruned worktree")
        except sh.ErrorReturnCode as error:
            abort_deletion(plan, completed, f"prune failed: {decode_stderr(error)}")
    elif plan.worktree is not None:
        try:
            git("worktree", "remove", *(["--force"] if force else []), plan.worktree)
            typer.echo(f"Removed worktree: {plan.worktree}")
            completed.append("removed worktree")
        except sh.ErrorReturnCode as error:
            abort_deletion(
                plan, completed, f"worktree removal failed: {decode_stderr(error)}"
            )

    try:
        git("branch", "-D" if force or plan.left_upstream_behind else "-d", plan.branch)
        typer.echo(f"Deleted branch: {plan.branch}")
        completed.append("deleted branch")
    except sh.ErrorReturnCode as error:
        abort_deletion(
            plan, completed, f"branch deletion failed: {decode_stderr(error)}"
        )

    if not plan.delete_remote:
        if plan.has_remote:
            typer.echo(
                f"Kept remote branch: origin/{plan.branch} — it holds these "
                "commits now (--remote deletes it too)"
            )
        return

    try:
        git("push", "origin", "--delete", plan.branch)
        typer.echo(f"Deleted remote branch: origin/{plan.branch}")
    except sh.ErrorReturnCode as error:
        typer.echo(f"Warning: remote deletion failed: {decode_stderr(error)}", err=True)


def delete_branch(
    name: str,
    dry_run: bool,
    force: bool,
    remote: bool | None = None,
    preserved: str = "",
) -> None:
    """Delete a branch and its worktree, and origin's copy if it is spent.

    ``preserved`` names the ref a caller has already parked the commits at,
    for the one path — :func:`run_retirement` — that preserves them before
    deleting. Empty means nobody has, which is the case the warning below is
    written for.
    """
    cur = git.out("branch", "--show-current")
    if name == cur:
        typer.echo(f"Error: cannot delete the current branch ({name})", err=True)
        raise typer.Exit(1)

    plan = plan_deletion(name, force, remote)

    if dry_run:
        typer.echo(f"Would perform {len(plan.actions)} action(s):")
        for action in plan.actions:
            typer.echo(f"  {action.render()}")
        typer.echo(f"  {traces.archive(name, dry_run=True).summary()}")
        return

    blocked = plan.blocked()
    if blocked:
        typer.echo(f"Refusing to delete {name} — nothing was changed:", err=True)
        for action in blocked:
            typer.echo(f"  {action.render()}", err=True)
        typer.echo("Use --force to override.", err=True)
        raise typer.Exit(1)

    if plan.delete_remote and not is_ancestor(name, "HEAD") and not preserved:
        typer.echo(
            f"Warning: {name} holds commits HEAD does not, and origin/{name} "
            "is going with it — after this the work is in no branch. To keep "
            f"it, `dev retire {name} --reason ...` closes a pull request over "
            "it first, which preserves the commits past the deletion.",
            err=True,
        )

    # Before the worktree goes, not after: its trace store is usually the only
    # copy, and every later reader would see absence rather than loss.
    traces.keep_before_deleting(name)
    run_deletion(plan, force)


class RetirementPlan(BaseModel):
    """Every step retiring a branch takes, evaluated without mutating anything.

    Retiring is deleting a branch whose work is *not* wanted, without losing
    the work. The two are usually the same act and must not be: a branch the
    integration branch never absorbed, deleted with no copy on the remote,
    leaves its commits reachable from nothing and a collector free to take
    them. `dev delete` says so at the moment it happens, which is too late to
    be a choice.

    A pull request is the durable copy. GitHub writes the head of every one
    it has ever seen to ``refs/pull/<number>/head`` and keeps it there
    whether the request merged, and whether the branch behind it still
    exists — so a request opened and closed over work nobody wants outlives
    both the branch and the remote copy, and carries the reason beside the
    commits rather than in a session nobody will read again.
    """

    branch: str
    integration: str
    unique_commits: int
    subjects: list[str] = []
    """``<short sha> <subject>`` per commit the integration branch lacks."""
    pull_request: int | None = None
    """An existing request for this branch, reused rather than duplicated."""
    actions: list[PlannedAction] = []

    def blocked(self) -> list[PlannedAction]:
        return [action for action in self.actions if action.verdict == "blocked"]

    def body(self, reason: str, number: int) -> str:
        """The record the pull request exists to keep.

        Written after the number is known, because the recovery line is the
        one thing a reader arriving here needs and a command they have to
        assemble themselves is one they will get wrong.
        """
        listed = "\n".join(f"- `{subject}`" for subject in self.subjects)
        return f"""**This pull request exists to be closed, not merged.**

Retiring `{self.branch}`: {reason}

Its commits stay reachable after the branch is deleted. GitHub keeps a closed
request's head as `refs/pull/{number}/head` whether or not the branch behind it
still exists, where a deleted branch with no remote copy becomes unreachable and
is collected.

Recover the work with:

```bash
git fetch origin refs/pull/{number}/head:{self.branch}
```

## What it held

{self.unique_commits} commit(s) `{self.integration}` does not carry:

{listed}
"""


def unique_subjects(branch: str, integration: str) -> list[str]:
    """Each commit the integration branch lacks, as sha and subject.

    By ancestry, not by the ``--cherry-pick`` filter the survey counts with,
    because the two are wrong in opposite directions and only one of them is
    survivable here. This decides whether there is anything to preserve, so
    a false *yes* costs a pull request nobody needed and a false *no* sends
    the caller to `dev delete` over work that had no other copy.
    """
    return [
        line
        for line in git.lines(
            "log", "--format=%h %s", "--no-merges", f"{integration}..{branch}"
        )
        if line
    ]


def plan_retirement(name: str, integration: str) -> RetirementPlan:
    """Evaluate every step a retirement depends on, changing nothing."""
    from lup.devtools.dev.worktree import branch_exists

    actions: list[PlannedAction] = []
    if not branch_exists(name):
        actions.append(
            PlannedAction(
                description=f"Retire {name}",
                verdict="blocked",
                detail="no such local branch",
            )
        )
        return RetirementPlan(
            branch=name, integration=integration, unique_commits=0, actions=actions
        )

    subjects = unique_subjects(name, integration)
    existing = get_pr_info(name)
    reused = existing.number if existing is not None and existing.reusable() else None

    actions.append(PlannedAction(description=f"Push {name} to origin"))
    if reused is None:
        actions.append(
            PlannedAction(description=f"Open a pull request onto {integration}")
        )
    else:
        actions.append(
            PlannedAction(
                description=f"Reuse pull request #{reused}",
                detail="already open for this branch",
            )
        )
    actions.append(PlannedAction(description="Close it without merging"))
    actions.append(PlannedAction(description=f"Delete {name}, locally and on origin"))

    return RetirementPlan(
        branch=name,
        integration=integration,
        unique_commits=len(subjects),
        subjects=subjects,
        pull_request=reused,
        actions=actions,
    )


def run_retirement(plan: RetirementPlan, reason: str) -> int:
    """Carry out a plan whose preflight passed, returning the request's number.

    Ordered so nothing is destroyed before the copy that replaces it exists:
    the push, then the request, then the close, and only then the deletion.
    A failure at any step leaves the branch where it was.
    """
    try:
        git("push", "--force-with-lease", "origin", f"{plan.branch}:{plan.branch}")
        typer.echo(f"Pushed {plan.branch} to origin")
    except sh.ErrorReturnCode as error:
        typer.echo(f"Could not push {plan.branch}: {decode_stderr(error)}", err=True)
        raise typer.Exit(1)

    number = plan.pull_request
    if number is None:
        try:
            raw = gh.out(
                "pr",
                "create",
                *repository_arguments(),
                "--base",
                plan.integration,
                "--head",
                plan.branch,
                "--title",
                f"retire: {plan.branch}",
                "--body",
                f"Retiring `{plan.branch}`: {reason}",
            )
        except sh.ErrorReturnCode as error:
            typer.echo(f"Could not open a request: {decode_stderr(error)}", err=True)
            raise typer.Exit(1)
        number = int(PurePosixPath(urlparse(raw.strip().splitlines()[-1]).path).name)
        typer.echo(f"Opened #{number}")

    try:
        gh(
            "pr",
            "edit",
            str(number),
            *repository_arguments(),
            "--body",
            plan.body(reason, number),
        )
    except sh.ErrorReturnCode as error:
        # The request carries the commits either way; only the note is missing.
        logger.warning("could not write the retirement note: %s", decode_stderr(error))

    try:
        gh(
            "pr",
            "close",
            str(number),
            *repository_arguments(),
            "--comment",
            f"Retired, not merged. Recover with "
            f"`git fetch origin refs/pull/{number}/head:{plan.branch}`.",
        )
        typer.echo(f"Closed #{number}")
    except sh.ErrorReturnCode as error:
        typer.echo(f"Could not close #{number}: {decode_stderr(error)}", err=True)
        raise typer.Exit(1)

    return number


def retire_branch(
    name: str,
    reason: str,
    dry_run: bool,
    integration: str | None = None,
) -> None:
    """Retire a branch through a pull request, so its commits outlive it."""
    target = integration if integration is not None else get_integration_branch()
    if name == git.out("branch", "--show-current"):
        typer.echo(f"Error: cannot retire the current branch ({name})", err=True)
        raise typer.Exit(1)

    plan = plan_retirement(name, target)

    if dry_run:
        typer.echo(f"Would perform {len(plan.actions)} action(s):")
        for action in plan.actions:
            typer.echo(f"  {action.render()}")
        if not plan.blocked():
            typer.echo(
                f"  Preserving {plan.unique_commits} commit(s) as refs/pull/<n>/head"
            )
        return

    blocked = plan.blocked()
    if blocked:
        typer.echo(f"Refusing to retire {name} — nothing was changed:", err=True)
        for action in blocked:
            typer.echo(f"  {action.render()}", err=True)
        raise typer.Exit(1)

    if not plan.unique_commits:
        typer.echo(
            f"{name} holds nothing {target} lacks — `dev delete` is enough, and "
            "no request is needed to preserve it.",
            err=True,
        )
        raise typer.Exit(1)

    number = run_retirement(plan, reason)
    delete_branch(
        name,
        dry_run=False,
        force=True,
        remote=True,
        preserved=f"refs/pull/{number}/head",
    )
    typer.echo(
        f"Retired {name}: recover with `git fetch origin refs/pull/{number}/head`"
    )


def create_resolve_branch(concern_id: str) -> None:
    """Create and switch to the `resolve/<id>` branch for a /lup:resolve editor.

    The execute workflow's editor calls this as its first step, through the
    allowlisted `uv run lup-devtools` path, instead of a raw `git checkout -b` —
    so the bash hook needs no editor special-case. The name is fixed to the
    `resolve/<slug>` convention the workflow's merge and cleanup rely on.
    """
    slug = concern_id.strip().strip("/")  # lup: ignore[string-strip] — typed-id hygiene
    ok = bool(slug) and slug[0].isalnum()
    ok = ok and all(c.isalnum() or c in "._-" for c in slug)
    if not ok:
        typer.echo(f"Invalid concern id: {concern_id!r}", err=True)
        raise typer.Exit(1)
    branch = f"resolve/{slug}"
    try:
        git("checkout", "-b", branch)
    except sh.ErrorReturnCode as e:
        typer.echo(f"Could not create {branch}: {decode_stderr(e)}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Created and switched to {branch}")
