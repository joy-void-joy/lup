"""A conversation laid out in blocks: the drawer, one earlier exchange, and one call read whole, as the page draws them and as their text form reads.

Ported from the page's `conversation.test.ts`, its layout's cases; what's the
page's editor (opening a comment on a line, quoting a passage, the changes
between two texts and a cursor moved by them) stays with the page.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

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
from lup_dev.adapters.claude import ClaudeTranscripts
from lup_dev.adapters.codex import CodexTranscripts
from lup_dev.host.records import Call, Called, Entry, Reader, Said
from lup_dev.inbox.marks import ReviewMark
from lup_dev.inbox.protocol import Exchanged, Pathed, exchanged
from lup_dev.inbox.store import (
    Answer,
    Answered,
    Citation,
    Decided,
    Decision,
    Done,
    HeldChange,
    Item,
    Message,
    Question,
    Reason,
    Ruling,
    Told,
    Unresolved,
    Waiting,
)
from lup_ledger.parties import Conversation, Operator
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
)

if TYPE_CHECKING:
    from collections.abc import Callable


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
        """One call, or a part of it, read as its fold opens."""
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


def read_back(
    entries: list[Entry], beside: Exchanged = ALONE, of: OfAgent = OF, step: int = 0
) -> Blocks:
    """Return what the fold of what the operator has read shows as it opens, in the exchange at `step`: where they've spoken through lup since, the conversation's items where they happened."""
    asked = OfExchange(
        runtime=of.runtime,
        session=of.session,
        agent=of.agent,
        step=step,
        through=len(entries) - 1,
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
        "trace · 8 steps · 2 new",
        "▸ you: Look into reading transcripts.  [exchange step=0]",
        "▾ you: Build the reader.",
        "  ▾ Twenty kinds of line.",
        "    Twenty kinds of line.",
        "",
        "    Four carry what was said.",
        "  · Grep",
    )
    assert folds(view.blocks) == [
        ["exchange 0", "earlier", "you: Look into reading transcripts."],
        ["exchange 5", "earlier", "you: Build the reader."],
        ["said 6", "items", "Twenty kinds of line."],
    ]
    earlier, latest = view.blocks
    assert isinstance(earlier, Fold)
    assert not earlier.open
    assert earlier.content == Load.of(
        Viewing.exchange, OfExchange(runtime="claude", session="s1", step=0)
    )
    # The latest is the same fold the operator's next words will close, open, its content given.
    assert isinstance(latest, Fold)
    assert latest.open
    # The earlier exchange, read as its fold opens: the agent's words, its run of calls open, each on a row of its own.
    first = exchange(STEPS, 0)
    assert first.summary == []
    assert first.text() == said(
        "▾ Each session is a JSONL file;",
        "  Each session is a JSONL file;",
        "  subagents get their own.",
        "▾ · 3 calls: Bash x2, Read",
        "  · Bash",
        "  · Bash",
        "  · Read",
    )
    assert folds(first.blocks) == [
        ["said 1", "items", "Each session is a JSONL file;"],
        ["calls 2", "calls", "· 3 calls: Bash x2, Read"],
    ]


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
        ["exchange 6", "earlier", "you: Third."],
        ["said 7", "items", "Three."],
    ]
    # The rest of their words fold with what they opened; the last exchange is open, their words whole.
    assert exchange(steps, 2).text() == "     Two lines.\n▾ One.\n  One."
    assert exchange(steps, None).text() == "▾ Starting.\n  Starting.\n· Bash"
    assert view.text().endswith("▾ you: Third.\n  ▾ Three.\n    Three.")
    # Opened under its fold, their further lines stand under the first's words.
    under = Fold(
        id="exchange 2",
        kind="earlier",
        open=True,
        summary=view.blocks[1].summary if isinstance(view.blocks[1], Fold) else [],
        content=exchange(steps, 2).blocks,
    )
    assert (
        Blocks(blocks=[under]).text()
        == "▾ you: First.\n       Two lines.\n  ▾ One.\n    One."
    )
    # Where they never spoke, no exchange folds; where they spoke first, theirs is open under its line.
    assert folds(drawer(steps[:2]).blocks) == [["said 0", "items", "Starting."]]
    assert folds(drawer(steps[2:4]).blocks) == [
        ["exchange 0", "earlier", "you: First."],
        ["said 1", "items", "One."],
    ]
    assert exchange(steps[2:4], None).blocks == []


def test_the_operator_s_words_of_several_paragraphs_keep_one_blank_line_between_them() -> (
    None
):
    view = drawer(
        [Said(by="operator", text="One.\n\n\nTwo.\n"), Said(by="operator", text="")]
    )
    assert view.text() == "trace · 2 steps\n▸ you: One.  [exchange step=0]\nyou:"
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


def test_each_call_is_a_line_of_its_own_saying_what_it_was_given_a_run_of_them_open_under_one_line_its_input_and_output_read_as_it_opens() -> (
    None
):
    view = drawer(CALLING)
    assert view.text() == said(
        "trace · 7 steps · 6 new",
        "▾ you: Fix it.",
        "  ▸ · Bash: Run the tests  [call id=t1]",
        "  ▾ Two fail.",
        "    Two fail.",
        "  ▾ · 4 calls: Edit x2, Read, Bash",
        "    ▸ · Read: review.ts:480  [call id=t2]",
        "    ▸ · Edit: review.ts  [call id=t3]",
        "    ▸ · Edit: review.ts  [call id=t4]",
        "    · Bash",
    )
    # A run's calls are set off under its line, as each call's input and output is under its.
    run = block(view.blocks, "calls 3")
    assert isinstance(run, Fold)
    assert (run.kind, run.open, run.barred) == ("calls", True, True)
    assert [span.tone for span in run.summary] == ["run"]
    assert [each for each in folds(view.blocks) if each[1] == "call"] == [
        ["call t1", "call", "· Bash: Run the tests"],
        ["call t2", "call", "· Read: review.ts:480"],
        ["call t3", "call", "· Edit: review.ts"],
        ["call t4", "call", "· Edit: review.ts"],
    ]
    # Each call's input and output is read from the call's view as it opens, set off by a bar.
    call = block(view.blocks, "call t2")
    assert isinstance(call, Fold)
    assert call.barred
    assert not call.open
    assert call.content == Load(
        view="call",
        argument={
            "runtime": "claude",
            "session": "s1",
            "agent": None,
            "id": "t2",
            "output": None,
            "argument": None,
        },
    )
    # A call its record gives no id has nothing to read: a line, named by its step.
    assert block(view.blocks, "step 6") == Line.of("step 6", "· Bash", "call")
    # Its line, in the call's tone, isn't the agent's words.
    assert [span.tone for span in call.summary] == ["call"]


def test_a_run_of_calls_keeps_its_id_as_it_grows_and_says_what_there_s_most_of_on_one_row() -> (
    None
):
    start: list[Entry] = [Said(by="operator", text="Go.", at=at(0))]
    three: list[Entry] = [
        Called(tool="Read", id=f"r{each}", at=at(1)) for each in range(3)
    ]
    grown = drawer([*start, *three, Called(tool="Bash", id="b", at=at(2))])
    assert folds(drawer([*start, *three]).blocks)[1] == [
        "calls 1",
        "calls",
        "· 3 calls: Read x3",
    ]
    assert folds(grown.blocks)[1] == ["calls 1", "calls", "· 4 calls: Read x3, Bash"]
    # Fewer than three are rows alone.
    assert [each[1] for each in folds(drawer([*start, *three[:2]]).blocks)] == [
        "earlier",
        "call",
        "call",
    ]
    many: list[Entry] = [
        *start,
        *(
            Called(tool=f"mcp__lup__tool_{each}", id=f"t{each}", at=at(1))
            for each in range(30)
        ),
    ]
    line = folds(drawer(many).blocks)[1][2]
    assert len(line) <= 100
    assert line.startswith("· 30 calls: mcp__lup__tool_0, ")
    assert line.endswith("…")


def test_a_call_that_only_sent_an_item_is_no_row_of_a_run_and_doesn_t_break_one_apart_from_its_item() -> (
    None
):
    entries: list[Entry] = [
        Said(by="operator", text="Go.", at=at(0)),
        *(Called(tool="Read", id=f"r{each}", at=at(1)) for each in range(3)),
        Called(tool="mcp__lup__note", id="n", at=at(2)),
        *(Called(tool="Bash", id=f"b{each}", at=at(3)) for each in range(3)),
    ]
    noted = item(50, note("Found it."), 2, call="n")
    view = drawer(entries, listed((noted, "Found it.")))
    top = view.blocks[0]
    assert isinstance(top, Fold)
    assert isinstance(top.content, list)
    assert [each.id for each in top.content] == ["calls 1", "item 50", "calls 5"]
    first = block(view.blocks, "calls 1")
    assert isinstance(first, Fold)
    assert isinstance(first.content, list)
    assert [each.id for each in first.content] == ["call r0", "call r1", "call r2"]


def test_a_call_s_line_stays_one_row_whole_under_its_fold() -> None:
    given = f"Run the {'whole ' * 30}gate"
    view = drawer(
        [
            Said(by="operator", text="Go.", at=at(0)),
            Called(tool="Bash", gist=given, id="t1", at=at(1)),
        ]
    )
    call = block(view.blocks, "call t1")
    assert isinstance(call, Fold)
    line = "".join(span.text for span in call.summary)
    assert len(line) <= 100
    assert line.startswith("· Bash: Run the whole")
    assert line.endswith("…")
    assert isinstance(call.content, Load)


def opened_call(read: Call | None, key: str = "t1", **part: object) -> Blocks:
    """Return the call's view of `read`, of the part named: as its fold opens with none, or as a fold in it does."""
    of = OfCall.model_validate(
        {"runtime": "claude", "session": "s1", "id": key, **part}
    )
    return call_blocks(of, read, view=Viewing.call)


