"""A conversation laid out in blocks: the drawer, one earlier exchange, and one call read whole, as the page draws them and as their text form reads.

Ported from the page's `conversation.test.ts`, its layout's cases; what's the
page's editor (opening a comment on a line, quoting a passage, the changes
between two texts and a cursor moved by them) stays with the page.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, JsonValue

import lup
from lup.blocks import (
    SHELL_TONES,
    Block,
    Blocks,
    Fold,
    FoldKind,
    Line,
    Load,
    Markdown,
    OfAgent,
    Offer,
)
from lup_dev.host.records import Call, Called, Entry, Said
from lup_dev.inbox.marks import ReviewMark
from lup_dev.inbox.protocol import Exchanged, Pathed, exchanged
from lup_dev.inbox.store import (
    Answer,
    Answered,
    Citation,
    Conversation,
    Decided,
    Decision,
    Done,
    HeldChange,
    Item,
    Message,
    Operator,
    Question,
    Reason,
    Ruling,
    Told,
    Unresolved,
    Waiting,
)
from lup_transcripts.environment.conversation import (
    EARLIER_KIND,
    FOLD_KINDS,
    TONES,
    ConversationError,
    OfCall,
    OfExchange,
    call_blocks,
    conversation_blocks,
    exchange_blocks,
    given,
)


class Viewing(BaseModel):
    """The three views, as `TranscriptsServing` serves them: what the folds' loads name."""

    @lup.view(place=lup.Drawer(letter="v", called="the conversation", colour="cyan"))
    async def conversation(self, viewed: OfAgent) -> Blocks:
        """The whole conversation."""
        del viewed
        return Blocks()

    @lup.view
    async def exchange(self, viewed: OfExchange) -> Blocks:
        """One earlier exchange."""
        del viewed
        return Blocks()

    @lup.view
    async def call(self, viewed: OfCall) -> Blocks:
        """One call read whole."""
        del viewed
        return Blocks()


def at(minute: int) -> datetime:
    return datetime(2026, 10, 18, 10, minute, tzinfo=UTC)


OF = OfAgent(runtime="claude", session="s1")


ALONE = Exchanged(sent=[], received=[])
"""A conversation with nothing exchanged through lup."""


def drawer(
    entries: list[Entry],
    beside: Exchanged = ALONE,
    of: OfAgent = OF,
    earlier: FoldKind = EARLIER_KIND,
    *,
    mark: ReviewMark | None = None,
    reading: Offer | None = None,
) -> Blocks:
    return conversation_blocks(
        of,
        entries,
        beside,
        exchange=Viewing.exchange,
        call=Viewing.call,
        earlier=earlier,
        mark=mark,
        reading=reading,
    )


def exchange(
    entries: list[Entry], step: int | None, beside: Exchanged = ALONE, of: OfAgent = OF
) -> Blocks:
    asked = OfExchange(
        runtime=of.runtime, session=of.session, agent=of.agent, step=step
    )
    return exchange_blocks(
        asked, entries, beside, exchange=Viewing.exchange, call=Viewing.call
    )


def opened(blocks: list[Block]) -> list[Block]:
    """Return `blocks` with every fold whose content is given opened, as the operator opening them all sees them."""
    return [
        each.model_copy(update={"open": True, "content": opened(each.content)})
        if isinstance(each, Fold) and not isinstance(each.content, Load)
        else each
        for each in blocks
    ]


def whole(view: Blocks) -> str:
    """Say `view` as text with every fold whose content is given opened."""
    return Blocks(summary=view.summary, blocks=opened(view.blocks)).text()


def every(blocks: list[Block]) -> list[Block]:
    """Return every block among `blocks`, each fold's given content after it."""
    return [
        found
        for each in blocks
        for found in [
            each,
            *(
                every(each.content)
                if isinstance(each, Fold) and not isinstance(each.content, Load)
                else []
            ),
        ]
    ]


def folds(blocks: list[Block]) -> list[list[str]]:
    """Return each fold among `blocks`, those inside each after it: its id, its kind and its summary."""
    return [
        [each.id, each.kind, "".join(span.text for span in each.summary)]
        for each in every(blocks)
        if isinstance(each, Fold)
    ]


def ids(blocks: list[Block]) -> list[str]:
    """Return every block's id among `blocks`, those inside folds among them."""
    return [each.id for each in every(blocks)]


def block(blocks: list[Block], key: str) -> Block:
    """Return the block among `blocks`, those inside folds among them, whose id is `key`."""
    found = [each for each in every(blocks) if each.id == key]
    assert found, key
    return found[0]


def said(*lines: str) -> str:
    """Return `lines` as one text, a line each."""
    return "\n".join(lines)


STEPS: list[Entry] = [
    Said(by="operator", text="Look into reading transcripts.", at=at(0)),
    Said(
        by="agent",
        text="Each session is a JSONL file;\nsubagents get their own.",
        at=at(1),
    ),
    Called(tool="Bash", at=at(2)),
    Called(tool="Bash", at=at(2)),
    Called(tool="Read", at=at(3)),
    Said(by="operator", text="Build the reader.", at=at(9)),
    Said(
        by="agent",
        text="Twenty kinds of line.\n\n\nFour carry what was said.  ",
        at=at(10),
    ),
    Called(tool="Grep", at=at(11)),
]

