"""Concrete lease, worktree, commit, and dependency-base orchestration."""

from pathlib import Path

from lup.codescan.symbols import DefinedSymbol, defined_symbols, symbols_lost
from lup.harness.process import ExitStatus, LaunchRequest, ProcessLauncher
from lup.resolver.contracts import WorktreePreparer
from lup.resolver.notes import clear_concern_notes
from lup.resolver.models import (
    Concern,
    DependencyBase,
    DiffValidation,
    DropCandidate,
    NoteClearanceCommit,
    SourceSnapshot,
    WorkerReport,
    WorktreeRemoval,
    WritableRootLease,
)


def report_mismatch(undeclared: list[str], unswept: list[str]) -> str:
    """Name exactly which paths a worker must reconcile to pass this gate.

    A revision round can only converge on something it can read. The prior
    wording named no path at all, so a worker re-derived the same report and
    failed identically until the round budget ran out.
    """
    return "; ".join(
        [
            *(
                [f"changed but not declared: {', '.join(undeclared)}"]
                if undeclared
                else []
            ),
            *(
                [f"declared swept but not changed: {', '.join(unswept)}"]
                if unswept
                else []
            ),
        ]
    )


class LeaseViolationError(RuntimeError):
    """A resolver attempted to share or escape a writable root."""


