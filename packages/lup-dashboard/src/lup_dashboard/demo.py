"""The dashboard over stand-in data: the real page, every view populated, with no host service or session behind it.

`lup-dashboard demo` serves it, for looking at a view while it's built (a session
in a room screenshots it headless) and for the operator to try one before it
lands. Its data are the host's own models, so it shows what the page would show.
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

from lup.types import MutableModel
from lup_dashboard.host import Host
from lup_dev.clock import Clock, SystemClock
from lup_dev.host.protocol import (
    Activity,
    Limits,
    Listed,
    ListLaunches,
    Refused,
    Register,
    Talker,
)
from lup_dev.host.records import Called, Entry, Said
from lup_dev.inbox.protocol import (
    Context,
    Conversed,
    Drafted,
    Files,
    Items,
    KeepDraft,
    ListInbox,
    Reviewed,
    SendDraft,
    SendItem,
    ShowContext,
    ShowConversation,
    ShowDraft,
    ShowFiles,
    Shown,
)
from lup_dev.inbox.store import (
    Approval,
    Binary,
    ChangedFile,
    Conversation,
    Decision,
    Draft,
    HeldChange,
    Item,
    Message,
    Operator,
    Question,
    Text,
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

    @override
    async def ask(self, request: Asked) -> Replied:
        match request:
            case ListLaunches():
                return self.listed()
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
            case ShowFiles(number=number):
                return files(number)
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
        yield await self.ask(request)
        await asyncio.Event().wait()

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
            talkers=talkers,
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
                " packages/lup-dashboard/page/src/agents.ts               |  3 +++\n"
                " packages/lup-dashboard/src/lup_dashboard/icon.png (new) | Bin 0 -> 1150 bytes\n"
                " packages/lup-dev/pyproject.toml                         |  1 +\n"
                " packages/lup-dev/src/lup_dev/cli.py                     | 15 +++++++++++----\n"
                " packages/lup/src/lup/transcripts/views.py (new)         | 25 +++++++++++++++++++++++++\n"
                " 5 files changed, 40 insertions(+), 4 deletions(-)"
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
                        text="Let the change to 2 files land?",
                        summary=(
                            "AGENTS.md: AGENTS.md is the operator's document, asked "
                            "about every time\n"
                            "packages/lup-dashboard/page/package.json: "
                            "/home/op/lup.git/tree/dev/packages/lup-dashboard/page/"
                            "package.json is a protected path (package.json)"
                        ),
                        worktree=lup / "tree" / "dev",
                        key="a1b2c3",
                    ),
                    sender=Conversation(repository=lup, runtime=first, session="s1"),
                    recipient=Operator(),
                    worktree=lup / "tree" / "dev",
                    call="call-55",
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

lup is the environment sessions on Claude Code and Codex work in.

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


def text(*parts: str) -> Text:
    """Return a stand-in file's text, made of `parts`."""
    return Text(text="".join(parts))


def files(number: int) -> Files | Refused:
    """Return the stand-in files of the approval (54) and the held change (55): Python, TypeScript, TOML, Markdown and JSON, changed, created, and one binary."""
    match number:
        case 54:
            return Files(
                number=number,
                files=[
                    ChangedFile(
                        path=Path("packages/lup-dashboard/page/src/agents.ts"),
                        before=text(AGENTS_HEAD, AGENTS_BEFORE, AGENTS_TAIL),
                        after=text(AGENTS_HEAD, AGENTS_AFTER, AGENTS_TAIL),
                    ),
                    ChangedFile(
                        path=Path("packages/lup-dashboard/src/lup_dashboard/icon.png"),
                        before=None,
                        after=Binary(size=1150),
                    ),
                    ChangedFile(
                        path=Path("packages/lup-dev/pyproject.toml"),
                        before=text(PYPROJECT_HEAD, PYPROJECT_TAIL),
                        after=text(PYPROJECT_HEAD, PYPROJECT_ADDED, PYPROJECT_TAIL),
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
                        after=text(
                            CLI_HEAD,
                            CLI_SHOW_AFTER,
                            CLI_MIDDLE,
                            CLI_PUSH_AFTER,
                            CLI_TAIL,
                        ),
                    ),
                    ChangedFile(
                        path=Path("packages/lup/src/lup/transcripts/views.py"),
                        before=None,
                        after=text(VIEWS),
                    ),
                ],
            )
        case 55:
            return Files(
                number=number,
                files=[
                    ChangedFile(
                        path=Path("AGENTS.md"),
                        before=text(AGENTS_MD_HEAD, AGENTS_MD_BEFORE, AGENTS_MD_TAIL),
                        after=text(AGENTS_MD_HEAD, AGENTS_MD_AFTER, AGENTS_MD_TAIL),
                    ),
                    ChangedFile(
                        path=Path("packages/lup-dashboard/page/package.json"),
                        before=text(PACKAGE_HEAD, PACKAGE_TAIL),
                        after=text(PACKAGE_HEAD, PACKAGE_ADDED, PACKAGE_TAIL),
                    ),
                ],
            )
        case _:
            return Refused(error=f"item {number} changes no file")


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
