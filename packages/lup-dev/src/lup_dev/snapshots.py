"""The ledger as each copy of `lup-dev` left it: a snapshot taken at each switch, and restoring one.

`docs/trust.md`, *The way back*. A copy can change what the ledger stores, and
conversions are one-way, so an older copy may not read what a newer one left.
So the switch takes a snapshot once the service has stopped and nothing writes
(`Snapshots.taken`), kept in lup's state, which no room mounts: the database,
as one state, and a hard link to each attachment, which costs no disk, since
the store only ever writes one whole under a new name.

**What a snapshot leaves out:** the launches' records, the judge's stores and the
sessions' names, which move with sessions still running, and which going back
leaves where they stand, as a restart of the service does.

**Restoring loses what happened since,** which the operator is told as they do it
(`Lost`, `lup-dev restore`). It moves the ledger aside rather than removing it, keeps
the number sequence past every number used, so an item made after never takes the number
a hold or a session still names, and brings back any attachment gone.
"""

import secrets
import shutil
import sqlite3
import urllib.parse
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from lup.types import Model
from lup_dev.conversions import snapshot
from lup_dev.stored import read_model, write_model
from lup_ledger.environment.layout import LedgerLayout


class Written(Model):
    """How far a ledger had been written, and at which version of its tables, read with SQLite alone, since the code reading it may be older or newer than what wrote it."""

    tables: int
    """The version of its tables, its `user_version`."""
    versions: int | None = None
    """Its latest node's version; none where its tables don't say."""
    edges: int | None = None
    """Its latest edge; none where its tables don't say."""
    next: int | None = None
    """The number its next node would take; none where its tables don't say."""


def read_only(database: Path) -> sqlite3.Connection:
    """Open `database` through a connection that can't write it."""
    uri = urllib.parse.urlunsplit(("file", "", str(database), "mode=ro", ""))
    return sqlite3.connect(uri, uri=True)


def written(database: Path) -> Written | None:
    """Say how far the ledger's database at `database` was written; none where there's none."""
    if not database.is_file():
        return None
    connection = read_only(database)
    try:
        tables = connection.execute("PRAGMA user_version").fetchone()[0]

        def read(query: str) -> int | None:
            try:
                return connection.execute(query).fetchone()[0]
            except sqlite3.OperationalError:
                return None

        return Written(
            tables=tables,
            versions=read("SELECT coalesce(max(version), 0) FROM versions"),
            edges=read("SELECT coalesce(max(drawn), 0) FROM edges"),
            next=read("SELECT next FROM sequence"),
        )
    finally:
        connection.close()


class Snapshot(Model):
    """The ledger as a copy left it, at a switch."""

    name: str
    """Its directory, under the snapshots."""
    taken: datetime
    left: str | None
    """The copy that left the ledger so (`Kept.name`); none where no copy of the
    repository's was recorded."""
    commit: str | None
    """The commit of that copy, to say it by."""
    written: Written


class Lost(Model):
    """What restoring a snapshot takes out of the ledger, to say before doing it."""

    since: datetime
    versions: int | None = None
    """Versions of the ledger's nodes written since; none where the two can't be
    compared, as across a change to its tables."""
    edges: int | None = None
    """Its edges drawn since; none likewise."""

    def said(self) -> str:
        """Say what goes, in the operator's words.

        >>> from datetime import datetime
        >>> print(Lost(since=datetime(2026, 11, 6, 14, 2), versions=3, edges=7).said())
        Everything since 2026-11-06 14:02 leaves the ledger: 3 writes of items and threads, and 7 links between them. A session waiting on one of those items gets no answer to it.
        >>> print(Lost(since=datetime(2026, 11, 6, 14, 2)).said())
        Everything since 2026-11-06 14:02 leaves the ledger, however much that is: its tables have changed, so it can't be counted. A session waiting on one of those items gets no answer to it.
        """
        at = self.since.astimezone().strftime("%Y-%m-%d %H:%M")
        if self.versions is None or self.edges is None:
            how = (
                ", however much that is: its tables have changed, so it can't be "
                "counted"
            )
        else:
            how = (
                f": {self.versions} writes of items and threads, and {self.edges} "
                "links between them"
            )
        return (
            f"Everything since {at} leaves the ledger{how}. A session waiting on one "
            "of those items gets no answer to it."
        )


class Restored(Model):
    """A snapshot restored: what it took out, and where the ledger it replaced is kept."""

    snapshot: Snapshot
    lost: Lost
    aside: Path
    """The ledger as it stood, in a directory no lup reads; nothing merges it back."""

    def said(self) -> str:
        """Say what happened, for the report."""
        return (
            f"The ledger is back as it was at "
            f"{self.snapshot.taken.astimezone().strftime('%Y-%m-%d %H:%M')}. "
            f"{self.lost.said()} What it replaced is kept in {self.aside}."
        )


