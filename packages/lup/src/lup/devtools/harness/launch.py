"""Native launch flows: runtime preflight, then the Claude and Codex launchers.

Each launcher regenerates its target's artifacts, verifies every claimed
native requirement against a live probe, and hands the terminal to the
native CLI with the non-interactive environment applied.
"""

import asyncio
import logging
import os
import shutil
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from datetime import datetime
from pathlib import Path
from tempfile import mkdtemp
from typing import Protocol, runtime_checkable
from uuid import uuid4

import sh
import typer
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from lup.harness.devices import Device
from lup.providers.login import ProviderLogin
from lup.providers.profile_tree import profile_directory
from lup.providers.profiles import DefaultHomeProfile, ProfileDirectory
from lup.providers.user_config import UserConfig, UserConfigFile
from lup.devtools.harness.config_volume import HomeSeedPlaces, named_file
from lup.devtools.harness.contained import contained_argv, read_config_home
from lup.providers.claude.model_choice import (
    claude_default_effort,
    claude_model_id,
    claude_effort,
    claude_effort_named,
    listed_claude_model,
    refuse_unsupported_effort as refuse_claude_effort,
)
from lup.providers.codex.model_choice import (
    codex_default_effort,
    codex_effort_arguments,
    codex_effort_named,
    codex_model_id,
    listed_codex_model,
    refuse_unsupported_effort as refuse_codex_effort,
)
from lup.providers.codex.subagents import CodexModelTiers
from lup.providers.claude.config_home import (
    CLAUDE_HOME_DOCUMENT,
    WORKSPACE_SETTINGS,
    ClaudeConfigHome,
    ClaudeConfigUnreadable,
    selected_config_home,
)
from lup.providers.claude.home_seed import (
    KEYBINDINGS,
    ClaudeHomeReturn,
    ClaudeHomeSeed,
)
from lup.providers.claude.theme import settle_claude_theme
from lup.providers.claude.harness import ClaudeSpellings
from lup.providers.claude.transcripts import ClaudeTranscripts
from lup.providers.codex.harness import CodexSpellings
from lup.providers.codex.login import CODEX_LOGIN
from lup.providers.codex.account import read_account
from lup.providers.codex.install import install_codex_plugin
from lup.providers.codex.marketplace import CodexMarketplace
from lup.providers.codex.profile import CodexProfileSettings
from lup.providers.codex.transcripts import CodexTranscripts
from lup.coordination.identity import MEMBER_ENV, NAME_ENV, LaunchedMember
from lup.coordination.repository import RepositoryPeers, launched_member
from lup.harness.environment import non_interactive_environment
from lup.harness.image import Image
from lup.harness.messaging import SessionInboxes, cleared
from lup.workspace.edition import shared_git_directory
from lup.harness.models import HookSet, NativeName, Plugin, Resumption
from lup.policy.boundary import BoundaryPreflight
from lup.policy.identity import POLICY_ROOT_ENV
from lup.policy.profiles import compile_boundary, depended_on, measured
from lup.policy.snapshots import accept_destination_policies, destination_authorities
from lup.devtools.pointer_trust import judged_roots, store_exposure
from lup.sandbox.rail import (
    AccessibleRoot,
    fleet_lease,
)
from lup.devtools.sync import accessible_roots, granted_devices
from lup.launch.boundary import apply_sandbox_environment
from lup.launch.declaration import LaunchSandbox, settled_sandbox
from lup.providers.claude.launch import (
    claude_resume_arguments,
    claude_sandbox_arguments,
    companion_plugin_directories,
)
from lup.providers.codex.launch import codex_resume_arguments, codex_sandbox_arguments
from lup.harness.notice import Banner, Notice
from lup.harness.requirements import (
    Finding,
    HostFacts,
    Manifest,
    refused,
)
from lup.harness.process import LocalProcessLauncher
from lup.harness.toolchain import (
    bubblewrap_requirement,
    container_client,
    for_host,
    granted_device_requirement,
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
from lup.observability.sessions import Session, SessionRecorder
from lup.sessions.recursion import MAX_RECURSIVE_AGENT_ENV
from lup.types import EnvVars, JsonObject, JsonValue
from lup.workspace.paths import agent_version, harness_runs_path, project_root
from lup.providers.codex.home import (
    SEED_RECORD,
    CodexWorktreeHomeStore,
    seeded_codex_settings,
    select_codex_home,
)
from lup.devtools.harness.composition import NativeTargets
from lup.devtools.dev.branches import settle_base_freshness
from lup.devtools.harness.drift import (
    RepositoryWriter,
    generate_targets,
    generate_with_report,
)
from lup.harness.generate import NativeHarnessComposition
from lup.devtools.harness.preflight import (
    LaunchSentinels,
    ROOT_VARIABLE,
    exclude_sandbox_placeholders,
    record_preflight,
    release_ledger,
    retire_mount_table,
    sweep_ledgers,
)
from lup.devtools.dev.worktree import RelocationHint, refuse_redirected_pointers
from lup.devtools.layout import find_tree_dir


def declared_mounts(
    writable: list[Path], read_only: list[Path]
) -> list[AccessibleRoot]:
    """The folders one command line asked this session to reach, as roots.

    The same shape a `sync.json.local` registration resolves to, because the
    two say the same thing at different lifetimes: a registration is standing
    and reviewed, a flag lasts one launch. Everything downstream -- the lease,
    the boundary declaration, each runtime's own widening -- already speaks
    this type, so the flag costs no second path.
    """
    return [
        *[AccessibleRoot(path=path) for path in writable],
        *[AccessibleRoot(path=path, writable=False) for path in read_only],
    ]


def declared_devices(names: list[str]) -> list[Device]:
    """The devices one command line asked this session to be granted.

    The same shape an image declares its standing ones in, so a flag costs no
    second path downstream. A name the specification's grammar refuses is
    refused here in the launcher's own words, naming the flag's value, rather
    than by the engine refusing the whole container over it.
    """

    def declared(name: str) -> Device:
        try:
            return Device(name=name)
        except ValidationError as error:
            raise typer.BadParameter(
                f"--device {name!r}: a device is named the way CDI names it, "
                "vendor/class=device, such as nvidia.com/gpu=all"
            ) from error

    return [declared(name) for name in names]


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
    rather than written again here. Restating it is how the two come to
    disagree: the guidance naming the move a runtime supports, this naming a
    tool, and a workflow change having to find both to land. One of them
    being an adapter method makes that impossible.
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


class LaunchOpening(BaseModel):
    """What clearing the gates before a session left for the opening to say.

    The banner travels with the findings because the two are halves of one
    answer and are produced at opposite ends of the launch: the runtime is
    established here, the boundary is measured after the container starts,
    and the reader wants them in one block ordered by what they might have to
    do about it. A component that printed as it went would put the version
    above the roster above the boundary, which is the order the launcher
    happens to work in and no order at all to anybody reading it.
    """

    findings: list[Finding] = []
    """The host roster, carried to the boundary preflight that needs it."""

    banner: Banner = Banner()
    """Every line held so far, said once the last measurement is in."""

    runtime: str = ""
    """The runtime this opens, and the version of it that answered."""

    sandbox: LaunchSandbox = LaunchSandbox.OUTER
    """The sandbox this session opens under, settled once for everything after.

    Carried rather than recomputed, because the default is settled by asking
    the host and says so when it falls back: a launcher reading the flag
    again would see the question and not its answer."""


def ready_to_open(
    composition: NativeHarnessComposition,
    generate_only: bool,
    sentinels: LaunchSentinels,
    companions: list[NativeHarnessComposition] = [],
    repository_writers: list[RepositoryWriter] = [],
    sandbox: LaunchSandbox | None = None,
) -> LaunchOpening | None:
    """Generate this target's artifacts and clear every gate standing before a session.

    Both launchers reach a session through here, so a gate added once is a
    gate every entry point makes — including one written later, which cannot
    open a session without first generating the artifacts it opens against.
    Answers whether to go on: a generate-only invocation has already done
    everything it was asked for.

    ``companions`` are the trees this launch does not open and regenerates
    anyway, which is what makes launching a runtime mean what `harness
    generate all` means. A launcher that left the other's tree behind
    whenever a shared source moved would fail the next `dev check` on drift
    nobody had introduced -- reported against a session that had done
    nothing but open. They are generated in passing, so a tree that is
    already current says nothing.

    ``None`` is that answer, and the opening is the other one — including an
    empty roster, which is why this is not a list and a truth test. What
    those findings are *for* is the boundary preflight, which needs both
    halves of one measurement and can only be assembled where the second
    half is taken; carrying them out of here is what saves the launch from
    exercising the same probes twice and reporting each of them twice.

    Settling the base is one of those steps rather than a workflow's own. A
    tree whose base has moved is self-consistent and says nothing about it, so
    a session opened on one plans and edits against code that is no longer
    there — which cost a planning pass over thirteen concerns on a tree ten
    commits behind its remote, where two merged pull requests had already done
    part of the work being planned. Being behind is not itself grounds for
    refusing a session, so what happens here is a sync and a report: a clean
    checkout is brought level with its own remote, and a base that has moved
    is named on the way in.

    Settling the sandbox is another. ``sandbox`` is what the command line
    asked for, ``None`` where it named none, and :func:`settled_sandbox`
    answers it once here, as the first thing asked of the host: the host
    roster depends on which side of the container the session runs, and
    everything after reads the answer off the opening. After generation, so
    a generate-only invocation, which opens nothing, is neither probed nor
    warned.

    The two lines said here are said before their work rather than after
    it, for the reason the fetch names itself below: these are the stretches
    a launch spends silent when everything is current, and a line naming
    the wait is what separates a slow one from a stopped one. A
    generate-only invocation reports each tree anyway, so it is not told.
    """
    if not generate_only:
        typer.echo("regenerating what this session opens against")
    generate_with_report(composition, in_passing=not generate_only)
    generate_targets(companions, repository_writers, in_passing=not generate_only)
    if generate_only:
        return None
    # Before any host git runs on the way in -- base freshness, status, the
    # preflight's own probes -- so a session a previous contained one left with
    # a redirected worktree pointer is refused here rather than opened onto git
    # reading the config that pointer now leads to.
    refuse_redirected_pointers()
    # Before anything writes one, so a launch that was killed last week does
    # not leave its measurement standing for somebody to find. On the way in
    # rather than only on the way out, because the launch that crashed is
    # exactly the one that did not get to tidy up after itself.
    sweep_ledgers(project_root())
    # The runtime sandbox's own leavings, taken out of `git status` before a
    # session reads it: said only when something was added, because a line
    # repeated on every launch is read on none.
    excluded = exclude_sandbox_placeholders(project_root())
    if excluded:
        typer.echo(
            f"excluded {len(excluded)} sandbox placeholder file(s) from git "
            f"status: {', '.join(excluded)}"
        )
    typer.echo("checking the host")
    opening = LaunchOpening(sandbox=settled_sandbox(sandbox, "pass `--sandbox inner`"))
    opening.findings = runtime_preflight(
        composition, sentinels, opening, opening.sandbox.contained()
    )
    settle_base_freshness(LocalProcessLauncher(), project_root())
    return opening


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
    record: Session | None = None
    """The ledger node pointing at this launch's directory, where one was recorded."""

    recorder: SessionRecorder | None = None

    def close(self, *, succeeded: bool, interrupted: bool = False) -> None:
        """Stop ingestion, record the outcome, and release the diagnostics log.

        The ledger's record of the launch is amended last, after the journal
        holds its final record, so the digest pinned is the closed journal's.
        """
        if self.watcher is not None:
            self.watcher.stop()
        self.journal.emit("run_end", {"succeeded": succeeded})
        if self.diagnostics is not None:
            watcher_logger().removeHandler(self.diagnostics)
            self.diagnostics.close()
        if self.recorder is not None and self.record is not None:
            self.recorder.closed(
                self.record,
                "interrupted"
                if interrupted
                else "completed"
                if succeeded
                else "failed",
            )


def watcher_logger() -> logging.Logger:
    """The logger the native transcript watcher reports its own failures on."""
    return logging.getLogger(NativeTranscriptWatcher.__module__)


def capture_watcher_diagnostics(run_directory: Path) -> logging.Handler:
    """Send watcher diagnostics to a file for the life of one launch.

    The launcher hands its terminal to an interactive CLI that draws over the
    whole screen. Nothing configures logging on this path, so a watcher failure
    would reach Python's last-resort handler and print a traceback into that UI
    -- so a recovered polling error would read as a crash. The durable
    record is the journal's own error event; this file is for the detail
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
    recorder: SessionRecorder | None = None,
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

    This is the writer that opens a launch's directory, so it is where the
    launch is recorded in the ledger: handed a ``recorder``, it records one
    :class:`~lup.observability.sessions.Session` pointing at the directory
    and its observable journal, which :meth:`HarnessTranscript.close` amends
    with the outcome. The harness command tree wires the recorder from the
    project's declared kinds; handed none, nothing is recorded.
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
    record = (
        recorder.opened(provider, agent_version(), trace_path.parent, trace_path)
        if recorder is not None
        else None
    )
    if not transcribe:
        return HarnessTranscript(journal=journal, record=record, recorder=recorder)
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
    # Said by the banner rather than here, where it was printed a second time
    # under `Artifacts` a few lines later: one path, twice, in two different
    # spellings of the same sentence.
    return HarnessTranscript(
        journal=journal,
        watcher=watcher,
        diagnostics=diagnostics,
        record=record,
        recorder=recorder,
    )


def runtime_preflight(
    composition: NativeHarnessComposition,
    sentinels: LaunchSentinels,
    opening: LaunchOpening,
    contained: bool = True,
) -> list[Finding]:
    """Verify each claimed native requirement immediately before launch.

    Two rosters, asked in the order their failures matter. The native probes
    answer whether this runtime can host a session at all, and a gap there
    stops the launch. The declared requirements answer what the session will
    be able to *do*, and almost every gap there costs a capability rather
    than the session -- so those are named and the launch continues, which is
    the only posture that works on a machine without a display, a container,
    or an editor attached.

    A supported probe is not a line. Three of them answering with one version
    between them is one fact stated three times, and the fact is which
    runtime this opens -- so that is what the opening carries, and each
    capability is heard from only where it is missing, which is the answer
    the launch stops on.
    """
    target = composition.recipe.label
    evidence = composition.readiness()
    for item in evidence:
        if item.supported:
            continue
        Notice(
            text=f"{target} {item.version}: required capability unavailable: {item.capability}",
            urgency="refusal",
        ).say()
    if any(not item.supported for item in evidence):
        raise typer.BadParameter(
            f"Cannot launch {target}: required runtime checks failed. "
            "Run `uv run lup-devtools harness doctor` for details."
        )
    versions = ", ".join(sorted({item.version for item in evidence}))
    opening.runtime = f"{target} {versions}" if versions else target
    return report_requirements(
        composition.recipe.source.requirements,
        sentinels=sentinels,
        in_passing=True,
        contained=contained,
    )


def report_requirements(
    manifest: Manifest,
    setting_up: bool = False,
    sentinels: LaunchSentinels = LaunchSentinels(),
    in_passing: bool = False,
    contained: bool = False,
) -> list[Finding]:
    """Exercise the host-side requirements, printing what each one found.

    An absence is exactly the fact a session needs at the top of its
    scrollback, because it is the one the agent inside cannot discover except
    by failing at it.

    *in_passing* is a roster exercised on the way to something else, and
    there a capability that works is counted rather than named: the roster
    grows, the block of `working` grows with it, and the launch reports the
    same block every session. A caller that asked -- `harness requirements`,
    whose whole job is this answer -- hears every entry, because a command
    that prints nothing on a healthy machine has not answered the question.

    *setting_up* widens this to everything checked only at setup, and is off
    for a launch. Two different things live there and both would be wrong to
    repeat: a nicety reported before every session becomes a line people learn
    to skip, along with the line above it that mattered; and an exercise that
    starts a container is a cost no session should pay to be told something
    that was equally true yesterday.
    """
    # The host sentinel reaches a probe through this process's own environment
    # rather than through an argument, because an exercise runs as a
    # subprocess of this one and inherits it. Set here, at the one place the
    # host roster runs, so a probe asking which side it is on has an answer
    # before it is asked -- and so nothing else has to carry the value.
    os.environ.update(sentinels.outside())  # lup: ignore[os-environ]
    environ: EnvVars = dict(os.environ)  # lup: ignore[os-environ]
    # Pointed at this host's client here rather than declared as one, because
    # the declaration is hashed into the ownership digest and a container
    # client is a fact about the machine. This is the only place the
    # exercises actually run, so it is the only place that has to know.
    #
    # The machine's device grants join the roster here for the same reason
    # and from the same side: a grant is read off this machine's own file at
    # the moment the roster runs, so a committed manifest never names a
    # vendor's device, and a setup check still re-proves every grant.
    findings = for_host(
        Manifest(
            requirements=[
                *manifest.requirements,
                *(granted_device_requirement(device) for device in granted_devices()),
            ]
        ),
        container_client(),
        project_root(),
        inside_sentinel=sentinels.inside,
        host_sentinel=sentinels.host,
    ).check(environ, setting_up=setting_up, contained=contained)
    return reported(findings, in_passing)


def reported(findings: list[Finding], in_passing: bool = False) -> list[Finding]:
    """Say what each finding found, and stop where absence refuses.

    One place for both halves so the two rosters cannot come to differ about
    what a refusal means. Two rosters printed separately have somewhere to
    differ: either is free to treat a refused finding as a line rather than
    a stop.

    The refusal names the capabilities and stops there. Joining their whole
    consequences into the exception is unreadable at the size this roster
    reaches: four refusals make one nine-line paragraph inside an error box,
    restating word for word what has just been printed above it with the
    causes, the recoveries and the blank lines all flattened out. The
    lines above are the report; this is the exit code and what it was about.

    *in_passing* decides which half of a finding is read: everything it
    found, for a caller that asked, and only what a reader has to act on for
    a launch on its way to opening a session.
    """
    for finding in findings:
        for notice in finding.alarms() if in_passing else finding.notices():
            notice.say()
    stopping = refused(findings)
    if stopping:
        raise typer.BadParameter(
            f"Cannot launch: {len(stopping)} required checks failed: "
            + ", ".join(item.requirement.capability for item in stopping)
            + ". See the errors above."
        )
    return findings


def verify_inside(
    manifest: Manifest,
    opening: list[str],
    setting_up: bool = True,
    sentinels: LaunchSentinels = LaunchSentinels(),
    environment: EnvVars | None = None,
    in_passing: bool = False,
    skipped: Sequence[str] = (),
    accessible: Sequence[AccessibleRoot] = (),
) -> list[Finding]:
    """Exercise the image half behind an argv somebody already assembled.

    Split from :func:`report_inside_requirements` so the launch can use it
    without building the argv a second time. Assembling it starts the egress
    proxy and may build the image, so a second call would not merely be slow
    -- it would print the whole boundary notice again, which reads as the
    launch having done it twice.

    ``skipped`` is what another composition over the same image already
    exercised, by :meth:`Manifest.inside_signatures`.

    ``accessible`` is the roots the argv was assembled with, so the read-only
    binds a probe checks are the lease that argv carries -- taken after the
    argv, whose assembly readies each shared git directory the lease reads.
    """
    if environment is None:
        environ: EnvVars = dict(os.environ)  # lup: ignore[os-environ]
    else:
        environ = dict(environment)
    leased = fleet_lease(project_root(), list(accessible))
    return reported(
        manifest.check_inside(
            environ,
            opening,
            setting_up,
            HostFacts(
                checkout=project_root(),
                inside_sentinel=sentinels.inside,
                host_sentinel=sentinels.host,
                read_only_binds=list(leased.read_only),
            ),
            skipped,
        ),
        in_passing,
    )


def report_inside_requirements(
    composition: NativeHarnessComposition,
    plugin: Plugin,
    config_home: Path,
    login: ProviderLogin,
    sentinels: LaunchSentinels = LaunchSentinels(),
    setting_up: bool = True,
    skipped: Sequence[str] = (),
    banner: Banner | None = None,
) -> list[Finding]:
    """Exercise the image-side requirements inside the container a session opens.

    ``skipped`` and ``banner`` are for a caller asking two runtimes about one
    image: the checks the first already exercised are not paid for again, and
    the boundary notice the argv assembly says is collected into the banner
    rather than printed a second time.

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
        editor_rendezvous(login),
        credential if credential.exists() else None,
        login,
        streams="captured",
        banner=banner,
        sentinels=sentinels,
        # The same mounts and devices a session gets, for the reason this
        # probe assembles nothing of its own: a container built without the
        # declared roots is a container no session opens, and a placement
        # verified in one says nothing about the other.
        accessible=accessible_roots(),
        devices=granted_devices(),
    )
    # The same values on both sides of one call, which is the whole of what a
    # placement probe asks. Injected into the argv above and handed to the
    # roster below: aimed with one and opened with the other, the probe would
    # look for a value nothing had set and report the boundary broken on a
    # machine whose boundary was fine.
    return verify_inside(
        harness.requirements,
        opening,
        setting_up=setting_up,
        sentinels=sentinels,
        skipped=skipped,
        accessible=accessible_roots(),
    )


