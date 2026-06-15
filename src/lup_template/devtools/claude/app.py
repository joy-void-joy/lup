"""The ``claude`` command group: Claude Code runner (default) + ``usage``.

``lup-devtools claude`` launches Claude Code wired for this project (tools +
local plugin + active profile). Use ``claude run`` for options and to pass
extra arguments through to ``claude``; ``claude usage`` shows usage.
"""

from typing import Annotated

import typer

import lup_template.devtools.claude.run as run
from lup_template.devtools.usage.app import app as usage_app

app = typer.Typer(
    help="Run Claude Code wired for this project (tools, local plugin, profile)",
    invoke_without_command=True,
)
app.add_typer(usage_app, name="usage", help="Claude Code usage display")


@app.command(
    "run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run_cmd(
    ctx: typer.Context,
    profile: Annotated[
        str | None,
        typer.Option("--profile", "-p", help="Claude profile (CLAUDE_CONFIG_DIR)"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model override (e.g. sonnet, opus)"),
    ] = None,
    no_tools: Annotated[
        bool,
        typer.Option("--no-tools", help="Skip attaching the project MCP tools"),
    ] = False,
    no_plugin: Annotated[
        bool,
        typer.Option("--no-plugin", help="Skip loading the local lup plugin"),
    ] = False,
    with_prompt: Annotated[
        bool,
        typer.Option("--prompt/--no-prompt", help="Append the agent system prompt"),
    ] = False,
) -> None:
    """Launch Claude Code with the project's tools, local plugin, and profile.

    Extra args pass through to ``claude`` (e.g. ``claude run -- --resume``).
    """
    run.run_claude(profile, model, no_tools, no_plugin, with_prompt, ctx.args)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Launch Claude Code with project defaults when no subcommand is given."""
    if ctx.invoked_subcommand is not None:
        return
    run.run_claude(
        profile=None,
        model=None,
        no_tools=False,
        no_plugin=False,
        with_prompt=False,
        extra_args=[],
    )
