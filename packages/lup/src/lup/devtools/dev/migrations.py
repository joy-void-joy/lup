"""What an adopter has to do about a break, where two trees cannot say it.

Most of what a range asks of a project built on this one is derivable, and is
derived: a module that moved and a name that was renamed are fully determined
by the surface at each end, which git holds for every revision, so
:mod:`lup.devtools.dev.preservation` reads both and the map costs nothing to
keep. What is left over is the residue — a signature that gained required
parameters, a refusal that split in two, a default whose meaning changed —
where nothing in either tree says what a caller should now pass. That is what
is declared here, and only that.

A migration is keyed to the commit it applies after, because commits are what
this library ships at: a project pinned to a branch is between releases by
definition, and a record that only existed at release time would be silent
exactly when such a project is updating. A release cadence on top changes
nothing here — :func:`rendered` folds whatever is pending into the release's
changelog section, and the declarations leave the tree, so what stands here is
always the unreleased window and never a growing pile.

The gate is in this repository rather than downstream. A capability that
disappears between the merge base and the working tree, with no migration
naming it, fails the gate that would have shipped it — so a break cannot land
without its instruction, and an adopter reads a complete record rather than a
diligent one.
"""

from pathlib import Path

import sh
from pydantic import BaseModel

from lup.devtools.dev.branches import detect_base_branch
from lup.devtools.dev.preservation import (
    Capability,
    compare,
    surface_at,
    surface_now,
)
from lup.devtools.project import DevProject
from lup.execution.shell import git


class MigrationStep(BaseModel, frozen=True):
    """One thing to do about a break, in the form it can be done in."""

    instruction: str
    """What to do, as a sentence somebody can act on."""

    command: list[str] = []
    """The command that does it, where a command does.

    Empty for the ordinary case, which is the whole reason this is declared
    rather than derived: what a caller should pass to a signature that grew is
    a decision about their code, and a command that guessed at it would be
    worse than a sentence that asks.
    """

    def spelled(self) -> str:
        """This step as an update reports it, with its command where it has one."""
        return self.instruction + (
            f"\n    {' '.join(self.command)}" if self.command else ""
        )


class Migration(BaseModel, frozen=True):
    """One break, the commit that made it, and what a caller does about it."""

    subjects: list[str]
    """Every capability this break took, spelled as the surface walk spells it.

    Plural because one decision takes several names at once — a mode retired
    takes its enum member, its reader and its two commands — and splitting
    that into an entry per name would ask a reader to reassemble one change
    out of four records saying the same sentence.
    """

    reason: str
    """Why the break was taken. This is what reaches the changelog at release."""

    steps: list[MigrationStep]

    commit: str = ""
    """The commit the break landed in, once it has one.

    Empty while the declaration is younger than the commit carrying it — the
    commit being written cannot name itself — and read as *newer than every
    revision*, which is what it is: a project taking this library takes the
    break with it, whatever commit it stood at before. Filling it in later
    buys one thing, which is telling a project that already has it so.
    """

    def covers(self, capability: Capability) -> bool:
        """Whether this migration is the one that speaks for that capability.

        Matched on the name rather than on the module it was declared in: a
        capability that disappeared has no module any more, and the name is
        what a caller's code holds.
        """
        return capability.identity in self.subjects

    def applied_at(self, revision: str, root: Path = Path()) -> bool:
        """Whether a project standing at ``revision`` already has this break.

        Ancestry rather than ordering: a project pinned to a branch that never
        carried the commit has not applied it, whatever the dates say. A
        declaration naming no commit is pending for every revision, which is
        the honest answer while the break is newer than any commit that could
        be named.

        Asked of whichever checkout holds both commits. In this repository
        that is this one; in a project built on it, it is the clone of upstream
        the update already fetched, since neither commit is in the project's
        own history at all.
        """
        if not self.commit:
            return False
        try:
            git("-C", str(root), "merge-base", "--is-ancestor", self.commit, revision)
        except sh.ErrorReturnCode:
            return False
        return True

    def spelled(self) -> list[str]:
        """This migration as an update reports it: the reason, then the steps."""
        return [
            f"{', '.join(self.subjects)} — {self.reason}",
            *(f"  {step.spelled()}" for step in self.steps),
        ]


