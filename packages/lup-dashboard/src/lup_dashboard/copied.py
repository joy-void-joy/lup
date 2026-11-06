"""The demo over a copy of the operator's dashboard state: the host's own handlers, as this checkout has them, over a copy in a directory of the demo's own, with nothing reaching the operator.

`docs/dashboard.md`, *The demo*. `lup-dashboard demo --copy` asks the host,
on the launch's request socket, for a copy of what the operator's dashboard
shows (`host-copy`, `lup_dev/host/copying.py`), every repository's, writes it
into a directory of its own (`DemoLayout`), and serves the page over it. Each
request the page sends (`api.Asked`) is answered by the host's own handler for
its kind (`lup_dev.host.service`, `.inbox.protocol`, `.inbox.marks`,
`.policy.waits`, `.host.views`), as this checkout has them: a session runs their
own branch's page, server and views on the operator's real data, at its real
size, and acts on it, the copy alone changing.

**What the host would convert, and nothing else** (`taken`). Each file copied
is read with this checkout's models as the demo starts, the ledger's items
among them; one that doesn't read stops it, naming the file and why, which is
what the host would meet once this checkout is approved. The inbox is then
opened as the host opens it at its start (`lup_dev.conversions.inbox_opened`),
converting onto the copy's ledger what an earlier lup kept in files where the
ledger keeps none of it yet, as the review marks. An item's attachments, its
diff and files, are read as the host reads them, as they're asked for.

**A conversation's record is read as it's asked for** (`HostRecords`): asked of
the host through the same request, written into the copy, and read with this
checkout's reader, since records are the bulk and grow as their agents work.

**Every view is answered by this checkout's modules** (`Views`): the launch's
own repository's from the declaration of the checkout the demo runs in; another's,
whose declaration is out of the room's reach, from lup's defaults, as the
stand-in demo's are, which the page says (`About.copied`).

**Nothing reaches out, by construction** (`lup_dashboard/handled.py`, which lists
each edge the host's handlers reach and how a demo cuts it). Beside those, what's
the copy's own:
- what an agent's branches changed since the operator saw them, and marking it
  reviewed (`ShowSince`, `ReviewSince`): git in the operator's worktrees, each
  snapshotted, its attributes' filters run (`lup_dev.policy.since`). Here both
  are refused, saying why (`unread`);
- a conversation's record (`ShowConversation`, `ShowContext`, a view's): read
  from the homes on the host. Here it's asked of the host as a copy, the one
  request the demo sends it (`ShowCopy`), and written into the copy.
What the handlers write is inside the copy's directory (`DemoLayout.lup`). A
worktree an item names, which the room mounts writable, is never written. The
landings waiting, which the host holds in memory alone, aren't copied, so none
waits here.
"""

import json
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, override

from pydantic import BaseModel, Field, ValidationError

from lup.types import Model, MutableModel
from lup_dashboard.errors import CopyError
from lup_dashboard.handled import Handled, handled
from lup_dev import Project
from lup_dev.clock import Clock, SystemClock
from lup_dev.conversions import inbox_opened
from lup_dev.declaration.load import load
from lup_dev.declaration.resolve import resolve
from lup_dev.errors import LupDevError
from lup_dev.host.client import FromRoom, RoomClient
from lup_dev.host.copying import Copied, Copy, RecordOf, ShowCopy
from lup_dev.host.courier import Conversations
from lup_dev.host.homes import Found
from lup_dev.host.names import SessionNames
from lup_dev.host.protocol import HostError, Register, Reply
from lup_dev.host.records import Recorded, Records
from lup_dev.host.service import Route, Served
from lup_dev.host.watch import Changes
from lup_dev.inbox.marks import MarksFile
from lup_dev.policy.checkpoint import Conversations as Working
from lup_dev.policy.checkpoint import Warned
from lup_dev.policy.since import ReviewSince, ShowSince
from lup_dev.policy.worktrees import Holding

