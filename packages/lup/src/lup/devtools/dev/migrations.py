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


class RenderedMigrations(BaseModel, frozen=True):
    """Installed-library output consumed by a process started before its update."""

    count: int
    lines: list[str]


DECLARED: list[Migration] = [
    Migration(
        subjects=["ProjectEntry.review_from", "ProjectEntry.last_synced_commit"],
        commit="1e185c85c94c04c2d5eb73c2e45e106294a2d0de",
        reason=(
            "path registrations review fetched origin commits by default and "
            "review checkpoints are shared across sibling worktrees, bound to "
            "the repository and ref reviewed"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "For unpublished local work, set review_from to local in "
                    "sync.json.local, or run sync setup NAME /path/to/repo "
                    "--review-from local. A repository with no origin remains "
                    "local. Remote review fetches without moving the checkout."
                )
            ),
            MigrationStep(
                instruction=(
                    "Check sync status for the selected review ref. A branchless "
                    "registration matching the library Git source follows its "
                    "consumed branch; resolve any reported source/branch mismatch "
                    "before reviewing commits."
                )
            ),
            MigrationStep(
                instruction=(
                    "After review, run sync mark-synced NAME --at REVIEWED_SHA "
                    "with the immutable commit actually reviewed. This records "
                    "the checkpoint under the common Git directory for all "
                    "worktrees, without fetching an existing upstream. An older "
                    "last_synced_commit remains the seed until that shared "
                    "checkpoint is recorded; changing the repository or ref "
                    "requires reviewing and recording a checkpoint for that source."
                )
            ),
        ],
    ),
    Migration(
        subjects=[
            "ClaudeProfileStore",
            "ClaudeProfileStore.homes_root",
            "ClaudeProfileStore.load_registry",
            "ClaudeProfileStore.save_registry",
            "ClaudeProfileStore.resolver_registry",
            "ClaudeProfileStore.resolve_config_dir",
            "ClaudeProfileStore.names",
            "ClaudeProfileStore.config_dir_for",
            "ClaudeProfileStore.active_profile",
            "ClaudeProfileStore.add_profile",
            "ClaudeProfileStore.set_active",
            "ClaudeProfileStore.remove_profile",
        ],
        commit="fcb61ade64fe36d224b0889eebb1e097ffa954cf",
        reason=(
            "personal Claude profile storage, reading names, and curating accounts "
            "are separate collaborators; the registry file format is unchanged"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Import AccountFile, ClaudeProfileNames, and "
                    "ClaudeProfileRegistrar from lup.providers.claude.profile_store. "
                    "Construct accounts = AccountFile(registry_path), then pass the "
                    "same accounts to ClaudeProfileNames(accounts) and "
                    "ClaudeProfileRegistrar(accounts). Keep homes_root, "
                    "load_registry, save_registry, resolver_registry, and "
                    "resolve_config_dir calls on accounts; call names, "
                    "config_dir_for, and active_profile on the names reader; call "
                    "add_profile, set_active, and remove_profile on the registrar."
                )
            ),
            MigrationStep(
                instruction=(
                    "For CLI profile selection, compose ProfileDirectory(names, "
                    "registrar, CLAUDE_LOGIN) from lup.providers.profiles and "
                    "lup.providers.claude.login. Preserve the existing registry "
                    "path and account homes; no credential or data migration is needed."
                )
            ),
        ],
    ),
    Migration(
        # lup: ignore[native-spelling] — migration names the retired import
        subjects=["CLAUDE_CONFIG_DIR"],
        commit="da46c6bb283385f65ba2f30946d06647b758bc14",
        reason="the Claude configuration-home declaration belongs to its login adapter",
        steps=[
            MigrationStep(
                instruction=(
                    # lup: ignore[native-spelling] — migration names its replacement import
                    "Import CLAUDE_CONFIG_DIR from lup.providers.claude.login "
                    "instead of the former lup.adapters.claude.config module. "
                    "When building a launch environment, prefer "
                    "CLAUDE_LOGIN.environment(config_home) from the same module."
                )
            )
        ],
    ),
    Migration(
        subjects=["CODEX_COMMAND"],
        reason="Codex queue delivery must select the target's verified home and execution scope.",
        steps=[
            MigrationStep(
                instruction="Call wake(WakePath(...), message) rather than the raw "
                "CODEX_COMMAND. Retain the native arrival hook's home and scope "
                "when persisting a wake path. queued now takes that WakePath, "
                "not a thread string; missing or foreign scope leaves durable mail pending."
            ),
        ],
    ),
    Migration(
        subjects=[
            "DynamicToolCall",
            "DynamicToolCall.thread_id",
            "DynamicToolCall.turn_id",
            "DynamicToolCall.call_id",
            "DynamicToolCall.tool",
            "DynamicToolCall.arguments",
            "CodexSchemaRebindingError",
            "dynamic_tool",
        ],
        reason="Codex typed output uses a per-turn native schema and portable validation, "
        "so submission no longer installs a thread-lifetime dynamic tool.",
        steps=[
            MigrationStep(
                instruction="Pass the output model and submission gate through TurnRequest. "
                "Remove direct dynamic_tool/DynamicToolCall use for submission; expose "
                "application tools through MCP. Untyped turns, changed schemas and resumed "
                "threads are supported without catching CodexSchemaRebindingError."
            ),
            MigrationStep(
                instruction="Configure correction on CodexSessionConfig to bound validation "
                "retries. Handle StructuredOutputError for exhausted output validation, "
                "and UnsupportedCapability for native controls that cannot be enforced."
            ),
        ],
    ),
    Migration(
        subjects=["REPOSITORY_URL", "GitSource.url"],
        reason="Repository identity is configured by each consumer; the library "
        "carries no hosting account or implicit upstream URL.",
        steps=[
            MigrationStep(
                instruction="Pass url when constructing GitSource. Replace imports of "
                "REPOSITORY_URL with repository_url(root), or supply your own URL. "
                "For CLI use, pass dev library git --url <repository>, keep an existing "
                "Git dependency pin, or configure the scaffold's named project in "
                "sync.json.local with its url or checkout path."
            ),
            MigrationStep(
                instruction="Declare publication URLs in your package metadata when "
                "needed. Dependency tracker routing follows the configured library "
                "source; project issue routing continues to use its own origin."
            ),
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
