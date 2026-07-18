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

from lup.codescan.markers import find_feedback
from lup.harness.environment import non_interactive_environment
from lup.harness.process import LaunchRequest, LocalProcessLauncher, ProcessLauncher
from lup.resolver.contracts import QuestionBroker
from lup.resolver.core import ResolverCore
from lup.resolver.models import (
    AnswerBatch,
    InventoryNote,
    QuestionAnswer,
    QuestionBatch,
    ResolveRequest,
    ResolverConfig,
    SourceSnapshot,
    VerificationCommand,
)
from lup.runtime.contracts import SessionFactory
from lup.types import EnvVars
from lup.workspace.paths import project_root
from lup_template.devtools.dev.comments import scan_tracked
from lup_template.devtools.dev.remote_auth import check_remote_auth
from lup_template.devtools.harness.composition import harness_compositions


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


def run_resolve(adapter: str, run_id: str | None, human_decision: bool | None) -> None:
    """Drive the shared persisted resolver through one explicit native adapter."""
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
        from lup_template.agent.config import settings
        from lup.hooks import (
            create_git_inspection_hook,
            create_permission_hooks,
            merge_hooks,
        )

        session_environment = non_interactive_environment(
            os.environ  # lup: ignore[os-environ] — sessions inherit the console
        )

        def worker_factory(cwd: Path) -> SessionFactory:
            if adapter == "claude":
                return create_claude_session_factory(
                    ClaudeSessionConfig(
                        model=settings.model,
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
                    model=settings.model,
                    developer_instructions=(
                        "Execute the persisted Lup resolver assignment."
                    ),
                    cwd=cwd,
                    sandbox="workspaceWrite",
                    approval_policy="never",
                    environment=session_environment,
                    writable_roots=[cwd],
                )
            )

        def reviewer_factory(cwd: Path) -> SessionFactory:
            if adapter == "claude":
                return create_claude_session_factory(
                    ClaudeSessionConfig(
                        model=settings.model,
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
                    model=settings.model,
                    developer_instructions=(
                        "Independently review the persisted resolver change."
                    ),
                    cwd=cwd,
                    sandbox="readOnly",
                    approval_policy="never",
                    environment=session_environment,
                )
            )

        from lup_template.devtools.harness.catalog import portable_harness

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
            ConsoleQuestionBroker(),
            launcher,
        )
        if core.repository.exists():
            manifest = await core.resume()
        else:
            comments = scan_tracked(find_feedback)
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
        if manifest.accepted is None and manifest.final_review is not None:
            typer.echo(f"Review branch: {manifest.review_branch}")
            typer.echo(manifest.final_review.model_dump_json(indent=2))
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