if TYPE_CHECKING:
    from collections.abc import Callable

    from lup_dashboard.layout import DemoLayout
    from lup_dev.host.records import Reader, Record
    from lup_dev.layout import Layout


class Asking(Model):
    """The host, as the copy asks it: for its state files, or a conversation's record (`ShowCopy`), and nothing else."""

    room: FromRoom = Field(default_factory=lambda: FromRoom(room=RoomClient()))
    """The launch's request socket, where the room mounts it."""

    def copied(self, record: RecordOf | None = None) -> Copy:
        """Ask the host for its state files a copy holds, or with `record` that conversation's record, waiting for the answer.

        Raise `HostError` where the host refuses, as one running a copy of lup
        from before it answered this does, or can't be reached, as from outside
        a room.
        """
        return self.room.ask(ShowCopy(record=record), Copy)


class HostRecords(MutableModel, Records, arbitrary_types_allowed=True):
    """One runtime's records of the copy's conversations: each asked of the host as it's read, what came since the copy last read it alone, written into the copy laid out as its home has it, and read there."""

    runtime: str
    asking: Asking
    directory: Path
    """Where its records are written, the root every read of them stays inside."""
    places: dict[str, Path] = {}
    """Where each conversation's record is written, by their runtime's ids, once
    the host has given it."""
    turns: threading.Lock = Field(default_factory=threading.Lock)
    """Held while a record is asked and written, so two reads of one record at
    once never write what came twice."""

    @override
    def kept(self, under: list[Path], repository: Path) -> list[Record]:
        return []

    @override
    def held(self, session: str) -> bool:
        return False

    @override
    def conversation(self, session: str, agent: str | None) -> Found | None:
        """Ask the host for what came of the record since the copy last read it, add it to the copy, and return the record there; refused as the host refuses it, one of a session the operator ran on the host among them, with `HostError`."""
        key = json.dumps([session, agent])
        with self.turns:
            kept = self.places.get(key)
            held = kept.stat().st_size if kept is not None and kept.is_file() else 0
            record = RecordOf(
                runtime=self.runtime, session=session, agent=agent, held=held
            )
            files = self.asking.copied(record).files
            found = [self.written(each) for each in files if each.under == "home"]
            if not found:
                return None
            self.places = {**self.places, key: found[0]}
        return Found(record=found[0], root=self.directory)

    def written(self, copied: Copied) -> Path:
        """Add `copied` to the record in the copy, where it carries on from what's there; else write it whole, in one step, so a read meanwhile reads it whole. Return where it is."""
        place = self.directory / copied.place
        content = copied.content()
        if copied.start > 0:
            with place.open("ab") as adding:
                adding.write(content)
            return place
        place.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=place.parent, prefix=f".{place.name}.", delete=False
        ) as partial:
            partial.write(content)
        Path(partial.name).replace(place)
        return place


class Withholding(Model):
    """Why the copy refuses what an agent's branches changed since the operator saw them, which the drawer says in its place."""

    why: str = (
        "the copy reads no worktree: what an agent's branches changed is read with "
        "git in the operator's worktrees, which nothing in the copy runs"
    )


def unread(withholding: Withholding) -> list[Route]:
    """Route what an agent's branches changed since the operator saw them, and marking it reviewed, to a refusal saying why (`Withholding`): the host reads them with git in the operator's worktrees, snapshotting each, which the copy never runs."""

    async def refused(raw: str) -> Reply:
        del raw
        raise HostError(withholding.why)

    return [
        Route(kind=ShowSince.named(), answer=refused),
        Route(kind=ReviewSince.named(), answer=refused),
    ]


def written(lup: Layout, copied: Copied) -> Path:
    """Write `copied`, one of the host's state files, into the copy at `lup`, where the host keeps it, and return where.

    Raise `CopyError` for a record, which the host gives only when it's asked
    for one.
    """
    match copied.under:
        case "state":
            path = lup.state / copied.place
        case "runtime":
            path = lup.runtime / copied.place
        case "home":
            message = (
                f"the host gave a conversation's record, {copied.place}, among its "
                "state files"
            )
            raise CopyError(message)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(copied.content())
    return path


