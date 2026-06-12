"""Tests for the run_subagent delegation tool and query() option honesty.

The tool exists so non-Claude backends get real subagent delegation
from the same SubagentSpec list Claude uses natively. These tests pin
the failure modes: unknown roles, specs whose tools the backend cannot
provide, and query() refusing Claude-only options on other backends.
"""

from typing import cast

import pytest

import lup.subagents
from lup.adapters.common import query
from lup.mcp import ToolResponse
from lup.subagents import create_run_subagent_tool
from lup.types import LupResponse, LupTextBlock, SubagentSpec

RESEARCHER = SubagentSpec(
    name="researcher",
    description="Researches questions",
    prompt="You research.",
    tools=["WebSearch"],
    model="haiku",
)

GPT_ANALYST = SubagentSpec(
    name="gpt-analyst",
    description="Analyzes with a GPT model",
    prompt="You analyze.",
    tools=["Read"],
    model="gpt-5.5",
)

INHERITOR = SubagentSpec(
    name="inheritor",
    description="Pins no model; runs on whatever the session runs",
    prompt="You adapt.",
)


def response_text(response: ToolResponse) -> str:
    return "".join(item.get("text", "") for item in response.get("content", []))


class TestRunSubagentTool:
    async def test_unknown_role_lists_available(self) -> None:
        tool = create_run_subagent_tool([RESEARCHER], default_model="haiku")

        result = cast(ToolResponse, await tool.handler({"name": "ghost", "task": "x"}))
        assert result.get("is_error") is True
        assert "researcher" in response_text(result)

    async def test_tools_on_non_claude_backend_fail_loudly(self) -> None:
        tool = create_run_subagent_tool([GPT_ANALYST], default_model="haiku")

        result = cast(
            ToolResponse, await tool.handler({"name": "gpt-analyst", "task": "x"})
        )
        assert result.get("is_error") is True
        assert "tools" in response_text(result)

    async def test_dispatches_query_with_spec(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        async def fake_query(prompt: str, **kwargs: object) -> LupResponse:
            captured["prompt"] = prompt
            captured.update(kwargs)
            return LupResponse(blocks=[LupTextBlock(text="findings")])

        monkeypatch.setattr(lup.subagents, "query", fake_query)
        tool = create_run_subagent_tool([RESEARCHER], default_model="opus")

        result = cast(
            ToolResponse,
            await tool.handler({"name": "researcher", "task": "look this up"}),
        )
        assert result.get("is_error", False) is False
        assert "findings" in response_text(result)
        assert captured["prompt"] == "look this up"
        assert captured["model"] == "haiku"
        assert captured["system_prompt"] == "You research."
        assert captured["tools"] == ["WebSearch"]

    async def test_modelless_spec_inherits_default_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[
            str, object
        ] = {}  # claude: ignore — heterogeneous kwargs capture

        async def fake_query(prompt: str, **kwargs: object) -> LupResponse:
            captured["prompt"] = prompt
            captured.update(kwargs)
            return LupResponse(blocks=[LupTextBlock(text="adapted")])

        monkeypatch.setattr(lup.subagents, "query", fake_query)
        tool = create_run_subagent_tool([INHERITOR], default_model="gpt-5.5")

        result = cast(
            ToolResponse, await tool.handler({"name": "inheritor", "task": "go"})
        )
        assert result.get("is_error", False) is False
        assert captured["model"] == "gpt-5.5"


class TestQueryOptionHonesty:
    async def test_claude_only_options_raise_on_other_backends(self) -> None:
        with pytest.raises(ValueError, match="max_budget_usd"):
            await query("hi", model="gpt-5.5", max_budget_usd=1.0)

    async def test_tools_raise_on_openai_compatible_backend(self) -> None:
        with pytest.raises(ValueError, match="tools"):
            await query("hi", model="llama-3-70b", tools=["Read"])
