"""Adapter capability declarations and the query() budget guard.

The capability contract only has value if the declarations stay truthful:
these tests pin the entries that other code branches on (stop_event for
the completion guard, cost_reporting for budget wiring) and the
instance-dependent Codex cost entry.
"""

import pytest
from claude_agent_sdk import ClaudeAgentOptions

from lup.adapters.claude import ClaudeAdapter
from lup.adapters.codex import CodexAdapter, per_mtok_usage_cost
from lup.adapters.common import query
from lup.adapters.openai_compat import OpenAICompatibleAdapter


def test_claude_capabilities_full_tier() -> None:
    caps = ClaudeAdapter(ClaudeAgentOptions()).capabilities
    assert caps.hooks
    assert caps.native_subagents
    assert caps.streaming == "live"
    assert caps.stop_event
    assert caps.cost_reporting == "native"
    assert caps.interrupt
    assert caps.background_tools
    assert caps.realtime == "in_process"
    assert not caps.turn_timeout


def test_codex_capabilities_intersection_tier() -> None:
    caps = CodexAdapter(model="gpt-5.5", system_prompt="").capabilities
    assert not caps.hooks
    assert not caps.native_subagents
    assert not caps.stop_event
    assert not caps.interrupt
    assert caps.streaming == "post_hoc"
    assert not caps.background_tools
    assert caps.realtime == "relay"
    assert caps.turn_timeout


def test_codex_cost_reporting_depends_on_rates() -> None:
    bare = CodexAdapter(model="gpt-5.5", system_prompt="")
    assert bare.capabilities.cost_reporting == "none"

    priced = CodexAdapter(
        model="gpt-5.5",
        system_prompt="",
        max_budget_usd=1.0,
        usage_cost=per_mtok_usage_cost(input_usd=1.0, output_usd=2.0),
    )
    assert priced.capabilities.cost_reporting == "rates"


def test_openai_compat_inherits_codex_capabilities() -> None:
    caps = OpenAICompatibleAdapter(model="glm-4").capabilities
    assert not caps.hooks
    assert caps.streaming == "post_hoc"


async def test_query_budget_guard_explains_oneshot_limit() -> None:
    with pytest.raises(ValueError, match="one-shot"):
        await query("hi", model="gpt-5.5", max_budget_usd=1.0)


async def test_query_claude_only_options_still_rejected() -> None:
    with pytest.raises(ValueError, match="max_turns"):
        await query("hi", model="gpt-5.5", max_turns=3)