MORE: list[Entry] = [
    Called(tool="Grep", at=at(12)),
    Said(by="agent", text="Found the four.", at=at(13)),
]


# A conversation laid out


def test_each_exchange_before_the_operator_s_last_words_folds_under_their_words_the_latest_open() -> (
    None
):
    view = drawer(STEPS)
    assert view.text() == said(
        "conversation · 8 steps · 2 new",
        "▸ you: Look into reading transcripts.  [exchange step=0]",
        "you: Build the reader.",
        "Twenty kinds of line.",
        "",
        "Four carry what was said.",
        "· Grep",
    )
    assert folds(view.blocks) == [
        ["exchange 0", "earlier", "you: Look into reading transcripts."]
    ]
    earlier = view.blocks[0]
    assert isinstance(earlier, Fold)
    assert not earlier.open
    assert earlier.content == Load.of(
        Viewing.exchange, OfExchange(runtime="claude", session="s1", step=0)
    )
    # The earlier exchange, read as its fold opens: the agent's words, its run of calls folded.
    first = exchange(STEPS, 0)
    assert first.summary == []
    assert (
        first.text()
        == "Each session is a JSONL file;\nsubagents get their own.\n▸ · called Bash x2, Read"
    )
    assert whole(first) == said(
        "Each session is a JSONL file;",
        "subagents get their own.",
        "▾ · called Bash x2, Read",
        "  · Bash",
        "  · Bash",
        "  · Read",
    )
    assert folds(first.blocks) == [["calls 2", "calls", "· called Bash x2, Read"]]


def test_each_exchange_but_the_last_folds_what_came_before_their_first_words_under_a_line_of_its_own() -> (
    None
):
    steps: list[Entry] = [
        Said(by="agent", text="Starting.", at=at(0)),
        Called(tool="Bash", at=at(1)),
        Said(by="operator", text="First.\nTwo lines.", at=at(5)),
        Said(by="agent", text="One.", at=at(6)),
        Said(by="operator", text="Second.", at=at(7)),
        Said(by="agent", text="Two.", at=at(8)),
        Said(by="operator", text="Third.", at=at(9)),
        Said(by="agent", text="Three.", at=at(10)),
    ]
    view = drawer(steps)
    assert folds(view.blocks) == [
        [
            "exchange before",
            "earlier",
            "earlier · 2 steps, from 5m before your first words",
        ],
        ["exchange 2", "earlier", "you: First."],
        ["exchange 4", "earlier", "you: Second."],
    ]
    # The rest of their words fold with what they opened; the last exchange is open, their words whole.
    assert exchange(steps, 2).text() == "     Two lines.\nOne."
    assert exchange(steps, None).text() == "Starting.\n· Bash"
    assert view.text().endswith("you: Third.\nThree.")
    # Opened under its fold, their further lines stand under the first's words.
    under = Fold(
        id="exchange 2",
        kind="earlier",
        open=True,
        summary=view.blocks[1].summary if isinstance(view.blocks[1], Fold) else [],
        content=exchange(steps, 2).blocks,
    )
    assert Blocks(blocks=[under]).text() == "▾ you: First.\n       Two lines.\n  One."
    # Where they never spoke, or spoke first, nothing folds.
    assert folds(drawer(steps[:2]).blocks) == []
    assert folds(drawer(steps[2:4]).blocks) == []
    assert exchange(steps[2:4], None).blocks == []


def test_the_operator_s_words_of_several_paragraphs_keep_one_blank_line_between_them() -> (
    None
):
    view = drawer(
        [Said(by="operator", text="One.\n\n\nTwo.\n"), Said(by="operator", text="")]
    )
    assert view.text() == "conversation · 2 steps\n▸ you: One.  [exchange step=0]\nyou:"
    assert (
        exchange([Said(by="operator", text="One.\n\n\nTwo.\n")], 0).text()
        == "\n     Two."
    )


def test_an_exchange_is_named_by_the_operator_s_words_that_open_it() -> None:
    with pytest.raises(
        ConversationError, match="step 1 of the conversation isn't the operator's words"
    ):
        exchange(STEPS, 1)
    with pytest.raises(ConversationError, match="step 40"):
        exchange(STEPS, 40)


def test_a_conversation_with_no_steps_is_no_drawer() -> None:
    assert drawer([]) == Blocks()


# Each call

CALLING: list[Entry] = [
    Said(by="operator", text="Fix it.", at=at(0)),
    Called(tool="Bash", gist="Run the tests", id="t1", at=at(1)),
    Said(by="agent", text="Two fail.", at=at(2)),
    Called(tool="Read", gist="review.ts:480", id="t2", at=at(3)),
    Called(tool="Edit", gist="review.ts", id="t3", at=at(4)),
    Called(tool="Edit", gist="review.ts", id="t4", at=at(4)),
    Called(tool="Bash", at=at(5)),
]


