"""Tests for ToolPolicy class."""

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
