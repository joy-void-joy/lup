"""Review marks as the core keeps them: moved and read by a module's key, one file of each module's per repository, the judge's marks of files carried in once from where each branch's were kept before, and a room reading its own repository's alone."""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.host.watch import Changes, Remarked
from lup_dev.inbox.marks import (
    MarksMoved,
    MarksMoving,
    MarksRead,
    MarksReading,
    MarkStore,
    MoveMarks,
    Moving,
    ReadMarks,
    ReviewMark,
    ReviewMarks,
    StoredMarks,
    keyed,
)
from lup_dev.inbox.store import InboxError
from lup_dev.layout import Layout
from lup_dev.policy.reviewed import CARRIED, JUDGE, Mark, Marks, Reviews

if TYPE_CHECKING:
    from conftest import FakeClock

REPOSITORY = Path("/r/.git")


def layout(tmp_path: Path) -> Layout:
    return Layout(state=tmp_path / "state", data=tmp_path / "data")


def test_a_mark_moved_is_read_back_by_its_key_in_any_order_the_latest_alone(
    tmp_path: Path, clock: FakeClock
) -> None:
    store = MarkStore(layout=layout(tmp_path).marks(REPOSITORY))
    key = {"runtime": "claude", "session": "s1", "agent": None}
    assert store.of("transcripts", key) is None
    first = ReviewMark(key=key, up_to="12", at=clock.now())
    store.moved("transcripts", [first])
    clock.sleep(60)
    later = ReviewMark(
        key={"agent": None, "session": "s1", "runtime": "claude"},
        up_to="40",
        at=clock.now(),
    )
    other = ReviewMark(key={**key, "session": "s2"}, up_to="3", at=clock.now())
    after = store.moved("transcripts", [later, other])
    assert [each.up_to for each in after.marks] == ["40", "3"]
    assert store.of("transcripts", key) == later
    # Another module's marks are its own.
    assert store.of("core", key) is None
    assert keyed(key) == keyed(later.key)


def test_the_judge_s_marks_of_each_branch_are_carried_in_once_and_the_older_files_left(
    tmp_path: Path, clock: FakeClock
) -> None:
    machine = layout(tmp_path)
    older = machine.reviewed(REPOSITORY)
    feat = Marks(
        branch="feat/x",
        files=[
            Mark(path=Path("src/a.py"), version="a" * 40, at=clock.now()),
            Mark(path=Path("src/gone.py"), version=None, at=clock.now()),
        ],
    )
    main = Marks(
        branch="main",
        files=[Mark(path=Path("src/a.py"), version="b" * 40, at=clock.now())],
    )
    for marks in [feat, main]:
        path = older.branch(marks.branch)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(marks.model_dump_json())
    before = {path: path.read_bytes() for path in older.branches.iterdir()}

    reviews = Reviews.of(machine, REPOSITORY)
    assert reviews.marks("feat/x") == feat
    assert reviews.marks("main") == main
    assert reviews.marks("other") == Marks(branch="other")
    kept = MarkStore(layout=machine.marks(REPOSITORY)).kept(JUDGE)
    assert kept.carried == [CARRIED]
    assert kept.of({"branch": "feat/x", "path": "src/a.py"}) == ReviewMark(
        key={"branch": "feat/x", "path": "src/a.py"}, up_to="a" * 40, at=clock.now()
    )
    # The older files are as they were, for an older copy of lup to read.
    assert {path: path.read_bytes() for path in older.branches.iterdir()} == before

    # A mark made since is the latest: an older file changed after, as an older
    # copy would write it, is never carried in again.
    clock.sleep(300)
    marked = Mark(path=Path("src/a.py"), version="c" * 40, at=clock.now())
    Reviews.of(machine, REPOSITORY).marked("feat/x", [marked], {})
    rewritten = feat.model_copy(
        update={
            "files": [Mark(path=Path("src/b.py"), version="d" * 40, at=clock.now())]
        }
    )
    older.branch("feat/x").write_text(rewritten.model_dump_json())
    again = Reviews.of(machine, REPOSITORY).marks("feat/x")
    assert again.of(Path("src/a.py")) == marked
    assert again.of(Path("src/b.py")) is None


