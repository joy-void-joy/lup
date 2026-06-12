"""Tests for ToolPolicy class."""

from lup.mcp import create_mcp_server

from lup_template.agent.config import settings
from lup_template.agent.tool_policy import ToolPolicy


class TestToolPolicyIsToolAvailable:
    """Tests for is_tool_available method."""

    def test_excluded_tool_is_unavailable(self) -> None:
        """A tool in excluded_tools must report unavailable."""
        policy = ToolPolicy(settings)
        policy.excluded_tools = frozenset({"mcp__live__quote"})

        assert not policy.is_tool_available("mcp__live__quote")
        assert policy.is_tool_available("mcp__live__history")

    def test_excluded_tools_dropped_from_allowed_list(self) -> None:
        """get_allowed_tools must omit excluded built-in tools."""
        policy = ToolPolicy(settings)
        policy.excluded_tools = frozenset({"WebSearch"})

        allowed = policy.get_allowed_tools()
        assert "WebSearch" not in allowed
        assert "Read" in allowed


class TestGetMcpServers:
    """Server registry keys determine the mcp__<server>__<tool> names the
    agent sees — a mangled key breaks every tool on that server."""

    def test_server_keyed_by_its_name(self) -> None:
        server = create_mcp_server(name="example", version="1.0.0", tools=[])
        policy = ToolPolicy(settings)

        servers = policy.get_mcp_servers(server)

        assert list(servers) == ["example"]
        assert servers["example"] is server

    def test_multiple_servers_keep_distinct_names(self) -> None:
        first = create_mcp_server(name="alpha", version="1.0.0", tools=[])
        second = create_mcp_server(name="beta", version="1.0.0", tools=[])
        policy = ToolPolicy(settings)

        servers = policy.get_mcp_servers(first, second)

        assert sorted(servers) == ["alpha", "beta"]
