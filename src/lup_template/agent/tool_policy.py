"""Decide which tools the agent is allowed to use this session.

This is a TEMPLATE. Customize for your domain.

A tool may be unavailable because its dependency is unmet — an API key the
settings don't carry, a mode that forbids it. :class:`ToolPolicy` is the one
place that decision lives, so a tool that needs a key you haven't configured
simply never reaches the agent (it can't call a tool that would only fail).

Express each rule whichever way is cheaper to maintain:

- by tag, when you own the tool — annotate it ``tags=["requires:<dep>"]`` at
  its definition and let the policy drop it; the requirement travels with the
  tool, so this file never changes as tools come and go.
- by name, when you don't — group the full names of built-ins or external
  server tools per dependency and subtract them.

Usage:
    from lup.hooks import create_tool_allowlist_hook
    from lup_template.agent.config import settings
    from lup_template.agent.tool_policy import ToolPolicy

    policy = ToolPolicy(settings)
    mcp_servers = policy.get_mcp_servers(*lup_servers)
    hooks = create_tool_allowlist_hook(policy.get_allowed_tools(mcp_servers))
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from lup.adapters.claude.tools import CLAUDE_BUILTIN_TOOLS, FRAMEWORK_TOOLS
from lup.mcp import LupMcpServerConfig, LupMcpTool, McpServerEntry, server_tool_names

if TYPE_CHECKING:
    from lup_template.agent.config import Settings


# claude: backend-abc migration step 10 (move the ToolPolicy mechanism into
# lup.tool_policy, with template subclasses for domain exclusions) is not done —
# ToolPolicy still lives in the template.
class ToolPolicy:
    """Centralized policy for tool availability.

    Determines which tools are available based on:
    - API key availability (from settings)
    - Mode configuration (e.g., restricted mode)
    - Session context (e.g., allow certain tools only in some contexts)

    Customize ``__init__`` to define your exclusion logic.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        restricted_mode: bool = False,
        excluded_tools: frozenset[str] = frozenset(),
        excluded_tags: frozenset[str] = frozenset(),
    ) -> None:
        self.settings = settings
        self.restricted_mode = restricted_mode

        excluded: set[str] = set(excluded_tools)
        tags: set[str] = set(excluded_tags)

        # Tags: map each unmet requirement to its tag (TEMPLATE example —
        # replace with your domain's keys).
        if not settings.example_api_key:
            tags.add("requires:example-api")

        # TODO: Add your name-set exclusion logic

        self.excluded_tools: frozenset[str] = frozenset(excluded)
        self.excluded_tags: frozenset[str] = frozenset(tags)

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
            *additional_servers: Additional in-process servers to include
                (``LupMcpServerConfig`` from ``create_mcp_server``).

        Returns:
            Dict mapping server name to an in-process ``LupMcpServerConfig`` or
            an external transport config (stdio/http/sse). The Claude adapter
            narrows each value by ``isinstance``: the in-process case has a
            ``Server`` instance to register, the external case is passed
            through as-is.

        Customize this to return your domain's MCP servers.
        """
        servers: dict[str, McpServerEntry] = {}

        # Add any additional servers passed in
        for server in additional_servers:
            if self.group_enabled(server.name):
                servers[server.name] = server

        # TODO: Add your MCP servers
        # Example:
        # servers["search"] = search_server
        # servers["financial"] = financial_server
        #
        # Conditional inclusion:
        # if not self.restricted_mode:
        #     servers["live_data"] = live_data_server

        return servers

    def group_enabled(self, name: str) -> bool:
        """Whether a tool group is available under this policy.

        One predicate for every backend: the Claude path filters the
        in-process servers it registers (:meth:`get_mcp_servers`), the
        Codex/OpenAI path filters the group names it serves
        (:meth:`filter_group_names`).

        Customize with your domain's conditions, e.g.::

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
