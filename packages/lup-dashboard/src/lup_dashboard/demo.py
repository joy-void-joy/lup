"""The dashboard over stand-in data: the real page, every view populated, with no host service or session behind it.

`lup-dashboard demo` serves it, for looking at a view while it's built (a session
in a room screenshots it headless) and for the operator to try one before it
lands. Its state is seeded as the host keeps its own, in a directory of its own:
the items, threads, checks, review marks and draft on a ledger of its own, each
conversation's whereabouts, the launches and their names, the landing waiting.
Each request the page sends is answered by the host's own handler of its kind
(`lup_dashboard/handled.py`), so what the host refuses is refused here, and the
drive tests run over the host's rules rather than a stand-in's.

What stands in is what's beyond the host's handlers: each conversation's record
(`lup_dashboard/standins.py`); what an agent's branches changed since the
operator saw them, which the host reads with git in worktrees no demo has
(`since`, `reviewed`); the agents themselves, whose hooks and calls are a few
timers set going as the page first asks (`asking`): a question that arrives,
an approval's types read, two writes to a branch.
"""

import asyncio
import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, override

from pydantic import Field, JsonValue

from lup.events import CallFinished, CallStarted
from lup.types import Model, MutableModel
from lup_dashboard.handled import Handled, handled
from lup_dashboard.host import Host
from lup_dashboard.layout import DemoLayout
from lup_dashboard.standins import StandInReader, StandInRecords, StoodIn
from lup_dev import Project
from lup_dev.approval import Approval as ApprovedZone
from lup_dev.approval import WorkspaceTool
from lup_dev.clock import Clock, SystemClock
from lup_dev.copies import Copies, Kept, linked
from lup_dev.declaration.kinds import Levels, Role
from lup_dev.declaration.resolve import resolve
from lup_dev.host.courier import Conversation as Talking
from lup_dev.host.courier import Conversations
from lup_dev.host.names import Names
from lup_dev.host.protocol import (
    Activity,
    Limits,
    ListLaunches,
    Refused,
    Register,
)
from lup_dev.host.records import (
    Call,
    Called,
    Entry,
    Recorded,
    Said,
    Task,
    Transcript,
    Usage,
)
from lup_dev.host.service import Route, Served
from lup_dev.host.watch import Changes, Touched
from lup_dev.inbox import marks
from lup_dev.inbox.citations import resolved
from lup_dev.inbox.concerns import ROOT
from lup_dev.inbox.marks import CORE, ReviewMark
from lup_dev.inbox.parts import PartId
from lup_dev.inbox.protocol import Files, ListInbox, ShowFiles
from lup_dev.inbox.store import (
    ApiChanged,
    Approval,
    Binary,
    ChangedFile,
    Comment,
    Content,
    Decided,
    Decision,
    Done,
    Draft,
    Edit,
    Flagged,
    Found,
    Friction,
    HeldChange,
    HowItFelt,
    Inbox,
    Item,
    Letter,
    Message,
    Question,
    Quote,
    Reading,
    Reply,
    Review,
    Text,
    Told,
    Unresolved,
    Waiting,
    Whereabouts,
    cited,
)
from lup_dev.inbox.store import Asked as Ask
from lup_dev.inbox.texts import opening
from lup_dev.inbox.threaded import Joined
from lup_dev.inbox.threads import spoken
from lup_dev.policy.reviewed import Mark, Marks
from lup_dev.policy.since import (
    HeldAt,
    ReviewSince,
    ShowSince,
    Since,
    SinceFile,
    SincePlace,
    SinceReviewed,
    ViewedFile,
)
from lup_dev.policy.waits import Awaited, Declined, Wait
from lup_dev.stored import write_model
from lup_ledger.parties import Conversation, Lup, Operator
from lup_ledger.threads import (
    Check,
    In,
    Moved,
    Parked,
    Settled,
    Status,
    Thread,
    TimeCame,
)
from lup_ledger.threads import Done as ThreadDone

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from lup_dashboard.api import Asked, Replied
    from lup_dev.layout import Layout


class StandIn(Model):
    """A stand-in call: its step in a conversation, and what reading it whole answers."""

    step: Called
    whole: Call


def stand_in(
    id_: str,
    tool: str,
    gist: str | None,
    at: datetime,
    given: JsonValue,
    *,
    output: str | None = None,
) -> StandIn:
    """Return a stand-in call to `tool` saying `gist`, what it was given as its runtime's reader would say it, given `given`, which returned `output`; none while it runs."""
    return StandIn(
        step=Called(tool=tool, gist=gist, id=id_, at=at),
        whole=Call(id=id_, input=given, output=output),
    )


def steps(recorded: list[Said | StandIn]) -> list[Entry]:
    """Return a stand-in conversation's steps, as its record would hold them."""
    return [each.step if isinstance(each, StandIn) else each for each in recorded]


class Stands(Model):
    """A file of a stand-in branch as it stands: what the integration branch holds of it, what the branch makes of it, the flagged write on it, with the judge's reading, and the landing waiting on it."""

    path: Path
    before: Content | None
    after: Content | None
    flag: int | None = None
    reading: Reading | None = None
    held: HeldAt | None = None
    role: Role = "production"
    """Its path's role, as the host reads it by lup's default declaration."""


class Standing(MutableModel):
    """What a stand-in conversation's record says of it: what its context holds, and its task list."""

    usage: Usage | None = None
    tasks: list[Task] = []


class StandInThread(Model):
    """One of the demo's threads, as it seeds them: the thread, and what's in it, each by when it came, a part moved in by the part's place in its item."""

    thread: Thread
    members: list[Joined] = []


class Changing(Model):
    """What a stand-in item changes, as the host keeps it beside it: its number, and each file whole."""

    number: int
    files: list[ChangedFile]


class Threaded(Model):
    """The demo's threads as it seeds them: each with what's in it, the check in one, and each one's latest status."""

    threads: list[StandInThread]
    check: Check
    statuses: list[Status]


class Cast(Model):
    """One of the demo's conversations, as the host would have heard them: the launch they run in, by its id, what they're called, who spawned them, what they're doing, the thread they work in, by its name, and when they ended."""

    launch: str
    session: str
    agent: str | None = None
    own: str | None = None
    """A subagent's name; none for a session's own conversation, named as their launch."""
    kind: str | None = None
    parent: str | None = None
    """The runtime's id for the subagent that spawned them; none where their session's own conversation did."""
    activity: Activity
    works: str | None = None
    """For a session's own conversation, their root thread; for a subagent, the thread they joined or hold; none for one who works in their session's root."""
    ended: datetime | None = None

    def id(self) -> str:
        """Return lup's id for them."""
        return f"{self.launch}-{self.agent or self.session}"