def codex_login_preflight(
    home: Path,
    environment: EnvVars,
    command: list[str] | None = None,
    *,
    headless: bool = False,
    profile: str | None = None,
) -> None:
    """Refresh managed authentication through its native owner before launch.

    A local token deadline proves neither renewal nor acceptance by another
    service. Native account/read owns renewal; its absence or failure is an
    unverified login, never a successful local-file check. Declining sign-in
    remains explicit so a deliberately offline session is still possible.
    """
    if profile is not None:
        typer.echo(
            f"Codex authentication for profile {profile}: not verified before launch. "
            "The native account API cannot select named profiles; "
            "the session will validate its selected configuration."
        )
        return
    selected = {**environment, **CODEX_LOGIN.environment(home)}
    executable, *arguments = command or ["codex"]

    def verified() -> bool:
        try:
            state = asyncio.run(
                read_account(
                    Path(executable), selected, refresh_token=True, arguments=arguments
                )
            )
        except (OSError, RuntimeError, ValueError, sh.CommandNotFound) as error:
            # Native error bodies can contain credentials or account identity.
            typer.echo(
                f"Codex authentication in {home}: not verified; "
                f"native account check failed ({type(error).__name__})."
            )
            return False
        if state.ready:
            return True
        typer.echo(f"Codex authentication in {home}: not signed in.")
        return False

    if verified():
        return
    if not typer.confirm("Sign in to Codex now?", default=True):
        typer.echo(
            "Continuing with authentication not verified — "
            "Codex will report its own authentication errors."
        )
        return
    try:
        sh.Command(executable)(
            *arguments,
            "login",
            *(["--device-auth"] if headless else []),
            _fg=True,
            _env=selected,
        )
    except sh.ErrorReturnCode as error:
        raise typer.BadParameter("Codex sign-in did not complete") from error
    if not verified():
        raise typer.BadParameter(
            f"Codex authentication in {home} remains unverified after sign-in; "
            "the session was not opened."
        )


