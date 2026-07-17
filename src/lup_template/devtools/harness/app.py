"""Public ``lup-devtools harness`` generation, diagnosis, and launch surface."""
# lup: Wait, where is the generic hooks folder that specify what can be modified or not, and gets compiled to .claude/plugin/hooks/auto_allow_edit.py for instance?

import asyncio
import hashlib
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Annotated

import sh
import typer
from pydantic import BaseModel, ConfigDict

from lup.adapters.claude.harness import ClaudeSkillInvocationRenderer
from lup.adapters.claude.harness_runtime import (
    ClaudeCliEvidence,
    claude_capability_probes,
)
from lup.adapters.claude.profile_store import ClaudeProfileStore
from lup.adapters.codex.harness import CodexSkillInvocationRenderer
from lup.adapters.codex.harness_runtime import (
    CodexCliEvidence,
    CodexPluginInstaller,
    PluginCacheConfig,
    codex_capability_probes,
)
from lup.codescan.markers import find_feedback
from lup.harness.contracts import ProcessLauncher, SkillInvocationRenderer
from lup.harness.environment import non_interactive_environment
from lup.harness.models import CapabilityEvidence, LaunchRequest, ReconciliationMetadata
from lup.harness.process import LocalProcessLauncher
from lup.harness.proposals import ReconciliationProposalWriter
from lup.harness.reconciliation import source_patch_base_digest
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
from lup_template.devtools.harness.generate import (
    DriftReport,
    GenerationRecipe,
    HarnessGenerationConflict,
    claude_generation_recipe,
    codex_generation_recipe,
    generate as generate_target,
    inspect_generation,
)
from lup_template.devtools.harness.evidence import (
    EvidenceDrift,
    evidence_drift,
    sdk_evidence_drift,
)

type NativeCapabilityEvidence = (
    CapabilityEvidence[ClaudeCliEvidence] | CapabilityEvidence[CodexCliEvidence]
)
type RuntimeReadiness = Callable[[], Sequence[NativeCapabilityEvidence]]