def test_a_call_opened_shows_what_it_was_given_its_output_folded_read_as_that_opens() -> (
    None
):
    read = Call(
        id="t1",
        input={"command": "uv run pytest -q", "description": "Run the tests"},
        output="2 failed\n3 passed\n",
    )
    shown = opened_call(read)
    assert shown.text() == said(
        "command: uv run pytest -q",
        "description: Run the tests",
        "▸ output · 2 lines  [call id=t1 output=True]",
    )
    assert ids(shown.blocks) == [
        "input t1 command",
        "input t1 description",
        "output t1",
    ]
    output = block(shown.blocks, "output t1")
    assert isinstance(output, Fold)
    assert (output.kind, output.open, output.barred) == ("detail", False, True)
    assert output.content == Load(
        view="call",
        argument={
            "runtime": "claude",
            "session": "s1",
            "agent": None,
            "id": "t1",
            "output": True,
            "argument": None,
        },
    )
    # Read as it opens: what it returned, whole, on lines of its own.
    whole_output = opened_call(read, output=True)
    assert whole_output.text() == said("2 failed", "3 passed")
    assert ids(whole_output.blocks) == ["output t1.1", "output t1.2"]
    # Still running, it says so; once it's returned nothing, that; a call the record doesn't hold, that it wasn't read.
    running = Call(id="t2", input={"file_path": "/w/review.ts", "offset": 480})
    assert opened_call(running, "t2").text() == said(
        "file_path: /w/review.ts", "offset: 480", "output: none yet"
    )
    assert opened_call(Call(id="t2", input={"a": 1}, output=""), "t2").text() == said(
        "a: 1", "output: nothing"
    )
    assert opened_call(None, "t3").blocks == [
        Line.of("unread t3", "not read: its record doesn't hold the call", "muted")
    ]


