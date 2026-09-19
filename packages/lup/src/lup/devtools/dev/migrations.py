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
        subjects=[
            "PYTHON_SUFFIXES",
            "MARKDOWN_SUFFIXES",
            "JS_SUFFIXES",
            "JSON_SUFFIXES",
        ],
        reason=(
            "the marker scanner routes a file by one dict from suffix to scan "
            "mode, where four parallel tuples each guarded an arm of a match "
            "that decided on nothing the subject carried"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Read `SCAN_MODES` from `lup.harness.codescan.markers` where "
                    "one of the suffix tuples was read: its keys are the suffixes "
                    "and its values the `ScanMode` each routes to, so the "
                    "suffixes of one mode are the keys whose value is that mode."
                ),
            ),
        ],
    ),
    Migration(
        subjects=[
            "AntiPatternSet",
            "AntiPatternSet.python",
            "AntiPatternSet.typescript",
            "AntiPatternSet.for_suffix",
            "AntiPatternSet.selected",
            "antipattern_set_for",
        ],
        reason=(
            "the set holds every rule a project is judged by — the line rules, "
            "the project rules the sweep runs, and the composition rule "
            "generation runs — so it is named for what it holds"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Import `RuleSet` from `lup.harness.codescan.antipatterns` "
                    "where `AntiPatternSet` was imported, and `rule_set_for` where "
                    "`antipattern_set_for` was; the fields and methods keep their "
                    "names, and `project` and `composition` stand beside `python` "
                    "and `typescript`."
                ),
            ),
        ],
    ),
    Migration(
        subjects=[
            "AntiPattern.id",
            "AntiPattern.examples",
            "AntiPattern.message",
            "AntiPattern.refinement",
            "AntiPattern.strength",
            "AntiPattern.examples_bound_the_rule",
            "STRUCTURAL_RULES",
            "anti_pattern_rules",
        ],
        reason=(
            "every rule is one declaration: what every rule states moved to the "
            "`Rule` base that `AntiPattern`, `ProjectRule` and `CompositionRule` "
            "share, and the reference derives every card from the set instead "
            "of keeping the structural ones by hand"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "A caller constructing or reading an `AntiPattern` changes "
                    "nothing: the fields are inherited. One that read "
                    "`STRUCTURAL_RULES` or `anti_pattern_rules()` reads "
                    "`all_rules()`, which derives every card. A project declaring "
                    "a rule the sweep decides declares a `ProjectRule` from "
                    "`lup.harness.codescan.project` beside its audit and adds it "
                    "to its set's `project` list."
                ),
            ),
        ],
    ),
    Migration(
        subjects=["member_environment"],
        reason=(
            "a launcher mints a session's name beside its id, numbered against "
            "the live sessions of the repository so two sessions in one "
            "worktree are reachable apart, and exports the two together"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Where `member_environment(member_id)` was exported, call "
                    "`launched_member(root)` from `lup.coordination.repository` "
                    "and export its `.environment()`; a caller holding an id "
                    "and a name of its own builds a `LaunchedMember` and "
                    "exports that."
                ),
            ),
        ],
    ),
    Migration(
        commit="cf72246a2",
        subjects=[
            "NATIVE_SPELLING_RULE_ID",
            "KERNEL_IMPORT_RULE_ID",
            "LIBRARY_DEFAULT_RULE_ID",
            "CONSTANT_DECLARATION_RULE_ID",
        ],
        reason=(
            "the boundary scanner's rule ids are one enumeration: several audits "
            "share that module, and a constant apiece said the same thing as "
            "many times as there were suppression comments naming it, so "
            "`RuleId` says it once"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Read the id off `RuleId` instead: `RuleId.NATIVE_SPELLING`, "
                    "`RuleId.KERNEL_IMPORTS`, `RuleId.LIBRARY_DEFAULT` and "
                    "`RuleId.CONSTANT_DECLARATION`, all from "
                    "`lup.harness.codescan.boundaries`. Note the plural in the "
                    "second, whose constant was singular. Each carries the same "
                    "string it always did and the type is a `StrEnum`, so a "
                    "comparison against a rule id read from anywhere else -- a "
                    "directive, a deny message, the generated reference -- holds "
                    "without being converted."
                ),
            ),
        ],
    ),
    Migration(
        commit="a329d017d",
        subjects=[
            "changes_runtime_source",
            "prompt_command",
            "prompt_entry",
            "prompt_artifacts",
        ],
        reason=(
            "the roster's prompt hook became one guard serving the arriving and "
            "the departing event alike, so none of these names a thing that is "
            "only about the prompt any more, and each has to be told which "
            "script and which runtime module it is building for"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Call `runtime_source(module)` for `changes_runtime_source()`, "
                    "`guard_command(plugin_root_env, guard_script)` for "
                    "`prompt_command(plugin_root_env)`, and "
                    "`hook_entry(plugin_root_env, guard_script)` for "
                    "`prompt_entry(plugin_root_env)`. The added argument is which "
                    "guard the entry points at, and a caller that had one hook "
                    "passes the script it was already generating."
                ),
            ),
            MigrationStep(
                instruction=(
                    "Call `roster_artifacts` for `prompt_artifacts`. It keeps "
                    "`plugin_root`, `semantic_id` and `event` and adds "
                    "`guard_script`, `runtime_module`, `source_file` and "
                    "`origin` -- what the one prompt guard used to hold as its "
                    "own constants, passed now that two events render it."
                ),
            ),
        ],
    ),
    Migration(
        commit="05c5b945e",
        subjects=["CallToolResultWithAlias", "CallToolResultWithAlias.is_error"],
        reason=(
            "in-process MCP servers are built on the mcp 2.x server API, whose "
            "result already answers to `is_error`; the subclass existed only to "
            "alias `isError` onto the snake-case spelling an SDK query runner "
            "looked for, and it has nothing left to translate"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Drop the subclass and let the server's own result stand. A "
                    "caller that built one to get the alias reads `is_error` off "
                    "the response envelope instead -- which is what a `@lup_tool` "
                    "handler's failure already crosses as, and what "
                    "`mcp_response(text, is_error=True)` sets."
                ),
            ),
        ],
    ),
    Migration(
        commit="625532040",
        subjects=["refuse_a_blocked_registration"],
        reason=(
            "a merge-driver registration a contained session cannot make no "
            "longer refuses the worktree: the registration is the host's "
            "once-per-clone act, and the checkout is usable without it, so the "
            "pre-flight reports the gap and answers whether it is blocked "
            "instead of stopping"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Call `report_a_blocked_registration` where the refusal was "
                    "called; it returns whether the registration is blocked, "
                    "which a caller that made the worktree conditional on it "
                    "reads instead of catching the exit."
                ),
            ),
        ],
    ),
    Migration(
        commit="d0af16a1b",
        subjects=[
            "repository_worktrees",
            "WriteFacts.worktrees",
            "ShellContext.repository_worktrees",
            "redirected_verb_only_reads",
            "redirect_stays_in_this_repository",
        ],
        reason=(
            "a git directory redirect is a value flag and nothing more: the verb "
            "behind `-C`, `--git-dir` and `--work-tree` is judged by its own row "
            "in the other tree, as `cd there && git <verb>` always was, so the "
            "guard that asked about the redirect and the worktree list it was "
            "measured against have nothing left to decide"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Drop the `repository_worktrees` argument from any call into "
                    "`decide_shell`, `classify_shell` or `shell_context`, and "
                    "the `worktrees` key from a `WriteFacts` a project builds by "
                    "hand; a project's own shell vocabulary needs no change, and "
                    "a git rule that listed the directory flags under "
                    "`ask_flags` keeps them under `value_flags` alone."
                ),
            ),
        ],
    ),
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
    Migration(
        subjects=[
            "standing",
            "unsaid",
            "gone",
            "member_of",
            "RepositoryPeers.pulsed",
            "RepositoryPeers.rewound",
            "RosterRecord.applied",
            "ActorSpawned.applied",
            "ActorJoined.applied",
            "ActorDescribed.applied",
            "ActorFinished.applied",
            "TouchRecord.claim",
            "TouchRecord.applied",
            "PathTouched.claim",
            "PathTouched.applied",
            "PathContested.claim",
            "PathContested.applied",
            "PrefixLocked.claim",
            "PrefixLocked.applied",
            "PrefixReleased.claim",
            "PrefixReleased.applied",
            "PathVacated.claim",
            "PathVacated.applied",
            "stream_records",
            "peer_members",
            "peer_heard",
            "peer_present",
            "peer_name_claims",
            "peer_addresses",
            "peer_listing",
            "claim_covers",
            "peer_claims",
        ],
        reason=(
            "the coordination store was folded by three hand-kept readers that "
            "shared no import — the typed library, the prompt-time hook and the "
            "compiled permission dispatcher — so every record the store gained "
            "had to be taught to each separately, and one that missed a record "
            "went on answering confidently about a store it no longer "
            "understood; there is now one fold, `lup.coordination.bare.store`, "
            "which every reader imports and each plugin ships"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Fold the roster with `store.members(roster_path)`, and read "
                    "it as the pulses and resets leave it with "
                    "`store.present(root)`, which applies both. What a record "
                    "makes of a member is `store.applied` and is no longer a "
                    "method on the record: `ActorJoined` and its siblings are "
                    "writers now, and the fold takes them off disk without "
                    "importing them."
                ),
            ),
            MigrationStep(
                instruction=(
                    "`RepositoryPeers.pulsed` and `.rewound` are `store.pulsed` "
                    "and `store.rewound`; `RepositoryPeers.present()` applies "
                    "both already and is what a caller wanted from either."
                ),
            ),
            MigrationStep(
                instruction=(
                    "Claims fold with `store.claims(root)`, narrow to live "
                    "holders with `store.held(root, live)`, and answer a path "
                    "with `store.covering(root, path, live)`. `Claim.covers`, "
                    "`.subject` and `.vacant` still answer for a typed caller, "
                    "over that same fold."
                ),
            ),
            MigrationStep(
                instruction=(
                    "The dispatcher's half is gone from `lup.policy.assets."
                    "host`: `peer_addresses` and `peer_listing` are "
                    "`store.addresses` and `store.listing`, `claim_holders` is "
                    "`store.claim_holders`, `record_claims` is "
                    "`store.record_claims`, and each takes the coordination "
                    "directory `peer_store` still resolves rather than a "
                    "project root and a list of file names."
                ),
            ),
        ],
    ),
    Migration(
        subjects=[
            "PeerPolicy.roster_file",
            "PeerPolicy.names_file",
            "PeerPolicy.touches_file",
            "PeerPolicy.member_kind",
            "PeerPolicy.heartbeats_dir",
            "PeerPolicy.stale_after_seconds",
        ],
        reason=(
            "the compiled dispatcher imports the shipped fold, which owns every "
            "file name the store is made of, so a policy restating them was the "
            "second spelling that could drift"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "Drop those six from any `PeerPolicy(...)` you build. What "
                    "is left is what the fold cannot know: `store`, the path "
                    "parts beneath the shared git directory; `windows_dir`, the "
                    "dispatcher's own snapshots; `member_env`; and the five "
                    "lines a stopped caller reads. A project that moved its "
                    "store still says so with `store`."
                ),
            ),
        ],
    ),
    Migration(
        subjects=["roster_artifacts", "DEPARTURE_ORIGIN", "DEPARTURE_SOURCE"],
        reason=(
            "a plugin carries the coordination half as one package rather than a "
            "loose file per hook, because the two hooks and the dispatcher all "
            "stand on the same fold"
        ),
        steps=[
            MigrationStep(
                instruction=(
                    "`roster_artifacts` is gone. `store_artifacts(plugin_root, "
                    "semantic_id)` places the package under "
                    "`hooks/runtime/coordination/`, and is called "
                    "unconditionally: it takes no hook set, because the "
                    "dispatcher imports the package whatever a project declared "
                    "about rosters. `hook_artifacts(...)` places one event's "
                    "guard and the entry beside the package that it runs."
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
