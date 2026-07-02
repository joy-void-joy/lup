"""Tests for ToolPolicy: server registry, allowlist computation and enforcement."""

import pytest
from pydantic import BaseModel

from lup.hooks import create_tool_allowlist_hook
from lup.mcp import create_mcp_server, lup_tool
from lup.tool_policy import BaseToolPolicy
from lup.types import LupHookInput, LupHooksConfig

from lup_template.agent.config import settings
from lup_template.agent.tool_policy import ToolPolicy


class PingInput(BaseModel):
    text: str


class PingOutput(BaseModel):
    text: str


@lup_tool("Echo a ping. Test fixture tool.")
async def ping(params: PingInput) -> PingOutput:
    return PingOutput(text=params.text)


@lup_tool(
    "Tagged ping requiring an API key. Test fixture tool.", tags=["requires:demo-api"]
)
async def gated_ping(params: PingInput) -> PingOutput:
    return PingOutput(text=params.text)


async def allowlist_decision(
    config: LupHooksConfig, tool_name: str
) -> tuple[str | None, str | None]:
    """Run the allowlist hook for a tool; return (decision, reason)."""
    input_data = LupHookInput(
        hook_event_name="PreToolUse",
        tool_name=tool_name,
        tool_input={},
    )
    output = await config["PreToolUse"][0].hook(input_data)
    return output.get("decision"), output.get("reason")


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

        allowed = policy.get_allowed_tools({})
        assert "WebSearch" not in allowed
        assert "Read" in allowed

    def test_excluded_tool_unavailable(self) -> None:
        policy = ToolPolicy(settings, excluded_tools=frozenset({"WebFetch"}))

        assert not policy.is_tool_available("WebFetch")


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


class TestGetAllowedTools:
    """The allowlist must cover builtins, framework tools, and every
    registered MCP tool — a missing name bricks that tool at runtime."""

    def test_includes_builtins_framework_and_mcp_tools(self) -> None:
        server = create_mcp_server(name="pingsrv", version="1.0.0", tools=[ping])
        policy = ToolPolicy(settings)

        allowed = policy.get_allowed_tools(policy.get_mcp_servers(server))

        assert "Bash" in allowed
        assert "StructuredOutput" in allowed
        assert "mcp__pingsrv__ping" in allowed
        assert "TodoRead" not in allowed

    def test_name_exclusion_removes_tools_from_allowlist(self) -> None:
        server = create_mcp_server(name="pingsrv", version="1.0.0", tools=[ping])
        policy = ToolPolicy(
            settings, excluded_tools=frozenset({"WebFetch", "mcp__pingsrv__ping"})
        )

        allowed = policy.get_allowed_tools(policy.get_mcp_servers(server))

        assert "WebFetch" not in allowed
        assert "mcp__pingsrv__ping" not in allowed
        assert "WebSearch" in allowed


class TestTagFiltering:
    """Tags filter at server construction: tools with unmet requirements
    are never registered instead of failing on their first call."""

    def test_tagged_tool_filtered_when_tag_excluded(self) -> None:
        policy = ToolPolicy(settings, excluded_tags=frozenset({"requires:demo-api"}))

        kept = policy.filter_tools([ping, gated_ping])

        assert gated_ping not in kept
        assert ping in kept

    def test_untagged_tools_unaffected_by_tag_exclusions(self) -> None:
        policy = ToolPolicy(
            settings, excluded_tags=frozenset({"requires:demo-api", "requires:other"})
        )

        assert policy.filter_tools([ping]) == [ping]

    def test_missing_example_key_excludes_example_api_tag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from lup_template.agent.tools.example import EXAMPLE_TOOLS

        monkeypatch.setattr(settings, "example_api_key", None)
        policy = ToolPolicy(settings)

        assert "requires:example-api" in policy.excluded_tags
        kept_names = [t.name for t in policy.filter_tools(EXAMPLE_TOOLS)]
        assert "search_example" not in kept_names
        assert "fetch_example" in kept_names

    def test_present_example_key_keeps_tagged_tools(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from lup_template.agent.tools.example import EXAMPLE_TOOLS

        monkeypatch.setattr(settings, "example_api_key", "key-123")
        policy = ToolPolicy(settings)

        assert "requires:example-api" not in policy.excluded_tags
        assert policy.filter_tools(EXAMPLE_TOOLS) == list(EXAMPLE_TOOLS)


class TestBaseToolPolicyStandalone:
    """The library base must be complete from constructor arguments alone —
    no application settings — so any project can subclass or use it as-is."""

    def test_construction_args_drive_all_filtering(self) -> None:
        policy = BaseToolPolicy(
            excluded_tools=frozenset({"WebFetch"}),
            excluded_tags=frozenset({"requires:demo-api"}),
        )

        assert policy.filter_tools([ping, gated_ping]) == [ping]
        assert not policy.is_tool_available("WebFetch")
        allowed = policy.get_allowed_tools({})
        assert "WebFetch" not in allowed
        assert "Bash" in allowed

    def test_group_predicate_gates_both_backend_paths(self) -> None:
        """One group_enabled override must gate the Claude server registry
        and the Codex served-group names identically."""

        class RestrictedPolicy(BaseToolPolicy):
            def group_enabled(self, name: str) -> bool:
                return not (name == "sandbox" and self.restricted_mode)

        policy = RestrictedPolicy(restricted_mode=True)

        assert policy.filter_group_names(("notes", "sandbox")) == ("notes",)
        sandbox_server = create_mcp_server(name="sandbox", version="1.0.0", tools=[])
        assert policy.get_mcp_servers(sandbox_server) == {}


class TestAllowlistEnforcement:
    """Policy + allowlist hook end-to-end: under bypassPermissions the
    hook is the only thing standing between the agent and excluded tools."""

    async def test_builtin_tool_allowed(self) -> None:
        policy = ToolPolicy(settings)
        config = create_tool_allowlist_hook(policy.get_allowed_tools({}))

        decision, _ = await allowlist_decision(config, "Read")

        assert decision == "allow"

    async def test_registered_mcp_tool_allowed(self) -> None:
        server = create_mcp_server(name="pingsrv", version="1.0.0", tools=[ping])
        policy = ToolPolicy(settings)
        servers = policy.get_mcp_servers(server)
        config = create_tool_allowlist_hook(policy.get_allowed_tools(servers))

        decision, _ = await allowlist_decision(config, "mcp__pingsrv__ping")

        assert decision == "allow"

    async def test_excluded_tool_denied_with_available_tools_listed(self) -> None:
        policy = ToolPolicy(settings, excluded_tools=frozenset({"WebFetch"}))
        config = create_tool_allowlist_hook(policy.get_allowed_tools({}))

        decision, reason = await allowlist_decision(config, "WebFetch")

        assert decision == "deny"
        assert reason is not None
        assert "WebFetch" in reason
        assert "Available tools" in reason
        assert "WebSearch" in reason
