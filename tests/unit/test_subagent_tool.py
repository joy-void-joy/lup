"""Tests for the run_subagent delegation tool.

The tool exists so non-Claude engines get real subagent delegation
from the same SubagentSpec list Claude uses natively. These tests pin
the failure modes: unknown roles, and specs whose tools the engine
cannot provide (the tool fails loudly).
"""

import pytest

import lup.subagents
from lup.mcp import ToolResponse
from lup.subagents import create_run_subagent_tool
from lup.types import JsonValue, LupResponse, LupTextBlock, SubagentSpec

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

        result = await tool.handler({"name": "ghost", "task": "x"})
        assert result.get("is_error") is True
        assert "researcher" in response_text(result)

    async def test_tools_on_non_claude_backend_fail_loudly(self) -> None:
        tool = create_run_subagent_tool([GPT_ANALYST], default_model="haiku")

        result = await tool.handler({"name": "gpt-analyst", "task": "x"})
        assert result.get("is_error") is True
        assert "tools" in response_text(result)

    async def test_dispatches_query_with_spec(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, JsonValue] = {}

        async def fake_query(prompt: str, **kwargs: JsonValue) -> LupResponse:
            captured["prompt"] = prompt
            captured.update(kwargs)
            return LupResponse(blocks=[LupTextBlock(text="findings")])

        monkeypatch.setattr(lup.subagents, "query", fake_query)
        tool = create_run_subagent_tool([RESEARCHER], default_model="opus")

        result = await tool.handler({"name": "researcher", "task": "look this up"})
        assert result.get("is_error", False) is False
        assert "findings" in response_text(result)
        assert captured["prompt"] == "look this up"
        assert captured["model"] == "haiku"
        assert captured["system_prompt"] == "You research."
        assert captured["tools"] == ["WebSearch"]

    async def test_modelless_spec_inherits_default_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, JsonValue] = {}

        async def fake_query(prompt: str, **kwargs: JsonValue) -> LupResponse:
            captured["prompt"] = prompt
            captured.update(kwargs)
            return LupResponse(blocks=[LupTextBlock(text="adapted")])

        monkeypatch.setattr(lup.subagents, "query", fake_query)
        tool = create_run_subagent_tool([INHERITOR], default_model="gpt-5.5")

        result = await tool.handler({"name": "inheritor", "task": "go"})
        assert result.get("is_error", False) is False
        assert captured["model"] == "gpt-5.5"
