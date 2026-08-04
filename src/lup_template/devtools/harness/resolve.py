"""Resolver command glue between the CLI and the shared persisted resolver.

Owns the console question broker, resolver-scoped Git snapshotting of
review-note files, the per-adapter worker and reviewer session factories,
and the driver that starts a persisted resolver run, resumes it, and widens
it with work discovered while it ran.
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import sh
import typer
from pydantic import BaseModel, ConfigDict

from lup.codescan.markers import find_feedback
from lup.mcp import create_mcp_server, serve_stdio, server_tool_names
from lup.policy.identity import (
    agent_identity_environment,
    concern_allowances_environment,
)
from lup.harness.environment import non_interactive_environment
from lup.harness.process import LaunchRequest, LocalProcessLauncher, ProcessLauncher
from lup.resolver.contracts import (
    ResolverAwaitingAnswers,
    ResolverObserver,
    WorktreePreparer,
)
from lup.resolver.core import ResolverCore
from lup.resolver.models import (
    AdmissionRequest,
    Concern,
    ConcernAdmission,
    ConcernProgress,
    InventoryNote,
    MaterialQuestion,
    ResolvePhase,
    ResolveRequest,
    ResolverConfig,
    SourceSnapshot,
    VerificationCommand,
    WorkerContext,
)
from lup.channels.models import utc_now
from lup.resolver.mailbox import (
    AnswerDoor,
    AnswerOffer,
    QuestionMailbox,
)
from lup.resolver.tools import (
    RESOLVER_CONCERN_ENV,
    RESOLVER_RUN_DIR_ENV,
    ResolverToolContext,
    create_inbox_hooks,
    create_question_tools,
    read_resolver_tool_context,
)
from lup.runtime.factory import SessionFactory
from lup.types import EnvVars
from lup.workspace.paths import project_root
from lup_template.devtools.dev.comments import FoundComment, scan_tracked
from lup_template.devtools.dev.remote_auth import check_remote_auth
from lup_template.devtools.dev.worktree import (
    copy_gitignored_extras,
    sync_dependencies,
)
from lup_template.devtools.harness.composition import harness_compositions


class ResolverIntake(BaseModel):
    """The scan partitioned at the resolver boundary.

    Deferred notes never enter the resolver inventory — waking one is an
    explicit edit that removes its `defer[...]` head — so an editor can
    never be assigned parked work. ``carried`` reports each parked note.
    """

    actionable: list[FoundComment]
    carried: list[str]


def resolver_intake(comments: list[FoundComment]) -> ResolverIntake:
    """Partition scanned notes into resolver work and carried deferrals."""
    return ResolverIntake(
        actionable=[comment for comment in comments if comment.kind == "note"],
        carried=[
            f"carrying deferred[{comment.condition}] "
            f"{comment.file}:{comment.start_line}-{comment.end_line}"
            for comment in comments
            if comment.kind == "defer"
        ],
    )


class FeatureWorktreePreparer(WorktreePreparer):
    """Prepare leased resolver worktrees exactly like feature worktrees.

    Copies the same gitignored extras and runs the same dependency sync as
    ``dev worktree create``, so verification and tests inside a lease bind
    to the leased checkout instead of the source tree's environment.
    """

    def __init__(self, source_root: Path) -> None:
        self.source_root = source_root

    def prepare(self, root: Path) -> None:
        copy_gitignored_extras(self.source_root, root)
        sync_dependencies(root)


class ConsoleResolverObserver(ResolverObserver):
    """Print one line per durably recorded resolver transition.

    Long worker phases are otherwise silent; these lines are the liveness
    signal that lets an operator stop polling state files and worktrees.
    """

    def phase_changed(self, phase: ResolvePhase) -> None:
        typer.echo(f"[resolve] phase: {phase}")

    def concern_changed(self, progress: ConcernProgress) -> None:
        line = f"[resolve] {progress.concern_id}: {progress.status}"
        if progress.reason:
            line = f"{line} ({progress.reason})"
        typer.echo(line)


def parse_answer_flags(
    flags: list[str],
) -> dict[str, str]:  # lup: ignore[dict-str-payload] — open question-id map
    """Split repeatable ``--answer`` flags into a question-id to value map."""
    pairs = [
        flag.split("=", 1)  # lup: ignore[string-split] — this CLI's flag grammar
        for flag in flags
    ]
    malformed = [
        flag
        for flag, pair in zip(flags, pairs, strict=True)
        if len(pair) != 2 or not pair[0]
    ]
    if malformed:
        raise typer.BadParameter(
            "--answer takes <question-id>=<value>; got: " + ", ".join(malformed)
        )
    identifiers = [pair[0] for pair in pairs]
    if len(identifiers) != len(dict.fromkeys(identifiers)):
        raise typer.BadParameter("--answer question ids must be unique")
    return {pair[0]: pair[1] for pair in pairs}


class NoteTargetRef(BaseModel):
    """One `file:line` target naming a note already written in the tree."""

    model_config = ConfigDict(frozen=True)

    file: Path
    line: int


def parse_note_targets(targets: list[str]) -> list[NoteTargetRef]:
    """Split repeatable ``--admit-note`` flags into located note targets."""
    parsed = [
        target.rpartition(":")  # lup: ignore[string-split] — this CLI's flag grammar
        for target in targets
    ]
    malformed = [
        target
        for target, pair in zip(targets, parsed, strict=True)
        if not pair[0] or not pair[2].isdigit()
    ]
    if malformed:
        raise typer.BadParameter(
            "--admit-note takes <file>:<line>; got: " + ", ".join(malformed)
        )
    return [NoteTargetRef(file=Path(pair[0]), line=int(pair[2])) for pair in parsed]


def admission_notes(
    targets: list[NoteTargetRef], actionable: list[FoundComment]
) -> list[InventoryNote]:
    """Locate each named note among the notes a scan found actionable.

    The note's own text and surrounding context are carried rather than
    retyped, so a concern admitted from a note is grounded in exactly what
    intake would have planned from. Deferred notes never reach ``actionable``,
    so a target landing on parked work is refused with the rest.
    """
    located = {
        f"{comment.file}:{comment.start_line}": comment for comment in actionable
    }
    missing = [
        f"{target.file}:{target.line}"
        for target in targets
        if f"{target.file}:{target.line}" not in located
    ]
    if missing:
        raise typer.BadParameter(
            "no actionable `# lup:` note at: " + ", ".join(missing)
        )
    return [
        InventoryNote(
            file=target.file,
            line=located[f"{target.file}:{target.line}"].start_line,
            text=located[f"{target.file}:{target.line}"].marker_text(),
            context=located[f"{target.file}:{target.line}"].context,
        )
        for target in targets
    ]


def offer_flag_answers(
    mailbox: QuestionMailbox,
    run_id: str,
    provided: dict[str, str],  # lup: ignore[dict-str-payload] — open id map
) -> None:
    """Offer every ``--answer`` value through the mailbox.

    Offers may precede their questions, so a flag answers a question this
    run has not asked yet — which is why a fresh run no longer has to park
    once before its answers can count.
    """
    for identifier, value in provided.items():
        mailbox.offer(
            AnswerOffer(
                run_id=run_id,
                question_id=identifier,
                value=value,
                door=AnswerDoor.FLAG,
                offered_at=utc_now(),
            )
        )


def run_resolver_tool_server() -> None:
    """Serve the question tools to a worker whose tools run out of process.

    The Codex runtime spawns MCP servers as subprocesses, so a handler there
    cannot see any in-process object. It rebuilds the same mailbox from the
    relayed run directory instead, which is why the mailbox is files.
    """
    context = read_resolver_tool_context()
    if context is None:
        raise typer.BadParameter(
            f"{RESOLVER_RUN_DIR_ENV} and {RESOLVER_CONCERN_ENV} must both be set"
        )
    serve_stdio(
        create_mcp_server(
            "resolver",
            tools=create_question_tools(
                QuestionMailbox(context.run_dir),
                context.concern_id,
                run_id=context.run_dir.name,
            ),
        )
    )


SUPERVISED_WAIT_SECONDS = 3600.0


class SupervisorSpawn(BaseModel):
    """Whether a run opens a page beside itself, and on which port."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    port: int = 8766
    linger: bool = False


