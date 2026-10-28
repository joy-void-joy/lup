"""The items one conversation exchanged, each with its line as a view of the conversation shows it, as the core words it (`inbox/lines.py`).

Ported from `Transcripts`' conversation tests, whose wording the core makes now:
`Transcripts` lays each line where it happened, and names no kind of item.
"""

from datetime import UTC, datetime
from pathlib import Path

from lup.blocks import OfAgent, Span
from lup_dev.inbox.protocol import Exchange, Exchanged, Pathed, exchanged
from lup_dev.inbox.store import (
    Answer,
    Answered,
    Citation,
    Conversation,
    Decided,
    Done,
    Flagged,
    HeldChange,
    Item,
    Letter,
    Message,
    Operator,
    Question,
    Reason,
    Review,
    Ruling,
    Superseded,
    Told,
    Unresolved,
    Withdrawn,
)


def at(minute: int) -> datetime:
    return datetime(2026, 10, 18, 10, minute, tzinfo=UTC)


SESSION = Conversation(repository=Path("/r.git"), runtime="claude", session="s1")
SURVEY = SESSION.model_copy(update={"agent": "a04"})
OPERATOR = Operator()
PATHS = [
    Pathed(conversation=SESSION, path="lup-impl"),
    Pathed(conversation=SURVEY, path="lup-impl/a04"),
]


def note(text: str, *, of: int | None = None, ending: bool = False) -> Message:
    return Message(kind="note", text=text, of=of, ending=ending)


def item(number: int, reason: Reason, minute: int, **fields: object) -> Item:
    """An item of the session's, sent to the operator unless `fields` say otherwise."""
    return Item.model_validate(
        {
            "number": number,
            "reason": reason,
            "sender": SESSION,
            "recipient": OPERATOR,
            "made": at(minute),
            **fields,
        }
    )


def listed(
    *items: Item, party: Conversation = SESSION, paths: list[Pathed] = PATHS
) -> Exchanged:
    """Return what `party` exchanged, each text saying whether it's as written or as told."""
    return exchanged(
        party,
        list(items),
        written=lambda each: f"written {each.number}",
        told=lambda each: f"told {each.number}",
        paths=paths,
    )


def said(each: Exchange) -> str:
    """Say an item's line as text."""
    return "".join(span.text for span in each.line)


def test_one_sent_says_what_it_is_whom_to_and_where_it_stands() -> None:
    held = item(
        55,
        HeldChange(
            text="Let the change land?",
            summary="AGENTS.md: the operator's",
            worktree=Path("/w"),
            key="k",
        ),
        12,
        state=Decided(at=at(13), approved=False, comment="Not this file."),
    )
    flagged = Flagged(
        text="a.py landed, flagged.",
        summary="a.py is a new production file",
        worktree=Path("/w"),
        path=Path("a.py"),
    )
    sent = listed(
        held,
        item(56, Message(kind="problem", text="Stuck."), 12),
        item(57, note("Done."), 12, state=Done(at=at(13))),
        item(
            58, Question(text="Which?"), 12, state=Withdrawn(at=at(13), why="Found it.")
        ),
        # A flag and news wait on no one, as the review ranks them: unread, never waiting on you.
        item(59, flagged, 12),
        item(60, note("Assumed UTF-8."), 12),
        item(61, Question(text="Which?"), 12, state=Superseded(at=at(13), by=62)),
    )
    assert sent.received == []
    assert [said(each) for each in sent.sent] == [
        "→ @55 held change to you · declined",
        "→ @56 problem to you · waiting on you",
        "→ @57 note to you · read",
        "→ @58 question to you · withdrawn: Found it.",
        "→ @59 flagged write to you · unread",
        "→ @60 note to you · unread",
        "→ @61 question to you · superseded by @62",
    ]
    # Its text as it wrote it, and the operator's comment on deciding it beside.
    first = sent.sent[0]
    assert (first.text, first.comment, first.at) == (
        "written 55",
        "Not this file.",
        at(12),
    )


