"""Agent introspection and interactive debugging tools.

Commands:
- inspect: Pretty-print the full agent configuration (tools, schemas, prompt, subagents)
- serve-tools: Start SDK tools as an MCP stdio server (used by ``chat``)
- chat: Launch an interactive ``claude`` session with the agent's tools and prompt
- repl: Interactive REPL with the agent via the SDK (continuous session)

Examples::

    $ uv run lup-devtools agent inspect
    $ uv run lup-devtools agent inspect --json
    $ uv run lup-devtools agent inspect --full
    $ uv run lup-devtools agent chat
    $ uv run lup-devtools agent chat --model opus --no-tools
    $ uv run lup-devtools agent repl
    $ uv run lup-devtools agent repl --model sonnet --no-prompt
    $ uv run lup-devtools agent serve-tools
"""

import asyncio
import atexit
import hashlib
import inspect as inspect_mod
import io
import json
import logging
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, TypedDict

if TYPE_CHECKING:
    from rich.console import Console

    from lup.adapters.common import Conversation
    from lup.types import LupResponse

import sh
import typer

from lup_template.agent.config import settings
from lup_template.agent.models import AgentOutput
from lup_template.agent.prompts import get_system_prompt
from lup_template.agent.subagents import get_subagent_specs
from lup_template.agent.tools.example import EXAMPLE_TOOLS
from lup.mcp import LupMcpTool
from lup.paths import SessionContext

logger = logging.getLogger(__name__)

MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def save_images(
    images: list[tuple[str, bytes]],
    images_dir: Path,
) -> list[Path]:
    """Save raw image data to disk, deduplicating by content hash."""
    images_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for media_type, data in images:
        ext = MIME_TO_EXT.get(media_type, ".bin")
        name = hashlib.sha256(data).hexdigest()[:12] + ext
        path = images_dir / name
        if not path.exists():
            path.write_bytes(data)
        paths.append(path)
    return paths


app = typer.Typer(no_args_is_help=True)

CLIPBOARD_IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp")


def read_clipboard_image() -> tuple[str, bytes] | None:
    """Read image data from the system clipboard via xclip.

    Returns ``(media_type, raw_bytes)`` or ``None`` when no image is available.
    """
    try:
        xclip = sh.Command("xclip")
        targets = str(xclip("-selection", "clipboard", "-o", "-t", "TARGETS"))
    except sh.ErrorReturnCode, sh.CommandNotFound:
        return None

    for mime in CLIPBOARD_IMAGE_MIMES:
        if mime not in targets:
            continue
        try:
            buf = io.BytesIO()
            xclip("-selection", "clipboard", "-o", "-t", mime, _out=buf)
            data = buf.getvalue()
            if data:
                return (mime, data)
        except sh.ErrorReturnCode:
            continue
    return None


def read_clipboard_text() -> str | None:
    """Read text from the system clipboard via xclip."""
    try:
        xclip = sh.Command("xclip")
        text = str(xclip("-selection", "clipboard", "-o"))
        return text if text else None
    except sh.ErrorReturnCode, sh.CommandNotFound:
        return None


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


def print_model_source(
    out: io.StringIO, model: type, label: str, indent: str = "    "
) -> None:
    """Print the Python source of a BaseModel class."""
    out.write(f"\n{indent}{label}:\n")
    try:
        source = inspect_mod.getsource(model)
        for line in source.splitlines():
            out.write(f"{indent}  {line}\n")
    except OSError, TypeError:
        out.write(f"{indent}  {model.__name__} (source unavailable)\n")


def tool_location(tool: LupMcpTool) -> str:
    """Get file:line for the tool handler (unwraps decorators)."""
    handler = inspect_mod.unwrap(tool.handler)
    try:
        filepath = inspect_mod.getfile(handler)
        filename = os.path.basename(filepath)
        _, lineno = inspect_mod.getsourcelines(handler)
        return f"{filename}:{lineno}"
    except OSError, TypeError:
        return "?"


def tool_signature(tool: LupMcpTool) -> str:
    """One-liner: input fields → output model name, file:line."""
    parts: list[str] = []
    for name, f in tool.input_model.model_fields.items():
        ann = f.annotation
        type_name = getattr(ann, "__name__", None) if ann is not None else None
        parts.append(f"{name}: {type_name}" if type_name else name)
    fields = ", ".join(parts)
    output_part = f" → {tool.output_model.__name__}" if tool.output_model else ""
    return f"({fields}){output_part}  [{tool_location(tool)}]"


