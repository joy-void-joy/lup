"""Concrete lease, worktree, commit, and dependency-base orchestration."""

from pathlib import Path

from lup.harness.process import LaunchRequest, ProcessLauncher
from lup.resolver.contracts import WorktreePreparer
from lup.resolver.notes import clear_concern_notes
from lup.resolver.models import (
    Concern,
    DependencyBase,
    DiffValidation,
    NoteClearanceCommit,
    SourceSnapshot,
    WorkerReport,
    WritableRootLease,
)


class LeaseViolationError(RuntimeError):
    """A resolver attempted to share or escape a writable root."""


class WritableRootLeases:
    """Own non-overlapping writable roots for one resolver run."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.leases: dict[str, WritableRootLease] = {}

    def acquire(self, concern_id: str, branch: str) -> WritableRootLease:
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
        lease = WritableRootLease(
            concern_id=concern_id,
            root=candidate,
            branch=branch,
        )
        self.leases[concern_id] = lease
        return lease

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

    def create(self, lease: WritableRootLease, base_commit: str) -> None:
        status = self.launcher.launch(
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
            )
        )
        if status.code != 0:
            raise RuntimeError(f"failed to create worktree for {lease.concern_id}")
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
        if reported != actual or not swept <= actual:
            return DiffValidation(
                concern_id=concern.id,
                valid=False,
                reason="worker report does not match the inspected changed paths",
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

    def remove(self, lease: WritableRootLease) -> bool:
        status = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "worktree", "remove", str(lease.root)],
                cwd=self.workspace,
            )
        )
        if status.code != 0:
            return False
        deleted = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "branch", "-D", lease.branch],
                cwd=self.workspace,
            )
        )
        return deleted.code == 0

    def restore(self, lease: WritableRootLease) -> None:
        """Restore a persisted branch into its persisted writable root."""
        status = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "worktree", "add", str(lease.root), lease.branch],
                cwd=self.workspace,
            )
        )
        if status.code != 0:
            raise RuntimeError(f"failed to restore worktree for {lease.concern_id}")
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

    def reset(self, lease: WritableRootLease, commit: str) -> None:
        """Discard an uncommitted attempt before safely retrying a concern."""
        reset = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "reset", "--hard", commit],
                cwd=lease.root,
            )
        )
        cleaned = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "clean", "-fd"],
                cwd=lease.root,
            )
        )
        if reset.code != 0 or cleaned.code != 0:
            raise RuntimeError(f"failed to reset worktree for {lease.concern_id}")

    def head(self, lease: WritableRootLease) -> str:
        """Read the exact current commit identity for an orchestrated worktree."""
        identified = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "rev-parse", "HEAD"],
                cwd=lease.root,
            )
        )
        lines = identified.stdout.splitlines()
        if identified.code != 0 or len(lines) != 1 or not lines[0]:
            raise RuntimeError(f"failed to identify worktree {lease.concern_id}")
        return lines[0]

    def prepare_join(self, lease: WritableRootLease, parent_commits: list[str]) -> None:
        """Stage a no-commit merge so the portable merger can resolve semantics."""
        if len(parent_commits) != 2:
            raise ValueError("one semantic join step requires exactly two commits")
        # Preparing is idempotent: a merge already open against this same parent
        # is the one a previous turn was resolving, and re-running `git merge`
        # over it would fail on the existing MERGE_HEAD anyway. Leaving it in
        # place is what lets a resolution survive the park that interrupted it.
        if self.merging(lease) == parent_commits[1]:
            return
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
                f"failed to prepare semantic join for {lease.concern_id}"
            )

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
        if checked.code != 0 or unresolved.code != 0 or unresolved.stdout.splitlines():
            raise RuntimeError(
                f"semantic join for {lease.concern_id} still has invalid changes"
            )
        status = self.launcher.launch(
            LaunchRequest(arguments=["git", "status", "--porcelain"], cwd=lease.root)
        )
        merge_head = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                cwd=lease.root,
            )
        )
        if status.code != 0:
            raise RuntimeError(
                f"failed to inspect semantic join for {lease.concern_id}"
            )
        if not status.stdout.splitlines() and merge_head.code != 0:
            return self.head(lease)
        added = self.launcher.launch(
            LaunchRequest(arguments=["git", "add", "-A"], cwd=lease.root)
        )
        committed = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "commit", "-m", title],
                cwd=lease.root,
            )
        )
        identified = self.launcher.launch(
            LaunchRequest(
                arguments=["git", "rev-parse", "HEAD"],
                cwd=lease.root,
            )
        )
        lines = identified.stdout.splitlines()
        if (
            added.code != 0
            or committed.code != 0
            or identified.code != 0
            or len(lines) != 1
            or not lines[0]
        ):
            raise RuntimeError(f"failed to commit semantic join for {lease.concern_id}")
        return lines[0]


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