class Demo(MutableModel, Host, arbitrary_types_allowed=True):
    """A host over stand-in state, as of the clock's time: launches, conversations and items seeded in a directory of its own as the host keeps its own, as the page first asks, and each request answered by the host's own handler (`handled`); what's beyond those, the records, the branches and the agents, stands in."""

    clock: Clock = SystemClock()
    # lup: ignore("runtime-mention", why="stand-in data: the runtimes the demo's launches show, not a feature built for one")
    runtimes: list[str] = ["claude", "codex"]
    """The runtimes the demo's launches run, by name: the first for most, the second for one."""
    say: Callable[[str], None] = lambda _: None
    """Where what the handlers say is said, a refusal or a failure among it."""
    kept: TemporaryDirectory[str] = Field(default_factory=TemporaryDirectory)
    """Where its state is kept, removed as the demo ends."""
    grown: int = 0
    """How many steps the parser subagent's conversation has taken since the demo began: one more each time their record is read, so a page following it sees it grow."""
    types_read: timedelta = timedelta(seconds=4)
    """How long the approval's types take to read, its files carrying the reading of their parse alone until then, as the host reads them in the background."""
    reading: asyncio.TimerHandle | None = None
    """The reading of the approval's types under way, once the page asked for its files."""
    arrives: timedelta = timedelta(seconds=10)
    """How long after the page first asks for the inbox a question of the parser subagent's arrives, so a session can watch the review keep its place as an item comes to a group above."""
    arriving: asyncio.TimerHandle | None = None
    """The arrival under way, once the page asked for the inbox."""
    size: int = 36
    """How many flagged writes of a busy day the review holds beside the demo's own items (`worked`), each of a module of hundreds of lines, from `workers` workers of the lup-impl session, each with a note and a friction, the first with a long conversation: none for the demo's own items alone, as its tests ask it."""
    first_worked: int = 1000
    """The number of the first item a worker made (`worked`): after the demo's own, so they're laid out after them."""
    workers: int = 6
    """How many workers the busy day's writes come from, subagents of the lup-impl session, each in a worktree of its own."""
    functions: int = 36
    """How many functions a worker's module holds, a dozen lines each: a file of hundreds of lines."""
    approval_lines: int = 0
    """How many lines the approval's change holds beside its own files, as one of lup's own code may hold tens of
    thousands (`approved`): none by default."""
    hooks: float = 0
    """How many stand-in hook calls a minute the workers make, each changing what one of them does and answering every watch again, as the host service answers each watch at each hook (`docs/host.md`, *Watching*); none by default."""
    hooked: int = 0
    """How many stand-in hook calls have come."""
    hooking: asyncio.TimerHandle | None = None
    """The next stand-in hook call, once the page first asked for the launches."""
    began: datetime | None = None
    """When the demo began, as of the clock the first time it's asked (`ago`)."""
    marks: dict[str, Marks] = {}
    """The files the operator marked reviewed in a drawer, by branch, kept in
    memory: what stands in for the judge's marks, read with git."""
    versions: dict[str, Content | None] = {}
    """Each version of a file a drawer showed, by its stand-in of git's id for
    it, which marking it reviewed keeps."""
    grows: timedelta = timedelta(seconds=20)
    """How long after the page first asks what the parser subagent's branch changed since the operator approved it two more writes come to it, so a session can watch the drawer bring them in."""
    growth: asyncio.TimerHandle | None = None
    """The growth under way, once the page asked."""
    grew: bool = False
    """Whether the two writes came."""
    lands: timedelta = timedelta(seconds=2)
    """How long after the operator answers the landing's file its stand-in call
    is done waiting, as a call wakes to the answer."""
    ticker: Path = Path("packages/lup-dev/src/lup_dev/ticker.py")
    """The fix-clock subagent's new module, flagged, held at landing."""
    ticker_names: Path = Path("packages/lup-dev/src/lup_dev/ticker_names.py")
    """The fix-clock subagent's module on their other branch, `clock-names`."""
    timings: Path | None = None
    """Where what the page measured of itself is kept, laid out as the host keeps
    it (`HostLayout.timings`), for `lup-dev dashboard timings --kept` to read;
    none keeps it in the demo's own directory, gone as the demo stops."""
    first_thread: int = 301
    """The number of the demo's first thread (`stand_in_threads`), the rest and
    their check numbered after it: past the demo's own items, as the ledger
    numbers every node from one sequence."""

    @override
    async def ask(self, request: Asked) -> Replied:
        self.asking(request)
        return await self.host.ask(request)

    @override
    async def watch(self, request: Asked) -> AsyncGenerator[Replied]:
        """Yield the reply at once, then again as the host's handlers answer it again (`Handled.watch`)."""
        self.asking(request)
        async for replied in self.host.watch(request):
            yield replied

    @override
    async def settle(self, number: int) -> None:
        await self.host.settle(number)

    def asking(self, request: Asked) -> None:
        """Set going what the page's first asking for it sets going: the workers' hook calls, the late question, the reading of the approval's types, the two writes to the parser subagent's branch."""
        later = asyncio.get_running_loop().call_later
        match request:
            case ListLaunches() if self.hooks > 0 and self.hooking is None:
                self.hooking = later(60 / self.hooks, self.hook)
            case ListInbox() if self.arriving is None:
                self.arriving = later(self.arrives.total_seconds(), self.arrive)
            case ShowFiles(number=54) if self.reading is None:
                self.reading = later(self.types_read.total_seconds(), self.typed)
            case ShowSince() if self.growth is None:
                self.growth = later(self.grows.total_seconds(), self.grow)
            case _:
                pass

    @cached_property
    def host(self) -> Handled:
        """Return the host's handlers over the demo's state, seeded (`seeded`) the first time it's asked."""
        layout = DemoLayout(home=Path(self.kept.name))
        lup = layout.lup
        changes = Changes()
        inbox = Inbox.kept_in(lup, changes)
        self.seeded(inbox)
        self.copies_kept(lup)
        defaults = resolve(Project())
        made = handled(
            lup,
            inbox,
            changes,
            {
                runtime: Recorded(
                    records=StandInRecords(
                        runtime=runtime,
                        directory=layout.records(runtime),
                        stands=self.stood,
                    ),
                    reader=StandInReader(),
                )
                for runtime in self.runtimes
            },
            own=self.lup_session().repository,
            declared=defaults,
            defaults=defaults,
            served=self.served(lup),
            beyond=self.branches(),
            who="the demo",
            clock=self.clock,
            say=self.say,
            timings=self.timings,
        )
        made.waits.began(self.landing())
        return made

    def copies_kept(self, lup: Layout) -> None:
        """Keep three copies of `lup-dev` in the demo's state, as a machine keeps them, for the plain page to list and switch between (`docs/dashboard.md`, *The plain page*): the first running, the second the one before it, the third on trial, never run."""
        repository = self.lup_session().repository
        copies = Copies(layout=lup.judge(repository))
        subjects = [
            "Merge the review's folds: what's folded stays folded across a reload",
            "Merge fix-the-clock: a tick no longer drifts past the hour",
            "Merge the way back: copies kept, a switch that falls back",
        ]
        now = self.clock.now()
        kept = [
            Kept(
                name=f"copy-{at}",
                repository=repository,
                approval=ApprovedZone(
                    commit=f"{at}c0ffee",
                    fingerprint=f"the zone at {at}c0ffee",
                    paths=[],
                    tool=WorkspaceTool(
                        name="lup-dev", package=Path("packages/lup-dev"), members=[]
                    ),
                    time=now - timedelta(hours=at + 1),
                ),
                subject=subject,
                answered=now - timedelta(hours=at + 1) if at != 2 else None,
            )
            for at, subject in enumerate(subjects)
        ]
        for each in reversed(kept):
            copies.place(each).bin.mkdir(parents=True)
            copies.recorded(each)
        copies.pin([kept[2].commit])
        copies.switch(copies.place(kept[0]))
        copies.back(copies.place(kept[1]))
        linked(lup.host_copies, copies.layout.home)

    def seeded(self, inbox: Inbox) -> None:
        """Keep the demo's state in `inbox`, as the host keeps its own: each item (`every`), with the files of each that changes any; each conversation's whereabouts (`cast`); each thread, its check, what's in each and its status (`stand_in_threads`); how far the operator has read and seen each, as of 3 minutes before the demo began, so what came since is new; and their draft from before the pile to read was there, the voice session's how it felt, @58, left for later, a park the page drops."""
        items = sorted(self.every(), key=lambda each: each.number)
        threaded = self.stand_in_threads()
        numbered = {each.thread.name: each.thread.number for each in threaded.threads}
        ledger = inbox.ledger
        with ledger.writing():
            for item in items:
                inbox.kept(item)
            for each in self.changing(items):
                inbox.filed(each.number, each.files)
            for place in self.places_heard(numbered):
                inbox.placed(place)
            for each in threaded.threads:
                ledger.kept(each.thread)
            ledger.kept(threaded.check)
            writers = {
                **{each.number: each.sender for each in items},
                threaded.check.number: threaded.check.by,
            }
            for each in threaded.threads:
                thread = each.thread
                for member in each.members:
                    ledger.drawn(
                        In(
                            source=member.node,
                            target=thread.number,
                            repository=thread.repository,
                            by=writers[member.node],
                            at=member.came,
                        )
                        if member.part is None
                        else Moved(
                            source=member.node,
                            part=member.part,
                            target=thread.number,
                            repository=thread.repository,
                            by=Operator(),
                            at=member.came,
                        )
                    )
            for status in threaded.statuses:
                ledger.drawn(status)
            self.read_before(inbox, items, threaded)
            inbox.drafted(Draft(parked=[58]))

    def read_before(self, inbox: Inbox, items: list[Item], threaded: Threaded) -> None:
        """Mark what the operator has read and seen as of 3 minutes before the demo began: each thread up to the last item in it that came by then, and each agent's group up to the last of theirs still waiting that was made by then."""
        known = [each.number for each in items]
        for each in threaded.threads:
            before = [
                member.node
                for member in each.members
                if member.part is None
                and member.node in known
                and member.came <= self.ago(3)
            ]
            if before:
                mark = ReviewMark(
                    key=marks.on_node(each.thread.number),
                    up_to=str(before[-1]),
                    at=self.ago(3),
                )
                inbox.marks.moved(each.thread.repository, CORE, [mark])
        waiting = [
            each
            for each in items
            if each.recipient == Operator() and isinstance(each.state, Waiting)
        ]
        senders = dict.fromkeys(
            each.sender for each in waiting if isinstance(each.sender, Conversation)
        )
        for sender in senders:
            before = [
                each.number
                for each in waiting
                if each.sender == sender and each.made <= self.ago(3)
            ]
            if before:
                mark = ReviewMark(
                    key=marks.seen(sender), up_to=str(max(before)), at=self.ago(3)
                )
                inbox.marks.moved(sender.repository, CORE, [mark])

    def changing(self, items: list[Item]) -> list[Changing]:
        """Return the files each of `items` that changes any changes, as the host keeps them beside it: the approval's with the reading of their parse alone, until its types are read (`typed`)."""
        fix_clock = {
            68: self.clock_stands(),
            69: self.names_stands(),
        }

        def files_of(number: int) -> list[ChangedFile]:
            if number >= self.first_worked:
                return self.worked_changed(number)
            stands = fix_clock.get(number)
            if stands is None:
                return kept_files(number, typed=False, lines=self.approval_lines)
            return [
                ChangedFile(
                    path=each.path,
                    before=each.before,
                    after=each.after,
                    reading=each.reading,
                )
                for each in stands
            ]

        return [
            Changing(number=each.number, files=files_of(each.number))
            for each in items
            if isinstance(each.reason, Approval | HeldChange | Flagged)
        ]

    def worked_changed(self, number: int) -> list[ChangedFile]:
        """Return the files a worker's flagged write changes (`worked_files`)."""
        found = self.worked_files(number)
        return found.files if isinstance(found, Files) else []

    def launches(self) -> list[Register]:
        """Return four launches over three repositories: one with subagents working, asking and ended; one idle; one on the second runtime; one whose session hasn't started."""
        first, second = self.runtimes
        return [
            launch(LUP_IMPL, "lup-impl", first, Path("/home/op/lup.git/tree/dev")),
            launch(
                "b2e1",
                "guidance-voice",
                first,
                Path("/home/op/lup.git/tree/guidance-voice"),
            ),
            launch("c3d2", "main", second, Path("/home/op/zoetrope.git/tree/main")),
            launch(
                "d4c3", "magpie-search", first, Path("/home/op/magpie.git/tree/main")
            ),
        ]

    def ended_launch(self) -> Register:
        """Return the launch the docs session ran in, which has ended since: no record of it is kept, and nothing of it served."""
        first, _ = self.runtimes
        return launch(
            "e5f4", "docs-pass", first, Path("/home/op/lup.git/tree/docs-pass")
        )

    def cast(self) -> list[Cast]:
        """Return each conversation the host would have heard: the lup-impl session, their subagents working, asking and ended, and each worker of a busy day; the voice session, idle; zoetrope's session and their subagent; no one in the demo's last launch, whose session hasn't started; and the docs session, whose launch has ended."""
        calling = Activity(state="calling", since=self.ago(0.4), tool="Bash")
        ended = [
            Cast(
                launch=LUP_IMPL,
                session="s1",
                agent=f"a0{at + 4}",
                own=name,
                kind="Explore",
                activity=Activity(state="ended", since=self.ago(minutes)),
                works=works,
                ended=self.ago(minutes),
            )
            for at, (name, minutes, works) in enumerate(
                [
                    ("survey-legacy", 52, "legacy-cache"),
                    ("probe-meta", 40, None),
                    ("nest-probe", 33, None),
                ]
            )
        ]
        return [
            Cast(
                launch=LUP_IMPL,
                session="s1",
                activity=calling,
                works="lup-impl",
            ),
            Cast(
                launch=LUP_IMPL,
                session="s1",
                agent="a01",
                own="explore-auth",
                kind="Explore",
                activity=Activity(state="calling", since=self.ago(1.5), tool="Grep"),
                works="auth-survey",
            ),
            Cast(
                launch=LUP_IMPL,
                session="s1",
                agent="a02",
                own="parser",
                kind="general-purpose",
                activity=self.parser_waiting(),
                works="transcript-reader",
            ),
            Cast(
                launch=LUP_IMPL,
                session="s1",
                agent="a03",
                own="grep-tokens",
                kind="general-purpose",
                parent="a02",
                activity=Activity(state="idle", since=self.ago(0.2)),
                works="transcript-reader",
            ),
            *ended,
            Cast(
                launch=LUP_IMPL,
                session="s1",
                agent=FIX_CLOCK,
                own="fix-clock",
                kind="general-purpose",
                activity=Activity(state="ended", since=self.ago(25)),
                works="clock-ticks",
                ended=self.ago(25),
            ),
            *(
                Cast(
                    launch=LUP_IMPL,
                    session="s1",
                    agent=worker_agent(n),
                    own=f"worker-{n}",
                    kind="general-purpose",
                    activity=self.worker_doing(n),
                    works=f"module-{n}",
                )
                for n in range(1, self.workers + 1)
                if self.size > 0
            ),
            Cast(
                launch="b2e1",
                session="s2",
                activity=Activity(state="idle", since=self.ago(12)),
                works="guidance-voice",
            ),
            Cast(
                launch="c3d2",
                session="s3",
                activity=Activity(
                    state="calling", since=self.ago(2), tool="exec_command"
                ),
                works="main",
            ),
            Cast(
                launch="c3d2",
                session="s3",
                agent="th-7",
                own="render_frames",
                kind="default",
                activity=Activity(
                    state="calling", since=self.ago(0.7), tool="exec_command"
                ),
            ),
            Cast(
                launch="e5f4",
                session="s4",
                activity=Activity(state="ended", since=self.ago(190)),
                works="docs-pass",
                ended=self.ago(190),
            ),
        ]

    def places_heard(self, numbered: dict[str, int]) -> list[Whereabouts]:
        """Return where each conversation was last heard, as the inbox keeps it (`cast`), each thread they work in by its number in `numbered`."""
        launches = {
            each.launch: each for each in [*self.launches(), self.ended_launch()]
        }

        def heard(each: Cast) -> Whereabouts:
            register = launches[each.launch]
            party = Conversation(
                repository=register.repository,
                runtime=register.runtime,
                session=each.session,
                agent=each.agent,
            )
            main = party.main()
            thread = None if each.works is None else numbered[each.works]
            return Whereabouts(
                conversation=party,
                launch=each.launch,
                worktree=register.worktree,
                since=self.ago(480),
                ended=each.ended,
                parent=None
                if each.agent is None
                else main
                if each.parent is None
                else main.model_copy(update={"agent": each.parent}),
                name=each.own,
                thread=None if each.agent is None else thread,
                root=thread if each.agent is None else None,
            )

        return [heard(each) for each in self.cast()]

    def served(self, lup: Layout) -> list[Served]:
        """Return each launch as the host serves it, its record and each session's name written where the host keeps them, which say whose conversations still hold what they hold, and how they're called."""
        cast = self.cast()
        names = Names(path=lup.host.names)

        def talking(each: Cast) -> Talking:
            own = [other for other in cast if other.launch == each.launch]
            [main] = [other for other in own if other.agent is None]
            spawner = next((other for other in own if other.agent == each.parent), main)
            return Talking(
                id=each.id(),
                session=each.session,
                agent=each.agent,
                name=each.own,
                parent=None if each.agent is None else spawner.id(),
                kind=each.kind,
            )

        def of(register: Register) -> Served:
            write_model(lup.host.record(register.launch), register)
            own = [each for each in cast if each.launch == register.launch]
            sessions = list(dict.fromkeys(each.session for each in own))
            for session in sessions:
                names.keep(session, register.name or register.launch)
            return Served(
                launch=register,
                conversations=Conversations(
                    known=[talking(each) for each in own],
                    session=next(iter(sessions), None),
                    activities={each.id(): each.activity for each in own},
                ),
                servers=[],
            )

        return [of(each) for each in self.launches()]

    def branches(self) -> list[Route]:
        """Route what an agent's branches changed since the operator saw them, and marking it reviewed, to what stands in for reading them with git (`since`, `reviewed`), since no demo has their worktrees."""

        async def showing(raw: str) -> Since:
            asked = ShowSince.model_validate_json(raw)
            return self.since(asked.conversation, asked.seen)

        async def reviewing(raw: str) -> SinceReviewed | Refused:
            asked = ReviewSince.model_validate_json(raw)
            return self.reviewed(
                asked.conversation,
                asked.branch,
                asked.files,
                asked.seen,
                decline=asked.decline,
            )

        return [
            Route(kind=ShowSince.named(), answer=showing),
            Route(kind=ReviewSince.named(), answer=reviewing),
        ]

    def stood(self, runtime: str, session: str, agent: str | None) -> StoodIn:
        """Return the record of a conversation as it stands: the parser subagent's a step longer each time it's read, as when the page reads their drawer."""
        if (session, agent) == ("s1", "a02"):
            self.grown += 1
        recorded = self.recorded(session, agent)
        standing = self.standing(session, agent)
        return StoodIn(
            transcript=Transcript(
                runtime=runtime,
                session=session,
                entries=steps(recorded),
                usage=standing.usage,
                tasks=standing.tasks,
            ),
            calls=[each.whole for each in recorded if isinstance(each, StandIn)],
        )

    def stand_in_threads(self) -> Threaded:
        """Return the demo's threads, over its items (`every`): each session's root, held by them; the lup-impl session's work under theirs, the parser's reader with its question, a check and the parser's exchange with their subagent, explore-auth's survey new with its exchange with the session, the clock's ticks whose landing waits on a file, the legacy reader's cache settled, the reader's names parked; the voice session's root done, to confirm, with a part of the operator's words moved under it; zoetrope's render, its problem asking; the docs pass, the root of a session that has ended, its last note read, which its end settles not; and each worker's module, of a busy day."""
        first, second = self.runtimes
        lup = Path("/home/op/lup.git")
        zoetrope = Path("/home/op/zoetrope.git")
        session = self.lup_session()
        parser = session.model_copy(update={"agent": "a02"})
        explorer = session.model_copy(update={"agent": "a01"})
        survey = session.model_copy(update={"agent": "a04"})
        clock = session.model_copy(update={"agent": FIX_CLOCK})
        voice = Conversation(repository=lup, runtime=first, session="s2")
        docs = Conversation(repository=lup, runtime=first, session="s4")
        main = Conversation(repository=zoetrope, runtime=second, session="s3")
        items = {each.number: each for each in self.every()}
        (
            lup_root,
            reader,
            auth,
            ticks,
            cache,
            names,
            voice_root,
            branch,
            zoetrope_root,
            past,
            reached,
            docs_root,
        ) = range(self.first_thread, self.first_thread + 12)
        workers_from = self.first_thread + 12

        def came(number: int) -> Joined:
            item = items.get(number)
            return Joined(node=number, came=self.ago(0) if item is None else item.made)

        def thread(
            number: int,
            name: str,
            title: str,
            *,
            holder: Conversation | None,
            parent: int | None = None,
            minutes: float = 60,
            repository: Path = lup,
        ) -> Thread:
            return Thread(
                number=number,
                repository=repository,
                by=holder or Lup(),
                at=self.ago(minutes),
                name=name,
                title=title,
                parent=parent,
                holder=holder,
            )

        tried = Check(
            number=reached,
            repository=lup,
            by=parser,
            at=self.ago(3.8),
            text=(
                "Open the longest record you have and search a word in it: the "
                "search finds it, and nothing hangs."
            ),
        )
        workers = [
            StandInThread(
                thread=thread(
                    workers_from + n,
                    f"module-{n}",
                    f"Worker {n}'s module",
                    holder=self.worker(n),
                    parent=lup_root,
                    minutes=420,
                ),
                members=[
                    came(each.number)
                    for each in self.worked()
                    if each.sender == self.worker(n)
                ],
            )
            for n in range(1, self.workers + 1)
            if self.size > 0
        ]
        stood = [
            StandInThread(
                thread=thread(lup_root, "lup-impl", ROOT, holder=session, minutes=480),
                members=[came(60), came(55), came(62)],
            ),
            StandInThread(
                thread=thread(
                    reader,
                    "transcript-reader",
                    "The transcript reader",
                    holder=parser,
                    parent=lup_root,
                    minutes=40,
                ),
                members=[
                    came(47),
                    came(67),
                    came(70),
                    came(59),
                    came(51),
                    Joined(node=reached, came=tried.at),
                    came(57),
                ],
            ),
            StandInThread(
                thread=thread(
                    auth,
                    "auth-survey",
                    "Where auth is checked",
                    holder=explorer,
                    parent=lup_root,
                    minutes=8,
                ),
                members=[came(64), came(65), came(66)],
            ),
            StandInThread(
                thread=thread(
                    ticks,
                    "clock-ticks",
                    "The clock's ticks",
                    holder=clock,
                    parent=lup_root,
                    minutes=35,
                ),
                members=[came(68), came(69)],
            ),
            StandInThread(
                thread=thread(
                    cache,
                    "legacy-cache",
                    "The legacy reader's cache",
                    holder=survey,
                    parent=lup_root,
                    minutes=20,
                ),
                members=[came(44)],
            ),
            StandInThread(
                thread=thread(
                    names,
                    "reader-names",
                    "The reader's names",
                    holder=parser,
                    parent=reader,
                    minutes=15,
                ),
            ),
            StandInThread(
                thread=thread(
                    voice_root, "guidance-voice", ROOT, holder=voice, minutes=30
                ),
                members=[came(52), came(45), came(56), came(58)],
            ),
            StandInThread(
                thread=thread(
                    branch,
                    "voice-branch",
                    "Put the voice on its branch",
                    holder=voice,
                    parent=voice_root,
                    minutes=7,
                ),
                members=[Joined(node=50, part=3, came=self.ago(7))],
            ),
            StandInThread(
                thread=thread(
                    zoetrope_root,
                    "main",
                    ROOT,
                    holder=main,
                    minutes=90,
                    repository=zoetrope,
                ),
                members=[came(53)],
            ),
            StandInThread(thread=thread(past, "dev", ROOT, holder=None, minutes=2880)),
            StandInThread(
                thread=thread(docs_root, "docs-pass", ROOT, holder=docs, minutes=240),
                members=[came(43)],
            ),
            *workers,
        ]
        return Threaded(
            threads=stood,
            check=tried,
            statuses=[
                Settled(target=cache, repository=lup, by=Operator(), at=self.ago(16)),
                Parked(
                    target=names,
                    repository=lup,
                    by=parser,
                    at=self.ago(14),
                    until=[TimeCame(at=self.ago(-120))],
                    why="named once the reader lands",
                ),
                ThreadDone(
                    target=voice_root,
                    repository=lup,
                    by=voice,
                    at=self.ago(1.3),
                    to_try=(
                        "Read the voice section of AGENTS.md: each line says what "
                        "is, and its examples are short."
                    ),
                ),
                Settled(
                    target=past,
                    repository=lup,
                    by=Lup(),
                    at=self.ago(2000),
                    why="nothing waited when threads came: converted",
                ),
            ],
        )

    def typed(self) -> None:
        """End the reading of the approval's types, as the host's does (`lup_dev.inbox.typed`): its files kept with their whole reading, and the approval kept, which each watch sees."""
        inbox = self.host.inbox
        inbox.filed(54, kept_files(54, typed=True, lines=self.approval_lines))
        item = inbox.item(54)
        if isinstance(item.reason, Approval):
            read = item.reason.model_copy(update={"typing": False})
            inbox.kept(item.model_copy(update={"reason": read}))

    def arrive(self) -> None:
        """Let the parser subagent's late question arrive, made at the clock's time, in the thread they work in, as an item a call of theirs made does."""
        delivery = self.host.delivery
        parser = self.lup_session().model_copy(update={"agent": "a02"})
        question = Question(
            text=(
                "The reader is done but for its name. Which, for the module and the "
                "class?"
            ),
            decisions=[
                Decision(
                    text="`transcripts.reader`, as the first lup called it",
                    lean="yes: sessions looking for it will look there first",
                )
            ],
        )
        item = delivery.inbox.kept(
            Item(
                number=61,
                reason=question,
                sender=parser,
                recipient=Operator(),
                worktree=parser.repository / "tree" / "dev",
                call="call-61",
                made=self.clock.now(),
            )
        )
        delivery.landed(item)

    def grow(self) -> None:
        """Let the parser subagent start the two writes to their branch, calling `Edit`, and end the call a moment later (`wrote`), as their hooks would say."""
        self.doing(
            "a02",
            Activity(state="calling", since=self.ago(0), tool="Edit"),
            CallStarted.named(),
        )
        asyncio.get_running_loop().call_later(1.5, self.wrote)

    def wrote(self) -> None:
        """Let the two writes land on the parser subagent's branch as their call ends: their drawer brings them in as the page reads it at that hook."""
        self.grew = True
        self.doing("a02", self.parser_waiting(), CallFinished.named())

    def doing(self, agent: str, activity: Activity, by: str) -> None:
        """Say what subagent `agent` of the lup-impl session is doing, as a hook of theirs at event `by` says, and tell each watch, a view of theirs among them."""
        session = self.lup_session()
        served = self.host.launches.served[LUP_IMPL].conversations
        known = next(each for each in served.known if each.agent == agent)
        served.activities = {**served.activities, known.id: activity}
        self.host.changes.changed(
            [
                Touched(
                    repository=session.repository,
                    runtime=session.runtime,
                    session=session.session,
                    agent=agent,
                    by=by,
                )
            ]
        )

    def parser_waiting(self) -> Activity:
        """Return what the parser subagent does but while they write: waiting on the operator's answer to their question."""
        return Activity(
            state="calling", since=self.ago(4), tool="mcp__lup__ask", lups=True
        )

    def standing(self, session: str, agent: str | None) -> Standing:
        """Return what a stand-in conversation's record says of it: the parser subagent's three tasks and a ninth of the long window; their session's half of it and no task; the second runtime's session's own window and plan; none for the rest."""
        match (session, agent):
            case ("s1", "a02"):
                return Standing(
                    usage=Usage(used=112_000, window=1_000_000, model="opus-4-1"),
                    tasks=[
                        Task(id="1", subject="Read the records", status="completed"),
                        Task(
                            id="2",
                            subject="Write the reader",
                            status="in_progress",
                            active="Writing the reader",
                        ),
                        Task(
                            id="3", subject="Test each kind of line", status="pending"
                        ),
                    ],
                )
            case ("s1", None):
                return Standing(
                    usage=Usage(used=512_000, window=1_000_000, model="opus-4-1")
                )
            case ("s3", _):
                return Standing(
                    usage=Usage(used=61_000, window=272_000, model="gpt-5.1"),
                    tasks=[
                        Task(
                            id="1",
                            subject="Render the second scene",
                            status="in_progress",
                        ),
                        Task(id="2", subject="Cut the reel", status="pending"),
                    ],
                )
            case _:
                return Standing()

    def since(self, conversation: Conversation, seen: str | None) -> Since:
        """Return what a stand-in conversation's branches changed since the operator last saw them (`drawn`): the parser subagent's new reader module and its test and, once `grew`, the reader grown and a change to the clock beside it; explore-auth's survey, to review with nothing flagged; a worker's modules; the ended fix-clock subagent's clock module, held at landing while the landing waits, and a module on a branch no worktree has checked out; nothing for the rest."""
        places = self.places(conversation)
        version = " | ".join(
            stand_in_id(Text(text=each.model_dump_json())) or "" for each in places
        )
        if seen == version:
            return Since(version=version, same=True)
        return Since(version=version, places=places)

    def places(self, conversation: Conversation) -> list[SincePlace]:
        """Return each place a stand-in conversation worked, as its drawer shows it (`since`)."""
        dev = conversation.repository / "tree" / "dev"
        worker = next(
            (
                n
                for n in range(1, self.workers + 1)
                if worker_agent(n) == conversation.agent
            ),
            None,
        )
        if conversation.session != "s1":
            return [SincePlace(worktree=dev, branch=None)]
        if worker is not None and self.size > 0:
            tree = worker_worktree(worker)
            return [self.drawn(tree, f"worker-{worker}", self.worked_stands(worker))]
        if conversation.agent == "a01":
            return [self.drawn(dev, "auth-survey", self.survey_stands())]
        if conversation.agent == "a02":
            return [self.drawn(dev, "feat-reader", self.parser_stands())]
        if conversation.agent == FIX_CLOCK:
            tree = conversation.repository / "tree" / "fix-clock"
            return [
                self.drawn(
                    tree, "fix-clock", self.clock_stands(self.held_at_landing())
                ),
                self.drawn(None, "clock-names", self.names_stands()),
            ]
        return [SincePlace(worktree=dev, branch=None)]

    def fix_clock_flags(self) -> list[Item]:
        """Return the ended fix-clock subagent's two flagged writes: their ticker module on `fix-clock`, which the session's landing waits on, and the names beside it on `clock-names`, which no worktree has checked out."""
        writer = self.lup_session().model_copy(update={"agent": FIX_CLOCK})
        tree = writer.repository / "tree" / "fix-clock"
        return [
            Item(
                number=number,
                reason=Flagged(
                    text=f"{path} landed, flagged for the operator's review.",
                    summary=f"{path} is a new production file",
                    worktree=tree,
                    path=path,
                    branch=branch,
                ),
                sender=writer,
                recipient=Operator(),
                worktree=tree,
                call=f"call-{number}",
                made=self.ago(minutes),
            )
            for number, path, branch, minutes in [
                (68, self.ticker, "fix-clock", 30),
                (69, self.ticker_names, "clock-names", 28),
            ]
        ]

    def held_at_landing(self) -> HeldAt | None:
        """Return the landing waiting on the fix-clock subagent's clock module, as their drawer shows it held there; none once it's done waiting."""
        waiting = self.host.waits.waits.get(LANDING_KEY)
        if waiting is None:
            return None
        return HeldAt(
            key=LANDING_KEY,
            lander=waiting.lander,
            named=waiting.named,
            tip=waiting.tip,
            declined=any(each.declined is not None for each in waiting.files),
        )

    def clock_stands(self, held: HeldAt | None = None) -> list[Stands]:
        """Return the fix-clock subagent's branch as it stands: the clock module, flagged, `held` at landing while the session's landing waits on it."""
        return [
            Stands(
                path=self.ticker,
                before=None,
                after=Text(text=CLOCK_SOURCE),
                flag=68,
                reading=Reading(
                    role="production",
                    asks=[
                        Ask(name="new-file", taken="flagged"),
                        Ask(
                            name="public-api",
                            taken="flagged",
                            line=4,
                            api=ApiChanged(kind="class-added", name="Ticker"),
                        ),
                    ],
                ),
                held=held,
            )
        ]

    def names_stands(self) -> list[Stands]:
        """Return the fix-clock subagent's other branch, `clock-names`, which no worktree has checked out: a module of names, flagged."""
        return [
            Stands(
                path=self.ticker_names,
                before=None,
                after=Text(text=NAMES_SOURCE),
                flag=69,
                reading=Reading(
                    role="production", asks=[Ask(name="new-file", taken="flagged")]
                ),
            )
        ]

    def lup_session(self) -> Conversation:
        """Return the lup-impl session's own conversation, who lands the fix-clock subagent's branch."""
        first, _ = self.runtimes
        return Conversation(
            repository=Path("/home/op/lup.git"), runtime=first, session="s1"
        )

    def landing(self) -> Wait:
        """Return the landing waiting on the operator: the lup-impl session's landing of `fix-clock` on `dev`, waiting on its clock module, held in the fix-clock subagent's drawer."""
        writer = self.lup_session().model_copy(update={"agent": FIX_CLOCK})
        return Wait(
            key=LANDING_KEY,
            repository=Path("/home/op/lup.git"),
            lander=self.lup_session(),
            onto="refs/heads/dev",
            old=None,
            tip=LANDING_TIP,
            branches=["fix-clock"],
            files=[Awaited(path=self.ticker, flags=[68], writers=[writer])],
            began=self.ago(3),
        )

    def landed(self) -> None:
        """End the stand-in landing's wait, the operator having answered its file: landed where they approved it, not where they declined it; each watch answers again."""
        self.host.waits.ended(LANDING_KEY)

    def survey_stands(self) -> list[Stands]:
        """Return explore-auth's branch as it stands: their survey, written with nothing flagged, so it's only to review."""
        return [
            Stands(
                path=Path("docs/auth-survey.md"),
                before=None,
                after=Text(text=SURVEY_SOURCE),
                role="docs",
            )
        ]

    def parser_stands(self) -> list[Stands]:
        """Return the parser subagent's branch as it stands: their new reader module, flagged, and its test; once `grew`, the reader with a method more and the clock's change, flagged."""
        [reader] = kept_files(59)
        [clock] = kept_files(60)
        grown = Text(text=READER + READER_GROWN)
        test = Stands(
            path=Path("packages/lup/tests/test_reader.py"),
            before=None,
            after=Text(text=TEST_READER),
            role="test",
        )
        return [
            *(
                [
                    Stands(
                        path=clock.path,
                        before=clock.before,
                        after=clock.after,
                        flag=60,
                        reading=clock.reading,
                    )
                ]
                if self.grew
                else []
            ),
            Stands(
                path=reader.path,
                before=None,
                after=grown if self.grew else reader.after,
                flag=59,
                reading=reader.reading,
            ),
            test,
        ]

    def worked_stands(self, n: int) -> list[Stands]:
        """Return worker `n`'s branch as it stands: the module of each of their flagged writes (`worked_files`)."""
        numbers = [
            each.number
            for each in self.worked()
            if isinstance(each.reason, Flagged) and each.sender == self.worker(n)
        ]
        return [
            Stands(
                path=file.path,
                before=file.before,
                after=file.after,
                flag=number,
                reading=file.reading,
            )
            for number in numbers
            if isinstance(found := self.worked_files(number), Files)
            for file in found.files
        ]

    def flag_approved(self, number: int) -> bool:
        """Say whether flagged write `number` is approved, as the inbox has it."""
        item = self.host.inbox.items.get(number)
        return (
            item is not None and isinstance(item.state, Decided) and item.state.approved
        )

    def drawn(
        self, worktree: Path | None, branch: str, stands: list[Stands]
    ) -> SincePlace:
        """Return a place of a stand-in drawer as the host reads it (`lup_dev.policy.since`): each file of `stands` from the version the operator last marked reviewed, else from the integration branch's, one standing as it was marked with nothing under it; its flag's reading while it isn't approved, and the landing waiting on it."""
        marks = self.marks.get(branch, Marks(branch=branch))
        self.versions = {
            **self.versions,
            **{
                version: each.after
                for each in stands
                if (version := stand_in_id(each.after)) is not None
            },
        }

        def filed(each: Stands) -> SinceFile | None:
            mark = marks.of(each.path)
            before = each.before
            if mark is not None:
                before = (
                    None if mark.version is None else self.versions.get(mark.version)
                )
            flags = (
                []
                if each.flag is None or self.flag_approved(each.flag)
                else [each.flag]
            )
            held = each.held if flags else None
            shown = SinceFile(
                path=each.path,
                version=stand_in_id(each.after),
                flags=flags,
                reviewed=None if mark is None else mark.at,
                held=held,
                role=each.role,
                level=Levels().model_dump()[each.role],
            )
            if before == each.after:
                return None if mark is None and held is None else shown
            file = ChangedFile(
                path=each.path,
                before=before,
                after=each.after,
                reading=each.reading if flags else None,
            )
            return shown.model_copy(update={"file": file})

        shown = [
            found
            for each in sorted(stands, key=lambda stand: stand.path)
            if (found := filed(each)) is not None
        ]
        return SincePlace(worktree=worktree, branch=branch, files=shown)

    def reviewed(
        self,
        conversation: Conversation,
        branch: str | None,
        viewed: list[ViewedFile],
        seen: str | None,
        *,
        decline: bool = False,
    ) -> SinceReviewed | Refused:
        """Mark each file of `viewed` reviewed at the version shown on the place of `branch`, the conversation's first where it names none, in memory, as stands in for the judge's marks, approving the flag on each still standing at it on the inbox, or, `decline`, declining the landing waiting on it on what the host keeps of it (`Waits`), as the host does (`lup_dev.policy.since`), with the drawer after where it stood at `seen`, the version the page shows. A landing waiting on a file answered ends its wait a moment after (`lands`)."""
        standing = self.since(conversation, None)
        place = next(
            (
                each
                for each in standing.places
                if branch is None or each.branch == branch
            ),
            None,
        )
        if place is None or place.branch is None:
            return Refused(error="the demo's conversation has no branch to mark on")
        versions = {each.path: each.version for each in place.files}
        flags = {each.path: each.flags for each in place.files}
        held = [each.path for each in place.files if each.held is not None]
        moved = [
            each.path for each in viewed if versions.get(each.path) != each.version
        ]
        approved = (
            []
            if decline
            else [
                number
                for each in viewed
                if each.path not in moved
                for number in flags.get(each.path, [])
            ]
        )
        for number in approved:
            self.host.delivery.flag_approved(number)
        declined = [each.path for each in viewed if decline and each.path in held]
        answered = [
            each.path for each in viewed if each.path in held and each.path not in moved
        ]
        at = self.clock.now()
        waits = self.host.waits
        for wait in [
            found
            for path in declined
            for found in waits.declined(
                conversation.repository, place.branch, path, Declined(at=at)
            )
        ]:
            waits.told(wait)
        if answered:
            asyncio.get_running_loop().call_later(
                self.lands.total_seconds(), self.landed
            )
        before = self.marks.get(place.branch, Marks(branch=place.branch))
        latest = {
            each.path: each
            for each in [
                *before.files,
                *(Mark(path=each.path, version=each.version, at=at) for each in viewed),
            ]
        }
        self.marks = {
            **self.marks,
            place.branch: Marks(branch=place.branch, files=list(latest.values())),
        }
        reviewed = SinceReviewed(
            reviewed=[each.path for each in viewed],
            approved=approved,
            declined=declined,
            moved=moved,
        )
        if seen != standing.version:
            return reviewed
        after = self.since(conversation, None)
        paths = [each.path for each in viewed]
        [now] = [each for each in after.places if each.branch == place.branch]
        return reviewed.model_copy(
            update={
                "version": after.version,
                "files": [each for each in now.files if each.path in paths],
            }
        )

    def ago(self, minutes: float) -> datetime:
        """Return the moment `minutes` before the demo began (`began`): its stand-in items and activities are made at moments before it, kept as a real inbox's are, so a watch's reply differs from the one before only where something changed."""
        if self.began is None:
            self.began = self.clock.now()
        return self.began - timedelta(minutes=minutes)

    def every(self) -> list[Item]:
        """Return every stand-in item the demo begins with: those waiting for the operator, a subagent's question of numbered decisions, a session's note, another's problem, an approval of a host zone, a session's write held for them, another's last words of a turn answering the operator's review, citing it, one citation edited and one naming no passage, the note that review was on, edited since, a friction and how it felt, and two writes that landed flagged, the subagent's new module gathering three; the parser subagent's note they replied to, at the call that sent it; an ended subagent's note whose reply went to their session; the docs session's last note, read, their session ended since; and the voice session's note the operator reviewed, and their review, which the session answers in the last words of a turn (`answer`)."""
        first, second = self.runtimes
        lup = Path("/home/op/lup.git")
        parser = Conversation(repository=lup, runtime=first, session="s1", agent="a02")
        session = Conversation(repository=lup, runtime=first, session="s1")
        survey = session.model_copy(update={"agent": "a04"})
        voice = Conversation(repository=lup, runtime=first, session="s2")
        docs = Conversation(repository=lup, runtime=first, session="s4")
        zoetrope = Conversation(
            repository=Path("/home/op/zoetrope.git"), runtime=second, session="s3"
        )
        question = Question(
            text=(
                "Which parser for the transcript reader? A runtime's records hold "
                "about twenty kinds of line, and only four say anything to you."
            ),
            decisions=[
                Decision(
                    text="Read each record with pydantic, one model per line kind",
                    lean="yes: unknown kinds pass over, and a renamed field fails loudly",
                ),
                Decision(
                    text="Fold every tool call to one line",
                    lean="yes, its name alone; the result stays in the record",
                ),
            ],
        )
        note = Message(
            kind="note",
            text=(
                "I assumed transcripts are UTF-8 throughout. A record that isn't is "
                "read with its bad bytes replaced,\nso a search never fails on one."
            ),
        )
        problem = Message(
            kind="problem",
            text=(
                "The render stalls at frame 412: ffmpeg says `Invalid data found when "
                "processing input`.\nI can't go on until the source clip is replaced."
            ),
        )
        approval = Approval(
            text="Approve the host zone of lup at 4750cf6?",
            summary=(
                " packages/lup-dashboard/page/README.md (new)             |  5 +++++\n"
                " packages/lup-dashboard/page/src/agents.ts               |  3 +++\n"
                " packages/lup-dashboard/page/src/main.tsx                |  4 ++--\n"
                " packages/lup-dashboard/src/lup_dashboard/icon.png (new) | Bin 0 -> 1150 bytes\n"
                " packages/lup-dev/pyproject.toml                         |  1 +\n"
                " packages/lup-dev/src/lup_dev/cli.py                     | 16 +++++++++++-----\n"
                " packages/lup/src/lup/transcripts/views.py (new)         | 25 +++++++++++++++++++++++++\n"
                " 7 files changed, 52 insertions(+), 6 deletions(-)"
            ),
            repository=lup,
            fingerprint="demo",
            typing=True,
        )
        made = [
            (51, question, parser, "dev", 4),
            (52, note, voice, "guidance-voice", 12),
            (53, problem, zoetrope, "main", 2),
        ]
        dev = lup / "tree" / "dev"
        reader = Path("packages/lup/src/lup/transcripts/reader.py")
        clock = Path("packages/lup-dev/src/lup_dev/clock.py")
        settled = [
            Item(
                number=43,
                reason=Message(
                    kind="note",
                    text=(
                        "The docs pass is done: each page says what's built, and "
                        "nothing more. I'm ending here."
                    ),
                ),
                sender=docs,
                recipient=Operator(),
                worktree=lup / "tree" / "docs-pass",
                made=self.ago(200),
                state=Done(at=self.ago(190)),
            ),
            Item(
                number=44,
                reason=Message(
                    kind="note",
                    text=(
                        "The legacy reader caches each record's offsets. I left the "
                        "cache out: the records are read whole anyway."
                    ),
                ),
                sender=survey,
                recipient=Operator(),
                worktree=dev,
                made=self.ago(17.5),
                state=Done(at=self.ago(16.5)),
            ),
            Item(
                number=46,
                reason=Message(kind="note", text="Right: leave it out.", of=44),
                sender=Operator(),
                recipient=session,
                addressed=survey,
                made=self.ago(16.5),
                state=Told(at=self.ago(16), how="call"),
            ),
            Item(
                number=47,
                reason=Message(
                    kind="note",
                    text=(
                        "The first runtime's records first, then the second's: they "
                        "keep subagents differently, so one reader each."
                    ),
                ),
                sender=parser,
                recipient=Operator(),
                worktree=dev,
                call="call-47",
                made=self.ago(26),
                state=Done(at=self.ago(23)),
            ),
            Item(
                number=48,
                reason=Message(
                    kind="note", text="Good: keep the two readers apart.", of=47
                ),
                sender=Operator(),
                recipient=parser,
                made=self.ago(23),
                state=Told(at=self.ago(23), how="call"),
            ),
            # The voice session's note the operator reviewed, which the session edited since, back before them;
            # and their review, which the session's turn's end answers.
            Item(
                number=45,
                reason=Message(kind="note", text=VOICE_EDITED),
                sender=voice,
                recipient=Operator(),
                worktree=lup / "tree" / "guidance-voice",
                made=self.ago(9),
                edits=[Edit(at=self.ago(1), before=VOICE_NOTE)],
            ),
            self.reviewed_voice(voice),
            # The operator's review of the voice session's note, which a reply copies before kept is on.
            Item(
                number=49,
                reason=Review(
                    covers=[52],
                    comments=[
                        Comment(
                            item=52,
                            quote=Quote(
                                text="I assumed transcripts are UTF-8 throughout.",
                                start=0,
                                end=43,
                            ),
                            text="Every one, both runtimes' records?",
                        )
                    ],
                ),
                sender=Operator(),
                recipient=voice,
                made=self.ago(11),
                state=Told(at=self.ago(11), how="call"),
                replies=[
                    Reply(
                        number=2,
                        to=PartId(item=49, part=1),
                        text=(
                            "Every one I read: both runtimes write UTF-8.\n"
                            "A stray byte is replaced, never raised."
                        ),
                        at=self.ago(10),
                    )
                ],
            ),
        ]
        return [
            *settled,
            *(
                Item(
                    number=number,
                    reason=reason,
                    sender=sender,
                    recipient=Operator(),
                    worktree=sender.repository / "tree" / worktree,
                    call=f"call-{number}",
                    made=self.ago(minutes),
                )
                for number, reason, sender, worktree, minutes in made
            ),
            Item(
                number=54,
                reason=approval,
                sender=Operator(),
                recipient=Operator(),
                worktree=dev,
                made=self.ago(1),
            ),
            Item(
                number=55,
                reason=HeldChange(
                    text="Let the change to 3 files land?",
                    summary=(
                        "AGENTS.md: AGENTS.md is the operator's document, asked "
                        "about every time\n"
                        "packages/lup-dashboard/page/package.json: "
                        "packages/lup-dashboard/page/package.json is a protected "
                        "path (package.json)\n"
                        "packages/lup/src/lup/transcripts/records.py: adds "
                        '`# lup: ignore("string-split", why="JSONL is an object a '
                        'line")` to packages/lup/src/lup/transcripts/records.py'
                    ),
                    worktree=dev,
                    key="a1b2c3",
                ),
                sender=session,
                recipient=Operator(),
                worktree=dev,
                call="call-55",
                made=self.ago(0.5),
            ),
            self.answer(voice),
            Item(
                number=63,
                reason=Unresolved(
                    of=56,
                    citations=[
                        each
                        for each in self.answer(voice).citations
                        if each.found is None
                    ],
                ),
                sender=voice,
                recipient=voice,
                worktree=lup / "tree" / "guidance-voice",
                made=self.ago(1.5),
                state=Told(at=self.ago(1.5), how="turn's end"),
            ),
            Item(
                number=57,
                reason=Friction(
                    text=(
                        "`uv run lup-dev check` rebuilt the engine for four minutes "
                        "before the tests ran, printing nothing until then. I was "
                        "running the gate on the reader; a line saying the rebuild, "
                        "and how long it takes, would have kept me from killing it."
                    ),
                    title="the gate rebuilds the engine without a word",
                ),
                sender=parser,
                recipient=Operator(),
                worktree=dev,
                call="call-57",
                made=self.ago(3),
            ),
            Item(
                number=58,
                reason=HowItFelt(
                    text=(
                        "Steady. The brief named every file I needed; the judge "
                        "repeating the file's findings after each edit wore a little."
                    )
                ),
                sender=voice,
                recipient=Operator(),
                worktree=lup / "tree" / "guidance-voice",
                call="call-58",
                made=self.ago(1.4),
            ),
            Item(
                number=59,
                reason=Flagged(
                    text=f"{reader} landed, flagged for the operator's review.",
                    summary=(
                        f"{reader} is a new production file\n"
                        f"{reader} adds the class `Turn`\n"
                        f"{reader} adds the class `Reader`"
                    ),
                    worktree=dev,
                    path=reader,
                    writes=3,
                ),
                sender=parser,
                recipient=Operator(),
                worktree=dev,
                call="call-59",
                made=self.ago(6),
            ),
            Item(
                number=60,
                reason=Flagged(
                    text=f"{clock} landed, flagged for the operator's review.",
                    summary=f"{clock} adds the method `Clock.why`",
                    worktree=dev,
                    path=clock,
                ),
                sender=session,
                recipient=Operator(),
                worktree=dev,
                call="call-60",
                made=self.ago(2.5),
            ),
            *self.fix_clock_flags(),
            Item(
                number=62,
                reason=Message(kind="note", text=MARKDOWN_NOTE),
                sender=session,
                recipient=Operator(),
                worktree=dev,
                call="call-62",
                made=self.ago(0.8),
            ),
            *self.exchanges(session, parser),
            *self.worked(),
        ]

    def exchanges(self, session: Conversation, parser: Conversation) -> list[Item]:
        """Return messages between agents, each in its recipient's inbox, told, and the operator's copy of it, done as it's made, which holds it in its thread (`Message.to`): the lup-impl session asking explore-auth where auth is checked, and their answer, beside which explore-auth's note to the operator, new; and, read since, the parser subagent asking their own subagent grep-tokens to count the kinds of line, and the count."""
        explorer = session.model_copy(update={"agent": "a01"})
        grep = session.model_copy(update={"agent": "a03"})
        dev = session.repository / "tree" / "dev"

        def sent(
            number: int,
            sender: Conversation,
            to: Conversation,
            text: str,
            minutes: float,
            *,
            copy: int,
        ) -> list[Item]:
            return [
                Item(
                    number=number,
                    reason=Message(kind="note", text=text),
                    sender=sender,
                    recipient=to,
                    worktree=dev,
                    made=self.ago(minutes),
                    state=Told(at=self.ago(minutes), how="call"),
                ),
                Item(
                    number=copy,
                    reason=Message(kind="note", text=text, to=to),
                    sender=sender,
                    recipient=Operator(),
                    worktree=dev,
                    made=self.ago(minutes),
                    state=Done(at=self.ago(minutes)),
                ),
            ]

        return [
            *sent(
                73,
                parser,
                grep,
                "Count each kind of line in every record you can find, and say which carry words.",
                20,
                copy=67,
            ),
            *sent(
                74,
                grep,
                parser,
                "Twenty-one kinds. Four carry words: user, assistant, tool_use and tool_result.",
                18,
                copy=70,
            ),
            *sent(
                71,
                session,
                explorer,
                "Find every place auth is checked, and say which run before a session starts.",
                6,
                copy=64,
            ),
            *sent(
                72,
                explorer,
                session,
                "Three places: the hook, the launch and the sweep. Only the hook runs before a session starts; my note to the operator says where each is.",
                2,
                copy=65,
            ),
            Item(
                number=66,
                reason=Message(
                    kind="note",
                    text=(
                        "Auth is checked in three places:\n\n"
                        "- the hook, `lup_dev/hooks.py`, before a session starts;\n"
                        "- the launch, `lup_dev/launch/run.py`, as a room is made;\n"
                        "- the sweep, `lup_dev/cli.py`, every 30 seconds."
                    ),
                ),
                sender=explorer,
                recipient=Operator(),
                worktree=dev,
                made=self.ago(1.8),
            ),
        ]

    def reviewed_voice(self, voice: Conversation) -> Item:
        """Return the operator's review of the voice session's note: a comment on a passage of it, one on it whole, and a message to the session, told to them at a call."""
        return Item(
            number=50,
            reason=Review(
                covers=[45],
                comments=[
                    Comment(
                        item=45,
                        quote=Quote(
                            text=VOICE_PASSAGE,
                            start=len(VOICE_OPENING) + 1,
                            end=len(VOICE_OPENING) + 1 + len(VOICE_PASSAGE),
                        ),
                        text=(
                            "Good. But does it read well where a line speaks of both "
                            "of us at once?"
                        ),
                    ),
                    Comment(item=45, text="And cut the history: say what is."),
                ],
                letters=[
                    Letter(
                        to=voice,
                        text=(
                            "Once that's done, put it on its branch for me to read. "
                            "Keep the examples short."
                        ),
                    )
                ],
            ),
            sender=Operator(),
            recipient=voice,
            made=self.ago(8),
            state=Told(at=self.ago(7.5), how="call"),
        )

    def answer(self, voice: Conversation) -> Item:
        """Return the voice session's turn's last words, answering the operator's review of that note (`reviewed_voice`), the session's citations of the operator's words read as the host reads them (`resolved`): one edited to name the part the session meant, and one that names no passage, shown as written."""
        said = spoken(self.reviewed_voice(voice))
        return Item(
            number=56,
            reason=Message(kind="note", text=VOICE_ANSWER, ending=True, answers=[50]),
            sender=voice,
            recipient=Operator(),
            worktree=Path("/home/op/lup.git/tree/guidance-voice"),
            made=self.ago(1.5),
            citations=resolved(VOICE_ANSWER, said),
            edits=[Edit(at=self.ago(1.2), before=VOICE_SENT)],
        )

    def moments(self) -> dict[int, list[Said | StandIn]]:
        """Return the stand-in moment of each item an agent's call made, by its number, each call with what reading it whole answers."""

        def operator(text: str, minutes: float) -> Said:
            return Said(by="operator", text=text, at=self.ago(minutes))

        def agent(text: str, minutes: float) -> Said:
            return Said(by="agent", text=text, at=self.ago(minutes))

        def called(
            tool: str,
            minutes: float,
            gist: str | None,
            given: JsonValue,
            output: str | None = None,
            *,
            id_: str | None = None,
        ) -> StandIn:
            return stand_in(
                id_ or f"toolu_{tool}_{minutes}",
                tool,
                gist,
                self.ago(minutes),
                given,
                output=output,
            )

        building = (
            "Build the transcript reader, both runtimes. Ask me about the shape "
            "before you build on it."
        )
        records = "/home/op/records/projects/-home-op-lup-git-tree-dev"
        tree = "/home/op/lup.git/tree/dev"
        return {
            51: [
                operator(building, 9),
                agent(
                    "Reading the first runtime's records, to see what each line holds.",
                    8,
                ),
                called(
                    "Bash",
                    8,
                    "Count each kind of line in the session records · python3 - <<'EOF' import collections, glob, json",
                    {
                        "command": (
                            "python3 - <<'EOF'\nimport collections, glob, json\n"
                            "kinds = collections.Counter()\n"
                            f"for path in glob.glob('{records}/*.jsonl'):\n"
                            "    for line in open(path):\n"
                            "        kinds[json.loads(line).get('type')] += 1\n"
                            "print(kinds.most_common())\nEOF"
                        ),
                        "description": "Count each kind of line in the session records",
                    },
                    "[('assistant', 9190), ('attachment', 7643), ('user', 5254), "
                    "('api-request', 3109), ('last-prompt', 1466), ('mode', 1452), "
                    "('permission-mode', 1452), ('ai-title', 1451), "
                    "('custom-title', 802), ('agent-name', 730), ('system', 234), "
                    "('queue-operation', 172), ('file-history-snapshot', 81), "
                    "('cost-state', 21), ('summary', 3), ('mcp-instructions', 2), "
                    "('worktree-state', 2), ('pr-link', 1), ('tag', 1), "
                    "('away-summary', 1)]\n",
                ),
                called(
                    "Bash",
                    7.8,
                    "Show the start of one record · head -c 400 /home/op/records/projects/-home-op-lup-git-tree-dev/0a1f3339.jsonl",
                    {
                        "command": f"head -c 400 {records}/0a1f3339.jsonl",
                        "description": "Show the start of one record",
                    },
                    '{"type":"permission-mode","permissionMode":"default",'
                    '"sessionId":"0a1f3339"}\n{"type":"user","message":{"role":'
                    '"user","content":"Look into reading transcripts."},"origin":'
                    '{"kind":"human"},"promptSource":"typed","cwd":'
                    f'"{tree}","timestamp":"2026-10-17T12:00:00.000Z"}}',
                ),
                called(
                    "Read",
                    7.5,
                    "lup_dev/host/records.py:40,51",
                    {
                        "file_path": f"{tree}/packages/lup-dev/src/lup_dev/host/records.py",
                        "offset": 40,
                        "limit": 12,
                    },
                    "40\tclass Said(Model):\n"
                    '41\t    """Something said in a session: the operator\'s words, or the agent\'s."""\n'
                    "42\t\n"
                    '43\t    kind: Literal["said"] = "said"\n'
                    '44\t    by: Literal["operator", "agent"]\n'
                    "45\t    text: str\n"
                    "46\t    at: datetime | None = None\n",
                ),
                agent(
                    "Twenty kinds of line; four carry what was said. Two ways to read "
                    "them: a model per kind, or a dict walked by hand.",
                    5,
                ),
                called(
                    "mcp__lup__ask",
                    4,
                    'question=Which way should the reader read each kind of line? · decisions=[{"text": "A model per kind", "lean": "yes"}, {"text": "A dict walked by hand", "lean": "no"}]',
                    {
                        "question": "Which way should the reader read each kind of line?",
                        "decisions": [
                            {"text": "A model per kind", "lean": "yes"},
                            {"text": "A dict walked by hand", "lean": "no"},
                        ],
                    },
                    id_="call-51",
                ),
                agent("While that waits, I'll read the second runtime's.", 3.9),
                called(
                    "Grep",
                    3.8,
                    "pattern=rollout- · path=/home/op/records/sessions",
                    {"pattern": "rollout-", "path": "/home/op/records/sessions"},
                ),
            ],
            52: [
                operator("Keep going on the guidance rewrite.", 30),
                agent("Checking how the records are encoded before I search them.", 14),
                called(
                    "Bash",
                    13,
                    "file /home/op/records/projects/-home-op-lup-git-tree-dev/*.jsonl | sort | uniq -c",
                    {"command": f"file {records}/*.jsonl | sort | uniq -c"},
                    "  45 JSON text data\n",
                ),
                called(
                    "mcp__lup__note",
                    12,
                    "remark=The records are UTF-8 JSON lines; no other encoding found.",
                    {
                        "remark": "The records are UTF-8 JSON lines; no other encoding found."
                    },
                    "Noted for the operator: @52.",
                    id_="call-52",
                ),
                agent("Carrying on with the search command.", 11.9),
            ],
            53: [
                operator("Render the second scene at full size.", 20),
                agent("Rendering frames 1 to 600.", 10),
                called(
                    "exec_command",
                    9,
                    "uv run zoetrope render scenes/second.toml --frames 1-600",
                    {
                        "cmd": "uv run zoetrope render scenes/second.toml --frames 1-600",
                        "workdir": "/home/op/zoetrope.git/tree/main",
                        "yield_time_ms": 600000,
                    },
                    "Process exited with code 1\nOutput:\nframe 412/600\n"
                    "ffmpeg: clips/harbour.mov: Invalid data found when processing input\n",
                ),
                called(
                    "exec_command",
                    3,
                    "ffprobe -v error -show_streams clips/harbour.mov",
                    {
                        "cmd": "ffprobe -v error -show_streams clips/harbour.mov",
                        "workdir": "/home/op/zoetrope.git/tree/main",
                    },
                    "Process exited with code 1\nOutput:\n"
                    "clips/harbour.mov: moov atom not found\n",
                ),
                agent("ffmpeg stops at frame 412, on the source clip.", 2.2),
                called(
                    "blocked",
                    2,
                    "why=The source clip clips/harbour.mov is truncated: its moov atom is missing.",
                    {
                        "why": "The source clip clips/harbour.mov is truncated: its moov atom is missing."
                    },
                    id_="call-53",
                ),
            ],
            55: [
                operator(
                    "Highlight the code in the review with CodeMirror's own "
                    "language packages.",
                    6,
                ),
                agent("Adding the language packages to the page.", 1),
                called(
                    "Bash",
                    0.8,
                    "Add CodeMirror's language packages · npm install --save-exact @codemirror/lang-python @codemirror/lang-javascript",
                    {
                        "command": "npm install --save-exact @codemirror/lang-python @codemirror/lang-javascript",
                        "description": "Add CodeMirror's language packages",
                    },
                    "added 4 packages in 2s\n",
                ),
                called(
                    "Edit",
                    0.5,
                    "page/src/code.ts -1 +2",
                    {
                        "file_path": f"{tree}/packages/lup-dashboard/page/src/code.ts",
                        "old_string": 'import { tags } from "@lezer/highlight";',
                        "new_string": 'import { python } from "@codemirror/lang-python";\nimport { tags } from "@lezer/highlight";',
                        "replace_all": False,
                    },
                    id_="call-55",
                ),
            ],
            57: [
                agent("Running the gate on the reader.", 7.5),
                called(
                    "Bash",
                    7.4,
                    "Run the gate · uv run lup-dev check",
                    {"command": "uv run lup-dev check", "description": "Run the gate"},
                    "passed   rules\npassed   ruff\npassed   pyright\n"
                    "passed   pytest (1,214 tests, 41.2s)\n\nThe gate passed.\n",
                ),
                called(
                    "mcp__lup__friction",
                    3,
                    "got_in_the_way=the gate's 41 seconds · trying=to iterate on the reader · would_change=run only the tests the change touches",
                    {
                        "got_in_the_way": "the gate's 41 seconds",
                        "trying": "to iterate on the reader",
                        "would_change": "run only the tests the change touches",
                    },
                    id_="call-57",
                ),
                agent("The tests pass; on to the second runtime's records.", 2.9),
            ],
            58: [
                operator("Keep going on the guidance rewrite.", 30),
                agent("The voice section is done, and the gate passes.", 1.6),
                called(
                    "mcp__lup__how_it_felt",
                    1.4,
                    "text=The rewrite went smoothly once the voice was settled.",
                    {"text": "The rewrite went smoothly once the voice was settled."},
                    id_="call-58",
                ),
            ],
            59: [
                operator(building, 9),
                agent(
                    "A module of its own for the reader, with a model per turn.", 6.5
                ),
                called(
                    "Write",
                    6,
                    "lup/transcripts/reader.py · 5 lines",
                    {
                        "file_path": f"{tree}/packages/lup/src/lup/transcripts/reader.py",
                        "content": '"""Reading a session\'s record."""\n\nclass Turn(BaseModel):\n    said: str\n',
                    },
                    id_="call-59",
                ),
                called(
                    "Edit",
                    5.5,
                    "lup/transcripts/reader.py -1 +1",
                    {
                        "file_path": f"{tree}/packages/lup/src/lup/transcripts/reader.py",
                        "old_string": "class Turn(BaseModel):",
                        "new_string": "class Turn(Model):",
                    },
                ),
                called(
                    "Edit",
                    5,
                    "lup/transcripts/reader.py -1 +2",
                    {
                        "file_path": f"{tree}/packages/lup/src/lup/transcripts/reader.py",
                        "old_string": "    said: str",
                        "new_string": "    said: str\n    at: datetime | None = None",
                    },
                ),
            ],
            60: [
                operator("Let the tests say why they wait.", 4),
                agent("The clock says why its last wait waited.", 2.7),
                called(
                    "Edit",
                    2.5,
                    "src/lup_dev/clock.py -1 +2",
                    {
                        "file_path": f"{tree}/packages/lup-dev/src/lup_dev/clock.py",
                        "old_string": "    def sleep(self, seconds: float) -> None:",
                        "new_string": "    def sleep(self, seconds: float) -> None:\n        self.waited = seconds",
                    },
                    id_="call-60",
                ),
            ],
            62: [
                operator(building, 9),
                agent(
                    "Counting what each kind of line holds, before the reader is shaped.",
                    1.2,
                ),
                called(
                    "Bash",
                    1.1,
                    "Count the parts of each kind of line · jq -r '.type' /home/op/records/projects/-home-op-lup-git-tree-dev/*.jsonl | sort | uniq -c | sort -rn | head",
                    {
                        "command": f"jq -r '.type' {records}/*.jsonl | sort | uniq -c | sort -rn | head",
                        "description": "Count the parts of each kind of line",
                    },
                    "   9190 assistant\n   7643 attachment\n   5254 user\n",
                ),
                called(
                    "mcp__lup__note",
                    0.8,
                    "remark=Four kinds of line carry what was said.",
                    {"remark": "Four kinds of line carry what was said."},
                    "Noted for the operator: @62.",
                    id_="call-62",
                ),
            ],
        }

    def recorded(self, session: str, agent: str | None) -> list[Said | StandIn]:
        """Return a stand-in conversation, each call with what reading it whole answers, in the order it came: what it says of itself (`spoken`), and each call that made an item of theirs, whose moment the host reads from it (`lup_dev.inbox.context`), with what led to it where `moments` says (`called` else)."""
        said = self.spoken(session, agent)
        held = [each.step.id for each in said if isinstance(each, StandIn)]
        moments = self.moments()
        return in_order(
            [
                *said,
                *(
                    step
                    for item in self.host.inbox.items.values()
                    if isinstance(item.sender, Conversation)
                    and item.sender.session == session
                    and item.sender.agent == agent
                    and item.call is not None
                    and item.call not in held
                    for step in moments.get(item.number) or self.called(item)
                ),
            ],
            self.ago(0),
        )

    def called(self, item: Item) -> list[Said | StandIn]:
        """Return the steps of the call that made `item`, where no moment says more: its own tool's, given what it says; a flagged write's between the agent's words around it."""
        call, said = item.call or "", opening(item)
        match item.reason:
            case Flagged(path=path):
                return [
                    Said(
                        by="agent",
                        text="Writing the module, a function a step, with a docstring each.",
                        at=item.made - timedelta(minutes=2),
                    ),
                    stand_in(
                        call,
                        "Write",
                        path.name,
                        item.made,
                        {"file_path": str(path)},
                        output=f"The file {path} has been updated successfully.",
                    ),
                    Said(
                        by="agent",
                        text="On to its tests.",
                        at=item.made + timedelta(seconds=6),
                    ),
                ]
            case Question():
                return [
                    stand_in(call, "mcp__lup__ask", said, item.made, {"question": said})
                ]
            case Friction():
                tool = "mcp__lup__friction"
            case _:
                tool = "mcp__lup__note"
        return [
            stand_in(
                call,
                tool,
                said,
                item.made,
                {"text": said},
                output=f"Noted for the operator: {cited(item.number)}.",
            )
        ]

    def briefed(self) -> list[Said | StandIn]:
        """Return how a worker's conversation begins: their brief, and the reading it asks for."""
        begun = self.ago(400)
        return [
            Said(
                by="operator",
                text=(
                    "Build the piece your brief names, on a branch of your own; ask "
                    "before you build on a shape."
                ),
                at=begun,
            ),
            Said(
                by="agent",
                text="Reading the files the brief names first.",
                at=begun + timedelta(minutes=1),
            ),
            stand_in(
                "toolu_b1",
                "Read",
                "reader.py",
                begun + timedelta(minutes=2),
                {"file_path": "packages/lup/src/lup/transcripts/reader.py"},
                output='1\t"""Reading a runtime\'s records of its sessions, a line at a time."""\n',
            ),
            stand_in(
                "toolu_b2",
                "Grep",
                "class Reader",
                begun + timedelta(minutes=3),
                {"pattern": "class Reader", "path": "packages"},
                output="packages/lup/src/lup/transcripts/reader.py:16:class Reader(BaseModel):\n",
            ),
        ]

    def spoken(self, session: str, agent: str | None) -> list[Said | StandIn]:
        """Return what a stand-in conversation says of itself, beside the calls that made its items (`recorded`): for the parser subagent, what led to the call that sent @47, then what they read since the demo began; for the first worker, a day's work (`long_conversation`), and any other, their brief (`briefed`); for the second runtime's session and their subagent, a render that broke; for any other, a short exchange."""
        tree = "/home/op/lup.git/tree/dev"
        workers = [worker_agent(n) for n in range(1, self.workers + 1)]
        if session == "s1" and agent in workers and self.size > 0:
            return (
                self.long_conversation() if agent == worker_agent(1) else self.briefed()
            )
        if (session, agent) == ("s1", "a02"):
            return [
                Said(
                    by="operator",
                    text="Look into reading transcripts.",
                    at=self.ago(30),
                ),
                Said(
                    by="agent",
                    text=(
                        "Starting with the record's layout. Each session is a JSONL "
                        "file;\nsubagents get their own beside it."
                    ),
                    at=self.ago(29),
                ),
                stand_in(
                    "toolu_p1",
                    "Bash",
                    "List the session records · ls /home/op/records/projects/-home-op-lup-git-tree-dev | head -4",
                    self.ago(28),
                    {
                        "command": "ls /home/op/records/projects/-home-op-lup-git-tree-dev | head -4",
                        "description": "List the session records",
                    },
                    output="0a1f3339-dd0c-456f-86ff-9a95af8bb48f\n"
                    "0a1f3339-dd0c-456f-86ff-9a95af8bb48f.jsonl\n"
                    "1a39941b-776b-425d-8bd8-be8542a9b28d\n"
                    "1a39941b-776b-425d-8bd8-be8542a9b28d.jsonl\n",
                ),
                stand_in(
                    "toolu_p2",
                    "Read",
                    "tree/dev/docs/field-notes.md:613,616",
                    self.ago(27),
                    {
                        "file_path": f"{tree}/docs/field-notes.md",
                        "offset": 613,
                        "limit": 4,
                    },
                    output="613\t### A session's record (measured 2026-10-18)\n"
                    "614\t\n"
                    "615\tWhat `lup-dev transcripts` reads of "
                    "`projects/<folder>/<session>.jsonl`.\n",
                ),
                stand_in(
                    "call-47",
                    "mcp__lup__note",
                    "remark=Each session's record is a JSONL file; a subagent's is beside it.",
                    self.ago(26),
                    {
                        "remark": "Each session's record is a JSONL file; a subagent's is beside it."
                    },
                    output="Noted for the operator: @47.",
                ),
                Said(
                    by="agent",
                    text="Reading the first runtime's records.",
                    at=self.ago(25.5),
                ),
                stand_in(
                    "toolu_p3",
                    "Read",
                    "src/lup_dev/host/records.py",
                    self.ago(24),
                    {
                        "file_path": f"{tree}/packages/lup-dev/src/lup_dev/host/records.py"
                    },
                    output='1\t"""Where a runtime keeps each session\'s record on this machine."""\n'
                    "2\t\n3\tfrom abc import ABC, abstractmethod\n",
                ),
                stand_in(
                    "toolu_p4",
                    "Grep",
                    "pattern=class Transcript · path=/home/op/lup.git/tree/dev/packages",
                    self.ago(22),
                    {"pattern": "class Transcript", "path": f"{tree}/packages"},
                    output="packages/lup-dev/src/lup_dev/host/records.py:118:"
                    "class Transcript(Model):\n",
                ),
                *self.growing(),
            ]
        if session == "s3":
            return self.rendering()
        return [
            Said(
                by="operator",
                text="Carry on with what you were doing.",
                at=self.ago(20),
            ),
            Said(by="agent", text="On it: reading the code first.", at=self.ago(19)),
            stand_in(
                "toolu_d1",
                "Grep",
                "pattern=def laid · output_mode=content · path=/home/op/lup.git/tree/dev/packages",
                self.ago(18),
                {
                    "pattern": "def laid",
                    "path": f"{tree}/packages",
                    "output_mode": "content",
                },
                output="packages/lup-dashboard/page/src/review.ts:871:export function laid(\n",
            ),
            stand_in(
                "toolu_d2",
                "Read",
                "page/src/review.ts:871,873",
                self.ago(17),
                {
                    "file_path": f"{tree}/packages/lup-dashboard/page/src/review.ts",
                    "offset": 871,
                    "limit": 3,
                },
                output="871\texport function laid(\n872\t    items: Item[],\n"
                "873\t    agents: Conversation[],\n",
            ),
            stand_in(
                "toolu_d3",
                "Read",
                "page/src/conversation.ts",
                self.ago(17),
                {
                    "file_path": f"{tree}/packages/lup-dashboard/page/src/conversation.ts"
                },
                output="1\t// One conversation laid out as one text to read and move through\n",
            ),
            Said(by="agent", text="Found it. Writing the fix next.", at=self.ago(15)),
        ]

    def rendering(self) -> list[Said | StandIn]:
        """Return the second runtime's session's conversation: a render asked for, the scene's settings read and patched, and the render breaking on its source clip, its calls as that runtime makes them."""
        main = "/home/op/zoetrope.git/tree/main"
        patch = (
            "*** Begin Patch\n*** Update File: scenes/second.toml\n@@\n"
            "-size = [960, 540]\n+size = [1920, 1080]\n*** End Patch\n"
        )
        return [
            Said(
                by="operator",
                text="Render the second scene at full size.",
                at=self.ago(20),
            ),
            Said(
                by="agent", text="Checking the scene's settings first.", at=self.ago(19)
            ),
            stand_in(
                "call_r1",
                "exec_command",
                "sed -n '1,20p' scenes/second.toml",
                self.ago(18),
                {"cmd": "sed -n '1,20p' scenes/second.toml", "workdir": main},
                output='Process exited with code 0\nOutput:\n[scene]\nname = "harbour"\n'
                "size = [960, 540]\nframes = 600\n",
            ),
            stand_in(
                "call_r2",
                "apply_patch",
                "scenes/second.toml",
                self.ago(16),
                patch,
                output="Success. Updated the following files:\nM scenes/second.toml\n",
            ),
            *self.moments()[53][1:],
        ]

    def growing(self) -> list[Said | StandIn]:
        """Return the steps the parser subagent took since the demo began: a call, then what they found, in turn."""
        rollouts = "/home/op/records/sessions/2026/10/17"
        return [
            stand_in(
                f"toolu_g{step}",
                "Read",
                f"rollouts/rollout-{step // 2 + 1}.jsonl",
                self.ago(0),
                {"file_path": f"{rollouts}/rollout-{step // 2 + 1}.jsonl"},
                output='1\t{"type":"session_meta","payload":{"id":"th-1","cwd":"/w"}}\n'
                '2\t{"type":"event_msg","payload":{"type":"user_message","message":"go"}}\n',
            )
            if step % 2 == 0
            else Said(
                by="agent",
                text=f"Read the second runtime's record {step // 2 + 1}: four kinds again.",
                at=self.ago(0),
            )
            for step in range(self.grown)
        ]

    def hook(self) -> None:
        """Let a stand-in hook call come: what one worker does changes (`worker_doing`), each watch answers again, and the next comes after the interval `hooks` gives."""
        self.hooked += 1
        if self.size > 0:
            n = self.hooked % self.workers + 1
            self.doing(worker_agent(n), self.worker_doing(n), CallStarted.named())
        else:
            self.host.changes.changed()
        self.hooking = asyncio.get_running_loop().call_later(60 / self.hooks, self.hook)

    def worker_doing(self, n: int) -> Activity:
        """Return what worker `n` does as the stand-in hook calls have it (`hook`): calling a tool, or between calls."""
        tools = ["Read", "Edit", "Bash"]
        return (
            Activity(
                state="calling",
                since=self.ago(0.3),
                tool=tools[(self.hooked + n) % len(tools)],
            )
            if (self.hooked + n) % 2 == 0
            else Activity(state="idle", since=self.ago(0.1))
        )

    def worker(self, n: int) -> Conversation:
        """Return worker `n`'s conversation: a subagent of the lup-impl session."""
        first, _ = self.runtimes
        return Conversation(
            repository=Path("/home/op/lup.git"),
            runtime=first,
            session="s1",
            agent=worker_agent(n),
        )

    def worked(self) -> list[Item]:
        """Return the busy day's items (`size`): each worker's note, written in Markdown, and their friction, then the flagged writes, each worker's in turn, each of a module of hundreds of lines (`worked_files`); numbered from `first_worked`, made over the last hours, oldest first, each by a call, so each has a moment (`worked_context`)."""
        if self.size == 0:
            return []

        def item(
            number: int, n: int, reason: Message | Friction | Flagged, minutes: float
        ) -> Item:
            return Item(
                number=number,
                reason=reason,
                sender=self.worker(n),
                recipient=Operator(),
                worktree=worker_worktree(n),
                call=f"call-{number}",
                made=self.ago(minutes),
            )

        def said(n: int) -> list[Item]:
            number = self.first_worked + 2 * (n - 1)
            note = Message(
                kind="note",
                text=f"Worker {n}'s reading of the records.\n\n{MARKDOWN_NOTE}",
            )
            friction = Friction(
                text=(
                    f"`uv run lup-dev check` rebuilt the engine before worker {n}'s "
                    "tests ran, printing nothing until then; a line saying the rebuild "
                    "would have kept me from killing it."
                ),
                title="the gate's rebuild prints nothing",
            )
            return [
                item(number, n, note, 400 - n),
                item(number + 1, n, friction, 390 - n),
            ]

        def landed(i: int) -> Item:
            number = self.first_worked + 2 * self.workers + i
            n = i % self.workers + 1
            path = worked_path(n, i)
            summary = (
                f"{path} adds the function `step_{self.functions - 1}`"
                if i % 2 == 0
                else f"{path} is a new production file"
            )
            flagged = Flagged(
                text=f"{path} landed, flagged for the operator's review.",
                summary=summary,
                worktree=worker_worktree(n),
                path=path,
                writes=1 + i % 3,
            )
            return item(number, n, flagged, 360 - 360 * i / self.size)

        return [
            *(each for n in range(1, self.workers + 1) for each in said(n)),
            *(landed(i) for i in range(self.size)),
        ]

    def worked_files(self, number: int) -> Files | Refused:
        """Return the file a worker's flagged write (`worked`) landed, whole: a module of `functions` functions, one added where an earlier write made it, flagged for the public API it adds, with a finding told; else new, flagged as a new file. Refused for a note or a friction, which change no file."""
        i = number - self.first_worked - 2 * self.workers
        if i < 0 or i >= self.size:
            return Refused(error=f"{cited(number)} changes no file")
        n = i % self.workers + 1
        after = text(module(n, i, self.functions))
        last = self.functions - 1
        added = f"def step_{last}(path: Path, count: int = {last}) -> list[str]:"
        stripped = line(after, '            if line.strip() == "":')
        grown = Reading(
            role="production",
            asks=[
                Ask(
                    name="public-api",
                    taken="flagged",
                    line=line(after, added),
                    api=ApiChanged(kind="function-added", name=f"step_{last}"),
                )
            ],
            findings=[
                Found(
                    rule="string-strip",
                    message=(
                        "`.strip` decides whether a line is blank by hand. Reading "
                        "structured text by hand matches the inputs it was tried on, "
                        "and fails quietly on the rest."
                    ),
                    start=stripped,
                    end=stripped,
                    taken="told",
                )
            ],
        )
        created = Reading(
            role="production", asks=[Ask(name="new-file", taken="flagged")]
        )
        return Files(
            number=number,
            files=[
                ChangedFile(
                    path=worked_path(n, i),
                    before=text(module(n, i, last)) if i % 2 == 0 else None,
                    after=after,
                    reading=grown if i % 2 == 0 else created,
                )
            ],
        )

    def long_conversation(self, length: int = 300) -> list[Said | StandIn]:
        """Return the first worker's conversation, `length` steps after their brief, as a day's work reads: what they're on, then a run of calls reading a module, changing a function, running its tests and reading them, in turn. A subagent never has the operator's typed words after their brief, so their whole run is one exchange, their drawer keeping only the agent's last words open (`EARLIER_KIND.keeps_open`)."""
        tree = worker_worktree(1)

        def step(at: int) -> Said | StandIn:
            k = at // 5 + 1
            module = f"packages/lup/src/lup/worker1/step_{k}.py"
            tests = f"packages/lup/tests/test_step_{k}.py"
            when = self.ago(400 - at)
            match at % 5:
                case 0:
                    return Said(
                        by="agent",
                        text=f"Step {k}: read the module, change one function, run its tests.",
                        at=when,
                    )
                case 1:
                    return stand_in(
                        f"toolu_w{at}",
                        "Read",
                        f"lup/worker1/step_{k}.py",
                        when,
                        {"file_path": str(tree / module)},
                        output=function(k),
                    )
                case 2:
                    return stand_in(
                        f"toolu_w{at}",
                        "Edit",
                        f"lup/worker1/step_{k}.py -1 +1",
                        when,
                        {
                            "file_path": str(tree / module),
                            "old_string": f"    count: int = {k}",
                            "new_string": f"    count: int = {k + 1}",
                            "replace_all": False,
                        },
                        output=f"The file {tree / module} has been updated successfully.",
                    )
                case 3:
                    return stand_in(
                        f"toolu_w{at}",
                        "Bash",
                        f"Run step {k}'s tests · uv run pytest {tests} -q",
                        when,
                        {
                            "command": f"uv run pytest {tests} -q",
                            "description": f"Run step {k}'s tests",
                        },
                        output="..\n2 passed in 0.04s\n",
                    )
                case _:
                    return stand_in(
                        f"toolu_w{at}",
                        "Read",
                        f"packages/lup/tests/test_step_{k}.py:1,20",
                        when,
                        {"file_path": str(tree / tests), "limit": 20},
                        output=f"1\tfrom lup.worker1.step_{k} import step_{k}\n",
                    )

        return [
            Said(
                by="operator",
                text=(
                    "Build the piece your brief names, on a branch of your own; ask "
                    "before you build on a shape."
                ),
                at=self.ago(400),
            ),
            *(step(at) for at in range(length)),
        ]


