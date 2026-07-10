"""Behavioral pins for the consume-tracking refusal fence.

Refusal derives an engine's honored knobs from what its translation reads
(:mod:`lup.adapters.clients.refusal`). These tests pin the fence around
that mechanism: a translation that reads nothing refuses everything, bulk
reads raise instead of silently consuming every knob, and incidental
``repr``/``str`` record nothing.
"""

import pytest

from lup.adapters.clients.refusal import (
    INTENT_KNOBS,
    ConsumeTracker,
    refuse_unconsumed,
)
from lup.adapters.errors import UnsupportedOptionsError
from lup.adapters.options import LupAgentOptions


def all_knobs_options() -> LupAgentOptions:
    """Options with every intent knob set, so nothing is exempt from refusal."""
    return LupAgentOptions(
        model="claude-opus-4-6",
        max_turns=3,
        max_thinking_tokens=1024,
        permission_mode="bypassPermissions",
        tools=["Read"],
        reasoning_effort="high",
        max_budget_usd=1.0,
        turn_timeout_seconds=5.0,
    )


def test_noop_translation_refuses_every_set_knob() -> None:
    with pytest.raises(UnsupportedOptionsError) as excinfo:
        refuse_unconsumed("null-engine", all_knobs_options(), lambda _opts: "native")
    assert excinfo.value.fields == sorted(INTENT_KNOBS)


def test_bulk_dump_inside_translation_raises() -> None:
    with pytest.raises(RuntimeError, match="field-by-field"):
        refuse_unconsumed(
            "null-engine", all_knobs_options(), lambda tracked: tracked.model_dump()
        )


def test_model_dump_json_raises() -> None:
    tracker = ConsumeTracker.tracking(all_knobs_options())
    with pytest.raises(RuntimeError, match="field-by-field"):
        tracker.model_dump_json()


def test_iteration_raises() -> None:
    tracker = ConsumeTracker.tracking(all_knobs_options())
    with pytest.raises(RuntimeError, match="field-by-field"):
        dict(tracker)


def test_repr_and_str_record_nothing() -> None:
    tracker = ConsumeTracker.tracking(all_knobs_options())
    repr(tracker)
    str(tracker)
    assert not tracker.consumed
