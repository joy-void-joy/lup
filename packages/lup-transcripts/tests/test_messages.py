"""An agent's messages laid out in blocks: the drawer of their words alone, as the page draws it and as its text form reads, from either runtime's record."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel

import lup
from lup.blocks import (
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
from lup_dev.host.records import Called, Entry, Reader, Said
from lup_dev.inbox.marks import ReviewMark
from lup_dev.inbox.protocol import Exchanged, Pathed, exchanged
from lup_dev.inbox.store import (
    Done,
    Ended,
    Flagged,
    Friction,
    Item,
    Message,
    Reason,
    Told,
    Unresolved,
)
from lup_ledger.parties import Conversation, Operator
from lup_transcripts.environment.conversation import EARLIER_KIND, inboxed
from lup_transcripts.environment.messages import (
    OfMessages,
    earlier_messages_blocks,
    messages_blocks,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class Viewing(BaseModel):
    """The view its fold of what came earlier reads, as `TranscriptsServing` serves it."""

    @lup.view
    async def earlier_messages(self, viewed: OfMessages) -> Blocks:
        """What came earlier among the messages."""
        del viewed
        return Blocks()


def at(minute: int) -> datetime:
    return datetime(2026, 10, 18, 10, minute, tzinfo=UTC)


REPOSITORY = Path("/r.git")
SESSION = Conversation(repository=REPOSITORY, runtime="claude", session="s1")
WORKER = SESSION.model_copy(update={"agent": "a1"})
OF_SESSION = OfAgent(runtime="claude", session="s1")
OF_WORKER = OfAgent(runtime="claude", session="s1", agent="a1")
PATHS = [
    Pathed(conversation=SESSION, path="lup-impl"),
    Pathed(conversation=WORKER, path="lup-impl/parser"),
]


def item(number: int, reason: Reason, minute: int, **fields: object) -> Item:
    """An item of the session's, sent to the operator unless `fields` say otherwise."""
    return Item.model_validate(
        {
            "number": number,
            "reason": reason,
            "sender": SESSION,
            "recipient": Operator(),
            "made": at(minute),
            **fields,
        }
    )


def note(text: str, *, ending: bool = False, to: Conversation | None = None) -> Message:
    return Message(kind="note", text=text, ending=ending, to=to)


def listed(
    *items: Item,
    party: Conversation = SESSION,
    parent: Conversation | None = None,
    read: Callable[[Item], str] | None = None,
) -> Exchanged:
    """Return what `party` exchanged as the core lists it, each text the message's own."""

    def text(each: Item) -> str:
        return each.reason.text if isinstance(each.reason, Message) else ""

    return exchanged(
        party,
        list(items),
        written=text,
        told=text,
        paths=PATHS,
        read=read or text,
        parent=parent,
    )


def drawer(
    entries: list[Entry],
    beside: Exchanged | None = None,
    of: OfAgent = OF_SESSION,
    *,
    earlier: FoldKind = EARLIER_KIND,
    mark: ReviewMark | None = None,
    reading: Offer | None = None,
    report: Callable[[OfAgent], str] | None = None,
    brief: str | None = None,
) -> Blocks:
    return messages_blocks(
        of,
        entries,
        beside or listed(),
        view=Viewing.earlier_messages,
        earlier=earlier,
        mark=mark,
        reading=reading,
        report=report or (lambda _: ""),
        brief=brief,
    )


def every(blocks: list[Block]) -> list[Block]:
    """Return `blocks` and each within their folds whose content is given."""
    return [
        each
        for block in blocks
        for each in [
            block,
            *(
                every(block.content)
                if isinstance(block, Fold) and isinstance(block.content, list)
                else []
            ),
        ]
    ]


def headings(view: Blocks) -> list[str]:
    """Return the line each message is under, in order, and the line of the fold of what came earlier."""
    return [
        "".join(span.text for span in block.summary)
        if isinstance(block, Fold)
        else block.said()
        for block in view.blocks
        if isinstance(block, Fold | Line)
    ]


def markdown(view: Blocks, key: str) -> Markdown:
    [found] = [
        each
        for each in every(view.blocks)
        if isinstance(each, Markdown) and each.id == key
    ]
    return found


def marked(step: int, minute: int = 59) -> ReviewMark:
    return ReviewMark(key={}, up_to=str(step), at=at(minute))


