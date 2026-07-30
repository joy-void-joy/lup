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
from lup_template.devtools.supervisor.app import serve_supervisor
from lup_template.devtools.supervisor.doors import (
    answer_questions,
    list_questions,
    park_run,
)

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


@app.command("serve-resolver-tools")
def serve_resolver_tools_command() -> None:
    """Serve one worker's question tools over stdio, for out-of-process runtimes."""
    resolve.run_resolver_tool_server()


resolve_app = typer.Typer(
    help="Drive the persisted resolver, and browse or answer its runs",
    invoke_without_command=True,
    no_args_is_help=False,
)
resolve_app.command("supervise")(serve_supervisor)
resolve_app.command("questions")(list_questions)
resolve_app.command("answer")(answer_questions)
resolve_app.command("park")(park_run)
app.add_typer(resolve_app, name="resolve")


@resolve_app.callback(invoke_without_command=True)
def resolve_command(
    context: typer.Context,
    adapter: Annotated[
        str | None, typer.Option("--adapter", help="claude or codex")
    ] = None,
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
    abort: Annotated[
        str | None,
        typer.Option(
            "--abort",
            help="End this run with the given reason, freeing every concern "
            "worktree and branch. Retains the review branch and the run's "
            "recorded evidence. Requires the run's process to have exited.",
        ),
    ] = None,
    admit: Annotated[
        list[str] | None,
        typer.Option(
            "--admit",
            help="Admit work discovered mid-run into this run, described in "
            "the human's own words (repeatable). Only the new evidence is "
            "planned; recorded answers and completed work are kept.",
        ),
    ] = None,
    admit_note: Annotated[
        list[str] | None,
        typer.Option(
            "--admit-note",
            help="Admit a `# lup:` note already written in the tree, as "
            "<file>:<line> (repeatable). Its text is read from the file, so "
            "the admitted concern stays traceable to code.",
        ),
    ] = None,
    wait: Annotated[
        float,
        typer.Option(
            "--wait",
            help="Seconds to wait for a human to answer a material question "
            "before parking the run. Zero parks immediately, so an unattended "
            "invocation is deterministic.",
        ),
    ] = 0.0,
    supervise: Annotated[
        bool,
        typer.Option(
            "--supervise",
            help="Open the supervisor page beside this run. Sugar for a long "
            "--wait plus `lup-devtools harness resolve supervise`, which you "
            "can also run yourself against any run at any time.",
        ),
    ] = False,
    supervise_port: Annotated[
        int, typer.Option("--supervise-port", help="Port for the supervisor page")
    ] = 8766,
    supervise_linger: Annotated[
        bool,
        typer.Option(
            "--supervise-linger",
            help="Leave the supervisor page running after the run exits",
        ),
    ] = False,
) -> None:
    """Drive the shared persisted resolver through one explicit native adapter."""
    if context.invoked_subcommand is not None:
        return
    if adapter is None:
        raise typer.BadParameter("--adapter is required to drive a resolver run")
    resolve.run_resolve(
        adapter,
        run_id,
        human_decision,
        answer or [],
        abort,
        max(wait, resolve.SUPERVISED_WAIT_SECONDS) if supervise else wait,
        resolve.SupervisorSpawn(
            enabled=supervise, port=supervise_port, linger=supervise_linger
        ),
        resolve.admission_request(admit or [], admit_note or []),
    )


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
        typer.Option("--codex-home", help="Override the worktree-scoped Codex home"),
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