class Snapshots(Model):
    """The ledger's snapshots, in `home`, of the ledger at `ledger`."""

    home: Path
    ledger: LedgerLayout

    def place(self, each: Snapshot) -> LedgerLayout:
        """Say where `each` keeps its ledger."""
        return LedgerLayout(home=self.home / each.name)

    def taken(
        self, at: datetime, left: str | None, commit: str | None
    ) -> Snapshot | None:
        """Keep the ledger as it stands, with nothing writing it, as the copy `left`, of `commit`, left it; none where there's no ledger yet.

        It's made under a name no reader takes for a snapshot, and renamed once
        whole, so a switch cut short leaves none half taken.
        """
        before = written(self.ledger.database)
        if before is None:
            return None
        name = f"{at.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(4)}"
        making = self.home / f".making-{name}"
        placed = LedgerLayout(home=making)
        snapshot(self.ledger, placed)
        self.linked_attachments(self.ledger, placed)
        taken = Snapshot(name=name, taken=at, left=left, commit=commit, written=before)
        write_model(making / "snapshot.json", taken)
        making.rename(self.home / name)
        return taken

    def linked_attachments(self, source: LedgerLayout, target: LedgerLayout) -> None:
        """Link each attachment `source` keeps that `target` doesn't into it, each costing a directory's entry alone: both are named by their content, and never rewritten."""
        if not source.attachments.is_dir():
            return
        target.attachments.mkdir(parents=True, exist_ok=True)
        for each in source.attachments.iterdir():
            kept = target.attachment(each.name)
            if not kept.exists():
                kept.hardlink_to(each)

    def all(self) -> list[Snapshot]:
        """Return each snapshot kept, the latest first; one whose record doesn't read is passed over, since going back reads these from an older copy than took them."""
        if not self.home.is_dir():
            return []

        def read(place: Path) -> Snapshot | None:
            try:
                return read_model(place / "snapshot.json", Snapshot)
            except ValidationError:
                return None

        found = [read(each) for each in self.home.iterdir() if each.is_dir()]
        kept = [each for each in found if each is not None]
        return sorted(kept, key=lambda each: each.taken, reverse=True)

    def left_by(self, copy: str) -> Snapshot | None:
        """Return the latest snapshot the copy `copy` left; none where it left none."""
        return next((each for each in self.all() if each.left == copy), None)

    def pruned(self, kept: list[str]) -> None:
        """Remove every snapshot but the latest each copy in `kept` left, with whatever a switch cut short left half made; the latest of all stays, whichever copy it's of, as what the switch just made."""
        if not self.home.is_dir():
            return
        everything = self.all()
        latest = {each.left: each.name for each in reversed(everything)}
        holding = [name for left, name in latest.items() if left in kept]
        if everything:
            holding.append(everything[0].name)
        for place in self.home.iterdir():
            aside = place.name.startswith("superseded-")
            if place.is_dir() and not aside and place.name not in holding:
                shutil.rmtree(place)

    def lost_to(self, each: Snapshot) -> Lost:
        """Say what restoring `each` takes out of the ledger as it stands."""
        now = written(self.ledger.database)
        then = each.written

        def since(later: int | None, earlier: int | None) -> int | None:
            if later is None or earlier is None or now is None:
                return None
            if now.tables != then.tables:
                return None
            return max(later - earlier, 0)

        return Lost(
            since=each.taken,
            versions=since(None if now is None else now.versions, then.versions),
            edges=since(None if now is None else now.edges, then.edges),
        )

    def restored(self, each: Snapshot, at: datetime) -> Restored:
        """Put `each` back as the ledger, with nothing writing it: what's there moved aside, whole, write-ahead log and all, then the snapshot copied in, so it can be restored again.

        The number sequence stays past every number the ledger it replaces
        used, or an item made after would take the number of one a hold, or a
        session, still names, and an answer meant for that one would reach it.
        An attachment the snapshot keeps that's gone from the ledger's comes back.
        """
        lost = self.lost_to(each)
        before = written(self.ledger.database)
        place = self.place(each)
        stamp = at.strftime("%Y%m%dT%H%M%S")
        aside = self.home / f"superseded-{stamp}-{secrets.token_hex(4)}"
        aside.mkdir(parents=True)
        database = self.ledger.database
        arriving = database.with_name(f"{database.name}.restoring")
        shutil.copyfile(place.database, arriving)
        if before is not None and before.next is not None:
            connection = sqlite3.connect(arriving)
            try:
                with connection:
                    connection.execute(
                        "UPDATE sequence SET next = max(next, ?)", (before.next,)
                    )
            finally:
                connection.close()
        for suffix in ["", "-wal", "-shm"]:
            kept = database.with_name(f"{database.name}{suffix}")
            if kept.exists():
                kept.rename(aside / kept.name)
        arriving.rename(database)
        self.linked_attachments(place, self.ledger)
        return Restored(snapshot=each, lost=lost, aside=aside)
