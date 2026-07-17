"""Public ``lup-devtools harness`` generation, diagnosis, and launch surface."""
# lup: Wait, where is the generic hooks folder that specify what can be modified or not, and gets compiled to .claude/plugin/hooks/auto_allow_edit.py for instance?

import os
from pathlib import Path
from typing import Annotated

import sh
import typer

from lup.adapters.claude.profile_store import ClaudeProfileStore
from lup.adapters.codex.harness_runtime import (
    CodexPluginInstaller,
    PluginCacheConfig,
)
from lup.harness.environment import non_interactive_environment
from lup.workspace.paths import project_root
from lup_template.devtools.harness.composition import (
    NativeHarnessComposition,
    claude_composition,
    codex_composition,
)
import lup_template.devtools.harness.doctor as doctor
import lup_template.devtools.harness.drift as drift
import lup_template.devtools.harness.reconcile as reconcile
import lup_template.devtools.harness.resolve as resolve

app = typer.Typer(no_args_is_help=True, help="Generate and launch a native harness")


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
    drift.generate_targets(target)


@app.command("check")
def check_command(
    target: Annotated[str, typer.Argument(help="claude, codex, or all")] = "all",
) -> None:
    """Read-only ownership and generated-artifact drift check for CI."""
    drift.check_targets(target)


@app.command("reconcile")
def reconcile_command(
    target: Annotated[str, typer.Argument(help="claude, codex, or all")] = "all",
) -> None:
    """Classify local differences without rewriting canonical Python source."""
    reconcile.classify_targets(target)


@app.command("apply-reconciliation")
def apply_reconciliation(
    proposal_id: Annotated[str, typer.Argument(help="Persisted proposal id")],
) -> None:
    """Apply a stale-base-checked source patch, then regenerate both targets."""
    reconcile.apply_proposal(proposal_id)


@app.command("propose-reconciliation")
def propose_reconciliation(
    patch: Annotated[
        Path,
        typer.Argument(help="Git-format patch against canonical Python source"),
    ],
) -> None:
    """Persist a source patch for separate review and stale-base-checked apply."""
    reconcile.propose_patch(patch)


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
    doctor.run_doctor(target, strict_evidence)


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
    resolve.run_resolve(adapter, run_id, human_decision)


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
    drift.generate_with_report(composition)
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
    drift.generate_with_report(composition)
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


