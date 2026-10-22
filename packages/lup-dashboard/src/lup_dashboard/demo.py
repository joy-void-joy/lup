"""The dashboard over stand-in data: the real page, every view populated, with no host service or session behind it.

`lup-dashboard demo` serves it, for looking at a view while it's built (a session
in a room screenshots it headless) and for the operator to try one before it
lands. Its data are the host's own models, so it shows what the page would show.
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

from pydantic import Field

from lup.types import MutableModel
from lup_dashboard.host import Host
from lup_dev.clock import Clock, SystemClock
from lup_dev.host.protocol import (
    Activity,
    Holding,
    Limits,
    Listed,
    ListLaunches,
    Refused,
    Register,
    SetHolding,
    Talker,
)
from lup_dev.host.records import Called, Entry, Said, Task, Usage
from lup_dev.inbox.delivery import body
from lup_dev.inbox.parts import PartId
from lup_dev.inbox.protocol import (
    Context,
    Conversed,
    Drafted,
    Exchange,
    Exchanged,
    Files,
    Items,
    KeepDraft,
    KeepTalk,
    ListInbox,
    ListItems,
    Reviewed,
    SendDraft,
    SendItem,
    ShowContext,
    ShowConversation,
    ShowDraft,
    ShowFiles,
    Shown,
    ShowTalk,
    Talked,
    written,
)
from lup_dev.inbox.store import (
    ApiChanged,
    Approval,
    Binary,
    ChangedFile,
    Comment,
    Conversation,
    Decision,
    Done,
    Draft,
    Flagged,
    Found,
    Friction,
    HeldChange,
    HowItWent,
    Item,
    Message,
    Operator,
    Question,
    Quote,
    Reading,
    Reply,
    Review,
    Talk,
    Text,
    Told,
    Waiting,
    cited,
)
from lup_dev.inbox.store import Asked as Ask
from lup_dev.policy.since import Approved, ApproveSince, ShowSince, Since, SinceFile

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from lup_dashboard.api import Asked, Replied


class Standing(MutableModel):
    """What a stand-in conversation's record says of it: what its context holds, and its task list."""

    usage: Usage | None = None
    tasks: list[Task] = []


