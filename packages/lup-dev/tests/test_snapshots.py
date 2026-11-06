"""The ledger as each copy left it, and restoring it (`lup_dev/snapshots.py`), on a real database."""

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from lup_dev.snapshots import Lost, Snapshots, written
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger

if TYPE_CHECKING:
    from pathlib import Path

AT = datetime(2026, 11, 6, 12, tzinfo=UTC)
LATER = AT + timedelta(hours=1)


def wrote(ledger: LedgerLayout, *, versions: int = 0, edges: int = 0) -> None:
    """Write `versions` versions of nodes and `edges` edges, as the store's own tables hold them, each taking a number from the sequence."""
    connection = sqlite3.connect(ledger.database)
    with connection:
        for _ in range(versions):
            number = connection.execute("SELECT next FROM sequence").fetchone()[0]
            connection.execute("UPDATE sequence SET next = next + 1")
            connection.execute(
                "INSERT INTO versions (number, kind, record) VALUES (?, 'k', '{}')",
                (number,),
            )
        for _ in range(edges):
            connection.execute(
                "INSERT INTO edges (kind, source, target, record) "
                "VALUES ('k', NULL, 1, '{}')"
            )
    connection.close()


@pytest.fixture
def ledger(tmp_path: Path) -> LedgerLayout:
    placed = LedgerLayout(home=tmp_path / "state" / "ledger")
    Ledger.opened(placed).close()
    wrote(placed, versions=2, edges=1)
    placed.attachments.mkdir()
    placed.attachment("abc").write_text("an attachment")
    return placed


@pytest.fixture
def snapshots(tmp_path: Path, ledger: LedgerLayout) -> Snapshots:
    return Snapshots(home=tmp_path / "state" / "snapshots", ledger=ledger)


def test_a_snapshot_holds_the_database_whole_and_links_its_attachments(
    snapshots: Snapshots, ledger: LedgerLayout
) -> None:
    taken = snapshots.taken(AT, "copy", "abc123")
    assert taken is not None
    assert taken.left == "copy"
    assert taken.commit == "abc123"
    assert taken.written.tables == 2
    assert taken.written.versions == 2
    assert taken.written.edges == 1
    assert taken.written.next == 3
    place = snapshots.place(taken)
    assert written(place.database) == taken.written
    assert place.attachment("abc").read_text() == "an attachment"
    assert (
        place.attachment("abc").stat().st_ino == ledger.attachment("abc").stat().st_ino
    )


def test_a_snapshot_stands_while_the_ledger_goes_on(
    snapshots: Snapshots, ledger: LedgerLayout
) -> None:
    taken = snapshots.taken(AT, "copy", "abc123")
    assert taken is not None
    wrote(ledger, versions=5)
    assert written(snapshots.place(taken).database) == taken.written


def test_theres_nothing_to_snapshot_where_no_ledger_is_yet(tmp_path: Path) -> None:
    snapshots = Snapshots(
        home=tmp_path / "snapshots", ledger=LedgerLayout(home=tmp_path / "none")
    )
    assert snapshots.taken(AT, None, None) is None
    assert snapshots.all() == []


def test_one_half_made_is_never_read_and_the_next_clears_it(
    snapshots: Snapshots,
) -> None:
    half = snapshots.home / ".making-20261106T110000-abc"
    half.mkdir(parents=True)
    assert snapshots.all() == []
    taken = snapshots.taken(AT, "copy", "abc123")
    assert taken is not None
    snapshots.pruned(["copy"])
    assert not half.exists()


def test_what_a_later_lup_wrote_is_passed_over(snapshots: Snapshots) -> None:
    taken = snapshots.taken(AT, "copy", "abc123")
    other = snapshots.home / "by-a-later-lup"
    other.mkdir()
    (other / "snapshot.json").write_text('{"another": "shape"}')
    assert snapshots.all() == [taken]


def test_the_latest_each_copy_left_is_found_and_the_rest_go(
    snapshots: Snapshots,
) -> None:
    one = snapshots.taken(AT, "one", "c1")
    two = snapshots.taken(AT + timedelta(minutes=1), "two", "c2")
    one_again = snapshots.taken(AT + timedelta(minutes=2), "one", "c1")
    three = snapshots.taken(AT + timedelta(minutes=3), "three", "c3")
    assert one is not None
    assert two is not None
    assert one_again is not None
    assert three is not None
    assert snapshots.left_by("one") == one_again
    assert snapshots.left_by("none") is None

    snapshots.pruned(["one", "two"])

    assert [each.name for each in snapshots.all()] == [
        three.name,
        one_again.name,
        two.name,
    ]