def personal_config(config: UserConfigFile) -> UserConfig:
    """The person's lup config, or a refusal naming the file to fix.

    Refused rather than passed over, because a launch that dropped a setting
    it could not read would open looking exactly like one that never had it.
    """
    try:
        return config.load()
    except ValueError as refusal:
        raise typer.BadParameter(str(refusal)) from refusal


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


# It takes a composition, an account, a profile, a model and a passthrough
# vector, and a mode is one optional argument among them; moving it onto
# LaunchMode would make the model answerable for starting a runtime it knows
# nothing about, and leave a project declaring no mode with no launcher at all.
def ambient_config_home(login: ProviderLogin, fallback: Path | None = None) -> Path:
    """The configuration home a launch would inherit, made concrete for a mount.

    ``launch_home`` answers ``None`` for "inherit whatever the environment
    selected", which is the right answer everywhere it is read -- except at a
    mount, which names a file rather than a policy. Resolving it here lets
    that ``None`` keep meaning what it means everywhere else instead of every
    caller inventing a default.

    ``fallback`` is what answers where the environment selected nothing, and
    it is a caller's because it is not always the provider's own default: a
    Codex composition falls back to the *worktree-scoped* home its store
    derives, which is a home per checkout rather than the account's. Omitting
    it takes the runtime's declared default, which is the right answer for a
    caller that has no home of its own in mind.
    """
    # lup: ignore[os-environ] — the process environment is the open
    # mapping this reads by definition, and absence is the answer it wants
    selected = login.selected_home(dict(os.environ))
    return selected if fallback is None or selected != login.ambient_home else fallback