class Demo(MutableModel, Host, arbitrary_types_allowed=True):
    """A host serving stand-in launches, conversations and items, as of the clock's time, and keeping the operator's draft in memory; what it can't answer it refuses, saying it's a demo."""

    clock: Clock = SystemClock()
    # lup: ignore("runtime-mention", why="stand-in data: the runtimes the demo's launches show, not a feature built for one")
    runtimes: list[str] = ["claude", "codex"]
    """The runtimes the demo's launches run, by name: the first for most, the second for one."""
    draft: Draft = Draft()
    talks: dict[str, Talk] = {}
    """What the operator writes on each conversation, by its key, kept in memory."""
    sent: list[Item] = []
    """The items the operator's messages sent from the page made, kept in memory:
    they reach no agent, and are told at once."""
    grown: int = 0
    """How many steps the parser subagent's conversation has taken since the demo began: one more each time it's asked, so a page following it sees it grow."""
    holding: list[SetHolding] = []
    """The operator's switch turned on for each conversation it holds every flagged write of, kept in memory."""
    changed: asyncio.Event = Field(default_factory=asyncio.Event)
    """Set once something the page watches changes, and replaced: each watch answers again."""
    typing: bool = True
    """Whether the approval's types are being read, its files carrying the reading of their parse alone, as the host reads them in the background: until `types_read` after the page first asks for them."""
    types_read: timedelta = timedelta(seconds=4)
    """How long the approval's types take to read."""
    reading: asyncio.TimerHandle | None = None
    """The reading of the approval's types under way, once the page asked for its files."""
    arrives: timedelta = timedelta(seconds=10)
    """How long after the page first asks for the inbox a question of the parser subagent's arrives, so a session can watch the review keep its place as an item comes to a group above."""
    arriving: asyncio.TimerHandle | None = None
    """The arrival under way, once the page asked for the inbox."""
    arrived: datetime | None = None
    """When the late question arrived; none until it has."""
    size: int = 36
    """How many flagged writes of a busy day the review holds beside the demo's own items (`worked`), each of a module of hundreds of lines, from `workers` workers of the lup-impl session, each with a note and a friction, the first with a long conversation: none for the demo's own items alone, as its tests ask it."""
    first_worked: int = 1000
    """The number of the first item a worker made (`worked`): after the demo's own, so they're laid out after them."""
    workers: int = 6
    """How many workers the busy day's writes come from, subagents of the lup-impl session, each in a worktree of its own."""
    functions: int = 36
    """How many functions a worker's module holds, a dozen lines each: a file of hundreds of lines."""
    hooks: float = 0
    """How many stand-in hook calls a minute the workers make, each changing what one of them does and answering every watch again, as the host service answers each watch at each hook (`docs/host.md`, *Watching*); none by default."""
    hooked: int = 0
    """How many stand-in hook calls have come."""
    hooking: asyncio.TimerHandle | None = None
    """The next stand-in hook call, once the page first asked for the launches."""
    began: datetime | None = None
    """When the demo began, as of the clock the first time it's asked (`ago`)."""
    approved: list[int] = []
    """The flagged writes marked good from the drawer, by number, kept in memory."""
    grows: timedelta = timedelta(seconds=20)
    """How long after the page first asks what the parser subagent's branch changed since the operator approved it two more writes come to it, so a session can watch the drawer say so and bring them in."""
    growth: asyncio.TimerHandle | None = None
    """The growth under way, once the page asked."""
    grew: bool = False
    """Whether the two writes came."""

    @override
    async def ask(self, request: Asked) -> Replied:
        match request:
            case ListLaunches():
                if self.hooks > 0 and self.hooking is None:
                    self.hooking = asyncio.get_running_loop().call_later(
                        60 / self.hooks, self.hook
                    )
                return self.listed()
            case SetHolding(on=on) as switched:
                others = [
                    each
                    for each in self.holding
                    if each.session != switched.session or each.agent != switched.agent
                ]
                self.holding = [*others, switched] if on else others
                self.changed.set()
                self.changed = asyncio.Event()
                return Holding(on=on)
            case ListInbox():
                if self.arriving is None:
                    self.arriving = asyncio.get_running_loop().call_later(
                        self.arrives.total_seconds(), self.arrive
                    )
                return self.items()
            case ShowDraft():
                return Drafted(draft=self.draft)
            case KeepDraft(draft=draft):
                self.draft = draft
                return Drafted(draft=draft)
            case SendDraft():
                self.draft = self.draft.kept()
                return Reviewed(items=[])
            case ShowTalk(conversation=conversation):
                return Talked(talk=self.talks.get(conversation.key(), Talk()))
            case KeepTalk(conversation=conversation, talk=talk):
                self.talks = {**self.talks, conversation.key(): talk}
                return Talked(talk=talk)
            case ShowFiles(number=number):
                if number >= self.first_worked:
                    return self.worked_files(number)
                if number == 54 and self.typing and self.reading is None:
                    self.reading = asyncio.get_running_loop().call_later(
                        self.types_read.total_seconds(), self.typed
                    )
                return files(number, typed=not self.typing)
            case ShowContext(number=number):
                return self.context(number)
            case SendItem() as sending:
                return self.sending(sending)
            case ShowConversation(session=session, agent=agent, since=since):
                if (session, agent) == ("s1", "a02"):
                    self.grown += 1
                steps = self.conversation(session, agent)
                standing = self.standing(session, agent)
                return Conversed(
                    entries=steps[since:],
                    since=since,
                    total=len(steps),
                    usage=standing.usage,
                    tasks=standing.tasks,
                )
            case ListItems(conversation=conversation):
                return self.exchanged(conversation)
            case ShowSince(conversation=conversation, seen=seen):
                if self.growth is None:
                    self.growth = asyncio.get_running_loop().call_later(
                        self.grows.total_seconds(), self.grow
                    )
                return self.since(conversation, seen)
            case ApproveSince(conversation=conversation, path=path):
                flags = [
                    each.flags
                    for each in self.since(conversation, None).files
                    if path is None or each.file.path == path
                ]
                approved = [number for each in flags for number in each]
                self.approved = [*self.approved, *approved]
                self.changed.set()
                self.changed = asyncio.Event()
                return Approved(flags=approved)
            case _:
                return Refused(error=f"the demo doesn't answer `{request.kind}`")

    @override
    async def watch(self, request: Asked) -> AsyncGenerator[Replied]:
        """Yield the reply at once, then again at each change where it differs from the one yielded last, as the host service's watch does (`docs/host.md`, *Watching*): a stand-in hook call sends the launches again, with what a worker does, and the inbox only where it changed."""
        sent = ""
        while True:
            changed = self.changed
            replied = await self.ask(request)
            line = replied.model_dump_json()
            if line != sent:
                yield replied
                sent = line
            await changed.wait()

    @override
    async def settle(self, number: int) -> None:
        """Install nothing: the demo's approvals are stand-ins."""
        del number

    def typed(self) -> None:
        """End the reading of the approval's types: its files carry their whole reading, and each watch answers again."""
        self.typing = False
        self.changed.set()
        self.changed = asyncio.Event()

    def arrive(self) -> None:
        """Let the parser subagent's late question arrive, made at the clock's time, and each watch answer again."""
        self.arrived = self.clock.now()
        self.changed.set()
        self.changed = asyncio.Event()

    def grow(self) -> None:
        """Let two more writes come to the parser subagent's branch: its drawer says so at the page's next asking, and brings them in on its key."""
        self.grew = True

    def standing(self, session: str, agent: str | None) -> Standing:
        """Return what a stand-in conversation's record says of it: the parser subagent's three tasks and a ninth of the long window; its session's half of it and no task; the second runtime's session's own window and plan; none for the rest."""
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
        """Return what a stand-in conversation's branch changed since the operator approved it: the parser subagent's new reader module and, once `grew`, a change to the clock beside it, from its session's worktree; each file approved from the drawer left out; nothing for the rest."""
        dev = conversation.repository / "tree" / "dev"
        worker = next(
            (n for n in range(1, self.workers + 1) if worker_agent(n) == conversation.agent),
            None,
        )
        if conversation.session == "s1" and worker is not None and self.size > 0:
            return self.worked_since(worker, seen)
        parser = conversation.session == "s1" and conversation.agent == "a02"
        if not parser:
            return Since(
                worktree=dev,
                branch=None,
                version="demo 0",
                writes=0,
                same=seen == "demo 0",
            )

        def filed(number: int) -> SinceFile | None:
            found = files(number)
            if number in self.approved or not isinstance(found, Files):
                return None
            [file] = found.files
            return SinceFile(file=file, version=f"blob-{number}", flags=[number])

        shown = [
            each
            for number in [59, *([60] if self.grew else [])]
            if (each := filed(number)) is not None
        ]
        writes = 5 if self.grew else 3
        version = f"demo-{'grown' if self.grew else 'first'} {len(self.approved)}"
        if seen == version:
            return Since(
                worktree=dev,
                branch="feat-reader",
                version=version,
                writes=writes,
                same=True,
            )
        return Since(
            worktree=dev,
            branch="feat-reader",
            version=version,
            writes=writes,
            files=shown,
        )

    def worked_since(self, n: int, seen: str | None) -> Since:
        """Return what worker `n`'s branch changed since the operator approved it: the module of each of its flagged writes (`worked_files`), each approved from the drawer left out, from its worktree; the files left out where `seen` is the version as it stands."""
        numbers = [
            each.number
            for each in self.worked()
            if isinstance(each.reason, Flagged) and each.sender == self.worker(n)
        ]

        def filed(number: int) -> SinceFile | None:
            found = self.worked_files(number)
            if number in self.approved or not isinstance(found, Files):
                return None
            [file] = found.files
            return SinceFile(file=file, version=f"blob-{number}", flags=[number])

        version = f"worker-{n} {len(self.approved)}"
        shown = [each for number in numbers if (each := filed(number)) is not None]
        return Since(
            worktree=worker_worktree(n),
            branch=f"worker-{n}",
            version=version,
            writes=len(numbers),
            same=seen == version,
            files=[] if seen == version else shown,
        )

    def ago(self, minutes: float) -> datetime:
        """Return the moment `minutes` before the demo began (`began`): its stand-in items and activities are made at moments before it, kept as a real inbox's are, so a watch's reply differs from the one before only where something changed."""
        if self.began is None:
            self.began = self.clock.now()
        return self.began - timedelta(minutes=minutes)

    def listed(self) -> Listed:
        """Return four launches over three repositories: one with subagents working, asking and ended; one idle; one on the second runtime; one whose session hasn't started."""
        first, second = self.runtimes
        lup = launch("a1f0", "lup-impl", first, Path("/home/op/lup.git/tree/dev"))
        voice = launch(
            "b2e1",
            "guidance-voice",
            first,
            Path("/home/op/lup.git/tree/guidance-voice"),
        )
        zoetrope = launch(
            "c3d2", "main", second, Path("/home/op/zoetrope.git/tree/main")
        )
        waiting = launch(
            "d4c3", "magpie-search", first, Path("/home/op/magpie.git/tree/main")
        )
        calling = Activity(state="calling", since=self.ago(0.4), tool="Bash")
        ended = [
            talker(
                name,
                "s1",
                Activity(state="ended", since=self.ago(minutes)),
                agent=f"a0{at + 4}",
                kind="Explore",
                parent="lup-impl",
                depth=1,
            )
            for at, (name, minutes) in enumerate(
                [("survey-legacy", 52), ("probe-meta", 40), ("nest-probe", 33)]
            )
        ]
        talkers = {
            "a1f0": [
                talker("lup-impl", "s1", calling),
                talker(
                    "explore-auth",
                    "s1",
                    Activity(state="calling", since=self.ago(1.5), tool="Grep"),
                    agent="a01",
                    kind="Explore",
                    parent="lup-impl",
                    depth=1,
                ),
                talker(
                    "parser",
                    "s1",
                    Activity(
                        state="calling",
                        since=self.ago(4),
                        tool="mcp__lup__ask",
                        lups=True,
                    ),
                    agent="a02",
                    kind="general-purpose",
                    parent="lup-impl",
                    depth=1,
                ),
                talker(
                    "grep-tokens",
                    "s1",
                    Activity(state="idle", since=self.ago(0.2)),
                    agent="a03",
                    kind="general-purpose",
                    parent="lup-impl/parser",
                    depth=2,
                ),
                *ended,
                *self.working(),
            ],
            "b2e1": [
                talker(
                    "guidance-voice", "s2", Activity(state="idle", since=self.ago(12))
                )
            ],
            "c3d2": [
                talker(
                    "main",
                    "s3",
                    Activity(state="calling", since=self.ago(2), tool="exec_command"),
                ),
                talker(
                    "render_frames",
                    "s3",
                    Activity(state="calling", since=self.ago(0.7), tool="exec_command"),
                    agent="th-7",
                    kind="default",
                    parent="main",
                    depth=1,
                ),
            ],
        }
        return Listed(
            launches=[lup, voice, zoetrope, waiting],
            sessions={"s1": "lup-impl", "s2": "guidance-voice", "s3": "main"},
            talkers={
                launch: [
                    each.model_copy(update={"holding": self.holds(each)})
                    for each in conversations
                ]
                for launch, conversations in talkers.items()
            },
        )

    def holds(self, talker: Talker) -> bool:
        """Say whether the operator holds each flagged write of `talker`."""
        return any(
            each.session == talker.session and each.agent == talker.agent
            for each in self.holding
        )

    def items(self) -> Items:
        """Return what waits for the operator: a subagent's question of numbered decisions, a session's note, another's problem, an approval of a host zone, a session's write held for them, another's last words of a turn, a friction and how the work went, and two writes that landed flagged, the subagent's new module gathering three; the operator last settled an item 3 minutes ago, so those since are new."""
        every = self.every()
        waiting = [
            each
            for each in every
            if each.recipient == Operator() and isinstance(each.state, Waiting)
        ]
        numbers = [each.number for each in waiting]
        return Items(
            items=waiting,
            reviewed=self.ago(3),
            answers=[
                each
                for each in every
                if each.sender == Operator()
                and isinstance(each.reason, Review)
                and any(comment.item in numbers for comment in each.reason.comments)
            ],
        )

    def sending(self, sending: SendItem) -> Shown | Refused:
        """Keep the operator's message to a conversation of a launch as the item it makes, told at once; refused for a launch whose session hasn't started."""
        listed = self.listed()
        launch = next(
            (each for each in listed.launches if each.launch == sending.launch), None
        )
        own = next(
            (
                each
                for each in listed.talkers.get(sending.launch, [])
                if each.agent is None
            ),
            None,
        )
        if launch is None or own is None:
            return Refused(error=f"no session of launch `{sending.launch}` has started")
        now = self.clock.now()
        item = Item(
            number=100 + len(self.sent) + 1,
            reason=Message(kind="note", text=sending.text),
            sender=Operator(),
            recipient=Conversation(
                repository=launch.repository,
                runtime=launch.runtime,
                session=own.session,
                agent=sending.agent,
            ),
            made=now,
            state=Told(at=now, how="call"),
        )
        self.sent = [*self.sent, item]
        self.changed.set()
        self.changed = asyncio.Event()
        return Shown(item=item)

    def exchanged(self, conversation: Conversation) -> Exchanged:
        """Return the stand-in items `conversation` sent, as it wrote them, and those it was sent, as it's told them."""
        items = [
            each
            for each in self.every()
            if conversation in (each.sender, each.recipient, each.addressed)
        ]
        return Exchanged(
            sent=[
                Exchange(item=each, text=written(each))
                for each in items
                if each.sender == conversation
            ],
            received=[
                Exchange(item=each, text=body(each))
                for each in items
                if each.sender != conversation
            ],
        )

    def every(self) -> list[Item]:
        """Return every stand-in item, by number: those waiting for the operator; the parser subagent's note they replied to, at the call that sent it; an ended subagent's note whose reply went to its session; the parser subagent's late question, once it has arrived (`arrives`); and the messages sent from the page."""
        first, second = self.runtimes
        lup = Path("/home/op/lup.git")
        parser = Conversation(repository=lup, runtime=first, session="s1", agent="a02")
        session = Conversation(repository=lup, runtime=first, session="s1")
        survey = session.model_copy(update={"agent": "a04"})
        voice = Conversation(repository=lup, runtime=first, session="s2")
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
            typing=self.typing,
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
            # The operator's review of the voice session's note, which its reply by id brought back before them.
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
            Item(
                number=56,
                reason=Message(
                    kind="note",
                    text=(
                        "The guidance's voice section is rewritten and the gate "
                        "passes; it's on its branch for you to look at."
                    ),
                    ending=True,
                ),
                sender=voice,
                recipient=Operator(),
                worktree=lup / "tree" / "guidance-voice",
                made=self.ago(1.5),
            ),
            Item(
                number=57,
                reason=Friction(
                    text=(
                        "`uv run lup-dev check` rebuilt the engine for four minutes "
                        "before the tests ran, printing nothing until then. I was "
                        "running the gate on the reader; a line saying the rebuild, "
                        "and how long it takes, would have kept me from killing it."
                    )
                ),
                sender=parser,
                recipient=Operator(),
                worktree=dev,
                call="call-57",
                made=self.ago(3),
            ),
            Item(
                number=58,
                reason=HowItWent(
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
            *(
                []
                if self.arrived is None
                else [
                    Item(
                        number=61,
                        reason=Question(
                            text=(
                                "The reader is done but for its name. Which, for "
                                "the module and the class?"
                            ),
                            decisions=[
                                Decision(
                                    text="`transcripts.reader`, as the first lup called it",
                                    lean="yes: sessions looking for it will look there first",
                                )
                            ],
                        ),
                        sender=parser,
                        recipient=Operator(),
                        worktree=dev,
                        call="call-61",
                        made=self.arrived,
                    )
                ]
            ),
            Item(
                number=62,
                reason=Message(kind="note", text=MARKDOWN_NOTE),
                sender=session,
                recipient=Operator(),
                worktree=dev,
                call="call-62",
                made=self.ago(0.8),
            ),
            *self.worked(),
            *self.sent,
        ]

    def context(self, number: int) -> Context | Refused:
        """Return a stand-in moment for each item an agent's call made: the operator's last words, what the agent said and called after them, the call, and what came after; the approval, which no call made, has none; a worker's item has its own (`worked_context`)."""
        if number >= self.first_worked:
            return self.worked_context(number)

        def operator(text: str, minutes: float) -> Said:
            return Said(by="operator", text=text, at=self.ago(minutes))

        def agent(text: str, minutes: float) -> Said:
            return Said(by="agent", text=text, at=self.ago(minutes))

        def called(tool: str, minutes: float, id_: str | None = None) -> Called:
            return Called(tool=tool, id=id_, at=self.ago(minutes))

        moments: dict[int, list[Entry]] = {
            51: [
                operator(
                    "Build the transcript reader, both runtimes. Ask me about the "
                    "shape before you build on it.",
                    9,
                ),
                agent(
                    "Reading the first runtime's records, to see what each line holds.",
                    8,
                ),
                called("Bash", 8),
                called("Bash", 7.8),
                called("Read", 7.5),
                agent(
                    "Twenty kinds of line; four carry what was said. Two ways to read "
                    "them: a model per kind, or a dict walked by hand.",
                    5,
                ),
                called("mcp__lup__ask", 4, "call-51"),
                agent("While that waits, I'll read the second runtime's.", 3.9),
                called("Grep", 3.8),
            ],
            52: [
                operator("Keep going on the guidance rewrite.", 30),
                agent("Checking how the records are encoded before I search them.", 14),
                called("Bash", 13),
                called("mcp__lup__note", 12, "call-52"),
                agent("Carrying on with the search command.", 11.9),
            ],
            53: [
                operator("Render the second scene at full size.", 20),
                agent("Rendering frames 1 to 600.", 10),
                called("exec_command", 9),
                called("exec_command", 3),
                agent("ffmpeg stops at frame 412, on the source clip.", 2.2),
                called("blocked", 2, "call-53"),
            ],
            55: [
                operator(
                    "Highlight the code in the review with CodeMirror's own "
                    "language packages.",
                    6,
                ),
                agent("Adding the language packages to the page.", 1),
                called("Bash", 0.8),
                called("Edit", 0.5, "call-55"),
            ],
            57: [
                agent("Running the gate on the reader.", 7.5),
                called("Bash", 7.4),
                called("mcp__lup__friction", 3, "call-57"),
                agent("The tests pass; on to the second runtime's records.", 2.9),
            ],
            58: [
                operator("Keep going on the guidance rewrite.", 30),
                agent("The voice section is done, and the gate passes.", 1.6),
                called("mcp__lup__how_it_went", 1.4, "call-58"),
            ],
            59: [
                operator(
                    "Build the transcript reader, both runtimes. Ask me about the "
                    "shape before you build on it.",
                    9,
                ),
                agent(
                    "A module of its own for the reader, with a model per turn.", 6.5
                ),
                called("Write", 6, "call-59"),
                called("Edit", 5.5),
                called("Edit", 5),
            ],
            60: [
                operator("Let the tests say why they wait.", 4),
                agent("The clock says why its last wait waited.", 2.7),
                called("Edit", 2.5, "call-60"),
            ],
            62: [
                operator(
                    "Build the transcript reader, both runtimes. Ask me about the "
                    "shape before you build on it.",
                    9,
                ),
                agent(
                    "Counting what each kind of line holds, before the reader is shaped.",
                    1.2,
                ),
                called("Bash", 1.1),
                called("mcp__lup__note", 0.8, "call-62"),
            ],
        }
        entries = moments.get(number)
        if entries is None:
            return Refused(error=f"{cited(number)} was made by no agent's call")
        [anchor] = [
            at
            for at, each in enumerate(entries)
            if isinstance(each, Called) and each.id == f"call-{number}"
        ]
        return Context(number=number, entries=entries, anchor=anchor)

    def conversation(self, session: str, agent: str | None) -> list[Entry]:
        """Return a stand-in conversation: for the parser subagent, the call that sent @47, then its moment around @51 with what led to it; for the first worker, a day's work (`long_conversation`); for any other, a short exchange."""
        if (session, agent) == ("s1", worker_agent(1)) and self.size > 0:
            return self.long_conversation()
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
                Called(tool="Bash", at=self.ago(28)),
                Called(tool="Read", at=self.ago(27)),
                Called(tool="mcp__lup__note", id="call-47", at=self.ago(26)),
                Said(
                    by="agent",
                    text="Reading the first runtime's records.",
                    at=self.ago(25.5),
                ),
                Called(tool="Read", at=self.ago(24)),
                Called(tool="Grep", at=self.ago(22)),
                *self.moment(51),
                *self.growing(),
            ]
        return [
            Said(
                by="operator",
                text="Carry on with what you were doing.",
                at=self.ago(20),
            ),
            Said(by="agent", text="On it: reading the code first.", at=self.ago(19)),
            Called(tool="Grep", at=self.ago(18)),
            Called(tool="Read", at=self.ago(17)),
            Called(tool="Read", at=self.ago(17)),
            Said(by="agent", text="Found it. Writing the fix next.", at=self.ago(15)),
        ]

    def growing(self) -> list[Entry]:
        """Return the steps the parser subagent took since the demo began: a call, then what it found, in turn."""
        return [
            Called(tool="Read", at=self.ago(0))
            if step % 2 == 0
            else Said(
                by="agent",
                text=f"Read the second runtime's record {step // 2 + 1}: four kinds again.",
                at=self.ago(0),
            )
            for step in range(self.grown)
        ]

    def moment(self, number: int) -> list[Entry]:
        """Return the stand-in steps around item `number`, none where it has none."""
        found = self.context(number)
        return found.entries if isinstance(found, Context) else []

    def hook(self) -> None:
        """Let a stand-in hook call come: what one worker does changes (`working`), each watch answers again, and the next comes after the interval `hooks` gives."""
        self.hooked += 1
        self.changed.set()
        self.changed = asyncio.Event()
        self.hooking = asyncio.get_running_loop().call_later(60 / self.hooks, self.hook)

    def working(self) -> list[Talker]:
        """Return the workers' conversations (`workers`), subagents of the lup-impl session, each calling a tool or between calls as the stand-in hook calls have it (`hook`); none without a busy day's writes (`size`)."""
        if self.size == 0:
            return []
        tools = ["Read", "Edit", "Bash"]
        return [
            talker(
                f"worker-{n}",
                "s1",
                Activity(
                    state="calling",
                    since=self.ago(0.3),
                    tool=tools[(self.hooked + n) % len(tools)],
                )
                if (self.hooked + n) % 2 == 0
                else Activity(state="idle", since=self.ago(0.1)),
                agent=worker_agent(n),
                kind="general-purpose",
                parent="lup-impl",
                depth=1,
            )
            for n in range(1, self.workers + 1)
        ]

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
        """Return the busy day's items (`size`): each worker's note, written in Markdown, and its friction, then the flagged writes, each worker's in turn, each of a module of hundreds of lines (`worked_files`); numbered from `first_worked`, made over the last hours, oldest first, each by a call, so each has a moment (`worked_context`)."""
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
                )
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

    def worked_context(self, number: int) -> Context | Refused:
        """Return the stand-in moment of a worker's item (`worked`): its brief, the reading before the item, the call that made it, and what came after."""
        item = next((each for each in self.worked() if each.number == number), None)
        if item is None:
            return Refused(error=f"{cited(number)} was made by no agent's call")

        def before(minutes: float) -> datetime:
            return item.made - timedelta(minutes=minutes)

        entries: list[Entry] = [
            Said(
                by="operator",
                text=(
                    "Build the piece your brief names, on a branch of your own; ask "
                    "before you build on a shape."
                ),
                at=before(50),
            ),
            Said(
                by="agent",
                text="Reading the files the brief names first.",
                at=before(49),
            ),
            Called(tool="Read", at=before(48)),
            Called(tool="Grep", at=before(47)),
            Said(
                by="agent",
                text="Writing the module, a function a step, with a docstring each.",
                at=before(2),
            ),
            Called(tool="Write", id=f"call-{number}", at=item.made),
            Said(by="agent", text="On to its tests.", at=before(-0.1)),
        ]
        return Context(number=number, entries=entries, anchor=5)

    def long_conversation(self, steps: int = 300) -> list[Entry]:
        """Return the first worker's conversation, `steps` long: its brief, then a call and what it found, in turn, as a day's work reads."""
        tools = ["Read", "Edit", "Bash"]
        return [
            Said(
                by="operator",
                text=(
                    "Build the piece your brief names, on a branch of your own; ask "
                    "before you build on a shape."
                ),
                at=self.ago(400),
            ),
            *(
                Called(tool=tools[step % len(tools)], at=self.ago(400 - step))
                if step % 2 == 0
                else Said(
                    by="agent",
                    text=(
                        f"Step {step // 2 + 1}: read the module, changed one function, "
                        "ran its tests."
                    ),
                    at=self.ago(400 - step),
                )
                for step in range(steps)
            ),
        ]