@asynccontextmanager
async def spawned_supervisor(
    spawn: SupervisorSpawn, run_id: str, adapter: str
) -> AsyncGenerator[None]:
    """Run the supervisor page beside this run, as a separate process.

    The page is an ordinary reader of the run directory, so it does not
    have to share this process — which is what removes the whole thread
    split the in-process host needed. The run's own loop hosts nothing.
    """
    if not spawn.enabled:
        yield
        return
    process = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "lup-devtools",
        "harness",
        "resolve",
        "supervise",
        "--run-id",
        run_id,
        "--adapter",
        adapter,
        "--port",
        str(spawn.port),
    )
    typer.echo(f"Resolver supervisor: http://127.0.0.1:{spawn.port}")
    try:
        yield
    finally:
        if spawn.linger:
            typer.echo("Supervisor left running; stop it with Ctrl-C in its terminal.")
        else:
            process.terminate()
            await process.wait()


def report_concern_evidence(concern: Concern) -> None:
    """Print what a concern was planned from, so its questions can be judged.

    A question prompt alone reads as a decision with no stakes: whoever
    answers it needs the `# lup:` notes that raised it and the spec the
    planner wrote from them, or they are guessing on the asker's behalf.
    """
    typer.echo(f"concern {concern.id}: {concern.title}")
    for note in concern.notes:
        typer.echo(f"  note {note.file}:{note.line}: {note.text}")
    for criterion in concern.criteria:
        typer.echo(f"  criterion {criterion.id}: {criterion.description}")
    for path in concern.files:
        typer.echo(f"  starting file: {path}")
    typer.echo(f"  spec: {concern.spec}")