def test_a_call_is_a_line_saying_what_it_did_a_run_of_them_under_one_line_its_input_and_output_read_as_it_opens() -> (
    None
):
    view = drawer(CALLING)
    assert view.text() == said(
        "conversation · 7 steps · 6 new",
        "you: Fix it.",
        "▸ · Bash: Run the tests  [call id=t1]",
        "Two fail.",
        "▸ · called Read, Edit x2, Bash",
    )
    assert whole(view).endswith(
        said(
            "▾ · called Read, Edit x2, Bash",
            "  ▸ · Read: review.ts:480  [call id=t2]",
            "  ▸ · Edit: review.ts  [call id=t3]",
            "  ▸ · Edit: review.ts  [call id=t4]",
            "  · Bash",
        )
    )
    assert folds(view.blocks) == [
        ["call t1", "call", "· Bash: Run the tests"],
        ["calls 3", "calls", "· called Read, Edit x2, Bash"],
        ["call t2", "call", "· Read: review.ts:480"],
        ["call t3", "call", "· Edit: review.ts"],
        ["call t4", "call", "· Edit: review.ts"],
    ]
    # Each call's input and output is read from the call's view as it opens, set off by a bar.
    call = block(view.blocks, "call t2")
    assert isinstance(call, Fold)
    assert call.barred
    assert call.content == Load(
        view="call",
        argument={"runtime": "claude", "session": "s1", "agent": None, "id": "t2"},
    )
    # A call its record gives no id has nothing to read: a line, named by its step.
    assert block(view.blocks, "step 6") == Line.of("step 6", "· Bash", "call")
    # Its line, in the call's tone, isn't the agent's words.
    assert [span.tone for span in call.summary] == ["call"]
    # A run's calls are set off under its line, as each call's input and output is under its.
    run = block(view.blocks, "calls 3")
    assert isinstance(run, Fold)
    assert run.barred


def test_a_call_s_view_shows_each_argument_after_its_name_what_it_returned_or_that_it_s_still_running() -> (
    None
):
    read = Call(
        id="t1",
        input={"command": "uv run pytest -q", "description": "Run the tests"},
        output="2 failed\n3 passed\n",
    )
    shown = call_blocks(OfCall(runtime="claude", session="s1", id="t1"), read)
    assert shown.text() == said(
        "input:",
        "  command: uv run pytest -q",
        "  description: Run the tests",
        "output:",
        "  2 failed",
        "  3 passed",
    )
    assert ids(shown.blocks) == [
        "input t1",
        "input t1.1",
        "input t1.2",
        "output t1",
        "output t1.1",
        "output t1.2",
    ]
    running = Call(id="t2", input={"file_path": "/w/review.ts", "offset": 480})
    assert call_blocks(
        OfCall(runtime="claude", session="s1", id="t2"), running
    ).text() == said(
        "input:", "  file_path: /w/review.ts", "  offset: 480", "output: none yet"
    )
    unread = call_blocks(OfCall(runtime="claude", session="s1", id="t3"), None)
    assert unread.blocks == [
        Line.of("unread t3", "not read: its record doesn't hold the call", "muted")
    ]


def test_a_failed_call_says_it_failed_text_given_is_laid_out_as_it_is_a_long_value_under_its_name() -> (
    None
):
    failed = Call(
        id="x",
        input="*** Begin Patch\n*** Update File: a.py\n*** End Patch",
        output="a.py: no such file",
        failed=True,
    )
    assert call_blocks(
        OfCall(runtime="claude", session="s1", id="x"), failed
    ).text() == said(
        "input:",
        "  *** Begin Patch",
        "  *** Update File: a.py",
        "  *** End Patch",
        "failed:",
        "  a.py: no such file",
    )
    decisions: JsonValue = [
        {"text": "A model per kind, read by pydantic", "lean": "yes"},
        {"text": "A dict walked by hand, key by key", "lean": "no"},
    ]
    assert given(
        {
            "question": "Which?\nOr neither?",
            "limit": 3,
            "tags": ["a"],
            "decisions": decisions,
        }
    ) == [
        "question:",
        "  Which?",
        "  Or neither?",
        "limit: 3",
        'tags: ["a"]',
        "decisions:",
        "  [",
        "    {",
        '      "text": "A model per kind, read by pydantic",',
        '      "lean": "yes"',
        "    },",
        "    {",
        '      "text": "A dict walked by hand, key by key",',
        '      "lean": "no"',
        "    }",
        "  ]",
    ]
    assert given(None, "  ") == ["  null"]


# The agent's words, which comments are on


def test_the_agent_s_words_at_each_step_are_one_block_whose_text_a_comment_quotes() -> (
    None
):
    first = exchange(STEPS, 0)
    words = block(first.blocks, "step 1")
    assert isinstance(words, Markdown)
    assert words == Markdown(
        id="step 1", text="Each session is a JSONL file;\nsubagents get their own."
    )
    # A comment's quote counts in that text, as the page's remarks do (`Remark.quote`).
    assert words.text[18:23] == "JSONL"
    latest = block(drawer(STEPS).blocks, "step 6")
    assert latest == Markdown(
        id="step 6", text="Twenty kinds of line.\n\nFour carry what was said."
    )


# The conversation growing


def test_what_arrives_is_added_at_the_end_everything_before_it_as_it_was() -> None:
    before = drawer(STEPS)
    after = drawer([*STEPS, *MORE])
    # Each block but the last stays as it was; the calls the conversation ended on go on, each a line.
    assert after.blocks[: len(before.blocks) - 1] == before.blocks[:-1]
    assert after.text().endswith("· Grep\n· Grep\nFound the four.")
    assert after.summary != before.summary
    # The earlier exchange reads as it did.
    assert exchange([*STEPS, *MORE], 0) == exchange(STEPS, 0)