def worker_agent(n: int) -> str:
    """Return the runtime's id of worker `n`'s subagent."""
    return f"w{n:02}"


def worker_worktree(n: int) -> Path:
    """Return worker `n`'s worktree: one of their own, beside the demo's."""
    return Path("/home/op/lup.git/tree") / f"worker-{n}"


def worked_path(n: int, i: int) -> Path:
    """Return the module worker `n`'s write `i` landed, from their worktree's root."""
    return Path("packages/lup/src/lup") / f"worker{n}" / f"module_{i}.py"


def module(n: int, i: int, functions: int) -> str:
    """Return a stand-in Python module, worker `n`'s write `i`, of `functions` functions: hundreds of lines, each function's body folding and its lines highlighted as the review shows them."""
    head = (
        f'"""Worker {n}\'s module {i}: stand-in code, a busy day\'s flagged write."""\n'
        "\n"
        "from pathlib import Path\n"
    )
    return "".join([head, *(function(at) for at in range(functions))])


def function(at: int, returned: str = "found") -> str:
    """Return one stand-in function, `step_<at>`, with a docstring and a body of a few lines ending in returning `returned`, so bodies fold and runs of lines sit inside them."""
    return (
        "\n\n"
        f"def step_{at}(path: Path, count: int = {at}) -> list[str]:\n"
        '    """Return the lines of `path` read `count` times, each numbered."""\n'
        "    found: list[str] = []\n"
        "    for turn in range(count):\n"
        "        for number, line in enumerate(path.read_text().splitlines()):\n"
        '            if line.strip() == "":\n'
        "                continue\n"
        '            found.append(f"{turn}:{number}:{line}")\n'
        f"    return {returned}\n"
    )