def editor_rendezvous(login: ProviderLogin) -> Path | None:
    """Where an editor on this machine would leave a lockfile for this runtime.

    Read off the environment this launcher runs in rather than the home the
    launch selected, because the editor is a *sibling* process: it reads the
    same variable and knows nothing about ``--profile``. ``None`` where the
    runtime declares no rendezvous, which is every runtime but Claude Code.
    """
    # lup: ignore[os-environ] — the same open mapping the editor itself reads
    return login.editor_rendezvous(dict(os.environ))


def settle_boundary(
    plugin: Plugin,
    sandbox: LaunchSandbox,
    findings: list[Finding],
    sentinels: LaunchSentinels,
    environment: EnvVars,
    banner: Banner,
    accessible: list[AccessibleRoot] = [],
    runtime: str = "",
) -> BoundaryPreflight:
    """Compile what this launch promised, measure it, and refuse if it fell short.

    The gate, and the reason every other part of this exists. A profile
    requiring a capability nothing delivered does not open, and the diagnostic
    names the capability and what was tried -- because "the sandbox is broken"
    sends somebody to read configuration, where the exercise's own words send
    them to the thing that failed.

    An optional capability that came back absent is not a refusal and not a
    question. The operations that need it are capability-blocked, which is
    what sends an agent to the missing channel rather than to argue with a
    rule, and the ledger is how the dispatcher learns which those are.

    The lease is read here rather than carried from the argv builder because
    an uncontained launch never builds one and still has a boundary to
    describe: the same worktree, the same siblings, and no container under
    them. One call answers for both postures, which is what stops the two
    from coming to disagree about what this session may write.

    ``accessible`` arrives as an argument rather than being read here, which
    is the one part of the lease that cannot be recomputed freely: resolving
    a registration can clone it, so a launch settles the list once and hands
    the same one to the boundary and to the argv. Passed empty, this answers
    for the checkout alone -- which is what a caller with no registry to read
    should get, rather than a boundary that quietly went looking for one.

    A refusal is said here and everything else is held. The banner is printed
    after the last measurement, and a launch that raises never reaches it --
    so the one report a reader cannot afford to lose is the one that cannot
    wait for it.
    """
    root = project_root()
    declared = plugin.hooks or HookSet(id="hooks.absent", policy_ids=[])
    # Before the lease asks git anything about these roots, on either posture:
    # a root whose pointer its repository does not list back is refused here
    # rather than mounted and read through, and each repository vouching for
    # a root is remembered before any container runs in it.
    trust = judged_roots([root, *(item.path for item in accessible)], operator=root)
    for notice in trust.notices:
        typer.echo(notice, err=True)
    if trust.refusal:
        raise typer.BadParameter(trust.refusal)
    lease = fleet_lease(root, accessible=accessible)
    if exposed := store_exposure(lease):
        raise typer.BadParameter(exposed)
    boundary = compile_boundary(
        declared,
        contained=sandbox.contained(),
        writable=list(lease.writable),
    )
    preflight = measured(boundary, depended_on(declared, sandbox.contained()), findings)
    said = preflight.opening()
    if not preflight.launchable():
        Notice(text=said, urgency="boundary").say()
        raise typer.BadParameter(
            f"{boundary.name}: "
            + ", ".join(entry.capability for entry in preflight.missing_required())
            + " could not be verified. Launch stopped. See the failed checks above."
        )
    if said:
        banner.add([Notice(text=said, urgency="boundary")])
    record_preflight(
        preflight,
        sentinels,
        root,
        destination_policies=accept_destination_policies(
            root, accessible, lease, runtime
        ),
        read_only_roots=list(lease.read_only),
        destination_authorities=destination_authorities(accessible, runtime),
    )
    if not sandbox.contained():
        # No mounts, so no mount table -- and the one a contained launch left
        # behind describes a boundary this session is not behind. Attributing
        # a refusal to it teaches an agent to reach for the host when the bug
        # was its own, which outlives the command it was wrong about.
        retire_mount_table(root)
    environment.update(
        sentinels.within() if sandbox.contained() else sentinels.outside()
    )
    environment[ROOT_VARIABLE] = str(root.resolve())
    return preflight