def worker_agent(n: int) -> str:
    """Return the runtime's id of worker `n`'s subagent."""
    return f"w{n:02}"


def worker_worktree(n: int) -> Path:
    """Return worker `n`'s worktree: one of its own, beside the demo's."""
    return Path("/home/op/lup.git/tree") / f"worker-{n}"


def worked_path(n: int, i: int) -> Path:
    """Return the module worker `n`'s write `i` landed, from its worktree's root."""
    return Path("packages/lup/src/lup") / f"worker{n}" / f"module_{i}.py"


def module(n: int, i: int, functions: int) -> str:
    """Return a stand-in Python module, worker `n`'s write `i`, of `functions` functions: hundreds of lines, each function's body folding and its lines highlighted as the review shows them."""
    head = (
        f'"""Worker {n}\'s module {i}: stand-in code, a busy day\'s flagged write."""\n'
        "\n"
        "from pathlib import Path\n"
    )
    return "".join([head, *(function(at) for at in range(functions))])


def function(at: int) -> str:
    """Return one stand-in function, `step_<at>`, with a docstring and a body of a few lines, so bodies fold and runs of lines sit inside them."""
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
        "    return found\n"
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
    integration = LupDevSettings().lup_integration_branch
    if f"refs/heads/{integration}" not in refs:
        return
    root = Git.pinned(launch.repository).main_worktree()
    number = await asyncio.to_thread(machine_trust(root, []).proposed)