CLI_HEAD = '''"""lup-dev's command line: launches, the host service, the inbox and trust."""

import asyncio
import sys
from pathlib import Path
from typing import Annotated

import typer

from lup_dev.host.client import Detached, HostClient
from lup_dev.inbox.delivery import Delivery
from lup_dev.launch.trust import machine_trust
from lup_dev.settings import LupDevSettings

app = typer.Typer(no_args_is_help=True)
inbox = typer.Typer(no_args_is_help=True)
app.add_typer(inbox, name="inbox")


def answering() -> HostClient:
    """Return the host service's client, the service started where none runs."""
    layout = Layout.of(LupDevSettings())
    return HostClient(layout=layout.host, clock=SystemClock(), starter=Detached())


@inbox.command("show")
def inbox_show(
    number: Annotated[int, typer.Argument(help="The item's number.")],
    *,
    diff: Annotated[bool, typer.Option(help="An approval's whole diff.")] = False,
'''
CLI_SHOW_BEFORE = ''') -> None:
    """Show one item whole."""
    client = answering()
    item = client.ask(ShowItem(number=number), Shown).item
    typer.echo(shown(item))
    if diff:
        typer.echo(client.ask(ShowDiff(number=number), Whole).text)
'''
CLI_SHOW_AFTER = '''    files: Annotated[bool, typer.Option(help="Each file it changes.")] = False,
) -> None:
    """Show one item whole; with `--diff` its whole diff, with `--files` each file."""
    client = answering()
    item = client.ask(ShowItem(number=number), Shown).item
    typer.echo(shown(item))
    if diff:
        typer.echo(client.ask(ShowDiff(number=number), Whole).text)
    if files:
        for each in client.ask(ShowFiles(number=number), Files).files:
            typer.echo(f"{each.path}: {changed(each)}")
'''
CLI_MIDDLE = '''

@inbox.command("done")
def inbox_done(
    number: Annotated[int, typer.Argument(help="The message's number.")],
) -> None:
    """Take a message you've read off your list."""
    answering().ask(FinishItem(number=number), Shown)
    typer.echo(f"Item {number} is done.")


@inbox.command("send")
def inbox_send(
    to: Annotated[str, typer.Argument(help="The launch whose session it's for.")],
    text: Annotated[str, typer.Argument(help="What you say.")],
) -> None:
    """Send a message to the session a launch runs."""
    answering().ask(SendItem(launch=to, text=text), Shown)
    typer.echo(f"Sent to {to}.")

'''
CLI_PUSH_BEFORE = '''
async def proposed_after(launch: Register, refs: list[str]) -> None:
    """Put the approval of the zone at the integration branch's tip in the inbox."""
    running = approved_branches(LAYOUT, launch.repository).running
    if f"refs/heads/{running}" not in refs:
        return
    root = Git.pinned(launch.repository).main_worktree()
    number = await asyncio.to_thread(machine_trust(root, []).proposed)
'''
CLI_PUSH_AFTER = '''
async def proposed_after(
    delivery: Delivery, launch: Register, refs: list[str]
) -> None:
    """Put the approval of the zone at the integration branch's tip in the inbox, naming the session that pushed."""
    running = approved_branches(LAYOUT, launch.repository).running
    if f"refs/heads/{running}" not in refs:
        return
    root = Git.pinned(launch.repository).main_worktree()
    pushed_by = delivery.running(launch.launch)
    branch = refs[0].split("/")[-1]
    number = await asyncio.to_thread(machine_trust(root, []).proposed, pushed_by)
'''
CLI_TAIL = '''    if number is not None:
        typer.echo(f"{launch.launch}: approval item {number} is in the inbox")


def main() -> None:
    """Run lup-dev's command line."""
    app()


if __name__ == "__main__":
    sys.exit(main())
'''