def test_a_failed_call_says_so_on_its_output_s_line_text_given_is_laid_out_as_it_is() -> (
    None
):
    failed = Call(
        id="x",
        input="*** Begin Patch\n*** Update File: a.py\n*** End Patch",
        output="a.py: no such file",
        failed=True,
    )
    assert opened_call(failed, "x").text() == said(
        "*** Begin Patch",
        "*** Update File: a.py",
        "*** End Patch",
        "▸ failed · 1 line  [call id=x output=True]",
    )
    assert opened_call(failed, "x", output=True).text() == "a.py: no such file"


def test_a_call_s_arguments_are_each_on_a_line_several_lines_set_in_under_its_name_any_value_as_json() -> (
    None
):
    read = Call(
        id="t1",
        input={
            "question": "Which?\nOr neither?",
            "limit": 3,
            "tags": ["a"],
            "decisions": [
                {"text": "A model per kind, read by pydantic", "lean": "yes"},
                {"text": "A dict walked by hand, key by key", "lean": "no"},
            ],
        },
    )
    assert opened_call(read).text().splitlines() == [
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
        "output: none yet",
    ]
    assert len(ids(opened_call(read).blocks)) == len(set(ids(opened_call(read).blocks)))


def test_an_argument_too_long_to_read_at_a_glance_folds_in_its_place_read_whole_as_it_opens() -> (
    None
):
    content = "\n".join(f"line {each}" for each in range(58))
    prose = "word " * 300
    decisions: JsonValue = [
        {"text": f"Choice {each}", "lean": "no"} for each in range(9)
    ]
    read = Call(
        id="t1",
        input={
            "file_path": "/w/a.py",
            "content": content,
            "prose": prose,
            "decisions": decisions,
        },
    )
    shown = opened_call(read)
    assert shown.text().splitlines() == [
        "file_path: /w/a.py",
        "▸ content: line 0 · 58 lines  [call id=t1 argument=content]",
        f"▸ prose: {'word ' * 15}word… · 1 line  [call id=t1 argument=prose]",
        '▸ decisions: [{"text": "Choice 0", "lean": "no"}, {"text": "Choice 1", "lean": "no"},… · 38 lines  [call id=t1 argument=decisions]',
        "output: none yet",
    ]
    fold = block(shown.blocks, "argument t1 content")
    assert isinstance(fold, Fold)
    assert (fold.kind, fold.open, fold.barred) == ("detail", False, True)
    line = "".join(span.text for span in fold.summary)
    assert len(line) <= 100
    # Each read whole as it opens: the text as it is, any other value spread.
    assert opened_call(read, argument="content").text().splitlines() == [
        f"line {each}" for each in range(58)
    ]
    assert opened_call(read, argument="decisions").text().splitlines()[:3] == [
        "[",
        "  {",
        '    "text": "Choice 0",',
    ]
    # An argument it wasn't given reads as nothing there; a text it was given whole folds as `input`.
    assert opened_call(read, argument="absent").text() == "null"
    patch = Call(id="t2", input=content, output="ok")
    assert opened_call(patch, "t2").text().splitlines() == [
        "▸ input: line 0 · 58 lines  [call id=t2 argument=input]",
        "▸ output · 1 line  [call id=t2 output=True]",
    ]
    assert opened_call(patch, "t2", argument="input").text().splitlines()[0] == "line 0"


def test_a_long_output_is_read_only_as_its_fold_opens_the_call_s_fold_holding_its_input() -> (
    None
):
    read = Call(id="t1", input={"a": 1}, output="\n".join(["x"] * 5000))
    shown = opened_call(read)
    assert shown.text().splitlines()[-1].startswith("▸ output · 5000 lines")
    assert len(shown.model_dump_json()) < 2000


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
    # Their fold holds them, so a comment on them stays on them however it stands.
    fold = block(first.blocks, "said 1")
    assert isinstance(fold, Fold)
    assert (fold.kind, fold.open, fold.barred) == ("items", True, False)
    assert fold.content == [words]
    assert [span.tone for span in fold.summary] == ["muted"]
    # A comment's quote counts in that text, as the page's remarks do (`Remark.quote`).
    assert words.text[18:23] == "JSONL"
    latest = block(drawer(STEPS).blocks, "step 6")
    assert latest == Markdown(
        id="step 6", text="Twenty kinds of line.\n\nFour carry what was said."
    )


def test_the_agent_s_long_words_say_how_they_start_on_one_row_and_are_whole_under_it() -> (
    None
):
    long = f"{'word ' * 40}end."
    view = drawer([Said(by="agent", text=f"\n{long}\n\nThe rest.", at=at(0))])
    fold = block(view.blocks, "said 0")
    assert isinstance(fold, Fold)
    line = "".join(span.text for span in fold.summary)
    assert len(line) <= 100
    assert line.startswith("word word")
    assert line.endswith("…")
    assert fold.content == [Markdown(id="step 0", text=f"{long}\n\nThe rest.")]
    # Words with nothing in them have nothing to say how they start.
    assert drawer([Said(by="agent", text=" ", at=at(0))]).blocks == [
        Markdown(id="step 0", text="")
    ]


# The conversation growing


