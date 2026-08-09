"""Native launch flows: runtime preflight, then the Claude and Codex launchers.

Each launcher regenerates its target's artifacts, verifies every claimed
native requirement against a live probe, and hands the terminal to the
native CLI with the non-interactive environment applied.
"""

import os
import shutil
from pathlib import Path

import sh
import typer
from pydantic import BaseModel, ConfigDict

from lup.adapters.claude.profile_store import ClaudeProfileStore
from lup.adapters.codex.harness_runtime import (
    CodexPluginInstaller,
    PluginCacheConfig,
)
from lup.harness.environment import non_interactive_environment
from lup.types import EnvVars
from lup.workspace.paths import project_root
from lup_template.devtools.harness.catalog import portable_harness
from lup_template.devtools.harness.codex_home import select_codex_home
from lup_template.devtools.harness.composition import (
    NativeHarnessComposition,
    claude_composition,
    codex_composition,
)
from lup_template.devtools.harness.drift import generate_with_report
from lup.devtools.layout import get_tree_dir


class RelocationHint(BaseModel):
    """How the harness a command is running under follows a new worktree."""

    model_config = ConfigDict(frozen=True)

    agent: str
    shell: str


def relocation_hint(worktree_path: Path) -> RelocationHint:
    """Name the follow-through in the vocabulary of the running harness.

    Each launcher exports its own configuration home, so a session that
    reached here through one of them is told the move it actually supports.
    Anything else gets the portable shell form alone rather than the name of
    a tool that runtime may not have.
    """
    environ = os.environ  # lup: ignore[os-environ]
    move = f"cd /; cd {worktree_path}"
    if "CLAUDE_CONFIG_DIR" in environ:
        return RelocationHint(
            agent="EnterWorktree(path=<the path above>)",
            shell=f"{move}; claude",
        )
    if "CODEX_HOME" in environ:
        return RelocationHint(
            agent="start a session there — this runtime cannot relocate a running one",
            shell=f"{move}; codex",
        )
    return RelocationHint(agent="", shell=move)


def runtime_preflight(composition: NativeHarnessComposition) -> None:
    """Verify each claimed native requirement immediately before launch."""
    target = composition.recipe.label
    evidence = composition.readiness()
    for item in evidence:
        state = "ready" if item.supported else "missing"
        typer.echo(f"{target} {item.capability}: {state} ({item.version})")
    if any(not item.supported for item in evidence):
        raise typer.BadParameter(f"{target} runtime preflight failed")


def apply_sandbox_environment(
    environment: EnvVars, label: str, required_tools: list[str]
) -> None:
    """Export LUP_SANDBOX_ACTIVE when the declared sandbox can actually run.

    The dispatchers defer unjudged shell only under this flag, so it is set
    exactly when the launch verified the OS boundary; without it the deny
    lattice keeps carrying the escalation recipe.
    """
    hooks = portable_harness().plugins[0].hooks
    if hooks is None or hooks.sandbox is None:
        return
    missing = [tool for tool in required_tools if shutil.which(tool) is None]
    if missing:
        typer.echo(
            f"{label} sandbox: missing {', '.join(missing)} — deny lattice stays active"
        )
        return
    environment["LUP_SANDBOX_ACTIVE"] = "1"
    typer.echo(f"{label} sandbox: active — unjudged shell defers to the OS boundary")


CODEX_SANDBOX_OVERRIDES = (
    "-s",
    "--sandbox",
    "--full-auto",
    "--yolo",
    "--dangerously-bypass-approvals-and-sandbox",
)


def codex_sandbox_arguments(environment: EnvVars, extra_args: list[str]) -> list[str]:
    """Compose the interactive Codex envelope that LUP_SANDBOX_ACTIVE vouches for.

    The launcher establishes the boundary it announces: an explicit
    workspace-write sandbox on the Codex command line, mirroring how the
    Claude settings artifact compiles the same declaration into an OS wall.
    Path-level write and credential denials have no Codex equivalent, so the
    envelope is the declaration's strict subset (network stays off). When the
    caller supplies its own sandbox flag the launcher vouches for nothing:
    the flag stays unset and the deny lattice keeps the escalation recipe.
    """
    hooks = portable_harness().plugins[0].hooks
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
    and cannot be edited from the session that created it. Claude resolves
    its workspace to the repository and never had the split.
    """
    try:
        tree = get_tree_dir()
    except (typer.Exit, SystemExit):
        return []
    return ["-c", f'sandbox_workspace_write.writable_roots=["{tree}"]']


def launch_claude(
    extra_args: list[str],
    profile: str | None,
    model: str | None,
    generate_only: bool,
) -> None:
    """Generate/reconcile Claude artifacts and launch the verified local plugin."""
    composition = claude_composition(project_root())
    generate_with_report(composition)
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
            *extra_args,
        ]
    )
    environment = non_interactive_environment(os.environ)  # lup: ignore[os-environ]
    apply_sandbox_environment(environment, "claude", ["bwrap", "socat"])
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


def launch_codex(
    extra_args: list[str],
    codex_home: Path | None,
    profile: str | None,
    model: str | None,
    generate_only: bool,
    force_install: bool,
) -> None:
    """Generate/reconcile Codex artifacts and launch without updating the CLI."""
    composition = codex_composition(project_root())
    generate_with_report(composition)
    if generate_only:
        return
    runtime_preflight(composition)
    environment = non_interactive_environment(os.environ)  # lup: ignore[os-environ]
    envelope = codex_sandbox_arguments(environment, extra_args)
    home = select_codex_home(codex_home, environment, project_root(), profile)
    selected_home = home.path
    if home.isolated:
        typer.echo(f"Using worktree-scoped Codex home: {selected_home}")
    plugin = portable_harness().plugins[0]
    cache = CodexPluginInstaller(
        PluginCacheConfig(codex_home=selected_home, marketplace=plugin.marketplace)
    ).ensure(
        project_root() / ".codex" / "plugins" / plugin.name,
        project_root(),
        force=force_install,
    )
    typer.echo(f"Verified installed Codex plugin: {cache.installed_root}")
    arguments: list[str] = list(envelope)
    if profile is not None:
        arguments.extend(["--profile", profile])
    if model is not None:
        arguments.extend(["--model", model])
    arguments.extend(extra_args)
    environment["CODEX_HOME"] = str(selected_home)
    try:
        sh.Command("codex")(*arguments, _fg=True, _env=environment)
    except sh.CommandNotFound as error:
        raise typer.BadParameter("Codex CLI is not installed") from error
    except sh.ErrorReturnCode as error:
        raise typer.Exit(error.exit_code) from error
