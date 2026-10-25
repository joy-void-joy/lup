"""The kept sessions as `lup-dev transcripts` prints them: the operator's words each after what it answered, the whole conversation, a search, and a session chosen."""

from datetime import UTC, datetime

import pytest

from lup_dev.host.records import Called, Said, Transcript
from lup_transcripts.environment import views


def session(
    entries: list[Said | Called], *, title: str | None = "lup-impl"
) -> Transcript:
    return Transcript(
        runtime="claude",
        session="c0fa70bc",
        title=title,
        entries=entries,
    )


def at(minute: int) -> datetime:
    return datetime(2026, 10, 17, 12, minute, tzinfo=UTC)


TALK = session(
    [
        Said(by="operator", text="Can we talk?", at=at(0)),
        Said(by="agent", text="Looking first.", at=at(1)),
        Called(tool="Read", at=at(1)),
        Called(tool="Read", at=at(1)),
        Said(by="agent", text="Two options:\n1. queue\n2. agents", at=at(2)),
        Said(by="operator", text="1->yes\n2->later", at=at(3)),
    ]
)


def test_answered_shows_each_of_the_operators_words_after_what_it_answered() -> None:
    shown = views.answered(TALK)
    assert "`lup-impl` (claude c0fa70bc)" in shown
    assert "(the session's first words)\n  you:\n    Can we talk?" in shown
    assert (
        "  answering the agent:\n    Two options:\n    1. queue\n    2. agents\n"
        "  you:\n    1->yes\n    2->later\n"
    ) in shown


def test_whole_folds_each_run_of_tool_calls_to_a_line() -> None:
    shown = views.whole(TALK)
    assert "the agent, " in shown
    assert "    Looking first.\n\n· called Read x2\n\nthe agent, " in shown


def test_found_gives_each_time_the_operator_said_every_word() -> None:
    other = session(
        [Said(by="operator", text="Nothing about it.", at=at(9))], title="other"
    )
    hit = views.found([other, TALK], ["LATER", "yes"])
    whole = views.found([other, TALK], ["LATER", "yes"], whole=True)
    missed = views.found([TALK], ["absent"])
    assert hit.startswith("`lup-impl` (claude c0fa70bc), ")
    assert "\n  answering: Two options:\n  you:\n    1->yes\n    2->later\n" in hit
    assert (
        "\n  answering:\n    Two options:\n    1. queue\n    2. agents\n  you:\n"
        "    1->yes\n    2->later\n"
    ) in whole
    assert "other" not in hit
    assert missed == "You never said 'absent' in a kept session.\n"


def test_a_session_is_chosen_by_its_id_its_ids_start_or_its_name() -> None:
    other = TALK.model_copy(update={"session": "c0ffee", "title": "other"})
    sessions = [TALK, other]
    assert views.chosen(sessions, "c0fa") == TALK
    assert views.chosen(sessions, "other") == other
    with pytest.raises(views.TranscriptError, match="several kept sessions are `c0f`"):
        views.chosen(sessions, "c0f")
    with pytest.raises(views.TranscriptError, match="no kept session is `zz`"):
        views.chosen(sessions, "zz")