def test_what_arrives_is_added_at_the_end_everything_before_it_as_it_was() -> None:
    before = drawer(STEPS)
    after = drawer([*STEPS, *MORE])
    # The latest exchange takes in what came, each block before as it was: its calls go on, each a line.
    assert after.blocks[0] == before.blocks[0]
    latest, grown = before.blocks[-1], after.blocks[-1]
    assert isinstance(latest, Fold)
    assert isinstance(grown, Fold)
    assert isinstance(latest.content, list)
    assert isinstance(grown.content, list)
    assert grown.id == latest.id
    assert grown.content[: len(latest.content)] == latest.content
    assert after.text().endswith(
        "· Grep\n  · Grep\n  ▾ Found the four.\n    Found the four."
    )
    assert after.summary != before.summary
    # The earlier exchange reads as it did.
    assert exchange([*STEPS, *MORE], 0) == exchange(STEPS, 0)


def test_the_last_exchange_folds_once_the_operator_speaks_again_named_as_before() -> (
    None
):
    later: list[Entry] = [
        *STEPS,
        *MORE,
        *(Called(tool="Read", at=at(14)) for _ in range(3)),
    ]
    view = drawer(later)
    assert view.text().endswith(
        "▾ Found the four.\n    Found the four.\n"
        "  ▾ · 3 calls: Read x3\n    · Read\n    · Read\n    · Read"
    )
    spoke = drawer([*later, Said(by="operator", text="Good.", at=at(15))])
    assert folds(spoke.blocks) == [
        ["exchange 0", "earlier", "you: Look into reading transcripts."],
        ["exchange 5", "earlier", "you: Build the reader."],
    ]
    assert [each[0] for each in folds(exchange(later, 5).blocks)] == [
        "said 6",
        "said 9",
        "calls 10",
    ]
    # Their words with nothing under them yet are a line.
    assert spoke.text().endswith("you: Good.")
    assert isinstance(spoke.blocks[-1], Line)


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
            line.strip().removeprefix("▸ ").removeprefix("▾ ")
            for line in whole(view).splitlines()
        )
        if each.startswith(marks)
    ]