def test_the_last_exchange_folds_once_the_operator_speaks_again_and_a_run_once_it_s_long_enough_each_named_as_before() -> (
    None
):
    later: list[Entry] = [
        *STEPS,
        *MORE,
        *(Called(tool="Read", at=at(14)) for _ in range(3)),
    ]
    view = drawer(later)
    assert whole(view).endswith(
        "Found the four.\n▾ · called Read x3\n  · Read\n  · Read\n  · Read"
    )
    spoke = drawer([*later, Said(by="operator", text="Good.", at=at(15))])
    assert folds(spoke.blocks) == [
        ["exchange 0", "earlier", "you: Look into reading transcripts."],
        ["exchange 5", "earlier", "you: Build the reader."],
    ]
    assert [each[0] for each in folds(exchange(later, 5).blocks)] == ["calls 10"]
    assert spoke.text().endswith("you: Good.")


# The items of lup's inbox in a conversation

SESSION = Conversation(repository=Path("/r.git"), runtime="claude", session="s1")
SURVEY = SESSION.model_copy(update={"agent": "a04"})
OPERATOR = Operator()
PATHS = [
    Pathed(conversation=SESSION, path="lup-impl"),
    Pathed(conversation=SURVEY, path="lup-impl/a04"),
]
"""How the core names the session's own conversation, and its subagent."""


def listed(*texts: tuple[Item, str], party: Conversation = SESSION) -> Exchanged:
    """Return what `party` exchanged as the core lists it: each item with its text, sent or received, and its line."""
    told = {item.number: text for item, text in texts}
    return exchanged(
        party,
        [item for item, _ in texts],
        written=lambda item: told[item.number],
        told=lambda item: told[item.number],
        paths=PATHS,
    )


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


CALLED: list[Entry] = [
    Said(by="operator", text="Look into reading transcripts.", at=at(0)),
    Said(by="agent", text="Each session is a JSONL file.", at=at(1)),
    Called(tool="Bash", id="b1", at=at(2)),
    Called(tool="mcp__lup__ask", id="q1", at=at(3)),
    Called(tool="Read", id="r1", at=at(4)),
    Said(by="agent", text="Reading the second runtime's.", at=at(6)),
    Called(tool="Grep", id="g1", at=at(8)),
]

ASKED = item(
    51,
    Question(
        text="Which parser?", decisions=[Decision(text="A model per kind", lean="yes")]
    ),
    3,
    call="q1",
    state=Answered(at=at(4), answer=53),
)
NOTED = item(52, note("I assumed UTF-8."), 7, state=Done(at=at(9)))
ANSWERED = item(
    53,
    Answer(question=51, rulings=[Ruling(decision=1, verdict="leaning")]),
    4,
    sender=OPERATOR,
    recipient=SESSION,
    state=Told(at=at(5), how="call"),
)
REPLIED = item(54, note("Good.", of=52), 9, sender=OPERATOR, recipient=SESSION)

EXCHANGED = listed(
    (ASKED, "Which parser?\n1. A model per kind (lean: yes)"),
    (NOTED, "I assumed UTF-8."),
    (
        ANSWERED,
        "Asked: Which parser?\n1. A model per kind (lean: yes): leaning: they go with the lean.",
    ),
    (REPLIED, "Good."),
)


def lines(view: Blocks, *marks: str) -> list[str]:
    """Return the lines of `view`'s text, every fold opened, that start with one of `marks` once a fold's mark is off."""
    return [
        each
        for each in (
            line.removeprefix("▸ ").removeprefix("▾ ")
            for line in whole(view).splitlines()
        )
        if each.startswith(marks)
    ]


def test_each_item_is_a_line_its_text_under_it_one_sent_after_the_call_that_made_it_one_received_when_told() -> (
    None
):
    view = drawer(CALLED, EXCHANGED)
    assert whole(view) == said(
        "conversation · 7 steps · 6 new",
        "you: Look into reading transcripts.",
        "Each session is a JSONL file.",
        "▸ · Bash  [call id=b1]",
        "▸ · mcp__lup__ask  [call id=q1]",
        "▾ → @51 question to you · answered by @53",
        "  Which parser?",
        "  1. A model per kind (lean: yes)",
        "▸ · Read  [call id=r1]",
        "▾ ← @53 your answer to @51",
        "  Asked: Which parser?",
        "  1. A model per kind (lean: yes): leaning: they go with the lean.",
        "Reading the second runtime's.",
        "▾ → @52 note to you · answered by @54",
        "  I assumed UTF-8.",
        "▸ · Grep  [call id=g1]",
        "▾ ← @54 your reply to @52 · not told yet",
        "  Good.",
    )
    # Each item's text folds under its line, closed, set off by a bar; sent in its tone, received in its own.
    assert [each for each in folds(view.blocks) if each[1] == "items"] == [
        ["item 51", "items", "→ @51 question to you · answered by @53"],
        ["item 53", "items", "← @53 your answer to @51"],
        ["item 52", "items", "→ @52 note to you · answered by @54"],
        ["item 54", "items", "← @54 your reply to @52 · not told yet"],
    ]
    answer = block(view.blocks, "item 53")
    assert isinstance(answer, Fold)
    assert not answer.open
    assert answer.barred
    assert [span.tone for span in answer.summary] == ["received"]
    assert answer.content == [
        Markdown(
            id="text 53",
            text="Asked: Which parser?\n1. A model per kind (lean: yes): leaning: they go with the lean.",
        )
    ]
    question = block(view.blocks, "item 51")
    assert isinstance(question, Fold)
    assert [span.tone for span in question.summary] == ["sent"]