'''
CLI_PUSH_AFTER = '''
async def proposed_after(
    delivery: Delivery, launch: Register, refs: list[str]
) -> None:
    """Put the approval of the zone at the integration branch's tip in the inbox, naming the session that pushed."""
    integration = LupDevSettings().lup_integration_branch
    if f"refs/heads/{integration}" not in refs:
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
4. **A held change is answered in the review:** Space `a` or `x`, the comments
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


def text(*parts: str) -> Text:
    """Return a stand-in file's text, made of `parts`."""
    return Text(text="".join(parts))


def line(content: Text, written: str) -> int:
    """Return the number, from 1, of the line of a stand-in file's `content` that's `written` whole: where its stand-in reading places what it triggered."""
    return content.text.splitlines().index(written) + 1


def files(number: int, *, typed: bool = True) -> Files | Refused:
    """Return the stand-in files of the approval (54), the held change (55) and the flagged writes (59, 60): Python, TypeScript, TOML, Markdown and JSON, changed, created, and one binary; each with a stand-in of the judge's reading of it, two of the approval's automatic, the rest open for what they ask, a production change, or a finding told, which only the approval's reading with types, once `typed`, holds; a new module and a method added, flagged."""
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


def talker(
    own: str,
    session: str,
    activity: Activity,
    *,
    agent: str | None = None,
    kind: str | None = None,
    parent: str | None = None,
    depth: int = 0,
) -> Talker:
    """Return a stand-in conversation, `depth` spawns below its session's own: its own name, under `parent`'s path where it has one."""
    path = own if parent is None else f"{parent}/{own}"
    return Talker(
        path=path,
        own=own,
        session=session,
        agent=agent,
        kind=kind,
        parent=parent,
        depth=depth,
        activity=activity,
    )