def test_each_item_is_a_line_its_text_under_it_one_sent_after_the_call_that_made_it_one_received_when_told() -> (
    None
):
    # Their last words came after it all: it's read, and it's what that fold shows.
    assert drawer(CALLED, EXCHANGED).text().splitlines() == [
        "trace · 7 steps",
        "▾ you: Look into reading transcripts.",
        "  ▸ 6 earlier steps, 4 items  [exchange step=0 through=6]",
    ]
    view = read_back(CALLED, EXCHANGED)
    assert whole(view) == said(
        "▾ Each session is a JSONL file.",
        "  Each session is a JSONL file.",
        "▸ · Bash  [call id=b1]",
        "▾ → @51 question to you · answered by @53 · Which parser?",
        "  Which parser?",
        "  1. A model per kind (lean: yes)",
        "  ▸ · mcp__lup__ask  [call id=q1]",
        "▸ · Read  [call id=r1]",
        "▾ ← @53 your answer to @51",
        "  Asked: Which parser?",
        "  1. A model per kind (lean: yes): leaning: they go with the lean.",
        "▾ Reading the second runtime's.",
        "  Reading the second runtime's.",
        "▾ → @52 note to you · answered by @54 · I assumed UTF-8.",
        "  I assumed UTF-8.",
        "▸ · Grep  [call id=g1]",
        "▾ ← @54 your reply to @52 · not told yet",
        "  Good.",
    )
    # Each item's text folds under its line, closed, set off by a bar; sent in its tone, received in its own.
    assert [each for each in folds(view.blocks) if each[0].startswith("item ")] == [
        ["item 51", "items", "→ @51 question to you · answered by @53 · Which parser?"],
        ["item 53", "items", "← @53 your answer to @51"],
        ["item 52", "items", "→ @52 note to you · answered by @54 · I assumed UTF-8."],
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
    assert [span.tone for span in question.summary] == ["sent", "muted"]


def test_a_call_that_only_sent_an_item_goes_under_its_line_a_write_flagged_keeps_its_own() -> (
    None
):
    held = item(
        55,
        HeldChange(
            text="Let the change land?",
            summary="AGENTS.md: the operator's",
            worktree=Path("/w"),
            key="k",
        ),
        4,
        call="r1",
    )
    view = drawer(
        CALLED, listed((ASKED, "Which parser?"), (held, "Let the change land?"))
    )
    # The `ask` is under its question, whose line stands for it; nothing else says it.
    assert block(view.blocks, "item 51") == Fold(
        id="item 51",
        kind="items",
        summary=[
            lup.Span(text="→ @51 question to you · answered by @53", tone="sent"),
            lup.Span(text=" · Which parser?", tone="muted"),
        ],
        barred=True,
        content=[
            Markdown(id="text 51", text="Which parser?"),
            block(view.blocks, "call q1"),
        ],
    )
    # The `Read` that wrote stands apart from the item lup made of it: they say different things.
    top = block(view.blocks, "exchange 0")
    assert isinstance(top, Fold)
    assert isinstance(top.content, list)
    assert [each.id for each in top.content] == [
        "said 1",
        "call b1",
        "item 51",
        "call r1",
        "item 55",
        "said 5",
        "call g1",
    ]
    assert "· Read" in whole(view)
    # An item whose call the record doesn't hold, or which has no text, is laid out without it.
    alone = drawer(STEPS[:2], listed((ASKED, "Which parser?")))
    assert block(alone.blocks, "item 51") == Fold(
        id="item 51",
        kind="items",
        summary=[
            lup.Span(text="→ @51 question to you · answered by @53", tone="sent"),
            lup.Span(text=" · Which parser?", tone="muted"),
        ],
        barred=True,
        content=[Markdown(id="text 51", text="Which parser?")],
    )


def test_a_call_read_apart_from_the_item_it_sent_keeps_its_own_line() -> None:
    # The mark folds the call, read; the item came after it was moved, new.
    late = ASKED.model_copy(
        update={"made": datetime(2026, 10, 18, 10, 3, 30, tzinfo=UTC)}
    )
    view = drawer(CALLED, listed((late, "Which parser?")), mark=marked(3, minute=3))
    assert "item 51" in ids(view.blocks)
    assert "call q1" not in ids(view.blocks)
    page = exchange_blocks(
        OfExchange(runtime="claude", session="s1", step=0, through=3),
        CALLED,
        listed((late, "Which parser?")),
        exchange=Viewing.exchange,
        call=Viewing.call,
        mark=marked(3, minute=3),
    )
    assert "call q1" in ids(page.blocks)
    assert "item 51" not in ids(page.blocks)


def test_an_item_s_line_says_how_its_text_starts_only_as_far_as_its_row_holds() -> None:
    long = f"{'word ' * 40}end."
    noted = item(52, note(long), 7)
    fold = block(drawer(CALLED, listed((noted, long))).blocks, "item 52")
    assert isinstance(fold, Fold)
    line = "".join(span.text for span in fold.summary)
    assert line.startswith("→ @52 note to you · unread · word word")
    assert line.endswith("…")
    assert len(line) <= 100
    # What they were sent says only what it is: they didn't say it, and its first line is as lup told it.
    told = item(54, note("Good.", of=52), 9, sender=OPERATOR, recipient=SESSION)
    fold = block(read_back(CALLED, listed((told, "Good."))).blocks, "item 54")
    assert isinstance(fold, Fold)
    assert [span.text for span in fold.summary] == [
        "← @54 your reply to @52 · not told yet"
    ]


def test_each_item_is_cited_by_at_and_its_number_which_nobody_takes_for_a_github_issue() -> (
    None
):
    assert not re.search(r"#\d", whole(read_back(CALLED, EXCHANGED)))


TURN_S_END = item(55, note("Reading the second runtime's.", ending=True), 8)
"""The note lup made of a turn's last words, which `CALLED`'s step 5 says."""


def test_a_turn_s_last_words_lup_made_a_note_of_fold_under_its_line_the_review_showing_them_as_an_item() -> (
    None
):
    beside = listed(
        (ASKED, "Which parser?"),
        (NOTED, "I assumed UTF-8."),
        (ANSWERED, "Asked."),
        (REPLIED, "Good."),
        (TURN_S_END, "Reading the second runtime's."),
    )
    view = read_back(CALLED, beside)
    fold = block(view.blocks, "said 5")
    assert fold == Fold(
        id="said 5",
        kind="items",
        summary=[
            lup.Span(text="→ @55 turn's end to you · unread", tone="sent"),
            lup.Span(text=" · Reading the second runtime's.", tone="muted"),
        ],
        barred=True,
        content=[Markdown(id="step 5", text="Reading the second runtime's.")],
    )
    # It stands once, where the words were, and no fold of an item says it again.
    assert "item 55" not in ids(view.blocks)
    assert whole(view).count("@55") == 1
    # Its words stay the step's block, which a comment on them is anchored to.
    assert block(view.blocks, "step 5") == block(drawer(CALLED).blocks, "step 5")


def test_a_message_keeps_its_fold_as_a_turn_s_end_arrives_saying_it_closed() -> None:
    before = block(drawer(CALLED).blocks, "said 5")
    after = block(
        drawer(CALLED, listed((TURN_S_END, "Reading the second runtime's."))).blocks,
        "said 5",
    )
    assert isinstance(before, Fold)
    assert isinstance(after, Fold)
    assert before.open
    assert not after.open
    assert before.content == after.content


def test_only_the_words_at_the_step_repeated_fold_the_latest_saying_them_by_then() -> (
    None
):
    entries: list[Entry] = [
        Said(by="agent", text="Done.", at=at(0)),
        Said(by="agent", text="Going on.", at=at(1)),
        Said(by="agent", text="Done.", at=at(2)),
        Said(by="agent", text="Done.", at=at(9)),
    ]
    ended = item(60, note("Done.", ending=True), 3)
    view = drawer(entries, listed((ended, "Done.")))
    assert [(each.id, each.open) for each in view.blocks if isinstance(each, Fold)] == [
        ("said 0", True),
        ("said 1", True),
        ("said 2", False),
        ("said 3", True),
    ]
    # Trailing spaces and blank lines aren't the words: the record and the hook may differ in them.
    spaced: list[Entry] = [
        Said(by="agent", text="Twenty kinds.\n\n\nFour.  \n", at=at(0))
    ]
    last = item(61, note("Twenty kinds.\n\nFour.", ending=True), 1)
    fold = block(
        drawer(spaced, listed((last, "Twenty kinds.\n\nFour."))).blocks, "said 0"
    )
    assert isinstance(fold, Fold)
    assert not fold.open


def test_a_turn_s_end_saying_what_no_step_says_stands_as_any_item() -> None:
    # A turn ended on the model's error, which says so in lup's words; or their words edited since.
    failed = item(62, note("Their turn ended on an error.", ending=True), 8)
    view = drawer(CALLED, listed((failed, "Their turn ended on an error.")))
    assert block(view.blocks, "item 62") == Fold(
        id="item 62",
        kind="items",
        summary=[
            lup.Span(text="→ @62 turn's end to you · unread", tone="sent"),
            lup.Span(text=" · Their turn ended on an error.", tone="muted"),
        ],
        barred=True,
        content=[Markdown(id="text 62", text="Their turn ended on an error.")],
    )
    fold = block(view.blocks, "said 5")
    assert isinstance(fold, Fold)
    assert fold.open
    # One made before the words it says, as a record's clock runs behind, repeats none of them.
    early = item(63, note("Reading the second runtime's.", ending=True), 1)
    beside = listed((early, "Reading the second runtime's."))
    assert "item 63" in ids(drawer(CALLED, beside).blocks)
    # Two items saying one step's words, in a record with no times: the later stands for it.
    timeless = [each.model_copy(update={"at": None}) for each in CALLED]
    again = item(64, note("Reading the second runtime's.", ending=True), 9)
    both = listed(
        (early, "Reading the second runtime's."),
        (again, "Reading the second runtime's."),
    )
    shown = drawer(timeless, both)
    fold = block(shown.blocks, "said 5")
    assert isinstance(fold, Fold)
    assert "@64" in fold.summary[0].text
    assert "item 63" in ids(shown.blocks)


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
        "▾ → @55 held change to you · declined · Let the change land?",
        "    Let the change land?",
        "    AGENTS.md: the operator's",
        "",
        "    your comment: Not this file.",
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
    session = read_back(STEPS[:3], listed((reply, "Right.")))
    subagent = read_back(
        STEPS[:3],
        listed((noted, "No cache."), (reply, "Right."), party=SURVEY),
        OfAgent(runtime="claude", session="s1", agent="a04"),
    )
    assert lines(session, "←", "→") == [
        "← @46 your reply to @44, for lup-impl/a04, which had ended"
    ]
    assert lines(subagent, "←", "→") == [
        "→ @44 note to you · answered by @46 · No cache.",
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
    view = read_back(STEPS[:3], listed((asked, "Which?"), (reply, "Right.")))
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
        (" · Which?", None),
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
        "▾ you: Go.",
        "  · Bash",
        "  ▸ → @60 note to you · unread · Early.",
        "  ▾ Ran it.",
        "    Ran it.",
        "  · Read",
        "  ▾ Read it.",
        "    Read it.",
        "  ▸ → @61 note to you · unread · Late.",
    ]
    timeless = [each.model_copy(update={"at": None}) for each in untimed]
    assert drawer(timeless, beside).text().splitlines()[1:] == [
        "▾ you: Go.",
        "  · Bash",
        "  ▾ Ran it.",
        "    Ran it.",
        "  · Read",
        "  ▾ Read it.",
        "    Read it.",
        "  ▸ → @60 note to you · unread · Early.",
        "  ▸ → @61 note to you · unread · Late.",
    ]


def test_an_item_before_the_operator_s_last_words_folds_in_its_exchange_one_before_their_first_words_counted_with_what_came_before() -> (
    None
):
    before = item(50, note("Early."), 4)
    assert "@50" not in drawer(STEPS, listed((before, "Early."))).text()
    assert [
        each[0] for each in folds(exchange(STEPS, 0, listed((before, "Early."))).blocks)
    ] == [
        "said 1",
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
    assert "▸ → @51 question to you · waiting on you · Which parser?" in before.text()

    def within(view: Blocks) -> list[Block]:
        """Return what's in the exchange `view` shows."""
        [fold] = view.blocks
        assert isinstance(fold, Fold)
        assert isinstance(fold.content, list)
        return fold.content

    # Their answer reads what came before it, the question among it, which says so as that fold opens.
    assert whole(read_back(CALLED, answered)).startswith(
        said(
            "▾ Each session is a JSONL file.",
            "  Each session is a JSONL file.",
            "▸ · Bash  [call id=b1]",
            "▾ → @51 question to you · answered by @53 · Which parser?",
            "  Which parser?",
            "  ▸ · mcp__lup__ask  [call id=q1]",
            "▸ · Read  [call id=r1]",
            "▾ ← @53 your answer to @51",
            "  Asked.",
        )
    )
    # Everything after it is as it was: nothing of it moved for the answer.
    assert [each.id for each in within(after)] == [
        "exchange 0 through 4",
        "said 5",
        "call g1",
    ]
    assert within(after)[1:] == within(before)[-2:]


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


def said_in(blocks: list[Block]) -> list[str]:
    """Return the agent's words among `blocks`, those inside folds among them, in order."""
    return [each.text for each in every(blocks) if isinstance(each, Markdown)]


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
    assert said_in(view.blocks) == [f"Word {each}." for each in range(5, 25)]
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
        "trace · 50 steps · 50 new",
        "▸ 11 earlier steps, 11 new  [exchange until_last=20]",
        "▾ Word 5.",
    ]
    # Twenty or fewer, nothing folds what came before them.
    assert not [
        each for each in folds(drawer(talking(20)).blocks) if each[1] == "earlier"
    ]


def test_a_turn_s_last_words_count_among_those_kept_so_turns_ends_alone_stay_small() -> (
    None
):
    """The cap keeps the drawer's answer small: words that fold are still in it."""
    entries: list[Entry] = [
        Said(by="agent", text=f"Word {each}.", at=at(each % 60)) for each in range(25)
    ]
    ends = [
        (
            item(100 + each, note(f"Word {each}.", ending=True), each % 60),
            f"Word {each}.",
        )
        for each in range(25)
    ]
    view = drawer(entries, listed(*ends))
    first = view.blocks[0]
    assert isinstance(first, Fold)
    assert first.id == "exchange before until last 20"
    assert len(view.blocks) == 21
    # None of those kept, being repeated, is open.
    assert not [
        each for each in view.blocks[1:] if isinstance(each, Fold) and each.open
    ]


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
    assert said_in(page.blocks) == [f"Word {each}." for each in range(5, 25)]
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
    assert said_in(last.blocks) == [f"Word {each}." for each in range(5)]
    assert not [each for each in folds(last.blocks) if each[1] == "earlier"]
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
        "trace · 9 steps · 8 new",
        "▾ you: Read them all.",
        "       Every record.",
        "  ▸ 5 earlier steps, 5 new  [exchange step=0 until_last=2]",
        "  ▾ Word 2.",
        "    Word 2.",
        "  · Bash",
        "  ▾ Word 3.",
        "    Word 3.",
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
    assert not [
        each
        for each in folds(drawer(talking(30), earlier=everything).blocks)
        if each[1] == "earlier"
    ]


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
        "trace · 20 steps · 10 new",
        "▸ 10 earlier steps  [exchange through=9]",
        "· Bash",
        "▾ Word 5.",
    ]
    first = view.blocks[0]
    assert isinstance(first, Fold)
    assert first.id == "exchange before through 9"
    assert view.offers == [READING]
    # Read to its last step, it's one line, nothing more to mark read.
    read = drawer(talking(10), mark=marked(19), reading=READING)
    assert read.text() == "trace · 20 steps\n▸ 20 earlier steps  [exchange through=19]"
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
    assert said_in(page.blocks) == [f"Word {each}." for each in range(5)]
    assert not [each for each in folds(page.blocks) if each[1] == "earlier"]


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
        "trace · 17 steps · 6 new",
        "▸ earlier · 10 steps, from 20m before your first words  [exchange]",
        "▾ you: Go on.",
        "  · Bash",
        "  ▾ Word 5.",
        "    Word 5.",
        "  · Bash",
        "  ▾ Word 6.",
        "    Word 6.",
        "  · Bash",
        "  ▾ Word 7.",
        "    Word 7.",
    ]
    # A mark after their words is the later.
    later = drawer(entries, mark=marked(13))
    assert later.text().splitlines()[2:5] == [
        "▾ you: Go on.",
        "  ▸ 3 earlier steps  [exchange step=10 through=13]",
        "  ▾ Word 6.",
    ]


