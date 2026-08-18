"""Native launch flows: runtime preflight, then the Claude and Codex launchers.

Each launcher regenerates its target's artifacts, verifies every claimed
native requirement against a live probe, and hands the terminal to the
native CLI with the non-interactive environment applied.
"""

import json
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import sh
import typer
from pydantic import BaseModel

from lup.runtime.profiles import ProfileDirectory
from lup.adapters.claude.transcripts import ClaudeTranscripts
from lup.adapters.codex.harness_runtime import (
    CodexPluginInstaller,
    PluginCacheConfig,
)
from lup.adapters.codex.transcripts import CodexTranscripts
from lup.harness.environment import non_interactive_environment
from lup.harness.models import Plugin
from lup.harness.process import LocalProcessLauncher
from lup.telemetry.journal import (
    ArgvRedaction,
    TraceActor,
    TraceContext,
    TraceJournal,
)
from lup.telemetry.native import NativeTranscripts, NativeTranscriptWatcher
from lup.types import EnvVars, JsonObject, JsonValue
from lup.workspace.paths import notes_path, project_root
from lup.adapters.codex.home import (
    CodexWorktreeHomeStore,
    login_state,
    select_codex_home,
)
from lup.devtools.dev.branches import settle_base_freshness
from lup.devtools.harness.drift import generate_with_report
from lup.devtools.harness.generate import NativeHarnessComposition
from lup.devtools.dev.worktree import RelocationHint
from lup.devtools.layout import get_tree_dir


def relocation_hint(worktree_path: Path) -> RelocationHint:
    """Name the follow-through in the vocabulary of the running harness.

    Each launcher exports its own configuration home, so a session that
    reached here through one of them is told the move it actually supports.
    Anything else gets the portable shell form alone rather than the name of
    a tool that runtime may not have.
    """
    environ = os.environ  # lup: ignore[os-environ]
    move = f"cd /; cd {worktree_path}"
    if "CLAUDE_CONFIG_DIR" in environ:
        return RelocationHint(
            agent="EnterWorktree(path=<the path above>)",
            shell=f"{move}; claude",
        )
    if "CODEX_HOME" in environ:
        return RelocationHint(
            agent="start a session there — this runtime cannot relocate a running one",
            shell=f"{move}; codex",
        )
    return RelocationHint(agent="", shell=move)


def ready_to_open(composition: NativeHarnessComposition, generate_only: bool) -> bool:
    """Generate this target's artifacts and clear every gate standing before a session.

    Both launchers reach a session through here, so a gate added once is a
    gate every entry point makes — including one written later, which cannot
    open a session without first generating the artifacts it opens against.
    Answers whether to go on: a generate-only invocation has already done
    everything it was asked for.

    Settling the base is one of those steps rather than a workflow's own. A
    tree whose base has moved is self-consistent and says nothing about it, so
    a session opened on one plans and edits against code that is no longer
    there — which cost a planning pass over thirteen concerns on a tree ten
    commits behind its remote, where two merged pull requests had already done
    part of the work being planned. Being behind is not itself grounds for
    refusing a session, so what happens here is a sync and a report: a clean
    checkout is brought level with its own remote, and a base that has moved
    is named on the way in.
    """
    generate_with_report(composition)
    if generate_only:
        return False
    runtime_preflight(composition)
    settle_base_freshness(LocalProcessLauncher(), project_root())
    return True


class HarnessTranscript(BaseModel, arbitrary_types_allowed=True):
    """Canonical journal and native watcher owned by one CLI launch.

    An interactive CLI owns its terminal, so a launch cannot be wrapped the way
    an SDK session is. Mirroring what the CLI persists into a journal of our own
    is what makes a hand-driven session produce the same observable trace a
    programmatic run does -- and what a launch path that starts nothing quietly
    takes away, since a trace nobody wrote is indistinguishable from a session
    nobody ran.
    """

    journal: TraceJournal
    watcher: NativeTranscriptWatcher
    diagnostics: logging.Handler

    def close(self, *, succeeded: bool) -> None:
        """Stop ingestion, record the outcome, and release the diagnostics log."""
        self.watcher.stop()
        self.journal.emit("run_end", {"succeeded": succeeded})
        watcher_logger().removeHandler(self.diagnostics)
        self.diagnostics.close()


