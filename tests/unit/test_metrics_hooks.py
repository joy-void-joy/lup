"""tracked decorator metrics and the nudge/capture PostToolUse hooks."""

from collections.abc import Iterator
from typing import cast

import pytest

from claude_agent_sdk.types import (
    HookContext,
    PostToolUseHookInput,
    SyncHookJSONOutput,
)

from lup.hooks import create_capture_hook, create_nudge_hook
from lup.metrics import get_metrics_summary, reset_metrics, tracked


@pytest.fixture(autouse=True)
def clean_metrics() -> Iterator[None]:
    reset_metrics()
    yield
    reset_metrics()


def post_input(tool_name: str, tool_response: object = None) -> PostToolUseHookInput:
    return PostToolUseHookInput(
        hook_event_name="PostToolUse",
        session_id="s",
        transcript_path="",
        cwd="",
        tool_name=tool_name,
        tool_input={},
        tool_response=tool_response,
        tool_use_id="t-1",
    )


# ---------------------------------------------------------------------------
# tracked decorator
# ---------------------------------------------------------------------------


async def test_tracked_records_calls_and_raised_errors() -> None:
    @tracked("my_tool")
    async def my_tool(value: int) -> dict[str, int]:
        if value < 0:
            raise ValueError("bad")
        return {"value": value}

    await my_tool(1)
    await my_tool(2)
    with pytest.raises(ValueError):
        await my_tool(-1)

    summary = get_metrics_summary()
    by_tool = summary["by_tool"]["my_tool"]
    assert by_tool["call_count"] == 3
    assert by_tool["error_count"] == 1
    assert summary["total_tool_calls"] == 3


async def test_tracked_flags_is_error_results() -> None:
    @tracked()
    async def soft_fail() -> dict[str, bool]:
        return {"is_error": True}

    await soft_fail()
    by_tool = get_metrics_summary()["by_tool"]["soft_fail"]
    assert by_tool["call_count"] == 1
    assert by_tool["error_count"] == 1


# ---------------------------------------------------------------------------
# nudge hook
# ---------------------------------------------------------------------------


async def test_nudge_hook_injects_system_message_for_matching_tool() -> None:
    def check(_data: PostToolUseHookInput) -> str | None:
        return "try the structured API instead"

    config = create_nudge_hook({"WebFetch": check})
    hook = config["PostToolUse"][0].hooks[0]

    nudged = cast(
        SyncHookJSONOutput,
        await hook(post_input("WebFetch"), None, HookContext(signal=None)),
    )
    assert nudged.get("systemMessage") == "try the structured API instead"

    skipped = cast(
        SyncHookJSONOutput,
        await hook(post_input("OtherTool"), None, HookContext(signal=None)),
    )
    assert skipped == {}


async def test_nudge_check_returning_none_skips_the_nudge() -> None:
    config = create_nudge_hook({"WebFetch": lambda _data: None})
    hook = config["PostToolUse"][0].hooks[0]

    out = cast(
        SyncHookJSONOutput,
        await hook(post_input("WebFetch"), None, HookContext(signal=None)),
    )
    assert out == {}


# ---------------------------------------------------------------------------
# capture hook
# ---------------------------------------------------------------------------


async def test_capture_hook_collects_only_matching_tool_data() -> None:
    def extract(data: PostToolUseHookInput) -> list[str]:
        return [str(data["tool_response"])]

    config, captured = create_capture_hook("WebSearch", extract)
    hook = config["PostToolUse"][0].hooks[0]

    await hook(post_input("WebSearch", "r1"), None, HookContext(signal=None))
    await hook(post_input("Other", "ignored"), None, HookContext(signal=None))
    await hook(post_input("WebSearch", "r2"), None, HookContext(signal=None))

    assert captured == ["r1", "r2"]