def test_what_they_said_through_lup_reads_what_came_before_it_as_their_typed_words_do() -> (
    None
):
    # A session driven from the dashboard: nothing typed, the operator's words through lup alone.
    sent = item(
        80,
        note("Go on."),
        4,
        sender=OPERATOR,
        recipient=SESSION,
        state=Told(at=at(4), how="call"),
    )
    # `talking` has a call and words a minute each: what came by then is read.
    view = drawer(talking(10), listed((sent, "Go on.")), reading=READING)
    assert view.text().splitlines()[:2] == [
        "trace · 20 steps · 10 new",
        "▸ 10 earlier steps, 1 item  [exchange through=9]",
    ]
    assert view.offers == [READING]
    # Nothing since: nothing's new, and nothing's offered, though nothing was ever typed or marked.
    done = drawer(talking(4), listed((sent, "Go on.")), reading=READING)
    assert done.text().splitlines() == [
        "trace · 8 steps",
        "▸ 8 earlier steps, 1 item  [exchange through=7]",
    ]
    assert done.offers == []


def test_what_came_while_their_words_waited_to_be_told_stays_new() -> None:
    # Told at the agent's next hook, a long call later: the operator had read only what came by the time they said it.
    sent = item(
        80,
        note("Go on."),
        4,
        sender=OPERATOR,
        recipient=SESSION,
        state=Told(at=at(12), how="call"),
    )
    other = item(
        81,
        note("Meanwhile."),
        8,
        sender=SURVEY,
        recipient=SESSION,
        state=Told(at=at(8), how="call"),
    )
    view = drawer(talking(10), listed((sent, "Go on."), (other, "Meanwhile.")))
    assert view.text().splitlines()[:2] == [
        "trace · 20 steps · 10 new",
        "▸ 10 earlier steps  [exchange through=9]",
    ]
    assert "@81" in whole(view)
    assert "@80" in whole(view)


