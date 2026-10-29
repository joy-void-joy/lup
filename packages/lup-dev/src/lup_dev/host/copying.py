"""A copy of what the operator's dashboard shows, for a room: the host's state files as stored, and each conversation's record as it's asked for.

`docs/host.md`, *Reading from a room*; `docs/dashboard.md`, *The demo*. A
session working on the dashboard runs their own branch's page, server and views
over a copy of the operator's dashboard state (`lup-dashboard demo --copy`),
taken through their launch's request socket, among the requests a room makes
that only read (`ShowCopy`). No room holds the dashboard's token: it approves
trust, which installs the code the host runs, and answers holds.

**What's copied is a list, never the state with its secrets taken out**
(`kept`), so a file a later lup keeps beside these reaches no room until it's
named here:
- the inbox's ledger, as one state (`Ledger.copied`), the operator's draft, the
  order of their review and what they write on each conversation among it,
  and the attachments beside it;
- each repository's review marks;
- each launch's record, and its conversations;
- the name each session last had;
- the judge's session index.
Never the dashboard's token (`HostLayout.dashboard_token`), the values lup
keeps unpublished (`lup_dev.private`), an account's login, or a credential.

**Every repository's, on purpose.** A room's `inbox` reads its own
repository's items alone; the copy holds every repository's, since the
dashboard shows every repository's, at its real size, which a change to it is
measured at. Other projects' text comes with it: the page's data, never
instructions to the session reading it.

**A conversation's record is read as it's asked for** (`ShowCopy.record`),
since records are the bulk of it and only grow, so only what came since the
asker last read it is sent (`RecordOf.held`): a launched session's alone,
in the home its launch registered (`home_of`), never the operator's own
directory, which holds the sessions they run on the host. It's sent as stored,
alone: what its runtime saved beside it, as the whole output of a long call a
runtime saves apart, isn't, so that call reads as the record has it, its
preview.
"""

import asyncio
import base64
import os
from pathlib import Path, PurePosixPath
from typing import Literal, override

from pydantic import field_validator

from lup.rooms.homes import opened, regular
from lup.types import Model
from lup_dev.host.homes import home_of
from lup_dev.host.protocol import HostError, Register, Reply, Request
from lup_dev.host.records import Recorded
from lup_dev.host.rooms import RoomHandler
from lup_dev.layout import Layout
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger

type Under = Literal["state", "runtime", "home"]
"""Which of the host's places a file copied is kept under: lup's state
(`Layout.state`), lup's runtime directory (`Layout.runtime`), where the
launches are recorded, or the home a conversation's record is in."""


class Copied(Model):
    """One file copied: where it's kept, under which of the host's places, and its content as stored."""

    under: Under
    place: PurePosixPath
    """Its path under that place, relative, never leaving it, so a copy lays
    it out where the host keeps it."""
    encoded: str
    """Its content, in base64, so a file that isn't text crosses JSON whole."""
    start: int = 0
    """Where in the file its content starts: past what the asker holds of a
    record already (`RecordOf.held`); the file whole from its start
    otherwise."""

    @field_validator("place")
    @classmethod
    def within(cls, place: PurePosixPath) -> PurePosixPath:
        """Refuse a place that isn't a relative path staying under its place: a copy writes it there.

        >>> from pydantic import ValidationError
        >>> try:
        ...     Copied(under="state", place=PurePosixPath("../x"), encoded="")
        ... except ValidationError as refused:
        ...     print(refused.errors()[0]["msg"])
        Value error, ../x leaves the place it's kept under
        """
        if place.is_absolute() or not place.parts or ".." in place.parts:
            message = f"{place} leaves the place it's kept under"
            raise ValueError(message)
        return place

    @classmethod
    def of(
        cls, under: Under, place: PurePosixPath, content: bytes, start: int = 0
    ) -> Copied:
        r"""Copy `content`, kept at `place` under `under`, from `start` in the file on.

        >>> Copied.of("state", PurePosixPath("a.json"), b"\x00a").content()
        b'\x00a'
        """
        encoded = base64.b64encode(content).decode()
        return cls(under=under, place=place, encoded=encoded, start=start)

    def content(self) -> bytes:
        """Return its content, decoded."""
        return base64.b64decode(self.encoded, validate=True)


class RecordOf(Model):
    """One conversation's record, by its runtime's ids: session `session`'s own, or their subagent `agent`'s; past the bytes of it the asker holds already."""

    runtime: str
    session: str
    agent: str | None = None
    held: int = 0
    """How many of its bytes the asker holds, from its start: a record only
    grows, so only what came past them is sent; the record whole where it's
    shorter."""


class ShowCopy(Request, reads=True):
    """Ask, from a room, for a copy of what the operator's dashboard shows, every repository's: the host's state files as stored (`kept`); with `record`, that conversation's record alone."""

    kind: Literal["host-copy"] = "host-copy"
    record: RecordOf | None = None


