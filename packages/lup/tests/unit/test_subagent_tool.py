# lup: ignore[dict-get]
# External MCP ToolResponse dictionaries are test fixtures.
"""Subagent delegation is driven by an explicitly injected factory recipe."""

from contextlib import AbstractAsyncContextManager
from datetime import timedelta
from typing import Self, overload

from pydantic import BaseModel

from lup.orchestration.subagents import create_run_subagent_tool
from lup.providers.claude import ClaudeSession
from lup.sessions.events import (
    SessionId,
    SessionSummary,
    TurnIdentifiers,
    TurnId,
    TurnInput,
    TurnResult,
    TurnTextBlock,
)
from lup.sessions.layers import SessionLayers
from lup.sessions.surface import Agent
from lup.tools.mcp import ToolResponse
from lup.types import SubagentSpec, Usage

RESEARCHER = SubagentSpec(
    name="researcher",
    description="Researches questions",
    prompt="You research.",
    tools=["WebSearch"],
    model="fast",
)


class AnsweringAgent:
    """An agent whose one-shot answer is scripted, recording what it was asked."""

    def __init__(self) -> None:
        self.asked: list[str | TurnInput] = []

    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[ClaudeSession]:
        raise AssertionError(f"the tool asks one-shot and never opens ({resume})")

    @overload
    async def ask(self, prompt: str | TurnInput) -> TurnResult[None]: ...

    @overload
    async def ask[T: BaseModel](
        self, prompt: str | TurnInput, output: type[T]
    ) -> TurnResult[T]: ...

    async def ask[T: BaseModel](
        self, prompt: str | TurnInput, output: type[T] | None = None
    ) -> TurnResult[T] | TurnResult[None]:
        self.asked.append(prompt)
        return TurnResult[None](
            output=None,
            messages=[],
            blocks=[TurnTextBlock(text="findings")],
            usage=Usage(),
            duration=timedelta(),
            identifiers=TurnIdentifiers(
                session=SessionId(value="nested"), turn=TurnId(value="only")
            ),
        )

    async def sessions(self) -> list[SessionSummary]:
        return []

    def layered(self, layers: SessionLayers) -> Self:
        return self


def response_text(response: ToolResponse) -> str:
    return "".join(item.get("text", "") for item in response.get("content", []))


class TestRunSubagentTool:
    async def test_unknown_role_lists_available(self) -> None:
        tool = create_run_subagent_tool(
            [RESEARCHER], factory_recipe=lambda _spec: AnsweringAgent()
        )

        result = await tool.handler({"name": "ghost", "task": "x"})
        assert result.get("is_error") is True
        assert "researcher" in response_text(result)

    async def test_invalid_recipe_fails_loudly(self) -> None:
        def invalid(_spec: SubagentSpec) -> Agent:
            raise ValueError("model route is unavailable")

        tool = create_run_subagent_tool([RESEARCHER], factory_recipe=invalid)
        result = await tool.handler({"name": "researcher", "task": "x"})

        assert result.get("is_error") is True
        assert "model route is unavailable" in response_text(result)

    async def test_dispatches_the_task_to_the_selected_spec_s_agent(self) -> None:
        selected: list[SubagentSpec] = []
        answering = AnsweringAgent()

        def recipe(spec: SubagentSpec) -> Agent:
            selected.append(spec)
            return answering

        tool = create_run_subagent_tool([RESEARCHER], factory_recipe=recipe)
        result = await tool.handler({"name": "researcher", "task": "look this up"})

        assert result.get("is_error", False) is False
        assert "findings" in response_text(result)
        assert selected == [RESEARCHER]
        assert answering.asked == ["look this up"]