class NativeHarnessComposition(BaseModel):
    """Concrete capabilities supplied to one CLI composition root."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    recipe: GenerationRecipe
    readiness: RuntimeReadiness
    invocation_renderer: SkillInvocationRenderer


def claude_composition(root: Path) -> NativeHarnessComposition:
    """Construct the Claude capabilities directly."""

    def readiness() -> Sequence[NativeCapabilityEvidence]:
        return [
            probe.probe()
            for probe in claude_capability_probes(root / ".claude" / "plugins" / "lup")
        ]

    return NativeHarnessComposition(
        recipe=claude_generation_recipe(root),
        readiness=readiness,
        invocation_renderer=ClaudeSkillInvocationRenderer(),
    )


def codex_composition(root: Path) -> NativeHarnessComposition:
    """Construct the Codex capabilities directly."""

    def readiness() -> Sequence[NativeCapabilityEvidence]:
        return [probe.probe() for probe in codex_capability_probes()]

    return NativeHarnessComposition(
        recipe=codex_generation_recipe(root),
        readiness=readiness,
        invocation_renderer=CodexSkillInvocationRenderer(),
    )


app = typer.Typer(no_args_is_help=True, help="Generate and launch a native harness")


def report_generation(target: str, changed: list[Path], removed: list[Path]) -> None:
    typer.echo(
        f"{target} harness ready: {len(changed)} changed, {len(removed)} removed"
    )


def generated(composition: NativeHarnessComposition) -> None:
    recipe = composition.recipe
    report = inspect_generation(recipe)
    report_drift(report, paths=True)
    try:
        materialized = generate_target(recipe)
    except HarnessGenerationConflict as error:
        typer.echo(str(error), err=True)
        typer.echo(
            "Existing unowned files were preserved. Reconcile them explicitly before "
            "adopting generated ownership.",
            err=True,
        )
        raise typer.Exit(1) from error
    report_generation(recipe.label, materialized.changed, materialized.removed)


def harness_compositions(value: str) -> list[NativeHarnessComposition]:
    """Parse a generic CLI selector into already concrete compositions."""
    constructors: dict[str, Callable[[Path], NativeHarnessComposition]] = {
        "claude": claude_composition,
        "codex": codex_composition,
    }
    root = project_root()
    if value == "all":
        return [constructor(root) for constructor in constructors.values()]
    constructor = constructors.get(value)  # lup: ignore[dict-get]
    if constructor is not None:
        return [constructor(root)]
    raise typer.BadParameter("target must be claude, codex, or all")


def report_drift(report: DriftReport, *, paths: bool = False) -> None:
    proposal = report.proposal
    typer.echo(
        f"{report.target}: {len(proposal.writes)} writes, "
        f"{len(proposal.deletes)} deletes, {len(proposal.conflicts)} conflicts, "
        f"ownership={'present' if report.ownership_present else 'missing'}"
    )
    for conflict in proposal.conflicts:
        label = "sensitive local conflict" if conflict.sensitive else conflict.category
        typer.echo(f"  {conflict.path}: {label}")
    if paths:
        for write in proposal.writes:
            typer.echo(f"  + {write.artifact.path}")
        for delete in proposal.deletes:
            typer.echo(f"  - {delete.path}")


def runtime_preflight(composition: NativeHarnessComposition) -> None:
    """Verify each claimed native requirement immediately before launch."""
    target = composition.recipe.label
    evidence = composition.readiness()
    for item in evidence:
        state = "ready" if item.supported else "missing"
        typer.echo(f"{target} {item.capability}: {state} ({item.version})")
    if any(not item.supported for item in evidence):
        raise typer.BadParameter(f"{target} runtime preflight failed")


@app.command("generate")
def generate_command(
    target: Annotated[str, typer.Argument(help="claude, codex, or all")] = "all",
) -> None:
    """Deterministically generate owned native artifacts without launching."""
    for composition in harness_compositions(target):
        generated(composition)


@app.command("check")
def check_command(
    target: Annotated[str, typer.Argument(help="claude, codex, or all")] = "all",
) -> None:
    """Read-only ownership and generated-artifact drift check for CI."""
    reports = [
        inspect_generation(composition.recipe)
        for composition in harness_compositions(target)
    ]
    for report in reports:
        report_drift(report)
    if any(not report.clean for report in reports):
        raise typer.Exit(1)


@app.command("reconcile")
def reconcile_command(
    target: Annotated[str, typer.Argument(help="claude, codex, or all")] = "all",
) -> None:
    """Classify local differences without rewriting canonical Python source."""
    compositions = harness_compositions(target)
    reports = [inspect_generation(composition.recipe) for composition in compositions]
    unresolved = False
    for report in reports:
        report_drift(report)
        unresolved = unresolved or bool(report.proposal.conflicts)
    if unresolved:
        typer.echo(
            "Unrecognized changes were preserved as conflicts; no arbitrary prompt "
            "or script content was reverse-engineered.",
            err=True,
        )
        raise typer.Exit(1)


@app.command("apply-reconciliation")
def apply_reconciliation(
    proposal_id: Annotated[str, typer.Argument(help="Persisted proposal id")],
) -> None:
    """Apply a stale-base-checked source patch, then regenerate both targets."""
    directory = project_root() / ".lup" / "reconcile" / proposal_id
    metadata = directory / "metadata.json"
    patch = directory / "source.patch"
    if not metadata.is_file() or not patch.is_file():
        raise typer.BadParameter(f"unknown reconciliation proposal {proposal_id!r}")
    try:
        record = ReconciliationMetadata.model_validate_json(
            metadata.read_text(encoding="utf-8")
        )
    except ValueError as error:
        raise typer.BadParameter("reconciliation metadata is malformed") from error
    if record.proposal_id != proposal_id:
        raise typer.BadParameter("reconciliation proposal identity does not match")
    actual = hashlib.sha256(patch.read_bytes()).hexdigest()
    if record.source_patch_sha256 != actual:
        raise typer.BadParameter("reconciliation patch digest is stale or malformed")
    content = patch.read_text(encoding="utf-8")
    try:
        base_digest = source_patch_base_digest(project_root(), content)
    except (OSError, ValueError) as error:
        raise typer.BadParameter("reconciliation source patch is malformed") from error
    if record.base_digest != base_digest:
        raise typer.BadParameter("reconciliation source base is stale")
    typer.echo(content)
    if not typer.confirm("Apply this canonical source patch and regenerate?"):
        raise typer.Abort()
    try:
        sh.Command("git")("apply", "--check", str(patch), _cwd=project_root())
        sh.Command("git")("apply", str(patch), _cwd=project_root())
    except sh.ErrorReturnCode as error:
        raise typer.BadParameter("reconciliation patch no longer applies") from error
    for composition in harness_compositions("all"):
        generated(composition)
    metadata.unlink()
    patch.unlink()
    directory.rmdir()


@app.command("propose-reconciliation")
def propose_reconciliation(
    patch: Annotated[
        Path,
        typer.Argument(help="Git-format patch against canonical Python source"),
    ],
) -> None:
    """Persist a source patch for separate review and stale-base-checked apply."""
    if not patch.is_file():
        raise typer.BadParameter(f"source patch does not exist: {patch}")
    try:
        record = ReconciliationProposalWriter().write(
            project_root(), patch.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise typer.BadParameter("reconciliation source patch is invalid") from error
    typer.echo(
        f"Reconciliation proposal {record.proposal_id} persisted; review it, then run "
        f"`uv run lup-devtools harness apply-reconciliation {record.proposal_id}`"
    )


@app.command("doctor")
def doctor_command(
    target: Annotated[str, typer.Argument(help="claude, codex, or all")] = "all",
    strict_evidence: Annotated[
        bool,
        typer.Option(
            "--strict-evidence",
            help="Exit nonzero when an installed component is newer than the "
            "evidence ledger (the nightly lane's re-probe trigger)",
        ),
    ] = False,
) -> None:
    """Report installed native runtime evidence without updating either CLI."""
    failed = False
    drifts: list[EvidenceDrift] = []  # lup: ignore[empty-collection]
    for composition in harness_compositions(target):
        evidence = composition.readiness()
        for item in evidence:
            typer.echo(item.model_dump_json(indent=2))
            if item.supported:
                drift = evidence_drift(item.capability, item.version)
                if drift is not None:
                    drifts.append(drift)
        if composition.recipe.label == "claude":
            sdk_drift = sdk_evidence_drift()
            if sdk_drift is not None:
                drifts.append(sdk_drift)
        failed = failed or any(not item.supported for item in evidence)
    for drift in drifts:
        typer.echo(drift.message, err=True)
    if failed or (strict_evidence and drifts):
        raise typer.Exit(1)


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


@app.command("resolve")
def resolve_command(
    adapter: Annotated[str, typer.Option("--adapter", help="claude or codex")],
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Stable run id; defaults to the source commit"),
    ] = None,
    human_decision: Annotated[
        bool | None,
        typer.Option(
            "--accept/--reject",
            help="Record human acceptance or rejection of the review branch",
        ),
    ] = None,
) -> None:
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
                            text=comment.text,
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


@app.command(
    "claude",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def claude(
    ctx: typer.Context,
    profile: Annotated[
        str | None,
        typer.Option("--profile", "-p", help="Claude config-directory profile"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Native model override"),
    ] = None,
    generate_only: Annotated[
        bool,
        typer.Option("--generate-only", help="Generate without launching"),
    ] = False,
) -> None:
    """Generate/reconcile Claude artifacts and launch the verified local plugin."""
    composition = claude_composition(project_root())
    generated(composition)
    if generate_only:
        return
    runtime_preflight(composition)
    arguments: list[str] = []
    if model is not None:
        arguments.extend(["--model", model])
    arguments.extend(
        [
            "--plugin-dir",
            str(project_root() / ".claude" / "plugins" / "lup"),
            *ctx.args,
        ]
    )
    environment = non_interactive_environment(os.environ)  # lup: ignore[os-environ]
    if profile is not None:
        environment["CLAUDE_CONFIG_DIR"] = str(
            ClaudeProfileStore().resolve_config_dir(profile)
        )
    try:
        sh.Command("claude")(*arguments, _fg=True, _env=environment)
    except sh.CommandNotFound as error:
        raise typer.BadParameter("Claude Code CLI is not installed") from error
    except sh.ErrorReturnCode as error:
        raise typer.Exit(error.exit_code) from error


@app.command(
    "codex",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def codex(
    ctx: typer.Context,
    codex_home: Annotated[
        Path | None,
        typer.Option("--codex-home", help="Codex account/config home"),
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option("--profile", "-p", help="Codex named config overlay"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Native model override"),
    ] = None,
    generate_only: Annotated[
        bool,
        typer.Option("--generate-only", help="Generate without launching"),
    ] = False,
    force_install: Annotated[
        bool,
        typer.Option(
            "--force-install", help="Reinstall even when the cached digest matches"
        ),
    ] = False,
) -> None:
    """Generate/reconcile Codex artifacts and launch without updating the CLI."""
    composition = codex_composition(project_root())
    generated(composition)
    if generate_only:
        return
    runtime_preflight(composition)
    environment = non_interactive_environment(os.environ)  # lup: ignore[os-environ]
    configured_home = environment["CODEX_HOME"] if "CODEX_HOME" in environment else None
    selected_home = codex_home or (
        Path(configured_home) if configured_home is not None else Path.home() / ".codex"
    )
    cache = CodexPluginInstaller(PluginCacheConfig(codex_home=selected_home)).ensure(
        project_root() / ".codex" / "plugins" / "lup",
        project_root(),
        force=force_install,
    )
    typer.echo(f"Verified installed Codex plugin: {cache.installed_root}")
    arguments: list[str] = []
    if profile is not None:
        arguments.extend(["--profile", profile])
    if model is not None:
        arguments.extend(["--model", model])
    arguments.extend(ctx.args)
    environment["CODEX_HOME"] = str(selected_home)
    try:
        sh.Command("codex")(*arguments, _fg=True, _env=environment)
    except sh.CommandNotFound as error:
        raise typer.BadParameter("Codex CLI is not installed") from error
    except sh.ErrorReturnCode as error:
        raise typer.Exit(error.exit_code) from error


# lup: This is way too bulky, and doesn't respect the convention of this repo, where we split subconcerns in subfolder
