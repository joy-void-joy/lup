"""Agent introspection and interactive debugging tools.

Commands:
- inspect: Pretty-print the full agent configuration (tools, schemas, prompt, subagents)
- serve-tools: Start SDK tools as an MCP stdio server (used by ``chat``)
- chat: Launch an interactive ``claude`` session with the agent's tools and prompt
"""

import asyncio
import inspect as inspect_mod
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
from typing import Annotated

import sh
import typer

from lup.agent.config import settings
from lup.agent.models import AgentOutput
from lup.agent.prompts import get_system_prompt
from lup.agent.subagents import get_subagents
from lup.agent.tools.example import EXAMPLE_TOOLS
from lup.lib.mcp import LupMcpTool

logger = logging.getLogger(__name__)

app = typer.Typer(no_args_is_help=True)


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


def _print_model_source(model: type, label: str, indent: str = "    ") -> None:
    """Print the Python source of a BaseModel class."""
    typer.echo(f"\n{indent}{label}:")
    try:
        source = inspect.getsource(model)
        for line in source.splitlines():
            typer.echo(f"{indent}  {line}")
    except (OSError, TypeError):
        typer.echo(f"{indent}  {model.__name__} (source unavailable)")


def _print_tool(tool: LupMcpTool) -> None:
    """Print a single tool's information."""
    sdk = tool["sdk_tool"]
    typer.echo(f"\n  {sdk.name}")
    typer.echo(f"  {'─' * len(sdk.name)}")

    desc_lines = sdk.description.split(". ")
    for line in desc_lines:
        line = line.strip()
        if line:
            typer.echo(f"    {line}.")

    _print_model_source(tool["input_model"], "Input")

    output_model = tool.get("output_model")
    if output_model is not None:
        _print_model_source(output_model, "Output")


def _collect_all_tools() -> list[LupMcpTool]:
    """Collect all LupMcpTool instances from known tool modules."""
    return list(EXAMPLE_TOOLS)


def _tool_to_dict(t: LupMcpTool) -> dict[str, object]:
    """Serialize a LupMcpTool for JSON output."""
    output_model = t.get("output_model")
    return {
        "name": t["sdk_tool"].name,
        "description": t["sdk_tool"].description,
        "input_schema": t["input_model"].model_json_schema(),
        "output_schema": output_model.model_json_schema() if output_model else None,
    }


@app.command("inspect")
def inspect_cmd(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
    full: Annotated[
        bool,
        typer.Option("--full", help="Show full system prompt (not truncated)"),
    ] = False,
) -> None:
    """Inspect the full agent configuration: tools, schemas, prompt, subagents."""
    tools = _collect_all_tools()
    subagents = get_subagents()
    prompt = get_system_prompt()

    if as_json:
        data: dict[str, object] = {
            "model": settings.model,
            "max_thinking_tokens": settings.max_thinking_tokens,
            "tools": [_tool_to_dict(t) for t in tools],
            "output_schema": AgentOutput.model_json_schema(),
            "subagents": {
                name: {
                    "description": agent.description,
                    "model": agent.model,
                    "tools": agent.tools,
                }
                for name, agent in subagents.items()
            },
            "system_prompt": prompt,
        }
        typer.echo(json.dumps(data, indent=2))
        return

    # --- Pretty-print mode ---

    typer.echo("=" * 60)
    typer.echo("  Agent Configuration")
    typer.echo("=" * 60)

    # Model
    typer.echo(f"\nModel: {settings.model}")
    typer.echo(f"Max thinking tokens: {settings.max_thinking_tokens}")

    # Tools
    typer.echo(f"\n{'─' * 60}")
    typer.echo(f"  MCP Tools ({len(tools)})")
    typer.echo(f"{'─' * 60}")
    for t in tools:
        _print_tool(t)

    # Agent output schema
    typer.echo(f"\n{'─' * 60}")
    typer.echo("  Agent Output Schema")
    typer.echo(f"{'─' * 60}")
    _print_model_source(AgentOutput, "AgentOutput", indent="  ")

    # Subagents
    typer.echo(f"\n{'─' * 60}")
    typer.echo(f"  Subagents ({len(subagents)})")
    typer.echo(f"{'─' * 60}")
    for name, agent in subagents.items():
        typer.echo(f"\n  {name} (model: {agent.model})")
        typer.echo(f"    {agent.description}")
        if agent.tools:
            typer.echo(f"    Tools: {', '.join(agent.tools)}")

    # System prompt
    typer.echo(f"\n{'─' * 60}")
    typer.echo("  System Prompt")
    typer.echo(f"{'─' * 60}")
    if full or len(prompt) <= 500:
        typer.echo(prompt)
    else:
        typer.echo(f"{prompt[:500]}... ({len(prompt)} chars total, use --full to see all)")

    typer.echo("")