def session_argv(
    cli: str,
    arguments: list[str],
    composition: NativeHarnessComposition,
    plugin: Plugin,
    config_home: Path,
    login: ProviderLogin,
    sandbox: LaunchSandbox,
    environment: EnvVars,
    transcript: Path | None = None,
    sentinels: LaunchSentinels = LaunchSentinels(),
    cleared: LaunchOpening = LaunchOpening(),
    mounts: list[AccessibleRoot] = [],
    devices: list[Device] = [],
    authenticate: Callable[[list[str], Path, bool], None] | None = None,
    member: LaunchedMember | None = None,
    prepare: Callable[[list[str], Path], None] | None = None,
    home_seed: HomeSeedPlaces | None = None,
) -> list[str]:
    """The argv that opens a session, inside the declared container or on the host.

    One place decides this for both runtimes, because "contained unless the
    operator said otherwise, or the host has no engine to contain it" is a
    property of the launch rather than of the CLI being launched -- and a
    second runtime that decided it separately is how one of them ends up
    quietly uncontained. ``sandbox`` arrives settled, by
    :func:`settled_sandbox`, so the fallback is said before this runs.

    It is also the one place that knows the whole opening: what the container
    had to say about itself, and whether the checks behind it passed. So the
    banner is said here, after the verification rather than before it -- a
    launch cannot report itself ready while the thing that would refute it
    has not run yet, and thirty lines printed ahead of the answer is how the
    refutation ends up below the fold. Both postures say it. A posture that
    says nothing leaves a transcript path in its place, printed on the way
    past by whatever opened the file.

    And it is where the boundary is settled, for the same reason: this is the
    one place that knows which posture the launch took, so it is the only
    place a boundary can be compiled that answers for the session actually
    about to open. Both postures write a ledger. A launch that wrote nothing
    would leave whatever a contained launch wrote last standing as this
    session's answer -- a boundary belonging to a session that has already
    ended.
    """
    banner = cleared.banner
    # Minted where both runtimes pass through, so a session's coordination
    # identity is a fact about having been launched rather than about which
    # CLI was launched. Exported rather than derived because the session's
    # tool server and its hooks are separate processes with no channel
    # between them, and an id each worked out for itself would put one
    # session on the roster twice. A launcher that already minted one, to
    # show its name in the runtime's own chrome, hands it in so the chrome
    # and the roster agree.
    #
    # Overwritten rather than respected. The variables are a launcher's claim
    # to have minted what is behind them, and an operator who happened to
    # have them exported would otherwise hand their own roster address to
    # every session they start — two peers answering to one id, which is the
    # one thing the durable id exists to rule out.
    environment.update((member or launched_member(project_root())).environment())
    environment[POLICY_ROOT_ENV] = str(project_root())

    # Settled once and handed to everything that needs it. Resolving a
    # registration can clone it, so a second resolution would be a second
    # trip to the forge -- and, where the two disagreed, a boundary compiled
    # against one set of roots and mounts built from another. The ad-hoc
    # mounts the caller named lead the list: they were asked for on this
    # command line, so they belong to this launch even where no registry does.
    def told(said: str) -> None:
        """Route the registry's own progress into the banner rather than past it."""
        banner.add([Notice(text=said, urgency="boundary")])

    accessible = [*mounts, *accessible_roots(told)]
    if not sandbox.contained():
        # A host posture holds the host's devices already, so a flag asking
        # for one describes a container this launch does not open. Said
        # rather than ignored: the operator typed it expecting a grant, and
        # silence would leave them reading a GPU that answers on the host as
        # one the flag delivered.
        if devices:
            banner.add(
                [
                    Notice(
                        text=(
                            "Devices: "
                            + ", ".join(device.name for device in devices)
                            + " asked for; the session runs on the host, which "
                            "holds its own devices, and --device grants one "
                            "inside the container."
                        ),
                        urgency="detail",
                    )
                ]
            )
        if prepare is not None:
            prepare([], config_home)
        if authenticate is not None:
            authenticate([cli], config_home, False)
        settle_boundary(
            plugin,
            sandbox,
            cleared.findings,
            sentinels,
            environment,
            banner,
            accessible,
            runtime=cli,
        )
        say_opening(cleared, cleared.findings, transcript)
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
    opening = contained_argv(
        harness.image,
        harness.requirements,
        project_root(),
        editor_rendezvous(login),
        credential if credential.exists() else None,
        login,
        inherited_environment=[
            # By name, so the value crosses out of this process's environment
            # rather than through an argv every process on the host can read.
            # The member id is not a secret, but a session whose id reached it
            # by a second route would be a session two mechanisms could
            # disagree about.
            *(
                [MAX_RECURSIVE_AGENT_ENV]
                if MAX_RECURSIVE_AGENT_ENV in environment
                else []
            ),
            MEMBER_ENV,
            NAME_ENV,
            POLICY_ROOT_ENV,
        ],
        banner=banner,
        sentinels=sentinels,
        accessible=accessible,
        # This launch's flags lead and the machine's standing grants follow,
        # settled here beside the roots for the same reason they are.
        devices=[*devices, *granted_devices(told)],
        home_seed=home_seed,
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
    inside = verify_inside(
        harness.requirements,
        probing(opening),
        setting_up=False,
        sentinels=sentinels,
        environment=environment,
        in_passing=True,
        accessible=accessible,
    )
    if prepare is not None:
        prepare(probing(opening, stdin=True), Path(harness.image.config_home))
    # A contained session sharing host loopback can receive a browser callback.
    # Device login is needed where that callback stays outside its namespace.
    if authenticate is not None:
        authenticate(
            [*probing(opening, stdin=True), cli],
            Path(harness.image.config_home),
            not harness.image.egress.shares_host_loopback(),
        )
    # Both halves of one measurement, joined here because this is where the
    # second is taken. The host roster answered for the relay and the store
    # before the container existed; the inside roster answered for the
    # placement behind the argv this session opens with. A preflight built
    # from either alone would report a capability nothing asked about.
    measured_here = [*cleared.findings, *inside]
    settle_boundary(
        plugin,
        sandbox,
        measured_here,
        sentinels,
        environment,
        banner,
        accessible,
        runtime=cli,
    )
    say_opening(cleared, measured_here, transcript)
    native = harness.image.clipboard.wrap(
        [cli, *arguments], composition.clipboard_transport
    )
    return [*opening, *native]


def say_opening(
    cleared: LaunchOpening, findings: list[Finding], transcript: Path | None
) -> None:
    """Say everything this launch held, once, in the order a reader wants it.

    The count is what replaces the roster. A reader who wants to know *which*
    checks passed is asking a question `harness requirements` answers on
    demand and a launch cannot answer usefully anyway -- the list is the same
    list as yesterday, every session, and the one time it differs is the one
    time a line is printed for it.
    """
    passed = sum(1 for finding in findings if finding.working)
    named = f"{cleared.runtime}: " if cleared.runtime else ""
    cleared.banner.add(
        [
            Notice(
                text=f"{named}artifacts current, {passed} checks passed",
                urgency="ready",
            ),
            *(
                [Notice(text=f"Transcript: {transcript}", urgency="artifact")]
                if transcript is not None
                else []
            ),
        ]
    )
    cleared.banner.say()


def probing(opening: list[str], *, stdin: bool = False) -> list[str]:
    """The session's own argv, with the interactive terminal taken back off.

    The same argv rather than a fresh one, because a probe assembled
    separately verifies a container no session opens -- an exercise that
    passes on a host whose sessions cannot start. The one difference is
    deliberate: a probe's output is captured, and ``-it`` against a pipe
    fails on the terminal it was promised.
    """
    return [
        "-i" if word == "-it" else word for word in opening if stdin or word != "-it"
    ]


def placed_inbox(
    inboxes: SessionInboxes, root: Path, member: LaunchedMember
) -> str | None:
    """Where this session binds the inbox a peer nudges it through, if anywhere.

    Named by the launcher rather than left to the runtime, whose own default
    is a directory a container does not share and a file named after a pid its
    namespace assigns -- so two sessions in sibling containers name one path
    and neither can reach the other. A directory that could not be made
    answers nothing, which is a peer that waits for its mail rather than a
    launch that fails.

    Refused where something already listens there, before the runtime can say
    so itself: its own refusal tells the reader to remove a socket that
    belongs to a live session. This one names the session, off the roster.
    """
    if inboxes.serve() is None:
        return None
    inbox = inboxes.socket(shared_git_directory(root), member.cli_name)
    if cleared(Path(inbox)):
        return inbox
    holders = RepositoryPeers(root).woken_through(inbox)
    raise typer.BadParameter(
        f"{', '.join(holders) or 'a process on no roster of this repository'} "
        f"is listening at {inbox}, the inbox this session would bind. lup "
        "leaves a live inbox alone rather than cut that session off from its "
        "nudges: end it, or let it finish, and launch again"
    )


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
    sandbox: LaunchSandbox | None = None,
    checkpoint: LaunchCheckpoint | None = None,
    max_recursive_agent: int = -1,
    transcribe_session: bool = False,
    companions: list[NativeHarnessComposition] = [],
    repository_writers: list[RepositoryWriter] = [],
    mounts: list[AccessibleRoot] = [],
    devices: list[Device] = [],
    recorder: SessionRecorder | None = None,
    effort: str | None = None,
) -> None:
    """Generate/reconcile Claude artifacts and launch the verified local plugin.

    ``sandbox`` is what the command line asked for, ``None`` where it named
    none; :func:`settled_sandbox` answers the default.
    """
    contradiction = resume.contradicted()
    if contradiction is not None:
        raise typer.BadParameter(contradiction)
    config = UserConfigFile()
    personal = personal_config(config)
    # A mode's model is a default rather than a fixture: it says what this kind
    # of session runs on when nobody said otherwise, and an explicit --model
    # still wins, because overriding the model is why a caller passes one.
    # Where neither names one, the person's tier does, as it does in code.
    selected_model = (
        model
        or (mode.native_model("claude") if mode is not None else None)
        or claude_model_id(personal.tier)
    )
    # Refused before anything is generated or checkpointed: an effort the
    # model's catalog row lacks would be dropped by the CLI without a word.
    # Unnamed, it is the model's default from the person's preferred rung, the
    # one a session declared in code takes, rather than the CLI's own settings.
    listed = None if selected_model is None else listed_claude_model(selected_model)
    try:
        chosen_effort = (
            claude_default_effort(listed, personal.effort or "xhigh")
            if effort is None
            else claude_effort_named(effort)
        )
        refuse_claude_effort(listed, chosen_effort)
    except ValueError as refusal:
        raise typer.BadParameter(str(refusal)) from refusal
    compiled_effort = None if chosen_effort is None else claude_effort(chosen_effort)
    if checkpoint is not None and not generate_only:
        checkpoint(provider="claude")
    plugin = composition.recipe.source.plugins[0]
    announce_relaxed_rules(relaxed, plugin)
    sentinels = LaunchSentinels()
    cleared = ready_to_open(
        composition,
        generate_only,
        sentinels,
        companions,
        repository_writers,
        sandbox=sandbox,
    )
    if cleared is None:
        return
    # What the gate settled on, which is the only posture read from here on.
    sandbox = cleared.sandbox
    arguments: list[str] = claude_resume_arguments(resume)
    if selected_model is not None:
        arguments.extend(["--model", selected_model])
    if compiled_effort is not None:
        arguments.extend(compiled_effort.arguments())
    root = project_root()
    # Minted here rather than where the argv is settled, because this runtime
    # shows the name in its own chrome and the flag carrying it is built now;
    # the same identity is handed on so the exported one agrees with it.
    member = launched_member(root)
    inbox = placed_inbox(composition.recipe.source.image.inboxes, root, member)
    named = [
        root / ".claude" / "plugins" / plugin.name,
        *companion_plugin_directories(root, plugin.name),
    ]
    arguments.extend(
        [
            *[flag for directory in named for flag in ("--plugin-dir", str(directory))],
            *claude_sandbox_arguments(
                plugin.hooks,
                sandbox=sandbox,
                accessible=(
                    [*mounts, *accessible_roots()]
                    if sandbox is LaunchSandbox.INNER
                    else []
                ),
                settings=(
                    compiled_effort.settings if compiled_effort is not None else None
                ),
                tree=find_tree_dir(),
            ),
            # What this runtime shows in its own chrome, made to agree with
            # the name the roster answers to: the same minted name is
            # exported for the session's tool server to join under, numbered
            # already where a live session in this worktree has the plain
            # one. The roster's name lives in `names.jsonl` and is what
            # addressing resolves through, so this is a display detail rather
            # than the identity — which is why Codex, whose launch takes no
            # such flag, loses nothing by it: a peer there is addressed by
            # exactly the same name, and renames through the same command.
            #
            # Ahead of `extra_args`, so a caller who named their own session
            # still wins.
            "--name",
            member.cli_name,
            # Where this session binds the inbox a peer nudges it through;
            # nowhere leaves the flag off and the session on its own default.
            *(["--messaging-socket-path", inbox] if inbox is not None else []),
            *(mode.command_words("claude") if mode is not None else []),
            *extra_args,
        ]
    )
    environment = non_interactive_environment(os.environ)  # lup: ignore[os-environ]
    environment[MAX_RECURSIVE_AGENT_ENV] = str(max_recursive_agent)
    apply_sandbox_environment(
        plugin.hooks,
        environment,
        "claude",
        [bubblewrap_requirement(), socat_requirement()],
        sandbox=sandbox,
    )
    # A name no origin answers to reaches here from an explicit --profile, and
    # from an active selection whose profile has since gone; a profile naming
    # the default home arrives by either route too. Each is the caller's to
    # fix, so none should arrive as a traceback.
    try:
        home = profiles.launch_home(profile)
    except (KeyError, DefaultHomeProfile) as error:
        raise typer.BadParameter(str(error)) from error
    if home is not None:
        environment.update(profiles.login.environment(home))
    # The theme is the account's, handed through its own files rather than as
    # a launch override, which would outrank a session's /theme: filled in
    # where the account keeps none, replaced only where the person's lup
    # config names one. A session on the host runs in the account's own home,
    # so what it changes there is the account's already.
    # lup: solved: a contained session runs in its repository's config volume,
    # so no theme reaches it and none it sets returns to the account; which
    # home a container's theme belongs to is the volume's question.
    # A contained session runs in its repository's volume instead, so the
    # account's settings are seeded into it at every start, the person's lup
    # config winning, and what the session changed of the person's comes
    # back when it closes.
    account = selected_config_home(environment)
    try:
        seed = (
            ClaudeHomeSeed.compose(
                account,
                personal,
                model=claude_model_id(personal.tier),
                effort=(
                    None
                    if personal.effort is None
                    else claude_effort(personal.effort).level
                ),
            )
            if sandbox.contained()
            else None
        )
        if seed is None:
            settle_claude_theme(account, personal.theme.claude)
    except ClaudeConfigUnreadable as error:
        raise typer.BadParameter(str(error)) from error
    seeded_at = Path(mkdtemp(prefix="lup-home-seed-")) if seed is not None else None
    places = (
        HomeSeedPlaces(
            seed=seed.write(seeded_at / "seed"), applied=seeded_at / "applied"
        )
        if seed is not None and seeded_at is not None
        else None
    )
    # Only a volume the seed reached is compared with it: before the
    # container starts, the volume still holds the previous session's
    # settings, and those read against this seed are no session's changes.
    seed_applied = False
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
        recorder=recorder,
    )
    succeeded = False
    interrupted = False
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
                home if home is not None else ambient_config_home(profiles.login),
                profiles.login,
                sandbox,
                environment,
                transcript.journal.path,
                sentinels,
                cleared,
                mounts,
                devices,
                member=member,
                home_seed=places,
            )
            seed_applied = places is not None
            sh.Command(argv[0])(*argv[1:], _fg=True, _env=environment)
        succeeded = True
    except KeyboardInterrupt:
        interrupted = True
        raise
    except sh.CommandNotFound as error:
        raise typer.BadParameter(
            f"Cannot launch Claude Code: executable {error} was not found. Check PATH."
        ) from error
    except sh.ErrorReturnCode as error:
        raise typer.Exit(error.exit_code) from error
    finally:
        # Taken away here rather than swept by the next launch, because a
        # launch that swept every ledger but its own would be correct exactly
        # once: with a second session open it removes a measurement that
        # session's dispatcher is still reading.
        release_ledger(project_root(), sentinels.nonce)
        transcript.close(succeeded=succeeded, interrupted=interrupted)
        if places is not None and seed_applied:
            # Measured against what this launch applied, which is the
            # seed settled against whatever a running session had changed.
            carry_claude_home(
                composition.recipe.source.image,
                project_root(),
                profiles.login,
                ClaudeHomeSeed.applied(places.applied),
                account,
                config,
                personal,
            )
        if seeded_at is not None:
            shutil.rmtree(seeded_at)
        if checkpoint is not None:
            checkpoint(provider="claude")


