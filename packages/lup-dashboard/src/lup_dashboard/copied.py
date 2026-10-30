"""The demo over a copy of the operator's dashboard state: the host's own handlers, as this checkout has them, over a copy in a directory of the demo's own, with nothing reaching the operator.

`docs/dashboard.md`, *The demo*. `lup-dashboard demo --copy` asks the host,
on the launch's request socket, for a copy of what the operator's dashboard
shows (`host-copy`, `lup_dev/host/copying.py`), every repository's, writes it
into a directory of its own (`CopyLayout`), and serves the page over it. Each
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

**Every view is answered by this checkout's modules** (`CopiedViews`): the
launch's own repository's from the declaration of the checkout the demo runs
in; another's, whose declaration is out of the room's reach, from lup's
defaults, as the stand-in demo's are, which the page says (`About.copied`).

**Nothing reaches out, by construction.** On the host, what the page's requests
set off reaches beyond the inbox. In the copy, each part that would is given
to the handlers as one that refuses, or keeps what it would do in the copy:
- an approval approved, by its answer or by a draft sent (`AnswerApproval`,
  `SendDraft`): the host installs the copy approved and restarts on it, in a
  process of its own (`Host.settle`, `lup-dev inbox answer --approve`). Here
  nothing is installed or run: the number is kept (`Withheld.settled`);
- a held change answered, the same ways: the host writes the answer into the
  store of the hold's worktree, runs git in that worktree and logs the verdict,
  for the hook waiting on it to put the files back or keep them
  (`Delivery.settle_hold`, `lup_dev.policy.holds.answer`). Here the answer is
  kept in memory (`Withheld.holds`), nothing written;
- an item for a conversation (`AnswerItem`, `SendItem`, `SendDraft`, an
  approval's comment, a landing's answer): the host releases their waiting
  call, pushes the item to their session on its connection to lup's tool
  server, or rings their runtime's messaging socket (`Delivery.delivered`,
  `wake`, `pushed`, `rung`). Here no call waits, no connection is open
  (`Pushes`), and the waker spells neither a push nor a ring (`Asleep`): no
  session is woken, or reached;
- an item for the operator, or one of theirs reopened: a desktop notice
  (`Delivery.noticed`, `notify-send`). Here it's kept (`Withheld.notices`);
- a launch renamed (`Rename`): its container renamed by podman
  (`Launches.moved`). Here there's no podman;
- a module's view (`Viewing`): the repository's process, started from its
  approved copy (`Workers`). Here this checkout's modules answer in this
  process, given the copy's records, items and marks, and none of the other
  repositories a declaration names, which the host finds with git
  (`CopiedModules`);
- what an agent's branches changed since the operator saw them, and marking it
  reviewed (`ShowSince`, `ReviewSince`): git in the operator's worktrees, each
  snapshotted, its attributes' filters run (`lup_dev.policy.since`). Here both
  are refused, saying why (`unread`);
- a conversation's record (`ShowConversation`, `ShowContext`, a view's): read
  from the homes on the host. Here it's asked of the host as a copy, the one
  request the demo sends it (`ShowCopy`), and written into the copy;
- a launch's hooks (the service's `Courier`, `Answerer` and judge): never heard
  here, nothing served on a launch's sockets (`NoCourier`, `NoAnswerer`,
  `NoJudge`).
What the handlers write, lup's state and runtime directory and each module's
data, is inside the copy's directory (`CopyLayout.lup`), what the page measured
of itself among it (`KeepTimings`), unless the demo was given a directory of
its own for that (`--timings`). A worktree an item
names, which the room mounts writable, is never written: the edges above are
the ways the host would. The landings waiting, which the host holds in memory
alone, aren't copied, so none waits here.
"""

import json
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, get_args, override

from pydantic import BaseModel, Field, ValidationError

