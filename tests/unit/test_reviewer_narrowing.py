"""Reviewer option narrowing by model backend (reflect.run_reviewer).

The config docs say "override the reviewer model to stay single-provider".
That only holds if run_reviewer stops passing Claude-only options to
non-Anthropic backends — query() rejects tools/max_turns/permission_mode
there. These tests pin the narrowed call shape on both routes.
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


async def test_anthropic_reviewer_keeps_full_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = QueryRecorder()
    monkeypatch.setattr(reflect, "query", recorder)

    critique = await reflect.run_reviewer(
        make_input(), None, model="claude-sonnet-4-6"
    )

    assert critique == "critique"
    assert recorder.kwargs["tools"] == ["Read", "Glob", "Grep", "WebFetch"]
    assert recorder.kwargs["max_turns"] == 5


async def test_non_claude_reviewer_drops_claude_only_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = QueryRecorder()
    monkeypatch.setattr(reflect, "query", recorder)

    critique = await reflect.run_reviewer(make_input(), None, model="gpt-5.5")

    assert critique == "critique"
    for claude_only in ("tools", "max_turns", "permission_mode", "max_thinking_tokens"):
        assert claude_only not in recorder.kwargs