def watcher_logger() -> logging.Logger:
    """The logger the native transcript watcher reports its own failures on."""
    return logging.getLogger(NativeTranscriptWatcher.__module__)


def capture_watcher_diagnostics(run_directory: Path) -> logging.Handler:
    """Send watcher diagnostics to a file for the life of one launch.

    The launcher hands its terminal to an interactive CLI that draws over the
    whole screen. Nothing configures logging on this path, so a watcher failure
    would reach Python's last-resort handler and print a traceback into that UI
    -- which is how a recovered polling error came to look like a crash. The
    durable record is the journal's own error event; this file is for the detail
    that does not belong in it.
    """
    run_directory.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(run_directory / "watcher.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = watcher_logger()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return handler


def start_harness_transcript(
    provider: str,
    transcripts: NativeTranscripts,
    *,
    model: str | None,
    profile: str | None,
    arguments: list[str],
) -> HarnessTranscript:
    """Start one canonical transcript around a native interactive CLI.

    The runtime arrives as its own transcript reader rather than as a directory
    to scan, because where a runtime keeps its sessions and how one of its
    records names itself are the runtime's business, not this launcher's.
    """
    run_id = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{provider}_{uuid4().hex[:8]}"
    )
    trace_path = notes_path() / "harness" / provider / run_id / "observable.jsonl"
    journal = TraceJournal(
        trace_path,
        TraceContext.root(
            run_id,
            TraceActor(
                kind="harness",
                name=f"lup-devtools harness {provider}",
                provider=provider,
                model=model,
            ),
        ),
    )
    # An argv vector reaches the journal only redacted: these are the words a
    # caller typed, and a credential passed as an option value is a value the
    # key-name redaction cannot see.
    safe_arguments: list[JsonValue] = list(ArgvRedaction().arguments(arguments))
    payload: JsonObject = {
        "provider": provider,
        "model": model,
        "profile": profile,
        "arguments": safe_arguments,
    }
    journal.emit("run_start", payload)
    watcher = NativeTranscriptWatcher(
        transcripts,
        journal.child(
            TraceActor(
                kind="native_agent",
                name=provider,
                provider=provider,
                model=model,
            )
        ),
        scope=project_root(),
    )
    diagnostics = capture_watcher_diagnostics(trace_path.parent)
    watcher.start()
    typer.echo(f"{provider} observable transcript: {trace_path}")
    return HarnessTranscript(journal=journal, watcher=watcher, diagnostics=diagnostics)


def runtime_preflight(composition: NativeHarnessComposition) -> None:
    """Verify each claimed native requirement immediately before launch."""
    target = composition.recipe.label
    evidence = composition.readiness()
    for item in evidence:
        state = "ready" if item.supported else "missing"
        typer.echo(f"{target} {item.capability}: {state} ({item.version})")
    if any(not item.supported for item in evidence):
        raise typer.BadParameter(f"{target} runtime preflight failed")


def codex_login_preflight(home: Path, environment: EnvVars) -> None:
    """Offer the sign-in a launch needs, rather than failing inside a session.

    An unusable login does not stop Codex from starting; it surfaces later as
    an authentication error against whichever service is reached first, which
    names neither the home the credential came from nor the way to fix it.
    Declining is respected — a session can still be useful offline.
    """
    state = login_state(home)
    if state.usable_at(datetime.now(UTC)):
        return
    reason = (
        f"expired {state.expires_at:%Y-%m-%d}"
        if state.expires_at is not None
        else "not signed in"
    )
    typer.echo(f"Codex login in {home}: {reason}")
    if not typer.confirm("Sign in to Codex now?", default=True):
        typer.echo("Continuing unauthenticated — Codex will report its own errors")
        return
    try:
        sh.Command("codex")(
            "login", _fg=True, _env={**environment, "CODEX_HOME": str(home)}
        )
    except sh.ErrorReturnCode as error:
        raise typer.BadParameter("Codex sign-in did not complete") from error