VIEWS = '''"""How a transcript's steps are said in a line each."""

from itertools import groupby

from lup.transcripts.records import Called, Entry, Said


def counted(tool: str, times: int) -> str:
    """Say a tool once, with how many times in a row it was called."""
    return tool if times == 1 else f"{tool} x{times}"


def folded(tools: list[str]) -> str:
    """Say a run of tool calls in a line: `· called Bash x2, Read`."""
    named = [counted(tool, len(list(run))) for tool, run in groupby(tools)]
    return f"· called {', '.join(named)}"


def said(entry: Entry) -> str:
    """Say one step: who said it and their words, or the tool called."""
    match entry:
        case Said(by=by, text=text):
            return f"{'you' if by == 'operator' else 'agent'}: {text}"
        case Called(tool=tool):
            return folded([tool])
'''

AGENTS_HEAD = """import type { components } from "./generated/api";

export type Talker = components["schemas"]["Talker"];

/** Say how long ago `then` was, from `now`, in the largest whole unit. */
export function since(then: Date, now: Date): string {
    const seconds = Math.max(0, Math.round((now.getTime() - then.getTime()) / 1000));
"""
AGENTS_BEFORE = """    if (seconds < 60) {
        return `${seconds}s`;
    }
"""
AGENTS_AFTER = """    if (seconds < 5) {
        return "just now";
    }
    if (seconds < 60) {
        return `${seconds}s`;
    }
"""
AGENTS_TAIL = """    const minutes = Math.round(seconds / 60);
    if (minutes < 60) {
        return `${minutes}m`;
    }
    return `${Math.round(minutes / 60)}h`;
}
"""

