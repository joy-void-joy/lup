"""Review marks as the core keeps them on the ledger: moved and read by a module's key, each move an edge the operator drew, drawn to the node it's on or to its module's marks of the repository; a room reading its own repository's alone; and an earlier lup's files converted once, the judge's older marks of each branch carried in."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.conversions import carrying, inbox_opened
from lup_dev.host.protocol import HostError
from lup_dev.host.watch import Changes, Remarked
from lup_dev.inbox.conversion import (
    MarkFiles,
    MarksConverted,
    marks_compared,
    marks_converted,
    marks_rehearsed,
)
from lup_dev.inbox.marks import (
    CORE,
    MarksFile,
    MarksMoved,
    MarksMoving,
    MarksRead,
    MarksReading,
    MarkStore,
    MoveMarks,
    Moving,
    ReadMarks,
    Reviewed,
    Reviewing,
    ReviewMark,
    ReviewMarks,
    StoredMarks,
    keyed,
    on_node,
)
from lup_dev.inbox.store import InboxError, Message
from lup_dev.layout import Layout
from lup_dev.policy.reviewed import CARRIED, JUDGE, Mark, Marks, Reviews
from lup_dev.settings import LupDevSettings
from lup_dev.stored import write_model
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.parties import Conversation, Operator
from lup_ledger.records import Edge
from lup_ledger.threads import Thread

if TYPE_CHECKING:
    from conftest import FakeClock

REPOSITORY = Path("/r/.git")
CONVERSATION = {"runtime": "claude", "session": "s1", "agent": None}


def layout(tmp_path: Path) -> Layout:
    return Layout(state=tmp_path / "state", data=tmp_path / "data")


def thread(store: MarkStore, repository: Path, at: datetime) -> Thread:
    """Open a thread on the store's ledger, as a session's root is."""
    main = Conversation(repository=repository, runtime="claude", session="s1")
    return store.ledger.kept(
        Thread(
            number=store.ledger.numbered(),
            repository=repository,
            by=main,
            at=at,
            name="root",
            title="a root",
            holder=main,
        )
    )


def test_a_mark_moved_is_read_back_by_its_key_in_any_order_the_latest_alone(
    tmp_path: Path, clock: FakeClock
) -> None:
    store = MarkStore.kept_in(layout(tmp_path))
    assert store.of(REPOSITORY, "transcripts", CONVERSATION) is None
    first = ReviewMark(key=CONVERSATION, up_to="12", at=clock.now())
    store.moved(REPOSITORY, "transcripts", [first])
    clock.sleep(60)
    later = ReviewMark(
        key={"agent": None, "session": "s1", "runtime": "claude"},
        up_to="40",
        at=clock.now(),
    )
    other = ReviewMark(key={**CONVERSATION, "session": "s2"}, up_to="3", at=clock.now())
    after = store.moved(REPOSITORY, "transcripts", [later, other])
    assert [each.up_to for each in after.marks] == ["40", "3"]
    assert store.of(REPOSITORY, "transcripts", CONVERSATION) == later
    # Another module's marks are its own, and another repository's.
    assert store.of(REPOSITORY, "core", CONVERSATION) is None
    assert store.of(Path("/other/.git"), "transcripts", CONVERSATION) is None
    assert keyed(CONVERSATION) == keyed(later.key)
    # Read again from the ledger, as the host service does at its start, they're
    # the same; and every move stays, an edge the operator drew.
    again = MarkStore.opened(store.ledger)
    assert again.kept(REPOSITORY, "transcripts") == after
    drawn = store.ledger.drawn_of(Reviewed)
    assert [each.up_to for each in drawn] == ["12", "40", "3"]
    assert {each.by.party for each in drawn} == {"operator"}


def test_a_module_s_marks_are_drawn_to_one_node_of_its_own_per_repository(
    tmp_path: Path, clock: FakeClock
) -> None:
    store = MarkStore.kept_in(layout(tmp_path))
    for session in ["s1", "s2"]:
        store.moved(
            REPOSITORY,
            "transcripts",
            [ReviewMark(key={**CONVERSATION, "session": session}, at=clock.now())],
        )
    store.moved(
        REPOSITORY,
        JUDGE,
        [ReviewMark(key={"branch": "feat", "path": "a.py"}, at=clock.now())],
    )
    anchors = store.ledger.every(Reviewing)
    assert [each.module for each in anchors] == ["transcripts", JUDGE]
    assert [each.by.party for each in anchors] == ["lup", "lup"]
    assert [each.target for each in store.ledger.drawn_of(Reviewed)] == [
        anchors[0].number,
        anchors[0].number,
        anchors[1].number,
    ]
    assert MarkStore.opened(store.ledger).anchors == store.anchors


def test_a_mark_on_a_thread_is_drawn_to_the_thread_and_one_on_no_node_of_its_repository_is_refused(
    tmp_path: Path, clock: FakeClock
) -> None:
    store = MarkStore.kept_in(layout(tmp_path))
    root = thread(store, REPOSITORY, clock.now())
    mark = ReviewMark(key=on_node(root.number), up_to="7", at=clock.now())
    store.moved(REPOSITORY, CORE, [mark])
    [drawn] = store.ledger.drawn_to(root.number, Reviewed)
    assert (drawn.up_to, drawn.module) == ("7", CORE)
    assert store.ledger.every(Reviewing) == []
    assert store.of(REPOSITORY, CORE, on_node(root.number)) == mark
    # A thread's marks don't change where it stands: they aren't in it.
    assert [type(each) for each in store.ledger.drawn_to(root.number, Edge)] == [
        Reviewed
    ]
    elsewhere = thread(store, Path("/other/.git"), clock.now())
    for key in [on_node(elsewhere.number), on_node(9999)]:
        with pytest.raises(HostError, match="can't draw"):
            store.moved(REPOSITORY, CORE, [ReviewMark(key=key, at=clock.now())])
    assert store.of(REPOSITORY, CORE, on_node(9999)) is None
    assert len(store.ledger.drawn_of(Reviewed)) == 1


def test_the_judge_s_stamp_of_a_branch_changes_as_a_mark_on_it_does_alone(
    tmp_path: Path, clock: FakeClock
) -> None:
    machine = layout(tmp_path)
    store = MarkStore.kept_in(machine)
    reviews = Reviews.of(machine, store, REPOSITORY)
    empty = reviews.stamp("feat")
    reviews.marked("other", [Mark(path=Path("a.py"), version=None, at=clock.now())], {})
    assert Reviews.of(machine, store, REPOSITORY).stamp("feat") == empty
    reviews.marked("feat", [Mark(path=Path("a.py"), version=None, at=clock.now())], {})
    assert Reviews.of(machine, store, REPOSITORY).stamp("feat") != empty


def test_marks_are_moved_at_the_host_s_time_each_told_and_read_by_the_operator_or_a_room_of_theirs(
    tmp_path: Path, clock: FakeClock
) -> None:
    store = MarkStore.kept_in(layout(tmp_path))
    changes = Changes()
    moving = MarksMoving(store=store, clock=clock, changes=changes)
    moved = asyncio.run(
        moving.answer(
            MoveMarks(
                repository=REPOSITORY,
                module="transcripts",
                marks=[Moving(key=CONVERSATION, up_to="7")],
            )
        )
    )
    mark = ReviewMark(key=CONVERSATION, up_to="7", at=clock.now())
    assert moved == MarksMoved(marks=[mark])
    assert changes.touches == {
        Remarked(
            repository=REPOSITORY, module="transcripts", key=keyed(CONVERSATION)
        ): 1
    }
    reading = MarksReading(store=store)
    asked = ReadMarks(
        repository=REPOSITORY, module="transcripts", keys=[CONVERSATION, {"x": 1}]
    )
    assert asyncio.run(reading.answer(asked)) == MarksRead(marks=[mark])
    every = ReadMarks(repository=REPOSITORY, module="transcripts")
    assert asyncio.run(reading.scoped(every, REPOSITORY)) == MarksRead(marks=[mark])
    with pytest.raises(HostError, match="aren't this repository's"):
        asyncio.run(reading.scoped(asked, Path("/other/.git")))
    assert not MoveMarks.reads


def test_a_module_s_marks_are_read_by_its_key_each_recorded_as_read(
    tmp_path: Path, clock: FakeClock
) -> None:
    store = MarkStore.kept_in(layout(tmp_path))
    store.moved(
        REPOSITORY,
        "transcripts",
        [ReviewMark(key=CONVERSATION, up_to="7", at=clock.now())],
    )
    marks = ReviewMarks(
        marks=StoredMarks(store=store), repository=REPOSITORY, module="transcripts"
    )
    unmarked = {**CONVERSATION, "session": "s2"}
    found = asyncio.run(marks.of([CONVERSATION, unmarked]))
    assert [None if each is None else each.up_to for each in found] == ["7", None]
    assert asyncio.run(marks.mark(CONVERSATION)) == found[0]
    assert marks.read == [
        Remarked(repository=REPOSITORY, module="transcripts", key=keyed(CONVERSATION)),
        Remarked(repository=REPOSITORY, module="transcripts", key=keyed(unmarked)),
    ]
    offered = marks.offer(CONVERSATION, "9", "mark it read")
    assert json.loads(json.dumps(offered.argument)) == {
        "repository": str(REPOSITORY),
        "module": "transcripts",
        "key": CONVERSATION,
        "up_to": "9",
    }


def test_a_group_or_a_thread_is_read_up_to_what_s_in_it_by_its_number_alone(
    tmp_path: Path, clock: FakeClock
) -> None:
    moving = MarksMoving(store=MarkStore.kept_in(layout(tmp_path)), clock=clock)
    with pytest.raises(HostError, match="by its number"):
        asyncio.run(
            moving.answer(
                MoveMarks(
                    repository=REPOSITORY,
                    module=CORE,
                    marks=[Moving(key=CONVERSATION, up_to="later")],
                )
            )
        )
    moved = asyncio.run(
        moving.answer(
            MoveMarks(
                repository=REPOSITORY,
                module=CORE,
                marks=[Moving(key=CONVERSATION, up_to="57")],
            )
        )
    )
    assert isinstance(moved, MarksMoved)


def files_of_an_earlier_lup(machine: Layout, repository: Path) -> MarksFile:
    """Write the marks an earlier lup kept of `repository`: Transcripts' file, the judge's, which never carried its older store in, and each branch's file of that store; return the judge's file."""
    at = datetime(2026, 10, 20, 9, tzinfo=UTC)
    marks = machine.marks(repository)
    write_model(
        marks.module("transcripts"),
        MarksFile(
            module="transcripts",
            marks=[ReviewMark(key=CONVERSATION, up_to="41", at=at)],
        ),
    )
    judge = MarksFile(
        module=JUDGE,
        marks=[
            ReviewMark(key={"branch": "feat", "path": "a.py"}, up_to="a" * 40, at=at),
            ReviewMark(key={"branch": "feat", "path": "gone.py"}, up_to=None, at=at),
        ],
    )
    write_model(marks.module(JUDGE), judge)
    older = machine.reviewed(repository)
    for branch in [
        Marks(
            branch="feat",
            files=[
                # Marked in the file since: the file's is the latest.
                Mark(path=Path("a.py"), version="b" * 40, at=at),
                Mark(path=Path("b.py"), version="c" * 40, at=at),
            ],
        ),
        Marks(branch="main", files=[Mark(path=Path("a.py"), version="d" * 40, at=at)]),
    ]:
        write_model(older.branch(branch.branch), branch)
    return judge


def test_an_earlier_lup_s_marks_are_converted_once_the_judge_s_older_marks_carried_in_the_files_left(
    tmp_path: Path, clock: FakeClock
) -> None:
    machine = layout(tmp_path)
    judge = files_of_an_earlier_lup(machine, REPOSITORY)
    # A repository lup knows no name of: its directory named by a digest alone.
    stranger = machine.marks(Path("/unknown/.git"))
    write_model(stranger.module("core"), MarksFile(module="core"))
    before = {
        path: path.read_bytes()
        for path in sorted((machine.state / "repositories").rglob("*.json"))
    }

    store = MarkStore.kept_in(machine)
    files = MarkFiles.read(machine, [REPOSITORY], carrying(machine))
    kept = marks_converted(store, files)

    assert kept is not None
    assert kept == MarksConverted(
        repositories=1, modules=2, marks=5, carried=2, unnamed=1
    )
    assert kept.said() == (
        "5 marks, 2 of them carried in from the judge's older store, of 2 modules "
        "in 1 repository; 1 file of a repository lup knows no name of left as it is"
    )
    assert marks_compared(MarkStore.opened(store.ledger), files) == []
    reviews = Reviews.of(machine, store, REPOSITORY)
    assert reviews.marks("feat").of(Path("a.py")) == Mark(
        path=Path("a.py"), version="a" * 40, at=judge.marks[0].at
    )
    assert reviews.marks("feat").of(Path("b.py")) is not None
    assert reviews.marks("main").of(Path("a.py")) is not None
    assert store.of(REPOSITORY, "transcripts", CONVERSATION) is not None
    # Every file is as it was, for an older copy of lup to read.
    assert {
        path: path.read_bytes()
        for path in sorted((machine.state / "repositories").rglob("*.json"))
    } == before
    # Once the ledger keeps marks, nothing is converted again.
    assert marks_converted(store, files) is None
    assert len(store.ledger.drawn_of(Reviewed)) == 5


def test_a_judge_s_file_that_carried_its_older_store_carries_nothing_more(
    tmp_path: Path,
) -> None:
    machine = layout(tmp_path)
    judge = files_of_an_earlier_lup(machine, REPOSITORY)
    carried = judge.model_copy(update={"carried": [CARRIED]})
    write_model(machine.marks(REPOSITORY).module(JUDGE), carried)
    files = MarkFiles.read(machine, [REPOSITORY], carrying(machine))
    assert files.carried == 0
    [kept] = [each for each in files.kept[REPOSITORY] if each.module == JUDGE]
    assert kept.marks == judge.marks


def test_the_host_service_converts_the_marks_as_it_opens_the_inbox_once_and_says_so(
    tmp_path: Path, clock: FakeClock
) -> None:
    machine = Layout(state=tmp_path / "state", runtime=tmp_path / "run", data=tmp_path)
    repository = tmp_path / "repo.git"
    # The inbox knows the repository by an item of one of its conversations'.
    first = inbox_opened(machine)
    sender = Conversation(repository=repository, runtime="claude", session="s1")
    first.made(Message(kind="note", text="hi"), sender, Operator(), None, clock.now())
    first.ledger.close()
    files_of_an_earlier_lup(machine, repository)
    said: list[str] = []

    opened = inbox_opened(machine, say=said.append)
    opened.ledger.close()
    again = inbox_opened(machine, say=said.append)

    assert len(said) == 1
    assert "5 marks, 2 of them carried in from the judge's older store" in said[0]
    assert again.marks.of(repository, "transcripts", CONVERSATION) is not None
    assert len(again.ledger.drawn_of(Reviewed)) == 5


def test_the_check_of_the_marks_conversion_reads_the_files_alone_and_says_counts_and_differences(
    tmp_path: Path,
) -> None:
    machine = layout(tmp_path)
    files_of_an_earlier_lup(machine, REPOSITORY)
    before = sorted((machine.state).rglob("*"))
    rehearsal = marks_rehearsed(
        machine, [REPOSITORY], carrying(machine), tmp_path / "scratch"
    )
    assert rehearsal.converted.marks == 5
    assert rehearsal.differs == []
    said = "\n".join(rehearsal.said())
    assert "Every mark read back alike" in said
    assert "a.py" not in said
    # Nothing was written where lup keeps its state: the ledger was a scratch one.
    assert sorted((machine.state).rglob("*")) == before
    with pytest.raises(InboxError, match="no repository's review marks"):
        marks_rehearsed(layout(tmp_path / "empty"), [REPOSITORY], [])


def test_lup_dev_inbox_check_conversion_rehearses_the_marks_beside_the_inbox_s_files_writing_nothing(
    tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    machine = Layout.of(LupDevSettings())
    repository = tmp_path / "repo.git"
    live = inbox_opened(machine)
    sender = Conversation(repository=repository, runtime="claude", session="s1")
    live.made(Message(kind="note", text="hi"), sender, Operator(), None, clock.now())
    live.ledger.close()
    files_of_an_earlier_lup(machine, repository)
    database = LedgerLayout.of(machine).database
    before = database.read_bytes()

    ran = CliRunner().invoke(cli.app, ["inbox", "check-conversion"])

    assert ran.exit_code == 0, ran.output
    assert "The inbox's files:\n  Nothing to convert" in ran.output
    assert "The review marks' files:\n  Read the review marks' files" in ran.output
    assert "5 marks, 2 of them carried in" in ran.output
    assert "Every mark read back alike" in ran.output
    assert database.read_bytes() == before
