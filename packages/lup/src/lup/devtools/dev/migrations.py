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


DECLARED = [
    Migration(
        commit="2bb3da2ea",
        subjects=[
            "approval_fingerprint",
            "approval_receipt_root",
            "record_approval",
            "spend_approval",
            "uncorrelated",
        ],
        reason=(
            "a queue approval is bound to the exact call, session, checkout "
            "and file preimages and spent once on retry, so the receipts that "
            "stood in for that correlation — written per pending prompt, and "
            "matched by nothing narrower than a prompt — have nothing left to "
            "answer"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Nothing outside the dispatcher called these. A project "
                    "that carried its own copy of the Codex dispatcher asset "
                    "takes the library's again by regenerating: the receipts "
                    "directory it wrote under the session root is no longer "
                    "read and can be removed."
                ),
                command=["uv", "run", "lup-devtools", "harness", "generate", "all"],
            ),
        ],
    ),
    Migration(
        commit="61d8c01e1",
        subjects=["LibraryMode.LINKED", "read_linked_path", "link_library"],
        reason=(
            "an editable install of a lup checkout moved the library with no "
            "command run in the project and nothing written down, so the pin, "
            "the copied half and the generated trees had nothing to be held at "
            "one commit against"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "A project resolving lup from a path pins the branch "
                    "carrying its changes instead, which moves under a command "
                    "and records the commit it moved to."
                ),
                command=[
                    "uv",
                    "run",
                    "lup-devtools",
                    "dev",
                    "library",
                    "git",
                    "--branch",
                    "<branch>",
                ],
            ),
        ],
    ),
    Migration(
        commit="e1aa3da35",
        subjects=["build_session_toolset", "tool_group_names", "ServerGroup"],
        reason=(
            "assembling a session's tool groups was the same work in every "
            "project built on lup and went stale in each of them separately; "
            "what a project decides is which groups it carries, so the "
            "assembly is the library's and the list is the project's"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Replace the copied `build_session_toolset` with a list of "
                    "`ToolGroup`s: name `coordination_group()`, `ledger_group("
                    "...)`, `sandbox_group()`, `codeintel_group()` and "
                    "`realtime_group()` from `lup.tools.toolsets` rather than "
                    "rebuilding them, and write a builder for each group of "
                    "your own. A builder that has nothing to build for a "
                    "session returns nothing, which replaces every `if` that "
                    "asked whether the session had a sandbox or an identity."
                ),
            ),
            MigrationStep(
                instruction=(
                    "`tool_group_names(realtime=...)` is derived now: "
                    "`served_names(groups, needs)` for one session, "
                    "`startup_names(groups)` for the servers a runtime starts "
                    "when a session opens."
                ),
            ),
            MigrationStep(
                instruction=(
                    "A `--server` option typed as the `ServerGroup` literal "
                    "takes a plain string and is checked against the declared "
                    "names, since a project's groups are its own."
                ),
            ),
        ],
    ),
    Migration(
        subjects=[
            "capture",
            "operations",
            "CAPTURE_FILE",
            "CapabilityKind",
            "CapabilityKind.COMMAND",
            "CapabilityKind.EXPORT",
            "Capability.kind",
            "SurfaceCapture.commands",
            "SurfaceCapture.read",
            "SurfaceCapture.write",
        ],
        reason=(
            "a surface stored in the tree ages against the walker that reads "
            "it — the checked-in one had already stopped seeing type aliases — "
            "while git holds every revision, so both ends of a range are read "
            "rather than remembered"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "`dev preserve capture` and its fixture are gone: nothing "
                    "is stored. `dev migrate map <base>..<head>` derives the "
                    "relocation, `dev migrate check` refuses a capability that "
                    "went undeclared, and both read the surface out of git."
                ),
                command=[
                    "uv",
                    "run",
                    "lup-devtools",
                    "dev",
                    "migrate",
                    "map",
                    "<base>..",
                ],
            ),
            MigrationStep(
                instruction=(
                    "A command is no longer walked as a capability of its own. "
                    "It is declared by a function whose name is in the surface "
                    "already, so a command that goes takes its declaration "
                    "with it."
                ),
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


def undeclared_breaks(
    project: DevProject, declared: list[Migration] = DECLARED
) -> list[Capability]:
    """Every capability this branch took that nothing here speaks for.

    Measured against the branch's own base rather than a branch named here:
    what this change took away is judged against where it started, and
    creation recorded that where topology can no longer recover it.
    """
    base = detect_base_branch().merge_base
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