PYPROJECT_HEAD = """[project]
name = "lup-dev"
description = "lup's environment: the judge, the host service and its tools."
requires-python = ">=3.14"
dependencies = [
    "filelock>=3.20",
    "lup",
"""
PYPROJECT_ADDED = """    "pygments>=2.19",
"""
PYPROJECT_TAIL = """    "rich>=14.1",
    "typer>=0.20",
]

[project.scripts]
lup-dev = "lup_dev.cli:main"

[build-system]
requires = ["uv_build>=0.9"]
build-backend = "uv_build"
"""

AGENTS_MD_HEAD = """# Working on lup

lup is the environment agents' sessions work in.

## How work goes

1. **Decisions first, in the conversation.** Before building a piece, put its
   decisions to the operator, numbered, each with your lean.
2. **One concern per branch, landed on `dev` by the session that started the work.**
"""
AGENTS_MD_BEFORE = """3. **Write with your file tools.** The judge runs before an Edit or Write lands.
"""
AGENTS_MD_AFTER = """3. **Write with your file tools.** The judge runs before an Edit or Write lands,
   and a protected path's change waits in its hook for the operator's answer.
4. **A held change is answered in the review:** Space `d` or `x`, the comments
   under it going to the agent with the answer.
"""
AGENTS_MD_TAIL = """
## Code

- **Parse structured data with a parser,** never `re`, `split` or slicing.
- **Name the fields.** No tuple carrying several meanings by position.
"""

