"""Resolver command glue between the CLI and the shared persisted resolver.

Owns the console question broker, resolver-scoped Git snapshotting of
review-note files, the per-adapter worker and reviewer session factories,
and the driver that starts or resumes a persisted resolver run and records
human acceptance of its review branch.
"""

import asyncio
import os
from pathlib import Path

import typer
from pydantic import BaseModel

from lup.codescan.markers import find_feedback
from lup.harness.environment import non_interactive_environment
from lup.harness.process import LaunchRequest, LocalProcessLauncher, ProcessLauncher
from lup.resolver.contracts import (
    QuestionBroker,
    ResolverAwaitingAnswers,
    ResolverObserver,
    WorktreePreparer,
)
from lup.resolver.core import ResolverCore
from lup.resolver.models import (
    AnswerBatch,
    ConcernProgress,
    InventoryNote,
    QuestionAnswer,
    QuestionBatch,
    ResolvePhase,
    ResolveRequest,
    ResolverConfig,
    SourceSnapshot,
    VerificationCommand,
)
from lup.runtime.contracts import SessionFactory
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


class ConsoleQuestionBroker(QuestionBroker):
    """Deliver persisted resolver questions through the native terminal."""

    async def ask(self, questions: QuestionBatch) -> AnswerBatch:
        answers: list[QuestionAnswer] = []  # lup: ignore[empty-collection]
        for question in questions.questions:
            default = question.recommendation or (
                question.choices[0] if question.choices else None
            )
            while True:
                value = (
                    await asyncio.to_thread(
                        typer.prompt, question.prompt, default=default
                    )
                    if default is not None
                    else await asyncio.to_thread(typer.prompt, question.prompt)
                )
                if not question.choices or value in question.choices:
                    break
                typer.echo("Choose one of: " + ", ".join(question.choices))
            answers.append(QuestionAnswer(question_id=question.id, value=value))
        return AnswerBatch(run_id=questions.run_id, answers=answers)


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


class HeadlessQuestionBroker(QuestionBroker):
    """Answer persisted resolver questions from pre-supplied flag values.

    Every question must be answered explicitly — recommendations are never
    assumed on behalf of the human. A batch with missing, invalid, or
    unknown answers parks the run for a flag-carrying rerun.
    """

    def __init__(
        self,
        provided: dict[str, str],  # lup: ignore[dict-str-payload] — open id map
    ) -> None:
        self.provided = provided

    async def ask(self, questions: QuestionBatch) -> AnswerBatch:
        known = [question.id for question in questions.questions]
        missing = [
            question
            for question in questions.questions
            if question.id not in self.provided
        ]
        invalid = [
            question
            for question in questions.questions
            if question.id in self.provided
            and question.choices
            and self.provided[question.id] not in question.choices
        ]
        problems = [
            *(
                f"--answer {question.id}={self.provided[question.id]} is not one of: "
                + ", ".join(question.choices)
                for question in invalid
            ),
            *(
                f"--answer {identifier}=... names no pending question"
                for identifier in self.provided
                if identifier not in known
            ),
        ]
        if missing or problems:
            raise ResolverAwaitingAnswers([*missing, *invalid], problems)
        return AnswerBatch(
            run_id=questions.run_id,
            answers=[
                QuestionAnswer(
                    question_id=question.id, value=self.provided[question.id]
                )
                for question in questions.questions
            ],
        )


def report_awaiting(parked: ResolverAwaitingAnswers, adapter: str, run_id: str) -> None:
    """Print parked questions and the exact flag-carrying rerun recipe."""
    typer.echo("Resolver run parked awaiting material answers.")
    for problem in parked.problems:
        typer.echo(f"  problem: {problem}")
    for question in parked.pending:
        typer.echo(f"question {question.id} (concern {question.concern_id}):")
        typer.echo(f"  {question.prompt}")
        if question.choices:
            typer.echo("  choices: " + " | ".join(question.choices))
        if question.recommendation is not None:
            typer.echo(f"  recommendation: {question.recommendation}")
    recipe = " ".join(
        [
            "uv run lup-devtools harness resolve",
            f"--adapter {adapter}",
            f"--run-id {run_id}",
            *(f"--answer {question.id}=<value>" for question in parked.pending),
        ]
    )
    typer.echo("Relay the questions to the human, then rerun:")
    typer.echo(f"  {recipe}")


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


