"""The ``claude`` command group: Claude Code runner (default) + ``usage``.

``lup-devtools claude`` launches Claude Code wired for this project (tools +
local plugin + active profile). Extra args forward straight to ``claude``
(e.g. ``claude --resume``); ``claude run`` is the explicit escape hatch for
args that collide with a subcommand name, and ``claude usage`` shows usage.
"""

from typing import Annotated

import typer
from typer import _click
from typer.core import TyperGroup

import lup_template.devtools.claude.run as run
from lup_template.devtools.usage.app import app as usage_app


class ClaudeRunnerGroup(TyperGroup):
    """Forward any non-subcommand invocation through ``run`` to ``claude``.

    A Typer group resolves the first token as a subcommand, so ``claude
    --resume`` or ``claude mcp`` would otherwise error before reaching the
    runner. Routing unknown tokens to ``run`` lets ``claude <args>`` pass
    straight through to ``claude`` while keeping real subcommands (``usage``)
    and the explicit ``claude run`` escape hatch for collisions.
    """

    # typer vendors click as ``typer._click``; match TyperGroup.resolve_command,
    # whose triple return shape is click's to define.
    def resolve_command(
        self, ctx: _click.Context, args: list[str]
    ) -> tuple[  # lup: ignore[tuple-shape] — click's triple
        str | None, _click.Command | None, list[str]
    ]:
        if args and args[0] not in self.commands:
            args = ["run", *args]
        return super().resolve_command(ctx, args)


app = typer.Typer(
    cls=ClaudeRunnerGroup,
    help="Run Claude Code wired for this project (tools, local plugin, profile)",
    invoke_without_command=True,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
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

    Extra args pass through to ``claude`` (e.g. ``claude run --resume``); the
    ``--`` is only needed for args that collide with this command's own options.
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
