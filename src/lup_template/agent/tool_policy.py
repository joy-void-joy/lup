"""Conditional tool availability based on configuration.

This is a TEMPLATE. Customize for your domain.

Key patterns:
1. Define tool sets as frozensets for fast membership testing
2. ToolPolicy class computes excluded tools at construction
3. Separate get_mcp_servers() and get_allowed_tools() methods

Usage:
    from lup_template.agent.config import settings
    from lup_template.agent.tool_policy import ToolPolicy

    policy = ToolPolicy(settings)
    mcp_servers = policy.get_mcp_servers()
    allowed_tools = policy.get_allowed_tools()
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any  # claude: ignore — for the ServerConfig alias

if TYPE_CHECKING:
    from lup.mcp import LupMcpServerConfig
    from lup_template.agent.config import Settings

# An MCP server entry is either an in-process LupMcpServerConfig or a raw SDK
# McpServerConfig (stdio/http/sse). core.py narrows each by hasattr(server,
# "server"), which pyright can't follow through that union — so the dict is
# typed Any here and resolved at the conversion site.
type ServerConfig = Any  # claude: ignore — runtime-narrowed union, see above


# =============================================================================
# TOOL SETS - Define tools that require specific API keys
# =============================================================================

# Built-in SDK tools (always available)
BUILTIN_TOOLS: frozenset[str] = frozenset(
    {
        "WebSearch",
        "WebFetch",
        "Read",
        "Write",
        "Glob",
        "Grep",
        "Bash",
        "Task",
        "TodoWrite",
    }
)

# Define named tool sets for each API dependency.
# Each set groups tools that share the same API key requirement.
# This makes it clear which tools degrade when a key is missing.
#
# Example:
# EXA_TOOLS: frozenset[str] = frozenset({
#     "mcp__search__search_exa",
# })
#
# FRED_TOOLS: frozenset[str] = frozenset({
#     "mcp__financial__fred_series",
#     "mcp__financial__fred_search",
# })


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
    ) -> None:
        self.settings = settings
        self.restricted_mode = restricted_mode

        excluded: set[str] = set()

        # TODO: Add your exclusion logic
        # Example:
        # if not settings.exa_api_key:
        #     excluded.update(EXA_TOOLS)
        # if not settings.fred_api_key:
        #     excluded.update(FRED_TOOLS)
        # if self.restricted_mode:
        #     excluded.update(LIVE_DATA_TOOLS)

        self.excluded_tools: frozenset[str] = frozenset(excluded)

    def get_mcp_servers(
        self, *additional_servers: LupMcpServerConfig
    ) -> dict[str, ServerConfig]:
        """Get MCP server configuration based on policy.

        Args:
            *additional_servers: Additional in-process servers to include
                (``LupMcpServerConfig`` from ``create_mcp_server``).

        Returns:
            Dict mapping server name to server config. Values are in-process
            ``LupMcpServerConfig`` or a raw SDK ``McpServerConfig``
            (stdio/http/sse); core.py converts the former to the SDK type at
            build time, narrowing each value by whether it has a ``server``
            attribute.

        Customize this to return your domain's MCP servers.
        """
        servers: dict[str, ServerConfig] = {}

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

    def get_allowed_tools(self) -> list[str]:
        """Get list of allowed tools based on policy.

        Returns:
            Sorted list of tool names that are allowed.
        """
        # Start with all potential tools
        tools: set[str] = set()

        # Built-in tools
        tools.update(BUILTIN_TOOLS)

        # TODO: Add your tool sets
        # tools.update(EXA_TOOLS)
        # tools.update(FRED_TOOLS)
        # tools.update(YOUR_DOMAIN_TOOLS)

        # Remove excluded tools
        tools -= self.excluded_tools

        return sorted(tools)

    def is_tool_available(self, tool_name: str) -> bool:
        """Check if a specific tool is available under this policy."""
        return tool_name not in self.excluded_tools
