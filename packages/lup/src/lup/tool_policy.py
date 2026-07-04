"""Tool-availability filtering: the mechanism, not the policy.

A session's tools pass through one policy object that decides what the
agent may call. *Which* exclusions apply is a per-project decision (API
keys, modes, session context), so this module owns only the machinery:
exclusion sets, tag filtering, the group predicate both backend paths
share, MCP-server assembly, and the Claude-path allowlist. A project
subclasses :class:`BaseToolPolicy` and maps its own settings onto the
constructor's exclusion arguments.

Express each exclusion whichever way is cheaper to maintain:

- by tag, when you own the tool — annotate it ``tags=["requires:<dep>"]``
  at its definition and exclude the tag when the dependency is unmet;
  the requirement travels with the tool, so the policy never changes as
  tools come and go.
- by name, when you don't — group the full names of built-ins or
  external server tools per dependency and subtract them.
"""

from collections.abc import Sequence

from lup.mcp import LupMcpServerConfig, LupMcpTool, McpServerEntry, server_tool_names

CLAUDE_BUILTIN_TOOLS: frozenset[str] = frozenset(
    {
        "Bash",
        "Edit",
        "Glob",
        "Grep",
        "NotebookEdit",
        "Read",
        "Task",
        "TodoWrite",
        "WebFetch",
        "WebSearch",
        "Write",
    }
)  # lup: We shouldn't have claude specific mentions here
"""The Claude Code built-in tool names a session may call.

A property of the Claude backend, not of any domain: the tools the SDK
exposes natively (shell/file/web). The allowlist computation reads these
to name every tool a Claude session may call; Codex/OpenAI agents get
tools from the served MCP groups plus the Codex runtime's own native
tools instead."""

FRAMEWORK_TOOLS: frozenset[str] = frozenset(
    {"StructuredOutput"}
)  # lup: Neither frozenset
"""Tools the agent always needs: ``StructuredOutput`` emits the final result
under ``ClaudeAgentOptions.output_format``, so the allowlist must carry it even
though no template tool defines it."""

SHELL_BUILTIN_TOOLS: frozenset[str] = frozenset({"Bash"})
"""Built-in tools that grant raw host-shell execution.

Dropped from the allowlist by default when the session carries a
code-execution sandbox (``code_execution=True``): the sandbox's isolated
``execute_code`` is the sanctioned code path, so raw shell is defense-in-depth
opt-in (``allow_shell=True``) rather than granted alongside it."""


class BaseToolPolicy:
    """Centralized machinery for tool availability.

    Subclasses decide *what* is excluded — typically in ``__init__``, by
    mapping application settings (API-key presence, modes) onto the
    exclusion arguments — and may override :meth:`group_enabled` for
    conditional groups or :meth:`get_mcp_servers` to register additional
    servers. The base owns *how* exclusions apply, identically on every
    backend path.

    When the session carries a code-execution sandbox
    (``code_execution=True``), :data:`SHELL_BUILTIN_TOOLS` (raw shell) is
    excluded by default; ``allow_shell=True`` opts back in.
    """

    def __init__(
        self,
        *,
        restricted_mode: bool = False,
        excluded_tools: frozenset[str] = frozenset(),
        excluded_tags: frozenset[str] = frozenset(),
        code_execution: bool = False,
        allow_shell: bool = False,
    ) -> None:
        self.restricted_mode = restricted_mode
        self.code_execution = code_execution
        self.allow_shell = allow_shell
        exclusions = set(excluded_tools)
        if code_execution and not allow_shell:
            exclusions |= SHELL_BUILTIN_TOOLS
        self.excluded_tools: frozenset[str] = frozenset(exclusions)
        self.excluded_tags: frozenset[str] = frozenset(excluded_tags)

    def filter_tools(self, tools: Sequence[LupMcpTool]) -> list[LupMcpTool]:
        """Drop tools whose tags intersect the policy's excluded tags.

        Apply before ``create_mcp_server`` so tools with unmet
        requirements are never registered — the agent only sees tools it
        can actually use. Untagged tools always pass through.
        """
        return [tool for tool in tools if not (set(tool.tags) & self.excluded_tags)]

    def get_mcp_servers(
        self, *additional_servers: LupMcpServerConfig
    ) -> dict[str, McpServerEntry]:
        """Get MCP server configuration based on policy.

        Args:
            *additional_servers: In-process servers to include
                (``LupMcpServerConfig`` from ``create_mcp_server``),
                registered only when their group is enabled.

        Returns:
            Dict mapping server name to an in-process ``LupMcpServerConfig`` or
            an external transport config (stdio/http/sse). The Claude adapter
            narrows each value by ``isinstance``: the in-process case has a
            ``Server`` instance to register, the external case is passed
            through as-is.

        Override to add a project's own servers (external transports,
        conditionally-included groups) on top of the passed-in ones.
        """
        servers: dict[str, McpServerEntry] = {}

        for server in additional_servers:
            if self.group_enabled(server.name):
                servers[server.name] = server

        return servers

    def group_enabled(self, name: str) -> bool:
        """Whether a tool group is available under this policy.

        One predicate for every backend: the Claude path filters the
        in-process servers it registers (:meth:`get_mcp_servers`), the
        Codex/OpenAI path filters the group names it serves
        (:meth:`filter_group_names`). Override with the project's
        conditions, e.g.::

            if name == "live_data":
                return not self.restricted_mode
        """
        _ = name
        return True

    def filter_group_names(self, names: Sequence[str]) -> tuple[str, ...]:
        """Filter tool-group names by policy (subprocess-served backends)."""
        return tuple(name for name in names if self.group_enabled(name))

    def get_allowed_tools(self, servers: dict[str, McpServerEntry]) -> list[str]:
        """Compute every tool name the agent may call (Claude path only —
        Codex/OpenAI tool availability is the served MCP groups).

        Combines built-in Claude Code tools, SDK framework tools, and the
        ``mcp__{server}__{tool}`` name of every tool on the registered
        *servers*, minus policy-excluded names. Feed the result to
        :func:`lup.hooks.create_tool_allowlist_hook` — under
        ``permission_mode="bypassPermissions"`` the SDK's ``allowed_tools``
        option is ignored, so that hook is the enforcement point.

        Args:
            servers: Registered MCP servers (from :meth:`get_mcp_servers`),
                keyed by the server name the SDK uses for tool prefixes.

        Returns:
            Sorted list of allowed tool names.
        """
        tools: set[str] = set(CLAUDE_BUILTIN_TOOLS) | set(FRAMEWORK_TOOLS)

        for server_name, server in servers.items():
            for tool_name in server_tool_names(server):
                tools.add(f"mcp__{server_name}__{tool_name}")

        tools -= self.excluded_tools

        return sorted(tools)

    def is_tool_available(self, tool_name: str) -> bool:
        """Check if a specific tool is available under this policy."""
        return tool_name not in self.excluded_tools