TALK: list[Entry] = [
    Said(by="operator", text="Look into reading transcripts.", at=at(0)),
    Said(by="agent", text="Reading them.", at=at(1)),
    Called(tool="Bash", id="b1", at=at(2)),
    Said(by="agent", text="Each session is a JSONL file.", at=at(3)),
    Said(by="operator", text="Build the reader.", at=at(9)),
    Said(by="agent", text="On it.", at=at(10)),
    Called(tool="Grep", id="g1", at=at(11)),
]


def test_it_holds_the_words_alone_what_the_operator_typed_and_their_turn_s_end_never_a_call_nor_the_agent_s_words_as_their_turn_goes_on() -> (
    None
):
    view = drawer(TALK, listed())
    assert view.text().splitlines() == [
        "messages · 3",
        "▾ you → lup-impl",
        "  Look into reading transcripts.",
        "▾ lup-impl · their last words",
        "  Each session is a JSONL file.",
        "▾ you → lup-impl",
        "  Build the reader.",
    ]


def test_a_conversation_with_nothing_said_is_no_drawer() -> None:
    assert drawer([]) == Blocks()
    assert drawer([Called(tool="Bash", at=at(0))]) == Blocks()


def test_a_message_between_agents_is_in_both_their_drawers_saying_who_s_talking_to_whom_and_the_operator_s_copy_is_in_neither() -> (
    None
):
    sent = item(
        60,
        note("The brief was wrong."),
        4,
        sender=WORKER,
        recipient=SESSION,
        state=Told(at=at(5), how="call"),
    )
    copy = item(
        61,
        note("The brief was wrong.", to=SESSION),
        4,
        sender=WORKER,
        state=Done(at=at(4)),
    )
    worker = drawer([], listed(sent, copy, party=WORKER, parent=SESSION), OF_WORKER)
    parent = drawer(TALK[:1], listed(sent, copy))
    assert headings(worker) == [
        "@60 lup-impl/parser → lup-impl · note · new",
    ]
    assert headings(parent) == [
        "you → lup-impl",
        "@60 lup-impl/parser → lup-impl · note · new",
    ]
    # The copy isn't in the trace either: what the two exchanged is the message.
    assert [each.number for each in inboxed(listed(sent, copy, party=WORKER))] == [60]


def test_a_comment_on_another_agent_s_words_goes_to_them_wherever_it_s_written_on_their_own_to_their_drawer_s_agent() -> (
    None
):
    from_worker = item(60, note("Found it."), 4, sender=WORKER, recipient=SESSION)
    own = item(61, note("Thanks."), 5, recipient=WORKER)
    parent = drawer(TALK[:1], listed(from_worker, own))
    assert markdown(parent, "text 60").by == OF_WORKER
    assert markdown(parent, "text 61").by is None
    assert markdown(parent, "step 0").by is None
    # In the worker's own drawer, what their parent wrote goes to their parent.
    worker = drawer(
        [], listed(from_worker, own, party=WORKER, parent=SESSION), OF_WORKER
    )
    assert markdown(worker, "text 60").by is None
    assert markdown(worker, "text 61").by == OF_SESSION


def test_what_the_operator_sends_through_lup_is_read_back_rather_than_told_in_tags_and_stays_an_item_for_them_where_they_re_told_it() -> (
    None
):
    said = item(50, note("Which parser?"), 1)
    review = item(
        51,
        note("<on item='50'>Tags are the agent's.</on>"),
        2,
        sender=Operator(),
        recipient=SESSION,
        state=Told(at=at(3), how="call"),
    )
    view = drawer(
        TALK[:1],
        listed(
            said,
            review,
            read=lambda each: (
                "> Which?\n\nA model." if each.number == 51 else "Which parser?"
            ),
        ),
    )
    assert headings(view) == [
        "you → lup-impl",
        "@50 lup-impl → you · note · unread",
        "@51 you → lup-impl · message",
    ]
    assert markdown(view, "text 51").text == "> Which?\n\nA model."


