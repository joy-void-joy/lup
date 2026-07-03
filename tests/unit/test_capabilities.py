"""Adapter capability declarations and the query() option degradation.

The capability contract only has value if the declarations stay truthful:
these tests pin the entries that other code branches on (stop_event for
the completion guard, cost_reporting for budget wiring) and the
instance-dependent Codex cost entry. They also pin that a one-shot query
degrades — rather than raises — when asked for options a weak backend cannot
honor, so a caller can express full intent and let the adapter layer keep what
it can.
"""

import pytest
from claude_agent_sdk import ClaudeAgentOptions

from lup.adapters import registry
from lup.adapters.claude.adapter import ClaudeAdapter
from lup.adapters.codex.adapter import CodexAdapter, per_mtok_usage_cost
from lup.adapters.common import query
from lup.adapters.codex.openai_compat import OpenAICompatibleAdapter
from tests.unit.conftest import RecordingOneShot


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


async def test_query_drops_oneshot_budget_on_weak_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A one-shot budget the Codex runtime can't enforce is dropped, not raised."""
    engine = RecordingOneShot()
    monkeypatch.setitem(registry.ONE_SHOT_BUILDERS, "openai", engine)

    response = await query("hi", model="gpt-5.5", max_budget_usd=1.0)

    assert response.text == "ok"
    assert engine.ran[0].max_budget_usd is None


async def test_query_drops_claude_only_options_on_weak_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude-only options degrade away on a backend without hooks/turn caps."""
    engine = RecordingOneShot()
    monkeypatch.setitem(registry.ONE_SHOT_BUILDERS, "openai", engine)

    await query("hi", model="gpt-5.5", max_turns=3, tools=["Read"])

    assert engine.ran[0].options.max_turns is None
    assert engine.ran[0].options.tools is None
