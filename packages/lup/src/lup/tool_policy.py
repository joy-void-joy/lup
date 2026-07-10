"""Tool-availability filtering: the mechanism, not the policy.

A session's tools pass through one policy object that decides what the
agent may call. *Which* exclusions apply is a per-project decision (API
keys, modes, session context), so this module owns only the machinery:
exclusion sets, tag filtering, the group predicate both backend paths
share, MCP-server assembly, and the hook-enforced allowlist. A project
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

from collections.abc import Iterable, Sequence

from lup.mcp import LupMcpServerConfig, LupMcpTool, McpServerEntry, server_tool_names

type NameSet = set[str]  # lup: ignore[set-shape] — membership-tested name sets


class BaseToolPolicy:
    """Centralized machinery for tool availability.

    Subclasses decide *what* is excluded — typically in ``__init__``, by
    mapping application settings (API-key presence, modes) onto the
    exclusion arguments — and may override :meth:`group_enabled` for
    conditional groups or :meth:`get_mcp_servers` to register additional
    servers. The base owns *how* exclusions apply, identically on every
    backend path.
    """

    def __init__(
        self,
        *,
        restricted_mode: bool = False,
        excluded_tools: Iterable[str] | None = None,
        excluded_tags: Iterable[str] | None = None,
    ) -> None:
        self.restricted_mode = restricted_mode
        # Internal state is set-shaped for the exclusion algebra
        # (difference/intersection in the filters below).
        tools_off = set(excluded_tools or ())  # lup: ignore[set-shape]
        tags_off = set(excluded_tags or ())  # lup: ignore[set-shape]
        self.excluded_tools: NameSet = tools_off
        self.excluded_tags: NameSet = tags_off

    def filter_tools(self, tools: Sequence[LupMcpTool]) -> list[LupMcpTool]:
        """Drop tools whose tags intersect the policy's excluded tags.

        Apply before ``create_mcp_server`` so tools with unmet
        requirements are never registered — the agent only sees tools it
        can actually use. Untagged tools always pass through.
        """
        excluded = self.excluded_tags
        return [tool for tool in tools if not excluded.intersection(tool.tags)]

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
            an external transport config (stdio/http/sse). The in-process
            adapter narrows each value by ``isinstance``: the in-process case
            has a ``Server`` instance to register, the external case is passed
            through as-is.

        Override to add a project's own servers (external transports,
        conditionally-included groups) on top of the passed-in ones.
        """
        return {
            server.name: server
            for server in additional_servers
            if self.group_enabled(server.name)
        }

    def group_enabled(self, name: str) -> bool:
        """Whether a tool group is available under this policy.

        One predicate for every backend: the hook-enforced path filters the
        in-process servers it registers (:meth:`get_mcp_servers`), the
        subprocess-served path filters the group names it serves
        (:meth:`filter_group_names`). Override with the project's
        conditions, e.g.::

            if name == "live_data":
                return not self.restricted_mode
        """
        _ = name
        return True

    def filter_group_names(self, names: Sequence[str]) -> list[str]:
        """Filter tool-group names by policy (subprocess-served backends)."""
        return [name for name in names if self.group_enabled(name)]

    def get_allowed_tools(
        self,
        servers: dict[str, McpServerEntry],
        *,
        builtin_tools: frozenset[str] = frozenset(),  # lup: ignore[frozenset-shape]
    ) -> list[str]:
        """Compute every tool name the agent may call (hook-enforced path only —
        on subprocess-served backends tool availability is the served MCP groups).

        Combines the engine's *builtin_tools*, framework tools, and the
        ``mcp__{server}__{tool}`` name of every tool on the registered
        *servers*, minus policy-excluded names. Feed the result to
        :func:`lup.hooks.create_tool_allowlist_hook` — under
        ``permission_mode="bypassPermissions"`` the SDK's ``allowed_tools``
        option is ignored, so that hook is the enforcement point.

        Args:
            servers: Registered MCP servers (from :meth:`get_mcp_servers`),
                keyed by the server name the SDK uses for tool prefixes.
            builtin_tools: The engine's native built-in tool names (a
                per-backend table from the engine's module under
                ``lup.adapters.tools``); empty for backends that expose
                none.

        Returns:
            Sorted list of allowed tool names.
        """
        # StructuredOutput is the SDK's own tool for emitting the final result
        # under output_format; no template tool defines it, so the allowlist
        # carries it alongside the engine's builtins.
        tools: NameSet = {"StructuredOutput", *builtin_tools}

        for server_name, server in servers.items():
            for tool_name in server_tool_names(server):
                tools.add(f"mcp__{server_name}__{tool_name}")

        tools -= self.excluded_tools

        return sorted(tools)

    def is_tool_available(self, tool_name: str) -> bool:
        """Check if a specific tool is available under this policy."""
        return tool_name not in self.excluded_tools