class Copy(Reply):
    """The files copied, and the repository of the launch that asked, whose room has its worktrees."""

    kind: Literal["host-copied"] = "host-copied"
    repository: Path
    """The asking launch's repository's git directory, as the host recorded it."""
    files: list[Copied]


class Kept(Model):
    """One of the host's state files a copy holds: where it is, and where it goes in a copy."""

    path: Path
    under: Under
    place: PurePosixPath


def kept(layout: Layout) -> list[Kept]:
    """List the host's state files a copy holds, as `layout` places them, the ledger's database apart (`Ledger.copied`): the ledger's attachments, each repository's review marks, each launch's record and conversations, the name each session last had, and the judge's session index.

    Each is named here, by where lup keeps it, so nothing else in lup's state,
    a file a later lup adds among it, is copied until it's named.
    """
    attachments = LedgerLayout.of(layout).attachments
    state = [
        # An attachment being written has a suffix until it's renamed into place.
        *(each for each in listed(attachments) if not PurePosixPath(each.name).suffix),
        *(each for marks in layout.every_marks() for each in marks.modules()),
        layout.host.names,
        *(each for each in listed(layout.session_index) if each.suffix == ".json"),
    ]
    launches = [each for each in listed(layout.host.launches) if each.suffix == ".json"]
    return [
        *(
            Kept(path=each, under="state", place=placed(layout.state, each))
            for each in state
        ),
        *(
            Kept(path=each, under="runtime", place=placed(layout.runtime, each))
            for each in launches
        ),
    ]


def listed(directory: Path) -> list[Path]:
    """List `directory`'s entries, sorted; none where it isn't there."""
    return sorted(directory.iterdir()) if directory.is_dir() else []


def placed(root: Path, path: Path) -> PurePosixPath:
    """Return where `path` is under `root`, as a copy lays it out."""
    return PurePosixPath(path.relative_to(root).as_posix())


def read(path: Path) -> bytes | None:
    """Return the regular file at `path` whole, never through a link; none where it isn't one, or isn't there, as one removed while it was listed."""
    descriptor = regular(path)
    if descriptor is None:
        return None
    with open(descriptor, "rb") as reading:
        return reading.read()


class Copying(Model, RoomHandler[ShowCopy], arbitrary_types_allowed=True):
    """Answers `ShowCopy`: the host's state files a copy holds, every repository's, or one launched conversation's record; read off the event loop."""

    layout: Layout
    """lup's state on the host, and its runtime directory."""
    ledger: Ledger
    """The inbox's ledger, as the host service holds it open."""
    recorded: dict[str, Recorded]
    """Each runtime's records on this machine, and how they're read, by its name."""

    @override
    def request(self) -> type[ShowCopy]:
        return ShowCopy

    @override
    async def answer(self, request: ShowCopy, launch: Register) -> Reply:
        record = request.record
        files = await asyncio.to_thread(
            self.state if record is None else lambda: self.conversation(record)
        )
        return Copy(repository=launch.repository, files=files)

    def state(self) -> list[Copied]:
        """Copy the host's state files (`kept`), the ledger's database as one state: each as stored, one gone since it was listed passed over."""
        ledger = self.ledger.layout
        database = Copied.of(
            "state", placed(self.layout.state, ledger.database), self.ledger.copied()
        )
        return [
            database,
            *(
                Copied.of(each.under, each.place, content)
                for each in kept(self.layout)
                if (content := read(each.path)) is not None
            ),
        ]

    def conversation(self, record: RecordOf) -> list[Copied]:
        """Copy the record of the conversation `record` names, where it's a launched session's, from the home its launch registered; refused otherwise, saying why.

        Raise `HostError` for a runtime lup doesn't read, a session no launch
        was heard on, whose record is the operator's own, or a record that
        isn't there.
        """
        whose = f"{record.runtime} session {record.session}" + (
            "" if record.agent is None else f", subagent {record.agent},"
        )
        reading = self.recorded.get(record.runtime)
        if reading is None:
            message = f"lup doesn't read the records of {record.runtime}"
            raise HostError(message)
        if home_of(self.layout.host, record.runtime, record.session) is None:
            message = (
                f"the record of {whose} is in no launch's home: a copy holds no "
                "session the operator ran on the host"
            )
            raise HostError(message)
        found = reading.records.conversation(record.session, record.agent)
        opening = None if found is None else opened(found.root, found.record)
        if found is None or opening is None:
            message = f"the record of {whose} isn't on this machine"
            raise HostError(message)
        with opening:
            size = os.fstat(opening.fileno()).st_size
            start = record.held if record.held <= size else 0
            opening.seek(start)
            content = opening.read()
        place = placed(found.root, found.record)
        return [Copied.of("home", place, content, start)]
