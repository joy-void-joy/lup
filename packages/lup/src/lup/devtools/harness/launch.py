"""Native launch flows: runtime preflight, then the Claude and Codex launchers.

Each launcher regenerates its target's artifacts, verifies every claimed
native requirement against a live probe, and hands the terminal to the
native CLI with the non-interactive environment applied.
"""

import json
import logging
import os
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import uuid4

import sh
import typer
from pydantic import BaseModel, Field

from lup.runtime.profiles import ProfileDirectory
from lup.adapters.claude.harness import ClaudeSpellings
from lup.adapters.claude.transcripts import ClaudeTranscripts
from lup.adapters.codex.harness import CodexSpellings
from lup.adapters.codex.harness_runtime import (
    CodexPluginInstaller,
    PluginCacheConfig,
)
from lup.adapters.codex.transcripts import CodexTranscripts
from lup.harness.environment import non_interactive_environment
from lup.harness.models import NativeName, Plugin, Resumption
from lup.harness.requirements import (
    Finding,
    LostCapability,
    Manifest,
    Requirement,
    Run,
    refused,
)
from lup.harness.process import LocalProcessLauncher
from lup.telemetry.journal import (
    ArgvRedaction,
    KeyRedaction,
    PathRedaction,
    PortableRoot,
    Redactions,
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
from lup.devtools.harness.composition import NativeTargets
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

    The wording is asked of the same spelling the guidance is rendered from
    rather than written again here. Restating it is how the two came to
    disagree: the guidance named the move a runtime supports, this named a
    tool, and a workflow change had to find both to land. One of them being
    an adapter method makes that impossible.
    """
    environ = os.environ  # lup: ignore[os-environ]
    move = f"cd /; cd {worktree_path}"
    here = "the path above"
    if "CLAUDE_CONFIG_DIR" in environ:
        return RelocationHint(
            agent=ClaudeSpellings().relocate_session(here),
            shell=f"{move}; claude",
        )
    if "CODEX_HOME" in environ:
        return RelocationHint(
            agent=CodexSpellings().relocate_session(here),
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


@runtime_checkable
class LaunchSession(Protocol):
    """How a launch mode opens whatever its session needs, around one run.

    Runtime-checkable because :class:`LaunchMode` is a pydantic model and an
    arbitrary-typed field is validated by ``isinstance``; the protocol carries
    only ``__call__``, which is exactly what that check can answer.

    Returns a context manager yielding the environment the native CLI is
    launched under, so a mode that has state to hold — a directory to make, a
    pointer to publish, a record to close — holds it for exactly the span the
    CLI is running and gets its exit path for free.

    The journal rather than a directory, because a mode's session usually has
    to be *findable* by a subprocess the CLI spawns, and what identifies one
    run is the trace context the journal already carries.
    """

    def __call__(
        self, *, provider: str, journal: TraceJournal
    ) -> AbstractContextManager[EnvVars]: ...


class LaunchMode(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """One named way of opening a session that the default launch is not.

    A mode is the application's, never the library's: it names a flag, the
    tree generation compiles while it is in force, the model that kind of
    session runs on, where its record is kept, and what has to be open around
    it. The launchers take one and read it; nothing here knows what any
    particular mode is *for*, which is what keeps a downstream project's
    vocabulary out of the framework.
    """

    name: NativeName
    """Spells the flag: a mode named ``syra`` is selected by ``--syra``."""

    help: str = Field(min_length=1)

    targets: NativeTargets
    """What generation compiles while this mode is in force.

    A mode changes the tree rather than only the command line, because the
    thing a mode usually adds — a tool server, a hook, a document — has to
    reach the session through an artifact the runtime reads at startup."""

    model: str | None = None
    """The native model this kind of session runs on, absent an explicit one."""

    record_root: Callable[[], Path] | None = None
    """Where this mode's transcripts are rooted, resolved at launch.

    A callable because the answer is relative to a project root that moves
    between worktrees, and a path captured at import time names the checkout
    the process started in rather than the one it is running against."""

    arguments: Callable[[str], list[str]] | None = None
    """Words this mode adds to the native command line, given the runtime.

    Per runtime because the same intent is spelled differently or not at all:
    a mode that wants its brief in the system prompt has a flag for that on
    one CLI and a generated document on the other, and a seam that could not
    tell them apart would put an unknown option on the second."""

    session: LaunchSession | None = None
    """What must be open while a session of this kind runs."""

    def command_words(self, provider: str) -> list[str]:
        """Words this mode contributes to one runtime's command line, if any."""
        return self.arguments(provider) if self.arguments is not None else []

    def transcript_root(self) -> Path | None:
        """Where this launch keeps its record, resolved now, not at import."""
        return self.record_root() if self.record_root is not None else None

    def opened(
        self, provider: str, journal: TraceJournal
    ) -> AbstractContextManager[EnvVars]:
        """Whatever this mode needs open around the run, or nothing to open.

        An empty environment from :func:`contextlib.nullcontext` rather than a
        branch at the call site, so a launcher holds one shape and a mode
        declaring no session costs it no conditional.
        """
        if self.session is None:
            return nullcontext({})
        return self.session(provider=provider, journal=journal)


class LaunchSelection(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """Which mode a caller's words selected, and what is left for the CLI."""

    mode: LaunchMode | None
    arguments: list[str]


def extract_launch_mode(
    modes: list[LaunchMode], arguments: list[str]
) -> LaunchSelection:
    """Take a declared mode flag out of the words meant for the native CLI.

    Read out of the passthrough vector rather than declared as a command
    option, because the flag's name belongs to a declaration the library
    reads at runtime and a Typer option's name is fixed when its function is
    defined. The launch commands already own unknown options — that is how
    they forward a caller's own arguments — so recognizing a few of them
    first is the same surface, not a new one.
    """
    selected = {f"--{mode.name}": mode for mode in modes}
    chosen = [selected[word] for word in arguments if word in selected]
    if len(chosen) > 1:
        named = ", ".join(f"--{mode.name}" for mode in chosen)
        raise typer.BadParameter(f"launch modes are exclusive; got {named}")
    return LaunchSelection(
        mode=chosen[0] if chosen else None,
        arguments=[word for word in arguments if word not in selected],
    )


def portable_roots() -> list[PortableRoot]:
    """The roots a durable transcript should name by role, not by location.

    The project root, the tree of sibling checkouts around it, and the
    operator's home — between them, everywhere a session's paths come from.
    Ordered widest-last is irrelevant here because the rule sorts by length;
    what matters is that all three are offered, since a payload quoting a
    sibling worktree names none of the other two.
    """
    return [
        PortableRoot(label="<project>", path=project_root()),
        PortableRoot(label="<tree>", path=project_root().parent),
        PortableRoot(label="<home>", path=Path.home()),
    ]


def start_harness_transcript(
    provider: str,
    transcripts: NativeTranscripts,
    *,
    model: str | None,
    profile: str | None,
    arguments: list[str],
    record_root: Path | None = None,
    mode: str | None = None,
) -> HarnessTranscript:
    """Start one canonical transcript around a native interactive CLI.

    The runtime arrives as its own transcript reader rather than as a directory
    to scan, because where a runtime keeps its sessions and how one of its
    records names itself are the runtime's business, not this launcher's.

    ``record_root`` is where the transcript tree is rooted, so a launch mode
    whose records are kept to a different standard keeps them somewhere a
    reader can tell apart without opening one. ``mode`` puts the same fact
    inside the record, because a directory is renameable and a run that has
    been copied out of one should still say what it was.
    """
    run_id = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{provider}_{uuid4().hex[:8]}"
    )
    root = record_root or notes_path() / "harness"
    trace_path = root / provider / run_id / "observable.jsonl"
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
        # A harness transcript is the one journal written to be kept and read
        # later, so it carries the path rule the in-process default does not:
        # what it mirrors is a native CLI's own record, full of this machine's
        # directories in prose no key-name rule can see.
        redaction=Redactions(KeyRedaction(), PathRedaction(portable_roots())),
    )
    # An argv vector reaches the journal only redacted: these are the words a
    # caller typed, and a credential passed as an option value is a value the
    # key-name redaction cannot see.
    safe_arguments: list[JsonValue] = list(ArgvRedaction().arguments(arguments))
    payload: JsonObject = {
        "provider": provider,
        "model": model,
        "profile": profile,
        "mode": mode,
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
    """Verify each claimed native requirement immediately before launch.

    Two rosters, asked in the order their failures matter. The native probes
    answer whether this runtime can host a session at all, and a gap there
    stops the launch. The declared requirements answer what the session will
    be able to *do*, and almost every gap there costs a capability rather
    than the session -- so those are named and the launch continues, which is
    the only posture that works on a machine without a display, a container,
    or an editor attached.
    """
    target = composition.recipe.label
    evidence = composition.readiness()
    for item in evidence:
        state = "ready" if item.supported else "missing"
        typer.echo(f"{target} {item.capability}: {state} ({item.version})")
    if any(not item.supported for item in evidence):
        raise typer.BadParameter(f"{target} runtime preflight failed")
    report_requirements(composition.recipe.source.requirements)


def report_requirements(manifest: Manifest, setting_up: bool = False) -> list[Finding]:
    """Exercise the host-side requirements, printing what each one found.

    Printed on the way past rather than only when something is wrong: a
    capability that is *absent* is exactly the fact a session needs at the
    top of its scrollback, because it is the one the agent inside cannot
    discover except by failing at it.

    *setting_up* widens this to everything checked only at setup, and is off
    for a launch. Two different things live there and both would be wrong to
    repeat: a nicety reported before every session becomes a line people learn
    to skip, along with the line above it that mattered; and an exercise that
    starts a container is a cost no session should pay to be told something
    that was equally true yesterday.
    """
    environ: EnvVars = dict(os.environ)  # lup: ignore[os-environ]
    findings = manifest.check(environ, setting_up=setting_up)
    for finding in findings:
        for line in finding.lines():
            typer.echo(line)
    stopping = refused(findings)
    if stopping:
        raise typer.BadParameter(
            "; ".join(item.requirement.absence.consequence() for item in stopping)
        )
    return findings


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

    Verified by exercising each tool rather than by finding it on PATH. The
    two answers differ exactly where it matters: a confinement binary that is
    installed and cannot start a namespace on this kernel is present and
    useless, and a flag set on its presence tells every dispatcher downstream
    to relax into a boundary that will not be there. Absence and breakage
    both leave the lattice standing, which is the safe direction, and the
    message says which of the two was found rather than only that one was.
    """
    hooks = plugin.hooks
    if hooks is None or hooks.sandbox is None:
        return
    findings = [
        Requirement(
            capability=tool,
            purpose="the OS boundary this launch claims",
            exercise=Run(command=[tool, "--version"]),
            absence=LostCapability(capability="OS confinement"),
        ).check(environment)
        for tool in required_tools
    ]
    unusable = [finding for finding in findings if not finding.working]
    if unusable:
        for finding in unusable:
            typer.echo(
                f"{label} sandbox: {finding.requirement.capability} — {finding.detail}"
            )
        typer.echo(f"{label} sandbox: deny lattice stays active")
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


def announce_relaxed_rules(relaxed: bool, plugin: Plugin) -> None:
    """Say what a relaxed launch retired, and what it did not.

    The launch is the only moment this is legible. The tree it compiles
    carries no rules, so nothing downstream can report their absence — a
    session opened under it simply meets no rule and has no way to tell that
    from a repository with none. So the count is read off the plugin actually
    being opened rather than off the declaration it came from.

    Two consequences ride along because both bite later and neither announces
    itself. The repository is unchanged, so the sweep still holds it to every
    rule and a session that edited freely under this will fail `dev check`.
    And the committed tree has just been rewritten, so a commit made from here
    would carry a plugin nobody declared.
    """
    if not relaxed:
        return
    retired = len(plugin.hooks.rules.retired if plugin.hooks is not None else [])
    typer.echo(f"anti-patterns retired for this session: {retired} rules")
    typer.echo(
        "`dev check --antipatterns` still holds this repository to them; run "
        "`lup-devtools harness generate all` before committing, or the "
        "compiled tree carries a policy nothing declares. To retire them for "
        "good instead, `dev seams --retire-all` writes it where a review sees "
        "it."
    )


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


# It takes a composition, an account, a profile, a model and a passthrough
# vector, and a mode is one optional argument among them; moving it onto
# LaunchMode would make the model answerable for starting a runtime it knows
# nothing about, and leave a project declaring no mode with no launcher at all.
# lup: ignore[model-free-function] — a launcher is not an operation on a mode.
def launch_claude(
    composition: NativeHarnessComposition,
    extra_args: list[str],
    profiles: ProfileDirectory,
    profile: str | None,
    model: str | None,
    generate_only: bool,
    mode: LaunchMode | None = None,
    resume: Resumption = Resumption(),
    relaxed: bool = False,
) -> None:
    """Generate/reconcile Claude artifacts and launch the verified local plugin."""
    contradiction = resume.contradicted()
    if contradiction is not None:
        raise typer.BadParameter(contradiction)
    plugin = composition.recipe.source.plugins[0]
    announce_relaxed_rules(relaxed, plugin)
    if not ready_to_open(composition, generate_only):
        return
    arguments: list[str] = claude_resume_arguments(resume)
    # A mode's model is a default rather than a fixture: it says what this kind
    # of session runs on when nobody said otherwise, and an explicit --model
    # still wins, because overriding the model is why a caller passes one.
    selected_model = model or (mode.model if mode is not None else None)
    if selected_model is not None:
        arguments.extend(["--model", selected_model])
    root = project_root()
    named = [
        root / ".claude" / "plugins" / plugin.name,
        *companion_plugin_directories(root, plugin.name),
    ]
    arguments.extend(
        [
            *[flag for directory in named for flag in ("--plugin-dir", str(directory))],
            *claude_sandbox_arguments(plugin),
            *(mode.command_words("claude") if mode is not None else []),
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
        model=selected_model,
        profile=profile,
        arguments=arguments,
        record_root=mode.transcript_root() if mode is not None else None,
        mode=mode.name if mode is not None else None,
    )
    succeeded = False
    try:
        opening = (
            nullcontext({})
            if mode is None
            else mode.opened("claude", transcript.journal)
        )
        with opening as session:
            environment.update(session)
            sh.Command("claude")(*arguments, _fg=True, _env=environment)
        succeeded = True
    except sh.CommandNotFound as error:
        raise typer.BadParameter("Claude Code CLI is not installed") from error
    except sh.ErrorReturnCode as error:
        raise typer.Exit(error.exit_code) from error
    finally:
        transcript.close(succeeded=succeeded)


# For the reason spelled at `launch_claude`: the mode is one optional argument
# among the ones that actually decide how a runtime starts.
# lup: ignore[model-free-function] — a launcher is not an operation on a mode.
def launch_codex(
    composition: NativeHarnessComposition,
    extra_args: list[str],
    codex_home: Path | None,
    profile: str | None,
    model: str | None,
    generate_only: bool,
    force_install: bool,
    mode: LaunchMode | None = None,
    resume: Resumption = Resumption(),
    relaxed: bool = False,
) -> None:
    """Generate/reconcile Codex artifacts and launch without updating the CLI."""
    contradiction = resume.contradicted()
    if contradiction is not None:
        raise typer.BadParameter(contradiction)
    plugin = composition.recipe.source.plugins[0]
    announce_relaxed_rules(relaxed, plugin)
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
    # The subcommand leads, and everything the envelope carries follows it,
    # because a word placed after a positional session id would be read as
    # another one.
    arguments: list[str] = [*codex_resume_arguments(resume), *envelope]
    if profile is not None:
        arguments.extend(["--profile", profile])
    selected_model = model or (mode.model if mode is not None else None)
    if selected_model is not None:
        arguments.extend(["--model", selected_model])
    arguments.extend(mode.command_words("codex") if mode is not None else [])
    arguments.extend(extra_args)
    environment["CODEX_HOME"] = str(selected_home)
    transcript = start_harness_transcript(
        "codex",
        CodexTranscripts(selected_home),
        model=selected_model,
        profile=profile,
        arguments=arguments,
        record_root=mode.transcript_root() if mode is not None else None,
        mode=mode.name if mode is not None else None,
    )
    succeeded = False
    opening = (
        nullcontext({}) if mode is None else mode.opened("codex", transcript.journal)
    )
    try:
        with (
            installer.temporary(
                project_root() / ".codex" / "plugins" / plugin.name,
                project_root(),
                force=force_install,
            ) as cache,
            opening as session,
        ):
            typer.echo(f"Verified installed Codex plugin: {cache.installed_root}")
            environment.update(session)
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
