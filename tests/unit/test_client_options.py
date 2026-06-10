"""query/build_client option handling and error-result emission.

Covers the silent-wrong-result paths: structured output requested
alongside pre-built options, keyword arguments silently dropped by
build_client, and error ResultMessages that previously vanished
without being printed or traced.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock

from lup.client import ResponseCollector, build_client, prepare_output_format
from lup.trace import TraceLogger


class Answer(BaseModel):
    answer: str


def test_output_type_computes_format_without_options() -> None:
    fmt = prepare_output_format(output_type=Answer, output_format=None, options=None)
    assert fmt == {"type": "json_schema", "schema": Answer.model_json_schema()}


def test_output_type_injected_into_prebuilt_options() -> None:
    options = ClaudeAgentOptions()
    fmt = prepare_output_format(output_type=Answer, output_format=None, options=options)
    assert fmt is None
    assert options.output_format == {
        "type": "json_schema",
        "schema": Answer.model_json_schema(),
    }


def test_conflict_with_preset_output_format_raises() -> None:
    options = ClaudeAgentOptions(output_format={"type": "json_schema", "schema": {}})
    with pytest.raises(ValueError, match="output_format"):
        prepare_output_format(output_type=Answer, output_format=None, options=options)


def test_explicit_format_wins_over_output_type() -> None:
    explicit = {"type": "json_schema", "schema": {"type": "object"}}
    fmt = prepare_output_format(
        output_type=Answer, output_format=explicit, options=None
    )
    assert fmt == explicit


def test_no_structured_output_requested_is_a_no_op() -> None:
    options = ClaudeAgentOptions()
    fmt = prepare_output_format(output_type=None, output_format=None, options=options)
    assert fmt is None
    assert options.output_format is None


async def test_build_client_rejects_kwargs_with_prebuilt_options() -> None:
    options = ClaudeAgentOptions()
    with pytest.raises(ValueError, match="model"):
        async with build_client(options=options, model="sonnet"):
            pass


# ---------------------------------------------------------------------------
# Error result emission
# ---------------------------------------------------------------------------


class FakeClient:
    """Stands in for ClaudeSDKClient: replays a scripted message stream."""

    def __init__(self, messages: list[object]) -> None:
        self.scripted = messages

    async def receive_response(self) -> AsyncIterator[object]:
        for message in self.scripted:
            yield message


async def test_error_result_is_traced_and_kept_before_raising(tmp_path: Path) -> None:
    error = ResultMessage(
        subtype="error",
        duration_ms=1,
        duration_api_ms=1,
        is_error=True,
        num_turns=1,
        session_id="s",
        result="budget exceeded",
    )
    progress = AssistantMessage(content=[TextBlock(text="working...")], model="m")
    client = cast(ClaudeSDKClient, FakeClient([progress, error]))
    trace = TraceLogger(trace_path=tmp_path / "t.md", title="T")
    collector = ResponseCollector(client, trace_logger=trace)

    with pytest.raises(RuntimeError, match="budget exceeded"):
        await collector.collect()

    assert collector.result is error
    assert collector.text == "working..."
    assert any("budget exceeded" in entry.content for entry in trace.entries)
