"""Translate neutral :class:`~lup.options.LupAgentOptions` into a Claude adapter.

This is where every Claude-specific construction detail lives: the
``claude_code`` system-prompt preset, the ``no-session-persistence`` extra arg,
the sandbox enablement block, the generic-effort -> ``EffortLevel`` mapping, and
the conversion of neutral hooks/servers/subagents into their SDK shapes. The
template hands over an assembled :class:`~lup.options.LupAgentOptions` and never
names ``ClaudeAgentOptions``.
"""

from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk.types import EffortLevel, McpSdkServerConfig

from lup.adapters.claude.adapter import (
    ClaudeAdapter,
    lup_hooks_to_claude,
    lup_server_to_claude,
    spec_to_claude,
)
from lup.mcp import LupMcpServerConfig, McpServerEntry, RawMcpServerConfig
from lup.options import BuiltAdapter, LupAgentOptions
from lup.types import normalize_effort


def server_to_claude(
    entry: McpServerEntry,
) -> McpSdkServerConfig | RawMcpServerConfig:
    """Narrow one neutral MCP entry to its Claude SDK form.

    An in-process ``LupMcpServerConfig`` becomes an SDK ``sdk`` server wrapping
    its live instance; an external transport config passes straight through.
    The ``isinstance`` is what replaces the old ``hasattr(server, "server")``
    runtime narrowing.
    """
    match entry:
        case LupMcpServerConfig():
            return lup_server_to_claude(entry)
        case _:
            return entry


def claude_effort(reasoning_effort: str | None) -> EffortLevel | None:
    """Map a generic effort level to the Claude SDK's ``EffortLevel``.

    ``EffortLevel`` is in scope here, so the mapping happens inside the adapter
    layer rather than leaking the SDK enum into the template. The normalized
    value is matched against the literal's members, so an unrecognized effort
    is dropped rather than smuggled through with a cast.
    """
    match normalize_effort(reasoning_effort, "anthropic"):
        case "low" | "medium" | "high" | "xhigh" | "max" as level:
            return level
        case _:
            return None


def build_claude_options(opts: LupAgentOptions) -> ClaudeAgentOptions:
    """Assemble the native ``ClaudeAgentOptions`` from neutral options."""
    extra_args: dict[str, str | None] = {}
    if not opts.persist_session:
        extra_args["no-session-persistence"] = None

    mcp_servers = {
        name: server_to_claude(server) for name, server in opts.tool_servers.items()
    }
    subagents = {spec.name: spec_to_claude(spec) for spec in opts.subagents}

    return ClaudeAgentOptions(
        model=opts.model,
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": opts.system_prompt,
        },
        max_thinking_tokens=opts.max_thinking_tokens,
        permission_mode=opts.permission_mode,
        extra_args=extra_args,
        hooks=lup_hooks_to_claude(opts.hooks),
        sandbox={
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
        },
        mcp_servers=mcp_servers,
        agents=subagents,
        add_dirs=[str(d) for d in opts.add_dirs],
        allowed_tools=opts.allowed_tools,
        max_turns=opts.max_turns,
        max_budget_usd=opts.max_budget_usd,
        effort=claude_effort(opts.reasoning_effort),
    )


def build_claude_adapter(opts: LupAgentOptions) -> BuiltAdapter:
    """Build the Claude adapter; its lifecycle is the caller-supplied sandbox."""
    return BuiltAdapter(adapter=ClaudeAdapter(build_claude_options(opts)))
