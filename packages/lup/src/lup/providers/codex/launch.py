"""Codex's spelling of a launch: the words and overrides an interactive CLI starts with."""

import json
from pathlib import Path

from lup.harness.models import HookSet, Resumption
from lup.harness.notice import Notice
from lup.harness.toolchain import codex_envelope_requirement
from lup.launch.boundary import apply_sandbox_environment
from lup.launch.declaration import LaunchSandbox
from lup.providers.codex.confinement import CODEX_CONFINEMENT
from lup.sandbox.rail import AccessibleRoot, working_trees
from lup.types import EnvVars

# lup: ignore[library-default] — each entry is literally a Codex CLI flag
CODEX_SANDBOX_OVERRIDES = (
    "-s",
    "--sandbox",
    "--approve-for-me",
    "--not-so-yolo",
    "--yolo",
    "--dangerously-bypass-approvals-and-sandbox",
)
"""Every Codex flag by which a caller picks the sandbox itself, aliases included.

``--yolo`` and ``--not-so-yolo`` are the CLI's hidden aliases of the two long
flags after them. ``--approve-for-me`` names workspace-write on its own, and
Codex refuses it beside ``--sandbox``, so the launcher cannot add one."""


def codex_resume_arguments(resume: Resumption) -> list[str]:
    """Codex's spelling: reopening is a subcommand, and it leads the vector.

    The same three requests, in the shape this runtime has for them —
    ``resume`` alone is the picker, ``--last`` is the most recent, and a
    session id is positional. It comes first because a subcommand does, which
    is the whole of why the two cannot share one word list.
    """
    if resume.session is not None:
        return ["resume", resume.session]
    if resume.pick:
        return ["resume"]
    return ["resume", "--last"] if resume.latest else []


def codex_sandbox_arguments(
    hooks: HookSet | None,
    environment: EnvVars,
    extra_args: list[str],
    sandbox: LaunchSandbox = LaunchSandbox.INNER,
    accessible: list[AccessibleRoot] = [],
    tree: Path | None = None,
) -> list[str]:
    """Compose the interactive Codex envelope that LUP_SANDBOX_ACTIVE vouches for.

    Establishing the inner sandbox, the launcher builds the boundary it
    announces: an explicit workspace-write sandbox on the Codex command line,
    mirroring how the Claude settings artifact compiles the same declaration
    into an OS wall. Path-level write and credential denials have no Codex
    equivalent, and neither does taking one command out of the envelope, so
    the envelope is the declaration's strict subset (network stays off). The
    dispatcher still reads the exclusions, judging those commands as though
    nothing confined them — which is the strict direction here too, since an
    envelope with no network is not a boundary they would have survived
    either. When the caller supplies its own sandbox flag the launcher vouches
    for nothing: the flag stays unset and the deny lattice keeps the
    escalation recipe.

    Contained, that same envelope is wrong in a way that has nothing to do
    with strictness, and what stands in its place is spelled by
    :data:`~lup.providers.codex.confinement.CODEX_CONFINEMENT` rather than
    here -- which carries why, and is where the image-side probe reads the
    same words rather than inventing its own. This is the counterpart of
    Claude's off switch, and it is what "every runtime, in the same change"
    means for a posture: one concept, each runtime's own word for it.

    Choosing no sandbox at all spells the same off switch on the host, and
    the notice says which wall holds instead: none, so the deny lattice
    stays standing and every unjudged command keeps its escalation recipe.

    LUP_SANDBOX_ACTIVE stays unset in both of those, because neither session
    relies on it -- the kernel reads the containment out of what the launch
    measured, and a boundary that was observed is a boundary whether this
    flag vouched for it or not, while a session with no boundary wants the
    lattice the flag would relax.
    """
    if hooks is None or hooks.sandbox is None:
        return []
    overrides = [
        word
        for word in extra_args
        if word in CODEX_SANDBOX_OVERRIDES or word.startswith("--sandbox=")
    ]
    if overrides:
        Notice(
            text=(
                f"codex sandbox: caller envelope ({' '.join(overrides)}) — "
                "deny lattice stays active"
            ),
            urgency="warning",
        ).say()
        return []
    match sandbox:
        case LaunchSandbox.OUTER:
            Notice(
                text=(
                    "codex sandbox: off inside the container — "
                    "the container is the boundary, and its proxy is the way out"
                ),
                urgency="boundary",
            ).say()
            return list(CODEX_CONFINEMENT.off)
        case LaunchSandbox.NONE:
            Notice(
                text=(
                    "codex sandbox: off on the host — "
                    "the semantic policy alone judges, and its deny lattice stands"
                ),
                urgency="boundary",
            ).say()
            return list(CODEX_CONFINEMENT.off)
        case LaunchSandbox.INNER:
            pass
    # Exercised before it is vouched for, the way the Claude path exercises
    # its confinement tools. Asserting the flag outright was the asymmetry:
    # `codex sandbox` runs a command under this exact envelope and no model
    # turn, so there was never a reason not to ask.
    vouched = apply_sandbox_environment(
        hooks,
        environment,
        "codex",
        [codex_envelope_requirement()],
        sandbox=sandbox,
        announce=False,
    )
    if vouched:
        Notice(
            text=(
                "codex sandbox: workspace-write envelope — "
                "unjudged shell defers to the OS boundary"
            ),
            urgency="boundary",
        ).say()
    # The envelope goes on either way. What a failed probe withdraws is the
    # claim, not the confinement: leaving the sandbox off because it could not
    # be verified would answer a boundary nobody could measure by removing it.
    return [
        "--sandbox",
        "workspace-write",
        *writable_root_arguments(accessible, tree),
    ]