def test_a_friction_a_how_it_felt_and_a_note_to_the_operator_show_and_what_s_no_words_doesn_t() -> (
    None
):
    friction = item(50, Friction(text="The gate hung."), 1)
    # The copy of it their parent is told, the same words again.
    quiet = item(
        51,
        Friction(text="The gate hung."),
        1,
        recipient=SESSION,
        quiet=True,
        sender=WORKER,
    )
    flagged = item(
        52,
        Flagged(
            text="a.py landed, flagged.",
            summary="a.py",
            worktree=Path("/w"),
            path=Path("a.py"),
        ),
        2,
    )
    unresolved = item(53, Unresolved(of=50, citations=[]), 3, recipient=SESSION)
    noted = item(54, note("I assumed UTF-8."), 4)
    view = drawer(TALK[:1], listed(friction, flagged, unresolved, noted))
    assert headings(view) == [
        "you → lup-impl",
        "@50 lup-impl → you · friction · unread · new",
        "@54 lup-impl → you · note · unread · new",
    ]
    # In the parent's drawer the friction they're told shows; in the worker's, what they told the operator alone.
    worker_said = item(50, Friction(text="The gate hung."), 1, sender=WORKER)
    worker = drawer([], listed(worker_said, quiet, party=WORKER), OF_WORKER)
    assert headings(worker) == ["@50 lup-impl/parser → you · friction · unread · new"]
    parent = drawer(TALK[:1], listed(quiet))
    assert headings(parent)[1:] == [
        "@51 lup-impl/parser → lup-impl · friction · not told yet · new"
    ]


def test_a_turn_s_end_an_item_repeats_stands_under_that_item_s_heading_its_words_the_step_s() -> (
    None
):
    ended = item(55, note("Each session is a JSONL file.", ending=True), 3)
    view = drawer(TALK[:5], listed(ended))
    assert headings(view) == [
        "you → lup-impl",
        "@55 lup-impl → you · turn's end · unread",
        "you → lup-impl",
    ]
    assert markdown(view, "step 3").text == "Each session is a JSONL file."


def test_a_subagent_s_drawer_opens_on_what_spawned_them_and_ends_on_their_last_words_a_comment_on_the_brief_to_their_parent() -> (
    None
):
    steps: list[Entry] = [
        Said(by="agent", text="Looking.", at=at(1)),
        Called(tool="Grep", id="g1", at=at(2)),
        Said(by="agent", text="Done: three call sites.", at=at(3)),
    ]
    view = drawer(
        steps,
        listed(party=WORKER, parent=SESSION),
        OF_WORKER,
        brief="Find every call site.",
    )
    assert headings(view) == [
        "lup-impl → lup-impl/parser · new",
        "lup-impl/parser → lup-impl · their last words · new",
    ]
    assert markdown(view, "step -1").text == "Find every call site."
    assert markdown(view, "step -1").by == OF_SESSION
    assert markdown(view, "step 2").by is None
    # While they go on, words before a call are the trace's.
    assert (
        headings(drawer(steps[:2], listed(party=WORKER, parent=SESSION), OF_WORKER))
        == []
    )


def test_a_subagent_s_end_says_their_last_words_in_their_parent_s_drawer_read_from_their_record_as_it_s_shown() -> (
    None
):
    handed = item(
        70,
        Ended(name="parser", handed=True, said="Done."),
        4,
        sender=WORKER,
        recipient=SESSION,
        quiet=True,
        state=Told(at=at(5), how="call"),
    )
    asked: list[OfAgent] = []

    def report(of: OfAgent) -> str:
        asked.append(of)
        return "Done: three call sites."

    view = drawer(TALK[:1], listed(handed, read=lambda _: ""), report=report)
    assert headings(view) == [
        "you → lup-impl",
        "@70 lup-impl/parser → lup-impl · ended · new",
    ]
    assert markdown(view, "text 70").text == "Done: three call sites."
    assert markdown(view, "text 70").by == OF_WORKER
    assert asked == [OF_WORKER]
    # Stopped, there are no such words: only what lup says of it, a line alone where it says nothing.
    stopped = item(
        71,
        Ended(name="parser", stopped=True),
        4,
        sender=WORKER,
        recipient=SESSION,
        quiet=True,
    )
    assert isinstance(
        next(
            each
            for each in drawer(
                TALK[:1], listed(stopped, read=lambda _: ""), report=report
            ).blocks
            if each.id == "item 71 line"
        ),
        Line,
    )


