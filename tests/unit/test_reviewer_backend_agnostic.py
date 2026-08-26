# lup: ignore[dict-str-object, bare-object, set-shape]
# Monkeypatch fixtures intentionally accept and record arbitrary call boundaries.
"""Reviewer composition receives a factory, a prompt, and a strict output model."""

from types import SimpleNamespace

import pytest

from lup.reflect import ReviewResult, ReviewVerdict
from lup_template.agent import core
from lup_template.agent.tools import reflect


class StubClient:
    """A client that records the one turn the reviewer runs on it.

    Stands in for `Client` structurally rather than by subclassing it: what
    the reviewer needs is `query`, and a stub that answered more than that
    would be asserting the reviewer stays inside a surface it never touches.
    """

    def __init__(self, requested: dict[str, object]) -> None:
        self.requested = requested

    async def query(self, prompt: object, output_type: object = None) -> object:
        self.requested.update(factory=self, prompt=prompt, output_type=output_type)
        return SimpleNamespace(
            output=ReviewResult(verdict=ReviewVerdict.approve, assessment="critique")
        )


def make_input() -> reflect.ReflectInput:
    return reflect.ReflectInput(
        assessment="solid work",
        confidence=0.7,
        tool_audit="all tools fine",
        process_reflection="smooth",
    )


async def test_reviewer_uses_explicit_factory_and_typed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: dict[str, object] = {}
    requested: dict[str, object] = {}

    # A stub client rather than a patched module function: dispatch is the
    # method now, so what the reviewer is handed is what answers it, and the
    # test intercepts by supplying that rather than by reaching around it.
    marker = StubClient(requested)

    def build(**kwargs: object) -> object:
        built.update(kwargs)
        return marker

    monkeypatch.setattr(core, "build_auxiliary_factory", build)

    result = await reflect.run_reviewer(make_input(), None, model="review-model")

    assert result is not None
    assert result.assessment == "critique"
    assert built["model"] == "review-model"
    assert built["tools"] == ["Read", "Glob", "Grep", "WebFetch"]
    assert requested["factory"] is marker
    assert requested["output_type"] is ReviewResult
    assert isinstance(requested["prompt"], str)


async def test_reviewer_factory_shape_does_not_depend_on_model_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def build(**kwargs: object) -> object:
        calls.append(kwargs)
        return StubClient({})

    monkeypatch.setattr(core, "build_auxiliary_factory", build)

    await reflect.run_reviewer(make_input(), None, model="claude-model")
    await reflect.run_reviewer(make_input(), None, model="gpt-model")

    assert set(calls[0]) == set(calls[1])
    assert calls[0]["tools"] == calls[1]["tools"]