def apply_sandbox_environment(
    plugin: Plugin,
    environment: EnvVars,
    label: str,
    required_tools: list[str],
) -> None:
    """Export LUP_SANDBOX_ACTIVE when the declared sandbox can actually run.

    The dispatchers defer unjudged shell only under this flag, so it is set
    exactly when the launch verified the OS boundary; without it the deny
    lattice keeps carrying the escalation recipe.
    """
    hooks = plugin.hooks
    if hooks is None or hooks.sandbox is None:
        return
    missing = [tool for tool in required_tools if shutil.which(tool) is None]
    if missing:
        typer.echo(
            f"{label} sandbox: missing {', '.join(missing)} — deny lattice stays active"
        )
        return
    environment["LUP_SANDBOX_ACTIVE"] = "1"
    typer.echo(f"{label} sandbox: active — unjudged shell defers to the OS boundary")


# lup: ignore[library-default] — each entry is literally a Codex CLI flag
CODEX_SANDBOX_OVERRIDES = (
    "-s",
    "--sandbox",
    "--full-auto",
    "--yolo",
    "--dangerously-bypass-approvals-and-sandbox",
)


def codex_sandbox_arguments(
    plugin: Plugin, environment: EnvVars, extra_args: list[str]
) -> list[str]:
    """Compose the interactive Codex envelope that LUP_SANDBOX_ACTIVE vouches for.

    The launcher establishes the boundary it announces: an explicit
    workspace-write sandbox on the Codex command line, mirroring how the
    Claude settings artifact compiles the same declaration into an OS wall.
    Path-level write and credential denials have no Codex equivalent, and
    neither does taking one command out of the envelope, so the envelope is
    the declaration's strict subset (network stays off). The dispatcher still
    reads the exclusions, judging those commands as though nothing confined
    them — which is the strict direction here too, since an envelope with no
    network is not a boundary they would have survived either. When the
    caller supplies its own sandbox flag the launcher vouches for nothing:
    the flag stays unset and the deny lattice keeps the escalation recipe.
    """
    hooks = plugin.hooks
    if hooks is None or hooks.sandbox is None:
        return []
    overrides = [
        word
        for word in extra_args
        if word in CODEX_SANDBOX_OVERRIDES or word.startswith("--sandbox=")
    ]
    if overrides:
        typer.echo(
            f"codex sandbox: caller envelope ({' '.join(overrides)}) — "
            "deny lattice stays active"
        )
        return []
    environment["LUP_SANDBOX_ACTIVE"] = "1"
    typer.echo(
        "codex sandbox: workspace-write envelope — "
        "unjudged shell defers to the OS boundary"
    )
    return ["--sandbox", "workspace-write", *writable_root_arguments()]


def writable_root_arguments() -> list[str]:
    """Widen the workspace-write root to the tree/ holding sibling worktrees.

    Codex roots writes at the launch directory, so a feature worktree this
    project's own workflow prescribes creating lands outside the boundary
    and cannot be edited from the session that created it.
    """
    try:
        tree = get_tree_dir()
    except (typer.Exit, SystemExit):
        return []
    return ["-c", f'sandbox_workspace_write.writable_roots=["{tree}"]']


def claude_sandbox_arguments(plugin: Plugin) -> list[str]:
    """Widen the Claude sandbox's writable set over the same sibling tree/.

    Claude roots writes at the working directory just as Codex does, so a
    second checkout is read-only to every command a session runs — and
    running the toolchain over one is ordinary work here, which is why the
    symptom arrives as pytest failing to write a cache and `ruff format`
    refusing to save. Neither error names a sandbox.

    The path is this machine's, so it is resolved at launch and passed as
    settings rather than declared: an artifact carrying an absolute path
    would be drift in every other checkout. The declared writable paths ride
    along rather than being left to the generated file, because the two
    surfaces document this key differently — arrays that merge across
    scopes, values that override per session — and a list carrying both is
    the same list under either reading.
    """
    hooks = plugin.hooks
    if hooks is None or hooks.sandbox is None:
        return []
    try:
        tree = get_tree_dir()
    except (typer.Exit, SystemExit):
        return []
    allowed = [*hooks.sandbox.writable_paths, str(tree)]
    widened = {"sandbox": {"filesystem": {"allowWrite": allowed}}}
    return ["--settings", json.dumps(widened)]


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


