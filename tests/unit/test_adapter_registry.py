"""The adapter registry dispatches by backend and builders honor neutral options.

These pin the construction seam the refactor introduces: ``build_adapter`` picks
the right engine builder, the Claude builder translates a neutral
``LupAgentOptions`` into native ``ClaudeAgentOptions`` (effort mapping,
session-persistence, server narrowing), and ``degrade_unsupported`` drops
one-shot options a weak backend cannot honor instead of raising.
"""

from lup.adapters.common import (
    AdapterCapabilities,
    OneShotOptions,
    degrade_unsupported,
)
from lup.adapters.registry import BACKEND_BUILDERS, build_adapter
from lup.mcp import LupMcpServerConfig, create_mcp_server
from lup.options import CodexOptions, LupAgentOptions
from lup.types import SubagentSpec


def claude_caps() -> AdapterCapabilities:
    from lup.adapters.claude.adapter import ClaudeAdapter
    from claude_agent_sdk import ClaudeAgentOptions

    return ClaudeAdapter(ClaudeAgentOptions()).capabilities


def weak_caps() -> AdapterCapabilities:
    from lup.adapters.codex.adapter import CodexAdapter

    return CodexAdapter(model="gpt-5.5", system_prompt="").capabilities


def test_registry_covers_every_backend() -> None:
    """Every Backend literal resolves to a builder — no gap a dispatch would hit."""
    from typing import get_args

    from lup.types import Backend

    assert set(BACKEND_BUILDERS) == set(get_args(Backend.__value__))


def test_build_adapter_dispatches_to_claude() -> None:
    from lup.adapters.claude.adapter import ClaudeAdapter

    built = build_adapter("anthropic", LupAgentOptions(model="claude-opus-4-6"))
    assert isinstance(built.adapter, ClaudeAdapter)
    assert built.mailbox is None


def test_claude_builder_translates_neutral_options() -> None:
    server = create_mcp_server("notes", tools=[])
    opts = LupAgentOptions(
        model="claude-opus-4-6",
        system_prompt="be good",
        tool_servers={"notes": server},
        subagents=[SubagentSpec(name="r", description="d", prompt="p")],
        allowed_tools=["Read"],
        max_turns=7,
        reasoning_effort="high",
        persist_session=False,
    )

    built = build_adapter("anthropic", opts)
    from lup.adapters.claude.adapter import ClaudeAdapter

    assert isinstance(built.adapter, ClaudeAdapter)
    native = built.adapter.options
    assert native.model == "claude-opus-4-6"
    assert native.max_turns == 7
    assert native.effort == "high"
    assert native.allowed_tools == ["Read"]
    # no-session-persistence is the Claude wire form of persist_session=False.
    assert native.extra_args == {"no-session-persistence": None}
    # The in-process server became an SDK ``sdk`` server, not passed through raw.
    assert isinstance(native.mcp_servers, dict)
    assert native.mcp_servers["notes"].get("type") == "sdk"
    assert native.agents is not None and "r" in native.agents


def test_claude_builder_keeps_session_when_persisting() -> None:
    built = build_adapter(
        "anthropic", LupAgentOptions(model="claude-opus-4-6", persist_session=True)
    )
    from lup.adapters.claude.adapter import ClaudeAdapter

    assert isinstance(built.adapter, ClaudeAdapter)
    assert "no-session-persistence" not in built.adapter.options.extra_args


def test_codex_builder_carries_budget_and_groups() -> None:
    from lup.adapters.codex.adapter import CodexAdapter, per_mtok_usage_cost

    opts = LupAgentOptions(
        model="gpt-5.5",
        served_tool_groups=("notes", "sandbox"),
        max_budget_usd=1.0,
        usage_cost=per_mtok_usage_cost(input_usd=1.0, output_usd=1.0),
        codex=CodexOptions(approval_policy="auto"),
    )
    built = build_adapter("openai", opts)
    assert isinstance(built.adapter, CodexAdapter)
    assert built.adapter.mcp_servers == ("notes", "sandbox")
    assert built.adapter.max_budget_usd == 1.0


def test_openai_builder_sets_provider() -> None:
    from lup.adapters.codex.openai_compat import OpenAICompatibleAdapter

    opts = LupAgentOptions(
        model="glm-4",
        codex=CodexOptions(
            openai_base_url="http://local", openai_model_provider="prov"
        ),
    )
    built = build_adapter("openai-compatible", opts)
    assert isinstance(built.adapter, OpenAICompatibleAdapter)
    assert built.adapter.base_url == "http://local"
    assert built.adapter.model_provider == "prov"


def test_degrade_drops_unsupported_on_weak_backend() -> None:
    asked = OneShotOptions(
        tools=["Read"], max_turns=5, max_thinking_tokens=8000, permission_mode="plan"
    )
    kept = degrade_unsupported(asked, weak_caps(), backend="openai", model="gpt-5.5")
    assert kept == OneShotOptions()


def test_degrade_keeps_everything_on_claude() -> None:
    asked = OneShotOptions(tools=["Read"], max_turns=5)
    kept = degrade_unsupported(
        asked, claude_caps(), backend="anthropic", model="claude-opus-4-6"
    )
    assert kept == asked


def test_lup_server_config_narrows_by_isinstance() -> None:
    """The Claude server conversion narrows by type, not a hasattr probe."""
    from lup.adapters.claude.options import server_to_claude

    entry = create_mcp_server("notes", tools=[])
    converted = server_to_claude(entry)
    assert converted.get("type") == "sdk"
    assert isinstance(entry, LupMcpServerConfig)
