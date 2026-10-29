"""The inbox on the ledger: each item a node and each change a version, where it stands and what it answers edges; attachments; conversations' whereabouts, the draft, the order and talks plain records; the files of an earlier lup converted once, and the rehearsal of that conversion."""

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.inbox.conversion import converted, rehearsed
from lup_dev.inbox.store import (
    KINDS,
    Answer,
    Answered,
    Answers,
    Approval,
    ChangedFile,
    ChangedFiles,
    Citation,
    Cites,
    Decided,
    Diff,
    Done,
    Draft,
    Edit,
    Flagged,
    Inbox,
    Item,
    ItemNode,
    Message,
    Order,
    Question,
    Replies,
    Stands,
    StandsAnswered,
    StandsSuperseded,
    StandsTold,
    StandsWaiting,
    StandsWithdrawn,
    Superseded,
    Talk,
    TalkComment,
    Told,
    Waiting,
    Whereabouts,
    Withdrawn,
)
from lup_dev.layout import InboxLayout, Layout
from lup_dev.settings import LupDevSettings
from lup_dev.stored import write_model
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.parties import Conversation, Lup, Operator
from lup_ledger.records import Edge, Node

if TYPE_CHECKING:
    import pytest

REPOSITORY = Path("/work/lup.git")
OTHER = Path("/work/other.git")
MAIN = Conversation(repository=REPOSITORY, runtime="claude", session="s1")
WORKER = MAIN.model_copy(update={"agent": "a1"})
START = datetime(2026, 10, 1, 12, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return START + timedelta(minutes=minutes)


def opened(home: Path) -> Ledger:
    return Ledger.opened(LedgerLayout(home=home), KINDS)


def item(
    number: int,
    reason: Message | Question | Answer | Flagged | Approval,
    **fields: object,
) -> Item:
    stored = {
        "number": number,
        "reason": reason,
        "sender": MAIN,
        "recipient": Operator(),
        "made": at(number),
        **fields,
    }
    return Item.model_validate(stored)


def stored_items() -> list[Item]:
    """An earlier lup's inbox, in a few items: a question answered, a turn's end answering the answer and citing it, a note replied to, a flagged write approved, an approval superseded by the next, one taken back, one announced, one between the operator and themselves, an answer to a question that isn't there."""
    cite = Citation(said="@2.1", start=0, end=4, item=2, part=1)
    return [
        item(1, Question(text="Which?"), state=Answered(at=at(2), answer=2)),
        item(
            2,
            Answer(question=1, comment="This one."),
            sender=Operator(),
            recipient=MAIN,
            state=Told(at=at(3), how="call"),
        ),
        item(
            3,
            Message(kind="note", text="@2.1 done.", ending=True, answers=[2]),
            citations=[cite],
            edits=[Edit(at=at(30), before="Done.")],
            state=Done(at=at(31)),
        ),
        item(
            4, Message(kind="note", text="A note."), sender=WORKER, state=Done(at=at(5))
        ),
        item(
            5,
            Message(kind="note", text="Thanks.", of=4),
            sender=Operator(),
            recipient=MAIN,
            addressed=WORKER,
            state=Told(at=at(6), how="start"),
        ),
        item(
            6,
            Flagged(
                text="A write", summary="s", worktree=Path("/w"), path=Path("a.py")
            ),
            sender=WORKER,
            state=Decided(at=at(7), approved=True),
        ),
        item(
            7,
            Approval(text="?", summary="s", repository=REPOSITORY, fingerprint="f1"),
            sender=Operator(),
            state=Superseded(at=at(8), by=8),
        ),
        item(
            8,
            Approval(text="?", summary="s", repository=REPOSITORY, fingerprint="f2"),
            sender=Operator(),
            state=Decided(at=at(9), approved=False, comment="No."),
        ),
        item(
            9,
            Message(kind="note", text="Taken back."),
            state=Withdrawn(at=at(10), why="Wrong."),
        ),
        item(10, Message(kind="note", text="Long."), state=Waiting(announced=at(11))),
        item(11, Message(kind="note", text="To myself."), sender=Operator()),
        item(12, Answer(question=99), sender=Operator(), recipient=MAIN),
    ]


def stored(home: Path) -> InboxLayout:
    """Write `stored_items` as an earlier lup's inbox kept them, with their whereabouts, attachments, draft, order and a talk."""
    layout = InboxLayout(home=home)
    for each in stored_items():
        write_model(layout.item(each.number), each)
    for number in (6, 7, 8):
        write_model(layout.diff(number), Diff(text=f"+ line {number}"))
        write_model(
            layout.changed(number),
            ChangedFiles(
                files=[ChangedFile.of(Path("a.py"), b"a", f"b{number}".encode())]
            ),
        )
    for place in [
        Whereabouts(conversation=MAIN, launch="l1", worktree=Path("/w"), since=at(0)),
        Whereabouts(
            conversation=WORKER,
            launch="l1",
            worktree=Path("/w"),
            since=at(1),
            ended=at(20),
            parent=MAIN,
            name="parser",
            held=["Parsed."],
        ),
    ]:
        write_model(layout.party(place.conversation.key()), place)
    write_model(layout.draft, Draft(done=[3], parked=[4]))
    write_model(layout.order, Order(places=["agent:s1"]))
    write_model(
        layout.talk(MAIN.key()), Talk(comments=[TalkComment(step=1, text="Hm.")])
    )
    return layout


def test_the_files_are_converted_once_each_item_keeping_its_number_and_where_it_stands(
    tmp_path: Path,
) -> None:
    layout = stored(tmp_path / "inbox")
    before = {
        path: path.read_bytes() for path in layout.home.rglob("*") if path.is_file()
    }
    ledger = opened(tmp_path / "ledger")

    kept = converted(ledger, layout)
    inbox = Inbox.opened(ledger)

    assert kept is not None
    assert (
        kept.items,
        kept.conversations,
        kept.states,
        kept.attachments,
        kept.talks,
    ) == (12, 2, 10, 6, 1)
    assert kept.nowhere == 1
    assert inbox.items == {each.number: each for each in stored_items()}
    assert inbox.whereabouts[WORKER.key()].name == "parser"
    assert ledger.numbered() == 13
    assert inbox.draft() == Draft(done=[3], parked=[4])
    assert inbox.order() == Order(places=["agent:s1"])
    assert inbox.talk(MAIN) == Talk(comments=[TalkComment(step=1, text="Hm.")])
    assert inbox.diff(6) == "+ line 6"
    assert inbox.files(8) == [ChangedFile.of(Path("a.py"), b"a", b"b8")]
    assert ledger.node(11, ItemNode).repository == Path("/")
    assert converted(ledger, layout) is None
    assert {
        path: path.read_bytes() for path in layout.home.rglob("*") if path.is_file()
    } == before


def test_where_an_item_stands_is_read_from_the_edges_drawn_to_it(
    tmp_path: Path,
) -> None:
    ledger = opened(tmp_path / "ledger")
    converted(ledger, stored(tmp_path / "inbox"))

    assert ledger.drawn_to(1, Stands) == [
        StandsAnswered(
            target=1,
            source=2,
            repository=REPOSITORY,
            by=Operator(),
            at=at(2),
            state=Answered(at=at(2), answer=2),
        )
    ]
    assert ledger.drawn_to(7, StandsSuperseded)[0].source == 8
    assert ledger.drawn_to(9, StandsWithdrawn)[0].by == MAIN
    assert ledger.drawn_to(10, StandsWaiting)[0].by == Lup()
    assert ledger.drawn_to(11, Stands) == []
    assert "state" not in ledger.node(1, ItemNode).model_dump()


def test_what_an_item_answers_replies_to_and_cites_is_drawn_from_its_fields(
    tmp_path: Path,
) -> None:
    ledger = opened(tmp_path / "ledger")
    converted(ledger, stored(tmp_path / "inbox"))

    def links(number: int) -> list[str]:
        return [
            f"{each.kind} @{each.target}"
            for each in ledger.drawn_from(number, Edge, current=True)
            if isinstance(each, Answers | Replies | Cites)
        ]

    assert links(2) == ["inbox:answers @1"]
    assert links(3) == ["inbox:answers @2", "inbox:cites @2"]
    assert ledger.drawn_from(3, Cites)[0].part == 1
    assert links(5) == ["inbox:replies @4"]
    assert links(12) == []


def test_a_state_changed_is_an_edge_and_a_change_to_what_it_says_a_version(
    tmp_path: Path,
) -> None:
    ledger = opened(tmp_path / "ledger")
    inbox = Inbox.opened(ledger)
    made = inbox.made(Message(kind="note", text="One."), MAIN, Operator(), None, at(0))
    told = inbox.kept(made.model_copy(update={"state": Told(at=at(1), how="call")}))
    edited = inbox.kept(
        told.model_copy(
            update={
                "reason": Message(kind="note", text="Two."),
                "edits": [Edit(at=at(2), before="One.")],
            }
        )
    )
    inbox.kept(edited.model_copy(update={"state": Waiting()}))

    versions = ledger.versions(made.number)
    assert [each.reason for each in versions if isinstance(each, ItemNode)] == [
        Message(kind="note", text="One."),
        Message(kind="note", text="Two."),
    ]
    assert [type(each) for each in ledger.drawn_to(made.number, Stands)] == [
        StandsTold,
        StandsWaiting,
    ]
    assert Inbox.opened(ledger).items == inbox.items


def test_a_new_item_takes_the_ledger_s_next_number_and_whereabouts_take_none(
    tmp_path: Path,
) -> None:
    ledger = opened(tmp_path / "ledger")
    converted(ledger, stored(tmp_path / "inbox"))
    inbox = Inbox.opened(ledger)
    subagent = MAIN.model_copy(update={"agent": "a2"})

    placed = inbox.placed(
        Whereabouts(
            conversation=subagent, launch="l1", worktree=Path("/w"), since=at(41)
        )
    )
    made = inbox.made(
        Message(kind="note", text="Next."), MAIN, Operator(), None, at(40)
    )

    assert made.number == 13
    assert Inbox.opened(ledger).whereabouts[subagent.key()] == placed
    assert ledger.every(Node) == ledger.every(ItemNode)


def test_a_citation_read_again_after_an_edit_replaces_the_one_before(
    tmp_path: Path,
) -> None:
    ledger = opened(tmp_path / "ledger")
    converted(ledger, stored(tmp_path / "inbox"))
    inbox = Inbox.opened(ledger)
    turn = inbox.item(3)

    inbox.kept(
        turn.model_copy(
            update={"citations": [Citation(said="@5", start=0, end=2, item=5)]}
        )
    )
    inbox.kept(inbox.item(3).model_copy(update={"call": "c1"}))

    standing = ledger.drawn_from(3, Cites, current=True)
    assert [(each.target, each.part, each.reading) for each in standing] == [
        (5, None, 2)
    ]
    assert len(ledger.drawn_from(3, Cites)) == 2


def test_attachments_written_on_another_thread_are_never_lost_to_the_event_loop_s_writes(
    tmp_path: Path,
) -> None:
    ledger = opened(tmp_path / "ledger")
    inbox = Inbox.opened(ledger)
    flags = [
        inbox.made(
            Flagged(
                text="w", summary="s", worktree=Path("/w"), path=Path(f"{each}.py")
            ),
            WORKER,
            Operator(),
            Path("/w"),
            at(each),
        )
        for each in range(8)
    ]
    for each in flags:
        inbox.attached(each.number, "+", [])

    def filing(number: int) -> None:
        for turn in range(20):
            inbox.filed(
                number, [ChangedFile.of(Path("a.py"), None, f"{turn}".encode())]
            )

    workers = [threading.Thread(target=filing, args=(each.number,)) for each in flags]
    for each in workers:
        each.start()
    for turn in range(20):
        for each in flags:
            inbox.kept(inbox.item(each.number).model_copy(update={"call": f"c{turn}"}))
    for each in workers:
        each.join()

    assert all(
        inbox.files(each.number) == [ChangedFile.of(Path("a.py"), None, b"19")]
        for each in flags
    )
    assert all(inbox.diff(each.number) == "+" for each in flags)
    assert Inbox.opened(ledger).items == inbox.items


def test_a_rehearsal_of_the_conversion_finds_everything_alike_and_says_no_content(
    tmp_path: Path,
) -> None:
    layout = stored(tmp_path / "inbox")

    rehearsal = rehearsed(layout, tmp_path / "scratch")

    assert rehearsal.differs == []
    assert rehearsal.unlinked == 1
    said = "\n".join(rehearsal.said())
    assert "12 items, 2 conversations" in said
    assert "read alike" in said
    assert all(
        text not in said for text in ["Which?", "This one.", "A note.", "Taken back."]
    )


def test_lup_dev_inbox_check_conversion_reads_the_files_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    layout = Layout.of(LupDevSettings())
    stored(layout.inbox.home)

    ran = CliRunner().invoke(cli.app, ["inbox", "check-conversion"])

    assert ran.exit_code == 0, ran.output
    assert "read alike" in ran.output
    assert not LedgerLayout.of(layout).home.exists()