PACKAGE_HEAD = """{
    "name": "lup-dashboard-page",
    "private": true,
    "type": "module",
    "dependencies": {
        "@codemirror/commands": "6.11.1",
"""
PACKAGE_ADDED = """        "@codemirror/lang-json": "6.0.2",
        "@codemirror/lang-markdown": "6.5.2",
        "@codemirror/lang-python": "6.2.1",
"""
PACKAGE_TAIL = """        "@codemirror/language": "6.13.1",
        "@codemirror/state": "6.7.6",
        "@codemirror/view": "6.43.14",
        "react": "19.3.1"
    }
}
"""


README = """# The dashboard's page

Built by `packages/lup-dashboard/build.py` into the package, which serves it.
Its types are generated from the API's description, so they never drift from
the host's models.
"""

MAIN_HEAD = """import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

"""
MAIN_BEFORE = """createRoot(document.getElementById("root")!).render(
  <StrictMode><App /></StrictMode>,
);
"""
MAIN_AFTER = """createRoot(document.getElementById("root")!).render(
    <StrictMode><App /></StrictMode>,
);
"""

RECORDS_HEAD = '''"""Reading a runtime's records of its sessions."""

import json
from pathlib import Path

from lup.transcripts.views import Entry


def recorded(path: Path) -> bool:
    """Say whether a session's record is there to read."""
    return path.is_file()
'''
RECORDS_ADDED = '''

def turns(path: Path) -> list[Entry]:
    """Read each step of a session's record, an object a line."""
    # lup: ignore("string-split", why="JSONL is an object a line")
    lines = path.read_text().split("\\n")
    return [Entry.model_validate(json.loads(line)) for line in lines if line]
'''


READER = '''"""Reading a runtime's records of its sessions, a line at a time."""

import json
from pathlib import Path

from pydantic import BaseModel


class Turn(BaseModel):
    """One step of a session: who spoke, and what they said."""

    by: str
    text: str


class Reader(BaseModel):
    """Reads one session's record."""

    path: Path

    def turns(self) -> list[Turn]:
        """Read each step of the record, an object a line."""
        lines = self.path.read_text().split("\\n")
        return [Turn.model_validate(json.loads(line)) for line in lines if line]
'''

READER_GROWN = '''
    def kinds(self) -> list[str]:
        """Return each kind of step the record holds, once, in the order they come."""
        return list(dict.fromkeys(turn.by for turn in self.turns()))
'''

TEST_READER = '''"""The reader of a runtime's records."""

from pathlib import Path

from lup.transcripts.reader import Reader


def test_each_line_is_a_turn(tmp_path: Path) -> None:
    record = tmp_path / "record.jsonl"
    record.write_text('{"by": "operator", "text": "Go."}\\n')
    [turn] = Reader(path=record).turns()
    assert (turn.by, turn.text) == ("operator", "Go.")
'''