def launch_claude(
    composition: NativeHarnessComposition,
    extra_args: list[str],
    profiles: ProfileDirectory,
    profile: str | None,
    model: str | None,
    generate_only: bool,
) -> None:
    """Generate/reconcile Claude artifacts and launch the verified local plugin."""
    plugin = composition.recipe.source.plugins[0]
    if not ready_to_open(composition, generate_only):
        return
    arguments: list[str] = []
    if model is not None:
        arguments.extend(["--model", model])
    root = project_root()
    named = [
        root / ".claude" / "plugins" / plugin.name,
        *companion_plugin_directories(root, plugin.name),
    ]
    arguments.extend(
        [
            *[flag for directory in named for flag in ("--plugin-dir", str(directory))],
            *claude_sandbox_arguments(plugin),
            *extra_args,
        ]
    )
    environment = non_interactive_environment(os.environ)  # lup: ignore[os-environ]
    apply_sandbox_environment(plugin, environment, "claude", ["bwrap", "socat"])
    # A name no origin answers to reaches here from an explicit --profile, and
    # from an active selection whose profile has since gone; both are the
    # caller's to fix, so neither should arrive as a traceback.
    try:
        home = profiles.launch_home(profile)
    except KeyError as error:
        raise typer.BadParameter(str(error)) from error
    if home is not None:
        environment.update(profiles.login.environment(home))
    transcript = start_harness_transcript(
        "claude",
        ClaudeTranscripts(home),
        model=model,
        profile=profile,
        arguments=arguments,
    )
    succeeded = False
    try:
        sh.Command("claude")(*arguments, _fg=True, _env=environment)
        succeeded = True
    except sh.CommandNotFound as error:
        raise typer.BadParameter("Claude Code CLI is not installed") from error
    except sh.ErrorReturnCode as error:
        raise typer.Exit(error.exit_code) from error
    finally:
        transcript.close(succeeded=succeeded)


def launch_codex(
    composition: NativeHarnessComposition,
    extra_args: list[str],
    codex_home: Path | None,
    profile: str | None,
    model: str | None,
    generate_only: bool,
    force_install: bool,
) -> None:
    """Generate/reconcile Codex artifacts and launch without updating the CLI."""
    plugin = composition.recipe.source.plugins[0]
    if not ready_to_open(composition, generate_only):
        return
    environment = non_interactive_environment(os.environ)  # lup: ignore[os-environ]
    envelope = codex_sandbox_arguments(plugin, environment, extra_args)
    store = CodexWorktreeHomeStore()
    home = select_codex_home(codex_home, environment, project_root(), profile, store)
    selected_home = home.path
    if home.isolated:
        typer.echo(f"Using worktree-scoped Codex home: {selected_home}")
    codex_login_preflight(selected_home, environment)
    installer = CodexPluginInstaller(
        PluginCacheConfig(codex_home=selected_home, marketplace=plugin.marketplace)
    )
    arguments: list[str] = list(envelope)
    if profile is not None:
        arguments.extend(["--profile", profile])
    if model is not None:
        arguments.extend(["--model", model])
    arguments.extend(extra_args)
    environment["CODEX_HOME"] = str(selected_home)
    transcript = start_harness_transcript(
        "codex",
        CodexTranscripts(selected_home),
        model=model,
        profile=profile,
        arguments=arguments,
    )
    succeeded = False
    try:
        with installer.temporary(
            project_root() / ".codex" / "plugins" / plugin.name,
            project_root(),
            force=force_install,
        ) as cache:
            typer.echo(f"Verified installed Codex plugin: {cache.installed_root}")
            sh.Command("codex")(*arguments, _fg=True, _env=environment)
        succeeded = True
    except sh.CommandNotFound as error:
        raise typer.BadParameter("Codex CLI is not installed") from error
    except sh.ErrorReturnCode as error:
        raise typer.Exit(error.exit_code) from error
    finally:
        transcript.close(succeeded=succeeded)
        if home.isolated and store.publish(project_root()):
            typer.echo("Returned the refreshed Codex login to the account home")