def report_questions(
    questions: list[MaterialQuestion], concerns: list[Concern]
) -> None:
    """Print each open question under the concern evidence that raised it."""
    evidence = {concern.id: concern for concern in concerns}
    for concern_id in dict.fromkeys(question.concern_id for question in questions):
        if concern_id in evidence:
            report_concern_evidence(evidence[concern_id])
        for question in [item for item in questions if item.concern_id == concern_id]:
            typer.echo(f"question {question.id} (concern {concern_id}):")
            typer.echo(f"  {question.prompt}")
            if question.choices:
                typer.echo("  choices: " + " | ".join(question.choices))
            if question.recommendation is not None:
                typer.echo(f"  recommendation: {question.recommendation}")
            if not question.closed_choices:
                typer.echo("  (choices are suggestions; any answer is accepted)")


def rerun_recipe(adapter: str, run_id: str, questions: list[MaterialQuestion]) -> str:
    """The exact command that answers these questions and drives the run on."""
    return " ".join(
        [
            "uv run lup-devtools harness resolve",
            f"--adapter {adapter}",
            f"--run-id {run_id}",
            *(f"--answer {question.id}=<value>" for question in questions),
        ]
    )


def report_awaiting(
    parked: ResolverAwaitingAnswers,
    adapter: str,
    run_id: str,
    concerns: list[Concern],
) -> None:
    """Print parked questions, their evidence, and the rerun recipe."""
    typer.echo("Resolver run parked awaiting material answers.")
    for problem in parked.problems:
        typer.echo(f"  problem: {problem}")
    report_questions(parked.pending, concerns)
    typer.echo("Relay the questions to the human, then rerun:")
    typer.echo(f"  {rerun_recipe(adapter, run_id, parked.pending)}")