CLOCK_HEAD = '''"""Time, through one seam, so tests drive it."""

from abc import ABC, abstractmethod
from datetime import datetime


class Clock(ABC):
    """The time, and waiting."""

    @abstractmethod
    def now(self) -> datetime:
        """Return the time."""

    @abstractmethod
'''
CLOCK_BEFORE = '''    def sleep(self, seconds: float) -> None:
        """Wait `seconds`."""
'''
CLOCK_AFTER = '''    def sleep(self, seconds: float) -> None:
        """Wait `seconds`."""

    @abstractmethod
    def why(self) -> str:
        """Say why the last wait waited, which a test's clock reads."""
'''


VOICE_OPENING = (
    "The guidance's voice section says what an agent does, in the second person."
)
"""How the voice session's note the operator reviewed opens, before the passage they commented on."""

VOICE_PASSAGE = "I kept 'you' for the agent throughout"
"""The passage of the voice session's note the operator commented on."""

VOICE_NOTE = f"{VOICE_OPENING} {VOICE_PASSAGE}, and named the operator by their role."
"""The voice session's note as the operator reviewed it."""

VOICE_EDITED = (
    f"{VOICE_OPENING} It says 'you' to the agent alone, and names the operator by "
    "their role."
)
"""The voice session's note as it edited it since, the passage the operator commented on changed."""

VOICE_ANSWER = (
    "It reads well where a line speaks of one of us. Where it speaks of both, "
    "@50.1[does it read well … at once?], I name you by your role and leave "
    '"you" to the agent, so nothing reads two ways.\n\n'
    "The history is out, @50.2[say what is]. The examples are a line each, "
    "@50.3[Keep the examples short], and the section is on its branch, "
    "`guidance-voice`, the gate passing.\n\n"
    "One thing I couldn't place: @50.1[the tone of the examples]."
)
"""The voice session's turn's last words, answering the operator's review of its note."""

VOICE_SENT = (
    "It reads well where a line speaks of one of us. Where it speaks of both, "
    "@50.1[does it read well … at once?], I name you by your role and leave "
    '"you" to the agent, so nothing reads two ways.\n\n'
    "The history is out, @50.1[say what is]. The examples are a line each, "
    "@50.3[Keep the examples short], and the section is on its branch, "
    "`guidance-voice`, the gate passing.\n\n"
    "One thing I couldn't place: @50.1[the tone of the examples]."
)
"""What those words said as the session sent them, before it edited a citation to name the part it meant."""

MARKDOWN_NOTE = """\
Read the first runtime's records whole: what each kind of line holds, and what \
I'd build on it.

| kind | lines | says |
|:-----|------:|:-----|
| `user` | 412 | the operator's words, and each tool's result |
| `assistant` | 398 | the agent's words and its calls |
| `summary` | 3 | a compaction's summary |
| `system` | 17 | nothing to you |

**Only four kinds say anything**; the rest is *bookkeeping*. Next, unless you \
say otherwise:

1. a model per kind, as @51 leans
2. the reader, with a test on each kind
   - the `summary` kind first, which the legacy reader got wrong
3. then the second runtime's records

## Open

Whether a record's `summary` replaces what came before it. The legacy reader \
kept both:

```python
def turns(path: Path) -> list[Entry]:
    return [Entry.model_validate(json.loads(line)) for line in lines(path)]
```

See [the field notes](docs/field-notes.md) and `records.py`.
"""
"""A session's note written in Markdown, as agents write them: a table, emphasis, a list, a heading, code and a link, for the page to show as such."""


LUP_IMPL = "a1f0"
"""The launch of the lup-impl session, by its id: the demo's busiest."""
FIX_CLOCK = "a07"
"""The ended fix-clock subagent of the lup-impl session, by their runtime's id:
their branch's landing waits on the operator, its clock module held in their
drawer, and a module of theirs is on a branch no worktree has checked out."""
LANDING_KEY = "demo-landing"
"""The stand-in landing's key among those waiting (`Wait.key`)."""
LANDING_TIP = "c1a55e5d0c4a7b1e9f0a3b2c4d5e6f708192a3b4"
"""The commit the stand-in landing puts on `dev`."""
CLOCK_SOURCE = (
    '"""A clock that ticks: what the dashboard\'s drawn spans read."""\n\n\n'
    "class Ticker:\n"
    '    """Says the time since a moment, again as it passes."""\n\n'
    "    def __init__(self, every: float = 5.0) -> None:\n"
    "        self.every = every\n\n"
    "    def due(self, last: float, now: float) -> bool:\n"
    '        """Say whether the next tick is due."""\n'
    "        return now - last >= self.every\n"
)
"""The clock module's text."""
NAMES_SOURCE = (
    '"""What each tick is called."""\n\n'
    'NAMES = {"s": "seconds", "m": "minutes", "h": "hours"}\n'
)
"""The names module's text."""

SURVEY_SOURCE = (
    "# Where auth is checked\n\n"
    "Each request's token is read once, in the middleware; no handler reads it again.\n"
)
"""explore-auth's survey's text."""


def stand_in_id(content: Content | None) -> str | None:
    """Return git's id for a stand-in file's content, as a drawer says its version, a binary one's made of its size; none for no file."""
    if content is None:
        return None
    data = content.text.encode() if isinstance(content, Text) else b"\0" * content.size
    return hashlib.sha1(
        b"blob %d\0" % len(data) + data, usedforsecurity=False
    ).hexdigest()


def kept_files(number: int, *, typed: bool = True, lines: int = 0) -> list[ChangedFile]:
    """Return the files a stand-in item changes (`files`), none where it changes none."""
    found = files(number, typed=typed, lines=lines)
    return found.files if isinstance(found, Files) else []


def in_order(recorded: list[Said | StandIn], latest: datetime) -> list[Said | StandIn]:
    """Return a record's steps in the order they came, each once, as a record holds them, `latest` for one saying no time: two moments of one conversation share the operator's words that led to them."""

    def came(each: Said | StandIn) -> datetime:
        at = each.step.at if isinstance(each, StandIn) else each.at
        return at or latest

    once = {each.model_dump_json(): each for each in recorded}
    return sorted(once.values(), key=came)


def text(*parts: str) -> Text:
    """Return a stand-in file's text, made of `parts`."""
    return Text(text="".join(parts))


def line(content: Text, written: str) -> int:
    """Return the number, from 1, of the line of a stand-in file's `content` that's `written` whole: where its stand-in reading places what it triggered."""
    return content.text.splitlines().index(written) + 1


def approved(lines: int, functions: int = 36) -> list[ChangedFile]:
    """Return the stand-in files that make the approval `lines` lines larger, as one of lup's own code may be by tens of thousands: half in production modules of `functions` functions, hundreds of lines each, every function of which changes, so the review shows each change with unchanged lines folded between; half in their tests, created, which it folds whole."""
    each = len(changing(0, functions, changed=True).splitlines())
    count = -(-lines // (2 * each))
    return [
        made
        for i in range(count)
        for made in (
            ChangedFile(
                path=Path("packages/lup/src/lup/approved") / f"module_{i}.py",
                before=text(changing(i, functions, changed=False)),
                after=text(changing(i, functions, changed=True)),
                reading=Reading(role="production"),
            ),
            ChangedFile(
                path=Path("packages/lup/tests/approved") / f"test_module_{i}.py",
                before=None,
                after=text(changing(i, functions, changed=True)),
                reading=Reading(role="test"),
            ),
        )
    ]


def changing(i: int, functions: int, *, changed: bool) -> str:
    """Return the stand-in module `i` of the approval's change (`approved`), of `functions` functions, each returning what it found, or, `changed`, sorted."""
    head = f'"""Module {i} of an approval at size: stand-in code."""\n\nfrom pathlib import Path\n'
    returned = "sorted(found)" if changed else "found"
    return "".join([head, *(function(at, returned) for at in range(functions))])


def files(number: int, *, typed: bool = True, lines: int = 0) -> Files | Refused:
    """Return the stand-in files of the approval (54), the held change (55) and the flagged writes (59, 60): Python, TypeScript, TOML, Markdown and JSON, changed, created, and one binary; each with a stand-in of the judge's reading of it, two of the approval's automatic, the rest open for what they ask, a production change, or a finding told, which only the approval's reading with types, once `typed`, holds; a new module and a method added, flagged. The approval holds `lines` lines more (`approved`)."""
    created = Reading(role="production", asks=[Ask(name="new-file", taken="flagged")])
    match number:
        case 54:
            cli = text(CLI_HEAD, CLI_SHOW_AFTER, CLI_MIDDLE, CLI_PUSH_AFTER, CLI_TAIL)
            split = line(cli, '    branch = refs[0].split("/")[-1]')
            told = [
                Found(
                    rule="string-split",
                    message=(
                        "`.split` takes a ref's name apart by hand. Splitting "
                        "structured text by hand matches the inputs it was tried "
                        "on, and fails quietly on the rest."
                    ),
                    start=split,
                    end=split,
                    taken="told",
                )
            ]
            return Files(
                number=number,
                files=[
                    ChangedFile(
                        path=Path("packages/lup-dashboard/page/README.md"),
                        before=None,
                        after=text(README),
                        reading=Reading(role="docs"),
                    ),
                    ChangedFile(
                        path=Path("packages/lup-dashboard/page/src/agents.ts"),
                        before=text(AGENTS_HEAD, AGENTS_BEFORE, AGENTS_TAIL),
                        after=text(AGENTS_HEAD, AGENTS_AFTER, AGENTS_TAIL),
                        reading=Reading(role="production"),
                    ),
                    ChangedFile(
                        path=Path("packages/lup-dashboard/page/src/main.tsx"),
                        before=text(MAIN_HEAD, MAIN_BEFORE),
                        after=text(MAIN_HEAD, MAIN_AFTER),
                        reading=Reading(role="production"),
                    ),
                    ChangedFile(
                        path=Path("packages/lup-dashboard/src/lup_dashboard/icon.png"),
                        before=None,
                        after=Binary(size=1150),
                        reading=created,
                    ),
                    ChangedFile(
                        path=Path("packages/lup-dev/pyproject.toml"),
                        before=text(PYPROJECT_HEAD, PYPROJECT_TAIL),
                        after=text(PYPROJECT_HEAD, PYPROJECT_ADDED, PYPROJECT_TAIL),
                        reading=Reading(
                            role="protected",
                            asks=[Ask(name="protected", taken="held")],
                        ),
                    ),
                    ChangedFile(
                        path=Path("packages/lup-dev/src/lup_dev/cli.py"),
                        before=text(
                            CLI_HEAD,
                            CLI_SHOW_BEFORE,
                            CLI_MIDDLE,
                            CLI_PUSH_BEFORE,
                            CLI_TAIL,
                        ),
                        after=cli,
                        reading=Reading(
                            role="production", findings=told if typed else []
                        ),
                    ),
                    ChangedFile(
                        path=Path("packages/lup/src/lup/transcripts/views.py"),
                        before=None,
                        after=text(VIEWS),
                        reading=created,
                    ),
                    *approved(lines),
                ],
            )
        case 55:
            records = text(RECORDS_HEAD, RECORDS_ADDED)
            ignored = (
                '    # lup: ignore("string-split", why="JSONL is an object a line")'
            )
            return Files(
                number=number,
                files=[
                    ChangedFile(
                        path=Path("AGENTS.md"),
                        before=text(AGENTS_MD_HEAD, AGENTS_MD_BEFORE, AGENTS_MD_TAIL),
                        after=text(AGENTS_MD_HEAD, AGENTS_MD_AFTER, AGENTS_MD_TAIL),
                        reading=Reading(
                            role="operator", asks=[Ask(name="operator", taken="held")]
                        ),
                    ),
                    ChangedFile(
                        path=Path("packages/lup-dashboard/page/package.json"),
                        before=text(PACKAGE_HEAD, PACKAGE_TAIL),
                        after=text(PACKAGE_HEAD, PACKAGE_ADDED, PACKAGE_TAIL),
                        reading=Reading(
                            role="protected",
                            asks=[Ask(name="protected", taken="held")],
                        ),
                    ),
                    ChangedFile(
                        path=Path("packages/lup/src/lup/transcripts/records.py"),
                        before=text(RECORDS_HEAD),
                        after=records,
                        reading=Reading(
                            role="production",
                            asks=[
                                Ask(
                                    name="ignore",
                                    taken="held",
                                    line=line(records, ignored),
                                )
                            ],
                        ),
                    ),
                ],
            )
        case 59:
            reader = text(READER)
            split = line(reader, '        lines = self.path.read_text().split("\\n")')
            return Files(
                number=number,
                files=[
                    ChangedFile(
                        path=Path("packages/lup/src/lup/transcripts/reader.py"),
                        before=None,
                        after=reader,
                        reading=Reading(
                            role="production",
                            asks=[Ask(name="new-file", taken="flagged")],
                            findings=[
                                Found(
                                    rule="string-split",
                                    message=(
                                        "`.split` takes a record apart by hand. "
                                        "Splitting structured text by hand matches "
                                        "the inputs it was tried on, and fails "
                                        "quietly on the rest."
                                    ),
                                    start=split,
                                    end=split,
                                    taken="told",
                                )
                            ],
                        ),
                    )
                ],
            )
        case 60:
            clock = text(CLOCK_HEAD, CLOCK_AFTER)
            return Files(
                number=number,
                files=[
                    ChangedFile(
                        path=Path("packages/lup-dev/src/lup_dev/clock.py"),
                        before=text(CLOCK_HEAD, CLOCK_BEFORE),
                        after=clock,
                        reading=Reading(
                            role="production",
                            asks=[
                                Ask(
                                    name="public-api",
                                    taken="flagged",
                                    line=line(clock, "    def why(self) -> str:"),
                                    api=ApiChanged(
                                        kind="function-added", name="Clock.why"
                                    ),
                                )
                            ],
                        ),
                    )
                ],
            )
        case _:
            return Refused(error=f"{cited(number)} changes no file")


def launch(id_: str, name: str, runtime: str, worktree: Path) -> Register:
    """Return a stand-in launch of `runtime` in `worktree`, named `name`."""
    repository = worktree.parent.parent
    return Register(
        launch=id_,
        runtime=runtime,
        worktree=worktree,
        repository=repository,
        judge=Path("/home/op/.local/bin/lup-dev"),
        container=f"lup-{id_}",
        limits=Limits(actions=["fetch", "push"], protected=["refs/heads/main"]),
        github=None,
        name=name,
    )
