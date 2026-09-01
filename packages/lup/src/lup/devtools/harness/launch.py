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

from lup.providers.login import ProviderLogin
from lup.providers.profiles import ProfileDirectory
from lup.devtools.harness.contained import contained_argv
from lup.providers.claude.confinement import CLAUDE_CONFINEMENT
from lup.providers.claude.harness import ClaudeSpellings
from lup.providers.claude.transcripts import ClaudeTranscripts
from lup.providers.codex.confinement import CODEX_CONFINEMENT
from lup.providers.codex.harness import CodexSpellings
from lup.providers.codex.login import CODEX_LOGIN
from lup.providers.codex.harness_runtime import (
    CodexPluginInstaller,
    PluginCacheConfig,
)
from lup.providers.codex.transcripts import CodexTranscripts
from lup.harness.environment import non_interactive_environment
from lup.harness.models import NativeName, Plugin, Resumption
from lup.harness.notice import Banner, Notice
from lup.harness.requirements import (
    Finding,
    Manifest,
    Requirement,
    refused,
)
from lup.harness.process import LocalProcessLauncher
from lup.harness.toolchain import (
    bubblewrap_requirement,
    container_client,
    for_host,
    socat_requirement,
)
from lup.observability.audit import (
    ArgvRedaction,
    KeyRedaction,
    PathRedaction,
    PortableRoot,
    Redactions,
    TraceActor,
    TraceContext,
    TraceJournal,
)
from lup.observability.native import NativeTranscripts, NativeTranscriptWatcher
from lup.sessions.recursion import MAX_RECURSIVE_AGENT_ENV
from lup.types import EnvVars, JsonObject, JsonValue
from lup.workspace.paths import harness_runs_path, project_root
from lup.providers.codex.home import (
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


@runtime_checkable
class LaunchCheckpoint(Protocol):
    """Application-owned data persistence at native launch boundaries."""

    def __call__(self, *, provider: str) -> None: ...


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
    watcher: NativeTranscriptWatcher | None = None
    diagnostics: logging.Handler | None = None

    def close(self, *, succeeded: bool) -> None:
        """Stop ingestion, record the outcome, and release the diagnostics log."""
        if self.watcher is not None:
            self.watcher.stop()
        self.journal.emit("run_end", {"succeeded": succeeded})
        if self.diagnostics is not None:
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
        self, *, provider: str, journal: TraceJournal, transcribe: bool
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

    model: Callable[[str], str | None] | None = None
    """What this kind of session runs on, given the runtime that will run it.

    Per runtime for the reason :attr:`arguments` is. A model name is one
    provider's vocabulary, so a mode declaring "the best available" means a
    different word on each, and one name shared between them reaches the
    other as a model that does not exist — a failure that arrives from the
    provider's API mid-session, naming neither the mode nor the launch that
    chose it. Absent an explicit ``--model``, which still wins."""

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

    max_recursive_agent: int = Field(default=-1, ge=-1)
    """Mode default when the launcher receives no explicit allowance."""

    recursive_targets: Callable[[int], NativeTargets] | None = None
    """Targets selected from the effective recursive-agent allowance."""

    transcribe_session: Callable[[str], bool] | None = None
    """Whether one runtime's native transcript is mirrored for this mode."""

    def command_words(self, provider: str) -> list[str]:
        """Words this mode contributes to one runtime's command line, if any."""
        return self.arguments(provider) if self.arguments is not None else []

    def native_model(self, provider: str) -> str | None:
        """What this mode runs one runtime on, when it names anything at all."""
        return self.model(provider) if self.model is not None else None

    def transcript_root(self) -> Path | None:
        """Where this launch keeps its record, resolved now, not at import."""
        return self.record_root() if self.record_root is not None else None

    def transcribes(self, provider: str) -> bool:
        """Whether this mode mirrors one provider's native session record."""
        return (
            self.transcribe_session(provider)
            if self.transcribe_session is not None
            else True
        )

    def recursive_agent_limit(self, explicit: int | None) -> int:
        """Resolve an explicit allowance over this mode's default."""
        return self.max_recursive_agent if explicit is None else explicit

    def targets_at(self, allowance: int) -> NativeTargets:
        """The native trees compiled for this allowance."""
        return (
            self.recursive_targets(allowance)
            if self.recursive_targets is not None
            else self.targets
        )

    def opened(
        self, provider: str, journal: TraceJournal, transcribe: bool
    ) -> AbstractContextManager[EnvVars]:
        """Whatever this mode needs open around the run, or nothing to open.

        An empty environment from :func:`contextlib.nullcontext` rather than a
        branch at the call site, so a launcher holds one shape and a mode
        declaring no session costs it no conditional.
        """
        if self.session is None:
            return nullcontext({})
        return self.session(
            provider=provider,
            journal=journal,
            transcribe=transcribe,
        )


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
    transcribe: bool = True,
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
    root = record_root or harness_runs_path()
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
    if not transcribe:
        return HarnessTranscript(journal=journal)
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
    Notice(
        text=f"{provider} observable transcript: {trace_path}",
        urgency="artifact",
    ).say()
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
        Notice(
            text=f"{target} {item.capability}: {state} ({item.version})",
            urgency="ready" if item.supported else "refusal",
        ).say()
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
    # Pointed at this host's client here rather than declared as one, because
    # the declaration is hashed into the ownership digest and a container
    # client is a fact about the machine. This is the only place the
    # exercises actually run, so it is the only place that has to know.
    findings = for_host(manifest, container_client(), project_root()).check(
        environ, setting_up=setting_up
    )
    return reported(findings)


def reported(findings: list[Finding]) -> list[Finding]:
    """Say what each finding found, and stop where absence refuses.

    One place for both halves so the two rosters cannot come to differ about
    what a refusal means. They already had somewhere to differ: the inside
    roster was written after the host one and, printed separately, would have
    been free to treat a refused finding as a line rather than a stop.

    The refusal names the capabilities and stops there. Joining their whole
    consequences into the exception was tried and is unreadable at the size
    this roster reached: four refusals became one nine-line paragraph inside
    an error box, restating word for word what had just been printed above it
    with the causes, the recoveries and the blank lines all flattened out. The
    lines above are the report; this is the exit code and what it was about.
    """
    for finding in findings:
        for notice in finding.notices():
            notice.say()
    stopping = refused(findings)
    if stopping:
        raise typer.BadParameter(
            f"{len(stopping)} of these refuse a session: "
            + ", ".join(item.requirement.capability for item in stopping)
            + ". Each is reported above with its cause and what answers it."
        )
    return findings


def verify_inside(
    manifest: Manifest,
    opening: list[str],
    setting_up: bool = True,
    environment: EnvVars | None = None,
) -> list[Finding]:
    """Exercise the image half behind an argv somebody already assembled.

    Split from :func:`report_inside_requirements` so the launch can use it
    without building the argv a second time. Assembling it starts the egress
    proxy and may build the image, so a second call would not merely be slow
    -- it would print the whole boundary notice again, which reads as the
    launch having done it twice.
    """
    if environment is None:
        environ: EnvVars = dict(os.environ)  # lup: ignore[os-environ]
    else:
        environ = dict(environment)
    return reported(manifest.check_inside(environ, opening, setting_up))


def report_inside_requirements(
    composition: NativeHarnessComposition,
    plugin: Plugin,
    config_home: Path,
    login: ProviderLogin,
) -> list[Finding]:
    """Exercise the image-side requirements inside the container a session opens.

    The half of the manifest that had nowhere to run. An image requirement is
    excluded from the host roster for a good reason -- a laptop without
    ``bun`` is not a laptop with a problem -- and excluded was as far as it
    went: declared, rendered into a package list, never exercised. What that
    bought was a preflight that reported a healthy machine and a session that
    could not resolve its own proxy, because everything the boundary is made
    of sat on the unexercised side.

    Behind the *same* argv a launch opens with, assembled by the same call.
    That is the whole design, and the alternative has already been measured
    wrong twice: an exercise spelled as its own ``run`` verified a container
    with no network, no mounts and no config home, and an exercise spelled
    with its own client verified an engine no session opens through. A probe
    that assembles its own container answers about that container.

    Non-interactive, which is the one deliberate difference. A probe's output
    is captured rather than shown, and ``-it`` against a pipe fails on the
    terminal it was promised.
    """
    harness = composition.recipe.source
    credential = login.credentials_path(config_home)
    opening = contained_argv(
        harness.image,
        harness.requirements,
        project_root(),
        plugin.hooks.human_owned_files if plugin.hooks is not None else [],
        config_home,
        credential if credential.exists() else None,
        login,
        interactive=False,
    )
    return verify_inside(harness.requirements, opening)


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
    required_tools: list[Requirement],
    contained: bool = False,
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

    Asked only of an uncontained launch. A contained one has a boundary
    already, and the kernel reads it from the image's own ``LUP_CONTAINED``
    rather than from anything a launcher passes -- ``boundary = sandboxed or
    contained``, so the flag would change no verdict. Probing anyway printed
    a sandbox verdict about a session that was not going to rely on it, and
    on a failed probe printed ``deny lattice stays active`` for a session
    whose lattice was about to stand down behind the container. Saying
    nothing is the honest report, and the container's own line says what the
    boundary is.

    Each tool carries its own exercise rather than being named here and
    probed with a flag chosen by this function. That is not tidiness: the
    one flag this spelled for every tool was ``--version``, socat has no
    such option and exits 1 on it, and the OS boundary was therefore
    reported unavailable on every host in the world.
    """
    hooks = plugin.hooks
    if contained or hooks is None or hooks.sandbox is None:
        return
    findings = [tool.check(environment) for tool in required_tools]
    unusable = [finding for finding in findings if not finding.working]
    if unusable:
        for finding in unusable:
            Notice(
                text=(
                    f"{label} sandbox: {finding.requirement.capability} — "
                    f"{finding.detail}"
                ),
                urgency="warning",
            ).say()
        Notice(
            text=f"{label} sandbox: deny lattice stays active", urgency="warning"
        ).say()
        return
    environment["LUP_SANDBOX_ACTIVE"] = "1"
    Notice(
        text=f"{label} sandbox: active — unjudged shell defers to the OS boundary",
        urgency="boundary",
    ).say()


# lup: ignore[library-default] — each entry is literally a Codex CLI flag
CODEX_SANDBOX_OVERRIDES = (
    "-s",
    "--sandbox",
    "--full-auto",
    "--yolo",
    "--dangerously-bypass-approvals-and-sandbox",
)


def codex_sandbox_arguments(
    plugin: Plugin,
    environment: EnvVars,
    extra_args: list[str],
    contained: bool = False,
) -> list[str]:
    """Compose the interactive Codex envelope that LUP_SANDBOX_ACTIVE vouches for.

    Uncontained, the launcher establishes the boundary it announces: an
    explicit workspace-write sandbox on the Codex command line, mirroring how
    the Claude settings artifact compiles the same declaration into an OS
    wall. Path-level write and credential denials have no Codex equivalent,
    and neither does taking one command out of the envelope, so the envelope
    is the declaration's strict subset (network stays off). The dispatcher
    still reads the exclusions, judging those commands as though nothing
    confined them — which is the strict direction here too, since an envelope
    with no network is not a boundary they would have survived either. When
    the caller supplies its own sandbox flag the launcher vouches for
    nothing: the flag stays unset and the deny lattice keeps the escalation
    recipe.

    Contained, that same envelope is wrong in a way that has nothing to do
    with strictness, and what stands in its place is spelled by
    :data:`~lup.providers.codex.confinement.CODEX_CONFINEMENT` rather than
    here -- which carries why, and is where the image-side probe reads the
    same words rather than inventing its own. This is the counterpart of
    Claude's off switch, and it is what "every runtime, in the same change"
    means for a posture: one concept, each runtime's own word for it.

    LUP_SANDBOX_ACTIVE stays unset either way here, because a contained
    session does not need it -- the kernel reads the container from the
    image's own ``LUP_CONTAINED``, and a boundary is a boundary whether the
    launcher vouched for it or not.
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
        Notice(
            text=(
                f"codex sandbox: caller envelope ({' '.join(overrides)}) — "
                "deny lattice stays active"
            ),
            urgency="warning",
        ).say()
        return []
    if contained:
        Notice(
            text=(
                "codex sandbox: off inside the container — "
                "the container is the boundary, and its proxy is the way out"
            ),
            urgency="boundary",
        ).say()
        return list(CODEX_CONFINEMENT.off)
    environment["LUP_SANDBOX_ACTIVE"] = "1"
    Notice(
        text=(
            "codex sandbox: workspace-write envelope — "
            "unjudged shell defers to the OS boundary"
        ),
        urgency="boundary",
    ).say()
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
    Notice(
        text=f"anti-patterns retired for this session: {retired} rules",
        urgency="warning",
    ).say()
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


def claude_sandbox_arguments(plugin: Plugin, contained: bool = False) -> list[str]:
    """Say what this launch means the Claude sandbox to be, in one settings merge.

    Uncontained, that is a widening: Claude roots writes at the working
    directory just as Codex does, so a second checkout is read-only to every
    command a session runs — and running the toolchain over one is ordinary
    work here, which is why the symptom arrives as pytest failing to write a
    cache and `ruff format` refusing to save. Neither error names a sandbox.

    The path is this machine's, so it is resolved at launch and passed as
    settings rather than declared: an artifact carrying an absolute path
    would be drift in every other checkout. The declared writable paths ride
    along rather than being left to the generated file, because the two
    surfaces document this key differently — arrays that merge across
    scopes, values that override per session — and a list carrying both is
    the same list under either reading.

    Contained, it is an *off* switch, and the artifact still says ``enabled:
    true`` because that is the right answer for the uncontained launch the
    same file serves. The switch itself is spelled by
    :data:`~lup.providers.claude.confinement.CLAUDE_CONFINEMENT` rather than
    here, so the image-side probe that asks whether a session can open at all
    opens the same one this does -- spelled twice, the probe verifies a
    session nobody launches, which is how it came to refuse for the absence
    of a confinement no launch has ever asked for.

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
    hooks = plugin.hooks
    if hooks is None or hooks.sandbox is None:
        return []
    if contained:
        return list(CLAUDE_CONFINEMENT.off)
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
def ambient_config_home(login: ProviderLogin, fallback: Path) -> Path:
    """The configuration home a launch would inherit, made concrete for a mount.

    ``launch_home`` answers ``None`` for "inherit whatever the environment
    selected", which is the right answer everywhere it is read -- except at a
    mount, which names a file rather than a policy. Resolving it here lets
    that ``None`` keep meaning what it means everywhere else instead of every
    caller inventing a default.
    """
    # lup: ignore[os-environ] — the process environment is the open
    # mapping this reads by definition, and absence is the answer it wants
    named = os.environ.get(login.config_home_env)
    return Path(named) if named else fallback


def session_argv(
    cli: str,
    arguments: list[str],
    composition: NativeHarnessComposition,
    plugin: Plugin,
    config_home: Path,
    login: ProviderLogin,
    unsandboxed: bool,
    environment: EnvVars,
    transcript: Path | None = None,
) -> list[str]:
    """The argv that opens a session, inside the declared container or on the host.

    One place decides this for both runtimes, because "contained unless the
    operator said otherwise" is a property of the launch rather than of the
    CLI being launched -- and a second runtime that decided it separately is
    how one of them ends up quietly uncontained.

    It is also the one place that knows the whole opening: what the container
    had to say about itself, and whether the checks behind it passed. So the
    banner is assembled here and said once, after the verification rather
    than before it -- a launch cannot report itself ready while the thing
    that would refute it has not run yet, and thirty lines printed ahead of
    the answer is how the refutation ends up below the fold.
    """
    if unsandboxed:
        return [cli, *arguments]
    harness = composition.recipe.source
    # A token crosses by name, so its value has to be in the environment of the
    # process that starts the container rather than anywhere in the argv. That
    # makes this the one place it has to be resolved: the argv builder reads
    # the same declaration for whether to pass the name, and a name passed
    # against an environment nobody populated forwards nothing.
    carried = harness.image.forge.sourced(environment)
    if carried:
        environment[harness.image.forge.token_variable] = carried
    credential = login.credentials_path(config_home)
    banner = Banner()
    opening = contained_argv(
        harness.image,
        harness.requirements,
        project_root(),
        plugin.hooks.human_owned_files if plugin.hooks is not None else [],
        config_home,
        credential if credential.exists() else None,
        login,
        inherited_environment=(
            [MAX_RECURSIVE_AGENT_ENV] if MAX_RECURSIVE_AGENT_ENV in environment else []
        ),
        banner=banner,
    )
    # Verified on the way in, rather than asserted. This is §6's whole point
    # and the launch is where it has to happen: the boundary was built two
    # lines ago and nothing had ever asked whether it carries traffic. What
    # that cost, measured on the first contained session anybody opened, was
    # a session that started cleanly, looked entirely healthy, and reported
    # every request as the operator's own internet or DNS being down.
    #
    # Not the whole image roster -- only the entries marked `always`, which
    # is the handful whose absence means the session can do nothing. A model
    # call and a toolchain version belong to `harness requirements --inside`.
    verify_inside(
        harness.requirements,
        probing(opening),
        setting_up=False,
        environment=environment,
    )
    banner.add(
        [
            Notice(
                text="generated artifacts current; runtime checks passed.",
                urgency="ready",
            ),
            *(
                [Notice(text=f"Transcript: {transcript}", urgency="artifact")]
                if transcript is not None
                else []
            ),
        ]
    )
    banner.say()
    return [*opening, cli, *arguments]


def probing(opening: list[str]) -> list[str]:
    """The session's own argv, with the interactive terminal taken back off.

    The same argv rather than a fresh one, because a probe assembled
    separately verifies a container no session opens -- which is how the
    exercise this replaces could pass on a host whose sessions could not
    start. The one difference is deliberate: a probe's output is captured,
    and ``-it`` against a pipe fails on the terminal it was promised.
    """
    return [word for word in opening if word != "-it"]


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
    unsandboxed: bool = False,
    checkpoint: LaunchCheckpoint | None = None,
    max_recursive_agent: int = -1,
    transcribe_session: bool = False,
) -> None:
    """Generate/reconcile Claude artifacts and launch the verified local plugin."""
    contradiction = resume.contradicted()
    if contradiction is not None:
        raise typer.BadParameter(contradiction)
    if checkpoint is not None and not generate_only:
        checkpoint(provider="claude")
    plugin = composition.recipe.source.plugins[0]
    announce_relaxed_rules(relaxed, plugin)
    if not ready_to_open(composition, generate_only):
        return
    arguments: list[str] = claude_resume_arguments(resume)
    # A mode's model is a default rather than a fixture: it says what this kind
    # of session runs on when nobody said otherwise, and an explicit --model
    # still wins, because overriding the model is why a caller passes one.
    selected_model = model or (
        mode.native_model("claude") if mode is not None else None
    )
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
            *claude_sandbox_arguments(plugin, contained=not unsandboxed),
            *(mode.command_words("claude") if mode is not None else []),
            *extra_args,
        ]
    )
    environment = non_interactive_environment(os.environ)  # lup: ignore[os-environ]
    environment[MAX_RECURSIVE_AGENT_ENV] = str(max_recursive_agent)
    apply_sandbox_environment(
        plugin,
        environment,
        "claude",
        [bubblewrap_requirement(), socat_requirement()],
        contained=not unsandboxed,
    )
    # A name no origin answers to reaches here from an explicit --profile, and
    # from an active selection whose profile has since gone; both are the
    # caller's to fix, so neither should arrive as a traceback.
    try:
        home = profiles.launch_home(profile)
    except KeyError as error:
        raise typer.BadParameter(str(error)) from error
    if home is not None:
        environment.update(profiles.login.environment(home))
    transcribing = transcribe_session or mode is None or mode.transcribes("claude")
    transcript = start_harness_transcript(
        "claude",
        ClaudeTranscripts(home),
        model=selected_model,
        profile=profile,
        arguments=arguments,
        record_root=mode.transcript_root() if mode is not None else None,
        mode=mode.name if mode is not None else None,
        transcribe=transcribing,
    )
    succeeded = False
    try:
        opening = (
            nullcontext({})
            if mode is None
            else mode.opened("claude", transcript.journal, transcribing)
        )
        with opening as session:
            environment.update(session)
            argv = session_argv(
                "claude",
                arguments,
                composition,
                plugin,
                home
                if home is not None
                else ambient_config_home(profiles.login, Path.home() / ".claude"),
                profiles.login,
                unsandboxed,
                environment,
                transcript.journal.path,
            )
            sh.Command(argv[0])(*argv[1:], _fg=True, _env=environment)
        succeeded = True
    except sh.CommandNotFound as error:
        raise typer.BadParameter("Claude Code CLI is not installed") from error
    except sh.ErrorReturnCode as error:
        raise typer.Exit(error.exit_code) from error
    finally:
        transcript.close(succeeded=succeeded)
        if checkpoint is not None:
            checkpoint(provider="claude")


# For the reason spelled at `launch_claude`: the mode is one optional argument
# among the ones that actually decide how a runtime starts.
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
    unsandboxed: bool = False,
    checkpoint: LaunchCheckpoint | None = None,
    max_recursive_agent: int = -1,
    transcribe_session: bool = False,
) -> None:
    """Generate/reconcile Codex artifacts and launch without updating the CLI."""
    contradiction = resume.contradicted()
    if contradiction is not None:
        raise typer.BadParameter(contradiction)
    if checkpoint is not None and not generate_only:
        checkpoint(provider="codex")
    plugin = composition.recipe.source.plugins[0]
    announce_relaxed_rules(relaxed, plugin)
    if not ready_to_open(composition, generate_only):
        return
    environment = non_interactive_environment(os.environ)  # lup: ignore[os-environ]
    environment[MAX_RECURSIVE_AGENT_ENV] = str(max_recursive_agent)
    envelope = codex_sandbox_arguments(
        plugin, environment, extra_args, contained=not unsandboxed
    )
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
    selected_model = model or (mode.native_model("codex") if mode is not None else None)
    if selected_model is not None:
        arguments.extend(["--model", selected_model])
    arguments.extend(mode.command_words("codex") if mode is not None else [])
    arguments.extend(extra_args)
    environment["CODEX_HOME"] = str(selected_home)
    transcribing = transcribe_session or mode is None or mode.transcribes("codex")
    transcript = start_harness_transcript(
        "codex",
        CodexTranscripts(selected_home),
        model=selected_model,
        profile=profile,
        arguments=arguments,
        record_root=mode.transcript_root() if mode is not None else None,
        mode=mode.name if mode is not None else None,
        transcribe=transcribing,
    )
    succeeded = False
    opening = (
        nullcontext({})
        if mode is None
        else mode.opened("codex", transcript.journal, transcribing)
    )
    try:
        cache = installer.ensure(
            project_root() / ".codex" / "plugins" / plugin.name,
            project_root(),
            force=force_install,
        )
        with opening as session:
            typer.echo(f"Verified installed Codex plugin: {cache.installed_root}")
            environment.update(session)
            argv = session_argv(
                "codex",
                arguments,
                composition,
                plugin,
                selected_home,
                CODEX_LOGIN,
                unsandboxed,
                environment,
                transcript.journal.path,
            )
            sh.Command(argv[0])(*argv[1:], _fg=True, _env=environment)
        succeeded = True
    except sh.CommandNotFound as error:
        raise typer.BadParameter("Codex CLI is not installed") from error
    except sh.ErrorReturnCode as error:
        raise typer.Exit(error.exit_code) from error
    finally:
        transcript.close(succeeded=succeeded)
        if home.isolated and store.publish(project_root()):
            typer.echo("Returned the refreshed Codex login to the account home")
        if checkpoint is not None:
            checkpoint(provider="codex")
