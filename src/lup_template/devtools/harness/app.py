"""Typer command tree for ``lup-devtools harness``: wiring only, no bodies.

Each command delegates to the module owning its concern: ``drift`` for
generation and checking, ``reconcile`` for local-difference workflows,
``doctor`` for runtime evidence, ``resolve`` for the persisted resolver,
and ``launch`` for the native launchers.
The generated plugins' permission policy is declared as data in
:mod:`lup_template.devtools.harness.catalog` (``HookSet``: protected edit
roots, fetch scopes, policy ids), decided by :mod:`lup.policy.kernel`, and
materialized under ``.claude/plugins/lup/hooks/`` and
``.codex/plugins/lup/hooks/`` (dispatcher script plus copied kernel and
rendered data rows).
"""

from pathlib import Path
from typing import Annotated

import typer

import lup_template.devtools.harness.doctor as doctor
import lup_template.devtools.harness.drift as drift
import lup_template.devtools.harness.launch as launch
import lup_template.devtools.harness.reconcile as reconcile
import lup_template.devtools.harness.resolve as resolve

app = typer.Typer(no_args_is_help=True, help="Generate and launch a native harness")


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
    answer: Annotated[
        list[str] | None,
        typer.Option(
            "--answer",
            help="Answer a parked material question as <question-id>=<value> "
            "(repeatable)",
        ),
    ] = None,
) -> None:
    """Drive the shared persisted resolver through one explicit native adapter."""
    resolve.run_resolve(adapter, run_id, human_decision, answer or [])


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
    launch.launch_claude(ctx.args, profile, model, generate_only)


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
    launch.launch_codex(
        ctx.args, codex_home, profile, model, generate_only, force_install
    )