def test_one_sent_is_answered_by_the_items_answering_it_one_received_says_whose_it_is_and_whether_it_s_told() -> (
    None
):
    asked = item(
        51,
        Question(text="Which parser?"),
        3,
        call="q1",
        state=Answered(at=at(4), answer=53),
    )
    noted = item(52, note("I assumed UTF-8."), 7, state=Done(at=at(9)))
    answered = item(
        53,
        Answer(question=51, rulings=[Ruling(decision=1, verdict="leaning")]),
        4,
        sender=OPERATOR,
        recipient=SESSION,
        state=Told(at=at(5), how="call"),
    )
    replied = item(54, note("Good.", of=52), 9, sender=OPERATOR, recipient=SESSION)
    shown = listed(asked, noted, answered, replied)
    assert [said(each) for each in shown.sent] == [
        "→ @51 question to you · answered by @53",
        "→ @52 note to you · answered by @54",
    ]
    assert [said(each) for each in shown.received] == [
        "← @53 your answer to @51",
        "← @54 your reply to @52 · not told yet",
    ]
    # One received is as it's told it, at when it was told, else made.
    assert [(each.text, each.at) for each in shown.received] == [
        ("told 53", at(5)),
        ("told 54", at(9)),
    ]


def test_a_review_says_what_it_answers_or_that_it_s_the_operator_s_message_from_the_review() -> (
    None
):
    told = {
        "state": Told(at=at(9), how="call"),
        "sender": OPERATOR,
        "recipient": SESSION,
    }
    written = item(
        60,
        Review(covers=[], letters=[Letter(to=SESSION, text="Rename it.")]),
        9,
        **told,
    )
    reviewed = item(61, Review(covers=[52, 53]), 9, **told)
    message = item(62, note("Go on."), 9, **told)
    assert [said(each) for each in listed(written, reviewed, message).received] == [
        "← @60 your message, from the review",
        "← @61 your review of @52, @53",
        "← @62 your message",
    ]


def test_lup_s_word_on_citations_is_received_though_it_s_the_conversation_s_own_item() -> (
    None
):
    missed = Citation(said="@50[the tone]", start=0, end=13, item=50, words="the tone")
    told = {"state": Told(at=at(9), how="turn's end"), "recipient": SESSION}
    one = item(63, Unresolved(of=56, citations=[missed]), 9, **told)
    two = item(64, Unresolved(of=57, citations=[missed, missed]), 9, **told)
    shown = listed(one, two)
    assert shown.sent == []
    assert [said(each) for each in shown.received] == [
        "← @63 from lup: a citation of your words in @56 named no one passage",
        "← @64 from lup: 2 citations of your words in @57 named no one passage",
    ]


def test_one_passed_on_from_an_ended_subagent_says_whose_it_was_in_its_session_and_where_it_went_in_the_subagent() -> (
    None
):
    noted = item(44, note("No cache."), 2, sender=SURVEY, state=Done(at=at(3)))
    reply = item(
        46,
        note("Right.", of=44),
        3,
        sender=OPERATOR,
        recipient=SESSION,
        addressed=SURVEY,
        state=Told(at=at(4), how="call"),
    )
    assert [said(each) for each in listed(reply).received] == [
        "← @46 your reply to @44, for lup-impl/a04, which had ended"
    ]
    subagent = listed(noted, reply, party=SURVEY)
    assert [said(each) for each in [*subagent.sent, *subagent.received]] == [
        "→ @44 note to you · answered by @46",
        "← @46 your reply to @44 · passed on to lup-impl, this one having ended",
    ]


def test_a_conversation_a_line_names_is_a_span_said_by_its_path_else_its_runtime_s_ids_referring_to_it() -> (
    None
):
    asked = item(51, Question(text="Which?"), 2, recipient=SURVEY)
    sent = item(52, note("Ask it."), 2, sender=SURVEY, recipient=SESSION)
    survey = OfAgent(runtime="claude", session="s1", agent="a04")
    assert listed(asked).sent[0].line == [
        Span(text="→ @51 question to "),
        Span(text="lup-impl/a04", conversation=survey),
        Span(text=" · not told yet"),
    ]
    # Unnamed, it's said by its runtime's ids: those it's referred to by, which no rename changes.
    unnamed = listed(sent, paths=[]).received[0]
    assert unnamed.line == [
        Span(text="← @52 note from "),
        Span(text="subagent a04 of claude session s1", conversation=survey),
        Span(text=" · not told yet"),
    ]


def test_a_turn_s_last_words_lup_made_a_note_of_echo_the_conversation_s_own() -> None:
    ended = item(55, note("Reading the second runtime's.", ending=True), 8)
    assert [each.echoes for each in listed(ended, item(56, note("Done."), 8)).sent] == [
        True,
        False,
    ]