def model_of(lup: Layout, path: Path) -> type[BaseModel] | None:
    """Return the model this checkout reads the copied file at `path` with, where the host keeps it as the copy at `lup` lays it out; none for a file read otherwise, an attachment of the ledger's, read as it's asked for, or one this checkout doesn't keep.

    A launch's and a session's files are named by its id, then what they hold.
    """
    named = Path(Path(path.name).stem).stem
    host = lup.host
    marks = [each for kept in lup.every_marks() for each in kept.modules()]
    known: dict[Path, type[BaseModel]] = {
        host.record(named): Register,
        host.conversations(named): Conversations,
        host.names: SessionNames,
        lup.session(named): Holding,
        lup.conversations(named): Working,
        lup.warned(named): Warned,
        **dict.fromkeys(marks, MarksFile),
    }
    return known.get(path)


def checked(lup: Layout, paths: list[Path]) -> dict[Path, BaseModel]:
    """Read each copied file at `paths` with this checkout's model of it, and return what each holds, by where it is.

    Raise `CopyError` naming the first that doesn't read, and why: what the
    host would meet once this checkout is approved.
    """

    def read(path: Path, model: type[BaseModel]) -> BaseModel:
        try:
            return model.model_validate_json(path.read_bytes())
        except ValidationError as failed:
            message = f"{path}, copied from the host, doesn't read: {failed}"
            raise CopyError(message) from failed

    return {
        path: read(path, model)
        for path in paths
        if (model := model_of(lup, path)) is not None
    }


def taken(
    layout: DemoLayout,
    asking: Asking,
    root: Path,
    readers: dict[str, Reader],
    *,
    clock: Clock | None = None,
    say: Callable[[str], None] = lambda _: None,
    timings: Path | None = None,
) -> Handled:
    """Take a copy of the operator's dashboard state into `layout`, asked of the host through `asking`, and return the host over it: its handlers as this checkout has them, the launch's own repository's views answered by the declaration of the checkout at `root`, each runtime's records read by its reader of `readers`, as they're asked for, and what the page measures of itself kept in `timings`, else in the copy.

    Raise `CopyError` where a file copied, or this checkout's declaration,
    doesn't read, saying which and why; `HostError` where the host can't be
    asked, or refuses.
    """
    clock = clock or SystemClock()
    copy = asking.copied()
    lup = layout.lup
    found = checked(lup, [written(lup, each) for each in copy.files])
    changes = Changes()
    try:
        inbox = inbox_opened(lup, changes, say)
    except HostError as failed:
        message = f"the inbox copied from the host doesn't read: {failed}"
        raise CopyError(message) from failed
    try:
        declared = resolve(load(root).project)
    except LupDevError as unloaded:
        message = f"the declaration at {root} doesn't load: {unloaded}"
        raise CopyError(message) from unloaded
    recorded = {
        runtime: Recorded(
            records=HostRecords(
                runtime=runtime, asking=asking, directory=layout.records(runtime)
            ),
            reader=reader,
        )
        for runtime, reader in readers.items()
    }
    return handled(
        lup,
        inbox,
        changes,
        recorded,
        own=copy.repository,
        declared=declared,
        defaults=resolve(Project()),
        served=[
            Served(
                launch=each,
                conversations=served_conversations(found, lup, each.launch),
                servers=[],
            )
            for each in found.values()
            if isinstance(each, Register)
        ],
        beyond=unread(Withholding()),
        who="the copy",
        clock=clock,
        say=say,
        timings=timings,
    )


def served_conversations(
    found: dict[Path, BaseModel], lup: Layout, launch: str
) -> Conversations:
    """Return launch `launch`'s conversations as the copy holds them, read already (`checked`); none where none were kept."""
    kept = found.get(lup.host.conversations(launch))
    return kept if isinstance(kept, Conversations) else Conversations()
