"""What the host service converts as it starts, before it serves anything, and the check of each conversion, which the operator runs on the host.

`docs/inbox.md`, *Kept on the ledger*. The inbox opens on the ledger
(`inbox_opened`) once what an earlier lup kept is on it, each converted the
first time the service starts on a ledger holding none of it, and said:
- the inbox's files: its items, conversations, the draft, the order
  (`lup_dev.inbox.conversion.converted`);
- the review marks' files, a file of each module's per repository, the judge's
  marks of each branch from before the files carried in
  (`lup_dev.inbox.conversion.marks_converted`).

`checked` is `lup-dev inbox check-conversion`: it rehearses each conversion
into a scratch directory, removed after, reading lup's files alone and the
ledger the host service holds through a connection that only reads
(`snapshot`), and says, for each, counts, times and what differs, never what an
item says or what a mark is on, so the operator can run it on their own state
before a lup that converts is approved, and pass on what it says.

It's apart from the inbox, the lowest of what it converts, since carrying the
judge's older marks in reads the judge's own store (`lup_dev.policy.reviewed`),
which sits above the inbox.
"""

import sqlite3
import tempfile
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

from lup.types import Model
from lup_dev.inbox.conversion import (
    Carrying,
    MarkFiles,
    converted,
    marks_converted,
    marks_rehearsed,
    rehearsed,
)
from lup_dev.inbox.store import KINDS, Inbox, InboxError, located
from lup_dev.policy.reviewed import CARRIED, JUDGE, older
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger

if TYPE_CHECKING:
    from collections.abc import Callable

    from lup_dev.host.watch import Changes
    from lup_dev.layout import InboxLayout, Layout


def inbox_opened(
    layout: Layout,
    changes: Changes | None = None,
    say: Callable[[str], None] = lambda _: None,
) -> Inbox:
    """Open the inbox on the ledger in lup's state at `layout`, telling `changes` of each item written, once what an earlier lup kept in files is converted onto it where it keeps none of it yet, each conversion said through `say`.

    Raise `InboxError` where a file or a record doesn't read; `HostError` where
    the ledger refuses a mark.
    """
    ledger = Ledger.opened(LedgerLayout.of(layout), KINDS)
    kept = converted(ledger, layout.inbox)
    if kept is not None and kept.items:
        say(
            f"lup: the inbox's files at {layout.inbox.home} are on the ledger at "
            f"{ledger.layout.database}: {kept.said()}. The files stay as they were."
        )
    inbox = Inbox.opened(ledger, changes)
    marked = marks_converted(
        inbox.marks, MarkFiles.read(layout, known(inbox), carrying(layout))
    )
    if marked is not None and (marked.marks or marked.unnamed):
        say(
            f"lup: the review marks' files under {layout.repositories} are on the "
            f"ledger: {marked.said()}. The files stay as they were."
        )
    return inbox


def known(inbox: Inbox) -> list[Path]:
    """List the repositories `inbox` knows, by their git directories: those its items and its conversations are of."""
    return list(
        dict.fromkeys(
            [
                *(located(each) for each in inbox.items.values()),
                *(each.conversation.repository for each in inbox.whereabouts.values()),
            ]
        )
    )


def carrying(layout: Layout) -> list[Carrying]:
    """Return the older stores the review marks' conversion carries in, as lup's state at `layout` keeps them: the judge's marks of each branch."""
    return [
        Carrying(
            module=JUDGE,
            name=CARRIED,
            read=lambda repository: older(layout, repository),
        )
    ]


class Check(Model):
    """One conversion's check: what it converts, what it says, a line each, and whether something differs."""

    of: str
    """What it converts, as a heading: `The review marks' files`."""
    said: list[str]
    differs: bool = False


def snapshot(source: LedgerLayout, target: LedgerLayout) -> bool:
    """Copy the ledger's database at `source` into `target`, as one state, through a connection that only reads it, so the host service holding it open goes on writing it: its attachments apart. Say whether there was one to copy."""
    if not source.database.is_file():
        return False
    target.home.mkdir(parents=True, exist_ok=True)
    only_reading = urllib.parse.urlunsplit(
        ("file", "", str(source.database), "mode=ro", "")
    )
    reading = sqlite3.connect(only_reading, uri=True)
    try:
        writing = sqlite3.connect(target.database)
        try:
            reading.backup(writing)
        finally:
            writing.close()
    finally:
        reading.close()
    return True


def checked(
    layout: Layout, files: InboxLayout, scratch: Path | None = None
) -> list[Check]:
    """Rehearse each conversion lup runs as its host service starts, over lup's state at `layout`, the inbox's files read from `files`, into `scratch`, or a temporary directory removed after; and say what each found.

    Nothing at `layout` is written: lup's files are read alone, and the
    ledger the host service holds is read through a snapshot (`snapshot`).
    """
    if scratch is None:
        with tempfile.TemporaryDirectory() as temporary:
            return checked(layout, files, Path(temporary))
    try:
        inbox = rehearsed(files, scratch / "inbox")
        items = Check(
            of="The inbox's files", said=inbox.said(), differs=bool(inbox.differs)
        )
    except InboxError as nothing:
        items = Check(of="The inbox's files", said=[f"Nothing to convert: {nothing}."])
    live = LedgerLayout(home=scratch / "live")
    if not snapshot(LedgerLayout.of(layout), live):
        return [
            items,
            Check(
                of="The review marks' files",
                said=[
                    f"Nothing to check: lup keeps no ledger at {LedgerLayout.of(layout).home}."
                ],
            ),
        ]
    ledger = Ledger.opened(live, KINDS)
    try:
        repositories = known(Inbox.opened(ledger))
    finally:
        ledger.close()
    try:
        rehearsal = marks_rehearsed(
            layout, repositories, carrying(layout), scratch / "marks"
        )
        marks = Check(
            of="The review marks' files",
            said=rehearsal.said(),
            differs=bool(rehearsal.differs),
        )
    except InboxError as nothing:
        marks = Check(
            of="The review marks' files", said=[f"Nothing to convert: {nothing}."]
        )
    return [items, marks]