from lup.types import Model, MutableModel
from lup_dashboard.api import Asked, Replied
from lup_dashboard.errors import CopyError, LupDashboardError
from lup_dashboard.host import Host, read
from lup_dashboard.layout import CopyLayout
from lup_dev import Project
from lup_dev.clock import Clock, SystemClock
from lup_dev.conversions import inbox_opened
from lup_dev.declaration.load import load
from lup_dev.declaration.resolve import Resolved, resolve
from lup_dev.errors import LupDevError
from lup_dev.host.client import FromRoom, RoomClient
from lup_dev.host.copying import Copied, Copy, RecordOf, ShowCopy
from lup_dev.host.courier import Conversations, Courier, Heard, Telling, Waker
from lup_dev.host.homes import Found
from lup_dev.host.names import Names, SessionNames
from lup_dev.host.protocol import HostError, Looks, Refused, Register, Reply, Request
from lup_dev.host.pushes import Pushes
from lup_dev.host.records import Recorded, Records
from lup_dev.host.service import (
    Answerer,
    Dispatcher,
    HoldingSetting,
    Launches,
    Renaming,
    Route,
    Served,
)
from lup_dev.host.service import Listing as LaunchesListing
from lup_dev.host.timings import TimingsStore
from lup_dev.host.timings import routes as timings_routes
from lup_dev.host.views import ModuleViews
from lup_dev.host.watch import Changes
from lup_dev.host.workers import LaunchJudge, RepositoryAsking, Viewing
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.exchanges import Exchanges
from lup_dev.inbox.marks import MarksFile, MarkStore, StoredMarks
from lup_dev.inbox.marks import routes as marks_routes
from lup_dev.inbox.notices import Notices
from lup_dev.inbox.protocol import Exchanged, ItemsListing, ListItems
from lup_dev.inbox.protocol import routes as inbox_routes
from lup_dev.inbox.store import HeldChange
from lup_dev.inbox.threaded import routes as threaded_routes
from lup_dev.layout import Layout
from lup_dev.policy.checkpoint import Conversations as Working
from lup_dev.policy.checkpoint import Warned
from lup_dev.policy.since import ReviewSince, ShowSince
from lup_dev.policy.waits import Waits
from lup_dev.policy.waits import routes as waits_routes
from lup_dev.policy.worktrees import Holding
from lup_dev.worker import RepositoryModules
from lup_ledger.parties import Conversation

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from lup.blocks import OfAgent
    from lup.tools.serving import Notice
    from lup.types import JsonObject
    from lup_dev.declaration.serving import Related
    from lup_dev.host.records import Reader, Record


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


class Asleep(Model, Waker):
    """Wakes no session: spells neither a push to it nor a ring of its messaging socket, so an item for a conversation waits for a call that never comes."""

    @override
    def woken(self, runtime: str, session: str, text: str) -> str | None:
        return None

    @override
    def pushed(self, runtime: str, text: str, token: str) -> Notice | None:
        return None

    @override
    def capabilities(self, runtime: str) -> dict[str, JsonObject]:
        return {}


class NoAnswerer(Model, Answerer):
    """Answers no runtime's hook: the copy serves no launch's."""

    @override
    def runtimes(self) -> list[str]:
        return []

    @override
    def unanswered(self, runtime: str, payload: str, failure: str) -> str:
        message = "the copy serves no launch's hooks"
        raise HostError(message)


class NoCourier(Model, Courier):
    """Reads no runtime's hook: the copy serves no launch's."""

    @override
    def heard(self, runtime: str, payload: str) -> Heard:
        message = "the copy serves no launch's hooks"
        raise HostError(message)

    @override
    def told(self, runtime: str, payload: str, answer: str, telling: Telling) -> str:
        message = "the copy serves no launch's hooks"
        raise HostError(message)


class NoJudge(Model, LaunchJudge):
    """Judges no launch's hook: the copy serves no launch's."""

    @override
    async def judged(self, launch: Register, payload: str) -> str:
        message = "the copy serves no launch's hooks"
        raise HostError(message)


class HoldAnswered(Model):
    """The operator's answer to a held change, as the host would write it for the hook waiting on it."""

    change: HeldChange
    approved: bool
    comment: str


class Withheld(MutableModel, Notices):
    """What the host would do beyond the inbox, which the copy keeps in its memory instead: each desktop notice, each answer to a held change, each approval it would install."""

    notices: list[str] = []
    holds: list[HoldAnswered] = []
    settled: list[int] = []
    """Each approval approved, by its number, whose copy the host would install."""

    @override
    async def notify(self, summary: str, body: str) -> None:
        self.notices = [*self.notices, f"{summary}\n{body}"]

    def hold(self, change: HeldChange, *, approved: bool, comment: str) -> None:
        """Keep the answer to `change`, where the host writes it for its hook (`Delivery.settle_hold`)."""
        answered = HoldAnswered(change=change, approved=approved, comment=comment)
        self.holds = [*self.holds, answered]


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


