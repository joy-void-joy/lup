"""Claude Code's spelling of a launch: the words and settings an interactive CLI starts with."""

import json
from pathlib import Path

from lup.harness.models import HookSet, Resumption
from lup.launch.declaration import LaunchSandbox
from lup.providers.claude.confinement import CLAUDE_SANDBOX_OFF
from lup.sandbox.rail import AccessibleRoot, host_run, in_repository
from lup.types import JsonObject, JsonValue


def claude_resume_arguments(resume: Resumption) -> list[str]:
    """Claude Code's spelling: continuing and resuming are two flags.

    ``--continue`` takes the most recent conversation in the working
    directory and ``--resume`` opens the picker or takes a session id, so a
    request reaches the runtime as words rather than as a mode.
    """
    if resume.session is not None:
        return ["--resume", resume.session]
    if resume.pick:
        return ["--resume"]
    return ["--continue"] if resume.latest else []


def claude_sandbox_settings(
    hooks: HookSet | None,
    sandbox: LaunchSandbox = LaunchSandbox.INNER,
    accessible: list[AccessibleRoot] = [],
    settings: JsonObject | None = None,
    tree: Path | None = None,
) -> JsonObject:
    """What this launch means the Claude sandbox to be, as one settings document.

    ``settings`` is whatever else this launch compiles into that document —
    an effort's ultracode switch — merged in here because the CLI reads one
    ``--settings`` flag, and a second would be read in place of the first.

    Establishing the inner sandbox, that is a widening: Claude roots writes at
    the working directory just as Codex does, so a second checkout is
    read-only to every command a session runs — and running the toolchain over
    one is ordinary work, which is why the symptom arrives as pytest failing
    to write a cache and `ruff format` refusing to save. Neither error names a
    sandbox. ``tree`` is the directory holding this checkout's sibling
    worktrees, and ``None`` where the checkout has none, which leaves the
    sandbox as the project's own settings declare it.

    The declared roots widen it the same way and for the same reason they
    reach the container's mount table: a project registered as reachable is
    one this session is meant to write, and a boundary that admitted it in
    one posture and refused it in the other would make where the session runs
    the thing that decides what it can do.

    For the same reason the container's read-only binds reach it too, as
    ``denyWrite``: each declared repository's shared `config` and `hooks/`,
    read off the lease that makes those binds. A mounted bare clone admits
    its git directory whole, and those two name what the host runs at the
    next git command there -- the documented rule is that a deny holds inside
    a wider allow, and Claude's own protection of `.git/hooks` and
    `.git/config` covers only the working directory.

    The path is this machine's, so it is resolved at launch and passed as
    settings rather than declared: an artifact carrying an absolute path
    would be drift in every other checkout. The declared writable paths ride
    along rather than being left to the generated file, because the two
    surfaces document this key differently — arrays that merge across
    scopes, values that override per session — and a list carrying both is
    the same list under either reading.

    Contained -- or with no sandbox chosen at all -- it is an *off* switch,
    and the artifact still says ``enabled: true`` because that is the right
    answer for the inner-sandbox launch the same file serves. The switch
    itself is spelled by
    :data:`~lup.providers.claude.confinement.CLAUDE_CONFINEMENT` rather than
    here, so the image-side probe that asks whether a session can open at all
    opens the same one this does -- spelled twice, the probe verifies a
    session nobody launches, and refuses for the absence of a confinement no
    launch has ever asked for.

    What the vendor documents in place of the nested sandbox travels with
    that spelling. The measured half belongs here, beside the launcher
    making the choice: in an unprivileged container bubblewrap cannot mount a
    fresh ``/proc`` -- ``Can't mount proc on /newroot/proc: Operation not
    permitted`` -- so the inner sandbox does not start, and the packages
    installed to keep it quiet bought silence rather than a boundary.

    What is lost is narrower than it looks. The credential read denials name
    paths this container never mounts; the human-owned write denials are
    still surfaced as approvals by the semantic policy; ``excludedCommands``
    was already inert here, because the container never agreed to leave any
    command alone. The domain allowlist is not a wall either -- it
    pre-approves rather than refuses, and ``strictAllowlist`` has no effect
    from a repository's own settings — and what does refuse is the egress
    proxy, which is untouched by this.
    """
    carried = settings or {}

    def document(sandboxed: JsonObject) -> JsonObject:
        return {**sandboxed, **carried}

    if hooks is None or hooks.sandbox is None:
        return document({})
    if sandbox is not LaunchSandbox.INNER:
        return document(CLAUDE_SANDBOX_OFF)
    if tree is None:
        return document({})
    allowed: list[JsonValue] = [
        *hooks.sandbox.writable_paths,
        str(tree),
        *[str(item.path) for item in accessible if item.writable],
    ]
    held: list[JsonValue] = [
        str(path)
        for item in accessible
        if item.writable and in_repository(item.path)
        for path in host_run(item.path)
    ]
    filesystem: JsonObject = {
        "allowWrite": allowed,
        **({"denyWrite": held} if held else {}),
    }
    return document({"sandbox": {"filesystem": filesystem}})


def claude_sandbox_arguments(
    hooks: HookSet | None,
    sandbox: LaunchSandbox = LaunchSandbox.INNER,
    accessible: list[AccessibleRoot] = [],
    settings: JsonObject | None = None,
    tree: Path | None = None,
) -> list[str]:
    """The ``--settings`` flag carrying :func:`claude_sandbox_settings`, or nothing."""
    merged = claude_sandbox_settings(hooks, sandbox, accessible, settings, tree)
    return ["--settings", json.dumps(merged)] if merged else []


def companion_plugin_directories(root: Path, generated: str) -> list[Path]:
    """The plugin directories this checkout carries beside the generated one.

    A project may keep a hand-written plugin next to the one the harness
    compiles. Its only other way into a session is a marketplace, and a
    marketplace name is one global namespace shared by every checkout
    declaring it — so the plugin a session loaded is whichever tree
    registered that name last, the same hazard `lease_plugin_dir` documents.
    A directory carrying `.claude-plugin/plugin.json` is a plugin by its own
    declaration, which is why nothing here needs to be written down twice.

    Sorted, so what a launch names does not depend on directory order.
    """
    plugins = root / ".claude" / "plugins"
    if not plugins.is_dir():
        return []
    return sorted(
        directory
        for directory in plugins.iterdir()
        if directory.name != generated
        and (directory / ".claude-plugin" / "plugin.json").is_file()
    )
