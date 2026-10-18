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
from lup_dev.host.records import Called, Entry, Said
from lup_dev.inbox.protocol import (
    Context,
    Conversed,
    Drafted,
    Items,
    KeepDraft,
    ListInbox,
    Reviewed,
    SendDraft,
    SendItem,
    ShowContext,
    ShowConversation,
    ShowDiff,
    ShowDraft,
    Shown,
    Whole,
)
from lup_dev.inbox.store import (
    Approval,
    Conversation,
    Decision,
    Draft,
    HeldChange,
    Item,
    Message,
    Operator,
    Question,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from lup_dashboard.api import Asked, Replied


class Demo(MutableModel, Host, arbitrary_types_allowed=True):
    """A host serving stand-in launches, conversations and items, as of the clock's time, and keeping the operator's draft in memory; what it can't answer it refuses, saying it's a demo."""

    clock: Clock = SystemClock()
    # lup: ignore("runtime-mention", why="stand-in data: the runtimes the demo's launches show, not a feature built for one")
    runtimes: list[str] = ["claude", "codex"]
    """The runtimes the demo's launches run, by name: the first for most, the second for one."""
    draft: Draft = Draft()
    sent: list[SendItem] = []
    """The operator's messages sent from the page, kept in memory: they reach no agent."""
    grown: int = 0
    """How many steps the parser subagent's conversation has taken since the demo began: one more each time it's asked, so a page following it sees it grow."""
    holding: list[SetHolding] = []
    """The operator's switch turned on for each conversation it holds every flagged write of, kept in memory."""
    changed: asyncio.Event = Field(default_factory=asyncio.Event)
    """Set once something the page watches changes, and replaced: each watch answers again."""

    @override
    async def ask(self, request: Asked) -> Replied:
        match request:
            case ListLaunches():
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
                return self.items()
            case ShowDraft():
                return Drafted(draft=self.draft)
            case KeepDraft(draft=draft):
                self.draft = draft
                return Drafted(draft=draft)
            case SendDraft():
                self.draft = self.draft.kept()
                return Reviewed(items=[])
            case ShowDiff():
                return Whole(text=diff())
            case ShowContext(number=number):
                return self.context(number)
            case SendItem() as sending:
                self.sent = [*self.sent, sending]
                first, _ = self.runtimes
                return Shown(
                    item=Item(
                        number=100 + len(self.sent),
                        reason=Message(kind="note", text=sending.text),
                        sender=Operator(),
                        recipient=Conversation(
                            repository=Path("/home/op/lup.git"),
                            runtime=first,
                            session="s1",
                            agent=sending.agent,
                        ),
                        made=self.clock.now(),
                    )
                )
            case ShowConversation(session=session, agent=agent, since=since):
                if (session, agent) == ("s1", "a02"):
                    self.grown += 1
                steps = self.conversation(session, agent)
                return Conversed(entries=steps[since:], since=since, total=len(steps))
            case _:
                return Refused(error=f"the demo doesn't answer `{request.kind}`")

    @override
    async def watch(self, request: Asked) -> AsyncGenerator[Replied]:
        while True:
            changed = self.changed
            yield await self.ask(request)
            await changed.wait()

    @override
    async def settle(self, number: int) -> None:
        """Install nothing: the demo's approvals are stand-ins."""
        del number

    def ago(self, minutes: float) -> datetime:
        """Return the moment `minutes` before the clock's."""
        return self.clock.now() - timedelta(minutes=minutes)

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
        adlib = launch("c3d2", "main", second, Path("/home/op/adlib.git/tree/main"))
        waiting = launch(
            "d4c3", "nori-search", first, Path("/home/op/nori.git/tree/main")
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
            launches=[lup, voice, adlib, waiting],
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
        """Return what waits for the operator: a subagent's question of numbered decisions, a session's note, another's problem, an approval of a host zone, and a session's write held for them."""
        first, second = self.runtimes
        lup = Path("/home/op/lup.git")
        parser = Conversation(repository=lup, runtime=first, session="s1", agent="a02")
        voice = Conversation(repository=lup, runtime=first, session="s2")
        adlib = Conversation(
            repository=Path("/home/op/adlib.git"), runtime=second, session="s3"
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
                " packages/lup-dev/src/lup_dev/cli.py | 48 +++++++\n"
                " packages/lup/src/lup/transcripts/views.py | 160 ++++++++++++++\n"
                " 2 files changed, 208 insertions(+)"
            ),
            repository=lup,
            fingerprint="demo",
        )
        made = [
            (51, question, parser, "dev", 4),
            (52, note, voice, "guidance-voice", 12),
            (53, problem, adlib, "main", 2),
        ]
        return Items(
            items=[
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
                    worktree=lup / "tree" / "dev",
                    made=self.ago(1),
                ),
                Item(
                    number=55,
                    reason=HeldChange(
                        text="Let the change to pyproject.toml land?",
                        summary=(
                            "pyproject.toml: /home/op/lup.git/tree/dev/pyproject.toml "
                            "is a protected path (pyproject.toml)"
                        ),
                        worktree=lup / "tree" / "dev",
                        key="a1b2c3",
                    ),
                    sender=Conversation(repository=lup, runtime=first, session="s1"),
                    recipient=Operator(),
                    worktree=lup / "tree" / "dev",
                    made=self.ago(0.5),
                ),
            ]
        )

    def context(self, number: int) -> Context | Refused:
        """Return a stand-in moment for each item an agent's call made: the operator's last words, what the agent said and called after them, the call, and what came after; the approval, which no call made, has none."""

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
                called("report", 2, "call-53"),
            ],
        }
        entries = moments.get(number)
        if entries is None:
            return Refused(error=f"item {number} was made by no agent's call")
        [anchor] = [
            at
            for at, each in enumerate(entries)
            if isinstance(each, Called) and each.id == f"call-{number}"
        ]
        return Context(number=number, entries=entries, anchor=anchor)

    def conversation(self, session: str, agent: str | None) -> list[Entry]:
        """Return a stand-in conversation: for the parser subagent, its moment around item 51 with what led to it; for any other, a short exchange."""
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


def diff() -> str:
    """Return the stand-in approval's whole diff."""
    return """diff --git a/packages/lup/src/lup/transcripts/views.py b/packages/lup/src/lup/transcripts/views.py
new file mode 100644
--- /dev/null
+++ b/packages/lup/src/lup/transcripts/views.py
@@ -0,0 +1,12 @@
+def folded(tools: list[str]) -> str:
+    \"\"\"Say a run of tool calls in a line.\"\"\"
+    named = [counted(tool, len(list(run))) for tool, run in groupby(tools)]
+    return f"· called {', '.join(named)}"
"""


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
