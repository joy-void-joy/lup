"""Agent configuration inspection: tools, schemas, prompt, subagents.

Named ``inspect_agent`` rather than ``inspect`` so the module never
shadows the stdlib ``inspect`` (imported here as ``inspect_mod``).
"""

import inspect as inspect_mod
import io
import json
import os
import sys
import tempfile
from typing import TypedDict

import sh
import typer

from lup_template.agent.config import settings
from lup_template.agent.models import AgentOutput
from lup_template.agent.prompts import get_system_prompt
from lup_template.agent.subagents import get_subagent_specs
from lup_template.devtools.agent.serve import (
    collect_all_tools,
    collect_dynamic_tool_names,
    collect_tools_by_server,
)
from lup.mcp import LupMcpTool


def print_model_source(
    out: io.StringIO, model: type, label: str, indent: str = "    "
) -> None:
    """Print the Python source of a BaseModel class."""
    out.write(f"\n{indent}{label}:\n")
    try:
        source = inspect_mod.getsource(model)
        for line in source.splitlines():
            out.write(f"{indent}  {line}\n")
    except (OSError, TypeError):
        out.write(f"{indent}  {model.__name__} (source unavailable)\n")


def tool_location(tool: LupMcpTool) -> str:
    """Get file:line for the tool handler (unwraps decorators)."""
    handler = inspect_mod.unwrap(tool.handler)
    try:
        filepath = inspect_mod.getfile(handler)
        filename = os.path.basename(filepath)
        _, lineno = inspect_mod.getsourcelines(handler)
        return f"{filename}:{lineno}"
    except (OSError, TypeError):
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


class ToolDict(TypedDict):
    name: str
    description: str
    input_schema: dict[str, object]  # lup: ignore  # JSON Schema is arbitrary nesting
    output_schema: (
        dict[str, object] | None
    )  # lup: ignore  # JSON Schema is arbitrary nesting


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
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        sys.stdout.write(text)
    finally:
        os.unlink(tmp.name)


def run_inspect(as_json: bool, full: bool) -> None:
    """Render the full agent configuration as JSON or paged pretty-print."""
    tools_by_server = collect_tools_by_server()
    dynamic_tools = collect_dynamic_tool_names()
    all_tools = collect_all_tools()
    subagents = {s.name: s for s in get_subagent_specs()}
    prompt = get_system_prompt()

    if as_json:
        data: dict[str, object] = {  # lup: ignore  # heterogeneous JSON inspect payload
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


def run_capabilities(markdown: bool) -> None:
    """Print the backend capability matrix — the parity contract, generated.

    ``--markdown`` emits the README-ready table; the regression test in
    ``tests/unit/test_capability_matrix_docs.py`` keeps the README copy
    identical to this output.
    """
    from lup.adapters.common import (
        AdapterCapabilities,
        canonical_capability_matrix,
        capability_matrix_markdown,
    )

    matrix = canonical_capability_matrix()
    if markdown:
        typer.echo(capability_matrix_markdown(matrix))
        return

    names = list(matrix)
    fields = list(AdapterCapabilities.model_fields)
    label_width = max(len(field) for field in fields)

    typer.echo(" " * (label_width + 2) + "".join(f"{name:>10}" for name in names))
    for field in fields:
        cells: list[str] = []
        for name in names:
            match getattr(matrix[name], field):
                case bool() as flag:
                    cells.append(f"{'yes' if flag else '—':>10}")
                case value:
                    cells.append(f"{value:>10}")
        typer.echo(f"{field:<{label_width}}  " + "".join(cells))