def writable_root_arguments(
    accessible: list[AccessibleRoot] = [], tree: Path | None = None
) -> list[str]:
    """Widen the workspace-write root to the tree/ holding sibling worktrees.

    Codex roots writes at the launch directory, so a feature worktree this
    project's own workflow prescribes creating lands outside the boundary
    and cannot be edited from the session that created it. ``tree`` is that
    directory, and ``None`` where the checkout keeps no sibling worktrees,
    which widens nothing.

    The declared roots widen it alongside, which is what makes this the same
    change as the Claude settings merge rather than a second policy: one
    registration, and both runtimes' uncontained sandboxes admit it. The
    spelling is each runtime's own -- a settings document there, a dotted
    TOML override here, whose value the CLI parses as TOML and falls back to
    treating as a literal string.

    A root nothing declared writable is left out rather than admitted
    read-only: this key grants writes, and there is no Codex spelling for
    "reachable and not writable" to be faithful to. Reads are not what it
    governs.

    A bare repository is widened to its worktrees rather than to itself. Its
    `config` and `hooks/` name what the host runs, which the container binds
    read-only and Claude's widening denies; this key cannot hold a read-only
    region inside a root, and Codex keeps only a root's `.git` read-only,
    which a bare repository does not have. So the session writes the
    worktrees the clone holds at launch and not its git directory -- which
    also leaves a worktree cut later, and a commit that writes the object
    store, to a later launch or to Claude.
    """
    if tree is None:
        return []
    roots = [
        str(tree),
        *[
            str(checkout)
            for item in accessible
            if item.writable
            for checkout in working_trees(item.path)
        ],
    ]
    # lup: defer: a Codex permission profile can hold `config` and `hooks/`
    # read-only inside a writable root (`[permissions.<name>.filesystem]`,
    # deepest entry wins), which would give a mounted bare clone the whole-
    # clone reach Claude has; it replaces `--sandbox workspace-write`, which
    # overrides a profile, so it is the envelope's redesign and not this key's
    return ["-c", f"sandbox_workspace_write.writable_roots={json.dumps(roots)}"]