def run_resolve(
    adapter: str,
    run_id: str | None,
    human_decision: bool | None,
    answers: list[str],
    interactive: bool = False,
) -> None:
    """Drive the shared persisted resolver through one explicit native adapter."""
    provided = parse_answer_flags(answers)
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

    async def execute() -> None:
        from lup.adapters.claude.runtime import (
            ClaudeSessionConfig,
            create_claude_session_factory,
        )
        from lup.adapters.codex.runtime import (
            CodexSessionConfig,
            create_codex_session_factory,
        )
        from lup_template.agent.config import engine_for_model, settings
        from lup.hooks import (
            create_git_inspection_hook,
            create_permission_hooks,
            merge_hooks,
        )

        session_environment = non_interactive_environment(
            os.environ  # lup: ignore[os-environ] — sessions inherit the console
        )
        session_model = (
            settings.model if engine_for_model(settings.model) == adapter else None
        )
        if session_model is None:
            typer.echo(
                f"Configured model {settings.model!r} does not route to adapter "
                f"{adapter!r}; sessions use the adapter's native default model."
            )

        def worker_factory(cwd: Path) -> SessionFactory:
            if adapter == "claude":
                return create_claude_session_factory(
                    ClaudeSessionConfig(
                        model=session_model,
                        system_prompt="Execute the persisted Lup resolver assignment.",
                        cwd=cwd,
                        add_dirs=[cwd],
                        environment=session_environment,
                        hooks=merge_hooks(
                            create_permission_hooks([cwd], []),
                            create_git_inspection_hook(),
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
                    environment=session_environment,
                    writable_roots=[cwd],
                )
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
                        environment=session_environment,
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
                    environment=session_environment,
                )
            )

        from lup_template.devtools.harness.catalog import portable_harness

        broker: QuestionBroker = (
            HeadlessQuestionBroker(provided)
            if provided or not interactive
            else ConsoleQuestionBroker()
        )
        core = ResolverCore(
            ResolverConfig(
                state_root=root / ".lup" / "resolve",
                workspace=root,
                worktree_root=(root.parent / f"{root.name}-resolve-{resolved_run_id}"),
                run_id=resolved_run_id,
                integration_branch=f"resolve/{resolved_run_id}/review",
                verification_commands=[
                    VerificationCommand(
                        name="ruff", arguments=["uv", "run", "ruff", "check", "."]
                    ),
                    VerificationCommand(
                        name="pyright", arguments=["uv", "run", "pyright"]
                    ),
                    VerificationCommand(
                        name="pytest", arguments=["uv", "run", "pytest", "-q"]
                    ),
                ],
            ),
            portable_harness().resolver,
            worker_factory,
            reviewer_factory,
            composition.invocation_renderer,
            broker,
            launcher,
            observer=ConsoleResolverObserver(),
            worktree_preparer=FeatureWorktreePreparer(root),
        )
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
            report_awaiting(parked, adapter, resolved_run_id)
            return
        if manifest.accepted is None and manifest.final_review is not None:
            typer.echo(f"Review branch: {manifest.review_branch}")
            typer.echo(manifest.final_review.model_dump_json(indent=2))
            if human_decision is None and not interactive:
                typer.echo(
                    "Run awaiting acceptance: relay the review to the human, "
                    "then rerun with --accept or --reject."
                )
                return
            accepted = (
                human_decision
                if human_decision is not None
                else await asyncio.to_thread(
                    typer.confirm,
                    "Accept this review branch for manual integration?",
                    default=manifest.final_review.accepted,
                )
            )
            manifest = core.record_human_acceptance(accepted)
        elif human_decision is not None:
            raise typer.BadParameter("the resolver run is not awaiting acceptance")
        typer.echo(manifest.model_dump_json(indent=2))

    asyncio.run(execute())