def many(count: int) -> Exchanged:
    """Return `count` notes the worker sent the session, told, a minute apart."""
    return listed(
        *(
            item(
                100 + each,
                note(f"Note {each}."),
                0,
                made=datetime(2026, 10, 18, 10, 0, each % 60, tzinfo=UTC),
                sender=WORKER,
                recipient=SESSION,
                state=Told(
                    at=datetime(2026, 10, 18, 10, 0, each % 60, tzinfo=UTC), how="call"
                ),
            )
            for each in range(count)
        )
    )


def test_at_most_the_last_twenty_stay_open_what_came_before_under_one_line_read_as_it_opens_twenty_more_each_time() -> (
    None
):
    beside = many(50)
    view = drawer([], beside)
    [fold, *shown] = view.blocks
    assert view.text().splitlines()[0] == "messages · 50 · 50 new"
    assert isinstance(fold, Fold)
    assert fold.id == "messages until last 20"
    assert "".join(span.text for span in fold.summary) == "30 earlier messages, 30 new"
    assert isinstance(fold.content, Load)
    assert fold.content.view == "earlier_messages"
    assert fold.content.argument["until_last"] == 20
    assert len(shown) == 20
    earlier = earlier_messages_blocks(
        OfMessages(**fold.content.argument),  # pyright: ignore[reportArgumentType]
        [],
        beside,
        view=Viewing.earlier_messages,
    )
    [deeper, *more] = earlier.blocks
    assert isinstance(deeper, Fold)
    assert deeper.id == "messages until last 40"
    assert len(more) == 20
    # Its id stays as another comes, so a fold the operator opened stays open.
    assert drawer([], many(51)).blocks[0].id == "messages until last 20"


def test_a_person_s_layer_keeps_more_of_them_open_or_all() -> None:
    all_open = EARLIER_KIND.model_copy(update={"keeps_open": None})
    assert len(drawer([], many(50), earlier=all_open).blocks) == 50
    some = EARLIER_KIND.model_copy(update={"keeps_open": 5})
    assert len(drawer([], many(50), earlier=some).blocks) == 6


def test_what_came_before_its_mark_folds_but_for_the_last_three_read_so_it_opens_on_where_the_exchange_stands() -> (
    None
):
    entries: list[Entry] = [
        Said(by="operator", text=f"Word {each}.", at=at(each)) for each in range(5)
    ]
    entries.append(Said(by="agent", text="Answered.", at=at(10)))
    ended = listed(item(60, note("Answered.", ending=True), 11))
    # Everything read: what's before the last three folded, nothing new.
    all_read = drawer(entries, ended, mark=marked(5, 59))
    assert headings(all_read)[0] == "3 earlier messages"
    assert all_read.blocks[0].id == "messages through step 2"
    assert "new" not in all_read.text()
    # Their own typed words read what came before them, the rest new.
    typed = drawer(entries, ended)
    assert typed.text().splitlines()[0] == "messages · 6 · 1 new"
    assert headings(typed)[-1].endswith("· new")


def test_what_they_said_through_lup_reads_what_came_before_it_and_the_drawer_offers_its_mark_only_where_any_are_new() -> (
    None
):
    offer = Offer(action="review-mark", verb="done", says="mark it read")
    said = item(
        60,
        note("One."),
        1,
        sender=WORKER,
        recipient=SESSION,
        state=Told(at=at(1), how="call"),
    )
    answered = item(
        61,
        note("Fine."),
        2,
        sender=Operator(),
        recipient=SESSION,
        state=Told(at=at(2), how="call"),
    )
    after = item(
        62,
        note("Two."),
        3,
        sender=WORKER,
        recipient=SESSION,
        state=Told(at=at(3), how="call"),
    )
    view = drawer([], listed(said, answered, after), reading=offer)
    assert view.text().splitlines()[0] == "messages · 3 · 1 new"
    assert view.offers == [offer]
    assert headings(view) == [
        "@60 lup-impl/parser → lup-impl · note",
        "@61 you → lup-impl · message",
        "@62 lup-impl/parser → lup-impl · note · new",
    ]
    read = drawer([], listed(said, answered), reading=offer)
    assert read.offers == []