def print_tool_compact(out: io.StringIO, tool: LupMcpTool) -> None:
    """Print a single tool as a one-liner."""
    out.write(f"    {tool.name}{tool_signature(tool)}\n")


def print_tool_full(out: io.StringIO, tool: LupMcpTool) -> None:
    """Print a single tool with full description and schemas."""
    out.write(f"\n  {tool.name}\n")
    out.write(f"  {'─' * len(tool.name)}\n")

    desc_lines = tool.description.split(". ")
    for line in desc_lines:
        line = line.strip()
        if line:
            out.write(f"    {line}.\n")

    print_model_source(out, tool.input_model, "Input")

    if tool.output_model is not None:
        print_model_source(out, tool.output_model, "Output")


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
    return toolset["groups"]


def collect_dynamic_tool_names() -> dict[str, list[str]]:
    """Discover tool names from modules that require runtime instantiation."""
    import ast
    from pathlib import Path

    tools_dir = Path(__file__).parent.parent / "agent" / "tools"
    dynamic: dict[str, list[str]] = {}

    for module_path in sorted(tools_dir.glob("*.py")):
        if module_path.name in ("__init__.py", "example.py"):
            continue

        try:
            tree = ast.parse(module_path.read_text())
        except SyntaxError:
            continue

        tool_names: list[str] = []
        for node in ast.walk(tree):
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


class ToolDict(TypedDict):
    name: str
    description: str
    input_schema: dict[
        str, object
    ]  # claude: ignore  # JSON Schema is arbitrary nesting
    output_schema: (
        dict[str, object] | None
    )  # claude: ignore  # JSON Schema is arbitrary nesting


def tool_to_dict(t: LupMcpTool) -> ToolDict:
    """Serialize a LupMcpTool for JSON output."""
    return {
        "name": t.name,
        "description": t.description,
        "input_schema": t.input_model.model_json_schema(),
        "output_schema": t.output_model.model_json_schema() if t.output_model else None,
    }


def page_output(text: str) -> None:
    """Write text through a pager (less) if stdout is a tty, otherwise print."""
    if not sys.stdout.isatty():
        sys.stdout.write(text)
        return
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    try:
        tmp.write(text)
        tmp.close()
        less = sh.Command("less")
        less("-R", "-F", "-X", tmp.name, _fg=True)
    except sh.CommandNotFound, sh.ErrorReturnCode:
        sys.stdout.write(text)
    finally:
        os.unlink(tmp.name)


