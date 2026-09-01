"""What a capture actually covers, and what it takes to say so honestly.

A snapshot reference is not recovery. Coverage, restoration, metadata,
completion, post-state, conflict behaviour, and storage durability are all
part of the guarantee, and a settlement row that discharged a question on the
existence of a ref would be discharging it on the cheapest part. So this
module answers three questions the settlement layer asks and never guesses at:

- **Which capture covers this operation?** A footprint that resolves
  statically takes a targeted snapshot of exactly those paths. One that does
  not — a glob, a variable, a directory walk — widens to every precious
  writable root, because the wider capture is what the opacity costs rather
  than a reason to refuse.
- **Was it taken?** Measured, and the answer is one of three: nothing
  required, capture proven, capture attempted and short. The third is not the
  first, and telling them apart is what lets a failed capture say so.
- **Can this be put back?** Only where the affected paths still hold what the
  operation left. Anything else is a later change this undo would clobber,
  and clobbering it silently is the failure a recovery layer exists to avoid.

The lease is the fourth thing, and it is narrower than it looks: it serializes
*Lup-coordinated* mutation across capture, execution, and post-state capture,
so two of this coordinator's operations cannot interleave their captures. It
does not pretend to stop a human, an IDE, a file watcher, or an unrelated
process — which is exactly why post-state evidence exists and why undo is
conflict-aware. A profile that needs stronger exclusivity enforces it through
its boundary.

No lease is held while a question waits. A lock held across a human's
attention is a lock held for minutes, and the rest of the session needs it.
"""

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from lup.policy.kernel.decision import CheckpointRequirement
from lup.policy.kernel.semantics import CheckpointEvidence
from lup.policy.operations import MutationFootprint


def capture_required(footprint: MutationFootprint) -> CheckpointRequirement:
    """Which capture would cover everything this footprint can affect.

    Read off the footprint rather than declared beside a rule, because the
    same rule reaches both answers: ``rm build/out`` names its target and
    ``rm $TARGET`` does not, and it is the second that needs every precious
    root held. A rule that stated one answer for both would either capture far
    too much on the ordinary case or too little on the opaque one.
    """
    if not footprint.touches():
        return "unrecoverable"
    return "targeted" if footprint.exact else "boundary_wide"


class PathState(BaseModel, frozen=True):
    """One path as a capture found it, including finding it absent.

    Absence is a state and not a gap: an operation that *creates* a file has
    "this was not here" as its pre-state, and an undo that cannot tell that
    from "this was not captured" either leaves the creation in place or
    deletes a file it never held.

    Mode is carried because a restore that puts content back and drops the
    executable bit has restored a file that no longer runs — which reads as a
    successful recovery right up until something tries to execute it.
    """

    path: Path
    present: bool
    digest: str = ""
    mode: int = 0
    directory: bool = False
    symlink_target: str = ""

    @classmethod
    def read(cls, path: Path) -> "PathState":
        """This path as it stands, without following a symlink through.

        A symlink is captured as the link it is rather than as what it points
        at, because restoring the target's content over the link would replace
        a pointer with a copy — a different tree that passes a content
        comparison.
        """
        if path.is_symlink():
            return cls(
                path=path,
                present=True,
                mode=path.lstat().st_mode & 0o7777,
                symlink_target=str(path.readlink()),
            )
        if not path.exists():
            return cls(path=path, present=False)
        if path.is_dir():
            return cls(
                path=path,
                present=True,
                directory=True,
                mode=path.stat().st_mode & 0o7777,
            )
        return cls(
            path=path,
            present=True,
            digest=hashlib.sha256(path.read_bytes()).hexdigest(),
            mode=path.stat().st_mode & 0o7777,
        )

    def matches(self, other: "PathState") -> bool:
        """Whether this path still holds exactly what the other recorded."""
        return (
            self.present == other.present
            and self.digest == other.digest
            and self.mode == other.mode
            and self.directory == other.directory
            and self.symlink_target == other.symlink_target
        )


class Checkpoint(BaseModel, frozen=True):
    """One capture, and everything that decides whether it may be trusted.

    ``complete`` is the field a settlement row reads, and it is false unless
    every path in the footprint was actually captured. A partial capture is
    not a small capture: it is one whose gap is exactly where nobody looked,
    and an operation authorized on it has been authorized on nothing.
    """

    operation: str
    requirement: CheckpointRequirement
    reference: str = ""
    pre_state: list[PathState] = []
    post_state: list[PathState] = []
    complete: bool = False
    failure: str = ""
    taken_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def evidence(self) -> CheckpointEvidence:
        """What settlement is told, which is a measurement and not an intent.

        ``absent`` for an operation that needed nothing captured — which is
        not a failure of anything — and ``failed`` for one that needed a
        capture and did not get it, because a person deciding about an
        unprotected loss should be told the protection was attempted.
        """
        if self.requirement == "unrecoverable":
            return "absent"
        if self.complete:
            return "complete"
        return "failed"

    def conflicts(self) -> list[Path]:
        """Paths that no longer hold what this operation left them holding.

        Anything here is a later change an undo would clobber. The undo is not
        refused over it — somebody may well want the earlier state back — but
        it stops being the conflict-free restore that allows, and becomes the
        question it actually is.
        """
        return [
            state.path
            for state in self.post_state
            if not PathState.read(state.path).matches(state)
        ]

    def restorable(self) -> bool:
        """Whether this capture may authorize anything at all.

        An incomplete checkpoint authorizes neither execution nor undo. Half a
        pre-state is worse than none: it reads as protection and covers only
        the paths that happened to be reachable when it ran.
        """
        return self.complete and bool(self.pre_state)


