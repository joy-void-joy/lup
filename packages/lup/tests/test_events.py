"""lup's events, one class each: their names on a wire, read back by them, and each runtime spelling every one of a session's."""

from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from lup.adapters.claude.terminal import spelled as claude_spelled
from lup.adapters.codex.terminal import spelled as codex_spelled
from lup.events import (
    CallStarted,
    ConversationEnded,
    EventName,
    Publishing,
    SessionEvent,
    Told,
    events,
)
from lup.publishing import Part, Post


def test_an_event_s_name_on_a_wire_is_its_class_s() -> None:
    assert [each.named() for each in events()] == [
        "launched",
        "stopped",
        "publishing",
        "session-started",
        "turn-started",
        "call-started",
        "call-finished",
        "turn-ended",
        "conversation-ended",
    ]


def test_an_event_crosses_a_wire_and_is_read_back_by_its_name() -> None:
    told = TypeAdapter[Told](Told)
    for event in [
        CallStarted(call="c1", tool="Bash"),
        ConversationEnded(),
        Publishing(
            published=Post(what="an issue", parts=[Part(name="title", text="x")])
        ),
    ]:
        raw = told.dump_json(event)
        assert told.validate_json(raw) == event
        assert type(told.validate_json(raw)) is type(event)
    assert told.dump_python(ConversationEnded()) == {"kind": "conversation-ended"}


def test_a_name_that_isn_t_an_event_s_is_refused_naming_them() -> None:
    names = TypeAdapter[EventName](EventName)
    assert names.validate_python("stopped") == "stopped"
    with pytest.raises(ValidationError, match="`stoped` isn't one of lup's events"):
        names.validate_python("stoped")


def test_each_runtime_spells_every_one_of_a_session_s_events() -> None:
    session: list[type[SessionEvent]] = list(get_args(SessionEvent.__value__))
    assert session == [each for each in events() if each in session]
    assert [claude_spelled(each) for each in session] == [
        ["SessionStart"],
        ["UserPromptSubmit"],
        ["PreToolUse"],
        ["PostToolUse", "PostToolUseFailure"],
        ["Stop", "StopFailure"],
        ["SubagentStop"],
    ]
    assert [codex_spelled(each) for each in session] == [
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "Stop",
        "SubagentStop",
    ]
