"""The reviewer never inspects the backend (reflect.run_reviewer).

Backend concerns live only in the adapter layer: ``run_reviewer`` asks for the
full reviewer setup — file tools, a thinking budget, a turn cap — on every
backend, and ``query`` (not the template tool) decides what the chosen backend
can honor. These tests pin that the call shape is identical regardless of the
reviewer's model, so the tool carries no ``match`` on the backend.
"""

import pytest

from lup.types import LupResponse, LupTextBlock
from lup_template.agent.tools import reflect


def make_input() -> reflect.ReflectInput:
    return reflect.ReflectInput(
        assessment="solid work",
        confidence=0.7,
        tool_audit="all tools fine",
        process_reflection="smooth",
    )


class QueryRecorder:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    async def __call__(self, prompt: str, **kwargs: object) -> LupResponse:
        self.kwargs = {"prompt": prompt, **kwargs}
        return LupResponse(blocks=[LupTextBlock(text="critique")])


async def test_reviewer_asks_for_full_options_on_claude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = QueryRecorder()
    monkeypatch.setattr(reflect, "query", recorder)

    critique = await reflect.run_reviewer(make_input(), None, model="claude-sonnet-4-6")

    assert critique == "critique"
    assert recorder.kwargs["tools"] == ["Read", "Glob", "Grep", "WebFetch"]
    assert recorder.kwargs["max_turns"] == 5


async def test_reviewer_call_shape_is_backend_agnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-Claude reviewer gets the same full option set — query() degrades it."""
    claude = QueryRecorder()
    monkeypatch.setattr(reflect, "query", claude)
    await reflect.run_reviewer(make_input(), None, model="claude-sonnet-4-6")

    gpt = QueryRecorder()
    monkeypatch.setattr(reflect, "query", gpt)
    await reflect.run_reviewer(make_input(), None, model="gpt-5.5")

    assert set(claude.kwargs) == set(gpt.kwargs)
    for claude_only in ("tools", "max_turns", "permission_mode", "max_thinking_tokens"):
        assert gpt.kwargs[claude_only] == claude.kwargs[claude_only]