def carry_claude_home(
    image: Image,
    root: Path,
    login: ProviderLogin,
    seed: ClaudeHomeSeed,
    account: ClaudeConfigHome,
    config: UserConfigFile,
    personal: UserConfig,
) -> None:
    """Bring back what a contained session changed of the person's, and say what stayed.

    Read out of the volume the session ran in and compared with what this
    launch seeded, so only the session's own changes move. Where the
    volume cannot be read, nothing moves and the launch says so rather
    than leaving a changed theme to look as though it never happened.
    """
    files = read_config_home(
        image, root, login, [WORKSPACE_SETTINGS, CLAUDE_HOME_DOCUMENT, KEYBINDINGS]
    )
    settings = named_file(files, WORKSPACE_SETTINGS)
    document = named_file(files, CLAUDE_HOME_DOCUMENT)
    keybindings = named_file(files, KEYBINDINGS)
    try:
        read = [
            TypeAdapter(JsonObject).validate_json(held.content)
            for held in (settings, document)
            if held is not None
        ]
    except ValidationError:
        read = []
    if settings is None or len(read) != (2 if document is not None else 1):
        Notice(
            text=(
                "Could not read this session's Claude settings back out of "
                "its volume, so nothing it changed was returned."
            ),
            urgency="warning",
        ).say()
        return
    returned = ClaudeHomeReturn.between(
        seed,
        read[0],
        read[1] if document is not None else {},
        keybindings.text() if keybindings is not None else None,
        personal,
    )
    returned.apply(account, config)
    if returned.carried():
        typer.echo(
            "Returned the Claude settings this session changed: "
            + ", ".join(returned.carried())
        )
    stayed = [
        *(f"{key} (never leaves a container)" for key in returned.withheld),
        *(f"{key} (the session's own)" for key in returned.session),
    ]
    if stayed:
        typer.echo("Kept in the container: " + ", ".join(stayed))