class WorktreeLease:
    """Serializes this coordinator's mutations within one canonical worktree.

    Sibling worktrees take independent leases, because they are independent
    trees: a capture of one says nothing about the other, and one lock across
    both would serialize work that never interacts.

    The lock is a directory rather than a file, because ``mkdir`` is atomic on
    every filesystem this runs on while "check then create" is not — and the
    window between checking and creating is exactly the interleaving this
    exists to prevent.

    A stale lease is a real failure mode: the holder crashed, and the lock
    outlives it. The holder's process id is recorded so a later acquirer can
    tell "somebody is working" from "somebody died", and breaking one is a
    deliberate act with the reason recorded rather than a timeout nobody sees.
    """

    path: Path
    holder: str

    def __init__(self, worktree: Path, holder: str, name: str = ".lup/lease") -> None:
        self.path = worktree / name
        self.holder = holder

    def held(self) -> str:
        """Who holds this lease, or ``""`` where nobody does."""
        marker = self.path / "holder"
        if not marker.exists():
            return ""
        try:
            return marker.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def acquire(self) -> bool:
        """Take the lease, or report that somebody else has it.

        Reported rather than raised, because the caller's next move differs by
        situation — a coordinator waits, a diagnostic prints — and an
        exception makes the common case the one that needs handling.
        """
        try:
            self.path.mkdir(parents=True)
        except FileExistsError:
            return False
        (self.path / "holder").write_text(
            f"{self.holder}:{os.getpid()}", encoding="utf-8"
        )
        return True

    def release(self) -> None:
        """Give the lease up, tolerating its already being gone.

        Tolerant because release runs on the failure path too, and a release
        that raises inside cleanup replaces the original failure with its own.
        """
        marker = self.path / "holder"
        if marker.exists():
            marker.unlink()
        if self.path.exists():
            self.path.rmdir()

    def __enter__(self) -> "WorktreeLease":
        if not self.acquire():
            raise RuntimeError(
                f"the mutation lease for {self.path.parent} is held by"
                f" {self.held() or 'somebody'}"
            )
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class RecoveryCoordinator:
    """Captures pre-state, measures it, and answers whether an undo is clean.

    The capture is content-addressed under a store the launcher owns rather
    than inside the worktree, so an operation that destroys the worktree does
    not destroy the record of what was there. ``.lup`` holds references only.
    """

    store: Path

    def __init__(self, store: Path) -> None:
        self.store = store

    def capture(
        self, operation: str, footprint: MutationFootprint, precious: list[Path]
    ) -> Checkpoint:
        """Take the capture this footprint requires, and say whether it worked.

        Widening on opacity rather than refusing: the operation is legible and
        its blast radius is not, so every precious writable root is captured
        and the operation proceeds. Refusing instead would make an unresolved
        variable into a policy decision, which is the wrong place for one.
        """
        requirement = capture_required(footprint)
        if requirement == "unrecoverable":
            return Checkpoint(operation=operation, requirement=requirement)
        targets = footprint.touches() if requirement == "targeted" else precious
        try:
            states = [PathState.read(path) for path in targets]
        except OSError as failure:
            return Checkpoint(
                operation=operation,
                requirement=requirement,
                failure=f"{type(failure).__name__}: {failure}",
            )
        if len(states) != len(targets):
            return Checkpoint(
                operation=operation,
                requirement=requirement,
                failure="the capture covered fewer paths than the footprint names",
            )
        return Checkpoint(
            operation=operation,
            requirement=requirement,
            reference=self.reference(operation, states),
            pre_state=states,
            complete=True,
        )

    def reference(self, operation: str, states: list[PathState]) -> str:
        """A stable name for one capture, derived from what it holds.

        Content-addressed so two captures of an unchanged tree collapse to one
        name — which matters because a capture is taken in front of every
        mutating operation, including the ones that are then refused.
        """
        material = "".join(
            f"{state.path.as_posix()}:{state.digest}:{state.present}"
            for state in states
        )
        return hashlib.sha256(f"{operation}{material}".encode()).hexdigest()[:16]

    def settle(self, checkpoint: Checkpoint) -> Checkpoint:
        """Record what the affected paths hold once the operation has run.

        Post-state is what makes undo conflict-aware. Without it the only
        available comparison is "does this differ from the pre-state", which
        is true of every successful operation — so every undo would look like
        a conflict and none of them would be one.
        """
        if not checkpoint.restorable():
            return checkpoint
        return checkpoint.model_copy(
            update={
                "post_state": [
                    PathState.read(state.path) for state in checkpoint.pre_state
                ]
            }
        )