def test_a_subagent_s_record_says_what_their_parent_told_them_as_typed_which_reads_nothing() -> (
    None
):
    told: list[Entry] = [
        Said(by="operator", text="Find every call site.", at=at(0)),
        *talking(3, start=1),
    ]
    ran = conversation_blocks(
        OfAgent(runtime="claude", session="s1", agent="a04"),
        [
            *told,
            Said(by="operator", text="Now these.", at=at(30)),
            *talking(1, start=40),
        ],
        Exchanged(sent=[], received=[], parent=OfAgent(runtime="claude", session="s1")),
        exchange=Viewing.exchange,
        call=Viewing.call,
    )
    assert ran.text().splitlines()[0] == "trace · 10 steps · 10 new"


def test_a_drawer_long_unread_since_its_mark_keeps_the_cap_its_fold_saying_how_many_are_new() -> (
    None
):
    entries = talking(30)
    view = drawer(entries, mark=marked(9))
    assert view.text().splitlines()[:3] == [
        "trace · 60 steps · 50 new",
        "▸ 21 earlier steps, 11 new  [exchange until_last=20]",
        "▾ Word 10.",
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
        "▾ Word 5.",
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
    assert not [each for each in folds(earlier.blocks) if each[1] == "earlier"]


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
        "trace · 12 steps · 6 new",
        "▸ 6 earlier steps, 1 item  [exchange through=5]",
        "▸ → @51 note to you · unread · Late.",
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
        "▾ you: Go.",
        "  ▸ 1 earlier item  [exchange step=0 through=0]",
        "  ▾ Done.",
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
            view=Viewing.call,
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
        each.startswith(("exchange ", "said ", "calls ", "call ", "item "))
        for each in fold_ids
    )
    assert not any(
        each.startswith(("exchange ", "said ", "calls ", "call ")) for each in line_ids
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
        ("items", "m", "cyan", 2, "together"),
        ("calls", "k", "purple", 3, "together"),
        ("call", "d", "orange", 4, "deep"),
        ("detail", "x", "muted", 5, "deep"),
    ]
    assert [(each.name, each.like, each.colour) for each in TONES] == [
        ("call", None, "orange"),
        ("sent", "call", None),
        ("received", "operator", None),
        ("run", "muted", None),
    ]


# Both runtimes, from their own records