def test_restoring_puts_it_back_and_keeps_what_it_replaces_aside(
    snapshots: Snapshots, ledger: LedgerLayout
) -> None:
    taken = snapshots.taken(AT, "copy", "abc123")
    assert taken is not None
    wrote(ledger, versions=3, edges=4)
    before = written(ledger.database)
    assert before is not None

    restored = snapshots.restored(taken, LATER)

    now = written(ledger.database)
    assert now is not None
    assert now.versions == taken.written.versions
    assert now.edges == taken.written.edges
    assert restored.lost == Lost(since=AT, versions=3, edges=4)
    kept = written(restored.aside / ledger.database.name)
    assert kept == before
    assert str(restored.aside) in restored.said()
    assert "3 writes of items and threads, and 4 links" in restored.said()


def test_restoring_never_reuses_a_number_the_ledger_it_replaces_gave_out(
    snapshots: Snapshots, ledger: LedgerLayout
) -> None:
    taken = snapshots.taken(AT, "copy", "abc123")
    assert taken is not None
    wrote(ledger, versions=7)
    given_out = written(ledger.database)
    assert given_out is not None
    assert given_out.next == 10

    snapshots.restored(taken, LATER)

    now = written(ledger.database)
    assert now is not None
    assert now.next == 10
    assert now.versions == taken.written.versions


def test_restoring_brings_back_an_attachment_gone_and_leaves_one_since(
    snapshots: Snapshots, ledger: LedgerLayout
) -> None:
    taken = snapshots.taken(AT, "copy", "abc123")
    assert taken is not None
    ledger.attachment("abc").unlink()
    ledger.attachment("since").write_text("since")

    snapshots.restored(taken, LATER)

    assert ledger.attachment("abc").read_text() == "an attachment"
    assert ledger.attachment("since").read_text() == "since"


def test_a_snapshot_can_be_restored_again(
    snapshots: Snapshots, ledger: LedgerLayout
) -> None:
    taken = snapshots.taken(AT, "copy", "abc123")
    assert taken is not None
    snapshots.restored(taken, LATER)
    wrote(ledger, versions=1)
    snapshots.restored(taken, LATER + timedelta(minutes=1))
    now = written(ledger.database)
    assert now is not None
    assert now.versions == taken.written.versions


def test_restoring_leaves_the_write_ahead_log_with_what_it_replaces(
    snapshots: Snapshots, ledger: LedgerLayout
) -> None:
    taken = snapshots.taken(AT, "copy", "abc123")
    assert taken is not None
    writing = sqlite3.connect(ledger.database)
    writing.execute("PRAGMA journal_mode = WAL")
    writing.execute("PRAGMA wal_autocheckpoint = 0")
    with writing:
        writing.execute("UPDATE sequence SET next = next + 40")
    # Left open: its log stays beside the database, as a service killed leaves it.
    restored = snapshots.restored(taken, LATER)
    writing.close()
    wal = ledger.database.with_name(f"{ledger.database.name}-wal")
    assert not wal.exists()
    now = written(ledger.database)
    assert now is not None
    assert now.next == 43
    assert (restored.aside / ledger.database.name).is_file()


def test_what_goes_cant_be_counted_across_a_change_to_the_tables(
    snapshots: Snapshots, ledger: LedgerLayout
) -> None:
    taken = snapshots.taken(AT, "copy", "abc123")
    assert taken is not None
    connection = sqlite3.connect(ledger.database)
    connection.execute("PRAGMA user_version = 3")
    connection.close()
    lost = snapshots.lost_to(taken)
    assert lost == Lost(since=AT)
    assert "however much that is" in lost.said()


def test_tables_it_doesnt_know_read_as_their_version_alone(tmp_path: Path) -> None:
    database = tmp_path / "ledger.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version = 9")
    connection.close()
    said = written(database)
    assert said is not None
    assert said.tables == 9
    assert said.versions is None
    assert said.next is None


def test_no_ledger_has_no_writing_to_say(tmp_path: Path) -> None:
    assert written(tmp_path / "none.sqlite3") is None