@app.command("inspect")
def inspect_cmd(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
    full: Annotated[
        bool,
        typer.Option("--full", help="Show full details (tool schemas, full prompt)"),
    ] = False,
) -> None:
    """Inspect the full agent configuration: tools, schemas, prompt, subagents."""
    tools_by_server = collect_tools_by_server()
    dynamic_tools = collect_dynamic_tool_names()
    all_tools = collect_all_tools()
    subagents = {s.name: s for s in get_subagent_specs()}
    prompt = get_system_prompt()

    if as_json:
        data: dict[
            str, object
        ] = {  # claude: ignore  # heterogeneous JSON inspect payload
            "model": settings.model,
            "max_thinking_tokens": settings.max_thinking_tokens,
            "tools": [tool_to_dict(t) for t in all_tools],
            "dynamic_tools": dynamic_tools,
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

    # --- Pretty-print mode (write to buffer, then page) ---
    out = io.StringIO()

    out.write("=" * 60 + "\n")
    out.write("  Agent Configuration\n")
    out.write("=" * 60 + "\n")

    # Model
    out.write(f"\nModel: {settings.model}\n")
    out.write(f"Max thinking tokens: {settings.max_thinking_tokens}\n")

    # Tools grouped by server
    total_static = sum(len(ts) for ts in tools_by_server.values())
    total_dynamic = sum(len(ts) for ts in dynamic_tools.values())
    out.write(f"\n{'─' * 60}\n")
    out.write(f"  MCP Tools ({total_static + total_dynamic})\n")
    out.write(f"{'─' * 60}\n")
    for server_name, server_tools in tools_by_server.items():
        out.write(f"\n  {server_name} ({len(server_tools)} tools)\n")
        for t in server_tools:
            if full:
                print_tool_full(out, t)
            else:
                print_tool_compact(out, t)
    if dynamic_tools:
        for module_name, tool_names in dynamic_tools.items():
            out.write(
                f"\n  {module_name} ({len(tool_names)} tools, created at runtime)\n"
            )
            for name in tool_names:
                out.write(f"    {name}\n")

    # Agent output schema
    out.write(f"\n{'─' * 60}\n")
    out.write("  Agent Output Schema\n")
    out.write(f"{'─' * 60}\n")
    if full:
        print_model_source(out, AgentOutput, "AgentOutput", indent="  ")
    else:
        for name, f in AgentOutput.model_fields.items():
            ann = f.annotation
            type_name = getattr(ann, "__name__", None) if ann is not None else None
            out.write(f"    {name}: {type_name or '?'}\n")

    # Subagents
    out.write(f"\n{'─' * 60}\n")
    out.write(f"  Subagents ({len(subagents)})\n")
    out.write(f"{'─' * 60}\n")
    for name, agent in subagents.items():
        out.write(f"\n  {name} (model: {agent.model})\n")
        if full:
            out.write(f"    {agent.description}\n")
        if agent.tools:
            out.write(f"    Tools: {', '.join(agent.tools)}\n")

    # System prompt
    out.write(f"\n{'─' * 60}\n")
    out.write("  System Prompt\n")
    out.write(f"{'─' * 60}\n")
    if full or len(prompt) <= 500:
        out.write(prompt + "\n")
    else:
        out.write(
            f"{prompt[:500]}... ({len(prompt)} chars total, use --full to see all)\n"
        )

    out.write("\n")

    page_output(out.getvalue())


# ---------------------------------------------------------------------------
# serve-tools
# ---------------------------------------------------------------------------


@app.command("serve-tools")
def serve_tools_cmd(
    list_only: Annotated[
        bool,
        typer.Option("--list", help="Print served tool names and exit"),
    ] = False,
    server_group: Annotated[
        str | None,
        typer.Option(
            "--server",
            help="Serve only this group (notes, sandbox, session, example); default: all but example",
        ),
    ] = None,
) -> None:
    """Start SDK tools as an MCP stdio server (the ``notes`` server).

    Launched as a subprocess by the Codex/OpenAI adapters and by the
    ``chat`` command. When session-context env vars are present (see
    ``lup.paths.SessionContext``), session-bound tools — reflect and
    submit_output — are served alongside the static tools, and tool
    metrics are flushed to the session directory for the parent to read.
    """
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
        case "sandbox" | "session" | "example":
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
    from mcp.types import CallToolResult, TextContent, Tool

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
        return CallToolResult(
            content=[
                TextContent(type="text", text=d.get("text", "")) for d in content_dicts
            ],
            isError=result.get("is_error", False),
        )

    async def run() -> None:
        init_options = server.create_initialization_options()
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, init_options)

    asyncio.run(run())


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
                "notes": {
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
        typer.echo(
            "Error: 'claude' CLI not found. Install Claude Code first.", err=True
        )
        raise typer.Exit(1)
    except sh.ErrorReturnCode:
        pass  # claude exited normally or user quit
    finally:
        if mcp_config_path:
            try:
                os.unlink(mcp_config_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# repl
# ---------------------------------------------------------------------------


class Interrupted(Exception):
    """Raised when the user interrupts response collection via Ctrl-C."""


async def send_interruptible(
    conv: "Conversation",
    prompt: str,
    console: "Console",
) -> LupResponse:
    """Send a prompt with Ctrl-C interrupt support.

    First Ctrl-C sends an interrupt signal (graceful stop).
    Second Ctrl-C cancels the task (force stop).
    """
    loop = asyncio.get_running_loop()
    interrupt_count = 0

    send_task = asyncio.create_task(conv.send(prompt))

    def on_sigint() -> None:
        nonlocal interrupt_count
        interrupt_count += 1
        if interrupt_count == 1:
            console.print("\n  [dim]interrupting...[/dim]")
            asyncio.ensure_future(conv.interrupt())
        else:
            send_task.cancel()

    loop.add_signal_handler(signal.SIGINT, on_sigint)
    try:
        return await send_task
    except asyncio.CancelledError:
        raise Interrupted from None
    finally:
        loop.remove_signal_handler(signal.SIGINT)


def apply_repl_overrides(
    adapter: object,
    *,
    no_tools: bool,
    no_prompt: bool,
) -> None:
    """Apply ``--no-tools``/``--no-prompt`` to a built adapter.

    Claude: realized on the options object. Codex/OpenAI: realized on
    the adapter attributes, which ``conversation()`` reads at open time
    (``mcp_tools`` gates the served-tools config, ``system_prompt``
    becomes the developer instructions). Unknown adapter types warn so
    the flags are never silently ignored.
    """
    if not no_tools and not no_prompt:
        return

    from lup.adapters.claude import ClaudeAdapter
    from lup.adapters.codex import CodexAdapter

    match adapter:
        case ClaudeAdapter():
            options = adapter.options
            if no_tools:
                options.mcp_servers = {}
                options.allowed_tools = []
            if no_prompt:
                options.system_prompt = None
        case CodexAdapter():
            if no_tools:
                adapter.mcp_tools = False
            if no_prompt:
                adapter.system_prompt = ""
        case _:
            typer.echo(
                "Warning: --no-tools/--no-prompt not supported on "
                f"{type(adapter).__name__}",
                err=True,
            )


async def repl(
    *,
    model: str | None = None,
    no_tools: bool = False,
    no_prompt: bool = False,
) -> None:
    """Run the interactive REPL loop."""
    from contextlib import AsyncExitStack

    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style as PTStyle
    from rich.console import Console
    from rich.panel import Panel

    from lup_template.agent.core import build_adapter
    from lup.paths import project_root

    console = Console(highlight=False)
    effective_model = model or settings.model
    stack = AsyncExitStack()

    # Welcome panel with server → tool listing
    panel_lines = [
        "[bold]✻ Agent REPL[/bold]",
        f"[dim]model:[/dim] {effective_model}",
    ]
    if not no_tools:
        servers = collect_tools_by_server()
        dynamic = collect_dynamic_tool_names()
        group_names: list[tuple[str, list[str]]] = [
            (name, [t.name for t in stools]) for name, stools in servers.items()
        ] + list(dynamic.items())
        for i, (name, tool_names_list) in enumerate(group_names):
            is_last_server = i == len(group_names) - 1
            panel_lines.append(f"[dim]{'└' if is_last_server else '├'} {name}[/dim]")
            for j, tname in enumerate(tool_names_list):
                is_last_tool = j == len(tool_names_list) - 1
                branch = "  └" if is_last_tool else "  ├"
                if not is_last_server:
                    branch = f"[dim]│[/dim] {'└' if is_last_tool else '├'}"
                panel_lines.append(f"[dim]{branch}[/dim] {tname}")
    else:
        panel_lines.append("[dim]no tools[/dim]")
    panel_lines += [
        "",
        "[dim]/quit · Ctrl-C stop · Ctrl-V paste image · Alt+Enter newline[/dim]",
    ]

    console.print()
    console.print(Panel("\n".join(panel_lines), border_style="blue", width=60))
    console.print()

    # -- prompt_toolkit session --
    session_cost = 0.0
    pending_images: list[tuple[str, bytes]] = []

    def rprompt() -> FormattedText:
        parts = [effective_model]
        if pending_images:
            n = len(pending_images)
            parts.append(f"{n} img{'s' if n > 1 else ''}")
        if session_cost:
            parts.append(f"${session_cost:.4f}")
        return FormattedText([("class:rprompt", " · ".join(parts))])

    history_dir = project_root() / ".lup"
    history_dir.mkdir(parents=True, exist_ok=True)

    # Key bindings: Enter submits, Alt+Enter inserts newline
    kb = KeyBindings()

    @kb.add("escape", "enter")  # Alt+Enter or Esc then Enter
    def newline_binding(event: object) -> None:
        from prompt_toolkit.key_binding import KeyPressEvent

        assert isinstance(event, KeyPressEvent)
        event.current_buffer.newline()

    @kb.add("enter")
    def submit_binding(event: object) -> None:
        from prompt_toolkit.key_binding import KeyPressEvent

        assert isinstance(event, KeyPressEvent)
        event.current_buffer.validate_and_handle()

    @kb.add("c-v")
    def paste_binding(event: object) -> None:
        from prompt_toolkit.key_binding import KeyPressEvent

        assert isinstance(event, KeyPressEvent)
        result = read_clipboard_image()
        if result is not None:
            pending_images.append(result)
            n = len(pending_images)
            console.print(
                f"[dim]{n} image{'s' if n > 1 else ''} attached (/drop to clear)[/dim]"
            )
        else:
            text = read_clipboard_text()
            if text:
                event.current_buffer.insert_text(text)

    pt_session: PromptSession[str] = PromptSession(
        message=FormattedText([("class:prompt", "❯ ")]),
        rprompt=rprompt,
        style=PTStyle.from_dict(
            {
                "prompt": "fg:ansiblue bold",
                "prompt-continuation": "fg:ansiblue",
                "rprompt": "fg:#666666",
            }
        ),
        history=FileHistory(str(history_dir / "repl_history")),
        completer=WordCompleter(
            ["/quit", "/exit", "/q", "/help", "/drop"],
            sentence=True,
        ),
        key_bindings=kb,
        multiline=True,
        prompt_continuation=FormattedText([("class:prompt-continuation", "··· ")]),
    )

    try:
        # ``build_adapter`` reads ``settings.model`` for every backend, so
        # override it here to make ``--model`` actually take effect (not just
        # decorate the panel). ``--no-tools``/``--no-prompt`` are applied to the
        # built Claude options below.
        original_model = settings.model
        if model:
            settings.model = model
        try:
            adapter, adapter_ctx, _notes = build_adapter("repl")
        finally:
            settings.model = original_model
        apply_repl_overrides(adapter, no_tools=no_tools, no_prompt=no_prompt)
        stack.enter_context(adapter_ctx)

        async with stack:
            async with adapter.conversation() as conv:
                last_input_sigint = 0.0

                while True:
                    try:
                        user_input = await pt_session.prompt_async()
                    except EOFError, asyncio.CancelledError:
                        console.print()
                        break
                    except KeyboardInterrupt:
                        now = time.monotonic()
                        if now - last_input_sigint < 2.0:
                            console.print()
                            break
                        last_input_sigint = now
                        console.print("[dim]Press Ctrl-C again to exit[/dim]")
                        continue

                    last_input_sigint = 0.0
                    stripped = user_input.strip()
                    if not stripped:
                        continue
                    if stripped in ("/quit", "/exit", "/q"):
                        break
                    if stripped == "/drop":
                        pending_images.clear()
                        console.print("[dim]images cleared[/dim]")
                        continue

                    console.print("[dim]thinking...[/dim]")
                    if pending_images:
                        images_dir = project_root() / ".lup" / "images"
                        saved = save_images(pending_images, images_dir)
                        path_list = ", ".join(str(p) for p in saved)
                        query_text = (stripped + "\n\n" if stripped else "") + (
                            f"[image attached: {path_list}]"
                        )
                        prompt_text = query_text
                        pending_images.clear()
                    else:
                        prompt_text = user_input
                    try:
                        response = await send_interruptible(
                            conv,
                            prompt_text,
                            console,
                        )
                        parts: list[str] = []
                        if response.result and response.result.duration_ms:
                            secs = response.result.duration_ms / 1000
                            parts.append(f"{secs:.1f}s")
                        if response.result and response.result.total_cost_usd:
                            session_cost += response.result.total_cost_usd
                            parts.append(f"${response.result.total_cost_usd:.4f}")
                        elif response.result and response.result.usage:
                            # Backends without cost reporting (Codex sans
                            # rates) still show what they can: token counts
                            usage = response.result.usage
                            parts.append(
                                f"{usage.input_tokens}in/{usage.output_tokens}out tok"
                            )
                        if parts:
                            console.print(f"  [dim]{' · '.join(parts)}[/dim]")
                        console.print()
                    except Interrupted:
                        console.print("  [dim]interrupted[/dim]\n")
                    except RuntimeError as e:
                        console.print(f"  [red]error:[/red] {e}\n")
    except KeyboardInterrupt:
        # Additional Ctrl+C during cleanup — containers will be cleaned
        # on next start via stale container removal
        pass


@app.command("repl")
def repl_cmd(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Override the model"),
    ] = None,
    no_tools: Annotated[
        bool,
        typer.Option("--no-tools", help="Skip MCP tools"),
    ] = False,
    no_prompt: Annotated[
        bool,
        typer.Option("--no-prompt", help="Skip agent system prompt"),
    ] = False,
) -> None:
    """Interactive REPL — continuous session with the agent via the SDK."""
    try:
        asyncio.run(repl(model=model, no_tools=no_tools, no_prompt=no_prompt))
    except KeyboardInterrupt:
        pass