class CopiedExchanges(Model, Exchanges, arbitrary_types_allowed=True):
    """The copy's items one of a repository's conversations exchanged, as the host's handler answers `ListItems` over them."""

    repository: Path
    listing: ItemsListing

    @override
    async def exchanged(self, viewed: OfAgent) -> Exchanged:
        party = Conversation(
            repository=self.repository,
            runtime=viewed.runtime,
            session=viewed.session,
            agent=viewed.agent,
        )
        answered = await self.listing.answer(ListItems(conversation=party))
        if not isinstance(answered, Exchanged):
            message = f"the inbox answered a conversation's items with {answered.kind}"
            raise HostError(message)
        return answered


class CopiedModules(RepositoryModules):
    """A repository's modules in the copy: made as its process makes them, but given none of the other repositories its declaration names, which the host finds with git (`related_of`)."""

    @override
    def related(self) -> list[Related]:
        return []


class CopiedViews(MutableModel, RepositoryAsking, arbitrary_types_allowed=True):
    """Each repository's modules, answering its views as its process would, in this process: the asking launch's repository's made from this checkout's declaration, every other's from lup's defaults, its declaration out of the room's reach."""

    own: Path
    """The asking launch's repository's git directory."""
    declared: Resolved
    """This checkout's declaration, resolved: the launch's own repository's."""
    defaults: Resolved
    """lup's default declaration, resolved: every other repository's."""
    repositories: list[Path]
    """Each repository the copy's launches run in, whose views look as its
    modules say."""
    layout: Layout
    """lup's places in the copy, where each module keeps its own data."""
    recorded: dict[str, Recorded]
    listing: ItemsListing
    """The copy's items, as the host's handler lists a conversation's."""
    marks: MarkStore
    """The copy's review marks, as the host holds them."""
    made: dict[Path, CopiedModules] = {}

    def modules(self, repository: Path) -> CopiedModules:
        """Return `repository`'s modules, made once."""
        found = self.made.get(repository)
        if found is not None:
            return found
        made = CopiedModules(
            repository=repository,
            resolved=self.declared if repository == self.own else self.defaults,
            recorded=self.recorded,
            layout=self.layout,
            exchanges=CopiedExchanges(repository=repository, listing=self.listing),
            marks=StoredMarks(store=self.marks),
        )
        self.made = {**self.made, repository: made}
        return made

    def by_defaults(self) -> list[Path]:
        """List the repositories whose views lup's default modules answer."""
        return [each for each in self.repositories if each != self.own]

    @override
    async def asked(self, repository: Path, request: Request) -> Reply:
        """Answer a view of `repository`'s, or refuse it saying why, as its process does (`lup_dev.worker.Views`)."""
        if not isinstance(request, Viewing):
            message = f"the copy asks a repository's modules no `{request.kind}`"
            raise HostError(message)
        try:
            return await self.modules(repository).view(request)
        except LupDevError as refused:
            raise HostError(str(refused)) from refused

    @override
    @asynccontextmanager
    async def watching(self, repository: Path) -> AsyncGenerator[None]:
        """Hold nothing while a view of `repository`'s is watched: its modules stay made."""
        del repository
        yield

    @override
    def looks(self) -> dict[Path, Looks]:
        return {each: self.modules(each).resolved.looks for each in self.repositories}


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


def asked_kinds() -> list[str]:
    """List the kinds the page may ask (`api.Asked`)."""
    [union, _] = get_args(Asked.__value__)
    return [each.named() for each in get_args(union)]


def answering(routes: list[Route]) -> dict[str, Route]:
    """Return the routes of the kinds the page may ask, each by its kind, every other left out, so nothing else the handlers serve is reached.

    Raise `LupDashboardError` where a kind the page may ask has none.
    """
    kinds = asked_kinds()
    routed = {each.kind: each for each in routes if each.kind in kinds}
    missing = [each for each in kinds if each not in routed]
    if missing:
        message = f"the copy answers none of {', '.join(missing)}"
        raise LupDashboardError(message)
    return routed


