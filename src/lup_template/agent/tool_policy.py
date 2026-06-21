"""Conditional tool availability based on configuration.

This is a TEMPLATE. Customize for your domain.

Key patterns:
1. Define tool sets as frozensets for fast membership testing #claude: This is bad writing. I do not care about why you re using frozensets. I care about what you're doing in this file and why. Why is it useful for. Why should I care?
2. ToolPolicy class computes excluded tools and tags at construction
3. get_mcp_servers() registers servers; get_allowed_tools() feeds the
   allowlist hook that enforces availability at call time

Usage:
    from lup.hooks import create_tool_allowlist_hook
    from lup_template.agent.config import settings
    from lup_template.agent.tool_policy import ToolPolicy

    policy = ToolPolicy(settings)
    mcp_servers = policy.get_mcp_servers(*lup_servers)
    hooks = create_tool_allowlist_hook(policy.get_allowed_tools(mcp_servers))
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any  # claude: ignore — for the ServerConfig alias

from lup.mcp import LupMcpServerConfig, LupMcpTool, server_tool_names

if TYPE_CHECKING:
    from lup_template.agent.config import Settings

# An MCP server entry is either an in-process LupMcpServerConfig or a raw SDK
# McpServerConfig (stdio/http/sse). core.py narrows each by hasattr(server,
# "server"), which pyright can't follow through that union — so the dict is
# typed Any here and resolved at the conversion site.
# claude: What? This is extremely confusing. Why do you type alias any? Seems like something that should stay purely in the backend?
type ServerConfig = Any  # claude: ignore — runtime-narrowed union, see above


# =============================================================================
# TOOL SETS - Define tools that require specific API keys
# =============================================================================

# Claude Agent SDK builtin tool names — consumed only by build_options()
# on the Claude path. Codex/OpenAI agents get tools from the served MCP
# groups (toolsets.py) plus the Codex runtime's native shell/file/web tools.

# claude: I feel like this could be unified? Also, this feels fundamental enough thaat I don't understand why this is in the template
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
)

# Tools the SDK injects for the session itself, outside the builtin
# toolset: StructuredOutput emits the final structured output when
# ClaudeAgentOptions.output_format is set, so denying it would leave the
# agent unable to finish.
# claude: What? You're saying "we shouldn't deny it", but I don't even know why I would have denied it in the first place
FRAMEWORK_TOOLS: frozenset[str] = frozenset({"StructuredOutput"})

# Two complementary mechanisms control which tools the agent gets:
#
# 1. Tags (primary) — declare the requirement on the tool itself:
# claude: What? What are tags? How are they defined?
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
    # claude: Are you sure this should be in template? Seems like the construct itself should be universal and go in lib?
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
        #claude: I really don't know if I buy this whole tag logic
        if not settings.example_api_key:
            tags.add("requires:example-api")

        # TODO: Add your name-set exclusion logic
        # claude: Yes. TODOs are great. I think we should have more TODOs for the agent in the template, there's not enough of those
        # Example:
        # if self.restricted_mode:
        #     excluded.update(LIVE_DATA_TOOLS)

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

    def get_allowed_tools(self, servers: dict[str, ServerConfig]) -> list[str]:
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