def test_a_mark_made_before_the_older_files_are_carried_in_stays_the_latest(
    tmp_path: Path, clock: FakeClock
) -> None:
    machine = layout(tmp_path)
    older = machine.reviewed(REPOSITORY).branch("feat")
    older.parent.mkdir(parents=True)
    at = clock.now()
    older.write_text(
        Marks(
            branch="feat", files=[Mark(path=Path("a.py"), version="a" * 40, at=at)]
        ).model_dump_json()
    )
    store = MarkStore(layout=machine.marks(REPOSITORY))
    clock.sleep(60)
    store.moved(
        JUDGE,
        [
            ReviewMark(
                key={"branch": "feat", "path": "a.py"}, up_to="e" * 40, at=clock.now()
            )
        ],
    )
    carried = Reviews.of(machine, REPOSITORY).marks("feat")
    assert carried.of(Path("a.py")) == Mark(
        path=Path("a.py"), version="e" * 40, at=clock.now()
    )


def test_the_judge_s_stamp_of_a_branch_changes_as_a_mark_on_it_does_alone(
    tmp_path: Path, clock: FakeClock
) -> None:
    machine = layout(tmp_path)
    reviews = Reviews.of(machine, REPOSITORY)
    empty = reviews.stamp("feat")
    reviews.marked("other", [Mark(path=Path("a.py"), version=None, at=clock.now())], {})
    assert Reviews.of(machine, REPOSITORY).stamp("feat") == empty
    reviews.marked("feat", [Mark(path=Path("a.py"), version=None, at=clock.now())], {})
    assert Reviews.of(machine, REPOSITORY).stamp("feat") != empty


def test_marks_are_moved_at_the_host_s_time_each_told_and_read_by_the_operator_or_a_room_of_theirs(
    tmp_path: Path, clock: FakeClock
) -> None:
    machine = layout(tmp_path)
    changes = Changes()
    key = {"runtime": "claude", "session": "s1", "agent": None}
    moving = MarksMoving(layout=machine, clock=clock, changes=changes)
    moved = asyncio.run(
        moving.answer(
            MoveMarks(
                repository=REPOSITORY,
                module="transcripts",
                marks=[Moving(key=key, up_to="7")],
            )
        )
    )
    mark = ReviewMark(key=key, up_to="7", at=clock.now())
    assert moved == MarksMoved(marks=[mark])
    assert changes.touches == {
        Remarked(repository=REPOSITORY, module="transcripts", key=keyed(key)): 1
    }
    reading = MarksReading(layout=machine)
    asked = ReadMarks(repository=REPOSITORY, module="transcripts", keys=[key, {"x": 1}])
    assert asyncio.run(reading.answer(asked)) == MarksRead(marks=[mark])
    every = ReadMarks(repository=REPOSITORY, module="transcripts")
    assert asyncio.run(reading.scoped(every, REPOSITORY)) == MarksRead(marks=[mark])
    with pytest.raises(InboxError, match="aren't this repository's"):
        asyncio.run(reading.scoped(asked, Path("/other/.git")))
    assert not MoveMarks.reads


def test_a_module_s_marks_are_read_by_its_key_each_recorded_as_read(
    tmp_path: Path, clock: FakeClock
) -> None:
    machine = layout(tmp_path)
    key = {"runtime": "claude", "session": "s1", "agent": None}
    MarkStore(layout=machine.marks(REPOSITORY)).moved(
        "transcripts", [ReviewMark(key=key, up_to="7", at=clock.now())]
    )
    marks = ReviewMarks(
        marks=StoredMarks(layout=machine), repository=REPOSITORY, module="transcripts"
    )
    unmarked = {**key, "session": "s2"}
    found = asyncio.run(marks.of([key, unmarked]))
    assert [None if each is None else each.up_to for each in found] == ["7", None]
    assert asyncio.run(marks.mark(key)) == found[0]
    assert marks.read == [
        Remarked(repository=REPOSITORY, module="transcripts", key=keyed(key)),
        Remarked(repository=REPOSITORY, module="transcripts", key=keyed(unmarked)),
    ]
    offered = marks.offer(key, "9", "mark it read")
    assert json.loads(json.dumps(offered.argument)) == {
        "repository": str(REPOSITORY),
        "module": "transcripts",
        "key": key,
        "up_to": "9",
    }