def test_each_item_is_cited_by_at_and_its_number_which_nobody_takes_for_a_github_issue() -> (
    None
):
    assert not re.search(r"#\d", whole(drawer(CALLED, EXCHANGED)))


def test_a_turn_s_last_words_lup_made_a_note_are_left_out_being_the_agent_s_words_already_shown() -> (
    None
):
    ended = item(55, note("Reading the second runtime's.", ending=True), 8)
    beside = listed(
        (ASKED, "Which parser?"),
        (NOTED, "I assumed UTF-8."),
        (ANSWERED, "Asked."),
        (REPLIED, "Good."),
        (ended, "Reading the second runtime's."),
    )
    view = drawer(CALLED, beside)
    assert [each[0] for each in folds(view.blocks) if each[1] == "items"] == [
        "item 51",
        "item 53",
        "item 52",
        "item 54",
    ]
    assert "@55" not in whole(view)


def test_the_operator_s_comment_on_deciding_an_item_is_under_its_text() -> None:
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
    text = whole(
        drawer(STEPS, listed((held, "Let the change land?\nAGENTS.md: the operator's")))
    )
    assert text[text.index("▾ → @55") :] == said(
        "▾ → @55 held change to you · declined",
        "  Let the change land?",
        "  AGENTS.md: the operator's",
        "",
        "  your comment: Not this file.",
    )


