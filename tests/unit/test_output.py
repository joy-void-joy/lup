"""Tests for the submit_output finalization tool and completion guard.

The output tool is the SDK-agnostic finalization mechanism: validation
and reflection-gating happen inside the handler, so these tests exercise
the enforcement paths an agent actually hits — premature submission,
invalid payloads, resubmission, and the stop guard's bounded retries.
"""

from pathlib import Path
from typing import cast

from pydantic import BaseModel, Field

from lup.hooks import LupHookInput, create_completion_guard
from lup.mcp import ToolResponse
from lup.workspace.output import create_output_tool, output_path, read_output
from lup.reflect import ReflectionGate


class DemoOutput(BaseModel):
    summary: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


def response_text(response: ToolResponse) -> str:
    return "".join(item.get("text", "") for item in response.get("content", []))


class TestSubmitOutput:
    async def test_rejects_submission_until_reflected(self, tmp_path: Path) -> None:
        gate = ReflectionGate()
        kit = create_output_tool(
            DemoOutput,
            session_dir=tmp_path,
            gate=gate,
            reflection_tool_name="review",
        )
        tool = kit["tools"][0]

        denied = cast(ToolResponse, await tool.handler({"summary": "done"}))
        assert denied.get("is_error") is True
        assert "review" in response_text(denied)
        assert not kit["output_path"].exists()

        gate.mark_reflected()
        accepted = cast(ToolResponse, await tool.handler({"summary": "done"}))
        assert accepted.get("is_error", False) is False
        saved = read_output(tmp_path, DemoOutput)
        assert saved is not None
        assert saved.summary == "done"

    async def test_invalid_payload_is_retriable(self, tmp_path: Path) -> None:
        kit = create_output_tool(DemoOutput, session_dir=tmp_path)
        tool = kit["tools"][0]

        invalid = cast(
            ToolResponse, await tool.handler({"summary": "x", "confidence": 7})
        )
        assert invalid.get("is_error") is True
        assert "confidence" in response_text(invalid)
        assert not kit["output_path"].exists()

        fixed = cast(
            ToolResponse, await tool.handler({"summary": "x", "confidence": 0.7})
        )
        assert fixed.get("is_error", False) is False
        assert kit["output_path"].exists()

    async def test_resubmission_overwrites(self, tmp_path: Path) -> None:
        kit = create_output_tool(DemoOutput, session_dir=tmp_path)
        tool = kit["tools"][0]

        await tool.handler({"summary": "first"})
        await tool.handler({"summary": "second"})

        saved = read_output(tmp_path, DemoOutput)
        assert saved is not None
        assert saved.summary == "second"

    def test_read_output_handles_absent_and_corrupt_files(self, tmp_path: Path) -> None:
        assert read_output(tmp_path, DemoOutput) is None

        output_path(tmp_path).write_text("{not json", encoding="utf-8")
        assert read_output(tmp_path, DemoOutput) is None


class TestCompletionGuard:
    async def test_blocks_until_output_exists(self, tmp_path: Path) -> None:
        flag = tmp_path / "output.json"
        hooks = create_completion_guard(
            flag.exists, output_tool_name="submit_output", max_blocks=3
        )
        hook = hooks.stop[0].hook
        stop_event = LupHookInput(event="Stop")

        blocked = await hook(stop_event)
        assert blocked.decision == "block"
        assert "submit_output" in blocked.reason

        flag.write_text("{}", encoding="utf-8")
        allowed = await hook(stop_event)
        assert allowed.decision is None

    async def test_gives_up_after_max_blocks(self) -> None:
        hooks = create_completion_guard(lambda: False, max_blocks=2)
        hook = hooks.stop[0].hook
        stop_event = LupHookInput(event="Stop")

        first = await hook(stop_event)
        second = await hook(stop_event)
        third = await hook(stop_event)
        assert first.decision == "block"
        assert second.decision == "block"
        assert third.decision is None

    async def test_ignores_non_stop_events(self) -> None:
        hooks = create_completion_guard(lambda: False)
        hook = hooks.stop[0].hook

        result = await hook(LupHookInput(event="PreToolUse"))
        assert result.decision is None