class CopyHost(MutableModel, Host, arbitrary_types_allowed=True):
    """The host over a copy of the operator's dashboard state: each request answered by the host's own handler of its kind, over the copy, as this checkout has them (`taken`)."""

    layout: CopyLayout
    dispatcher: Dispatcher
    changes: Changes
    """Told once each request is answered, as the host service's control socket
    tells it, so each watch answers again."""
    views: CopiedViews
    withheld: Withheld
    """What the host would have done beyond the inbox, kept here instead."""

    @override
    async def ask(self, request: Asked) -> Replied:
        replied = await self.dispatcher.answered(request.model_dump_json())
        self.changes.changed()
        return read(replied.model_dump_json().encode())

    @override
    async def watch(self, request: Asked) -> AsyncGenerator[Replied]:
        sent = ""
        async for replied in self.dispatcher.replies(request.model_dump_json()):
            line = replied.model_dump_json()
            if line != sent:
                yield read(line.encode())
                sent = line
            if isinstance(replied, Refused):
                return

    @override
    async def settle(self, number: int) -> None:
        """Install nothing, and restart nothing: keep the approval's number."""
        self.withheld.settled = [*self.withheld.settled, number]


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
    layout: CopyLayout,
    asking: Asking,
    root: Path,
    readers: dict[str, Reader],
    *,
    clock: Clock | None = None,
    say: Callable[[str], None] = lambda _: None,
    timings: Path | None = None,
) -> CopyHost:
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
    withheld = Withheld()
    waits = Waits(changes=changes)
    delivery = Delivery(
        inbox=inbox,
        waker=Asleep(),
        pushes=Pushes(),
        layout=lup.host,
        notices=withheld,
        clock=clock,
        say=say,
        settle_hold=lambda change, approved, said: withheld.hold(
            change, approved=approved, comment=said
        ),
        landing=waits.holding,
    )
    recorded = {
        runtime: Recorded(
            records=HostRecords(
                runtime=runtime, asking=asking, directory=layout.records(runtime)
            ),
            reader=reader,
        )
        for runtime, reader in readers.items()
    }
    launches = Launches(
        layout=lup.host,
        answerer=NoAnswerer(),
        courier=NoCourier(),
        post=None,
        judge=NoJudge(),
        tools=[],
        room_routes=[],
        modules=None,
        line_limit=0,
        waker=Asleep(),
        pushes=Pushes(),
        say=say,
        names=Names(path=lup.host.names),
        changes=changes,
        clock=clock,
    )
    registered = [each for each in found.values() if isinstance(each, Register)]
    launches.served = {
        each.launch: Served(
            launch=each,
            conversations=served_conversations(found, lup, each.launch),
            servers=[],
        )
        for each in registered
    }
    views = CopiedViews(
        own=copy.repository,
        declared=declared,
        defaults=resolve(Project()),
        repositories=list(
            dict.fromkeys([copy.repository, *(each.repository for each in registered)])
        ),
        layout=lup,
        recorded=recorded,
        listing=ItemsListing(delivery=delivery),
        marks=inbox.marks,
    )
    module_views = ModuleViews(asking=views, changes=changes, say=say, clock=clock)
    routes = [
        Route.reading(
            LaunchesListing(
                launches=launches, asking=views, standing=views.defaults.looks
            )
        ),
        Route.to(Renaming(launches=launches)),
        Route.to(HoldingSetting(launches=launches)),
        *inbox_routes(delivery, recorded),
        *marks_routes(inbox.marks, clock, changes),
        *threaded_routes(delivery),
        *waits_routes(waits),
        *timings_routes(TimingsStore(home=timings or lup.host.timings), clock),
        *unread(Withholding()),
        Route.reading(module_views, watch=module_views.watched),
    ]
    return CopyHost(
        layout=layout,
        dispatcher=Dispatcher(
            routes=answering(routes), answering="the copy", say=say, changes=changes
        ),
        changes=changes,
        views=views,
        withheld=withheld,
    )


def served_conversations(
    found: dict[Path, BaseModel], lup: Layout, launch: str
) -> Conversations:
    """Return launch `launch`'s conversations as the copy holds them, read already (`checked`); none where none were kept."""
    kept = found.get(lup.host.conversations(launch))
    return kept if isinstance(kept, Conversations) else Conversations()
