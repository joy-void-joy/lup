"""Tests for ToolPolicy: server registry, allowlist computation and enforcement."""

from typing import cast

from claude_agent_sdk.types import (
    HookContext,
    PreToolUseHookInput,
    PreToolUseHookSpecificOutput,
    SyncHookJSONOutput,
)
from pydantic import BaseModel

from lup.hooks import HooksConfig, create_tool_allowlist_hook
from lup.mcp import create_mcp_server, extract_sdk_tools, lup_tool

from lup_template.agent.config import settings
from lup_template.agent.tool_policy import ToolPolicy


class PingInput(BaseModel):
    text: str


class PingOutput(BaseModel):
    text: str


@lup_tool("Echo a ping. Test fixture tool.")
async def ping(params: PingInput) -> PingOutput:
    return PingOutput(text=params.text)


async def allowlist_decision(
    config: HooksConfig, tool_name: str
) -> tuple[str | None, str | None]:
    """Run the allowlist hook for a tool; return (decision, reason)."""
    input_data = PreToolUseHookInput(
        hook_event_name="PreToolUse",
        session_id="s",
        transcript_path="",
        cwd="",
        tool_name=tool_name,
        tool_input={},
        tool_use_id="t-1",
    )
    hook = config["PreToolUse"][0].hooks[0]
    output = cast(
        SyncHookJSONOutput, await hook(input_data, None, HookContext(signal=None))
    )
    specific = cast(
        PreToolUseHookSpecificOutput | None, output.get("hookSpecificOutput")
    )
    if specific is None:
        return None, None
    return specific.get("permissionDecision"), specific.get("permissionDecisionReason")


class TestToolPolicyIsToolAvailable:
    """Tests for is_tool_available method."""

    def test_unknown_tool_available(self) -> None:
        """Unknown tools should be available (not excluded)."""
        policy = ToolPolicy(settings)

        assert policy.is_tool_available("mcp__custom__my_tool")

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
        server = create_mcp_server(
            name="pingsrv", version="1.0.0", tools=extract_sdk_tools([ping])
        )
        policy = ToolPolicy(settings)

        allowed = policy.get_allowed_tools(policy.get_mcp_servers(server))

        assert "Bash" in allowed
        assert "StructuredOutput" in allowed
        assert "mcp__pingsrv__ping" in allowed
        assert "TodoRead" not in allowed

    def test_name_exclusion_removes_tools_from_allowlist(self) -> None:
        server = create_mcp_server(
            name="pingsrv", version="1.0.0", tools=extract_sdk_tools([ping])
        )
        policy = ToolPolicy(
            settings, excluded_tools=frozenset({"WebFetch", "mcp__pingsrv__ping"})
        )

        allowed = policy.get_allowed_tools(policy.get_mcp_servers(server))

        assert "WebFetch" not in allowed
        assert "mcp__pingsrv__ping" not in allowed
        assert "WebSearch" in allowed


class TestAllowlistEnforcement:
    """Policy + allowlist hook end-to-end: under bypassPermissions the
    hook is the only thing standing between the agent and excluded tools."""

    async def test_builtin_tool_allowed(self) -> None:
        policy = ToolPolicy(settings)
        config = create_tool_allowlist_hook(policy.get_allowed_tools({}))

        decision, _ = await allowlist_decision(config, "Read")

        assert decision == "allow"

    async def test_registered_mcp_tool_allowed(self) -> None:
        server = create_mcp_server(
            name="pingsrv", version="1.0.0", tools=extract_sdk_tools([ping])
        )
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
