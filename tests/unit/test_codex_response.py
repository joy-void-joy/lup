# lup: ignore[bare-object, cast]
# Test fixtures and assertions construct these shapes deliberately.
"""Codex response assembly.

build_lup_response is where Codex turns become portable lup responses:
structured-output parsing must degrade (not raise) on non-JSON text and
the session id must ride along. CodexSession.send must stamp wall-clock
duration — the SDK reports tokens but no duration. (The post-hoc stream
this engine rides is the composed client's replay path, pinned in
``test_composed_client.py``.)
"""

from typing import TYPE_CHECKING, cast

from openai_codex.generated.v2_all import ThreadTokenUsage, TokenUsageBreakdown

from lup.adapters.clients.codex.sessions import CodexSession
from lup.adapters.clients.codex.messages import build_lup_response
from lup.types import JsonObject

if TYPE_CHECKING:
    from openai_codex import AsyncThread, TurnResult


def usage_for_turn(input_tokens: int, output_tokens: int) -> ThreadTokenUsage:
    breakdown = TokenUsageBreakdown(
        cached_input_tokens=0,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=0,
        total_tokens=input_tokens + output_tokens,
    )
    return ThreadTokenUsage(last=breakdown, total=breakdown, model_context_window=None)


class FakeTurnResult:
    """Minimal TurnResult stand-in: no items, scripted final_response."""

    def __init__(self, final_response: str | None) -> None:
        self.items: list[object] = []
        self.final_response = final_response
        self.usage = usage_for_turn(10, 5)


class FakeThread:
    """AsyncThread stand-in returning a scripted final response."""

    def __init__(self, final_response: str | None) -> None:
        self.id = "thread-fake"
        self.final_response = final_response

    async def run(
        self,
        prompt: str,
        *,
        effort: object = None,
        output_schema: object = None,
    ) -> FakeTurnResult:
        _ = (prompt, effort, output_schema)
        return FakeTurnResult(self.final_response)


SCHEMA: JsonObject = {"type": "object"}


def test_structured_output_parses_valid_json() -> None:
    result = cast("TurnResult", FakeTurnResult('{"answer": 42}'))

    response = build_lup_response(result, output_schema=SCHEMA, session_id="s1")

    assert response.result is not None
    assert response.result.structured_output == {"answer": 42}
    assert response.session_id == "s1"


def test_structured_output_degrades_on_non_json() -> None:
    result = cast("TurnResult", FakeTurnResult("sorry, plain prose"))

    response = build_lup_response(result, output_schema=SCHEMA)

    assert response.result is not None
    assert response.result.structured_output is None
    assert response.result.result == "sorry, plain prose"


def test_no_schema_means_no_parse_attempt() -> None:
    result = cast("TurnResult", FakeTurnResult('{"answer": 42}'))

    response = build_lup_response(result)

    assert response.result is not None
    assert response.result.structured_output is None


async def test_send_stamps_wall_clock_duration() -> None:
    conv = CodexSession(cast("AsyncThread", FakeThread("ok")))

    response = await conv.send("task")

    assert response.result is not None
    assert response.result.duration_ms is not None
    assert response.result.duration_ms >= 0
