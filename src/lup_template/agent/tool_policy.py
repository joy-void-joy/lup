"""Conditional tool availability based on configuration.

This is a TEMPLATE. Customize for your domain.

Key patterns:
1. Define tool sets as frozensets for fast membership testing
2. ToolPolicy class computes excluded tools at construction
3. from_settings() factory for easy initialization
4. get_mcp_servers() registers servers; get_allowed_tools() feeds the
   allowlist hook that enforces availability at call time

Usage:
    from lup.hooks import create_tool_allowlist_hook
    from lup_template.agent.config import settings
    from lup_template.agent.tool_policy import ToolPolicy

    policy = ToolPolicy.from_settings(settings)
    mcp_servers = policy.get_mcp_servers(*sdk_servers)
    hooks = create_tool_allowlist_hook(policy.get_allowed_tools(mcp_servers))
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from claude_agent_sdk.types import McpSdkServerConfig, McpServerConfig

from lup.mcp import LupMcpTool, server_tool_names

if TYPE_CHECKING:
    from lup_template.agent.config import Settings


# =============================================================================
# TOOL SETS - Define tools that require specific API keys
# =============================================================================

# Built-in Claude Code tools (always available)
BUILTIN_TOOLS: frozenset[str] = frozenset(
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
)

# Tools the SDK injects for the session itself, outside the builtin
# toolset: StructuredOutput emits the final structured output when
# ClaudeAgentOptions.output_format is set, so denying it would leave the
# agent unable to finish.
FRAMEWORK_TOOLS: frozenset[str] = frozenset({"StructuredOutput"})

# Two complementary mechanisms control which tools the agent gets:
#
# 1. Tags (primary) — declare the requirement on the tool itself:
#
#        @lup_tool("...", tags=["requires:example-api"])
#
#    ``__init__`` maps missing settings to excluded tags, and
#    ``filter_tools()`` drops tagged tools before server registration.
#    The requirement lives next to the tool definition, so adding or
#    renaming a tool never means editing this file.
#
# 2. Name sets — for tools you don't define (built-ins, external
#    servers), group full tool names per dependency and subtract them
#    via ``excluded_tools``:
#
#        LIVE_DATA_TOOLS: frozenset[str] = frozenset({
#            "WebSearch",
#            "mcp__external__live_quote",
#        })
#
#    Name exclusions are enforced by the allowlist hook at call time.


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
        # Example:
        # if self.restricted_mode:
        #     excluded.update(LIVE_DATA_TOOLS)

        self.excluded_tools: frozenset[str] = frozenset(excluded)
        self.excluded_tags: frozenset[str] = frozenset(tags)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        restricted_mode: bool = False,
    ) -> ToolPolicy:
        """Create a ToolPolicy from application settings.

        Args:
            settings: Application settings with API keys.
            restricted_mode: If True, enables additional restrictions.

        Returns:
            ToolPolicy configured based on settings.
        """
        return cls(
            settings,
            restricted_mode=restricted_mode,
        )

    def filter_tools(self, tools: Sequence[LupMcpTool]) -> list[LupMcpTool]:
        """Drop tools whose tags intersect the policy's excluded tags.

        Apply before ``create_mcp_server`` so tools with unmet
        requirements are never registered — the agent only sees tools it
        can actually use. Untagged tools always pass through.
        """
        return [tool for tool in tools if not (set(tool.tags) & self.excluded_tags)]

    def get_mcp_servers(
        self, *additional_servers: McpSdkServerConfig
    ) -> dict[str, McpServerConfig]:
        """Get MCP server configuration based on policy.

        Args:
            *additional_servers: Additional MCP servers to include.

        Returns:
            Dict mapping server name to server config.

        Customize this to return your domain's MCP servers.
        """
        servers: dict[str, McpServerConfig] = {}

        # Add any additional servers passed in
        for server in additional_servers:
            servers[server["name"]] = server

        # TODO: Add your MCP servers
        # Example:
        # servers["search"] = search_server
        # servers["financial"] = financial_server
        #
        # Conditional inclusion:
        # if not self.restricted_mode:
        #     servers["live_data"] = live_data_server

        return servers

    def get_allowed_tools(self, servers: dict[str, McpServerConfig]) -> list[str]:
        """Compute every tool name the agent may call.

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
        tools: set[str] = set(BUILTIN_TOOLS) | set(FRAMEWORK_TOOLS)

        for server_name, server in servers.items():
            for tool_name in server_tool_names(server):
                tools.add(f"mcp__{server_name}__{tool_name}")

        tools -= self.excluded_tools

        return sorted(tools)

    def is_tool_available(self, tool_name: str) -> bool:
        """Check if a specific tool is available under this policy."""
        return tool_name not in self.excluded_tools