def report_admission(admission: ConcernAdmission, adapter: str, run_id: str) -> None:
    """Print what joined the run and the gates it still has to pass."""
    typer.echo(
        f"Admitted {len(admission.concerns)} concern(s) into {run_id} "
        f"at phase {admission.phase}."
    )
    report_questions(admission.questions, admission.concerns)
    typer.echo("Relay the new questions to the human, then rerun:")
    typer.echo(f"  {rerun_recipe(adapter, run_id, admission.questions)}")


def resolver_git(
    launcher: ProcessLauncher,
    root: Path,
    arguments: list[str],
    *,
    environment: EnvVars | None = None,
) -> str:
    """Run one resolver-owned Git inspection or snapshot operation."""
    status = launcher.launch(
        LaunchRequest(
            arguments=["git", *arguments],
            cwd=root,
            environment=environment or {},
        )
    )
    if status.code != 0:
        raise RuntimeError(
            f"resolver Git operation failed ({' '.join(arguments)}): {status.stderr}"
        )
    lines = status.stdout.splitlines()
    return lines[0] if len(lines) == 1 else "\n".join(lines)


def resolver_source_snapshot(
    launcher: ProcessLauncher,
    root: Path,
    run_root: Path,
    note_paths: list[Path],
) -> SourceSnapshot:
    """Create an unattached source commit containing current review-note files."""
    branch = resolver_git(launcher, root, ["branch", "--show-current"]) or "HEAD"
    head = resolver_git(launcher, root, ["rev-parse", "HEAD"])
    status = launcher.launch(
        LaunchRequest(
            arguments=["git", "diff", "--quiet", "HEAD", "--", *map(str, note_paths)],
            cwd=root,
        )
    )
    if status.code == 0:
        return SourceSnapshot(branch=branch, commit=head)
    if status.code != 1:
        raise RuntimeError(f"resolver source inspection failed: {status.stderr}")
    run_root.mkdir(parents=True, exist_ok=True)
    index = (run_root / ".source.index").resolve()
    environment = {"GIT_INDEX_FILE": str(index)}
    try:
        resolver_git(launcher, root, ["read-tree", "HEAD"], environment=environment)
        resolver_git(
            launcher,
            root,
            ["add", "--", *map(str, note_paths)],
            environment=environment,
        )
        tree = resolver_git(launcher, root, ["write-tree"], environment=environment)
        commit = resolver_git(
            launcher,
            root,
            [
                "commit-tree",
                tree,
                "-p",
                head,
                "-m",
                "chore(review): resolver source snapshot",
            ],
            environment=environment,
        )
    finally:
        if index.exists():
            index.unlink()
    return SourceSnapshot(branch=branch, commit=commit)


REVIEW_BRANCH_SUFFIX = "/review"


def integration_branch(launcher: ProcessLauncher, root: Path, run_id: str) -> str:
    """Where this run integrates: onto a standing review branch, or a fresh one.

    A resolve run started while HEAD is already a review branch is resolving
    that branch's own feedback, so minting a second one strands the work on a
    branch nobody asked for and leaves the human to reconcile two. Advancing
    the branch it was launched from is what makes a nested run compose.
    """
    current = resolver_git(launcher, root, ["branch", "--show-current"])
    if current.startswith("resolve/") and current.endswith(REVIEW_BRANCH_SUFFIX):
        return current
    return f"resolve/{run_id}{REVIEW_BRANCH_SUFFIX}"


def detach_resolve(adapter: str, run_id: str | None, answers: list[str]) -> None:
    """Start a run that outlives this command, and say where to reach it.

    A blocking run holds the launching agent's only turn, so nothing could
    write to a run while it moved — which made every delivery route in the
    design unreachable, however well the channels underneath worked. Once
    launching returns, the run directory is the whole contract: the page and
    an orchestrating agent are peers on it, exactly as two pages would be.
    """
    root = project_root()
    resolved = run_id or (
        "resolve-"
        + resolver_git(
            LocalProcessLauncher(), root, ["rev-parse", "--short=12", "HEAD"]
        )
    )
    arguments = [
        "uv",
        "run",
        "lup-devtools",
        "harness",
        "resolve",
        "--adapter",
        adapter,
        "--run-id",
        resolved,
        *(part for answer in answers for part in ("--answer", answer)),
    ]
    sh.Command(arguments[0])(
        *arguments[1:],
        _cwd=str(root),
        _bg=True,
        _bg_exc=False,
        _new_session=True,
        _out="/dev/null",
        _err="/dev/null",
    )
    typer.echo(f"Run {resolved} started detached.")
    typer.echo(
        f"Follow it: uv run lup-devtools harness resolve supervise --run-id {resolved}"
    )