DECLARED: list[Migration] = [
    Migration(
        subjects=["shell_patch", "remembered_run", "patch_review"],
        reason="Native hook reviews bind captured documents and policy bytes; Codex approvals remain single-use.",
        steps=[
            MigrationStep(
                instruction=(
                    "Regenerate both native plugins. Replace direct shell_patch callers with "
                    "lup.policy.kernel.review.literal_input(command, 'apply_patch'). "
                    "Pass captured preconditions and the shell flag to patch_review; never re-read "
                    "the working tree for a parked review. Codex no longer consumes or creates "
                    "persistent approval memory: operators answer each queued review independently."
                )
            )
        ],
    ),
    Migration(
        subjects=["Runtime.contained"],
        reason=(
            "`contained` named the configuration home a workspace's sessions "
            "are pointed at, while everywhere else in this library it names a "
            "container — and a session can now ask for one. The method takes "
            "the word for what it does, `homed`, and the boundary keeps the "
            "other"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Call `Runtime.homed(request)` where you called "
                    "`Runtime.contained(request)`; nothing else about it moved. "
                    "A caller reaching it through `Runtime.session_factory` "
                    "was never naming it and has nothing to change."
                ),
                command=[
                    "uv",
                    "run",
                    "lup-devtools",
                    "dev",
                    "py",
                    "text",
                    "\\.contained\\(",
                ],
            ),
        ],
    ),
]
"""Every break this library has taken since its last release, and what to do.

Empty is the state to keep it in: an entry is added by the commit that breaks
something, and every entry leaves at the next release, rendered into that
release's changelog section by `version bump`. A list that grows is a release
overdue rather than a record to reorganise.
"""


def unapplied(
    declared: list[Migration], revision: str, root: Path = Path()
) -> list[Migration]:
    """The declared migrations a project standing at ``revision`` still owes."""
    return [
        migration for migration in declared if not migration.applied_at(revision, root)
    ]


def unnamed(
    disappeared: list[Capability], declared: list[Migration]
) -> list[Capability]:
    """Every capability that went with no migration speaking for it.

    The gate's whole question. A capability that moved is not here — the map
    is derived and needs nobody to write it down — and one that went on
    purpose is not here either, as long as the commit that took it said so.
    """
    return [
        capability
        for capability in disappeared
        if not any(migration.covers(capability) for migration in declared)
    ]


def gate_base(integration: str, release: str = "main") -> str | None:
    """The commit this checkout's breaks are judged from, or ``None`` with none to read.

    A feature branch is judged from where it started, which creation recorded
    and topology can otherwise guess among the local branches. The
    integration branch is judged from the release branch: what it has taken
    since the last release is what an adopter meets on their next update.
    Where no local branch stands beside the current one -- a CI clone holds
    the branch it checks out and nothing else, and a pull request's checkout
    stands on no branch at all -- the remote's copy of the base is read
    instead, which a full fetch carries.

    No base at all is a reading, not a refusal. The base detector exits the
    process where it finds no other local branch, and for every push after
    this gate was written that exit took the whole report with it: the log
    held one line and an exit code, and named no check.
    """
    current = git.out("branch", "--show-current").strip()
    siblings = [
        branch
        for branch in git.lines("branch", "--format=%(refname:short)")
        if branch != current
    ]
    if current and current != integration and siblings:
        return detect_base_branch(current).merge_base
    named = release if current == integration else integration
    for ref in (named, f"origin/{named}"):
        found = git.out("merge-base", ref, "HEAD", _ok_code=[0, 1, 128]).strip()
        if found:
            return found
    return None


def undeclared_breaks(
    project: DevProject, base: str, declared: list[Migration] = DECLARED
) -> list[Capability]:
    """Every capability this checkout took since ``base`` that nothing speaks for.

    ``base`` is what :func:`gate_base` answered: what this change took away is
    judged against where it started, and creation recorded that where
    topology can no longer recover it.
    """
    divergence = compare(surface_at(base, project), surface_now(project))
    return unnamed(divergence.disappeared, declared)


def rendered(declared: list[Migration]) -> list[str]:
    """What a release's changelog section says about the breaks in it.

    The prose half only: a reason and the steps a reader has to act on. The
    derived half is left out on purpose — a relocation map is re-derivable
    from any two revisions, and a hundred pairs pasted into a changelog go
    stale the next time one module moves.
    """
    return [line for migration in declared for line in migration.spelled()]