class WritableRootLeases:
    """Own non-overlapping writable roots for one resolver run."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.leases: dict[str, WritableRootLease] = {}

    def acquire(self, concern_id: str, branch: str) -> WritableRootLease:
        lease = self.plan(concern_id, branch)
        self.leases[concern_id] = lease
        return lease

    def plan(self, concern_id: str, branch: str) -> WritableRootLease:
        """Resolve one non-overlapping writable root without taking it.

        A concern admitted mid-run is checked against the roots this run
        already handed out before anything about the run is written, so an
        overlap is refused at the boundary rather than discovered by a
        worker editing another concern's tree.
        """
        if concern_id in self.leases and self.leases[concern_id].active:
            raise LeaseViolationError(f"concern {concern_id!r} already has a lease")
        candidate = (self.root / concern_id).resolve()
        if not candidate.is_relative_to(self.root):
            raise LeaseViolationError(f"lease root escapes resolver root: {candidate}")
        for existing in self.leases.values():
            if not existing.active:
                continue
            other = existing.root.resolve()
            if (
                candidate == other
                or candidate.is_relative_to(other)
                or other.is_relative_to(candidate)
            ):
                raise LeaseViolationError(
                    f"writable roots overlap for {concern_id!r} and "
                    f"{existing.concern_id!r}"
                )
        return WritableRootLease(
            concern_id=concern_id,
            root=candidate,
            branch=branch,
        )

    def adopt(self, leases: list[WritableRootLease]) -> None:
        """Take a run's persisted active leases as this process's authority.

        Every later acquisition is then checked against roots this run
        already handed out, which is what makes a lease acquired long after
        the first batch — for a concern admitted mid-run — refuse an overlap
        instead of quietly sharing a writable root.
        """
        self.leases = {lease.concern_id: lease for lease in leases if lease.active}

    def assert_path(self, concern_id: str, path: Path) -> None:
        try:
            lease = self.leases[concern_id]
        except KeyError as error:
            raise LeaseViolationError(f"unknown lease {concern_id!r}") from error
        candidate = path.resolve()
        if not lease.active or not candidate.is_relative_to(lease.root.resolve()):
            raise LeaseViolationError(
                f"{candidate} is outside the active lease for {concern_id!r}"
            )


class WorktreeOrchestrator:
    """Run only orchestrator-authorized worktree, diff, and commit operations."""

    def __init__(
        self,
        launcher: ProcessLauncher,
        workspace: Path,
        preparer: WorktreePreparer | None = None,
    ) -> None:
        self.launcher = launcher
        self.workspace = workspace
        self.preparer = preparer

    def require(self, request: LaunchRequest, failure: str) -> ExitStatus:
        """Launch one step whose failure refuses the run, in git's own words.

        A sequence reported under one message cannot say which of its steps
        failed, and a bare status code names neither the step nor anything
        to act on. Raising at the step also stops the sequence there, so a
        later step never runs against a tree an earlier one failed to make.
        """
        status = self.launcher.launch(request)
        if status.code != 0:
            raise RuntimeError(
                f"{failure}: `{' '.join(request.arguments)}` exited "
                f"{status.code}: {status.stderr.strip()}"
            )
        return status

    def create(self, lease: WritableRootLease, base_commit: str) -> None:
        self.require(
            LaunchRequest(
                arguments=[
                    "git",
                    "worktree",
                    "add",
                    "-b",
                    lease.branch,
                    str(lease.root),
                    base_commit,
                ],
                cwd=self.workspace,
            ),
            f"failed to create worktree for {lease.concern_id}",
        )
        if self.preparer is not None:
            self.preparer.prepare(lease.root)

    def clear_notes(
        self, lease: WritableRootLease, concern: Concern, base_commit: str
    ) -> NoteClearanceCommit:
        """Strip this concern's notes from its lease as a distinct commit.

        Committing rather than leaving the strip in the working tree is what
        keeps :meth:`validate_and_commit` strict: the worker's base already
        has the notes gone, so its reported paths still equal the inspected
        diff. A concern whose notes were all absent commits nothing and keeps
        the base it was given.
        """
        clearance = clear_concern_notes(lease.root, concern)
        if not clearance.cleared:
            return NoteClearanceCommit(clearance=clearance, commit=base_commit)
        added = self.launcher.launch(
            LaunchRequest(arguments=["git", "add", "-A"], cwd=lease.root)
        )
        committed = self.launcher.launch(
            LaunchRequest(
                arguments=[
                    "git",
                    "commit",
                    "-m",
                    f"resolve: clear review notes for {concern.id}",
                ],
                cwd=lease.root,
            )
        )
        identified = self.launcher.launch(
            LaunchRequest(arguments=["git", "rev-parse", "HEAD"], cwd=lease.root)
        )
        commit_lines = identified.stdout.splitlines()
        if (
            added.code != 0
            or committed.code != 0
            or identified.code != 0
            or len(commit_lines) != 1
            or not commit_lines[0]
        ):
            raise RuntimeError(f"failed to clear review notes for {concern.id}")
        return NoteClearanceCommit(clearance=clearance, commit=commit_lines[0])

    def validate_and_commit(
        self,
        concern: Concern,
        report: WorkerReport,
        lease: WritableRootLease,
        base_commit: str,
        leases: WritableRootLeases,
    ) -> DiffValidation:
        try:
            self.branch(lease)
        except RuntimeError:
            return DiffValidation(
                concern_id=concern.id,
                valid=False,
                reason="worker changed branch authority",
            )
        current = self.head(lease)
        if current != base_commit:
            return DiffValidation(
                concern_id=concern.id,
                valid=False,
                reason="worker changed commit or branch authority",
            )
        intent = self.launcher.launch(
            LaunchRequest(arguments=["git", "add", "-N", "."], cwd=lease.root)
        )
        if intent.code != 0:
            return DiffValidation(
                concern_id=concern.id,
                valid=False,
                reason="new paths could not be inspected",
            )
        checked = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "diff", "--check", base_commit],
                cwd=lease.root,
            )
        )
        if checked.code != 0:
            return DiffValidation(
                concern_id=concern.id,
                valid=False,
                reason="diff validation failed",
            )
        named = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "diff", "--name-only", base_commit],
                cwd=lease.root,
            )
        )
        if named.code != 0:
            return DiffValidation(
                concern_id=concern.id,
                valid=False,
                reason="changed paths could not be inspected",
            )
        changed = [Path(line) for line in named.stdout.splitlines() if line]
        for path in changed:
            if path.is_absolute() or ".." in path.parts:
                return DiffValidation(
                    concern_id=concern.id,
                    valid=False,
                    reason=f"changed path escapes the worktree: {path}",
                )
            leases.assert_path(concern.id, lease.root / path)
        actual = {path.as_posix() for path in changed}
        reported = {path.as_posix() for path in report.files_changed}
        swept = {path.as_posix() for path in report.swept_beyond_scope}
        # The safety property is that nothing changes undeclared, which is
        # containment and not equality. Requiring equality also punished a
        # worker for a stale path it believed it had touched, and cost 71
        # files of correct work over two such entries — nothing was hidden in
        # either. Over-reporting is named back rather than rejected, because a
        # reason that names no path cannot converge: every retry re-derives
        # the same report and fails identically until the budget is spent.
        undeclared = sorted(actual - reported)
        unswept = sorted(swept - actual)
        if undeclared or unswept:
            return DiffValidation(
                concern_id=concern.id,
                valid=False,
                reason=report_mismatch(undeclared, unswept),
                declaration=True,
            )
        if not changed:
            return DiffValidation(
                concern_id=concern.id,
                valid=not report.changed,
                commit=base_commit if not report.changed else None,
                reason=(
                    ""
                    if not report.changed
                    else "worker reported changes but diff is empty"
                ),
            )
        if not report.changed:
            return DiffValidation(
                concern_id=concern.id,
                valid=False,
                reason="worker reported no change but the worktree is modified",
            )
        added = self.launcher.launch(
            LaunchRequest(arguments=["git", "add", "-A"], cwd=lease.root)
        )
        committed = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "commit", "-m", f"resolve: {concern.title}"],
                cwd=lease.root,
            )
        )
        if added.code != 0 or committed.code != 0:
            return DiffValidation(
                concern_id=concern.id,
                valid=False,
                reason="orchestrator commit failed",
            )
        identified = self.launcher.launch(
            LaunchRequest(arguments=["git", "rev-parse", "HEAD"], cwd=lease.root)
        )
        commit_lines = identified.stdout.splitlines()
        if identified.code != 0 or len(commit_lines) != 1 or not commit_lines[0]:
            return DiffValidation(
                concern_id=concern.id,
                valid=False,
                reason="created commit identity was not available",
            )
        return DiffValidation(
            concern_id=concern.id,
            valid=True,
            commit=commit_lines[0],
        )

    def remove(self, lease: WritableRootLease) -> WorktreeRemoval:
        """Free a lease's worktree, reporting what actually stands in the way.

        An exit status cannot tell a dirty worktree from one that is no
        longer there — `git worktree remove` refuses both — so reading the
        refusal as uncommitted work sent a human to directories that did not
        exist and described work that was not being held. What remains on
        disk is observable, so it is observed rather than inferred, and the
        refusal git gave is carried instead of a guess at it.
        """
        status = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "worktree", "remove", str(lease.root)],
                cwd=self.workspace,
            )
        )
        notes: list[str] = []
        if status.code != 0:
            if lease.root.exists():
                return WorktreeRemoval(freed=False, detail=status.stderr.strip())
            self.launcher.launch(
                LaunchRequest(
                    arguments=["git", "worktree", "prune"], cwd=self.workspace
                )
            )
            notes.append("worktree was already gone")
        deleted = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "branch", "-D", lease.branch],
                cwd=self.workspace,
            )
        )
        if deleted.code != 0:
            notes.append(f"branch retained: {deleted.stderr.strip()}")
        return WorktreeRemoval(freed=True, detail="; ".join(notes))

    def restore(self, lease: WritableRootLease) -> None:
        """Restore a persisted branch into its persisted writable root."""
        self.require(
            LaunchRequest(
                arguments=["git", "worktree", "add", str(lease.root), lease.branch],
                cwd=self.workspace,
            ),
            f"failed to restore worktree for {lease.concern_id}",
        )
        if self.preparer is not None:
            self.preparer.prepare(lease.root)

    def branch_exists(self, lease: WritableRootLease) -> bool:
        """Report whether a persisted resolver branch exists locally."""
        status = self.launcher.launch(
            LaunchRequest(
                arguments=[
                    "git",
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{lease.branch}",
                ],
                cwd=self.workspace,
            )
        )
        return status.code == 0

    def merging(self, lease: WritableRootLease) -> str | None:
        """The parent of a merge left in progress, or ``None`` when settled."""
        status = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                cwd=lease.root,
            )
        )
        lines = status.stdout.splitlines()
        return lines[0] if status.code == 0 and lines else None

    def already_joined(self, lease: WritableRootLease, commit: str) -> bool:
        """Report whether a parent is already contained in the worktree's HEAD."""
        status = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "merge-base", "--is-ancestor", commit, "HEAD"],
                cwd=lease.root,
            )
        )
        return status.code == 0

    def branch(self, lease: WritableRootLease) -> str:
        """Read the current branch for an orchestrated worktree."""
        identified = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "branch", "--show-current"],
                cwd=lease.root,
            )
        )
        lines = identified.stdout.splitlines()
        if identified.code != 0 or lines != [lease.branch]:
            raise RuntimeError(f"worktree branch changed for {lease.concern_id}")
        return lines[0]

    # lup: solved: reset lost its production caller when restore_worktree chose to
    # preserve the interrupted turn (a park is a pause, not an abandonment);
    # decide whether any retry path still owes a hard discard, or remove
    # this method and the three tests that exercise it.
    def head(self, lease: WritableRootLease) -> str:
        """Read the exact current commit identity for an orchestrated worktree."""
        identified = self.require(
            LaunchRequest(
                arguments=["git", "rev-parse", "HEAD"],
                cwd=lease.root,
            ),
            f"failed to identify worktree {lease.concern_id}",
        )
        lines = identified.stdout.splitlines()
        if len(lines) != 1 or not lines[0]:
            raise RuntimeError(
                f"failed to identify worktree {lease.concern_id}: `git rev-parse "
                f"HEAD` named {len(lines)} commits: {identified.stdout.strip()!r}"
            )
        return lines[0]

    def prepare_join(self, lease: WritableRootLease, parent_commits: list[str]) -> bool:
        """Stage a no-commit merge, reporting whether git had to leave a conflict.

        The answer is what decides whether an agent turn is spent at all.
        Accepting exit 0 and exit 1 identically meant a merger was invoked on
        every parent, handed an already-correct tree it could edit, with
        nothing to decide — ten such turns in a twelve-parent run.
        """
        if len(parent_commits) != 2:
            raise ValueError("one semantic join step requires exactly two commits")
        # Preparing is idempotent: a merge already open against this same parent
        # is the one a previous turn was resolving, and re-running `git merge`
        # over it would fail on the existing MERGE_HEAD anyway. Leaving it in
        # place is what lets a resolution survive the park that interrupted it.
        if self.merging(lease) == parent_commits[1]:
            # A merge left open is one a turn was already resolving, so the
            # question it was invoked over stands whatever git reported then.
            return True
        status = self.launcher.launch(
            LaunchRequest(
                arguments=[
                    "git",
                    "merge",
                    "--no-commit",
                    "--no-ff",
                    parent_commits[1],
                ],
                cwd=lease.root,
            )
        )
        if status.code not in {0, 1}:
            raise RuntimeError(
                f"failed to prepare semantic join for {lease.concern_id}: "
                f"`git merge` exited {status.code}: {status.stderr.strip()}"
            )
        return status.code == 1

    def conflicted_paths(self, lease: WritableRootLease) -> list[Path]:
        """Every path git left unmerged, which git already knows exactly."""
        unmerged = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=lease.root,
            )
        )
        return [Path(line) for line in unmerged.stdout.splitlines() if line]

    def current_branch(self, root: Path) -> str:
        """Which branch a worktree has checked out, empty when detached."""
        named = self.launcher.launch(
            LaunchRequest(arguments=["git", "branch", "--show-current"], cwd=root)
        )
        lines = named.stdout.splitlines()
        return lines[0] if named.code == 0 and lines else ""

    def fast_forward(self, root: Path, source: str) -> bool:
        """Advance a checked-out branch from inside the worktree holding it.

        Every plumbing route that moves the ref from outside corrupts the
        view: ``git branch -f`` refuses outright, while ``git update-ref``
        and ``git push .`` both report success and leave the standing
        worktree showing a staged modification nobody made, because the ref
        moved and the index did not. Merging from inside moves ref, index
        and working tree together.
        """
        merged = self.launcher.launch(
            LaunchRequest(arguments=["git", "merge", "--ff-only", source], cwd=root)
        )
        return merged.code == 0

    def merge_base(self, lease: WritableRootLease, left: str, right: str) -> str:
        """Where two commits forked, so a contribution can be read from there."""
        found = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "merge-base", left, right],
                cwd=lease.root,
            )
        )
        lines = found.stdout.splitlines()
        if found.code != 0 or not lines:
            raise RuntimeError(f"{left} and {right} share no history")
        return lines[0]

    def changed_between(
        self, lease: WritableRootLease, base: str, commit: str
    ) -> list[Path]:
        """Every path that differs between two commits."""
        named = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "diff", "--name-only", base, commit],
                cwd=lease.root,
            )
        )
        return [Path(line) for line in named.stdout.splitlines() if line]

    def added_lines(
        self, lease: WritableRootLease, base: str, parent: str, path: Path
    ) -> list[str]:
        """Every substantive line one parent adds to one path.

        Blank and near-punctuation lines are excluded because they carry no
        identity: a closing brace surviving proves nothing about the hunk
        that added it, and including them would bury a real loss under noise
        the merger then has to account for.
        """
        diffed = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "diff", "-U0", base, parent, "--", path.as_posix()],
                cwd=lease.root,
            )
        )
        return [
            stripped
            for line in diffed.stdout.splitlines()
            if line.startswith("+") and not line.startswith("+++")
            for stripped in [line[1:].strip()]
            if len(stripped) > 3 and any(character.isalnum() for character in stripped)
        ]

    def file_at(self, lease: WritableRootLease, commit: str, path: Path) -> str:
        """One path's content at one commit, empty where it does not exist."""
        shown = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "show", f"{commit}:{path.as_posix()}"],
                cwd=lease.root,
            )
        )
        return shown.stdout if shown.code == 0 else ""

    def drop_candidates(
        self, lease: WritableRootLease, base: str, parent: str, result: str
    ) -> list[DropCandidate]:
        """What this parent contributed that the joined tree no longer holds.

        Line presence rather than hunk identity, so a resolution that merely
        moved code within its file still reads as kept. A line that was
        genuinely rewritten does read as missing — which is the point, since
        a rewrite is exactly the choice the merger has to declare.
        """
        found: list[DropCandidate] = []  # lup: ignore[empty-collection]
        for path in self.changed_between(lease, base, parent):
            contributed = self.added_lines(lease, base, parent, path)
            lost = self.lost_symbols(lease, base, parent, result, path)
            if not contributed and not lost:
                continue
            held = self.file_at(lease, result, path)
            missing = [line for line in contributed if line not in held]
            if missing or lost:
                found.append(
                    DropCandidate(
                        parent=parent, path=path, missing=missing, lost_symbols=lost
                    )
                )
        return found

    def lost_symbols(
        self,
        lease: WritableRootLease,
        base: str,
        parent: str,
        result: str,
        path: Path,
    ) -> list[DefinedSymbol]:
        """Definitions this parent introduced that the joined tree dropped.

        Restricted to what the parent itself added, so a definition removed
        deliberately on the other side is that side's decision and not this
        parent's loss. The convention this repository states for merges is
        exactly this comparison — account for every missing `def` and `class`
        — and stating it in a guidance document made it a step a merger could
        skip, where computing it makes the answer an obligation.
        """
        if path.suffix.lower() not in {".py", ".pyi"}:
            return []
        introduced = symbols_lost(
            self.file_at(lease, parent, path), self.file_at(lease, base, path)
        )
        held = {
            symbol.name for symbol in defined_symbols(self.file_at(lease, result, path))
        }
        return [symbol for symbol in introduced if symbol.name not in held]

    def commit_join(self, lease: WritableRootLease, title: str) -> str:
        """Create and read the orchestrator-owned semantic join commit."""
        checked = self.launcher.launch(
            LaunchRequest(arguments=["git", "diff", "--check"], cwd=lease.root)
        )
        unresolved = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=lease.root,
            )
        )
        # `git diff --check` is the conflict guard: it exits non-zero on a
        # marker left in the content. A path can also sit unmerged in the index
        # while its content is fully resolved, which is what the merger leaves
        # behind when it edits the file without staging it — `git add -A` below
        # settles exactly that, so an unmerged path is only a failure when the
        # content still carries markers. Naming both conditions here rejected
        # resolved work and stopped one line short of the call that would have
        # accepted it.
        if checked.code != 0 or unresolved.code != 0:
            raise RuntimeError(
                f"semantic join for {lease.concern_id} still has "
                f"invalid changes: {checked.stdout.strip() or unresolved.stderr.strip()}"
            )
        status = self.require(
            LaunchRequest(arguments=["git", "status", "--porcelain"], cwd=lease.root),
            f"failed to inspect semantic join for {lease.concern_id}",
        )
        merge_head = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                cwd=lease.root,
            )
        )
        if not status.stdout.splitlines() and merge_head.code != 0:
            return self.head(lease)
        self.require(
            LaunchRequest(arguments=["git", "add", "-A"], cwd=lease.root),
            f"failed to stage semantic join for {lease.concern_id}",
        )
        self.require(
            LaunchRequest(
                arguments=["git", "commit", "-m", title],
                cwd=lease.root,
            ),
            f"failed to commit semantic join for {lease.concern_id}",
        )
        return self.head(lease)


class DependencyBaseBuilder:
    """Build root, single-parent, and semantic multi-parent dependency bases."""

    def __init__(self, source: SourceSnapshot) -> None:
        self.source = source

    def build(
        self,
        concern: Concern,
        parent_commits: dict[str, str],  # lup: ignore[dict-str-payload]
        joined_commit: str | None = None,
    ) -> DependencyBase:
        commits = [parent_commits[parent] for parent in concern.dependencies]
        if not commits:
            commit = self.source.commit
            semantic_join = False
        elif len(commits) == 1:
            commit = commits[0]
            semantic_join = False
        else:
            if joined_commit is None:
                raise ValueError(
                    f"concern {concern.id!r} needs a semantic multi-parent join"
                )
            commit = joined_commit
            semantic_join = True
        return DependencyBase(
            concern_id=concern.id,
            parent_concerns=concern.dependencies,
            parent_commits=commits,
            commit=commit,
            semantic_join=semantic_join,
        )