def admission_request(
    statements: list[str], note_targets: list[str]
) -> AdmissionRequest | None:
    """Build the evidence one invocation asked to admit, if it asked at all."""
    if not statements and not note_targets:
        return None
    targets = parse_note_targets(note_targets)
    scanned = resolver_intake(scan_tracked(find_feedback)).actionable if targets else []
    return AdmissionRequest(
        notes=admission_notes(targets, scanned), statements=statements
    )


def run_resolve(
    adapter: str,
    run_id: str | None,
    answers: list[str],
    abort_reason: str | None = None,
    wait_seconds: float = 0.0,
    supervisor: SupervisorSpawn | None = None,
    admission: AdmissionRequest | None = None,
) -> None:
    """Drive the shared persisted resolver through one explicit native adapter."""
    provided = parse_answer_flags(answers)
    if abort_reason is not None and admission is not None:
        raise typer.BadParameter("a run cannot be widened and ended in one command")
    compositions = harness_compositions(adapter)
    if len(compositions) != 1:
        raise typer.BadParameter("resolve requires exactly one adapter")
    composition = compositions[0]
    root = project_root()
    if not check_remote_auth():
        typer.echo(
            "Continuing local-only: agent git commands that need the remote "
            "will fail fast instead of prompting.",
            err=True,
        )
    launcher = LocalProcessLauncher()
    resolved_run_id = run_id or (
        "resolve-" + resolver_git(launcher, root, ["rev-parse", "--short=12", "HEAD"])
    )
    # Every concern worktree is created from here, so it is what a worker's
    # own diff is measured against when scoping the note gate.
    base_commit = resolver_git(launcher, root, ["rev-parse", "HEAD"])

    async def execute() -> None:
        from lup.adapters.claude.runtime import (
            ClaudeSandboxConfig,
            ClaudeSessionConfig,
            create_claude_session_factory,
        )
        from lup.adapters.codex.runtime import (
            CodexMcpServerConfig,
            CodexSessionConfig,
            create_codex_session_factory,
        )
        from lup_template.agent.config import engine_for_model, settings
        from lup.adapters.claude.hooks import claude_hook_semantic_tool
        from lup.harness.enforcement import semantic_policy_for
        from lup.hooks import (
            LupHooksConfig,
            create_git_inspection_hook,
            create_permission_hooks,
            merge_hooks,
        )
        from lup.policy.enforcement import create_policy_hooks

        from lup_template.devtools.harness.catalog import (
            declared_hook_set,
            portable_harness,
        )

        session_environment = non_interactive_environment(
            os.environ  # lup: ignore[os-environ] — sessions inherit the console
        )
        # Both identities are written, never omitted: a runtime merges the
        # session environment over the launching process's, so a reviewer
        # that stayed silent would inherit an operator's exported identity.
        worker_environment = {
            **session_environment,
            **agent_identity_environment(portable_harness().resolver.worker_identity),
        }
        reviewer_environment = {
            **session_environment,
            **agent_identity_environment(""),
            **concern_allowances_environment([]),
        }
        session_model = (
            settings.model if engine_for_model(settings.model) == adapter else None
        )
        if session_model is None:
            typer.echo(
                f"Configured model {settings.model!r} does not route to adapter "
                f"{adapter!r}; sessions use the adapter's native default model."
            )

        state_root = root / ".lup" / "resolve"

        def toolchain_writable_paths() -> list[Path]:
            """Absolute paths a sandboxed worker's toolchain must be able to write.

            A worker is contained to its lease, which is where its work belongs
            — but every command it verifies with reaches the toolchain through
            `uv`, whose cache lives outside any worktree. Granting the declared
            paths is what keeps containment from disarming verification.
            """
            hooks = portable_harness().plugins[0].hooks
            declared = hooks.sandbox if hooks is not None else None
            return [
                Path(path).expanduser()
                for path in (declared.writable_paths if declared is not None else [])
            ]

        def worker_factory(context: WorkerContext) -> SessionFactory:
            """Open one worker session that can ask its own questions.

            The tools are bound to this concern here rather than taking the
            id as an argument, so a worker structurally cannot post against
            a sibling. ``core`` is read at call time, which is after it is
            built — the wake event only exists once the core does.
            """
            cwd = context.root
            tool_context = ResolverToolContext(
                run_dir=state_root / resolved_run_id, concern_id=context.concern_id
            )
            # Grants are per-concern: a lease carries only what the human
            # approved with the concern it was leased for.
            concern_environment = {
                **worker_environment,
                **concern_allowances_environment(
                    [allowance.value for allowance in context.allowances]
                ),
            }
            if adapter == "claude":
                server = create_mcp_server(
                    "resolver",
                    tools=create_question_tools(
                        QuestionMailbox(tool_context.run_dir),
                        context.concern_id,
                        run_id=resolved_run_id,
                        wake=core.wake,
                    ),
                )
                return create_claude_session_factory(
                    ClaudeSessionConfig(
                        model=session_model,
                        system_prompt="Execute the persisted Lup resolver assignment.",
                        cwd=cwd,
                        add_dirs=[cwd, *toolchain_writable_paths()],
                        sandbox=ClaudeSandboxConfig(),
                        environment=concern_environment,
                        tool_servers={"resolver": server},
                        allowed_tools=[
                            f"mcp__resolver__{name}"
                            for name in server_tool_names(server)
                        ],
                        hooks=merge_hooks(
                            merge_hooks(
                                merge_hooks(
                                    create_permission_hooks([cwd], []),
                                    worker_policy_hooks(),
                                ),
                                create_git_inspection_hook(),
                            ),
                            create_inbox_hooks(
                                QuestionMailbox(tool_context.run_dir),
                                context.concern_id,
                            ),
                        ),
                    )
                )
            return create_codex_session_factory(
                CodexSessionConfig(
                    model=session_model,
                    developer_instructions=(
                        "Execute the persisted Lup resolver assignment."
                    ),
                    cwd=cwd,
                    sandbox="workspace-write",
                    approval_policy="never",
                    environment=concern_environment,
                    mcp_servers={
                        "resolver": CodexMcpServerConfig(
                            command="uv",
                            args=[
                                "run",
                                "lup-devtools",
                                "harness",
                                "serve-resolver-tools",
                            ],
                            env={**session_environment, **tool_context.to_env()},
                        )
                    },
                    writable_roots=[cwd],
                )
            )

        def worker_policy_hooks() -> LupHooksConfig:
            """Judge a worker's calls by the policy every plugin enforces.

            The directory ACL beside this bounds where a worker may write and
            says nothing about what it may read, fetch, or run — so reads,
            egress and every non-filesystem act passed unjudged, with the OS
            sandbox as the only floor. What blocked this before was that a
            denial had nowhere to go; the `ask` verdict reaches the mailbox
            now, so a worker meeting a genuine need outside the vocabulary
            asks for it instead of failing.

            The worker is autonomous because its edits are reviewed by an
            actor of this run, which is the same fact the generated tree
            derives its autonomous list from.
            """
            return create_policy_hooks(
                semantic_policy_for(
                    declared_hook_set(), autonomous=True, interactive=False
                ),
                claude_hook_semantic_tool,
            )

        def reviewer_factory(cwd: Path) -> SessionFactory:
            if adapter == "claude":
                return create_claude_session_factory(
                    ClaudeSessionConfig(
                        model=session_model,
                        system_prompt=(
                            "Independently review the persisted resolver change."
                        ),
                        cwd=cwd,
                        add_dirs=[cwd],
                        environment=reviewer_environment,
                        hooks=create_permission_hooks([], [cwd]),
                    )
                )
            return create_codex_session_factory(
                CodexSessionConfig(
                    model=session_model,
                    developer_instructions=(
                        "Independently review the persisted resolver change."
                    ),
                    cwd=cwd,
                    sandbox="read-only",
                    approval_policy="never",
                    environment=reviewer_environment,
                )
            )

        offer_flag_answers(
            QuestionMailbox(state_root / resolved_run_id), resolved_run_id, provided
        )
        core = ResolverCore(
            ResolverConfig(
                state_root=state_root,
                workspace=root,
                worktree_root=(root.parent / f"{root.name}-resolve-{resolved_run_id}"),
                run_id=resolved_run_id,
                integration_branch=integration_branch(launcher, root, resolved_run_id),
                # The whole gate rather than part of it restated. Naming three
                # of its checks let a worker introduce an anti-pattern or
                # leave an unresolved note and still verify green — the two
                # rules most specific to this repository were the ones its own
                # output was not held to. `--since` scopes the note gate to
                # what this tree changed, because a concern's worktree holds
                # every sibling's notes and it has no lease on any of them.
                verification_commands=[
                    VerificationCommand(
                        name="dev check",
                        arguments=[
                            "uv",
                            "run",
                            "lup-devtools",
                            "dev",
                            "check",
                            "--since",
                            base_commit,
                        ],
                    ),
                ],
            ),
            portable_harness().resolver,
            worker_factory,
            reviewer_factory,
            composition.invocation_renderer,
            launcher,
            observer=ConsoleResolverObserver(),
            worktree_preparer=FeatureWorktreePreparer(root),
            answer_wait_seconds=wait_seconds,
        )

        async def drive() -> None:
            if abort_reason is not None:
                if not core.repository.exists():
                    raise typer.BadParameter(
                        f"no resolver run {resolved_run_id!r} to abort"
                    )
                aborted = core.abort(abort_reason)
                for record in aborted.cleanup:
                    typer.echo(
                        f"[abort] {record.action} {record.path}: {record.reason}"
                    )
                typer.echo(f"aborted {resolved_run_id}: {abort_reason}")
                return
            if admission is not None:
                if not core.repository.exists():
                    raise typer.BadParameter(
                        f"no resolver run {resolved_run_id!r} to admit into"
                    )
                report_admission(await core.admit(admission), adapter, resolved_run_id)
                return
            try:
                if core.repository.exists():
                    manifest = await core.resume()
                else:
                    intake = resolver_intake(scan_tracked(find_feedback))
                    for carried in intake.carried:
                        typer.echo(carried)
                    comments = intake.actionable
                    if not comments:
                        typer.echo("No unresolved # lup: comments.")
                        return
                    note_paths = sorted({Path(comment.file) for comment in comments})
                    source = resolver_source_snapshot(
                        launcher,
                        root,
                        core.repository.root,
                        note_paths,
                    )
                    manifest = await core.run(
                        ResolveRequest(
                            source=source,
                            notes=[
                                InventoryNote(
                                    file=Path(comment.file),
                                    line=comment.start_line,
                                    text=comment.marker_text(),
                                    context=comment.context,
                                )
                                for comment in comments
                            ],
                        )
                    )
            except ResolverAwaitingAnswers as parked:
                planned = (
                    core.repository.load().concerns if core.repository.exists() else []
                )
                report_awaiting(parked, adapter, resolved_run_id, planned)
                return
            typer.echo(f"Review branch: {manifest.review_branch}")
            typer.echo(manifest.model_dump_json(indent=2))

        async with spawned_supervisor(
            supervisor or SupervisorSpawn(), resolved_run_id, adapter
        ):
            await drive()

    asyncio.run(execute())