def test_the_fold_of_what_they_read_reads_up_to_the_message_it_names_and_nothing_where_it_s_gone() -> (
    None
):
    entries: list[Entry] = [
        Said(by="operator", text=f"Word {each}.", at=at(each)) for each in range(6)
    ]
    view = drawer(entries, mark=marked(5))
    fold = view.blocks[0]
    assert isinstance(fold, Fold)
    assert isinstance(fold.content, Load)
    of = OfMessages(**fold.content.argument)  # pyright: ignore[reportArgumentType]
    assert of.through == "step 2"
    earlier = earlier_messages_blocks(
        of, entries, listed(), view=Viewing.earlier_messages
    )
    assert [each.id for each in earlier.blocks] == ["said 0", "said 1", "said 2"]
    gone = of.model_copy(update={"through": "item 9"})
    assert (
        earlier_messages_blocks(gone, entries, listed(), view=Viewing.earlier_messages)
        == Blocks()
    )


def claude_said(folder: Path) -> Path:
    """A Claude Code session's record: the operator's words, the agent's as their turn goes on, a call, and their turn's last words."""

    def line(**fields: object) -> str:
        return json.dumps({"timestamp": "2026-10-18T10:00:00Z", **fields})

    def agent(*blocks: dict[str, object]) -> str:
        return line(
            type="assistant", message={"role": "assistant", "content": list(blocks)}
        )

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
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Bash",
                        "input": {"command": "ls"},
                    }
                ),
                agent({"type": "text", "text": "Fixed."}),
            ]
        )
        + "\n"
    )
    return record


def codex_said(folder: Path) -> Path:
    """A Codex thread's rollout of the same turn."""

    def rolled(type_: str, payload: dict[str, object]) -> str:
        return json.dumps(
            {"timestamp": "2026-10-18T10:00:00Z", "type": type_, "payload": payload}
        )

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
                rolled(
                    "response_item",
                    {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "t1",
                        "arguments": json.dumps({"cmd": "ls"}),
                    },
                ),
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
    ("reader", "record"),
    [(ClaudeTranscripts(), claude_said), (CodexTranscripts(), codex_said)],
    ids=["claude", "codex"],
)
def test_each_runtime_s_record_gives_the_same_words_the_operator_s_their_turn_s_end_and_no_call(
    tmp_path: Path, reader: Reader, record: Callable[[Path], Path]
) -> None:
    entries = reader.read(record(tmp_path)).entries
    ended = item(
        71,
        note("Fixed.", ending=True),
        0,
        made=datetime(2026, 10, 18, 10, 0, 1, tzinfo=UTC),
    )
    view = drawer(entries, listed(ended))
    assert view.text().splitlines() == [
        "messages · 2 · 1 new",
        "▾ you → lup-impl",
        "  Fix it.",
        "▾ @71 lup-impl → you · turn's end · unread · new",
        "  Fixed.",
    ]


def test_what_a_subagent_s_record_says_spawned_them_is_their_brief_on_claude_code_codex_keeping_it_among_their_steps(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "subagents"
    folder.mkdir()
    claude = folder / "agent-a1.jsonl"
    claude.write_text(
        json.dumps(
            {
                "timestamp": "2026-10-18T10:00:00Z",
                "type": "user",
                "isSidechain": True,
                "message": {"role": "user", "content": "Find every call site."},
            }
        )
        + "\n"
        + json.dumps(
            {
                "timestamp": "2026-10-18T10:00:01Z",
                "type": "assistant",
                "isSidechain": True,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Three."}],
                },
            }
        )
        + "\n"
    )
    read = ClaudeTranscripts().read(claude)
    assert read.brief == "Find every call site."
    assert read.entries == [Said(by="agent", text="Three.", at=read.entries[0].at)]
    # A session's own record has none: their first line is the operator's words.
    assert ClaudeTranscripts().read(claude_said(tmp_path)).brief is None
    assert CodexTranscripts().read(codex_said(tmp_path)).brief is None


def test_a_subagent_s_steps_their_parent_said_as_a_runtime_records_what_spawned_them_read_from_their_parent() -> (
    None
):
    # Codex's first `spawn_agent` writes its message in the subagent's rollout as words typed.
    steps: list[Entry] = [
        Said(by="operator", text="Find every call site.", at=at(0)),
        Said(by="agent", text="Three.", at=at(1)),
    ]
    view = drawer(steps, listed(party=WORKER, parent=SESSION), OF_WORKER)
    assert headings(view)[0] == "lup-impl → lup-impl/parser"
    assert markdown(view, "step 0").by == OF_SESSION