# ---------------------------------------------------------------------------
# serve-tools
# ---------------------------------------------------------------------------


def _run_stdio_server() -> None:
    """Run the MCP stdio server with all SDK tools."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool

    from lup.lib.mcp import _generate_json_schema, extract_sdk_tools

    sdk_tools = extract_sdk_tools(_collect_all_tools())
    tool_map = {t.name: t for t in sdk_tools}

    server = Server("lup-tools", version="1.0.0")

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_tools() -> list[Tool]:
        tool_list = []
        for t in sdk_tools:
            schema = _generate_json_schema(t.input_schema)
            tool_list.append(
                Tool(name=t.name, description=t.description, inputSchema=schema)
            )
        return tool_list

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(
        name: str, arguments: dict[str, object]
    ) -> list[dict[str, str]]:
        if name not in tool_map:
            raise ValueError(f"Tool '{name}' not found")
        result = await tool_map[name].handler(arguments)
        return result.get("content", [])  # type: ignore[return-value]

    async def run() -> None:
        init_options = server.create_initialization_options()
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, init_options)

    asyncio.run(run())


@app.command("serve-tools")
def serve_tools_cmd() -> None:
    """Start SDK tools as an MCP stdio server.

    This is used by the ``chat`` command — claude CLI launches it as a subprocess.
    Can also be used standalone for testing MCP tool integration.
    """
    _run_stdio_server()


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------


@app.command("chat")
def chat_cmd(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Override the model (e.g. sonnet, opus)"),
    ] = None,
    no_tools: Annotated[
        bool,
        typer.Option("--no-tools", help="Skip MCP tool server"),
    ] = False,
    no_prompt: Annotated[
        bool,
        typer.Option("--no-prompt", help="Skip appending the agent system prompt"),
    ] = False,
) -> None:
    """Launch an interactive claude session with the agent's tools and prompt.

    Starts the SDK MCP tools as a stdio server, generates the system prompt,
    and execs into ``claude`` with the right flags.
    """
    claude_args: list[str] = []

    # Model
    effective_model = model or settings.model
    claude_args.extend(["--model", effective_model])

    # System prompt
    if not no_prompt:
        prompt = get_system_prompt()
        claude_args.extend(["--append-system-prompt", prompt])

    # MCP config with serve-tools as stdio server
    mcp_config_path: str | None = None
    if not no_tools:
        mcp_config = {
            "mcpServers": {
                "lup-tools": {
                    "command": "uv",
                    "args": ["run", "lup-devtools", "agent", "serve-tools"],
                }
            }
        }
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="lup-mcp-", delete=False
        )
        json.dump(mcp_config, tmp)
        tmp.close()
        mcp_config_path = tmp.name
        claude_args.extend(["--mcp-config", mcp_config_path])

    typer.echo(f"Launching claude with model={effective_model}")
    if not no_tools:
        typer.echo(f"MCP config: {mcp_config_path}")
    if not no_prompt:
        typer.echo("System prompt: appended")

    # exec into claude so the user gets a full interactive session
    try:
        claude = sh.Command("claude")
        claude(*claude_args, _fg=True)
    except sh.CommandNotFound:
        typer.echo("Error: 'claude' CLI not found. Install Claude Code first.", err=True)
        raise typer.Exit(1)
    except sh.ErrorReturnCode:
        pass  # claude exited normally or user quit
    finally:
        if mcp_config_path:
            try:
                os.unlink(mcp_config_path)
            except OSError:
                pass