def claude_said(folder: Path) -> Path:
    """A Claude Code record of a turn: words, a command, a read, an edit and lup's `note`, and its last words."""

    def line(**fields: object) -> str:
        return json.dumps({"timestamp": "2026-10-18T10:00:00Z", **fields})

    def agent(*blocks: dict[str, object]) -> str:
        return line(
            type="assistant", message={"role": "assistant", "content": list(blocks)}
        )

    def call(id_: str, name: str, **given: object) -> dict[str, object]:
        return {"type": "tool_use", "id": id_, "name": name, "input": given}

    record = folder / "s1.jsonl"
    record.write_text(
        "\n".join(
            [
                line(
                    type="user",
                    origin={"kind": "human"},
                    promptSource="typed",
                    cwd="/w",
                    message={"role": "user", "content": "Fix it."},
                ),
                agent({"type": "text", "text": "On it."}),
                agent(
                    call(
                        "t1",
                        "Bash",
                        command="cd /w/tree/dev && uv run pytest -q",
                        description="Run the tests",
                    )
                ),
                agent(
                    call("t2", "Read", file_path="/w/page/src/review.ts", offset=480)
                ),
                agent(
                    call(
                        "t3",
                        "Edit",
                        file_path="/w/page/src/review.ts",
                        old_string="a",
                        new_string="b\nc",
                    )
                ),
                agent(call("t4", "mcp__lup__note", remark="I assumed UTF-8.")),
                agent({"type": "text", "text": "Fixed."}),
            ]
        )
        + "\n"
    )
    return record


def codex_said(folder: Path) -> Path:
    """A Codex rollout of the same turn: a shell's command, a patch, lup's `note`, and its last words."""

    def rolled(type_: str, payload: dict[str, object]) -> str:
        return json.dumps(
            {"timestamp": "2026-10-18T10:00:00Z", "type": type_, "payload": payload}
        )

    def called(id_: str, name: str, **given: object) -> str:
        return rolled(
            "response_item",
            {
                "type": "function_call",
                "name": name,
                "call_id": id_,
                "arguments": json.dumps(given),
            },
        )

    patch = "*** Begin Patch\n*** Update File: page/src/review.ts\n@@\n-a\n+b\n*** End Patch"
    rollout = folder / "rollout-2026-10-18T10-00-00-th-1.jsonl"
    rollout.write_text(
        "\n".join(
            [
                rolled(
                    "session_meta",
                    {
                        "id": "th-1",
                        "session_id": "th-1",
                        "cwd": "/w",
                        "history_mode": "legacy",
                    },
                ),
                rolled(
                    "event_msg",
                    {"type": "user_message", "message": "Fix it.", "images": []},
                ),
                rolled(
                    "event_msg",
                    {
                        "type": "agent_message",
                        "message": "On it.",
                        "phase": "commentary",
                    },
                ),
                called(
                    "t1",
                    "exec_command",
                    cmd="cd /w/tree/dev && uv run pytest -q",
                    workdir="/w",
                ),
                rolled(
                    "response_item",
                    {
                        "type": "custom_tool_call",
                        "name": "apply_patch",
                        "call_id": "t2",
                        "input": patch,
                    },
                ),
                called("t3", "write_stdin", session_id=4, chars="y"),
                called("t4", "mcp__lup__note", remark="I assumed UTF-8."),
                rolled(
                    "event_msg",
                    {
                        "type": "agent_message",
                        "message": "Fixed.",
                        "phase": "final_answer",
                    },
                ),
            ]
        )
        + "\n"
    )
    return rollout


@pytest.mark.parametrize(
    ("reader", "record", "run", "calls"),
    [
        (
            ClaudeTranscripts(),
            claude_said,
            "  ▾ · 3 calls: Bash, Read, Edit",
            [
                "· Bash: Run the tests · uv run pytest -q",
                "· Read: page/src/review.ts:480",
                "· Edit: page/src/review.ts -1 +2",
            ],
        ),
        (
            CodexTranscripts(),
            codex_said,
            "  ▾ · 3 calls: exec_command, apply_patch, write_stdin",
            [
                "· exec_command: uv run pytest -q",
                "· apply_patch: page/src/review.ts",
                "· write_stdin: session_id=4 · chars=y",
            ],
        ),
    ],
    ids=["claude", "codex"],
)
def test_each_runtime_s_record_lays_out_each_call_with_what_it_was_given_its_last_words_folded(
    tmp_path: Path,
    reader: Reader,
    record: Callable[[Path], Path],
    run: str,
    calls: list[str],
) -> None:
    entries = reader.read(record(tmp_path)).entries
    sent = item(
        70,
        note("I assumed UTF-8."),
        0,
        call="t4",
        made=datetime(2026, 10, 18, 10, 0, tzinfo=UTC),
    )
    ended = item(
        71,
        note("Fixed.", ending=True),
        0,
        made=datetime(2026, 10, 18, 10, 0, 1, tzinfo=UTC),
    )
    beside = listed((sent, "I assumed UTF-8."), (ended, "Fixed."))
    view = drawer(entries, beside)
    assert [
        line
        for line in view.text().splitlines()[1:]
        if not line.startswith("    ") or line.startswith("    ▸")
    ] == [
        "▾ you: Fix it.",
        "  ▾ On it.",
        run,
        *(f"    ▸ {call}  [call id=t{at}]" for at, call in enumerate(calls, start=1)),
        "  ▸ → @70 note to you · unread · I assumed UTF-8.",
        "  ▸ → @71 turn's end to you · unread · Fixed.",
    ]
    # Each last word, and each `note`, folds: only what no item says stays open.
    fold = block(view.blocks, "item 70")
    assert isinstance(fold, Fold)
    assert "call t4" in ids(fold.content if isinstance(fold.content, list) else [])
    assert isinstance(block(view.blocks, "step 1"), Markdown)