def settled_codex_seed(image: Image, theirs: JsonObject) -> JsonObject:
    """What a contained Codex home will be given, and where the person's settings won.

    The three-way merge the home's own installation runs
    (:func:`~lup.providers.codex.home.seeded_codex_settings`), run first on
    the volume as it stands, so the launch knows what its session starts
    from and can say which settings a running session had changed too.
    """
    files = read_config_home(
        image, project_root(), CODEX_LOGIN, ["config.toml", SEED_RECORD]
    )
    current = named_file(files, "config.toml")
    recorded = named_file(files, SEED_RECORD)
    seeded = seeded_codex_settings(
        current.text() if current is not None else None,
        recorded.text() if recorded is not None else None,
        theirs,
    )
    for conflict in seeded.conflicts:
        Notice(
            text=(
                f"Settings: {conflict} was changed both by a session still "
                "running in this repository and in your own settings; yours win."
            ),
            urgency="warning",
        ).say()
    return seeded.settings


def carry_codex_home(
    store: CodexWorktreeHomeStore,
    image: Image | None,
    config: UserConfigFile,
    applied: JsonObject | None = None,
) -> None:
    """Bring back what a Codex session changed of the person's, and say what stayed.

    ``image`` is the container a contained session ran in, whose volume
    holds the configuration it left; ``None`` reads the worktree home a
    session on the host ran in. A volume that cannot be read moves
    nothing, said aloud.
    """
    left = None
    if image is not None:
        read = named_file(
            read_config_home(image, project_root(), CODEX_LOGIN, ["config.toml"]),
            "config.toml",
        )
        if read is None:
            Notice(
                text=(
                    "Could not read this session's Codex settings back out of "
                    "its volume, so nothing it changed was returned."
                ),
                urgency="warning",
            ).say()
            return
        left = read.text()
    returned = store.return_settings(
        project_root(), config, current=left, applied=applied
    )
    if returned.carried():
        typer.echo(
            "Returned the Codex settings this session changed: "
            + ", ".join(returned.carried())
        )
    stayed = [
        *(f"{key} (never leaves its home)" for key in returned.withheld),
        *(f"{key} (the session's own)" for key in returned.session),
    ]
    if stayed:
        typer.echo("Kept in the session's home: " + ", ".join(stayed))


