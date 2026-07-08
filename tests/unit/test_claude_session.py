"""ClaudeSession and ClaudeResponseCollector against a scripted fake client.

The conversation layer owns response assembly and error propagation —
exactly where backends quietly diverge. These tests script SDK message
sequences and pin block partitioning, the is_error raise, the
missing-result raise, usage normalization degrading to None, and the
streamed event ordering.
"""

from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import cast

import pytest
from claude_agent_sdk import ClaudeSDKClient
from claude_agent_sdk.types import (
    AssistantMessage,
    Message,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from lup.adapters.clients.claude.client import ClaudeSession
from lup.adapters.clients.claude.collector import ClaudeUsageNormalizer
from lup.types import (
    JsonValue,
    LupDoneEvent,
    LupTextEvent,
    LupThinkingEvent,
    LupToolResultEvent,
    LupToolUseEvent,
    Usage,
)


class FakeClient:
    """Scripted stand-in for ClaudeSDKClient (duck-typed)."""

    def __init__(self, messages: list[Message]) -> None:
        self.messages = messages
        self.prompts: list[str] = []

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)

    async def receive_response(self) -> AsyncIterator[Message]:
        for message in self.messages:
            yield message

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def result_message(
    *,
    is_error: bool = False,
    result: str | None = "done",
    usage: Mapping[str, JsonValue] | None = None,
) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1200,
        duration_api_ms=1000,
        is_error=is_error,
        num_turns=1,
        session_id="sess-1",
        total_cost_usd=0.01,
        usage=dict(usage) if usage is not None else None,
        result=result,
    )


def session(
    messages: list[Message],
    usage_normalizer: ClaudeUsageNormalizer | None = None,
) -> tuple[ClaudeSession, FakeClient]:
    fake = FakeClient(messages)
    client = cast(ClaudeSDKClient, fake)
    if usage_normalizer is None:
        return ClaudeSession(client), fake
    return ClaudeSession(client, usage_normalizer=usage_normalizer), fake


SCRIPT: list[Message] = [
    AssistantMessage(
        content=[
            TextBlock(text="looking at it"),
            ToolUseBlock(id="t1", name="Read", input={"file_path": "x.py"}),
        ],
        model="claude-opus-4-6",
    ),
    UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="contents")]),
    AssistantMessage(content=[TextBlock(text="answer")], model="claude-opus-4-6"),
    result_message(usage={"input_tokens": 10, "output_tokens": 5}),
]


async def test_send_partitions_blocks_and_collects_result() -> None:
    conv, fake = session(SCRIPT)

    response = await conv.send("the task")

    assert fake.prompts == ["the task"]
    assert response.text == "looking at it\n\nanswer"
    assert len(response.blocks) == 3
    assert len(response.tool_results) == 1
    assert len(response.messages) == 3
    assert response.session_id == "sess-1"
    assert response.result is not None
    assert response.result.total_cost_usd == 0.01
    assert response.result.duration_ms == 1200
    assert response.result.usage == Usage(input_tokens=10, output_tokens=5)


async def test_send_raises_on_error_result() -> None:
    conv, fake = session([result_message(is_error=True, result="exploded")])
    _ = fake

    with pytest.raises(RuntimeError, match="exploded"):
        await conv.send("task")


async def test_send_raises_when_no_result_arrives() -> None:
    conv, fake = session([AssistantMessage(content=[TextBlock(text="hi")], model="m")])
    _ = fake

    with pytest.raises(RuntimeError, match="No result"):
        await conv.send("task")


async def test_broken_usage_normalizer_degrades_to_none() -> None:
    def broken(raw: Mapping[str, JsonValue]) -> Usage | None:
        _ = raw
        raise KeyError("nope")

    conv, fake = session(SCRIPT, usage_normalizer=broken)
    _ = fake

    response = await conv.send("task")

    assert response.result is not None
    assert response.result.usage is None


async def test_run_streamed_event_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_agent_sdk import ClaudeAgentOptions

    from lup.adapters.clients.claude.client import ClaudeClient

    script: list[Message] = [
        AssistantMessage(
            content=[
                ThinkingBlock(thinking="hmm", signature="sig"),
                TextBlock(text="hello"),
                ToolUseBlock(id="t1", name="Read", input={}),
            ],
            model="m",
        ),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="data")]),
        result_message(),
    ]
    fake = FakeClient(script)
    monkeypatch.setattr("claude_agent_sdk.ClaudeSDKClient", lambda options: fake)

    adapter = ClaudeClient(ClaudeAgentOptions())
    events = [event async for event in adapter.stream("go")]

    assert isinstance(events[0], LupThinkingEvent)
    assert isinstance(events[1], LupTextEvent)
    assert isinstance(events[2], LupToolUseEvent)
    assert isinstance(events[3], LupToolResultEvent)
    assert isinstance(events[4], LupDoneEvent)
    assert len(events[4].blocks) == 3


async def test_session_id_tracks_the_result() -> None:
    conv, fake = session(SCRIPT)
    _ = fake

    assert conv.id is None
    await conv.send("task")
    assert conv.id == "sess-1"


async def test_session_resume_threads_the_saved_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resume= reaches the SDK options and seeds Session.id — without
    mutating the client's own options."""
    from claude_agent_sdk import ClaudeAgentOptions

    from lup.adapters.clients.claude.client import ClaudeClient

    opened: list[ClaudeAgentOptions] = []

    def fake_sdk_client(options: ClaudeAgentOptions) -> FakeClient:
        opened.append(options)
        return FakeClient([result_message()])

    monkeypatch.setattr("claude_agent_sdk.ClaudeSDKClient", fake_sdk_client)

    client = ClaudeClient(ClaudeAgentOptions())
    async with client.session(resume="sess-42") as conv:
        assert conv.id == "sess-42"

    assert opened[0].resume == "sess-42"
    assert client.options.resume is None


async def test_collector_state_after_collect() -> None:
    from lup.adapters.clients.claude.collector import ClaudeResponseCollector

    fake = FakeClient(SCRIPT)
    collector = ClaudeResponseCollector(cast(ClaudeSDKClient, fake))

    response = await collector.collect()

    assert response.session_id == "sess-1"
    assert response.text == "looking at it\n\nanswer"
    assert len(response.blocks) == 3
    assert len(response.tool_results) == 1
    assert collector.result is not None
    assert collector.result.session_id == "sess-1"


async def test_collector_raises_mid_iteration_on_error() -> None:
    from lup.adapters.clients.claude.collector import ClaudeResponseCollector

    fake = FakeClient([result_message(is_error=True, result="boom")])
    collector = ClaudeResponseCollector(cast(ClaudeSDKClient, fake))

    with pytest.raises(RuntimeError, match="boom"):
        await collector.collect()


async def test_error_result_is_traced_and_kept_before_raising(tmp_path: Path) -> None:
    """An error result must land in the trace and collector state, then raise."""
    from lup.adapters.clients.claude.collector import ClaudeResponseCollector
    from lup.telemetry.trace import TraceLogger

    progress = AssistantMessage(content=[TextBlock(text="working...")], model="m")
    error = result_message(is_error=True, result="budget exceeded")
    conv, fake = session([progress, error])
    _ = fake
    trace = TraceLogger(trace_path=tmp_path / "t.md", title="T")
    collector = ClaudeResponseCollector(conv.client, trace_logger=trace)

    with pytest.raises(RuntimeError, match="budget exceeded"):
        await collector.collect()

    assert collector.result is error
    assert collector.text == "working..."
    assert any("budget exceeded" in entry.content for entry in trace.entries)