def test_one_passed_on_from_an_ended_subagent_is_in_both_its_session_s_view_and_the_subagent_s() -> (
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
    session = drawer(STEPS[:3], listed((reply, "Right.")))
    subagent = drawer(
        STEPS[:3],
        listed((noted, "No cache."), (reply, "Right."), party=SURVEY),
        OfAgent(runtime="claude", session="s1", agent="a04"),
    )
    assert lines(session, "←", "→") == [
        "← @46 your reply to @44, for lup-impl/a04, which had ended"
    ]
    assert lines(subagent, "←", "→") == [
        "→ @44 note to you · answered by @46",
        "← @46 your reply to @44 · passed on to lup-impl, this one having ended",
    ]


def test_a_conversation_an_item_s_line_names_keeps_its_span_referring_to_it_in_the_line_s_tone() -> (
    None
):
    reply = item(
        46,
        note("Right.", of=44),
        3,
        sender=OPERATOR,
        recipient=SESSION,
        addressed=SURVEY,
        state=Told(at=at(4), how="call"),
    )
    asked = item(51, Question(text="Which?", decisions=[]), 2, recipient=SURVEY)
    view = drawer(STEPS[:3], listed((asked, "Which?"), (reply, "Right.")))
    survey = OfAgent(runtime="claude", session="s1", agent="a04")
    passed = block(view.blocks, "item 46")
    assert isinstance(passed, Fold)
    assert passed.summary == [
        lup.Span(text="← @46 your reply to @44, for ", tone="received"),
        lup.Span(text="lup-impl/a04", tone="received", conversation=survey),
        lup.Span(text=", which had ended", tone="received"),
    ]
    question = block(view.blocks, "item 51")
    assert isinstance(question, Fold)
    assert [(span.text, span.conversation) for span in question.summary] == [
        ("→ @51 question to ", None),
        ("lup-impl/a04", survey),
        (" · not told yet", None),
    ]


def test_a_step_with_no_time_takes_the_last_before_it_and_in_a_record_with_no_times_items_go_at_its_end() -> (
    None
):
    untimed: list[Entry] = [
        Said(by="operator", text="Go."),
        Called(tool="Bash"),
        Said(by="agent", text="Ran it.", at=at(5)),
        Called(tool="Read"),
        Said(by="agent", text="Read it."),
    ]
    early = item(60, note("Early."), 4)
    late = item(61, note("Late."), 6)
    beside = listed((late, "Late."), (early, "Early."))
    assert drawer(untimed, beside).text().splitlines()[1:] == [
        "you: Go.",
        "· Bash",
        "▸ → @60 note to you · unread",
        "Ran it.",
        "· Read",
        "Read it.",
        "▸ → @61 note to you · unread",
    ]
    timeless = [each.model_copy(update={"at": None}) for each in untimed]
    assert drawer(timeless, beside).text().splitlines()[1:] == [
        "you: Go.",
        "· Bash",
        "Ran it.",
        "· Read",
        "Read it.",
        "▸ → @60 note to you · unread",
        "▸ → @61 note to you · unread",
    ]


def test_an_item_before_the_operator_s_last_words_folds_in_its_exchange_one_before_their_first_words_counted_with_what_came_before() -> (
    None
):
    before = item(50, note("Early."), 4)
    assert "@50" not in drawer(STEPS, listed((before, "Early."))).text()
    assert [
        each[0] for each in folds(exchange(STEPS, 0, listed((before, "Early."))).blocks)
    ] == [
        "calls 2",
        "item 50",
    ]
    first = item(49, note("Earliest."), 0)
    early = drawer(STEPS[1:], listed((first, "Earliest.")))
    assert (
        early.text().splitlines()[1]
        == "▸ earlier · 4 steps, 1 item, from 9m before your first words  [exchange]"
    )


def test_an_item_arriving_is_added_and_its_question_s_line_changes_as_its_answer_arrives_the_rest_as_it_was() -> (
    None
):
    waiting = ASKED.model_copy(update={"state": Waiting()})
    asked = listed((waiting, "Which parser?"))
    answered = listed((ASKED, "Which parser?"), (ANSWERED, "Asked."))
    before, after = drawer(CALLED, asked), drawer(CALLED, answered)
    assert "▸ → @51 question to you · waiting on you" in before.text()
    assert whole(after).endswith(
        said(
            "▾ → @51 question to you · answered by @53",
            "  Which parser?",
            "▸ · Read  [call id=r1]",
            "▾ ← @53 your answer to @51",
            "  Asked.",
            "Reading the second runtime's.",
            "▸ · Grep  [call id=g1]",
        )
    )
    # Every other block is as it was: the question's own changes, and its answer is added.
    kept = [each for each in before.blocks if each.id != "item 51"]
    assert [
        each for each in after.blocks if each.id not in {"item 51", "item 53"}
    ] == kept


def test_an_item_with_no_text_is_a_line_with_nothing_folded_under_it() -> None:
    missed = Citation(said="@50[the tone]", start=0, end=13, item=50, words="the tone")
    told = {"state": Told(at=at(9), how="turn's end"), "recipient": SESSION}
    two = item(64, Unresolved(of=57, citations=[missed, missed]), 9, **told)
    view = drawer(CALLED, listed((two, "")))
    assert block(view.blocks, "item 64 line") == Line.of(
        "item 64 line",
        "← @64 from lup: 2 citations of your words in @57 named no one passage",
        "received",
    )


# What stays open: at most the agent's last words, their calls not counted


def talking(words: int, start: int = 0) -> list[Entry]:
    """The agent's words, `words` of them from `start` on, each after a call, as a session driven from the dashboard reads: none of the operator's typed words."""
    return [
        entry
        for each in range(start, start + words)
        for entry in [
            Called(tool="Bash", at=at(each % 60)),
            Said(by="agent", text=f"Word {each}.", at=at(each % 60)),
        ]
    ]


KEEPING_TWO = EARLIER_KIND.model_copy(update={"keeps_open": 2})
"""What came earlier as a person's layer might keep it: two of the agent's words open."""


def test_at_most_the_agent_s_last_twenty_words_stay_open_what_came_before_under_one_line() -> (
    None
):
    view = drawer(talking(25))
    # The last 20 of their words, each after their call: the calls don't count.
    shown = [each for each in view.blocks if isinstance(each, Markdown)]
    assert [each.text for each in shown] == [f"Word {each}." for each in range(5, 25)]
    first = view.blocks[0]
    assert isinstance(first, Fold)
    assert (first.id, first.kind, first.open) == (
        "exchange before until last 20",
        "earlier",
        False,
    )
    assert first.content == Load.of(
        Viewing.exchange,
        OfExchange(runtime="claude", session="s1", step=None, until_last=20),
    )
    # It says how many steps it holds, its text form the view and what it gives it.
    assert view.text().splitlines()[:3] == [
        "conversation · 50 steps · 50 new",
        "▸ 11 earlier steps, 11 new  [exchange until_last=20]",
        "Word 5.",
    ]
    # Twenty or fewer, nothing folds.
    assert folds(drawer(talking(20)).blocks) == []


def test_the_fold_of_what_came_earlier_reads_twenty_more_of_the_agent_s_words_and_folds_the_rest_the_same_way() -> (
    None
):
    entries = talking(45)
    page = exchange_blocks(
        OfExchange(runtime="claude", session="s1", until_last=20),
        entries,
        ALONE,
        exchange=Viewing.exchange,
        call=Viewing.call,
    )
    shown = [each.text for each in page.blocks if isinstance(each, Markdown)]
    assert shown == [f"Word {each}." for each in range(5, 25)]
    deeper = page.blocks[0]
    assert isinstance(deeper, Fold)
    assert deeper.id == "exchange before until last 40"
    assert isinstance(deeper.content, Load)
    assert deeper.content.argument["until_last"] == 40
    last = exchange_blocks(
        OfExchange(runtime="claude", session="s1", until_last=40),
        entries,
        ALONE,
        exchange=Viewing.exchange,
        call=Viewing.call,
    )
    assert [each.text for each in last.blocks if isinstance(each, Markdown)] == [
        f"Word {each}." for each in range(5)
    ]
    assert folds(last.blocks) == []
    # Asked for more than the agent said, there's nothing before it.
    assert (
        exchange_blocks(
            OfExchange(runtime="claude", session="s1", until_last=60),
            entries,
            ALONE,
            exchange=Viewing.exchange,
            call=Viewing.call,
        ).blocks
        == []
    )


def test_as_the_agent_speaks_the_fold_keeps_its_id_and_the_word_it_passed_goes_under_it() -> (
    None
):
    before = drawer(talking(25))
    after = drawer([*talking(25), *talking(1, start=25)])
    assert before.blocks[0].id == after.blocks[0].id == "exchange before until last 20"
    assert "step 11" in ids(before.blocks)
    assert "step 11" not in ids(after.blocks)
    # The fold's own view shows it now, its id the same: a comment on it stays on it.
    page = exchange_blocks(
        OfExchange(runtime="claude", session="s1", until_last=20),
        [*talking(25), *talking(1, start=25)],
        ALONE,
        exchange=Viewing.exchange,
        call=Viewing.call,
    )
    assert block(page.blocks, "step 11") == block(before.blocks, "step 11")


def test_in_an_exchange_the_operator_s_words_open_it_and_the_fold_comes_after_them() -> (
    None
):
    entries: list[Entry] = [
        Said(by="operator", text="Read them all.\nEvery record.", at=at(0)),
        *talking(4),
    ]
    view = drawer(entries, earlier=KEEPING_TWO)
    assert view.text().splitlines() == [
        "conversation · 9 steps · 8 new",
        "you: Read them all.",
        "     Every record.",
        "▸ 5 earlier steps, 5 new  [exchange step=0 until_last=2]",
        "Word 2.",
        "· Bash",
        "Word 3.",
    ]
    # An earlier exchange opened is kept the same way, the operator's further lines first.
    spoke = drawer(
        [*entries, Said(by="operator", text="Good.", at=at(9))], earlier=KEEPING_TWO
    )
    assert folds(spoke.blocks) == [["exchange 0", "earlier", "you: Read them all."]]
    opened = exchange_blocks(
        OfExchange(runtime="claude", session="s1", step=0),
        entries,
        ALONE,
        exchange=Viewing.exchange,
        call=Viewing.call,
        earlier=KEEPING_TWO,
    )
    assert opened.text().splitlines()[:2] == [
        "     Every record.",
        "▸ 5 earlier steps, 5 new  [exchange step=0 until_last=2]",
    ]


def test_items_count_in_the_fold_and_a_person_s_layer_keeps_more_or_everything_open() -> (
    None
):
    noted = item(50, note("Early."), 0)
    view = drawer(talking(4), listed((noted, "Early.")), earlier=KEEPING_TWO)
    assert view.text().splitlines()[1] == (
        "▸ 5 earlier steps, 1 item, 5 new  [exchange until_last=2]"
    )
    everything = EARLIER_KIND.model_copy(update={"keeps_open": None})
    assert folds(drawer(talking(30), earlier=everything).blocks) == []


# What the operator has read: the drawer's review mark, and their own words


def marked(step: int, minute: int = 59) -> ReviewMark:
    """The drawer's review mark, read up to `step`, moved at `minute`."""
    return ReviewMark(key=OF.model_dump(mode="json"), up_to=str(step), at=at(minute))


READING = Offer(action="review-mark", verb="done", says="mark it read")
"""The offer of marking the conversation read, as the module makes it."""


def test_what_came_before_the_drawer_s_mark_folds_under_one_line_what_came_after_open_and_new() -> (
    None
):
    view = drawer(talking(10), mark=marked(9), reading=READING)
    assert view.text().splitlines()[:4] == [
        "conversation · 20 steps · 10 new",
        "▸ 10 earlier steps  [exchange through=9]",
        "· Bash",
        "Word 5.",
    ]
    first = view.blocks[0]
    assert isinstance(first, Fold)
    assert first.id == "exchange before through 9"
    assert view.offers == [READING]
    # Read to its last step, it's one line, nothing more to mark read.
    read = drawer(talking(10), mark=marked(19), reading=READING)
    assert (
        read.text()
        == "conversation · 20 steps\n▸ 20 earlier steps  [exchange through=19]"
    )
    assert read.offers == []
    # Never read, everything is new, and it offers marking it read.
    assert drawer(talking(2), reading=READING).offers == [READING]


def test_the_fold_of_what_was_read_keeps_its_id_as_the_agent_speaks_and_opens_to_what_it_holds() -> (
    None
):
    before = drawer(talking(10), mark=marked(9))
    after = drawer(talking(12), mark=marked(9))
    assert before.blocks[0].id == after.blocks[0].id == "exchange before through 9"
    page = exchange_blocks(
        OfExchange(runtime="claude", session="s1", through=9),
        talking(12),
        ALONE,
        exchange=Viewing.exchange,
        call=Viewing.call,
        mark=marked(9),
    )
    shown = [each.text for each in page.blocks if isinstance(each, Markdown)]
    assert shown == [f"Word {each}." for each in range(5)]
    assert folds(page.blocks) == []


def test_the_operator_s_words_typed_after_the_mark_count_as_reading_what_came_before() -> (
    None
):
    entries: list[Entry] = [
        *talking(5),
        Said(by="operator", text="Go on.", at=at(20)),
        *talking(3, start=5),
    ]
    view = drawer(entries, mark=marked(3))
    assert view.text().splitlines() == [
        "conversation · 17 steps · 6 new",
        "▸ earlier · 10 steps, from 20m before your first words  [exchange]",
        "you: Go on.",
        "· Bash",
        "Word 5.",
        "· Bash",
        "Word 6.",
        "· Bash",
        "Word 7.",
    ]
    # A mark after their words is the later.
    later = drawer(entries, mark=marked(13))
    assert later.text().splitlines()[2:5] == [
        "you: Go on.",
        "▸ 3 earlier steps  [exchange step=10 through=13]",
        "Word 6.",
    ]


def test_a_drawer_long_unread_since_its_mark_keeps_the_cap_its_fold_saying_how_many_are_new() -> (
    None
):
    entries = talking(30)
    view = drawer(entries, mark=marked(9))
    assert view.text().splitlines()[:3] == [
        "conversation · 60 steps · 50 new",
        "▸ 21 earlier steps, 11 new  [exchange until_last=20]",
        "Word 10.",
    ]
    assert view.blocks[0].id == "exchange before until last 20"
    # Opened, what was read folds apart from the new it held.
    page = exchange_blocks(
        OfExchange(runtime="claude", session="s1", until_last=20),
        entries,
        ALONE,
        exchange=Viewing.exchange,
        call=Viewing.call,
        mark=marked(9),
    )
    assert page.text().splitlines()[:3] == [
        "▸ 10 earlier steps  [exchange through=9]",
        "· Bash",
        "Word 5.",
    ]
    # An earlier exchange opened is read whole: the mark folds nothing of it.
    spoke = [
        Said(by="operator", text="Look.", at=at(0)),
        *talking(3),
        Said(by="operator", text="Now.", at=at(30)),
    ]
    earlier = exchange_blocks(
        OfExchange(runtime="claude", session="s1", step=0),
        spoke,
        ALONE,
        exchange=Viewing.exchange,
        call=Viewing.call,
        mark=marked(2),
    )
    assert folds(earlier.blocks) == []


def test_an_item_told_after_the_mark_stays_open_one_told_before_folds_with_what_was_read() -> (
    None
):
    told = item(50, note("Seen."), 2)
    late = item(
        51, note("Late."), 2, made=datetime(2026, 10, 18, 10, 2, 30, tzinfo=UTC)
    )
    view = drawer(
        talking(6), listed((told, "Seen."), (late, "Late.")), mark=marked(5, minute=2)
    )
    lines = view.text().splitlines()
    assert lines[:3] == [
        "conversation · 12 steps · 6 new",
        "▸ 6 earlier steps, 1 item  [exchange through=5]",
        "▸ → @51 note to you · unread",
    ]


def test_what_was_read_of_items_alone_folds_named_by_the_step_read_and_opens_to_them() -> (
    None
):
    entries: list[Entry] = [
        Said(by="operator", text="Go.", at=at(0)),
        Said(by="agent", text="Done.", at=at(5)),
    ]
    told = item(50, note("On it."), 1)
    beside = listed((told, "On it."))
    view = drawer(entries, beside, mark=marked(0, minute=2))
    assert view.text().splitlines()[1:4] == [
        "you: Go.",
        "▸ 1 earlier item  [exchange step=0 through=0]",
        "Done.",
    ]
    page = exchange_blocks(
        OfExchange(runtime="claude", session="s1", step=0, through=0),
        entries,
        beside,
        exchange=Viewing.exchange,
        call=Viewing.call,
        mark=marked(0, minute=2),
    )
    assert [each.id for each in page.blocks] == ["item 50"]


# What the layouts declare, and the ids they keep


def test_every_block_has_an_id_of_its_own_a_fold_s_never_a_line_s() -> None:
    # One conversation's three views, each fold's loaded content beside the drawer.
    entries: list[Entry] = [
        *CALLED,
        Said(by="operator", text="Go on.\nAll of it.", at=at(10)),
        Said(by="agent", text="Going.", at=at(11)),
    ]
    views = [
        drawer(entries, EXCHANGED),
        exchange(entries, 0, EXCHANGED),
        call_blocks(
            OfCall(runtime="claude", session="s1", id="q1"),
            Call(id="q1", input={"a": 1}, output="ok"),
        ),
    ]
    every = [each for view in views for each in ids(view.blocks)]
    assert len(every) == len(set(every))
    shown = [
        *drawer(STEPS).blocks,
        *exchange(STEPS, 0).blocks,
        *drawer(CALLED, EXCHANGED).blocks,
    ]
    fold_ids = {each[0] for each in folds(shown)}
    line_ids = set(ids(shown)) - fold_ids
    assert fold_ids.isdisjoint(line_ids)
    assert all(
        each.startswith(("exchange ", "calls ", "call ", "item ")) for each in fold_ids
    )
    assert not any(
        each.startswith(("exchange ", "calls ", "call ")) for each in line_ids
    )


def test_every_tone_and_fold_kind_the_layouts_name_is_the_shell_s_or_declared() -> None:
    declared = {each.name for each in [*SHELL_TONES, *TONES]}
    views = [drawer(CALLED, EXCHANGED), exchange(STEPS, 0), drawer(STEPS[1:])]
    assert {
        tone for view in views for tone in Blocks(blocks=opened(view.blocks)).tones()
    } <= declared
    kinds = {each.name for each in FOLD_KINDS}
    assert {each[1] for view in views for each in folds(view.blocks)} <= kinds


def test_the_fold_kinds_keep_their_letters_and_colours() -> None:
    assert [
        (each.name, each.letter, each.colour, each.level, each.opens)
        for each in FOLD_KINDS
    ] == [
        ("earlier", "e", "ok", 1, "back"),
        ("calls", "k", "purple", 2, "together"),
        ("items", "m", "cyan", 3, "together"),
        ("call", "d", "orange", 4, "deep"),
    ]
    assert [(each.name, each.like, each.colour) for each in TONES] == [
        ("call", None, "orange"),
        ("sent", "call", None),
        ("received", "operator", None),
        ("run", "muted", None),
    ]