def prepare_codex_plugin(
    prefix: list[str],
    home: Path,
    root: Path,
    environment: EnvVars,
    force: bool = False,
    trusted: bool = False,
    settings: CodexProfileSettings | None = None,
) -> None:
    """Prepare the home where the launch runs, through its own execution boundary."""
    if not prefix:
        if settings is not None:
            settings.install(
                home, enforce_policy=CodexMarketplace.declared(root) is not None
            )
        install_codex_plugin(root, home, force, trusted)
        return
    assert CODEX_LOGIN.home_preparation is not None
    command = [
        *prefix,
        *CODEX_LOGIN.home_preparation.command(root, home, force, settings is not None),
    ]
    typer.echo(
        str(
            sh.Command(command[0])(
                *command[1:],
                _env=environment,
                _in=settings.model_dump_json() if settings is not None else None,
            )
        ),
        nl=False,
    )


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
    sandbox: LaunchSandbox | None = None,
    checkpoint: LaunchCheckpoint | None = None,
    max_recursive_agent: int = -1,
    transcribe_session: bool = False,
    companions: list[NativeHarnessComposition] = [],
    repository_writers: list[RepositoryWriter] = [],
    mounts: list[AccessibleRoot] = [],
    devices: list[Device] = [],
    recorder: SessionRecorder | None = None,
    effort: str | None = None,
) -> None:
    """Generate/reconcile Codex artifacts and launch without updating the CLI.

    ``sandbox`` is read as :func:`launch_claude` reads it.
    """
    contradiction = resume.contradicted()
    if contradiction is not None:
        raise typer.BadParameter(contradiction)
    config = UserConfigFile()
    personal = personal_config(config)
    named_model = model or (mode.native_model("codex") if mode is not None else None)
    # A named profile with no model named over it chose its model and effort
    # together, so neither the person's tier nor a default effort is sent.
    profiled = profile is not None and named_model is None
    selected_model = (
        named_model
        if named_model is not None or profiled
        else codex_model_id(personal.tier, CodexModelTiers())
    )
    # Refused before anything is generated or checkpointed: the API refuses an
    # effort the model lacks with a 400 that names neither. Unnamed, it is the
    # model's default from the person's preferred rung, the one a session
    # declared in code takes, rather than whatever the home's configuration says.
    listed = None if selected_model is None else listed_codex_model(selected_model)
    try:
        chosen_effort = (
            codex_effort_named(effort)
            if effort is not None
            else None
            if profiled
            else codex_default_effort(
                listed, CodexModelTiers(), personal.effort or "xhigh"
            )
        )
        refuse_codex_effort(listed, chosen_effort, CodexModelTiers())
    except ValueError as refusal:
        raise typer.BadParameter(str(refusal)) from refusal
    if checkpoint is not None and not generate_only:
        checkpoint(provider="codex")
    plugin = composition.recipe.source.plugins[0]
    announce_relaxed_rules(relaxed, plugin)
    sentinels = LaunchSentinels()
    cleared = ready_to_open(
        composition,
        generate_only,
        sentinels,
        companions,
        repository_writers,
        sandbox=sandbox,
    )
    if cleared is None:
        return
    # What the gate settled on, which is the only posture read from here on.
    sandbox = cleared.sandbox
    environment = non_interactive_environment(os.environ)  # lup: ignore[os-environ]
    environment[MAX_RECURSIVE_AGENT_ENV] = str(max_recursive_agent)
    envelope = codex_sandbox_arguments(
        plugin.hooks,
        environment,
        extra_args,
        sandbox=sandbox,
        accessible=(
            [*mounts, *accessible_roots()] if sandbox is LaunchSandbox.INNER else []
        ),
        tree=find_tree_dir(),
    )
    # The account a worktree home is derived from, and returns its login and
    # settings to: the selected profile, this checkout's then the global one,
    # resolved as on Claude, else the operator's own default home.
    try:
        account_home = profile_directory(CODEX_LOGIN, config).launch_home(None)
    except (KeyError, DefaultHomeProfile) as error:
        raise typer.BadParameter(str(error)) from error
    store = CodexWorktreeHomeStore(
        account_home=account_home or CODEX_LOGIN.ambient_home,
        theme=personal.theme.codex,
        editor=personal.editor,
        settings=personal.codex.settings,
    )
    # Only a volume the settings reached is compared with them: before the
    # container's home is prepared, it still holds the previous session's.
    installed: list[Path] = []
    # What a contained session's volume was given, settled three ways
    # against a session that may still be running there.
    applied: list[JsonObject] = []
    home = select_codex_home(codex_home, environment, project_root(), profile, store)
    selected_home = home.path
    selected_profile = (
        CodexProfileSettings.capture(
            selected_home, profile, as_base=sandbox.contained()
        )
        if profile is not None or sandbox.contained()
        else None
    )
    if home.isolated:
        typer.echo(
            f"Using worktree-scoped Codex home: {selected_home}, derived from "
            f"{store.account_home}"
        )
    # The subcommand leads, and everything the envelope carries follows it,
    # because a word placed after a positional session id would be read as
    # another one.
    arguments: list[str] = [*codex_resume_arguments(resume), *envelope]
    if selected_profile is not None and not selected_profile.as_base:
        arguments.extend(
            [
                "--profile",
                selected_profile.installed_name(),
            ]
        )
    if selected_model is not None:
        arguments.extend(["--model", selected_model])
    if chosen_effort is not None:
        arguments.extend(codex_effort_arguments(chosen_effort))
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
        recorder=recorder,
    )
    succeeded = False
    interrupted = False
    opening = (
        nullcontext({})
        if mode is None
        else mode.opened("codex", transcript.journal, transcribing)
    )

    def authenticate(command: list[str], native_home: Path, headless: bool) -> None:
        codex_login_preflight(
            native_home,
            environment,
            command,
            headless=headless,
            profile=None if sandbox.contained() else profile,
        )
        if home.isolated and not sandbox.contained():
            store.publish(project_root())

    def prepare(prefix: list[str], native_home: Path) -> None:
        if prefix and selected_profile is not None:
            applied.append(
                settled_codex_seed(
                    composition.recipe.source.image,
                    selected_profile.personal_settings(
                        CodexMarketplace.declared(project_root()) is not None
                    ),
                )
            )
        prepare_codex_plugin(
            prefix,
            native_home,
            project_root(),
            environment,
            force_install,
            settings=selected_profile,
        )
        installed.append(native_home)

    try:
        with opening as session:
            environment.update(session)
            argv = session_argv(
                "codex",
                arguments,
                composition,
                plugin,
                selected_home,
                CODEX_LOGIN,
                sandbox,
                environment,
                transcript.journal.path,
                sentinels,
                cleared,
                mounts,
                devices,
                authenticate=authenticate,
                prepare=prepare,
            )
            sh.Command(argv[0])(*argv[1:], _fg=True, _env=environment)
        succeeded = True
    except KeyboardInterrupt:
        interrupted = True
        raise
    except sh.CommandNotFound as error:
        raise typer.BadParameter(
            f"Cannot launch Codex: executable {error} was not found. Check PATH."
        ) from error
    except sh.ErrorReturnCode as error:
        raise typer.Exit(error.exit_code) from error
    finally:
        release_ledger(project_root(), sentinels.nonce)
        transcript.close(succeeded=succeeded, interrupted=interrupted)
        if home.isolated and store.publish(project_root()):
            typer.echo("Returned the refreshed Codex login to the account home")
        # lup: solved: a contained session runs in its repository's config
        # volume, so a setting it changes there — its /theme included — never
        # returns to the account; which home those belong to is the volume's
        # question.
        if home.isolated and (installed or not sandbox.contained()):
            carry_codex_home(
                store,
                composition.recipe.source.image if sandbox.contained() else None,
                config,
                applied[0] if applied else None,
            )
        if checkpoint is not None:
            checkpoint(provider="codex")
