"""Tool collection and the MCP stdio tool server (``serve-tools``)."""

import asyncio
import atexit
import signal

import typer

from lup_template.agent.tools.example import EXAMPLE_TOOLS
from lup.mcp import LupMcpTool
from lup.paths import SessionContext


def collect_tools_by_server(
    context: SessionContext | None = None,
) -> dict[str, list[LupMcpTool]]:
    """Collect LupMcpTool instances grouped by server name.

    Without context, only statically-available tools are returned —
    tools that require runtime state (reflect, realtime) are listed via
    :func:`collect_dynamic_tool_names`. With a session context (relayed
    by the Codex/OpenAI adapters via env vars), the session-bound
    reflect and submit_output tools are constructed and served too.
    """
    if context is None:
        return {"example": list(EXAMPLE_TOOLS)}

    from lup.reflect import ReflectionGate

    from lup_template.agent.toolsets import build_session_toolset

    sandbox = None
    if context.session_id:
        from lup.sandbox import Sandbox

        sandbox = Sandbox(
            session_id=context.session_id,
            shared_dir=context.session_dir / "sandbox_shared",
        )
        atexit.register(sandbox.stop)

    toolset = build_session_toolset(
        session_dir=context.session_dir,
        outputs_dir=context.outputs_dir,
        gate=ReflectionGate(flag_path=context.gate_flag),
        include_subagent_tool=True,
        sandbox=sandbox,
        realtime_dir=context.realtime_dir,
    )
    # claude: this seems to duplicate the creation of the server in core. This should be unified instead. serve should just reuse the same server from core
    return toolset["groups"]


def collect_dynamic_tool_names() -> dict[str, list[str]]:
    """Discover tool names from modules that require runtime instantiation."""
    import ast
    from pathlib import Path

    tools_dir = Path(__file__).parent.parent.parent / "agent" / "tools"
    dynamic: dict[str, list[str]] = {}

    for module_path in sorted(tools_dir.glob("*.py")):
        if module_path.name in ("__init__.py", "example.py"):
            continue

        try:
            tree = ast.parse(module_path.read_text())
        except SyntaxError:
            continue

        tool_names: list[str] = []
        for node in ast.walk(
            tree
        ):  # claude: Eh, is that necessary? This seems to be a bit wtf here, using glob + ast walking
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(
                    decorator.func, ast.Name
                ):
                    if decorator.func.id == "lup_tool":
                        tool_names.append(node.name)
        if tool_names:
            dynamic[module_path.stem] = tool_names

    return dynamic


def collect_all_tools(context: SessionContext | None = None) -> list[LupMcpTool]:
    """Collect all LupMcpTool instances from known tool modules."""
    tools: list[LupMcpTool] = []
    for server_tools in collect_tools_by_server(context).values():
        tools.extend(server_tools)
    return tools


def serve_tools(list_only: bool, server_group: str | None) -> None:
    """Serve the collected tools over MCP stdio (see the ``serve-tools`` command)."""
    from lup.metrics import configure_metrics, metrics_path
    from lup.paths import read_session_context

    context = read_session_context()
    if context is not None:
        configure_metrics(metrics_path(context.session_dir))

    by_server = collect_tools_by_server(context)
    match server_group:
        case None:
            # Default tool set excludes the example placeholder, which ships
            # fabricated data and is served to no live agent — matching the
            # Claude path. Serve it explicitly with --server example to test it.
            lup_tools = [
                t for key, tools in by_server.items() if key != "example" for t in tools
            ]
        case (
            "sandbox" | "session" | "example"
        ):  # claude: What? This is extremely hard-coded. Do you think match ... with should be a Claude ask in the edit hook?
            # claude: Like, the whole point of serve is that it serve the server without having to redo everything. This here seems to deduplicate a lot
            # claude: Also type str is wrong, should have been litteral. Maybe that's a deny hook or an instruction in Claude.md that could have brought this point or something. What do you think?
            lup_tools = list(by_server.get(server_group, []))
        case "notes":
            lup_tools = [
                t
                for key, tools in by_server.items()
                if key not in ("sandbox", "session", "example")
                for t in tools
            ]
        case _:
            typer.echo(f"Unknown server group: {server_group}", err=True)
            raise typer.Exit(1)
    tool_map = {t.name: t for t in lup_tools}

    if list_only:
        for t in lup_tools:
            typer.echo(t.name)
        return

    def terminate(_signum: int, _frame: object) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)

    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import CallToolResult, ContentBlock, ImageContent, TextContent, Tool

    server = Server(server_group or "notes", version="1.0.0")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        tool_list = []
        for t in lup_tools:
            tool_list.append(
                Tool(name=t.name, description=t.description, inputSchema=t.input_schema)
            )
        return tool_list

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, object]
    ) -> CallToolResult:  # claude: ignore  # MCP protocol boundary: arbitrary tool args
        if name not in tool_map:
            raise ValueError(f"Tool '{name}' not found")
        result = await tool_map[name].handler(arguments)
        content_dicts: list[dict[str, str]] = result.get("content", [])
        content: list[ContentBlock] = []
        for d in content_dicts:
            match d.get("type"):
                case "image":
                    content.append(
                        ImageContent(
                            type="image", data=d["data"], mimeType=d["mimeType"]
                        )
                    )
                case _:
                    content.append(TextContent(type="text", text=d.get("text", "")))
        return CallToolResult(
            content=content,
            isError=result.get("is_error", False),
        )

    async def run() -> None:
        init_options = server.create_initialization_options()
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, init_options)

    asyncio.run(run())
