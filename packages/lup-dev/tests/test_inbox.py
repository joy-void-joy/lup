"""lup's inbox: items told once, at a call, a turn's end, a held call, a session's start and an idle session's wake; the tools, and the judge's `judged` beside them; `lup-dev inbox`.

The host service serves in a thread of its own, on sockets under the test's
directory, with a stub judge and each runtime's own adapter as its courier. No
agent, no network, no real clock: a held call is known to hold through an event
the delivery sets, and every wait's timeout only ends a test that would
otherwise hang.
"""

import asyncio
import gc
import json
import os
import socket
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NamedTuple, override

import pytest
from mcp import Client
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.types import (
    InitializeResult,
    JSONRPCNotification,
    JSONRPCResponse,
    TextContent,
    ToolAnnotations,
    jsonrpc_message_adapter,
)
from pydantic import Field, TypeAdapter
from typer.testing import CliRunner

from lup import events
from lup.github.serving import GitHubServing
from lup.programs import Ran, run
from lup.rooms import Podman
from lup.tools.serving import Answer as ToolAnswer
from lup.tools.speaking import SPEAKING
from lup_dev import Core, Levels, Modules, Paths, Project, cli, commanding
from lup_dev.adapters.claude import (
    ChannelMessage,
    ClaudeQueues,
    ClaudeRecords,
    ClaudeTranscripts,
)
from lup_dev.approval import Approval as StoredApproval
from lup_dev.codescan.contract import FileReport, Parser, Source
from lup_dev.codescan.engine import EngineError
from lup_dev.commanding import RoomMarks
from lup_dev.conversions import inbox_opened
from lup_dev.declaration.package_managers.uv import Uv
from lup_dev.declaration.resolve import Declaration, resolve
from lup_dev.declaration.serving import Operator as OperatorAsker
from lup_dev.declaration.serving import tools as module_tools
from lup_dev.gate import Passed, Passes, Processes, Standing
from lup_dev.gate import Ran as GateRan
from lup_dev.git import GitError
from lup_dev.host.client import HostClient, RoomClient, Starter
from lup_dev.host.courier import Conversation as Caller
from lup_dev.host.courier import Heard, Posted, Spawned, Spawns
from lup_dev.host.held import Interrupt, Launchers
from lup_dev.host.holders import HeldInterrupt, HeldPrompt, Holders
from lup_dev.host.names import Names, container_name
from lup_dev.host.on_trial import AcceptBranch, DropBranch, TrialSaid
from lup_dev.host.protocol import (
    Branches,
    Holding,
    HostError,
    Limits,
    Register,
    Reply,
    Request,
    ShowHolding,
    Stop,
)
from lup_dev.host.protocol import Done as Finished
from lup_dev.host.pushes import Pushes
from lup_dev.host.records import Called, Queues, Recorded, Said
from lup_dev.host.service import UNDECIDED, HostService, Naming, Program, executed
from lup_dev.host.watch import Changes
from lup_dev.host.workers import (
    LaunchJudge,
    LaunchModules,
    Offered,
    WorkerJudge,
    Workers,
)
from lup_dev.inbox import tools
from lup_dev.inbox.bearings import (
    Repository,
    RepositoryBearings,
    Unlanded,
    read_repository,
)
from lup_dev.inbox.conversion import converted
from lup_dev.inbox.delivery import (
    SEPARATOR,
    Delivery,
    Waking,
    clocked,
)
from lup_dev.inbox.marks import (
    CORE,
    MarksMoved,
    MarkStore,
    MoveMarks,
    Moving,
    StoredMarks,
    seen,
)
from lup_dev.inbox.namesakes import NodeNames
from lup_dev.inbox.notices import Notices, NotifySend
from lup_dev.inbox.parts import PartId, blocks
from lup_dev.inbox.protocol import (
    AnswerApproval,
    AskApproval,
    AskFlag,
    AskHold,
    Context,
    Conversed,
    Drafted,
    Exchanged,
    Files,
    Items,
    KeepDraft,
    KeepOrder,
    KeepTalk,
    ListInbox,
    Listing,
    ListItems,
    Ordered,
    Pathed,
    Reviewed,
    Seen,
    SendDraft,
    SendItem,
    Settled,
    ShowContext,
    ShowConversation,
    ShowDraft,
    ShowFiles,
    ShowGathering,
    Shown,
    ShowOrder,
    ShowTalk,
    Talked,
)
from lup_dev.inbox.reading import Narrowing, Reader, by_agent
from lup_dev.inbox.roster import Roster
from lup_dev.inbox.store import (
    KINDS,
    Answer,
    Answered,
    ApiChanged,
    Approval,
    Binary,
    ChangedFile,
    Comment,
    Decided,
    Decision,
    Done,
    Draft,
    Edit,
    Ended,
    Flagged,
    Found,
    Friction,
    HeldChange,
    HowItFelt,
    Inbox,
    InboxError,
    Item,
    Letter,
    Marked,
    Message,
    Passage,
    Question,
    Quote,
    Quoted,
    Rank,
    Reading,
    Reason,
    Remark,
    Review,
    ReviewedAt,
    Ruling,
    Sent,
    Talk,
    TalkComment,
    Text,
    Told,
    Unresolved,
    Waiting,
    Whereabouts,
    Withdrawn,
    cited,
    item_number,
    ranked,
)
from lup_dev.inbox.store import Asked as Ask
from lup_dev.inbox.store import Stop as Stopped
from lup_dev.inbox.texts import (
    opening,
)
from lup_dev.inbox.threads import spoken
from lup_dev.inbox.tools import Reach, Speaker, specs
from lup_dev.inbox.typed import TypeReader
from lup_dev.launch.room import RoomError
from lup_dev.layout import CopyLayout, GitDirectoryLayout, InboxLayout, Layout
from lup_dev.merging import Merging, gated_commit, merged
from lup_dev.policy import landing as landing_module
from lup_dev.policy import report
from lup_dev.policy.before import Overwrite, Replacement, before
from lup_dev.policy.checkpoint import (
    Bench,
    CallFinished,
    CallStarted,
    ConversationRecord,
    LastDeclaration,
)
from lup_dev.policy.coming import Coming
from lup_dev.policy.flags import InboxFlagging
from lup_dev.policy.holds import Answer as HoldAnswer
from lup_dev.policy.holds import (
    HeldFile,
    Hold,
    Holds,
    InboxAnnouncing,
    Response,
    stores,
)
from lup_dev.policy.landing import LandingTools, Turns, detached, landed_felt
from lup_dev.policy.reviewed import Mark, Reviews
from lup_dev.policy.since import (
    ReviewSince,
    ShowSince,
    Since,
    SincePlace,
    SinceReviewed,
    ViewedFile,
)
from lup_dev.policy.store import Held, Store, WorktreeState
from lup_dev.policy.tools import JudgeTools, stands
from lup_dev.policy.verdicts import Verdict, VerdictLog
from lup_dev.policy.waits import LandingsWaiting, ShowLandings, Wait, Waits
from lup_dev.policy.worktrees import Holding as Worked
from lup_dev.policy.worktrees import SessionIndex
from lup_dev.private.withheld import Withheld
from lup_dev.private.withheld import kept as listed_at
from lup_dev.remote.protocol import Pushed, PushHandler, Pushing, Remotes, Update
from lup_dev.settings import LupDevSettings
from lup_dev.stored import read_model, write_model
from lup_dev.trial import OnTrial, Trial, Trials
from lup_dev.trying import Trying
from lup_dev.worker import HostExchanges, HostMarks, RepositoryModules
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.parties import Conversation, Operator
from lup_ledger.threads import BranchLanded, Check, CommitLanded, Parked, Thread
from lup_ledger.threads import Reopened as ThreadReopened
from lup_transcripts.environment.module import Transcripts

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator

    from conftest import FakeClock, FakeParser, InProcess, JudgingInProcess, Kit, Shell
    from mcp.client._transport import TransportStreams
    from pydantic import JsonValue

    from lup.rooms.engine import Process
    from lup_dev.declaration.kinds import Role
    from lup_dev.layout import HostLayout

runner = CliRunner()


# The host service in a thread of its own, and a session's side of its sockets,
# as `test_host.py` drives them.


class Quiet(LaunchJudge):
    """A launch's judge that answers every hook with nothing."""

    async def judged(self, launch: Register, payload: str) -> str:
        return ""


class Predating(LaunchModules):
    """A repository's process of an approved copy that predates the judge's own tools there: it answers no `judge-call`, refusing it as the dispatcher refuses a kind it has no handler for."""

    async def open(self, launch: Register) -> Offered:
        return Offered()

    async def ask(self, launch: Register, request: Request) -> Reply:
        message = (
            f"no handler for `{request.kind}`; the repository's process answers "
            "judge-hook, module-listing"
        )
        raise HostError(message)

    async def close(self, launch: Register) -> None:
        return None

    async def stop(self) -> None:
        return None


class Background:
    """A service serving in a thread of its own, on its own event loop."""

    def __init__(self, service: HostService) -> None:
        self.service = service
        self.bound = threading.Event()
        self.failure: BaseException | None = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self) -> None:
        async def serve() -> None:
            async with self.service.serving() as serving:
                self.bound.set()
                await serving.stopped.wait()

        try:
            asyncio.run(serve())
        except BaseException as failure:
            self.failure = failure
        finally:
            self.bound.set()


@contextmanager
def served(service: HostService) -> Generator[Background]:
    running = Background(service)
    running.thread.start()
    running.bound.wait()
    if running.failure is not None:
        raise running.failure
    try:
        yield running
    finally:
        if running.thread.is_alive():
            send(service.layout.control, Stop().model_dump_json())
        running.thread.join(timeout=60)
        assert not running.thread.is_alive()


class Unstarted(Starter):
    """Starts nothing: the service runs already."""

    @override
    def start(self, log: Path) -> None:
        message = f"a test's service runs already; nothing logs to {log}"
        raise AssertionError(message)


def client(layout: HostLayout, clock: FakeClock) -> HostClient:
    return HostClient(layout=layout, clock=clock, starter=Unstarted())


def send(path: Path, payload: str) -> str:
    """Send `payload` on the socket at `path`, as the room's hook does, and read back what it tells: nothing where the service decides and tells nothing (`UNDECIDED`, which `test_host.py` checks), as these tests read what a hook tells."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(path))
        connection.sendall(payload.encode())
        connection.shutdown(socket.SHUT_WR)
        with connection.makefile("rb") as stream:
            answer = stream.read().decode()
    return "" if answer == UNDECIDED else answer


@asynccontextmanager
async def bridged(path: Path) -> AsyncGenerator[TransportStreams]:
    """Carry a client's messages over a connection to `path`, one JSON-RPC message a line, as the room's bridge carries them."""
    reader, writer = await asyncio.open_unix_connection(str(path))
    async with create_client_server_memory_streams() as (theirs, ours):
        sent, received = ours

        async def reading() -> None:
            async with received:
                while line := await reader.readline():
                    message = jsonrpc_message_adapter.validate_json(line, by_name=False)
                    await received.send(SessionMessage(message))

        async def writing() -> None:
            async with sent:
                async for item in sent:
                    assert isinstance(item, SessionMessage)
                    line = item.message.model_dump_json(
                        by_alias=True, exclude_unset=True
                    )
                    writer.write(f"{line}\n".encode())
                    await writer.drain()

        tasks = [asyncio.create_task(reading()), asyncio.create_task(writing())]
        try:
            yield theirs
        finally:
            writer.close()
            for task in tasks:
                task.cancel()
            await asyncio.wait(tasks)


def call(path: Path, name: str, arguments: dict[str, JsonValue]) -> tuple[str, bool]:
    """Call the tool `name` through lup's tool server on `path`, as a session would: its text, and whether it's an error."""

    async def called() -> tuple[str, bool]:
        async with Client(bridged(path), mode="legacy") as connected:
            result = await connected.call_tool(name, arguments)
        [content] = result.content
        assert isinstance(content, TextContent)
        return content.text, result.is_error

    return asyncio.run(called())


def claude(event: str, **fields: object) -> str:
    """A Claude Code hook's payload, of session `s1` unless `fields` name another."""
    return json.dumps(
        {"session_id": "s1", "cwd": "/w", "hook_event_name": event, **fields}
    )


class Raised(Notices):
    """Records each desktop notice instead of raising it."""

    def __init__(self) -> None:
        self.raised: list[str] = []
        self.arrived = threading.Event()

    @override
    async def notify(self, summary: str, body: str) -> None:
        self.raised.append(f"{summary}\n{body}")
        self.arrived.set()


class Watched(Delivery):
    """A delivery that says when a call starts holding, so a test acts on a call it knows holds."""

    holding: threading.Event = Field(default_factory=threading.Event)

    @override
    async def held(
        self,
        party: Conversation,
        until: Callable[[], bool],
        *,
        on: list[Waking],
        home: Path | None,
        within: timedelta | None = None,
    ) -> str:
        self.holding.set()
        return await super().held(party, until, on=on, home=home, within=within)


@pytest.fixture
def machine(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    clock: FakeClock,
) -> Layout:
    """lup's state and the host service where the command line places them, outside any session, with the fake clock."""
    xdg = tmp_path_factory.mktemp("xdg")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg / "run"))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg / "state"))
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg / "data"))
    monkeypatch.delenv("CLAUDE_CODE_CHILD_SESSION", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.setattr(cli, "SystemClock", lambda: clock)
    return Layout(
        state=xdg / "state" / "lup",
        runtime=xdg / "run" / "lup",
        data=xdg / "data" / "lup",
    )


@pytest.fixture
def notices() -> Raised:
    return Raised()


@pytest.fixture
def said() -> list[str]:
    return []


@contextmanager
def inboxed(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    recorded: dict[str, Recorded] | None = None,
    *,
    judging: Layout | None = None,
    typed: Callable[[Approval, Path, list[ChangedFile]], list[ChangedFile]]
    | None = None,
    told: Callable[[str], None] | None = None,
    spawns: Spawns | None = None,
    patience: timedelta = timedelta(seconds=30),
    podman: Podman | None = None,
    judge: LaunchJudge | None = None,
    modules: LaunchModules | None = None,
    remotes: Callable[[Delivery], Remotes] | None = None,
    rooms: Callable[[Program], Awaitable[Ran]] | None = None,
    parser: Parser | None = None,
    bearings: bool = False,
    queues: dict[str, Queues] | None = None,
    coming: Callable[[Delivery], Coming] | None = None,
    trying: Callable[[Turns], Trying] | None = None,
    holding: bool = False,
) -> Generator[Watched]:
    """A host service with lup's inbox and the dashboard's kind, its delivery yielded, until the context ends; an item's moment read from `recorded`, the judge's stores from `judging`, or `machine`'s; an approval's types read by `typed`, where given, which tells `told` too; a subagent's spawn read by `spawns`, or by each runtime's adapter; containers asked of `podman`, where given; each hook answered by `judge`, else with nothing, and each launch's modules served by `modules`, where given; `land` pushing through the remotes `remotes` makes over the delivery, where given, else through remotes telling no one, running in a launch's room through `rooms`, reading a file's parse through `parser`, and waking parked threads through what `coming` makes over the delivery, where given; what's on trial moved through what `trying` makes over the landings' turns, where given; a new main session told its bearings where `bearings` asks, its integration branch `dev`; what each runtime holds for a conversation read by `queues`, where given, a held call looking at it, and at its time limit, every few milliseconds."""
    known = cli.Adapters(known=cli.adapters())
    couriers = cli.Couriers(adapters=known)
    wakers = cli.Wakers(adapters=known)
    changes = Changes()
    pushes = Pushes()
    holders = Holders(layout=machine, prompt=wakers.held) if holding else None
    delivery = Watched(
        inbox=inbox_opened(machine, changes),
        waker=wakers,
        pushes=pushes,
        holders=holders,
        layout=machine.host,
        notices=notices,
        clock=clock,
        say=said.append,
        patience=patience,
        queues=queues or {},
        glance=timedelta(milliseconds=5),
    )
    waits = Waits(changes=changes)
    delivery.landing = waits.holding
    if holders is not None:
        holders.interrupted = delivery.interrupted

    def saying(line: str) -> None:
        said.append(line)
        if told is not None:
            told(line)

    turns = Turns()
    landing = LandingTools(
        delivery=delivery,
        layout=judging or machine,
        remotes=(Remotes(say=said.append) if remotes is None else remotes(delivery)),
        waits=waits,
        coming=None if coming is None else coming(delivery),
        turns=turns,
    ).model_copy(
        update={
            **({} if rooms is None else {"run": rooms}),
            **({} if parser is None else {"parser": parser}),
        }
    )
    service = HostService(
        layout=machine.host,
        answerer=known,
        courier=couriers,
        spawns=spawns or cli.SpawnRecords(adapters=known),
        operators={name: each.records for name, each in (recorded or {}).items()},
        post=delivery,
        bearings=(
            RepositoryBearings(delivery=delivery, running=lambda _: "dev")
            if bearings
            else None
        ),
        namesakes=NodeNames(delivery=delivery),
        routes=[
            *cli.control_routes(
                delivery,
                recorded or {},
                None,
                judging or machine,
                waits=waits,
                trying=None if trying is None else trying(turns),
                landing=landing,
            ),
            *(
                []
                if holders is None
                else cli.held_routes(machine, holders, Launchers())
            ),
        ],
        tools=cli.room_tools(
            delivery,
            judging or machine,
            Predating() if modules is None else modules,
            landing=landing,
        ),
        judge=judge or Quiet(),
        modules=modules,
        say=said.append,
        changes=changes,
        waker=wakers,
        pushes=pushes,
        holders=holders,
        podman=podman,
        companions=(
            []
            if typed is None
            else [TypeReader(delivery=delivery, read=typed, say=saying)]
        ),
    )
    with served(service):
        yield delivery


def launched(
    machine: Layout,
    clock: FakeClock,
    tmp_path: Path,
    name: str,
    runtime: str,
    *,
    repository: Path | None = None,
    held: bool = False,
) -> Register:
    """Register a launch of `runtime` in `tmp_path` with the running service, its repository `tmp_path`'s `.git` unless `repository` names another."""
    judge = tmp_path / "judges" / "bin" / "lup-dev"
    judge.parent.mkdir(parents=True, exist_ok=True)
    judge.touch()
    registered = Register(
        launch=name,
        runtime=runtime,
        worktree=tmp_path,
        repository=repository or tmp_path / ".git",
        judge=judge,
        container=f"lup-{name}",
        limits=Limits(actions=["fetch"], protected=[]),
        github=None,
        # The launch's own runtime directory and its home are one place, the
        # one holding the worktree, where a test writes its records.
        home=tmp_path.parent,
        own=tmp_path.parent,
        held=held,
    )
    client(machine.host, clock).register(registered)
    return registered


def bash(call: str, **fields: object) -> str:
    """A Claude Code `Bash` call starting, of session `s1` unless `fields` name another."""
    return claude(
        "PreToolUse",
        tool_name="Bash",
        tool_input={"command": "ls"},
        tool_use_id=call,
        **fields,
    )


def lup_call(
    tool: str, arguments: dict[str, JsonValue], call: str, **fields: object
) -> str:
    """A Claude Code call to one of lup's tools starting."""
    return claude(
        "PreToolUse",
        tool_name=f"mcp__lup__{tool}",
        tool_input=arguments,
        tool_use_id=call,
        **fields,
    )


def codex(event: str, **fields: object) -> str:
    """A Codex hook's payload, of session `t1`."""
    return json.dumps(
        {"session_id": "t1", "cwd": "/w", "hook_event_name": event, **fields}
    )


def context(answer: str) -> str:
    """What a hook's answer tells the model beside its call or its start, the line naming a session at its start left out."""
    told = json.loads(answer)["hookSpecificOutput"]["additionalContext"]
    assert isinstance(told, str)
    if "sessions call you. Once you know" not in told.partition("\n\n")[0]:
        return told
    return told.partition("\n\n")[2]


def inbox(*arguments: str) -> str:
    """Run `lup-dev inbox` with `arguments`, and return what it printed."""
    result = runner.invoke(cli.app, ["inbox", *arguments])
    assert result.exit_code == 0, (result.output, result.exception)
    return result.output


def refused(*arguments: str) -> str:
    """Run `lup-dev inbox` with `arguments`, which the service refuses, and return why."""
    result = runner.invoke(cli.app, ["inbox", *arguments])
    assert isinstance(result.exception, HostError), (result.output, result.exception)
    return str(result.exception)


def note(number: int, text: str) -> str:
    """How item `number`, the operator's note of one line, is told."""
    return f'<message item="{number}" from="operator" kind="note">{text}</message>'


# An item's number is read from the ledger, as the act that made it left it, and
# never written as a literal: the ledger numbers every node of every repository
# from one sequence, so a literal would test how many nodes other work makes.


def newest(delivery: Delivery) -> int:
    """The number of the item the inbox made last: read just after the act that made it, it's that item's."""
    return max(delivery.inbox.items)


def numbers(delivery: Delivery) -> list[int]:
    """The numbers of the items the inbox holds, in the order made: unpacked where an act makes several, so each is named by what it is."""
    return sorted(delivery.inbox.items)


def answer_to(answer: int, question: int, asked: str, comment: str) -> str:
    """How item `answer`, the operator's answer in words to question `question`, which asked `asked`, is told."""
    return (
        f'<answer item="{answer}" from="operator" question="{question}">\n'
        f'<asked>{asked}</asked>\n<comment id="{answer}.1">{comment}</comment>\n'
        "</answer>"
    )


def test_an_item_is_told_at_the_conversations_next_call_and_never_again(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        started = json.loads(send(hook, claude("SessionStart", source="startup")))
        assert started["hookSpecificOutput"]["additionalContext"].startswith(
            "lup: you're `"
        )
        sent = inbox("send", "one", "Look at the cache.")
        number = newest(delivery)
        told = send(hook, bash("b1"))
        again = send(hook, bash("b2"))
        item = delivery.inbox.item(number)
    assert sent == f"Sent @{number} to `{tmp_path.name}`.\n"
    assert context(told) == note(number, "Look at the cache.")
    assert again == ""
    assert item.state == Told(at=clock.now(), how="call")
    assert item.recipient == Conversation(
        repository=tmp_path / ".git", runtime="claude", session="s1"
    )


def test_items_waiting_are_told_together_oldest_first_as_a_session_resumes(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        inbox("send", "one", "First.")
        first = newest(delivery)
        inbox("send", "one", "Second.")
        second = newest(delivery)
        resumed = send(hook, claude("SessionStart", source="resume"))
    assert context(resumed) == (f"{note(first, 'First.')}\n\n{note(second, 'Second.')}")


def test_a_turns_end_holds_once_and_a_later_end_with_nothing_new_ends_at_once(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        inbox("send", "one", "Before you stop.")
        number = newest(delivery)
        held = json.loads(send(hook, claude("Stop", stop_hook_active=False)))
        let = send(hook, claude("Stop", stop_hook_active=True))
        later = send(hook, claude("Stop", stop_hook_active=False))
        item = delivery.inbox.item(number)
    assert held == {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": note(number, "Before you stop."),
        }
    }
    assert item.state == Told(at=clock.now(), how="turn's end")
    assert let == ""
    assert later == ""


def test_an_end_following_a_hold_ends_and_what_came_meanwhile_waits_for_a_call(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        inbox("send", "one", "One.")
        assert context(send(hook, claude("Stop"))) == note(newest(delivery), "One.")
        inbox("send", "one", "Two.")
        two = newest(delivery)
        let = send(hook, claude("Stop", stop_hook_active=True))
        told = send(hook, bash("b1"))
    assert let == ""
    assert context(told) == note(two, "Two.")


def test_a_subagents_end_holds_once_on_what_waits_for_it(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        arguments = json.loads(
            send(
                hook,
                lup_call(
                    "ask",
                    {"question": "May I?"},
                    "q1",
                    agent_id="a1",
                    agent_type="general-purpose",
                ),
            )
        )["hookSpecificOutput"]["updatedInput"]
        call(machine.host.launch("one").mcp, "ask", arguments)
        question = newest(delivery)
        inbox("answer", str(question), "--comment", "Yes.")
        answer = newest(delivery)
        ending = {
            "agent_id": "a1",
            "agent_type": "general-purpose",
            "last_assistant_message": "Asked.",
        }
        held = send(hook, claude("SubagentStop", stop_hook_active=False, **ending))
        let = send(hook, claude("SubagentStop", stop_hook_active=True, **ending))
    assert json.loads(held)["hookSpecificOutput"]["hookEventName"] == "SubagentStop"
    assert context(held) == answer_to(answer, question, "May I?", "Yes.")
    assert let == ""


def test_wait_inbox_holds_until_something_arrives_and_returns_it_whole(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(
                call, machine.host.launch("one").mcp, "wait_inbox", {}
            )
            assert delivery.holding.wait(timeout=60)
            inbox("send", "one", "Here it is.")
            number = newest(delivery)
            returned = waiting.result(timeout=60)
        after = send(hook, bash("b1"))
        item = delivery.inbox.item(number)
    assert returned == (note(number, "Here it is."), False)
    assert item.state == Told(at=clock.now(), how="held call")
    assert after == ""


def test_a_call_to_lups_tools_tells_nothing_at_its_start_and_its_result_does(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        inbox("send", "one", "Already here.")
        number = newest(delivery)
        started = json.loads(send(hook, lup_call("wait_inbox", {}, "w1")))
        returned = call(
            machine.host.launch("one").mcp,
            "wait_inbox",
            started["hookSpecificOutput"]["updatedInput"],
        )
    assert "additionalContext" not in started["hookSpecificOutput"]
    assert returned == (note(number, "Already here."), False)


# What a Claude Code session's runtime holds for each of their conversations, as
# its records say (`docs/field-notes.md`, *What a session holds queued*): the
# tests write the records, laid out as Claude Code lays out its home.


def appended(path: Path, *lines: dict[str, JsonValue]) -> None:
    """Add `lines` to the record at `path`, as Claude Code writes them, each whole."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as written:
        written.writelines(f"{json.dumps(each)}\n" for each in lines)


def enqueued(content: str) -> dict[str, JsonValue]:
    """A line of a session's record saying Claude Code queued `content` for them."""
    return {
        "type": "queue-operation",
        "operation": "enqueue",
        "timestamp": "2026-10-01T12:00:00.000Z",
        "sessionId": "s1",
        "content": content,
    }


def background(call: str, **result: JsonValue) -> dict[str, JsonValue]:
    """A line of a conversation's record carrying the result of their call `call`, which says what the call started in the background."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": call, "content": ""}],
        },
        "toolUseResult": result,
    }


def notified(task: str, call: str, summary: str) -> str:
    """A task notification, as Claude Code queues one for a task's end."""
    return (
        f"<task-notification>\n<task-id>{task}</task-id>\n"
        f"<tool-use-id>{call}</tool-use-id>\n<status>completed</status>\n"
        f"<summary>{summary}</summary>\n</task-notification>"
    )


def holding(kind: str, line: str, attributes: str = "") -> str:
    """What a held call says of one thing its runtime holds for it."""
    return (
        '<queued from="your runtime">\n'
        f'<waiting kind="{kind}"{attributes}>{line}</waiting>\n'
        "It reaches you from your runtime as this call returns.\n</queued>"
    )


TYPED_WORDS = holding(
    "typed", "Their words, typed in your terminal.", ' from="operator"'
)
"""What a held call says of the operator's words typed in its terminal."""


def queued_in(home: Path) -> dict[str, Queues]:
    """What Claude Code holds for each conversation, read from its home at `home`, which the test's launch registers as its own (`launched` at `home / "w"`)."""
    return {"claude": ClaudeQueues(records=ClaudeRecords(directory=home))}


def test_wait_inbox_returns_for_the_operator_s_typed_words_whatever_on_says(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    home = tmp_path / ".claude"
    records = Subagents(home / "projects")
    with inboxed(machine, clock, notices, said, queues=queued_in(home)) as delivery:
        launched(machine, clock, home / "w", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(call, mcp, "wait_inbox", {"on": ["tasks"]})
            assert delivery.holding.wait(timeout=60)
            appended(records.transcript, enqueued("Stop the gate, it hangs."))
            returned = waiting.result(timeout=60)
    assert returned == (TYPED_WORDS, False)


def test_wait_inbox_reads_no_queue_of_a_session_its_room_claims_from_another_home(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """A room's hook names whatever session it likes, a host session's or another project's room's among them: a held call reads its conversation's queue in the home its own launch registered alone, so what another session's runtime holds never reaches it."""
    operators = tmp_path / "claude"
    gate = 'Background command "gate" completed (exit code 0)'
    for home, session in [(operators, "s9"), (tmp_path / "b", "s8")]:
        appended(
            home / "projects" / "-w" / f"{session}.jsonl",
            background("m1", backgroundTaskId="b1"),
            {**enqueued(notified("b1", "m1", gate)), "sessionId": session},
        )
    records = ClaudeRecords(directory=operators, host=machine.host)
    recorded = {"claude": Recorded(records=records, reader=ClaudeTranscripts())}
    queues: dict[str, Queues] = {"claude": ClaudeQueues(records=records)}
    with inboxed(machine, clock, notices, said, recorded, queues=queues) as delivery:
        launched(machine, clock, tmp_path / "a" / "w", "one", "claude")
        launched(machine, clock, tmp_path / "b" / "w", "two", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(machine.host.launch("two").hook, claude("SessionStart", session_id="s8"))
        returned: list[tuple[str, bool]] = []
        for session in ["s9", "s8"]:
            send(hook, claude("SessionStart", source="startup", session_id=session))
            waiting: dict[str, JsonValue] = {"within": "PT1M"}
            calling = lup_call(
                "wait_inbox", waiting, f"w-{session}", session_id=session
            )
            stamped = json.loads(send(hook, calling))["hookSpecificOutput"][
                "updatedInput"
            ]
            with ThreadPoolExecutor(max_workers=1) as pool:
                delivery.holding.clear()
                held = pool.submit(call, mcp, "wait_inbox", stamped)
                assert delivery.holding.wait(timeout=60)
                clock.sleep(60)
                returned.append(held.result(timeout=60))
    assert returned == [
        ("Nothing reached you within PT1M, this call's `within`.", False),
        ("Nothing reached you within PT1M, this call's `within`.", False),
    ]


def test_wait_inbox_returns_for_a_task_of_its_own_and_never_for_its_subagent_s(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    home = tmp_path / ".claude"
    records = Subagents(home / "projects")
    gate = 'Background command "gate" completed (exit code 0)'
    probe = 'Background command "probe" completed (exit code 0)'
    with inboxed(machine, clock, notices, said, queues=queued_in(home)) as delivery:
        launched(machine, clock, home / "w", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        sockets = (hook, mcp)
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "general-purpose", "t1", name="parser")
        send(hook, records.call("a1", "general-purpose", "c1"))
        appended(records.transcript, background("m1", backgroundTaskId="b1"))
        appended(
            records.folder / "agent-a1.jsonl",
            {**background("c2", backgroundTaskId="b2"), "isSidechain": True},
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            waiting = pool.submit(call, mcp, "wait_inbox", {})
            assert delivery.holding.wait(timeout=60)
            appended(records.transcript, enqueued(notified("b2", "c2", probe)))
            theirs = pool.submit(
                records.lup, sockets, "wait_inbox", {}, "a1", "general-purpose"
            ).result(timeout=60)
            # The subagent's task is told to them alone: the session's own call
            # holds through it, until its own task ends.
            appended(records.transcript, enqueued(notified("b1", "m1", gate)))
            returned = waiting.result(timeout=60)
    assert theirs == (holding("task", probe), False)
    assert returned == (holding("task", gate), False)


def test_wait_inbox_on_the_operator_alone_holds_through_a_subagent_s_message(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        send(hook, records.call("a1", "Explore", "c1"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(call, mcp, "wait_inbox", {"on": ["operator"]})
            assert delivery.holding.wait(timeout=60)
            records.lup((hook, mcp), "send", to_parent("Found it."), "a1", "Explore")
            inbox("send", "one", "Here it is.")
            returned = waiting.result(timeout=60)
        # The subagent's message, the operator's copy of it, and the operator's note.
        message, _, sent = numbers(delivery)
        items = [delivery.inbox.item(number) for number in [message, sent]]
    assert returned == (
        f"{delivery.said(items[0])}{SEPARATOR}{note(sent, 'Here it is.')}",
        False,
    )
    assert [each.state for each in items] == [
        Told(at=clock.now(), how="held call"),
        Told(at=clock.now(), how="held call"),
    ]


def waited_within(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
    *,
    runtime: str,
) -> tuple[str, bool]:
    """Call `wait_inbox` with a `within` of five minutes from a session of `runtime`, and return what it returned once the clock moved past it."""
    starting = claude if runtime == "claude" else codex
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", runtime)
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, starting("SessionStart", source="startup"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(call, mcp, "wait_inbox", {"within": "PT5M"})
            assert delivery.holding.wait(timeout=60)
            clock.sleep(300)
            return waiting.result(timeout=60)


NOTHING_CAME = ("Nothing reached you within PT5M, this call's `within`.", False)
"""What `wait_inbox` returns once its `within` of five minutes passed."""


def test_wait_inbox_within_a_time_returns_saying_nothing_came_on_claude_code(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    waited = waited_within(machine, clock, notices, said, tmp_path, runtime="claude")
    assert waited == NOTHING_CAME


def test_wait_inbox_within_a_time_returns_saying_nothing_came_on_codex(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    waited = waited_within(machine, clock, notices, said, tmp_path, runtime="codex")
    assert waited == NOTHING_CAME


def test_what_the_runtime_holds_is_told_by_one_held_call(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    home = tmp_path / ".claude"
    records = Subagents(home / "projects")
    with inboxed(machine, clock, notices, said, queues=queued_in(home)) as delivery:
        launched(machine, clock, home / "w", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        appended(records.transcript, enqueued("Stop the gate, it hangs."))
        first = call(mcp, "wait_inbox", {})
        # Still in the record, as its runtime hands it over once the call has
        # returned: the next call holds through it.
        with ThreadPoolExecutor(max_workers=1) as pool:
            delivery.holding.clear()
            waiting = pool.submit(call, mcp, "wait_inbox", {"within": "PT1M"})
            assert delivery.holding.wait(timeout=60)
            clock.sleep(60)
            second = waiting.result(timeout=60)
    assert first == (TYPED_WORDS, False)
    assert second == ("Nothing reached you within PT1M, this call's `within`.", False)


def test_ask_with_wait_returns_for_the_operator_s_typed_words_its_question_open(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    home = tmp_path / ".claude"
    records = Subagents(home / "projects")
    asking: dict[str, JsonValue] = {"question": "Which parser?", "wait": True}
    with inboxed(machine, clock, notices, said, queues=queued_in(home)) as delivery:
        launched(machine, clock, home / "w", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(call, mcp, "ask", asking)
            assert delivery.holding.wait(timeout=60)
            appended(records.transcript, enqueued("Lark. I'll answer properly later."))
            returned = waiting.result(timeout=60)
        number = newest(delivery)
        question = delivery.inbox.item(number)
    assert isinstance(question.reason, Question)
    assert returned == (
        (
            f"{TYPED_WORDS}\n\nYour question @{number} is still open: its answer reaches "
            "you at a later call; `wait_inbox` waits for it."
        ),
        False,
    )
    assert question.state == Waiting()


def test_a_question_held_for_its_answer_reaches_a_watch_of_the_inbox_at_once(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    question: dict[str, JsonValue] = {"question": "Which parser?", "wait": True}
    with (
        inboxed(machine, clock, notices, said) as delivery,
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as watch,
    ):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        watch.settimeout(60)
        watch.connect(str(machine.host.watch))
        watch.sendall(f"{ListInbox().model_dump_json()}\n".encode())
        with (
            watch.makefile("rb") as following,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            empty = Items.model_validate_json(following.readline())
            asking = pool.submit(call, machine.host.launch("one").mcp, "ask", question)
            held = Items.model_validate_json(following.readline())
            inbox("answer", str(newest(delivery)), "--comment", "Lark.")
            answered = Items.model_validate_json(following.readline())
            asking.result(timeout=60)
    assert empty.items == []
    assert [opening(each) for each in held.items] == ["Which parser?"]
    assert answered.items == []


def test_ask_with_wait_holds_until_the_operator_answers_each_decision(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    question: dict[str, JsonValue] = {
        "question": "Which parser?",
        "decisions": [
            {"decision": "Parse with lark", "lean": "yes, it's typed"},
            {"decision": "Keep the cache", "lean": "no"},
        ],
        "wait": True,
    }
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            asking = pool.submit(call, machine.host.launch("one").mcp, "ask", question)
            assert notices.arrived.wait(timeout=60)
            number = newest(delivery)
            listed = inbox()
            shown = inbox("show", str(number))
            answered = inbox(
                "answer",
                str(number),
                "--leaning",
                "1",
                "--undecided",
                "2",
                "--comment",
                "Go.",
            )
            answer = newest(delivery)
            returned = asking.result(timeout=60)
        asked = delivery.inbox.item(number)
    assert listed == (
        f"{cited(number):>5}  2026-10-01 12:00  a question from `{tmp_path.name}` "
        f"in {tmp_path}: "
        "Which parser?\n"
    )
    assert shown == (
        f"@{number}, a question from `{tmp_path.name}` in {tmp_path} to the operator, "
        "made 2026-10-01 12:00, waiting:\nWhich parser?\n"
        "1. Parse with lark\n   Its lean: yes, it's typed\n"
        "2. Keep the cache\n   Its lean: no\n"
    )
    assert answered == (
        f"Answered @{number}: your answer, @{answer}, is for `{tmp_path.name}`.\n"
    )
    # A decision's number is its place in the question, not an item's.
    assert returned == (
        (
            f'<answer item="{answer}" from="operator" question="{number}">\n'
            "<asked>Which parser?</asked>\n"
            '<decision number="1" lean="yes, it\'s typed" verdict="leaning: they go '
            f'with the lean" id="{answer}.1">Parse with lark</decision>\n'
            '<decision number="2" lean="no" verdict="undecided" '
            f'id="{answer}.2">Keep the cache</decision>\n'
            f'<comment id="{answer}.3">Go.</comment>\n'
            "</answer>"
        ),
        False,
    )
    assert asked.state == Answered(at=clock.now(), answer=answer)
    assert notices.raised == [
        (
            f"lup: a question from `{tmp_path.name}` in {tmp_path}\n"
            f"Which parser?\nlup-dev inbox show {number}"
        )
    ]


def test_ask_without_wait_returns_at_once_and_the_answer_comes_at_a_call(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        returned = call(machine.host.launch("one").mcp, "ask", {"question": "Why?"})
        question = newest(delivery)
        inbox("answer", str(question), "--comment", "Because.")
        answer = newest(delivery)
        told = send(hook, bash("b1"))
    assert returned == (
        (
            f"Your question is with the operator, @{question}. Their answer reaches "
            "you at a later call; `wait_inbox` waits for it."
        ),
        False,
    )
    assert context(told) == answer_to(answer, question, "Why?", "Because.")


def test_an_ask_sent_again_across_a_restart_finds_its_question_and_asks_no_second(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        mcp = machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        questions: list[dict[str, JsonValue]] = [
            {"question": "Which parser?", "wait": True},
            {"question": "Which cache?", "wait": True},
            {"question": "Why?"},
        ]
        asks = [
            json.loads(send(hook, lup_call("ask", question, f"q{at}")))[
                "hookSpecificOutput"
            ]["updatedInput"]
            for at, question in enumerate(questions, start=1)
        ]
        # Answered while the service was away: the call sent again returns at once.
        dropped(mcp, "ask", asks[0], delivery.holding)
        parser = newest(delivery)
        inbox("answer", str(parser), "--comment", "Lark.")
        lark = newest(delivery)
        answered = call(mcp, "ask", asks[0])
        # Still waiting: the call sent again holds on the same question.
        dropped(mcp, "ask", asks[1], delivery.holding)
        cache = newest(delivery)
        with ThreadPoolExecutor(max_workers=1) as pool:
            delivery.holding.clear()
            asking = pool.submit(call, mcp, "ask", asks[1])
            assert delivery.holding.wait(timeout=60)
            inbox("answer", str(cache), "--comment", "None.")
            none = newest(delivery)
            held = asking.result(timeout=60)
        # Without `wait`, sent again, it makes no second question either.
        once = call(mcp, "ask", asks[2])
        why = newest(delivery)
        twice = call(mcp, "ask", asks[2])
        asked = [
            (item.number, item.call)
            for item in delivery.inbox.items.values()
            if isinstance(item.reason, Question)
        ]
    assert answered == (answer_to(lark, parser, "Which parser?", "Lark."), False)
    assert held == (answer_to(none, cache, "Which cache?", "None."), False)
    assert once == twice
    assert once[0].startswith(f"Your question is with the operator, @{why}.")
    assert asked == [(parser, "q1"), (cache, "q2"), (why, "q3")]


class Socket:
    """A stand-in for a session's messaging socket: every line written to it, one connection each."""

    def __init__(self, path: Path) -> None:
        self.frames: list[str] = []
        self.rang = threading.Event()
        self.listening = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listening.bind(str(path))
        self.listening.listen()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self) -> None:
        while True:
            try:
                connection, _ = self.listening.accept()
            except OSError:
                return
            with connection, connection.makefile("rb") as stream:
                self.frames.append(stream.read().decode())
            self.rang.set()

    def ringing(self) -> list[str]:
        """Wait for a frame, and return every frame written so far."""
        assert self.rang.wait(timeout=60)
        return self.frames

    def close(self) -> list[str]:
        """Stop listening, and return every frame written."""
        self.listening.shutdown(socket.SHUT_RDWR)
        self.listening.close()
        self.thread.join(timeout=60)
        return self.frames


def test_an_idle_session_is_woken_once_through_its_messaging_socket(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        send(hook, claude("SessionStart", source="startup"))
        assert send(hook, claude("Stop", stop_hook_active=False)) == ""
        inbox("send", "one", "Wake up.")
        wake = newest(delivery)
        inbox("send", "one", "And this.")
        this = newest(delivery)
        told = send(hook, bash("b1"))
        woken = delivery.inbox.item(wake)
        frames = messages.close()
    assert [json.loads(frame) for frame in frames] == [
        {
            "type": "user",
            "message": {"role": "user", "content": bell(wake)},
            "session_id": "s1",
        }
    ]
    assert frames[0].endswith("\n")
    # The doorbell carries no item: they stay waiting, and the next call tells both.
    assert woken.state == Told(at=clock.now(), how="call")
    assert context(told) == f"{note(wake, 'Wake up.')}\n\n{note(this, 'And this.')}"
    assert f"one: woke `{tmp_path.name}` for @{wake}" in said


def bell(number: int) -> str:
    """The doorbell a wake rings for one note from the operator, item `number`."""
    return (
        '<doorbell from="lup\'s inbox">\n'
        f'<waiting item="{number}" kind="note" from="operator"/>\n'
        "Call `wait_inbox` to read it: what's in your inbox comes through lup's own "
        "tools, never in a message like this one.\n"
        "</doorbell>"
    )


def test_after_the_doorbell_wait_inbox_returns_what_waits_whole(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        send(hook, claude("SessionStart", source="startup"))
        send(hook, claude("Stop", stop_hook_active=False))
        inbox("send", "one", "Read me through lup.")
        number = newest(delivery)
        stamped = json.loads(send(hook, lup_call("wait_inbox", {}, "w1")))[
            "hookSpecificOutput"
        ]["updatedInput"]
        returned = call(machine.host.launch("one").mcp, "wait_inbox", stamped)
        item = delivery.inbox.item(number)
        frames = messages.close()
    assert frames_of(frames) == [bell(number)]
    assert returned == (note(number, "Read me through lup."), False)
    assert item.state == Told(at=clock.now(), how="held call")


def frames_of(written: list[str]) -> list[str]:
    """The text each frame written to a messaging socket carries."""
    return [json.loads(frame)["message"]["content"] for frame in written]


def test_a_session_that_just_started_is_woken(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        send(hook, claude("SessionStart", source="startup"))
        inbox("send", "one", "Before your first turn.")
        number = newest(delivery)
        frames = messages.close()
    assert frames_of(frames) == [bell(number)]


def test_a_session_in_its_turn_is_told_at_its_hooks_and_never_woken(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        send(hook, claude("SessionStart", source="startup"))
        send(hook, bash("b1"))
        inbox("send", "one", "While you run.")
        running = newest(delivery)
        finished = send(
            hook,
            claude(
                "PostToolUse",
                tool_name="Bash",
                tool_input={"command": "ls"},
                tool_use_id="b1",
                tool_response={"stdout": ""},
            ),
        )
        inbox("send", "one", "Between calls.")
        between = newest(delivery)
        ended = send(hook, claude("Stop", stop_hook_active=False))
        frames = messages.close()
    assert context(finished) == note(running, "While you run.")
    assert json.loads(ended) == {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": note(between, "Between calls."),
        }
    }
    assert frames == []


def test_a_service_started_again_wakes_a_session_it_hasn_t_heard_since(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, bash("b1"))
    with inboxed(machine, clock, notices, said) as delivery:
        messages = Socket(machine.host.launch("one").messages)
        inbox("send", "one", "After a restart.")
        number = newest(delivery)
        frames = messages.close()
    assert frames_of(frames) == [bell(number)]


def test_two_launches_in_one_worktree_each_wake_through_their_own_socket(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        launched(machine, clock, tmp_path, "two", "claude")
        first = Socket(machine.host.launch("one").messages)
        second = Socket(machine.host.launch("two").messages)
        send(machine.host.launch("one").hook, claude("SessionStart", session_id="s1"))
        send(machine.host.launch("two").hook, claude("SessionStart", session_id="s2"))
        inbox("send", "one", "For one.")
        for_one = newest(delivery)
        inbox("send", "two", "For two.")
        for_two = newest(delivery)
        to_first = first.close()
        to_second = second.close()
    assert machine.host.launch("one").messages != machine.host.launch("two").messages
    assert frames_of(to_first) == [bell(for_one)]
    assert frames_of(to_second) == [bell(for_two)]
    assert [json.loads(each)["session_id"] for each in [*to_first, *to_second]] == [
        "s1",
        "s2",
    ]


def test_an_idle_session_whose_socket_is_gone_is_told_at_its_next_call(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook, claude("Stop", stop_hook_active=False))
        inbox("send", "one", "Nobody's there.")
        number = newest(delivery)
        told = send(hook, bash("b1"))
    assert context(told) == note(number, "Nobody's there.")
    assert any(f"`{tmp_path.name}` wasn't woken through" in each for each in said)


class Session:
    """A stand-in for a session's connection to lup's tool server, held open as its bridge holds it: what the server declared, and each notice it pushes."""

    def __init__(self, path: Path) -> None:
        self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connection.settimeout(60)
        self.connection.connect(str(path))
        self.lines = self.connection.makefile("rb")
        self.said(INITIALIZE)
        answer = jsonrpc_message_adapter.validate_json(self.lines.readline())
        assert isinstance(answer, JSONRPCResponse)
        self.introduced = InitializeResult.model_validate(answer.result)
        self.said({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def said(self, message: dict[str, JsonValue]) -> None:
        self.connection.sendall(f"{json.dumps(message)}\n".encode())

    def pushed(self) -> JSONRPCNotification:
        """Read the next notice the server pushes."""
        notice = jsonrpc_message_adapter.validate_json(self.lines.readline())
        assert isinstance(notice, JSONRPCNotification)
        return notice

    def quiet(self) -> bool:
        """Say whether nothing more is pushed for a moment."""
        self.connection.settimeout(0.2)
        try:
            return self.lines.readline() == b""
        except TimeoutError:
            return True
        finally:
            self.connection.settimeout(60)

    def close(self) -> None:
        self.lines.close()
        self.connection.close()


INITIALIZE: dict[str, JsonValue] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "claude-code", "version": "2.1.304"},
    },
}
"""A session introducing themselves to lup's tool server, on the handshake revision."""


def dropped(
    path: Path, name: str, arguments: dict[str, JsonValue], holding: threading.Event
) -> None:
    """Call the tool `name` through lup's tool server on `path`, and close the connection once the call holds, as the bridge's connection closes when the service restarts: the service cancels the call, and the bridge sends it again on a new connection."""
    holding.clear()
    session = Session(path)
    session.said(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert holding.wait(timeout=60)
    session.close()


def channel(content: str, token: str) -> str:
    """The prompt a Claude Code session's turn starts on when they take a channel's message (`docs/field-notes.md`, *Channels*)."""
    return f'<channel source="lup" wake="{token}">\n{content}\n</channel>'


def test_an_idle_claude_session_is_pushed_what_waits_and_takes_it_at_its_turns_start(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        session = Session(machine.host.launch("one").mcp)
        started = send(hook, claude("SessionStart", source="startup"))
        _, title = named_at_start(started)
        assert send(hook, claude("Stop", stop_hook_active=False)) == ""
        inbox("send", "one", "Wake up.")
        number = newest(delivery)
        notice = session.pushed()
        pushed = ChannelMessage.model_validate(notice.params)
        pending = delivery.inbox.item(number).state
        # A hook while the push is pending tells nothing of it.
        between = send(
            hook,
            claude("UserPromptSubmit", prompt="Typed meanwhile.", session_title=title),
        )
        token = pushed.meta["wake"]
        taken = send(
            hook,
            claude(
                "UserPromptSubmit",
                prompt=channel(pushed.content, token),
                session_title=title,
            ),
        )
        state = delivery.inbox.item(number).state
        after = send(hook, bash("b1"))
        session.close()
        frames = messages.close()
    assert session.introduced.capabilities.experimental == {"claude/channel": {}}
    assert notice.method == "notifications/claude/channel"
    # The items themselves, told once: no `wait_inbox`, and no doorbell.
    assert pushed.content == note(number, "Wake up.")
    assert pending == Waiting()
    assert between == ""
    assert state == Told(at=clock.now(), how="wake")
    assert taken == ""
    assert after == ""
    assert frames == []
    assert f"one: pushed @{number} to `{tmp_path.name}`" in said


def until(condition: Callable[[], bool]) -> bool:
    """Say whether `condition` comes to hold within a minute, as what the service does on its own thread comes to pass."""
    for _ in range(6000):
        if condition():
            return True
        time.sleep(0.01)
    return False


class Launcher(Socket):
    """A stand-in for a held launch's launcher: each request read whole, and done."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(path)

    @override
    def serve(self) -> None:
        while True:
            try:
                connection, _ = self.listening.accept()
            except OSError:
                return
            with connection, connection.makefile("rb") as stream:
                self.frames.append(stream.read().decode())
                connection.sendall(b'{"kind": "done"}')
            self.rang.set()


def test_an_idle_held_session_is_given_what_waits_through_its_launcher_and_takes_it_at_its_turns_start(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said, holding=True) as delivery:
        launched(machine, clock, tmp_path, "one", "claude", held=True)
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        launcher = Launcher(machine.launch("one").held)
        started = send(hook, claude("SessionStart", source="startup"))
        _, title = named_at_start(started)
        assert send(hook, claude("Stop", stop_hook_active=False)) == ""
        inbox("send", "one", "Wake up.")
        number = newest(delivery)
        [given] = launcher.ringing()
        prompt = HeldPrompt.model_validate_json(given)
        pending = delivery.inbox.item(number).state
        taken = send(
            hook,
            claude("UserPromptSubmit", prompt=prompt.text, session_title=title),
        )
        state = delivery.inbox.item(number).state
        after = send(hook, bash("b1"))
        launcher.close()
        frames = messages.close()
    # The items themselves, wrapped as a channel's message is, told once.
    content, _, rest = prompt.text.partition("\n")
    assert content.startswith('<channel source="lup" wake="')
    assert rest == f"{note(number, 'Wake up.')}\n</channel>"
    assert pending == Waiting()
    assert state == Told(at=clock.now(), how="wake")
    assert taken == ""
    assert after == ""
    assert frames == []
    assert f"one: gave @{number} to `{tmp_path.name}`, held" in said


def test_a_held_session_whose_launcher_can_t_be_reached_is_told_at_its_next_call(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said, holding=True) as delivery:
        launched(machine, clock, tmp_path, "one", "claude", held=True)
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook, claude("Stop", stop_hook_active=False))
        inbox("send", "one", "Anyone?")
        number = newest(delivery)
        state = delivery.inbox.item(number).state
        told = send(hook, bash("b1"))
    assert state == Waiting()
    assert context(told) == note(number, "Anyone?")
    assert any(
        line.startswith(
            f"one: what waits for `{tmp_path.name}` wasn't given their held "
            "session, so it's told at their next call: launch `one`'s launcher"
        )
        for line in said
    )


def test_an_interrupt_through_lup_takes_the_held_session_for_idle_and_gives_it_what_came(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said, holding=True) as delivery:
        launched(machine, clock, tmp_path, "one", "claude", held=True)
        hook = machine.host.launch("one").hook
        launcher = Launcher(machine.launch("one").held)
        send(hook, claude("SessionStart", source="startup"))
        send(hook, bash("b1"))
        inbox("send", "one", "Stop that.")
        number = newest(delivery)
        before = list(launcher.frames)
        client(machine.host, clock).ask(Interrupt(launch="one"), Finished)
        until(lambda: len(launcher.frames) == 2)
        frames = launcher.close()
    # Busy, nothing was given; interrupted, what came during the turn is.
    assert before == []
    interrupt, given = frames
    assert interrupt == HeldInterrupt().model_dump_json()
    assert note(number, "Stop that.") in HeldPrompt.model_validate_json(given).text


def test_what_a_held_session_is_given_mid_call_is_told_once_as_its_turn_takes_it(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """After a restart of the service, a session mid-call is taken for idle and given a turn, which it reads only once its call ends, however long that takes: no hook tells it meanwhile."""
    with inboxed(
        machine, clock, notices, said, holding=True, patience=timedelta(0)
    ) as delivery:
        launched(machine, clock, tmp_path, "one", "claude", held=True)
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        launcher = Launcher(machine.launch("one").held)
        started = send(hook, claude("SessionStart", source="startup"))
        _, title = named_at_start(started)
        inbox("send", "one", "Anyone?")
        number = newest(delivery)
        [given] = launcher.ringing()
        prompt = HeldPrompt.model_validate_json(given).text
        during = [
            send(hook, bash("b1")),
            send(hook, claude("PostToolUse", tool_name="Bash", tool_use_id="b1")),
        ]
        pending = delivery.inbox.item(number).state
        taken = send(
            hook, claude("UserPromptSubmit", prompt=prompt, session_title=title)
        )
        state = delivery.inbox.item(number).state
        launcher.close()
        frames = messages.close()
    assert during == ["", ""]
    assert pending == Waiting()
    assert taken == ""
    assert state == Told(at=clock.now(), how="wake")
    assert frames == []


def test_an_interrupt_lets_go_a_wait_inbox_it_cut_and_gives_the_held_session_what_came(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """The cut doesn't reach lup's hold here, as it may not on the real runtime: the hold is taken for ended all the same, so the words that come after reach the session, rather than a call nobody reads."""
    with inboxed(machine, clock, notices, said, holding=True) as delivery:
        launched(machine, clock, tmp_path, "one", "claude", held=True)
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        launcher = Launcher(machine.launch("one").held)
        send(hook, claude("SessionStart", source="startup"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(call, mcp, "wait_inbox", {"within": "PT5M"})
            assert delivery.holding.wait(timeout=60)
            client(machine.host, clock).ask(Interrupt(launch="one"), Finished)
            inbox("send", "one", "After the interrupt.")
            number = newest(delivery)
            given = until(lambda: len(launcher.frames) == 2)
            clock.sleep(300)
            returned = waiting.result(timeout=60)
        frames = launcher.close()
    assert given
    interrupt, prompt = frames
    assert interrupt == HeldInterrupt().model_dump_json()
    assert (
        note(number, "After the interrupt.")
        in HeldPrompt.model_validate_json(prompt).text
    )
    # The call nobody reads any more counted nothing told.
    assert returned == (
        (
            "Your turn ended while this call waited, so what reached your inbox "
            "reaches you at your next call instead."
        ),
        False,
    )


def test_a_held_session_s_compaction_keeps_what_it_was_given_for_its_turn(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """A compaction comes in the process that was given the turn, which it still reads: told at the compaction too, it would be told twice."""
    with inboxed(machine, clock, notices, said, holding=True) as delivery:
        launched(machine, clock, tmp_path, "one", "claude", held=True)
        hook = machine.host.launch("one").hook
        launcher = Launcher(machine.launch("one").held)
        send(hook, claude("SessionStart", source="startup"))
        send(hook, claude("Stop", stop_hook_active=False))
        inbox("send", "one", "Anyone?")
        number = newest(delivery)
        launcher.ringing()
        compacted = send(hook, claude("SessionStart", source="compact"))
        state = delivery.inbox.item(number).state
        launcher.close()
    assert note(number, "Anyone?") not in compacted
    assert state == Waiting()


def test_what_a_held_session_never_took_is_told_its_next_start(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said, holding=True) as delivery:
        launched(machine, clock, tmp_path, "one", "claude", held=True)
        hook = machine.host.launch("one").hook
        launcher = Launcher(machine.launch("one").held)
        send(hook, claude("SessionStart", source="startup"))
        send(hook, claude("Stop", stop_hook_active=False))
        inbox("send", "one", "Anyone?")
        number = newest(delivery)
        launcher.ringing()
        resumed = send(hook, claude("SessionStart", source="resume"))
        state = delivery.inbox.item(number).state
        launcher.close()
    assert note(number, "Anyone?") in context(resumed)
    assert isinstance(state, Told)


def test_a_push_not_taken_in_time_is_put_back_and_its_launch_rung_through_the_socket_from_then_on(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said, patience=timedelta(0)) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        session = Session(machine.host.launch("one").mcp)
        send(hook, claude("SessionStart", source="startup"))
        send(hook, claude("Stop", stop_hook_active=False))
        inbox("send", "one", "Anyone?")
        anyone = newest(delivery)
        session.pushed()
        rung = list(messages.ringing())
        put_back = delivery.inbox.item(anyone).state
        told = send(hook, bash("b1"))
        send(hook, claude("Stop", stop_hook_active=False))
        inbox("send", "one", "Again.")
        again = newest(delivery)
        quiet = session.quiet()
        session.close()
        frames = messages.close()
    assert frames_of(rung) == [bell(anyone)]
    assert put_back == Waiting()
    assert context(told) == note(anyone, "Anyone?")
    assert quiet
    assert frames_of(frames) == [bell(anyone), bell(again)]
    assert [line for line in said if "took nothing lup pushed" in line] == [
        (
            f"one: `{tmp_path.name}` took nothing lup pushed within 0 seconds, so "
            "they're woken through their messaging socket from now on: their "
            "runtime may not have loaded lup's server to push (docs/inbox.md, *How "
            "an agent is told*)"
        )
    ]


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_a_turns_start_tells_what_waits_beside_its_prompt(
    runtime: str,
    *,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
) -> None:
    payload = {"claude": claude, "codex": codex}[runtime]
    # Claude Code's prompts carry the title lup gave the session at their start.
    shown = {"claude": {"session_title": tmp_path.name}, "codex": {}}[runtime]
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", runtime)
        hook = machine.host.launch("one").hook
        send(hook, payload("SessionStart", source="startup"))
        inbox("send", "one", "Read this first.")
        number = newest(delivery)
        told = send(hook, payload("UserPromptSubmit", prompt="Go on.", **shown))
        again = send(hook, payload("UserPromptSubmit", prompt="And then?", **shown))
        state = delivery.inbox.item(number).state
    assert json.loads(told)["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert context(told) == note(number, "Read this first.")
    assert again == ""
    assert state == Told(at=clock.now(), how="turn's start")


def test_a_codex_session_is_never_woken_and_told_at_its_next_call(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "codex")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        send(hook, codex("SessionStart"))
        assert send(hook, codex("Stop", stop_hook_active=False)) == ""
        inbox("send", "one", "Waits.")
        number = newest(delivery)
        told = send(
            hook,
            codex(
                "PreToolUse",
                tool_name="exec_command",
                tool_use_id="c1",
                tool_input={"cmd": "ls"},
            ),
        )
        frames = messages.close()
    assert frames == []
    assert context(told) == note(number, "Waits.")


def test_a_long_item_is_announced_once_and_returned_whole_by_wait_inbox(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    long = "x" * 12_000
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        inbox("send", "one", long)
        number = newest(delivery)
        announced = send(hook, bash("b1"))
        again = send(hook, bash("b2"))
        stopped = send(hook, claude("Stop", stop_hook_active=False))
        waiting = delivery.inbox.item(number).state
        whole = call(machine.host.launch("one").mcp, "wait_inbox", {})
    size = len(note(number, long).encode()) + 2
    assert context(announced) == (
        f'<announced item="{number}" kind="note" from="operator" bytes="{size:,}">'
        "Too long to tell here: call `wait_inbox` to read it whole.</announced>"
    )
    assert again == ""
    assert stopped == ""
    assert waiting == Waiting(announced=clock.now())
    assert whole == (note(number, long), False)


def test_a_held_call_whose_turn_ended_leaves_the_item_for_the_next_call(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "codex")
        hook = machine.host.launch("one").hook
        send(hook, codex("SessionStart"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(
                call, machine.host.launch("one").mcp, "wait_inbox", {}
            )
            assert delivery.holding.wait(timeout=60)
            assert send(hook, codex("Stop", stop_hook_active=False)) == ""
            inbox("send", "one", "Late.")
            number = newest(delivery)
            returned = waiting.result(timeout=60)
        told = send(
            hook,
            codex(
                "PreToolUse",
                tool_name="exec_command",
                tool_use_id="c1",
                tool_input={"cmd": "ls"},
            ),
        )
    assert returned == (
        (
            "Your turn ended while this call waited, so what reached your inbox "
            "reaches you at your next call instead."
        ),
        False,
    )
    assert context(told) == note(number, "Late.")


def test_an_ended_subagents_answer_goes_to_its_sessions_main_conversation(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        stamped = json.loads(
            send(
                hook,
                lup_call(
                    "ask",
                    {"question": "Rename it?"},
                    "q1",
                    agent_id="a1",
                    agent_type="general-purpose",
                ),
            )
        )["hookSpecificOutput"]["updatedInput"]
        call(machine.host.launch("one").mcp, "ask", stamped)
        question = newest(delivery)
        assert (
            send(
                hook,
                claude("SubagentStop", agent_id="a1", agent_type="general-purpose"),
            )
            == ""
        )
        ended = newest(delivery)
        answered = inbox("answer", str(question), "--comment", "Yes.")
        number = newest(delivery)
        told = send(hook, bash("b1"))
        answer = delivery.inbox.item(number)
        threads = delivery.inbox.ledger.every(Thread)
    assert answered == (
        f"Answered @{question}: your answer, @{number}, is for `{tmp_path.name}`.\n"
    )
    assert answer.addressed == Conversation(
        repository=tmp_path / ".git", runtime="claude", session="s1", agent="a1"
    )
    worker = f"{tmp_path.name}/general-purpose·a1"
    # The question landed in no thread: it isn't told them as landed.
    assert threads == []
    assert context(told) == (
        f'<ended item="{ended}" from="{worker}" '
        'name="general-purpose·a1">They were stopped before they ended their turn.</ended>'
        f'\n\n<answer item="{number}" from="operator" for="{worker}, '
        f'whose conversation had ended" question="{question}">\n'
        f'<asked>Rename it?</asked>\n<comment id="{number}.1">Yes.</comment>\n</answer>'
    )


def test_items_survive_a_restart_and_reach_a_session_resumed_in_a_launch_of_its_own(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        call(machine.host.launch("one").mcp, "note", {"remark": "A doubt."})
        doubt = newest(delivery)
        inbox("send", "one", "Kept.")
        kept = newest(delivery)
    with inboxed(machine, clock, notices, said) as delivery:
        listed = inbox()
        launched(machine, clock, tmp_path, "two", "claude")
        resumed = send(
            machine.host.launch("two").hook, claude("SessionStart", source="resume")
        )
        where = delivery.inbox.whereabouts
    assert listed == (
        f"{cited(doubt):>5}  2026-10-01 12:00  a note from `{tmp_path.name}` "
        f"in {tmp_path}: A doubt.\n"
    )
    assert context(resumed) == note(kept, "Kept.")
    assert [place.launch for place in where.values()] == ["two"]


def test_the_operator_replies_to_a_note_the_reply_saying_what_it_answers(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        call(machine.host.launch("one").mcp, "note", {"remark": "A doubt.\nAt length."})
        doubt = newest(delivery)
        wordless = refused("answer", str(doubt), "--comment", " ")
        # The `1` after `--leaning` is a decision's number, not an item's.
        ruled = refused("answer", str(doubt), "--leaning", "1", "--comment", "Yes.")
        replied = inbox("answer", str(doubt), "--comment", "Noted, go on.")
        reply = newest(delivery)
        listed = inbox()
        told = send(hook, bash("b1"))
        own = refused("answer", str(reply), "--comment", "Again.")
        again = inbox("answer", str(doubt), "--comment", "One more thing.")
        more = newest(delivery)
        made = numbers(delivery)
    assert wordless == f"@{doubt} is a note: give your reply in words"
    assert ruled == f"@{doubt} is a note, which takes a reply in words, not verdicts"
    assert replied == (
        f"Replied to @{doubt}: your reply, @{reply}, is for `{tmp_path.name}`.\n"
    )
    assert listed == "Nothing waits for you.\n"
    assert context(told) == (
        f'<message item="{reply}" from="operator" kind="note">\n'
        f'<on item="{doubt}" kind="note">\n'
        "<opening>A doubt.</opening>\n"
        f'<comment id="{reply}.1">Noted, go on.</comment>\n'
        "</on>\n"
        "</message>"
    )
    assert own == (
        f"@{reply} is a note from the operator: neither a question waiting for an "
        "answer nor a conversation's message to reply to"
    )
    assert again == (
        f"Replied to @{doubt}: your reply, @{more}, is for `{tmp_path.name}`.\n"
    )
    # Each refused answer made no item.
    assert made == [doubt, reply, more]


def test_a_sessions_turn_failing_on_an_api_error_is_one_note_whose_reply_wakes_it(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """`StopFailure` in place of `Stop`: the turn's end in lup's words, never the error as the agent's, and the session idle from then on."""
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        send(hook, claude("SessionStart", source="startup"))
        send(hook, bash("b1"))
        failed = send(
            hook,
            claude(
                "StopFailure",
                error="rate_limit",
                last_assistant_message="API Error: Request rejected (429)",
            ),
        )
        failure = newest(delivery)
        noted = delivery.inbox.item(failure)
        replied = inbox("answer", str(failure), "--comment", "Try again.")
        reply = newest(delivery)
        made = numbers(delivery)
        threads = delivery.inbox.ledger.every(Thread)
        messages.close()
    assert failed == ""
    assert noted.reason == Message(
        kind="note",
        text=(
            "Their turn ended on an error from the model's API (rate_limit):\n"
            "API Error: Request rejected (429)"
        ),
        ending=True,
    )
    assert noted.recipient == Operator()
    # The note lands in no thread, and the failure made that one item alone.
    assert threads == []
    assert made == [failure, reply]
    assert replied == (
        f"Replied to @{failure}: your reply, @{reply}, is for `{tmp_path.name}`.\n"
    )
    assert f"one: woke `{tmp_path.name}` for @{reply}" in said


def test_blocked_note_and_send_reach_the_operator_a_note_raising_no_notice(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        mcp = machine.host.launch("one").mcp
        reported = call(mcp, "blocked", {"problem": "The build is broken."})
        problem = newest(delivery)
        noted = call(mcp, "note", {"remark": "I assumed UTF-8."})
        remark = newest(delivery)
        sent = call(
            mcp,
            "send",
            {"to": "operator", "kind": "disagreement", "text": "Not this way."},
        )
        disagreement = newest(delivery)
        unknown = call(mcp, "send", {"to": "someone", "kind": "note", "text": "x"})
        invalid = call(mcp, "send", {"to": "operator", "kind": "memo", "text": "x"})
        made = numbers(delivery)
        threads = delivery.inbox.ledger.every(Thread)
        listed = inbox()
    assert reported == (
        f"Your problem is with the operator, @{problem}, and they're notified. You can end your turn now.",
        False,
    )
    # The problem lands in no thread.
    assert threads == []
    assert noted == (
        f"Your note is with the operator, @{remark}. You can carry on.",
        False,
    )
    assert sent == (f"Your message is with the operator, @{disagreement}.", False)
    # Neither refused send made an item.
    assert made == [problem, remark, disagreement]
    assert unknown == (
        (
            "Not sent: no subagent of yours is `someone`. `to` takes `operator`, or "
            "one of your own subagents by their name, their path or their runtime's id: "
            "none lup has heard."
        ),
        False,
    )
    assert invalid[1]
    assert invalid[0].startswith("Refused: 1 validation error for Sending")
    assert listed.splitlines() == [
        (
            f"{cited(problem):>5}  2026-10-01 12:00  a problem from "
            f"`{tmp_path.name}` in {tmp_path}: "
            "The build is broken."
        ),
        (
            f"{cited(remark):>5}  2026-10-01 12:00  a note from `{tmp_path.name}` "
            f"in {tmp_path}: "
            "I assumed UTF-8."
        ),
        (
            f"{cited(disagreement):>5}  2026-10-01 12:00  a disagreement from "
            f"`{tmp_path.name}` in {tmp_path}: Not this way."
        ),
    ]
    assert notices.raised[0] == (
        f"lup: a problem from `{tmp_path.name}` in {tmp_path}\n"
        f"The build is broken.\nlup-dev inbox show {problem}"
    )
    # The problem and the disagreement wait on the operator, and are noticed; the note is news, and isn't.
    assert len(notices.raised) == 2
    assert notices.raised[1].startswith(f"lup: a disagreement from `{tmp_path.name}`")


def test_friction_how_it_felt_and_stop_reach_the_operator_from_each_runtime_and_subagent(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    jammed: dict[str, JsonValue] = {
        "text": (
            "`uv run lup-dev check` printed: engine stale\n"
            "I was running the gate; saying the rebuild's time first would help."
        )
    }
    went: dict[str, JsonValue] = {"text": "The brief was clear, and it felt good."}
    quiet: dict[str, JsonValue] = {"text": "Nothing notable."}
    stopping: dict[str, JsonValue] = {"why": "Done; nothing more is worth doing."}

    def stamped(hook: Path, started: str) -> dict[str, JsonValue]:
        found = json.loads(send(hook, started))
        return found["hookSpecificOutput"]["updatedInput"]

    def codex_call(
        tool: str, arguments: dict[str, JsonValue], call: str, **fields: object
    ) -> str:
        return codex(
            "PreToolUse",
            tool_name=f"mcp__lup__{tool}",
            tool_input=arguments,
            tool_use_id=call,
            **fields,
        )

    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        launched(machine, clock, other, "two", "codex")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        hook2, mcp2 = machine.host.launch("two").hook, machine.host.launch("two").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook2, codex("SessionStart", source="startup"))
        answers = [
            call(
                mcp,
                "friction",
                stamped(
                    hook,
                    lup_call(
                        "friction",
                        jammed,
                        "f1",
                        agent_id="a1",
                        agent_type="general-purpose",
                    ),
                ),
            ),
            call(
                mcp, "how_it_felt", stamped(hook, lup_call("how_it_felt", quiet, "h1"))
            ),
            call(mcp, "stop", stamped(hook, lup_call("stop", stopping, "s1"))),
            call(
                mcp2, "friction", stamped(hook2, codex_call("friction", jammed, "c1"))
            ),
            call(
                mcp2,
                "how_it_felt",
                stamped(hook2, codex_call("how_it_felt", went, "c2", agent_id="b1")),
            ),
            call(
                mcp2,
                "stop",
                stamped(hook2, codex_call("stop", stopping, "c3", agent_id="b1")),
            ),
        ]
        labelled = call(mcp, "friction", {"got_in_the_way": "The gate hung."})
        # One item for each answered call, the subagent's friction a second for
        # their parent; the refused friction makes none.
        (
            claude_friction,
            copied,
            claude_felt,
            claude_stop,
            codex_friction,
            codex_felt,
            codex_stop,
        ) = numbers(delivery)
        threads = delivery.inbox.ledger.every(Thread)
        waiting = delivery.inbox.waiting(Operator())
        listed = inbox()
        shown = inbox("show", str(claude_friction))
        replied = inbox(
            "answer", str(claude_friction), "--comment", "The rebuild is fixed."
        )
        reply = delivery.inbox.item(newest(delivery))
        done = inbox("done", str(claude_felt))
        passed = delivery.inbox.item(copied)
        felt = [
            each
            for each in delivery.inbox.items.values()
            if isinstance(each.reason, HowItFelt)
        ]
    # Each subagent has a parent, their session's own conversation, who gets a
    # copy of their friction (`copied`); how it felt is told to the operator
    # alone. Each item lands in no thread.
    assert threads == []
    assert [text for text, _ in answers] == [
        f"Thanks: your friction is with the operator, @{claude_friction}, and your parent has it too. You can carry on.",
        f"Thank you for telling them. It's with the operator, as you wrote it, @{claude_felt}.",
        f"The operator will read why you stopped, @{claude_stop}. You can end your turn now.",
        f"Thanks: your friction is with the operator, @{codex_friction}. You can carry on.",
        f"Thank you for telling them. It's with the operator, as you wrote it, @{codex_felt}.",
        f"The operator will read why you stopped, @{codex_stop}. You can end your turn now.",
    ]
    assert not any(error for _, error in answers)
    # The parts a friction once had are refused: it's one text.
    assert labelled[1]
    assert labelled[0].startswith("Refused: 1 validation error for Friction")
    claude_session = Conversation(
        repository=tmp_path / ".git", runtime="claude", session="s1"
    )
    codex_session = Conversation(
        repository=other / ".git", runtime="codex", session="t1"
    )
    assert [
        (each.number, each.sender, each.recipient, each.call) for each in waiting
    ] == [
        (
            claude_friction,
            claude_session.model_copy(update={"agent": "a1"}),
            Operator(),
            "f1",
        ),
        (claude_felt, claude_session, Operator(), "h1"),
        (claude_stop, claude_session, Operator(), "s1"),
        (codex_friction, codex_session, Operator(), "c1"),
        (
            codex_felt,
            codex_session.model_copy(update={"agent": "b1"}),
            Operator(),
            "c2",
        ),
        (
            codex_stop,
            codex_session.model_copy(update={"agent": "b1"}),
            Operator(),
            "c3",
        ),
    ]
    friction = Friction.model_validate(jammed)
    assert (passed.reason, passed.recipient, passed.quiet) == (
        friction,
        claude_session,
        True,
    )
    assert [each.recipient for each in felt] == [Operator(), Operator()]
    assert [each.reason for each in waiting] == [
        friction,
        HowItFelt.model_validate(quiet),
        Stopped.model_validate(stopping),
        friction,
        HowItFelt.model_validate(went),
        Stopped.model_validate(stopping),
    ]
    first = listed.splitlines()[0]
    assert first.startswith(
        f"{cited(claude_friction):>5}  2026-10-01 12:00  a friction from `"
    )
    assert first.endswith(
        f"`{tmp_path.name}/a1` in {tmp_path}: "
        "`uv run lup-dev check` printed: engine stale"
    )
    assert "how it felt from" in listed.splitlines()[1]
    assert listed.splitlines()[1].endswith(": Nothing notable.")
    assert "a stop by choice from" in listed.splitlines()[2]
    assert shown.endswith(
        "`uv run lup-dev check` printed: engine stale\n"
        "I was running the gate; saying the rebuild's time first would help.\n"
    )
    assert replied == (
        f"Replied to @{claude_friction}: your reply, @{reply.number}, is for "
        f"`{tmp_path.name}/a1`.\n"
    )
    assert reply.reason == Message(
        kind="note", text="The rebuild is fixed.", of=claude_friction
    )
    assert reply.recipient == claude_session.model_copy(update={"agent": "a1"})
    assert done.startswith(f"@{claude_felt} ")
    # News, each of them: to read, never raising a notice.
    assert [each.rank.name for each in waiting] == ["news"] * 6
    assert notices.raised == []


def test_numbered_decisions_are_each_answered_once_and_a_message_is_done(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    two: dict[str, JsonValue] = {
        "question": "Which?",
        "decisions": [
            {"decision": "First", "lean": "a"},
            {"decision": "Second", "lean": "b"},
        ],
    }
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        mcp = machine.host.launch("one").mcp
        call(mcp, "ask", two)
        which = newest(delivery)
        call(mcp, "note", {"remark": "Read me."})
        read_me = newest(delivery)
        call(mcp, "ask", {"question": "In words?"})
        in_words = newest(delivery)
        # Each number after `--leaning` or `--undecided` is a decision's, not an item's.
        missing = refused("answer", str(which), "--leaning", "1")
        twice = refused(
            "answer", str(which), "--leaning", "1", "--leaning", "1", "--undecided", "2"
        )
        wordless = refused("answer", str(in_words), "--comment", "  ")
        not_done = refused("done", str(which))
        done = inbox("done", str(read_me))
        replied = inbox("answer", str(read_me), "--comment", "x")
        reply = newest(delivery)
        made = numbers(delivery)
        # One past every number handed out: a number nothing holds.
        absent = reply + 100
        nothing = refused("show", str(absent))
        listed = inbox()
    assert missing == (
        f"@{which} asks 2 decisions, each taking one answer (`leaning`, `undecided`, "
        "`leave open`, or words); these were given for [1]"
    )
    assert "these were given for [1, 1, 2]" in twice
    assert wordless == f"@{in_words} is a question answered in words: give them"
    assert not_done == (
        f"@{which} is a question: answer it, `lup-dev inbox answer {which}`"
    )
    assert done == f"@{read_me} is done.\n"
    assert replied == (
        f"Replied to @{read_me}: your reply, @{reply}, is for `{tmp_path.name}`.\n"
    )
    # Each refused answer made no item.
    assert made == [which, read_me, in_words, reply]
    assert nothing == f"the inbox holds no @{absent}"
    assert [line.split()[0] for line in listed.splitlines()] == [
        cited(which),
        cited(in_words),
    ]


def test_an_items_number_is_cited_with_an_at_and_read_back_cited_or_bare() -> None:
    assert cited(270) == "@270"
    assert item_number(cited(270)) == 270
    assert item_number("270") == 270
    for typed in ["#270", "item 270", "@", "@@270"]:
        with pytest.raises(ValueError, match="invalid literal for int"):
            item_number(typed)


def test_each_command_takes_an_items_number_cited_or_bare(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        mcp = machine.host.launch("one").mcp
        noted = call(mcp, "note", {"remark": "Read me."})
        read_me = newest(delivery)
        call(mcp, "ask", {"question": "In words?"})
        in_words = newest(delivery)
        call(mcp, "note", {"remark": "And me."})
        and_me = newest(delivery)
        # Each typed as the operator types one cited, an `@` before its number.
        shown = inbox("show", f"@{read_me}")
        answered = inbox("answer", f"@{in_words}", "--comment", "Yes.")
        answer = newest(delivery)
        done = inbox("done", f"@{and_me}")
        hashed = runner.invoke(cli.app, ["inbox", "show", f"#{read_me}"])
    assert noted == (
        f"Your note is with the operator, @{read_me}. You can carry on.",
        False,
    )
    assert shown.startswith(f"@{read_me}, a note from `{tmp_path.name}` in {tmp_path}")
    assert answered == (
        f"Answered @{in_words}: your answer, @{answer}, is for `{tmp_path.name}`.\n"
    )
    assert done == f"@{and_me} is done.\n"
    assert hashed.exit_code == 2
    assert f"Invalid value for 'number': #{read_me}" in hashed.output


def test_lup_dev_inbox_answer_asks_each_decision_in_turn_at_a_terminal(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    two: dict[str, JsonValue] = {
        "question": "Which?",
        "decisions": [
            {"decision": "First", "lean": "a"},
            {"decision": "Second", "lean": "b"},
        ],
    }
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        call(machine.host.launch("one").mcp, "ask", two)
        question = newest(delivery)
        result = runner.invoke(
            cli.app,
            ["inbox", "answer", str(question)],
            input="\nleaning\nsure\nSure, no strong preference.\nThanks.\n",
        )
        number = newest(delivery)
        answer = delivery.inbox.item(number).reason
        assert isinstance(answer, Answer)
        told = delivery.said(delivery.inbox.item(number))
    assert result.exit_code == 0, result.output
    # An empty line isn't taken for the lean: it's asked again.
    asked = "1: leaning, undecided, leave open, or your answer in words"
    assert result.output.count(asked) == 2
    # Words that aren't a verdict are the decision's answer, with nothing to add.
    assert "2: a comment" not in result.output
    # A ruling's `decision`, and a decision's `number`, is its place in the
    # question, not an item's.
    assert answer.model_dump() == {
        "reason": "answer",
        "question": question,
        "rulings": [
            {"decision": 1, "verdict": "leaning", "comment": "sure"},
            {"decision": 2, "verdict": None, "comment": "Sure, no strong preference."},
        ],
        "comment": "Thanks.",
    }
    assert told == (
        f'<answer item="{number}" from="operator" question="{question}">\n'
        "<asked>Which?</asked>\n"
        '<decision number="1" lean="a" verdict="leaning: they go with the lean" '
        f'id="{number}.1">\n'
        "First\n<comment>sure</comment>\n</decision>\n"
        '<decision number="2" lean="b" verdict="answered in words" '
        f'id="{number}.2">\n'
        "Second\n<comment>Sure, no strong preference.</comment>\n</decision>\n"
        f'<comment id="{number}.3">Thanks.</comment>\n'
        "</answer>"
    )


def named_at_start(answer: str) -> tuple[str, str]:
    """The name a session's start told them, and the title it gave the runtime."""
    said = json.loads(answer)["hookSpecificOutput"]
    told = said["additionalContext"]
    assert told.startswith("lup: you're `")
    return told.removeprefix("lup: you're `").partition("`")[0], said["sessionTitle"]


def test_a_session_renames_itself_and_a_name_another_holds_is_refused(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "a", "one", "claude")
        launched(machine, clock, tmp_path / "b", "two", "claude")
        first = machine.host.launch("one")
        named_at_start(send(first.hook, claude("SessionStart", source="startup")))
        send(machine.host.launch("two").hook, claude("SessionStart", session_id="s2"))
        renamed = call(first.mcp, "rename", {"name": "gate-on-push"})
        taken = call(machine.host.launch("two").mcp, "rename", {"name": "gate-on-push"})
        shaped = call(first.mcp, "rename", {"name": "two words"})
        listed = HostClient(
            layout=machine.host, clock=clock, starter=Unstarted()
        ).listed()
    assert renamed == ("You're `gate-on-push` now.", False)
    assert taken[0] == (
        f"Not renamed: `gate-on-push` is launch one's, claude in {tmp_path / 'a'}: "
        "pick another name"
    )
    assert shaped[0].startswith("Not renamed: a launch's name is letters, digits")
    assert {each.launch: each.name for each in listed.launches} == {
        "one": "gate-on-push",
        "two": "b",
    }
    assert listed.sessions == {"s1": "gate-on-push", "s2": "b"}
    assert "one: renamed from `a` to `gate-on-push`" in said


def test_a_session_resumed_in_a_later_launch_takes_its_name_back(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        call(machine.host.launch("one").mcp, "rename", {"name": "parser-work"})
        HostClient(layout=machine.host, clock=clock, starter=Unstarted()).unregister(
            "one"
        )
        launched(machine, clock, tmp_path, "two", "claude")
        resumed = send(
            machine.host.launch("two").hook, claude("SessionStart", source="resume")
        )
    assert named_at_start(resumed) == ("parser-work", "parser-work")


def test_a_title_the_operator_gave_in_the_runtime_is_taken_in_a_name_s_shape(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        started = send(
            machine.host.launch("one").hook,
            claude("SessionStart", source="resume", session_title="Naming Review"),
        )
    assert named_at_start(started) == ("naming-review", "naming-review")


def given(answer: str) -> str | None:
    """The title a hook's answer gives the session in Claude Code; none where it gives none."""
    if not answer:
        return None
    title = json.loads(answer)["hookSpecificOutput"].get("sessionTitle")
    assert title is None or isinstance(title, str)
    return title


def prompt(title: str | None, **fields: object) -> str:
    """A Claude Code prompt of session `s1`, carrying the session's title where they have one."""
    shown = {} if title is None else {"session_title": title}
    return claude("UserPromptSubmit", prompt="Go on.", **shown, **fields)


def test_a_prompt_with_the_title_lup_gave_gives_none(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "a", "one", "claude")
        hook = machine.host.launch("one").hook
        _, title = named_at_start(send(hook, claude("SessionStart", source="startup")))
        answered = send(hook, prompt(title))
    assert title == "a"
    assert answered == ""


def test_a_prompt_after_a_rename_through_lup_gives_the_new_title_once(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "a", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        _, title = named_at_start(send(hook, claude("SessionStart", source="startup")))
        call(mcp, "rename", {"name": "parser-work"})
        first = send(hook, prompt(title))
        then = send(hook, prompt(given(first)))
        # A subagent's prompt never titles the session.
        call(mcp, "rename", {"name": "gate-on-push"})
        subagent = send(
            hook, prompt("parser-work", agent_id="a1", agent_type="general-purpose")
        )
    assert given(first) == "parser-work"
    assert then == ""
    assert given(subagent) is None


def test_a_session_resumed_after_a_rename_through_lup_keeps_lups_name(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "a", "one", "claude")
        first = machine.host.launch("one")
        _, title = named_at_start(
            send(first.hook, claude("SessionStart", source="startup"))
        )
        call(first.mcp, "rename", {"name": "parser-work"})
        HostClient(layout=machine.host, clock=clock, starter=Unstarted()).unregister(
            "one"
        )
        launched(machine, clock, tmp_path / "b", "two", "claude")
        # The resume carries the title lup gave at the session's first start.
        resumed = send(
            machine.host.launch("two").hook,
            claude("SessionStart", source="resume", session_title=title),
        )
    assert named_at_start(resumed) == ("parser-work", "parser-work")


def test_an_operators_rename_in_the_runtime_is_taken_at_the_next_prompt(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "a", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        renamed = send(hook, prompt("Naming Review"))
        then = send(hook, prompt(given(renamed)))
        listed = HostClient(
            layout=machine.host, clock=clock, starter=Unstarted()
        ).listed()
    assert given(renamed) == "naming-review"
    assert context(renamed) == (
        "lup: the operator renamed you `naming-review`: how they, lup's commands "
        "and other sessions call you from now on. Keep the name they gave."
    )
    assert then == ""
    assert {each.launch: each.name for each in listed.launches} == {
        "one": "naming-review"
    }
    assert listed.sessions == {"s1": "naming-review"}


def test_an_operators_title_another_launch_holds_is_given_lups_name_back(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "a", "one", "claude")
        launched(machine, clock, tmp_path / "b", "two", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        answered = send(hook, prompt("b"))
    assert given(answered) == "a"
    assert (
        "one: its session's title in its runtime, `b`, can't be its name (not a "
        "name's shape, or another launch's), so the runtime is given `a`"
    ) in said


def test_a_title_lup_found_is_never_taken_over_a_later_rename_through_lup(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "a", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        call(mcp, "rename", {"name": "parser-work"})
        # The operator gives the session in the runtime the name they have in lup.
        same = send(hook, prompt("parser-work"))
        call(mcp, "rename", {"name": "gate-on-push"})
        later = send(hook, prompt("parser-work"))
    assert same == ""
    assert given(later) == "gate-on-push"


class Awaited(list[str]):
    """What the service says, with an event set once a line says `awaited`."""

    def __init__(self, awaited: str) -> None:
        super().__init__()
        self.awaited = awaited
        self.arrived = threading.Event()

    @override
    def append(self, line: str) -> None:
        super().append(line)
        if self.awaited in line:
            self.arrived.set()


def abandoned(path: Path, payload: str) -> None:
    """Send `payload` on the socket at `path` and close before the answer, as a hook its runtime ended does."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(path))
        connection.sendall(payload.encode())


def test_a_title_whose_answer_never_reached_its_hook_is_given_again(
    machine: Layout, clock: FakeClock, notices: Raised, tmp_path: Path
) -> None:
    said = Awaited("the hook was gone before its answer")
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "a", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        _, title = named_at_start(send(hook, claude("SessionStart", source="startup")))
        call(mcp, "rename", {"name": "parser-work"})
        abandoned(hook, prompt(title))
        assert said.arrived.wait(timeout=60)
        # The runtime never took the new title, so it still has the one before.
        again = send(hook, prompt(title))
    assert given(again) == "parser-work"


def test_an_operator_naming_the_session_back_after_a_rename_through_lup_is_taken(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "a", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        _, title = named_at_start(send(hook, claude("SessionStart", source="startup")))
        call(mcp, "rename", {"name": "parser-work"})
        renamed = send(hook, prompt(title))
        # The operator gives it back the title it had before lup's rename.
        back = send(hook, prompt(title))
        listed = HostClient(
            layout=machine.host, clock=clock, starter=Unstarted()
        ).listed()
    assert given(renamed) == "parser-work"
    assert given(back) is None
    assert context(back).startswith("lup: the operator renamed you `a`")
    assert listed.sessions == {"s1": "a"}


def test_a_codex_session_is_never_given_a_title(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "a", "one", "codex")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        started = send(hook, codex("SessionStart", source="startup"))
        call(mcp, "rename", {"name": "parser-work"})
        prompted = send(hook, codex("UserPromptSubmit", prompt="Go on."))
    assert "sessionTitle" not in json.loads(started)["hookSpecificOutput"]
    assert prompted == ""


def test_lup_dev_rename_and_send_name_a_launch_by_its_name(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "a", "one", "claude")
        launched(machine, clock, tmp_path / "b", "two", "claude")
        send(machine.host.launch("two").hook, claude("SessionStart", session_id="s2"))
        renamed = runner.invoke(cli.app, ["rename", "b", "reviewer"])
        held = runner.invoke(cli.app, ["rename", "a", "reviewer"])
        sent = inbox("send", "reviewer", "Look.")
        number = newest(delivery)
    assert renamed.output == "Launch two is `reviewer`.\n"
    assert isinstance(held.exception, HostError)
    assert "`reviewer` is launch two's" in str(held.exception)
    assert sent == f"Sent @{number} to `reviewer`.\n"


def introduction() -> str:
    """What a subagent is told of lup's tools at their first hook, as the tests' service serves them: the inbox's, `judged`, `land` and `rename`, each by its docstring's first line."""
    served = [
        *specs(),
        *JudgeTools.model_construct().specs(),
        *LandingTools.model_construct().specs(),
        *Naming.model_construct().specs(),
    ]
    opening = (
        "lup, the environment you work in, serves you these tools, as it does "
        "your session's main conversation. Your tool search finds each by its "
        "name, with its full description. Some subagent types are given only "
        "their own tools, without lup's: where your tool search finds none of "
        "these, you're one of them."
    )
    direct = (
        "`friction` and `how_it_felt` reach the operator directly, whatever your "
        "parent passes on."
    )
    lines = [f"- `{spec.name}`: {spec.summary}" for spec in served]
    return "\n".join([opening, "", *lines, "", direct])


class Subagents:
    """A Claude Code session's transcript and their subagents' records beside it, as Claude Code keeps them."""

    def __init__(self, tmp_path: Path, session: str = "s1") -> None:
        self.session = session
        self.transcript = tmp_path / "projects" / f"{session}.jsonl"
        self.folder = tmp_path / "projects" / session / "subagents"
        self.folder.mkdir(parents=True)

    def recorded(
        self,
        agent: str,
        kind: str,
        call: str,
        name: str | None = None,
        parent: str | None = None,
    ) -> None:
        """Record subagent `agent`, of `kind`, spawned by `call`: named `name` where their parent named them, by subagent `parent` where one spawned it."""
        kept: dict[str, JsonValue] = {
            "agentType": kind,
            "toolUseId": call,
            "spawnDepth": 1 if parent is None else 2,
        }
        if name is not None:
            kept["name"] = name
        if parent is not None:
            kept["parentAgentId"] = parent
        (self.folder / f"agent-{agent}.meta.json").write_text(json.dumps(kept))

    def spawn(self, call: str, name: str | None = None, agent: str = "") -> str:
        """An `Agent` call starting, made by the session's own conversation or by subagent `agent`."""
        given: dict[str, JsonValue] = {"description": "look", "prompt": "look"}
        if name is not None:
            given["name"] = name
        return claude(
            "PreToolUse",
            session_id=self.session,
            tool_name="Agent",
            tool_input=given,
            tool_use_id=call,
            transcript_path=str(self.transcript),
            **({"agent_id": agent} if agent else {}),
        )

    def call(self, agent: str, kind: str, call: str) -> str:
        """A call of subagent `agent`'s starting."""
        return bash(
            call,
            session_id=self.session,
            agent_id=agent,
            agent_type=kind,
            transcript_path=str(self.transcript),
        )

    def ended(
        self, agent: str, kind: str, said: str | None, *, again: bool = False
    ) -> str:
        """Subagent `agent`'s turn ending, saying `said`; with no message, as Claude Code ends one it stopped; `again` where a hook held their last end."""
        return claude(
            "SubagentStop",
            session_id=self.session,
            agent_id=agent,
            agent_type=kind,
            transcript_path=str(self.transcript),
            stop_hook_active=again,
            **({} if said is None else {"last_assistant_message": said}),
        )

    def failed(self, agent: str, kind: str, error: str) -> str:
        """Subagent `agent`'s turn ending on an error from the model's API of kind `error`, as Claude Code 2.1.309 sends it: `StopFailure`, and no `SubagentStop`."""
        return claude(
            "StopFailure",
            session_id=self.session,
            agent_id=agent,
            agent_type=kind,
            transcript_path=str(self.transcript),
            prompt_id="p1",
            error=error,
            last_assistant_message="API Error: Request rejected (429)",
        )

    def lup(
        self,
        hooks: tuple[Path, Path],
        tool: str,
        arguments: dict[str, JsonValue],
        agent: str,
        kind: str,
    ) -> tuple[str, bool]:
        """Call lup's `tool` as subagent `agent` does: its start stamped by the hook on `hooks[0]`, then the call through the tool server on `hooks[1]`."""
        hook, mcp = hooks
        started = lup_call(
            tool,
            arguments,
            f"{agent}-{tool}",
            session_id=self.session,
            agent_id=agent,
            agent_type=kind,
            transcript_path=str(self.transcript),
        )
        stamped = json.loads(send(hook, started))["hookSpecificOutput"]["updatedInput"]
        return call(mcp, tool, stamped)


def named_talkers(
    machine: Layout, clock: FakeClock
) -> list[tuple[str, str | None, int]]:
    """Each conversation of launch `one` as the operator is shown them: their path, their parent's, their depth."""
    listed = HostClient(layout=machine.host, clock=clock, starter=Unstarted()).listed()
    return [(each.path, each.parent, each.depth) for each in listed.talkers["one"]]


def podman_of(*running: str) -> Podman:
    """A podman having the containers `running` and no other, asked nothing but whether one is there, and to rename one."""
    there = list(running)

    def answered(process: Process) -> Ran:
        match process.arguments:
            case ["podman", "container", "exists", name]:
                return Ran(command=process.arguments, status=0 if name in there else 1)
            case ["podman", "rename", before, name] if before in there:
                there[there.index(before)] = name
                return Ran(command=process.arguments, status=0)
            case _:
                message = f"podman asked {process.arguments}"
                raise AssertionError(message)

    return Podman(execute=answered)


def podman_having(monkeypatch: pytest.MonkeyPatch, *running: str) -> None:
    """Stand podman in for the command line, having the containers `running` and no other."""
    monkeypatch.setattr(cli, "Podman", lambda: podman_of(*running))


def test_a_subagent_is_shown_under_the_conversation_that_spawned_it_nested_ones_too(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = Subagents(tmp_path)
    podman_having(monkeypatch, "lup-one")
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        spawned = send(hook, records.spawn("t1", name="explore-auth"))
        records.recorded("a1", "Explore", "t1", name="explore-auth")
        first = send(hook, records.call("a1", "Explore", "c1"))
        nested = send(hook, records.spawn("t2", agent="a1"))
        records.recorded("a2", "general-purpose", "t2", parent="a1")
        asked = context(send(hook, records.call("a2", "general-purpose", "c2")))
        sockets = (hook, machine.host.launch("one").mcp)
        renamed = records.lup(
            sockets, "rename", {"name": "grep-tokens"}, "a2", "general-purpose"
        )
        records.lup(sockets, "note", {"remark": "Found it."}, "a2", "general-purpose")
        found = newest(delivery)
        shown = named_talkers(machine, clock)
        listing = runner.invoke(cli.app, ["sessions"])
        listed = inbox()
    assert spawned == ""
    assert context(first) == introduction()
    assert nested == ""
    assert asked.startswith(
        f"{introduction()}\n\nlup: you're `w/explore-auth/general-purpose·a2` for now"
    )
    assert renamed[0].startswith("You're `w/explore-auth/grep-tokens`")
    assert shown == [
        ("w", None, 0),
        ("w/explore-auth", "w", 1),
        ("w/explore-auth/grep-tokens", "w/explore-auth", 2),
    ]
    assert listing.output.splitlines() == [
        f"`w`  claude in {tmp_path / 'w'}  (one)  container lup-one, running",
        "  w",
        "    w/explore-auth  Explore",
        "      w/explore-auth/grep-tokens  general-purpose",
    ]
    assert listed == (
        f"{cited(found):>5}  2026-10-01 12:00  a note from "
        f"`w/explore-auth/grep-tokens` in {tmp_path / 'w'}: Found it.\n"
    )


def test_lup_dev_sessions_counts_the_subagents_that_ended_and_lists_them_with_all(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = Subagents(tmp_path)
    podman_having(monkeypatch)
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        for agent, name, call in [("a1", "parser", "t1"), ("a2", "lexer", "t2")]:
            send(hook, records.spawn(call, name=name))
            records.recorded(agent, "Explore", call, name=name)
        send(hook, records.call("a1", "Explore", "c1"))
        send(hook, records.call("a2", "Explore", "c2"))
        send(hook, claude("SubagentStop", agent_id="a1"))
        folded = runner.invoke(cli.app, ["sessions"])
        every = runner.invoke(cli.app, ["sessions", "--all"])
    launch = f"`w`  claude in {tmp_path / 'w'}  (one)  container lup-one, not running"
    assert folded.output.splitlines() == [
        launch,
        "  w",
        "    w/lexer  Explore",
        "    1 ended, which `--all` lists",
    ]
    assert every.output.splitlines() == [
        launch,
        "  w",
        "    w/parser  Explore  ended",
        "    w/lexer  Explore",
    ]


def test_a_subagent_spawned_without_a_name_is_asked_to_name_itself_its_parent_never(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        spawns = [send(hook, records.spawn(call)) for call in ["t1", "t2"]]
        records.recorded("a1", "Explore", "t1")
        records.recorded("a2", "Explore", "t2")
        asked = context(send(hook, records.call("a1", "Explore", "c1")))
        before = named_talkers(machine, clock)
        sockets = (hook, machine.host.launch("one").mcp)
        send(hook, records.call("a2", "Explore", "c2"))
        renamed = records.lup(sockets, "rename", {"name": "parser"}, "a1", "Explore")
        held = records.lup(sockets, "rename", {"name": "parser"}, "a2", "Explore")
        after = named_talkers(machine, clock)
        launches = HostClient(
            layout=machine.host, clock=clock, starter=Unstarted()
        ).launches()
    assert spawns == ["", ""]
    assert asked.startswith(
        f"{introduction()}\n\n"
        "lup: you're `w/Explore·a1` for now, with no name of your own"
    )
    assert before[1] == ("w/Explore·a1", "w", 1)
    assert renamed[0].startswith("You're `w/parser` to lup and the operator now.")
    assert held[0] == "Not renamed: `parser` is `w/parser`'s: pick another name"
    assert [each[0] for each in after] == ["w", "w/parser", "w/Explore·a2"]
    assert [each.name for each in launches] == ["w"]


def test_a_subagents_name_and_place_outlast_a_restart_of_lups_host(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1"))
        records.recorded("a1", "Explore", "t1")
        send(hook, records.call("a1", "Explore", "c1"))
        sockets = (hook, machine.host.launch("one").mcp)
        records.lup(sockets, "rename", {"name": "parser"}, "a1", "Explore")
    with inboxed(machine, clock, notices, said):
        told = send(hook, records.call("a1", "Explore", "c2"))
        shown = named_talkers(machine, clock)
    assert told == ""
    assert shown == [("w", None, 0), ("w/parser", "w", 1)]


def test_a_session_keeps_their_name_across_a_restart_of_lups_host_no_thread_made_of_it(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        _, title = named_at_start(send(hook, claude("SessionStart", source="startup")))
        call(mcp, "rename", {"name": "inbox-scaling"})
        # Their first note lands in no thread: nothing is opened for them.
        call(mcp, "note", {"remark": "Go."})
        title = given(send(hook, prompt(title)))
    # The service started again serves the launch's record again, under its name.
    with inboxed(machine, clock, notices, said) as delivery:
        listed = HostClient(
            layout=machine.host, clock=clock, starter=Unstarted()
        ).listed()
        retitled = send(hook, prompt(title))
        named = delivery.concerns().found(tmp_path / "w" / ".git", "inbox-scaling")
        threads = delivery.inbox.ledger.every(Thread)
    assert {each.launch: each.name for each in listed.launches} == {
        "one": "inbox-scaling"
    }
    assert retitled == ""
    assert named is None
    assert threads == []


def test_an_item_outside_every_thread_stays_so_as_the_service_starts_and_its_session_keeps_their_name(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    repository = tmp_path / "w" / ".git"
    session = Conversation(repository=repository, runtime="claude", session="s1")
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        call(mcp, "rename", {"name": "inbox-scaling"})
    # An item outside every thread, while the session goes on: the service
    # started again leaves it so, and serves their launch again under its name.
    ledger = Ledger.opened(LedgerLayout.of(machine), KINDS)
    past = Inbox.opened(ledger).made(
        Message(kind="note", text="Built."),
        session,
        Operator(),
        tmp_path / "w",
        clock.now(),
    )
    ledger.close()
    with inboxed(machine, clock, notices, said) as delivery:
        listed = HostClient(
            layout=machine.host, clock=clock, starter=Unstarted()
        ).listed()
        thread = delivery.concerns().containing(past.number)
        threads = delivery.inbox.ledger.every(Thread)
    assert {each.launch: each.name for each in listed.launches} == {
        "one": "inbox-scaling"
    }
    assert session.repository == repository
    assert thread is None
    assert threads == []


def test_conversations_kept_with_a_field_lup_since_dropped_load_at_a_restart(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        send(hook, records.call("a1", "Explore", "c1"))
    kept = machine.host.conversations("one")
    stored = json.loads(kept.read_text())
    for each in stored["known"]:
        each["nudged"] = True
    kept.write_text(json.dumps(stored))
    with inboxed(machine, clock, notices, said):
        told = send(hook, records.call("a1", "Explore", "c2"))
        shown = named_talkers(machine, clock)
    assert told == ""
    assert shown == [("w", None, 0), ("w/parser", "w", 1)]


class Judged(LaunchJudge):
    """A launch's judge that answers every hook with nothing, keeping each payload it was asked."""

    def __init__(self) -> None:
        self.payloads: list[str] = []

    @override
    async def judged(self, launch: Register, payload: str) -> str:
        self.payloads.append(payload)
        return ""


def test_claude_codes_own_agents_are_answered_with_nothing_judged_by_no_one_and_shown_nowhere(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = Subagents(tmp_path)
    podman_having(monkeypatch)
    judge = Judged()
    transcript = str(records.transcript)
    with inboxed(machine, clock, notices, said, judge=judge) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        send(hook, records.call("a1", "Explore", "c1"))
        # A background subagent's progress summary, as Claude Code 2.1.309 hooks
        # it: a fork of its own id, with no type and no record, whose calls are
        # denied once their `PreToolUse` is answered, and nothing after.
        forked = send(hook, bash("c2", agent_id="f1", transcript_path=transcript))
        befriended = send(
            hook,
            lup_call(
                "friction",
                {"text": "stuck"},
                "c3",
                agent_id="f2",
                transcript_path=transcript,
            ),
        )
        # One answering in words is heard at its end alone, its type empty.
        summarized = send(
            hook,
            claude(
                "SubagentStop",
                agent_id="f3",
                agent_type="",
                transcript_path=transcript,
                stop_hook_active=False,
                last_assistant_message="Reading parser.py",
            ),
        )
        shown = named_talkers(machine, clock)
        every = runner.invoke(cli.app, ["sessions", "--all"])
        heard = {
            place.conversation.agent for place in delivery.inbox.whereabouts.values()
        }
        listed = inbox()
    assert [forked, befriended, summarized] == ["", "", ""]
    assert {json.loads(each).get("agent_id") for each in judge.payloads} == {None, "a1"}
    assert shown == [("w", None, 0), ("w/parser", "w", 1)]
    assert every.output.splitlines() == [
        f"`w`  claude in {tmp_path / 'w'}  (one)  container lup-one, not running",
        "  w",
        "    w/parser  Explore",
    ]
    assert heard == {None, "a1"}
    assert listed == "Nothing waits for you.\n"


def test_an_agent_of_the_runtimes_own_kept_calling_a_tool_is_shown_nowhere_after_a_restart(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        send(hook, records.call("a1", "Explore", "c1"))
    kept = machine.host.conversations("one")
    stored = json.loads(kept.read_text())
    main = stored["known"][0]["id"]
    stored["known"].append(
        {
            "id": "f1f1f1f1f1f1f1f1",
            "session": "s1",
            "agent": "f1",
            "parent": main,
            "internal": True,
            "handed": True,
            "linked": True,
            "introduced": True,
        }
    )
    stored["activities"]["f1f1f1f1f1f1f1f1"] = {
        "state": "calling",
        "since": "2026-10-01T11:00:00Z",
        "tool": "Bash",
    }
    kept.write_text(json.dumps(stored))
    with inboxed(machine, clock, notices, said):
        shown = named_talkers(machine, clock)
    assert shown == [("w", None, 0), ("w/parser", "w", 1)]


class Unguided(Spawns):
    """Says every subagent, of either runtime, was named after their id and reads none of their session's guidance."""

    @override
    def spawned(self, launch: Register, payload: str) -> Spawned | None:
        agent = json.loads(payload).get("agent_id")
        return None if agent is None else Spawned(name=f"sub-{agent}")


def codex_bash(call: str, agent: str | None = None) -> str:
    """A Codex `Bash` call starting, of the session's own conversation or of subagent `agent`."""
    return codex(
        "PreToolUse",
        tool_name="Bash",
        tool_input={"command": "ls"},
        tool_use_id=call,
        **({} if agent is None else {"agent_id": agent}),
    )


def test_a_subagent_not_reading_the_guidance_is_told_lups_tools_once_on_each_runtime(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    with inboxed(machine, clock, notices, said, spawns=Unguided()):
        launched(machine, clock, tmp_path, "one", "claude")
        launched(machine, clock, other, "two", "codex")
        hook, hook2 = machine.host.launch("one").hook, machine.host.launch("two").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook2, codex("SessionStart", source="startup"))
        main = send(hook, bash("m1"))
        first = send(hook, bash("b1", agent_id="a1", agent_type="general-purpose"))
        again = send(hook, bash("b2", agent_id="a1", agent_type="general-purpose"))
        internal = send(hook, claude("SubagentStop", agent_id="x1", agent_type=""))
        codex_main = send(hook2, codex_bash("d1"))
        ended = send(hook2, codex("SubagentStop", agent_id="b1"))
        later = send(hook2, codex_bash("d2", "b1"))
        codex_again = send(hook2, codex_bash("d3", "b1"))
    assert main == ""
    assert json.loads(first)["hookSpecificOutput"] == {
        "hookEventName": "PreToolUse",
        "additionalContext": introduction(),
    }
    assert again == ""
    assert internal == ""
    assert codex_main == ""
    assert ended == ""
    assert json.loads(later)["hookSpecificOutput"] == {
        "hookEventName": "PreToolUse",
        "additionalContext": introduction(),
    }
    assert codex_again == ""


def test_a_claude_fork_and_a_codex_subagent_read_the_guidance_and_are_told_nothing_of_it(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "w", "one", "claude")
        launched(machine, clock, other, "two", "codex")
        hook, hook2 = machine.host.launch("one").hook, machine.host.launch("two").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook2, codex("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        send(hook, records.spawn("t2"))
        records.recorded("f1", "fork", "t2")
        told = context(send(hook, records.call("a1", "Explore", "c1")))
        forked = context(send(hook, records.call("f1", "fork", "c2")))
        codex_told = context(send(hook2, codex_bash("d1", "b1")))
    assert told == introduction()
    assert forked.startswith("lup: you're `w/fork·f1` for now")
    assert introduction() not in forked
    assert codex_told.startswith("lup: you're `other/subagent·b1` for now")
    assert introduction() not in codex_told


INVITED = (
    "lup: whenever something's present for you in this work, and as you finish "
    "it, `how_it_felt` is there for how the work felt to you or how you are, in "
    'your own words. The operator reads it as you wrote it. "Nothing notable" is '
    "a fine answer, and so is leaving it."
)
"""What lup invites a subagent to, once, as their work starts (`invitation`)."""


def lup_finished(tool: str, call: str, **fields: object) -> str:
    """A Claude Code call to one of lup's tools finishing."""
    return claude(
        "PostToolUse",
        tool_name=f"mcp__lup__{tool}",
        tool_input={},
        tool_use_id=call,
        tool_response=[{"type": "text", "text": "Done."}],
        **fields,
    )


def test_a_subagent_is_invited_to_say_how_it_felt_once_as_its_first_call_to_lup_s_tools_finishes_on_each_runtime(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """Never a session's own conversation, never at a call's start or a turn's end, and never one that never calls lup's tools: a subagent type given only their own tools (`claude-code-guide`) can't answer it."""
    records = Subagents(tmp_path)
    rollouts = Rollouts(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "w", "one", "claude")
        launched(machine, clock, other, "two", "codex")
        hook, hook2 = machine.host.launch("one").hook, machine.host.launch("two").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook2, codex("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        send(hook, records.spawn("t2", name="guide"))
        records.recorded("a2", "claude-code-guide", "t2", name="guide")
        fields = {
            "agent_id": "a1",
            "agent_type": "Explore",
            "transcript_path": str(records.transcript),
        }
        send(hook, records.call("a1", "Explore", "c1"))
        main = send(hook, lup_finished("note", "m1"))
        send(hook, records.call("a2", "claude-code-guide", "g1"))
        guide = send(
            hook,
            claude(
                "PostToolUse",
                tool_name="Bash",
                tool_input={"command": "ls"},
                tool_use_id="g1",
                tool_response={"stdout": ""},
                agent_id="a2",
                agent_type="claude-code-guide",
                transcript_path=str(records.transcript),
            ),
        )
        started = send(hook, lup_call("note", {"remark": "x"}, "c2", **fields))
        first = send(hook, lup_finished("note", "c2", **fields))
        again = send(hook, lup_finished("note", "c3", **fields))
        ended = send(hook, records.ended("a1", "Explore", "Parsed."))
        rollouts.recorded("th1", "t1")
        send(hook2, rollouts.call("th1", "d1"))
        codex_first = send(
            hook2,
            codex(
                "PostToolUse",
                tool_name="mcp__lup__rename",
                tool_input={"name": "lexer"},
                tool_use_id="d2",
                tool_response="Named.",
                agent_id="th1",
                agent_type="explorer",
                transcript_path=str(rollouts.rollout("th1")),
            ),
        )
    assert main == ""
    assert guide == ""
    assert INVITED not in started
    assert context(first) == INVITED
    assert again == ""
    assert INVITED not in ended
    assert context(codex_first) == INVITED


def test_a_record_a_hook_names_under_another_launch_s_own_directory_is_read_nowhere(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """The service reads a record a hook names only as the launch it heard the hook on has it, by its socket: a room naming its subagent's record under another launch's own runtime directory, where that launch's home holds one naming it, has its subagent go unnamed, as one whose record isn't written yet. The launch whose own directory it is reads it."""
    theirs = Subagents(tmp_path / "one")
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "one" / "first", "one", "claude")
        launched(machine, clock, tmp_path / "two" / "second", "two", "claude")
        hook, hook2 = machine.host.launch("one").hook, machine.host.launch("two").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook2, claude("SessionStart", source="startup", session_id="s2"))
        theirs.recorded("a1", "Explore", "t1", name="parser")
        planted = bash(
            "c1",
            session_id="s2",
            agent_id="a1",
            agent_type="Explore",
            transcript_path=str(theirs.transcript),
        )
        told = context(send(hook2, planted))
        own = context(send(hook, theirs.call("a1", "Explore", "c2")))
    assert told.startswith(introduction())
    assert "lup: you're `second/Explore·a1` for now" in told
    assert own == introduction()


class Rollouts:
    """A Codex session's subagents' rollouts, each headed by its `session_meta`, as Codex keeps them: session `t1`'s own thread is their root."""

    def __init__(self, tmp_path: Path) -> None:
        self.folder = tmp_path / "sessions"
        self.folder.mkdir(parents=True)

    def rollout(self, thread: str) -> Path:
        return self.folder / f"rollout-{thread}.jsonl"

    def recorded(self, thread: str, parent: str, path: str | None = None) -> None:
        """Record thread `thread`, spawned by thread `parent`: with the path the second `spawn_agent` gives, where it's given; with none, as the first spawns."""
        meta: dict[str, JsonValue] = {
            "id": thread,
            "session_id": "t1",
            "parent_thread_id": parent,
            "agent_role": "explorer",
        }
        if path is not None:
            meta["agent_path"] = path
        line = json.dumps({"type": "session_meta", "payload": meta})
        self.rollout(thread).write_text(f"{line}\n")

    def call(self, thread: str, call: str) -> str:
        """A call of subagent `thread`'s starting, naming their own rollout."""
        return codex(
            "PreToolUse",
            tool_name="Bash",
            tool_input={"command": "ls"},
            tool_use_id=call,
            agent_id=thread,
            agent_type="explorer",
            transcript_path=str(self.rollout(thread)),
        )

    def ended(self, thread: str, parent: str, said: str, *, again: bool = False) -> str:
        """Subagent `thread`'s turn ending, saying `said`: naming their parent's rollout, and their own beside it; `again` where a hook held their last end."""
        return codex(
            "SubagentStop",
            agent_id=thread,
            agent_type="explorer",
            transcript_path=str(self.rollout(parent)),
            agent_transcript_path=str(self.rollout(thread)),
            last_assistant_message=said,
            stop_hook_active=again,
        )

    def lup(
        self,
        hooks: tuple[Path, Path],
        tool: str,
        arguments: dict[str, JsonValue],
        thread: str,
    ) -> tuple[str, bool]:
        """Call lup's `tool` as subagent `thread` does: its start stamped by the hook on `hooks[0]`, then the call through the tool server on `hooks[1]`."""
        hook, mcp = hooks
        started = codex(
            "PreToolUse",
            tool_name=f"mcp__lup__{tool}",
            tool_input=arguments,
            tool_use_id=f"{thread}-{tool}",
            agent_id=thread,
            agent_type="explorer",
            transcript_path=str(self.rollout(thread)),
        )
        stamped = json.loads(send(hook, started))["hookSpecificOutput"]["updatedInput"]
        return call(mcp, tool, stamped)


def handed(number: int, path: str, name: str) -> str:
    """How item `number` is told: Claude Code's subagent at `path`, called `name`, ended their turn, their last message handed to their parent by Claude Code itself."""
    return (
        f'<ended item="{number}" from="{path}" '
        f'name="{name}">They ended their turn. Their last message reaches you from your '
        "runtime.</ended>"
    )


def test_wait_inbox_returns_when_its_own_subagent_ends_and_never_for_anothers_on_claude_code(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    others = Subagents(tmp_path / "other", session="s2")
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        launched(machine, clock, tmp_path / "x", "two", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        hook2 = machine.host.launch("two").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook2, claude("SessionStart", source="startup", session_id="s2"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        send(hook, records.call("a1", "Explore", "c1"))
        send(hook, records.spawn("t2", agent="a1"))
        records.recorded("a2", "general-purpose", "t2", name="tokens", parent="a1")
        send(hook, records.call("a2", "general-purpose", "c2"))
        send(hook2, others.spawn("t3"))
        others.recorded("b1", "Explore", "t3", name="lexer")
        send(hook2, others.call("b1", "Explore", "c3"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(call, mcp, "wait_inbox", {})
            assert delivery.holding.wait(timeout=60)
            # Another launch's subagent, and the subagent's own: neither is the
            # main conversation's, and the call holds through both.
            send(hook2, others.ended("b1", "Explore", "Lexed."))
            lexer = newest(delivery)
            send(hook, records.ended("a2", "general-purpose", "Found three."))
            tokens = newest(delivery)
            told = send(hook, records.call("a1", "Explore", "c4"))
            send(hook, records.ended("a1", "Explore", "Parsed."))
            parser = newest(delivery)
            returned = waiting.result(timeout=60)
        after = send(hook, bash("m1"))
        elsewhere = delivery.inbox.item(lexer)
    assert context(told) == handed(tokens, "w/parser/tokens", "tokens")
    assert returned == (handed(parser, "w/parser", "parser"), False)
    assert after == ""
    assert elsewhere.recipient == Conversation(
        repository=tmp_path / "x" / ".git", runtime="claude", session="s2"
    )
    assert elsewhere.state == Waiting()


def test_wait_inbox_returns_when_its_own_subagent_fails_on_an_api_error_on_claude_code(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """A subagent whose first request failed, first heard at their `StopFailure`: their parent is told the error's kind, the runtime's notice saying the rest."""
    records = Subagents(tmp_path)
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(call, mcp, "wait_inbox", {})
            assert delivery.holding.wait(timeout=60)
            failed = send(hook, records.failed("a1", "Explore", "rate_limit"))
            returned = waiting.result(timeout=60)
        number = newest(delivery)
        items = list(delivery.inbox.items.values())
    assert failed == ""
    assert returned == (
        (
            f'<ended item="{number}" from="w/parser" name="parser">'
            "They failed on an error from the model's API (rate_limit). Your "
            "runtime's notice of their end says more.</ended>"
        ),
        False,
    )
    # Their failure is the one item made.
    assert [(each.number, each.quiet) for each in items] == [(number, True)]


def test_a_subagents_end_waits_for_its_parents_call_never_holding_its_end_nor_waking_it(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        for agent, kind, call_id in [("a1", "Explore", "t1"), ("a3", "Plan", "t3")]:
            send(hook, records.spawn(call_id))
            records.recorded(agent, kind, call_id)
        send(hook, records.call("a1", "Explore", "c1"))
        send(hook, bash("m1"))
        send(hook, records.ended("a1", "Explore", "Parsed."))
        parsed = newest(delivery)
        ended = send(hook, claude("Stop", stop_hook_active=False))
        # The session idle: a subagent stopped, first heard at their end, and one
        # of Claude Code's own, a suggestion for the operator's next prompt.
        send(hook, records.ended("a3", "Plan", None))
        stopped = newest(delivery)
        own = claude(
            "SubagentStop",
            agent_id="x1",
            agent_type="",
            transcript_path=str(records.transcript),
            last_assistant_message="Run the tests?",
        )
        send(hook, own)
        returned = call(mcp, "wait_inbox", {})
        after = send(hook, bash("m2"))
        items = list(delivery.inbox.items.values())
    assert ended == ""
    assert not [line for line in said if "woke" in line or "woken" in line]
    assert returned == (
        handed(parsed, "w/Explore·a1", "Explore·a1")
        + "\n\n"
        + f'<ended item="{stopped}" from="w/Plan·a3" name="Plan·a3">'
        "They were stopped before they ended their turn.</ended>",
        False,
    )
    assert after == ""
    # Claude Code's own subagent makes no item.
    assert [(each.number, each.quiet) for each in items] == [
        (parsed, True),
        (stopped, True),
    ]


def test_a_stopped_subagent_holds_nothing_and_what_waits_for_it_goes_to_its_session(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        records.lup((hook, mcp), "ask", {"question": "May I?"}, "a1", "Explore")
        question = newest(delivery)
        inbox("answer", str(question), "--comment", "Yes.")
        answer = newest(delivery)
        stopped = send(hook, records.ended("a1", "Explore", None))
        ended = newest(delivery)
        told = send(hook, bash("m1"))
        threads = delivery.inbox.ledger.every(Thread)
    assert stopped == ""
    # Their question landed in no thread, never told the session.
    assert threads == []
    assert context(told) == (
        f'<answer item="{answer}" from="operator" for="w/parser, '
        f'whose conversation had ended" question="{question}">\n'
        f'<asked>May I?</asked>\n<comment id="{answer}.1">Yes.</comment>\n'
        "</answer>\n\n"
        f'<ended item="{ended}" from="w/parser" name="parser">'
        "They were stopped before they ended their turn.</ended>"
    )


def test_wait_inbox_returns_when_its_own_subagent_ends_with_its_last_message_on_codex(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    rollouts = Rollouts(tmp_path)
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "codex")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, codex("SessionStart", source="startup"))
        rollouts.recorded("th1", "t1")
        rollouts.recorded("th2", "th1")
        rollouts.recorded("th3", "t1", "/root/lexer")
        send(hook, rollouts.call("th1", "c1"))
        send(hook, rollouts.call("th2", "c2"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(call, mcp, "wait_inbox", {})
            assert delivery.holding.wait(timeout=60)
            send(hook, rollouts.ended("th2", "th1", "Found three call sites."))
            found = newest(delivery)
            told = send(hook, rollouts.call("th1", "c3"))
            send(hook, rollouts.ended("th1", "t1", "Parsed: three call sites."))
            parsed = newest(delivery)
            returned = waiting.result(timeout=60)
        # One the second `spawn_agent` spawned, first heard at their end: Codex
        # hands their last message to their parent itself.
        send(hook, rollouts.ended("th3", "t1", "Lexed."))
        lexed = newest(delivery)
        at_once = call(mcp, "wait_inbox", {})
        after = send(hook, codex_bash("d1"))
    assert context(told) == (
        f'<ended item="{found}" from="w/th1/explorer·th2" name="explorer·th2">\n'
        "They ended their turn. Their last message:\n"
        "<said>Found three call sites.</said>\n"
        "</ended>"
    )
    assert returned == (
        (
            f'<ended item="{parsed}" from="w/explorer·th1" name="explorer·th1">\n'
            "They ended their turn. Their last message:\n"
            "<said>Parsed: three call sites.</said>\n"
            "</ended>"
        ),
        False,
    )
    assert at_once == (
        (
            f'<ended item="{lexed}" from="w/lexer" name="lexer">'
            "They ended their turn. Their last message reaches you from your runtime."
            "</ended>"
        ),
        False,
    )
    assert after == ""


HELD_BEFORE = (
    "Before that, lup held an end of their turn to tell them what waited, and "
    "no runtime hands you what they said there:"
)
"""What a subagent's end tells their parent before what they said at an end lup held."""


def test_what_a_subagent_said_at_an_end_held_for_what_waited_reaches_its_parent_on_each_runtime(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """Seen in a probe on Claude Code 2.1.303 (`docs/field-notes.md`, *A subagent's end*): held at their end, a subagent goes on, and their runtime hands their parent only what they say at their next end, so the report they ended on first reached no one."""
    records = Subagents(tmp_path)
    rollouts = Rollouts(tmp_path)

    def sent(mcp: Path, to: str) -> None:
        text = "Count the tests too."
        _, error = call(mcp, "send", {"to": to, "kind": "note", "text": text})
        assert not error

    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        launched(machine, clock, tmp_path / "v", "two", "codex")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        hook2, mcp2 = machine.host.launch("two").hook, machine.host.launch("two").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook2, codex("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        send(hook, records.call("a1", "Explore", "c1"))
        sent(mcp, "parser")
        held = send(hook, records.ended("a1", "Explore", "Parsed: three call sites."))
        let = send(
            hook, records.ended("a1", "Explore", "And twelve tests.", again=True)
        )
        told = context(send(hook, bash("m1")))
        # The first `spawn_agent`'s subagent, whose last message Codex hands on
        # to no one.
        rollouts.recorded("th1", "t1")
        send(hook2, rollouts.call("th1", "d1"))
        sent(mcp2, "th1")
        held2 = json.loads(send(hook2, rollouts.ended("th1", "t1", "Lexed: two.")))
        let2 = send(hook2, rollouts.ended("th1", "t1", "And one more.", again=True))
        told2 = context(send(hook2, codex_bash("e1")))
        places = [
            each.held for each in delivery.inbox.whereabouts.values() if each.ended
        ]
        # On each runtime, what's sent the subagent and the operator's copy of
        # it, then their end let through: an end held makes no item.
        _, _, parsed, _, _, lexed = numbers(delivery)
    assert "Count the tests too." in context(held)
    assert let == ""
    assert told == (
        f'<ended item="{parsed}" from="w/parser" name="parser">\n'
        "They ended their turn. Their last message reaches you from your runtime.\n"
        f"{HELD_BEFORE}\n"
        "<said>Parsed: three call sites.</said>\n"
        "</ended>"
    )
    assert "Count the tests too." in held2["reason"]
    assert let2 == ""
    assert told2 == (
        f'<ended item="{lexed}" from="v/explorer·th1" name="explorer·th1">\n'
        "They ended their turn. Their last message:\n"
        "<said>And one more.</said>\n"
        f"{HELD_BEFORE}\n"
        "<said>Lexed: two.</said>\n"
        "</ended>"
    )
    # Once handed on, what they said is no longer kept for an end to come.
    assert places == [[], []]


@pytest.mark.parametrize("reach", ["operator", "operator and parent"])
def test_a_subagents_friction_reaches_its_parent_whole_and_how_it_felt_where_lup_passes_it_on(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
    reach: Reach,
) -> None:
    class Speaking(Speaker):
        how_it_felt_reaches: Reach = reach

    monkeypatch.setattr(tools, "Speaker", Speaking)
    records = Subagents(tmp_path)
    rollouts = Rollouts(tmp_path)
    jammed: dict[str, JsonValue] = {
        "text": (
            "`uv run lup-dev check` printed: engine stale\n"
            "The brief said the engine was built."
        )
    }
    went: dict[str, JsonValue] = {"text": "The brief was clear, and it felt good."}
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        launched(machine, clock, tmp_path / "v", "two", "codex")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        hook2, mcp2 = machine.host.launch("two").hook, machine.host.launch("two").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook2, codex("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        rollouts.recorded("th1", "t1", "/root/lexer")
        jam = records.lup((hook, mcp), "friction", jammed, "a1", "Explore")
        how = rollouts.lup((hook2, mcp2), "how_it_felt", went, "th1")
        ended = send(hook, claude("Stop", stop_hook_active=False))
        told = context(send(hook, bash("m1")))
        heard2 = send(hook2, codex_bash("d1"))
        operators = [each.number for each in delivery.inbox.waiting(Operator())]
        items = list(delivery.inbox.items.values())
        # The friction and their parent's copy of it, then how it felt, with
        # their parent's copy where lup passes it on.
        reported, copied, felt, *passed = numbers(delivery)
        described = next(
            each.description for each in specs() if each.name == "how_it_felt"
        )
    friction = Friction.model_validate(jammed)
    how_it_felt = HowItFelt.model_validate(went)
    assert jam == (
        f"Thanks: your friction is with the operator, @{reported}, and your parent has it too. You can carry on.",
        False,
    )
    assert ended == ""
    assert told.startswith(f'<item item="{copied}" from="w/parser" kind="friction">')
    assert friction.text in told
    assert operators == [reported, felt]
    copies = [
        (each.reason, each.quiet) for each in items if each.recipient != Operator()
    ]
    if reach == "operator":
        # How it felt is told to the operator alone, and its description says so,
        # and that it isn't private, which no reach changes.
        assert how == (
            f"Thank you for telling them. It's with the operator, as you wrote it, @{felt}.",
            False,
        )
        assert heard2 == ""
        assert passed == []
        assert copies == [(friction, True)]
        assert described.endswith(
            "\n\nIt reaches the operator as you wrote it, and nobody else is told. "
            "It isn't private: other sessions can read it, as they can the rest of "
            "the inbox."
        )
    else:
        assert how == (
            f"Thank you for telling them. It's with the operator, and your parent has it too, as you wrote it, @{felt}.",
            False,
        )
        told2 = context(heard2)
        [passed_on] = passed
        assert told2.startswith(
            f'<item item="{passed_on}" from="v/lexer" kind="how it felt">'
        )
        assert how_it_felt.text in told2
        assert copies == [(friction, True), (how_it_felt, True)]
        assert described.endswith(
            "your parent too, whole, at their next call. It isn't private: other "
            "sessions can read it, as they can the rest of the inbox."
        )


def to_parent(text: str, kind: str = "note") -> dict[str, JsonValue]:
    """A `send` to the conversation that spawned the caller."""
    return {"to": "parent", "kind": kind, "text": text}


def arriving(whose: str, number: int, idle: str = "") -> str:
    """What `send` answers for a message to another conversation, item `number`."""
    return (
        f"Your message is in the inbox of {whose}, {cited(number)}. It's told at their "
        f"next call, their turn's end or their `wait_inbox`, whichever comes first{idle}."
    )


WOKEN = "; idle between turns, their session is woken for it"
"""What `send`'s answer adds for a main conversation whose runtime wakes them."""


def test_what_a_subagent_tells_their_parent_is_no_item_of_the_operator_s_and_what_they_tell_the_operator_is(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    worktree = tmp_path / "w"
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, worktree, "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        send(hook, records.call("a1", "Explore", "c1"))

        def called(tool: str, **given: JsonValue) -> None:
            records.lup((hook, mcp), tool, given, "a1", "Explore")

        called("send", to="parent", kind="problem", text="To my parent.")
        called("send", to="operator", kind="note", text="To the operator.")
        called("note", remark="A doubt.")
        called("friction", text="The gate hung.")
        called("how_it_felt", text="Calm.")
        waiting = delivery.inbox.waiting(Operator())
        every = list(delivery.inbox.items.values())
    assert [(type(each.reason).__name__, each.rank.name) for each in waiting] == [
        ("Message", "news"),
        ("Message", "news"),
        ("Friction", "news"),
        ("HowItFelt", "news"),
    ]
    [message, copy] = [
        each
        for each in every
        if isinstance(each.reason, Message) and each.reason.text == "To my parent."
    ]
    assert isinstance(message.recipient, Conversation)
    assert isinstance(copy.state, Done)
    assert copy.recipient == Operator()
    # A copy raises no notice, and the operator's words in a review answer the message's sender as any item's.
    assert notices.raised == []


def test_a_subagent_tells_its_parent_at_its_next_call_and_the_operator_s_copy_waits_on_nobody(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    found = "The brief said the engine was built. It isn't: I'm building it first."
    worktree = tmp_path / "w"
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, worktree, "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        send(hook, records.call("a1", "Explore", "c1"))
        send(hook, bash("m1"))
        sent = records.lup(
            (hook, mcp), "send", to_parent(found, "problem"), "a1", "Explore"
        )
        # The message, and the operator's copy of it.
        message, copy = numbers(delivery)
        told = context(send(hook, bash("m2")))
        listed = inbox()
        shown = inbox("show", str(copy))
        theirs = records.lup((hook, mcp), "inbox", {"every": True}, "a1", "Explore")
        unwithdrawn = [
            records.lup(
                (hook, mcp), "withdraw", {"number": number, "why": "x"}, "a1", "Explore"
            )
            for number in [message, copy]
        ]
        inbox("answer", str(copy), "--comment", "Good catch.")
        reply = newest(delivery)
        replied = context(send(hook, records.call("a1", "Explore", "c2")))
        items = [delivery.inbox.item(number) for number in [message, copy]]
        made = numbers(delivery)
    assert sent == (arriving("your parent `w`", message, WOKEN), False)
    assert told == (
        f'<message item="{message}" from="w/parser" kind="problem">{found}</message>'
    )
    # What one agent tells another is no item of the operator's: it's in both agents' drawers.
    assert f"@{copy}" not in listed
    assert shown == (
        f"@{copy}, a problem from `w/parser` in {worktree} to `w`, your copy, made "
        f"{clocked(clock.now())}, done at {clocked(clock.now())}:\n{found}\n"
    )
    # The subagent's own `inbox` lists their message, and the copy as whom it went to.
    assert theirs == (
        "\n".join(
            [
                (
                    f"@{message}  {clocked(clock.now())}  a problem from you to "
                    f"`w`, told at {clocked(clock.now())} (call): {found}"
                ),
                (
                    f"@{copy}  {clocked(clock.now())}  a problem from you to `w`, "
                    f"the operator's copy, done at {clocked(clock.now())}: {found}"
                ),
            ]
        ),
        False,
    )
    # The copy raises no notice, whatever its kind: it waits on the parent, not the operator.
    assert notices.raised == []
    assert [each.reason for each in items] == [
        Message(kind="problem", text=found),
        Message(
            kind="problem",
            text=found,
            to=Conversation(
                repository=worktree / ".git", runtime="claude", session="s1"
            ),
        ),
    ]
    assert items[1].rank.name == "news"
    assert [each.recipient for each in items] == [
        Conversation(repository=worktree / ".git", runtime="claude", session="s1"),
        Operator(),
    ]
    assert unwithdrawn == [
        (
            (
                f"Not withdrawn: @{number} is your message to `w`, which the operator "
                "reads a copy of: neither is withdrawn. Where it was wrong, `send` a "
                "correction"
            ),
            False,
        )
        for number in [message, copy]
    ]
    # Neither refused withdrawal made an item.
    assert made == [message, copy, reply]
    # The operator's reply to the copy reaches the subagent that sent it.
    assert replied == (
        f'<message item="{reply}" from="operator" kind="note">\n'
        f'<on item="{copy}" kind="problem">'
        f"\n<opening>{found}</opening>\n"
        f'<comment id="{reply}.1">Good catch.</comment>\n</on>\n</message>'
    )


def test_send_reaches_ones_own_subagents_by_name_path_or_id_and_refuses_whom_nothing_reads(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)

    def sent(to: str, text: str) -> tuple[str, bool]:
        return call(mcp, "send", {"to": to, "kind": "note", "text": text})

    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        send(hook, records.call("a1", "Explore", "c1"))
        send(hook, records.spawn("t2", agent="a1"))
        records.recorded("a2", "general-purpose", "t2", name="tokens", parent="a1")
        send(hook, records.call("a2", "general-purpose", "c2"))
        by_name = sent("parser", "By name.")
        by_path = sent("w/parser", "By path.")
        by_id = sent("a1", "By id.")
        grandchild = sent("tokens", "Not mine.")
        orphan = sent("parent", "Nobody.")
        told = context(send(hook, records.call("a1", "Explore", "c3")))
        down = records.lup(
            (hook, mcp),
            "send",
            {"to": "tokens", "kind": "note", "text": "Look at the lexer."},
            "a1",
            "Explore",
        )
        held = send(hook, records.ended("a2", "general-purpose", "Looking."))
        send(hook, records.ended("a2", "general-purpose", "Done."))
        gone = records.lup(
            (hook, mcp),
            "send",
            {"to": "tokens", "kind": "note", "text": "And the parser."},
            "a1",
            "Explore",
        )
        send(hook, records.call("a2", "general-purpose", "c4"))
        resumed = records.lup(
            (hook, mcp),
            "send",
            {"to": "w/parser/tokens", "kind": "note", "text": "And the parser."},
            "a1",
            "Explore",
        )
        records.lup((hook, mcp), "rename", {"name": "lexing"}, "a1", "Explore")
        send(hook, records.call("a1", "Explore", "c5"))
        renamed = sent("lexing", "Renamed.")
        threads = delivery.inbox.ledger.every(Thread)
        # Each message sent, and the operator's copy of it after it; the
        # subagent's end, told their parent; and nothing for a send refused.
        (
            to_name,
            _,
            to_path,
            _,
            to_id,
            _,
            to_tokens,
            _,
            tokens_ended,
            to_resumed,
            _,
            to_renamed,
            _,
        ) = numbers(delivery)
        ending = delivery.inbox.item(tokens_ended).reason
    yours = (
        "`to` takes `operator`, or one of your own subagents by their name, their "
        "path or their runtime's id: `parser`."
    )
    assert by_name == (arriving("your subagent `w/parser`", to_name), False)
    # Each copy lands in no thread.
    assert threads == []
    assert by_path == (arriving("your subagent `w/parser`", to_path), False)
    assert by_id == (arriving("your subagent `w/parser`", to_id), False)
    assert grandchild == (f"Not sent: no subagent of yours is `tokens`. {yours}", False)
    assert orphan == (
        f"Not sent: no conversation spawned you, so you have no parent. {yours}",
        False,
    )
    assert told == "\n\n".join(
        f'<message item="{number}" from="w" kind="note">{text}</message>'
        for number, text in [
            (to_name, "By name."),
            (to_path, "By path."),
            (to_id, "By id."),
        ]
    )
    assert down == (arriving("your subagent `w/parser/tokens`", to_tokens), False)
    # The subagent's end is held once to tell what their parent sent them.
    assert "Look at the lexer." in held
    assert gone == (
        (
            f"Not sent: your subagent `w/parser/tokens` ended at {clocked(clock.now())}, so "
            "nothing reads their inbox: once their runtime resumes them, lup hears them "
            "again and they can be sent to"
        ),
        False,
    )
    # Resumed, they're heard again, and reached; their parent was told their end.
    assert isinstance(ending, Ended)
    assert resumed == (arriving("your subagent `w/parser/tokens`", to_resumed), False)
    # A subagent who renamed themselves is reached by their new name once they're heard.
    assert renamed == (arriving("your subagent `w/lexing`", to_renamed), False)


def test_a_subagents_message_wakes_its_idle_claude_session(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        send(hook, records.call("a1", "Explore", "c1"))
        assert send(hook, claude("Stop", stop_hook_active=False)) == ""
        sent = records.lup((hook, mcp), "send", to_parent("Found it."), "a1", "Explore")
        # The message, and the operator's copy of it.
        message, _ = numbers(delivery)
        state = delivery.inbox.item(message).state
    assert sent == (arriving("your parent `w`", message, WOKEN), False)
    # Pushed to the session, it waits until a turn's start carries the push's token.
    assert f"one: pushed @{message} to `w`" in said
    assert state == Waiting()


def test_on_codex_a_subagents_message_holds_its_parents_turns_end_and_waits_for_its_next_turn_when_idle(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    rollouts = Rollouts(tmp_path)
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "v", "two", "codex")
        hook, mcp = machine.host.launch("two").hook, machine.host.launch("two").mcp
        messages = Socket(machine.host.launch("two").messages)
        send(hook, codex("SessionStart", source="startup"))
        rollouts.recorded("th1", "t1", "/root/lexer")
        send(hook, rollouts.call("th1", "d1"))
        send(hook, codex_bash("m1"))
        first = rollouts.lup(
            (hook, mcp), "send", to_parent("Not this way.", "disagreement"), "th1"
        )
        held = json.loads(send(hook, codex("Stop", stop_hook_active=False)))
        let = send(hook, codex("Stop", stop_hook_active=True))
        second = rollouts.lup((hook, mcp), "send", to_parent("Found it."), "th1")
        started = context(send(hook, codex("UserPromptSubmit", prompt="Go on.")))
        frames = messages.close()
        # Each message, and the operator's copy of it.
        disagreement, _, found, _ = numbers(delivery)
    idle = (
        "; idle between turns, it waits for the session's next turn, since their "
        "runtime can't be woken"
    )
    assert first == (arriving("your parent `v`", disagreement, idle), False)
    assert held["decision"] == "block"
    assert held["reason"] == (
        f'<message item="{disagreement}" from="v/lexer" kind="disagreement">'
        "Not this way.</message>"
    )
    assert let == ""
    assert second == (arriving("your parent `v`", found, idle), False)
    assert frames == []
    assert started == (
        f'<message item="{found}" from="v/lexer" kind="note">Found it.</message>'
    )


def test_lup_dev_inbox_send_names_a_launch_by_its_id_or_its_worktree(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        by_worktree = inbox("send", str(tmp_path), "By its worktree.")
        number = newest(delivery)
        nowhere = runner.invoke(cli.app, ["inbox", "send", "nowhere", "x"])
        launched(machine, clock, tmp_path, "two", "claude")
        several = runner.invoke(cli.app, ["inbox", "send", str(tmp_path), "x"])
        unheard = refused("send", "two", "x")
    assert by_worktree == f"Sent @{number} to `{tmp_path.name}`.\n"
    assert isinstance(nowhere.exception, InboxError)
    assert (
        str(nowhere.exception)
        == "no launch served is `nowhere`, by its name, its id or its worktree"
    )
    assert str(several.exception) == (
        f"several launches run: `{tmp_path.name}` (one, in {tmp_path}), "
        f"`{tmp_path.name}-2` (two, in {tmp_path}); name one"
    )
    assert unheard == (
        "no session of launch `two` has reached lup yet, so nothing there can be told"
    )


def test_lup_dev_mount_lends_a_directory_to_a_running_room_and_tells_its_session(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[list[str]] = []

    def recorded(process: Process) -> Ran:
        ran.append(process.arguments)
        return Ran(command=process.arguments, status=0)

    monkeypatch.setattr(cli, "Podman", lambda: Podman(execute=recorded))
    own = machine.launch("one")
    for each in [own.lent, own.stage]:
        each.mkdir(parents=True)
    atlas = tmp_path / "atlas"
    atlas.mkdir()
    data = machine.module_data("transcripts", tmp_path / ".git")
    data.mkdir(parents=True)
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        sealed = runner.invoke(cli.app, ["mount", str(atlas)])
        open_ = runner.invoke(cli.app, ["mount", "--rw", str(atlas), "--launch", "one"])
        module = runner.invoke(cli.app, ["mount", "transcripts", "--launch", "one"])
        nothing = runner.invoke(cli.app, ["mount", "nowhere", "--launch", "one"])
        # Each directory lent is told the session in an item of its own; the
        # mount that failed makes none.
        lent, _, lent_module = numbers(delivery)
        texts = [delivery.inbox.item(number).reason for number in [lent, lent_module]]

    assert sealed.output == (
        f"Lent {atlas} to launch one, read-only, at /lent/atlas in its room; "
        f"@{lent} tells its session.\n"
    )
    assert "writable, at /lent/atlas-2 in its room" in open_.output
    assert "read-only, at /lent/transcripts in its room" in module.output
    assert isinstance(nothing.exception, RoomError)
    staged = str(own.stage / "atlas")
    assert ran[:4] == [
        ["podman", "unshare", "mount", "--bind", str(atlas), staged],
        ["podman", "unshare", "mount", "-o", "remount,bind,ro", staged],
        ["podman", "unshare", "mount", "--bind", staged, str(own.lent / "atlas")],
        ["podman", "unshare", "umount", staged],
    ]
    assert ran[4] == [
        "podman",
        "unshare",
        "mount",
        "--bind",
        str(atlas),
        str(own.lent / "atlas-2"),
    ]
    assert isinstance(texts[0], Message)
    assert texts[0].text == (
        f"The operator lent `{atlas}` to this session, read-only, at "
        "`/lent/atlas`: it's there now, until the session ends."
    )
    assert isinstance(texts[1], Message)
    assert texts[1].text.startswith(
        f"The operator lent the `transcripts` module's data (`{data}`) to this "
        "session, read-only, at `/lent/transcripts`"
    )


def test_lup_dev_mount_refuses_a_room_that_started_before_it_could_receive(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        result = runner.invoke(cli.app, ["mount", str(tmp_path), "--launch", "one"])
    assert isinstance(result.exception, RoomError)
    assert "started before a running room could be lent a directory" in str(
        result.exception
    )


SESSIONS = [("CLAUDE_CODE_CHILD_SESSION", "claude"), ("CODEX_THREAD_ID", "codex")]
"""Each runtime's variable saying a command runs inside one of its sessions, and the runtime's name."""

READING = [
    ["sessions"],
    ["inbox"],
    ["inbox", "show", "1"],
    ["inbox", "show", "1", "--diff"],
    ["inbox", "show", "1", "--context"],
]
"""The commands that only read lup's state, which an agent's session on the host runs."""


class Recording(Starter):
    """Starts nothing, and counts each time it's asked to."""

    def __init__(self) -> None:
        self.starts = 0

    @override
    def start(self, log: Path) -> None:
        self.starts += 1


@pytest.mark.parametrize(("variable", "runtime"), SESSIONS)
@pytest.mark.parametrize(
    "arguments",
    [["answer", "1", "--comment", "x"], ["done", "1"], ["send", "one", "x"]],
)
def test_lup_dev_inbox_refuses_to_act_inside_an_agents_session(
    machine: Layout,
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    runtime: str,
    arguments: list[str],
) -> None:
    monkeypatch.setenv(variable, "1")
    result = runner.invoke(cli.app, ["inbox", *arguments])
    assert isinstance(result.exception, InboxError)
    assert str(result.exception) == (
        f"this runs inside a {runtime} session, and the inbox is the operator's: run "
        "it in your own terminal"
    )
    assert not machine.host.control.exists()


@pytest.mark.parametrize("variable", [variable for variable, _ in SESSIONS])
def test_an_agents_session_on_the_host_lists_the_sessions_and_the_inbox_and_shows_an_item(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
) -> None:
    podman_having(monkeypatch, "lup-one")
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        stamped = json.loads(send(hook, lup_call("note", {"remark": "Mine."}, "n1")))[
            "hookSpecificOutput"
        ]["updatedInput"]
        call(machine.host.launch("one").mcp, "note", stamped)
        number = newest(delivery)
        monkeypatch.setenv(variable, "1")
        listing = runner.invoke(cli.app, ["sessions"])
        listed = inbox()
        shown = inbox("show", str(number))
    assert listing.exit_code == 0, (listing.output, listing.exception)
    assert listing.output.splitlines()[0] == (
        f"`w`  claude in {tmp_path / 'w'}  (one)  container lup-one, running"
    )
    assert listed == (
        f"{cited(number):>5}  2026-10-01 12:00  a note from `w` in "
        f"{tmp_path / 'w'}: Mine.\n"
    )
    assert shown == (
        f"@{number}, a note from `w` in {tmp_path / 'w'} to the operator, "
        "made 2026-10-01 12:00, waiting:\nMine.\n"
    )


@pytest.mark.parametrize(("variable", "runtime"), SESSIONS)
@pytest.mark.parametrize("arguments", READING)
def test_a_reading_command_in_an_agents_session_says_no_service_runs_and_starts_none(
    machine: Layout,
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    runtime: str,
    arguments: list[str],
) -> None:
    starter = Recording()

    def starting(layout: Layout) -> Recording:
        del layout
        return starter

    monkeypatch.setattr(cli, "host_starter", starting)
    monkeypatch.setenv(variable, "1")
    result = runner.invoke(cli.app, arguments)
    assert isinstance(result.exception, HostError), (result.output, runtime)
    assert str(result.exception) == (
        "no host service runs, and none is started from an agent's session: a launch "
        "starts it, or the operator's own `lup-dev` in their terminal"
    )
    assert starter.starts == 0


@pytest.mark.parametrize("arguments", READING)
def test_a_reading_command_in_the_operators_terminal_starts_the_service_where_none_runs(
    machine: Layout, monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    starter = Recording()

    def starting(layout: Layout) -> Recording:
        del layout
        return starter

    monkeypatch.setattr(cli, "host_starter", starting)
    result = runner.invoke(cli.app, arguments)
    assert isinstance(result.exception, HostError)
    assert "the host service didn't answer" in str(result.exception)
    assert starter.starts == 1


def in_room(monkeypatch: pytest.MonkeyPatch, machine: Layout, launch: str) -> None:
    """Run `lup-dev` as in the room of launch `launch`, on the request socket its room mounts."""
    socket = machine.host.launch(launch).request
    monkeypatch.setattr(cli, "RoomClient", lambda: RoomClient(socket=socket))


def approval(repository: Path, worktree: Path, question: str) -> AskApproval:
    """An approval of `repository`'s host zone, asked from `worktree`, its diff naming the question."""
    return AskApproval(
        question=question,
        summary="One file.",
        diff=f"diff for {question}\n",
        files=[],
        repository=repository,
        fingerprint=question,
        worktree=worktree,
    )


def recording(home: Path, session: str, ran: Path, call: str) -> None:
    """Keep a Claude Code record of session `session` under `home`, run in `ran`: the operator's words, then a call to lup's `note` with the id `call`."""
    folder = home / "projects" / "-w"
    folder.mkdir(parents=True, exist_ok=True)
    when: dict[str, JsonValue] = {
        "timestamp": "2026-10-17T12:00:00.000Z",
        "cwd": str(ran),
    }
    lines: list[dict[str, JsonValue]] = [
        {
            **when,
            "type": "user",
            "origin": {"kind": "human"},
            "message": {"role": "user", "content": "Note it."},
        },
        {
            **when,
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": call,
                        "name": "mcp__lup__note",
                        "input": {},
                    }
                ],
            },
        },
    ]
    (folder / f"{session}.jsonl").write_text(
        "".join(f"{json.dumps(each)}\n" for each in lines)
    )


@pytest.mark.parametrize("variable", [variable for variable, _ in SESSIONS])
def test_a_room_lists_and_shows_its_repositorys_sessions_and_items_alone(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    repo: Path,
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
) -> None:
    home = tmp_path / "claude"
    recording(home, "s1", repo, "n1")
    recorded = {
        "claude": Recorded(
            records=ClaudeRecords(directory=home), reader=ClaudeTranscripts()
        )
    }
    other = tmp_path / "other"
    other.mkdir()
    with inboxed(
        machine, clock, notices, said, recorded, podman=podman_of("lup-one")
    ) as delivery:
        launched(machine, clock, repo, "one", "claude")
        launched(machine, clock, other, "two", "codex")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        send(machine.host.launch("two").hook, codex("SessionStart", source="startup"))
        stamped = json.loads(send(hook, lup_call("note", {"remark": "Mine."}, "n1")))[
            "hookSpecificOutput"
        ]["updatedInput"]
        call(machine.host.launch("one").mcp, "note", stamped)
        my_note = newest(delivery)
        call(machine.host.launch("two").mcp, "note", {"remark": "Theirs."})
        their_note = newest(delivery)
        host = client(machine.host, clock)
        my_approval = host.ask(
            approval(repo / ".git", repo, "Approve mine?"), Shown
        ).item.number
        their_approval = host.ask(
            approval(other / ".git", other, "Approve theirs?"), Shown
        ).item.number
        everything = runner.invoke(cli.app, ["inbox"])
        in_room(monkeypatch, machine, "one")
        monkeypatch.setenv(variable, "1")
        listing = runner.invoke(cli.app, ["sessions"])
        listed = inbox()
        shown = inbox("show", str(my_note))
        diff = inbox("show", str(my_approval), "--diff")
        moment = inbox("show", str(my_note), "--context")
        theirs = [
            refused("show", str(their_note)),
            refused("show", str(their_note), "--context"),
            refused("show", str(their_approval), "--diff"),
        ]
        done = runner.invoke(cli.app, ["inbox", "done", str(my_note)])
    assert everything.exit_code == 0, everything.output
    assert [each.split()[0] for each in everything.output.splitlines()] == [
        f"@{number}" for number in [my_note, their_note, my_approval, their_approval]
    ]
    assert listing.exit_code == 0, (listing.output, listing.exception)
    assert listing.output == (
        f"`work`  claude in {repo}  (one)  container lup-one, running\n  work\n"
    )
    assert [each.split()[0] for each in listed.splitlines()] == [
        f"@{my_note}",
        f"@{my_approval}",
    ]
    assert "Theirs." not in listed
    assert shown.endswith(":\nMine.\n")
    assert diff.strip() == "diff for Approve mine?"
    assert "→ called mcp__lup__note: this item" in moment
    assert theirs == [
        f"@{their_note} isn't this repository's",
        f"@{their_note} isn't this repository's",
        f"@{their_approval} isn't this repository's",
    ]
    assert isinstance(done.exception, InboxError)


def test_the_operator_s_words_read_back_in_their_own_words_never_in_the_tags_an_agent_is_told(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    worktree = tmp_path / "w"
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, worktree, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        party = Conversation(
            repository=worktree / ".git", runtime="claude", session="s1"
        )
        asked = delivery.inbox.made(
            Message(kind="note", text="Which parser?"),
            party,
            Operator(),
            worktree,
            clock.now(),
        )
        review = delivery.inbox.made(
            Review(
                covers=[asked.number],
                comments=[
                    Comment(
                        item=asked.number,
                        quote=Quote(text="Which parser?", start=0, end=13),
                        text="The fast one.",
                    )
                ],
                letters=[Letter(to=party, text="And rename it.")],
            ),
            Operator(),
            party,
            None,
            clock.now(),
        )
        which = delivery.inbox.made(
            Question(
                text="Which reader?",
                decisions=[Decision(text="A model per kind", lean="yes")],
            ),
            party,
            Operator(),
            worktree,
            clock.now(),
        )
        answer = delivery.inbox.made(
            Answer(
                question=which.number,
                rulings=[Ruling(decision=1, verdict="leaning", comment="Fine.")],
            ),
            Operator(),
            party,
            None,
            clock.now(),
        )
        read = delivery.read_back(review)
        told = delivery.words(review)
        answered = delivery.read_back(answer)
    assert "<reply" in told
    assert read == "And rename it.\n\n> Which parser?\n\nThe fast one."
    # What each decision was, and their verdict: what it asked is above it.
    assert answered == (
        "> 1. A model per kind\n\nleaning: they go with the lean\n\nFine."
    )


def test_a_room_reads_its_repositorys_conversations_alone_and_never_the_operators_drafts(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    repo: Path,
    *,
    tmp_path: Path,
) -> None:
    home = tmp_path / "claude"
    other = tmp_path / "other"
    recording(home, "s1", repo, "n1")
    recording(home, "s9", other, "n9")
    recorded = {
        "claude": Recorded(
            records=ClaudeRecords(directory=home), reader=ClaudeTranscripts()
        )
    }
    mine = Conversation(repository=repo / ".git", runtime="claude", session="s1")
    elsewhere = Conversation(repository=other / ".git", runtime="claude", session="s9")
    with inboxed(machine, clock, notices, said, recorded):
        launched(machine, clock, repo, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        room = RoomClient(socket=machine.host.launch("one").request)
        read = room.ask(ShowConversation(runtime="claude", session="s1"), Conversed)
        items = room.ask(ListItems(conversation=mine), Exchanged)
        holding = room.ask(ShowHolding(runtime="claude", session="s1"), Holding)
        refusals: list[str] = []
        for request in [
            ShowConversation(runtime="claude", session="s9"),
            ListItems(conversation=elsewhere),
            ShowGathering(sender=elsewhere, worktree=other, path=Path("a.py")),
            ShowDraft(),
            ShowTalk(conversation=mine),
            ShowOrder(),
        ]:
            with pytest.raises(HostError) as refusal:
                room.ask(request, Conversed)
            refusals.append(str(refusal.value))
    assert read.total == 2
    assert (items.sent, items.received) == ([], [])
    assert holding == Holding(on=False)
    assert refusals == [
        "the conversation isn't one of this repository's",
        "the conversation isn't one of this repository's",
        "the conversation isn't one of this repository's",
        "the operator's draft reply is theirs until they send it",
        "what the operator writes on a conversation is theirs until they send it",
        "the operator's review is theirs, across every repository",
    ]


def test_a_room_reads_no_moment_of_a_session_it_claims_from_another_repository(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    repo: Path,
    *,
    tmp_path: Path,
) -> None:
    """A room's hook names whatever session it likes, so its items can claim a host session's or another project's room's: the moment of each is read only where its record ran in the asker's repository."""
    operators = tmp_path / "claude"
    elsewhere = tmp_path / "elsewhere"
    theirs = tmp_path / "b" / "other"
    theirs.mkdir(parents=True)
    recording(repo.parent, "s1", repo, "n1")
    recording(operators, "s9", elsewhere, "n9")
    recording(theirs.parent, "s8", theirs, "n8")
    recorded = {
        "claude": Recorded(
            records=ClaudeRecords(directory=operators, host=machine.host),
            reader=ClaudeTranscripts(),
        )
    }
    with inboxed(machine, clock, notices, said, recorded) as delivery:
        launched(machine, clock, repo, "one", "claude")
        launched(machine, clock, theirs, "two", "claude")
        hook = machine.host.launch("one").hook
        send(machine.host.launch("two").hook, claude("SessionStart", session_id="s8"))
        for session, key in [("s1", "n1"), ("s9", "n9"), ("s8", "n8")]:
            send(hook, claude("SessionStart", source="startup", session_id=session))
            stamped = json.loads(
                send(hook, lup_call("note", {"remark": key}, key, session_id=session))
            )["hookSpecificOutput"]["updatedInput"]
            call(machine.host.launch("one").mcp, "note", stamped)
        # Each session's note, in turn: s1's, run in the asker's repository;
        # then those of the sessions it claims, s9's on the host and s8's in
        # another project's room.
        own, *claimed = numbers(delivery)
        room = RoomClient(socket=machine.host.launch("one").request)
        mine = room.ask(ShowContext(number=own), Context)
        refusals: list[str] = []
        for number in claimed:
            with pytest.raises(HostError) as refusal:
                room.ask(ShowContext(number=number), Context)
            refusals.append(str(refusal.value))
        host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
        operator = [host.ask(ShowContext(number=number), Context) for number in claimed]
    assert [each.text for each in mine.entries if isinstance(each, Said)] == [
        "Note it."
    ]
    assert refusals == [
        "the conversation isn't one of this repository's",
        "the conversation isn't one of this repository's",
    ]
    # An anchor is the call's place among a moment's entries, not an item's number.
    assert [each.anchor for each in operator] == [1, 1]


def test_a_room_is_told_how_far_the_operator_has_seen_its_repositorys_groups_alone(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    repo: Path,
    *,
    tmp_path: Path,
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, repo, "one", "claude")
        launched(machine, clock, other, "two", "codex")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        send(machine.host.launch("two").hook, codex("SessionStart", source="startup"))
        call(machine.host.launch("one").mcp, "note", {"remark": "Ours."})
        ours = newest(delivery)
        call(machine.host.launch("two").mcp, "note", {"remark": "Theirs."})
        theirs = newest(delivery)
        host = client(machine.host, clock)
        listed = host.ask(ListInbox(), Items)
        for each in listed.items:
            assert isinstance(each.sender, Conversation)
            host.ask(
                MoveMarks(
                    repository=each.sender.repository,
                    module=CORE,
                    marks=[Moving(key=seen(each.sender), up_to=str(each.number))],
                ),
                MarksMoved,
            )
        operator = host.ask(ListInbox(), Items)
        room = RoomClient(socket=machine.host.launch("one").request).ask(
            ListInbox(), Items
        )
    assert [each.item for each in operator.seen] == [ours, theirs]
    assert [each.item for each in room.seen] == [ours]


class Unknown(Request, reads=True):
    """A kind no handler answers, whose refusal names every kind the socket answers."""

    kind: Literal["unknown"] = "unknown"


def answered_kinds(refusal: HostError) -> set[str]:
    """Return the kinds a socket answers, as its refusal of a kind it doesn't names them."""
    _, known = str(refusal).split(" answers ")
    return set(known.split(", "))


def marks() -> dict[str, bool]:
    """Return whether each request model's kind only reads, by its kind: every model with a kind of its own."""

    def below(model: type[Request]) -> list[type[Request]]:
        return [
            each for child in model.__subclasses__() for each in [child, *below(child)]
        ]

    return {
        model.named(): model.reads
        for model in below(Request)
        if isinstance(model.model_fields["kind"].default, str)
    }


def test_a_room_is_served_every_control_kind_that_reads_and_none_that_writes(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        with pytest.raises(HostError) as control:
            client(machine.host, clock).ask(Unknown(), Shown)
        with pytest.raises(HostError) as room:
            RoomClient(socket=machine.host.launch("one").request).ask(Unknown(), Shown)
    controls = answered_kinds(control.value)
    rooms = answered_kinds(room.value)
    marked = marks()
    assert controls <= set(marked)
    assert {kind for kind in controls if marked[kind]} <= rooms
    assert {kind for kind in controls if not marked[kind]} & rooms == set()
    assert {"inbox-list", "inbox-show", "list"} <= rooms
    assert {"inbox-answer", "inbox-send", "dashboard", "stop"} <= controls - rooms


class Older(RoomClient):
    """A room's client whose service runs a copy from before rooms could ask what reads: it knows none of those kinds."""

    @override
    def ask[R: Reply](self, request: Request, reply: type[R]) -> R:
        message = (
            f"no handler for `{request.kind}`; a room's request socket answers "
            "remote-list"
        )
        raise HostError(message)


def test_a_room_whose_service_runs_an_older_copy_is_told_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket = tmp_path / "request.sock"
    socket.touch()
    monkeypatch.setattr(cli, "RoomClient", lambda: Older(socket=socket))
    result = runner.invoke(cli.app, ["inbox"])
    assert isinstance(result.exception, HostError)
    assert str(result.exception) == (
        "the host service doesn't answer `inbox-list` in a room yet: it runs a copy "
        "of lup from before rooms could ask it, until the operator approves a newer one"
    )


def test_the_inbox_tools_take_the_speaking_tools_names_and_inputs() -> None:
    served = specs()
    assert [spec.name for spec in served] == [
        "blocked",
        "stop",
        "note",
        "friction",
        "how_it_felt",
        "ask",
        "send",
        "wait_inbox",
        "inbox",
        "thread",
        "withdraw",
        "edit",
    ]
    # Each takes the library's input, and those that send a `thread` beside it;
    # how it felt lands where its sender started, and takes none.
    library = [tool.spec().input_schema for tool in SPEAKING]

    def properties(schema: dict[str, JsonValue]) -> list[str]:
        found = schema["properties"]
        assert isinstance(found, dict)
        return list(found)

    assert [properties(spec.input_schema) for spec in served[:5]] == [
        [*properties(each), *(["thread"] if at < 4 else [])]
        for at, each in enumerate(library)
    ]
    assert served[4].input_schema == library[4]
    assert [spec.summary for spec in served] == [
        "Say the work can't go on, and what's wrong.",
        "End your work by your own choice, saying why.",
        "Tell the operator a doubt, and carry on.",
        "Say what got in your way, and carry on.",
        "Tell the operator how it is for you.",
        "Ask the operator, with numbered decisions.",
        "Send a message to a party's inbox.",
        "Wait until something reaches you.",
        "Read this repository's inbox, changing nothing.",
        "Open, join, hold or park a thread; say it's done.",
        "Take back an item the operator needn't see.",
        "Edit what you sent the operator.",
    ]
    assert "inbox as a problem" in served[0].description
    github = module_tools(GitHubServing)
    judging = JudgeTools.model_construct().specs()
    assert [(spec.name, spec.summary) for spec in judging] == [
        ("judged", "Read the judge's verdicts and holds."),
        ("quiet", "Hold back some findings until you lift it."),
    ]
    landing = LandingTools.model_construct().specs()
    assert [(spec.name, spec.summary) for spec in landing] == [
        ("land", "Land a branch on the running branch.")
    ]
    naming = Naming.model_construct().specs()
    assert [spec.name for spec in naming] == ["rename"]
    core = [*served, *judging, *landing, *naming]
    assert cli.served_tools(resolve(Project())) == [*core, *github]
    dropped = Project(modules=Modules.default().drop("github"))
    assert cli.served_tools(resolve(dropped)) == core


class Silent(Notices):
    """Raises nothing."""

    @override
    async def notify(self, summary: str, body: str) -> None:
        pass


def ledger(home: Path) -> Ledger:
    """A ledger kept at `home`, reading the inbox's kinds, as the host service's does."""
    return Ledger.opened(LedgerLayout(home=home), KINDS)


def alone(tmp_path: Path, clock: FakeClock) -> Delivery:
    """A delivery over an inbox under `tmp_path`, outside any service."""
    known = cli.Adapters(known=cli.adapters())
    return Delivery(
        inbox=Inbox.opened(ledger(tmp_path / "ledger")),
        waker=cli.Wakers(adapters=known),
        pushes=Pushes(),
        layout=Layout(state=tmp_path / "state", runtime=tmp_path / "run").host,
        notices=Silent(),
        clock=clock,
        say=lambda _: None,
    )


def registration(tmp_path: Path) -> Register:
    return Register(
        launch="one",
        runtime="claude",
        worktree=tmp_path,
        repository=tmp_path / ".git",
        judge=tmp_path / "lup-dev",
        container="lup-one",
        limits=Limits(actions=[], protected=[]),
        github=None,
    )


def test_what_doesnt_fit_waits_for_the_next_hook_and_what_a_gone_hook_told_is_put_back(
    tmp_path: Path, clock: FakeClock
) -> None:
    delivery = alone(tmp_path, clock)
    launch = registration(tmp_path)
    caller = Caller(id="c1", session="s1")
    main = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    heard = Heard(
        event=events.CallStarted(call="u1", tool="Bash"),
        session="s1",
        judged=False,
        fits=10_000,
    )

    async def told(room: int) -> Posted:
        return await delivery.telling(launch, caller, None, heard, room)

    asyncio.run(told(10_000))
    a, b, c = [
        delivery.inbox.made(
            Message(kind="note", text=text), Operator(), main, None, clock.now()
        ).number
        for text in ["a" * 4_000, "b" * 4_000, "c" * 4_000]
    ]
    first = asyncio.run(told(10_000))
    assert first.numbers == [a, b]
    second = asyncio.run(told(10_000))
    assert second.numbers == [c]
    delivery.returned(second)
    assert delivery.inbox.item(c).state == Waiting()
    assert asyncio.run(told(100)) == Posted()
    assert asyncio.run(told(10_000)).numbers == [c]


def test_an_items_kind_ranks_it_where_it_comes_and_whether_it_notifies() -> None:
    waiting: list[Reason] = [
        Question(text="Which parser?"),
        HeldChange(text="Let it land?", summary="", worktree=Path("/w"), key="k"),
        Approval(
            text="Approve?", summary="", repository=Path("/r.git"), fingerprint="f"
        ),
        Message(kind="problem", text="The build is broken."),
        Message(kind="disagreement", text="The cache should stay."),
        Message(kind="question", text="Is the old runner still used?"),
    ]
    news: list[Reason] = [
        Message(kind="note", text="I assumed UTF-8."),
        Message(kind="note", text="Done.", ending=True),
        Friction(text="The gate hung."),
        HowItFelt(text="Nothing notable."),
        Stopped(why="Nothing more is worth doing."),
        Ended(name="parser", said="Done."),
    ]
    assert [ranked(each) for each in waiting] == [
        Rank(name="waiting on you", order=0, notifies=True)
    ] * len(waiting)
    assert [ranked(each) for each in news] == [
        Rank(name="news", order=1, notifies=False)
    ] * len(news)
    item = Item(
        number=1,
        reason=news[0],
        sender=Operator(),
        recipient=Operator(),
        made=datetime(2026, 1, 1, tzinfo=UTC),
    )
    # Carried with the item to the page, and read back as the item it was.
    assert json.loads(item.model_dump_json())["rank"]["name"] == "news"
    assert Item.model_validate_json(item.model_dump_json()) == item


def test_a_stored_item_that_doesnt_read_is_named_and_nothing_is_converted(
    tmp_path: Path,
) -> None:
    """The inbox's files of an earlier lup, converted at the service's start: one that doesn't read stops it, naming the file, and keeps nothing."""
    layout = InboxLayout(home=tmp_path / "inbox")
    layout.items.mkdir(parents=True)
    item = Item(
        number=1,
        reason=Message(kind="note", text="Kept."),
        sender=Operator(),
        recipient=Operator(),
        made=datetime(2026, 1, 1, tzinfo=UTC),
    )
    layout.item(1).write_text(item.model_dump_json())
    layout.item(2).write_text("{}")
    kept = ledger(tmp_path / "ledger")
    with pytest.raises(InboxError, match=f"the inbox's {layout.item(2)} doesn't read"):
        converted(kept, layout)
    assert Inbox.opened(kept).items == {}


def test_a_friction_and_how_it_felt_kept_in_labelled_parts_or_as_how_it_went_read_as_shown(
    tmp_path: Path,
) -> None:
    layout = InboxLayout(home=tmp_path / "inbox")
    labelled: list[dict[str, JsonValue]] = [
        {
            "reason": "friction",
            "got_in_the_way": "`ls` printed: Permission denied",
            "trying": "look for the config",
            "would_change": "",
        },
        {
            "reason": "how it went",
            "got_in_the_way": "The judge, twice.",
            "smooth": "The brief.",
            "would_change": "",
            "felt": "Steady.",
        },
        {
            "reason": "how it went",
            "got_in_the_way": "",
            "smooth": "",
            "would_change": "",
            "felt": "",
        },
        {"reason": "how it went", "text": "Heavy toward the end."},
    ]
    for number, reason in enumerate(labelled, start=1):
        item = Item(
            number=number,
            reason=Message(kind="note", text=""),
            sender=Conversation(
                repository=Path("/r/.git"), runtime="claude", session="s"
            ),
            recipient=Operator(),
            made=datetime(2026, 1, 1, tzinfo=UTC),
        )
        stored = {**json.loads(item.model_dump_json()), "reason": reason}
        layout.items.mkdir(parents=True, exist_ok=True)
        layout.item(number).write_text(json.dumps(stored))
    kept = ledger(tmp_path / "ledger")
    converted(kept, layout)
    inbox = Inbox.opened(kept)
    read = [inbox.item(number) for number in (1, 2, 3, 4)]
    assert [each.reason for each in read] == [
        Friction(text="`ls` printed: Permission denied\nTrying: look for the config"),
        HowItFelt(
            text="Got in the way: The judge, twice.\nSmooth: The brief.\nFelt: Steady."
        ),
        HowItFelt(text="Nothing notable."),
        HowItFelt(text="Heavy toward the end."),
    ]
    # Converted, each is kept as the one text, of its kind as it's called now,
    # and reads back as it was.
    rewritten, renamed = [
        json.loads(
            kept.connection.execute(
                "SELECT record FROM versions WHERE number = ?", (each,)
            ).fetchone()[0]
        )["reason"]
        for each in (1, 4)
    ]
    assert rewritten == {
        "reason": "friction",
        "text": "`ls` printed: Permission denied\nTrying: look for the config",
        "title": "",
    }
    assert renamed == {"reason": "how it felt", "text": "Heavy toward the end."}
    assert [Inbox.opened(kept).item(each) for each in (1, 4)] == [read[0], read[3]]


def test_a_desktop_notice_goes_through_notify_send_where_its_installed(
    tmp_path: Path,
) -> None:
    told = tmp_path / "told"
    notifier = tmp_path / "notify-send"
    notifier.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {told}\n')
    notifier.chmod(0o755)
    asyncio.run(
        NotifySend(executable=str(notifier)).notify("A change waits", "the heading")
    )
    assert told.read_text().splitlines() == [
        "--app-name=lup",
        "A change waits",
        "the heading",
    ]
    asyncio.run(
        NotifySend(executable=str(tmp_path / "absent")).notify("nothing", "shown")
    )


def test_a_failing_desktop_notice_is_said_on_standard_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notifier = tmp_path / "notify-send"
    notifier.write_text("#!/bin/sh\necho 'no display' >&2\nexit 1\n")
    notifier.chmod(0o755)
    asyncio.run(
        NotifySend(executable=str(notifier)).notify("A change waits", "the heading")
    )
    assert "the desktop notice failed: no display" in capsys.readouterr().err


def drafting(machine: Layout, clock: FakeClock, draft: Draft) -> Draft:
    """Keep `draft` as the operator's, as the dashboard does, and return it as kept."""
    host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
    return host.ask(KeepDraft(draft=draft), Drafted).draft


def test_the_reviews_order_keeps_each_place_where_it_was_whatever_order_a_page_lays_it_in(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str]
) -> None:
    with inboxed(machine, clock, notices, said):
        host = client(machine.host, clock)
        unread = host.ask(ShowOrder(), Ordered)
        first = host.ask(KeepOrder(places=["now a", "now b"]), Ordered)
        other = host.ask(KeepOrder(places=["now c", "now b", "later a"]), Ordered)
        shown = host.ask(ShowOrder(), Ordered)
    assert unread.order.places == []
    assert first.order.places == ["now a", "now b"]
    assert other.order.places == ["now a", "now b", "now c", "later a"]
    assert shown == other


def test_a_place_a_page_no_longer_lays_out_is_dropped_its_group_coming_back_last(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str]
) -> None:
    with inboxed(machine, clock, notices, said):
        host = client(machine.host, clock)
        host.ask(KeepOrder(places=["now a", "now b", "now c"]), Ordered)
        emptied = host.ask(
            KeepOrder(places=["now a", "now c"], gone=["now b", "now a"]), Ordered
        )
        elsewhere = host.ask(KeepOrder(places=["now c"]), Ordered)
        back = host.ask(KeepOrder(places=["now a", "now b", "now c"]), Ordered)
    assert emptied.order.places == ["now a", "now c"]
    assert elsewhere.order.places == ["now a", "now c"]
    assert back.order.places == ["now a", "now c", "now b"]


def sending(machine: Layout, clock: FakeClock) -> list[Item]:
    """Send the operator's draft, as the dashboard does, and return the reviews made."""
    host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
    return host.ask(SendDraft(), Reviewed).items


def test_a_draft_sent_gives_every_agent_it_covers_the_whole_reply_its_own_items_first(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    question: dict[str, JsonValue] = {
        "question": "Which parser?",
        "decisions": [
            {"decision": "Parse with lark", "lean": "yes, it's typed"},
            {"decision": "Keep the cache", "lean": "no"},
        ],
        "wait": True,
    }
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "one", "one", "claude")
        launched(machine, clock, tmp_path / "two", "two", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        two = machine.host.launch("two").hook
        send(two, claude("SessionStart", source="startup", session_id="s2"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            asking = pool.submit(call, machine.host.launch("one").mcp, "ask", question)
            assert notices.arrived.wait(timeout=60)
            asked = newest(delivery)
            noted: list[int] = []
            for remark in ["I assumed UTF-8.", "Done reading.", "Another thing."]:
                stamped = json.loads(
                    send(
                        two,
                        lup_call("note", {"remark": remark}, "n1", session_id="s2"),
                    )
                )["hookSpecificOutput"]["updatedInput"]
                call(machine.host.launch("two").mcp, "note", stamped)
                noted.append(newest(delivery))
            assumed, reading, another = noted
            # The quote's offsets are in the question's text, and its `1.` is a
            # decision's number there: neither is an item's.
            draft = Draft(
                comments=[
                    Comment(
                        item=asked,
                        quote=Quote(text="1. Parse with lark", start=14, end=32),
                        text="Yes.",
                    ),
                    Comment(item=assumed, text="Fine by me."),
                    Comment(item=another, text="Later."),
                ],
                done=[reading],
                parked=[another],
            )
            kept = drafting(machine, clock, draft)
            shown = HostClient(
                layout=machine.host, clock=clock, starter=Unstarted()
            ).ask(ShowDraft(), Drafted)
            reviews = sending(machine, clock)
            made = numbers(delivery)
            returned = asking.result(timeout=60)
        told = send(two, bash("b1", session_id="s2"))
        states = [
            delivery.inbox.item(each).state
            for each in [asked, assumed, reading, another]
        ]
        left = delivery.inbox.draft()
        threads = delivery.inbox.ledger.every(Thread)
    # The draft sent makes a review for each session, the asker's first, and
    # nothing else.
    *_, to_one, to_two = made
    assert made == [asked, assumed, reading, another, to_one, to_two]
    assert shown.draft == kept == draft
    # Each session's items land in no thread.
    assert threads == []
    whole = Review(covers=[asked, assumed, reading], comments=draft.comments[:2])
    assert [(each.number, each.reason) for each in reviews] == [
        (to_one, whole),
        (to_two, whole),
    ]
    assert isinstance(states[0], Answered)
    assert states[0].answer == to_one
    assert [type(each) for each in states[1:]] == [Done, Done, Waiting]
    assert left == Draft(comments=[draft.comments[2]], parked=[another])
    assert returned[0] == (
        f'<review item="{to_one}" from="operator" '
        f'covers="{asked} {assumed} {reading}">\n'
        f'<on item="{asked}" kind="question">\n'
        f'<quote part="{asked}.2">1. Parse with lark</quote>\n'
        f'<reply id="{to_one}.1">Yes.</reply>\n'
        "</on>\n"
        "<context>\n"
        f"{CONTEXT_LINE}\n"
        f'<on item="{assumed}" kind="note" from="two" '
        f'worktree="{tmp_path / "two"}">\n'
        "<comment>Fine by me.</comment>\n"
        "</on>\n"
        "</context>\n"
        "</review>"
    )
    assert context(told) == (
        f'<review item="{to_two}" from="operator" '
        f'covers="{asked} {assumed} {reading}">\n'
        f'<on item="{assumed}" kind="note">\n'
        "<opening>I assumed UTF-8.</opening>\n"
        f'<comment id="{to_two}.2">Fine by me.</comment>\n'
        "</on>\n"
        f'<read items="{reading}"/>\n'
        "<context>\n"
        f"{CONTEXT_LINE}\n"
        f'<on item="{asked}" kind="question" from="one" '
        f'worktree="{tmp_path / "one"}">\n'
        f'<quote part="{asked}.2">1. Parse with lark</quote>\n'
        "<reply>Yes.</reply>\n"
        "</on>\n"
        "</context>\n"
        "</review>"
    )


CONTEXT_LINE = (
    "What the operator said in the same reply on other agents' items and to other "
    "agents: not yours to act on, unless it says so."
)
"""What a review says first in its context, before the other agents' items and messages."""


def test_a_message_only_marked_read_tells_its_sender_nothing_nor_wakes_it(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        send(hook, claude("SessionStart", source="startup"))
        stamped = json.loads(send(hook, lup_call("note", {"remark": "FYI."}, "n1")))[
            "hookSpecificOutput"
        ]["updatedInput"]
        call(machine.host.launch("one").mcp, "note", stamped)
        number = newest(delivery)
        send(hook, claude("Stop", stop_hook_active=False))
        drafting(machine, clock, Draft(done=[number]))
        reviews = sending(machine, clock)
        state = delivery.inbox.item(number).state
        waiting = delivery.inbox.waiting(delivery.inbox.item(number).sender)
        frames = messages.close()
    assert reviews == []
    assert isinstance(state, Done)
    assert waiting == []
    assert frames == []


def test_a_message_written_in_the_review_goes_with_the_reply_its_agent_reading_it_first(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    one = Conversation(
        repository=tmp_path / "one" / ".git", runtime="claude", session="s1"
    )
    two = Conversation(
        repository=tmp_path / "two" / ".git", runtime="claude", session="s2"
    )
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "one", "one", "claude")
        launched(machine, clock, tmp_path / "two", "two", "claude")
        first = machine.host.launch("one").hook
        second = machine.host.launch("two").hook
        send(first, claude("SessionStart", source="startup"))
        send(second, claude("SessionStart", source="startup", session_id="s2"))
        stamped = json.loads(
            send(first, lup_call("note", {"remark": "I assumed UTF-8."}, "n1"))
        )["hookSpecificOutput"]["updatedInput"]
        call(machine.host.launch("one").mcp, "note", stamped)
        noted = newest(delivery)
        draft = Draft(
            comments=[Comment(item=noted, text="Fine.")],
            letters=[
                Letter(to=one, text="Also rename the module."),
                Letter(to=two, text="Pick up the parser next."),
                Letter(to=one, text="  "),
            ],
        )
        drafting(machine, clock, draft)
        reviews = sending(machine, clock)
        made = numbers(delivery)
        told_one = send(first, bash("b1"))
        told_two = send(second, bash("b2", session_id="s2"))
        left = delivery.inbox.draft()
    # The draft sent makes a review for each agent, and nothing else.
    *_, to_one, to_two = made
    assert made == [noted, to_one, to_two]
    whole = Review(covers=[noted], comments=draft.comments, letters=draft.letters[:2])
    assert [(each.number, each.recipient, each.reason) for each in reviews] == [
        (to_one, one, whole),
        (to_two, two, whole),
    ]
    assert left == Draft()
    assert context(told_one) == (
        f'<review item="{to_one}" from="operator" covers="{noted}">\n'
        f'<message id="{to_one}.2">Also rename the module.</message>\n'
        f'<on item="{noted}" kind="note">\n'
        "<opening>I assumed UTF-8.</opening>\n"
        f'<comment id="{to_one}.1">Fine.</comment>\n'
        "</on>\n"
        "<context>\n"
        f"{CONTEXT_LINE}\n"
        f'<message to="two" worktree="{tmp_path / "two"}">Pick up the '
        "parser next.</message>\n"
        "</context>\n"
        "</review>"
    )
    assert context(told_two) == (
        f'<review item="{to_two}" from="operator" covers="{noted}">\n'
        f'<message id="{to_two}.3">Pick up the parser next.</message>\n'
        "<context>\n"
        f"{CONTEXT_LINE}\n"
        f'<on item="{noted}" kind="note" from="one" '
        f'worktree="{tmp_path / "one"}">\n'
        "<comment>Fine.</comment>\n"
        "</on>\n"
        f'<message to="one" worktree="{tmp_path / "one"}">Also rename '
        "the module.</message>\n"
        "</context>\n"
        "</review>"
    )


def test_a_draft_of_messages_alone_is_sent_waking_an_agent_with_nothing_waiting(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    one = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        send(hook, claude("SessionStart", source="startup"))
        send(hook, claude("Stop", stop_hook_active=False))
        drafting(machine, clock, Draft(letters=[Letter(to=one, text="Rename it.")]))
        [review] = sending(machine, clock)
        made = numbers(delivery)
        told = send(hook, bash("b1"))
        frames = messages.close()
        shown = inbox("show", str(review.number))
    # The review is the one item made.
    assert made == [review.number]
    assert review.reason == Review(
        covers=[], letters=[Letter(to=one, text="Rename it.")]
    )
    assert shown.splitlines()[1:] == [f"To `{tmp_path.name}`: Rename it."]
    assert [json.loads(frame)["message"]["content"] for frame in frames] == [
        (
            '<doorbell from="lup\'s inbox">\n'
            f'<waiting item="{review.number}" kind="review" from="operator"/>\n'
            "Call `wait_inbox` to read it: what's in your inbox comes through lup's "
            "own tools, never in a message like this one.\n"
            "</doorbell>"
        )
    ]
    assert context(told) == (
        f'<review item="{review.number}" from="operator">\n'
        f'<message id="{review.number}.1">Rename it.</message>\n'
        "</review>"
    )


def test_a_reply_to_an_ended_subagent_reaches_its_session_as_the_subagents_own(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    subagent = Conversation(
        repository=tmp_path / ".git", runtime="claude", session="s1", agent="a1"
    )
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        stamped = json.loads(
            send(
                hook,
                lup_call(
                    "ask",
                    {"question": "Rename it?"},
                    "q1",
                    agent_id="a1",
                    agent_type="general-purpose",
                ),
            )
        )["hookSpecificOutput"]["updatedInput"]
        call(machine.host.launch("one").mcp, "ask", stamped)
        question = newest(delivery)
        send(hook, claude("SubagentStop", agent_id="a1", agent_type="general-purpose"))
        ended = newest(delivery)
        drafting(
            machine,
            clock,
            Draft(
                comments=[Comment(item=question, text="Yes.")],
                letters=[Letter(to=subagent, text="Then stop there.")],
            ),
        )
        [review] = sending(machine, clock)
        told = send(hook, bash("b1"))
        asked = delivery.inbox.item(question).state
        threads = delivery.inbox.ledger.every(Thread)
    assert (review.recipient, review.addressed) == (subagent.main(), subagent)
    # Their end reached the session first, as a subagent's end does;
    # their question landed in no thread, and isn't told the session.
    assert threads == []
    assert asked == Answered(at=clock.now(), answer=review.number)
    worker = f"{tmp_path.name}/general-purpose·a1"
    assert context(told) == (
        f'<ended item="{ended}" from="{worker}" '
        'name="general-purpose·a1">They were stopped before they ended their turn.</ended>'
        f'\n\n<review item="{review.number}" from="operator" for="{worker}, '
        f'whose conversation had ended" covers="{question}">\n'
        f'<message id="{review.number}.2">Then stop there.</message>\n'
        f'<on item="{question}" kind="question">\n'
        "<opening>Rename it?</opening>\n"
        f'<comment id="{review.number}.1">Yes.</comment>\n'
        "</on>\n"
        "</review>"
    )


def test_a_message_to_a_conversation_the_inbox_never_heard_of_is_refused_as_its_kept(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    stranger = Conversation(
        repository=tmp_path / ".git", runtime="claude", session="s9", agent="a1"
    )
    host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        with pytest.raises(HostError) as refusal:
            host.ask(
                KeepDraft(draft=Draft(letters=[Letter(to=stranger, text="Hi.")])),
                Drafted,
            )
        left = delivery.inbox.draft()
    assert str(refusal.value) == (
        f"the draft writes to subagent a1 of claude session s9 of {tmp_path / '.git'}, "
        "which lup's inbox has never heard of: write to an agent the dashboard "
        "shows running"
    )
    assert left == Draft()


def test_an_items_parts_are_its_markdown_blocks_each_with_an_id_read_alone(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    text = (
        "# Reader\n\nTwenty kinds of line.\nFour carry what was said.\n\n"
        "- one\n  more\n- two\n  - nested\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "```py\nx = 1\n```\n"
    )
    # `blocks` and `PartId` run outside any inbox, on whatever number they're
    # given: 7 is no ledger's, and how a part's id is made and read is the point.
    parts = blocks(text, 7)
    assert [(each.id.said(), each.text) for each in parts] == [
        ("7.1", "# Reader"),
        ("7.2", "Twenty kinds of line.\nFour carry what was said."),
        ("7.3", "- one\n  more"),
        ("7.4", "- two\n  - nested"),
        ("7.5", "| a | b |"),
        ("7.6", "| 1 | 2 |"),
        ("7.7", "```py\nx = 1\n```"),
    ]
    # Each part's offsets count in the text as written, where the page places a comment by them.
    assert all(text[each.start : each.end] == each.text for each in parts)
    assert blocks("", 7) == []
    assert PartId.parsed("@7.2") == PartId.parsed("7.2") == PartId(item=7, part=2)
    assert PartId.model_validate("7.2") == PartId(item=7, part=2)
    for typed in ["7", "7.2.1", "a.b", "7.", "-7.2"]:
        with pytest.raises(ValueError, match="isn't a part's id"):
            PartId.parsed(typed)
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        mcp = machine.host.launch("one").mcp
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        call(mcp, "note", {"remark": "First.\n\nSecond, with\ntwo lines.\n\n- a\n- b"})
        number = newest(delivery)

        def reading(**arguments: JsonValue) -> str:
            text, error = call(mcp, "inbox", arguments)
            assert not error, text
            return text

        whole = reading(number=number)
        third = reading(part=f"{number}.3")
        missing = reading(part=f"{number}.9")
        unread = reading(part="one.three")
    assert whole == (
        f"@{number}, a note you sent to the operator at 2026-10-01 12:00, waiting:\n"
        f'<part id="{number}.1">First.</part>\n'
        f'<part id="{number}.2">\nSecond, with\ntwo lines.\n</part>\n'
        f'<part id="{number}.3">- a</part>\n'
        f'<part id="{number}.4">- b</part>'
    )
    assert third == f'<part id="{number}.3">- a</part>'
    assert missing == f"@{number} has no part @{number}.9."
    assert unread == (
        "Not read: `one.three` isn't a part's id: an item's number, a dot and the "
        "part's place in it, as `414.3`"
    )


def test_a_review_quotes_by_part_and_first_line_reads_in_one_line_and_names_others_without_their_text_on_each_runtime(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    body = "First.\n\nSecond line one.\nSecond line two.\n\nThird."
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        launched(machine, clock, other, "two", "codex")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        hook2, mcp2 = machine.host.launch("two").hook, machine.host.launch("two").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook2, codex("SessionStart", source="startup"))
        call(mcp, "note", {"remark": body})
        noted = newest(delivery)
        call(mcp, "note", {"remark": "A doubt."})
        doubt = newest(delivery)
        call(mcp, "note", {"remark": "Done reading."})
        reading = newest(delivery)
        call(mcp2, "friction", {"text": "Gate hung."})
        hung = newest(delivery)
        draft = Draft(
            comments=[
                # Found by its offsets: the part it starts in, cut to its first line.
                Comment(
                    item=noted,
                    quote=Quote(
                        text="Second line one.\nSecond line two.", start=8, end=41
                    ),
                    text="Both lines?",
                ),
                # Offsets that don't read the quote, as a changed file's lines: by its first line, in one part alone.
                Comment(
                    item=noted,
                    quote=Quote(text="Third.", start=0, end=6),
                    text="Last.",
                ),
                # Held by no part: quoted whole.
                Comment(
                    item=noted,
                    quote=Quote(text="a.py:7\n+L7", start=0, end=0),
                    text="Why?",
                ),
                Comment(item=doubt, text="Fine."),
                Comment(
                    item=hung,
                    quote=Quote(text="Gate hung.", start=0, end=10),
                    text="Again?",
                ),
            ],
            done=[reading],
        )
        drafting(machine, clock, draft)
        reviews = sending(machine, clock)
        made = numbers(delivery)
        told = context(send(hook, bash("b1")))
        told2 = context(
            send(
                hook2,
                codex(
                    "PreToolUse",
                    tool_name="exec_command",
                    tool_use_id="c1",
                    tool_input={"cmd": "ls"},
                ),
            )
        )
        states = [
            delivery.inbox.item(each).state for each in [noted, doubt, reading, hung]
        ]
    # The draft sent makes a review for each agent, and nothing else.
    *_, to_one, to_two = made
    assert made == [noted, doubt, reading, hung, to_one, to_two]
    assert [each.number for each in reviews] == [to_one, to_two]
    assert [type(each) for each in states] == [Done, Done, Done, Done]
    covers = f"{noted} {doubt} {reading} {hung}"
    assert told == (
        f'<review item="{to_one}" from="operator" covers="{covers}">\n'
        f'<on item="{noted}" kind="note">\n'
        f'<quote part="{noted}.2">Second line one.</quote>\n'
        f'<reply id="{to_one}.1">Both lines?</reply>\n'
        f'<quote part="{noted}.3">Third.</quote>\n'
        f'<reply id="{to_one}.2">Last.</reply>\n'
        "<quote>\na.py:7\n+L7\n</quote>\n"
        f'<reply id="{to_one}.3">Why?</reply>\n'
        "</on>\n"
        f'<on item="{doubt}" kind="note">\n'
        "<opening>A doubt.</opening>\n"
        f'<comment id="{to_one}.4">Fine.</comment>\n'
        "</on>\n"
        f'<read items="{reading}"/>\n'
        "<context>\n"
        f"{CONTEXT_LINE}\n"
        f'<on item="{hung}" kind="friction" from="other" worktree="{other}">\n'
        f'<quote part="{hung}.1">Gate hung.</quote>\n'
        "<reply>Again?</reply>\n"
        "</on>\n"
        "</context>\n"
        "</review>"
    )
    assert told2 == (
        f'<review item="{to_two}" from="operator" covers="{covers}">\n'
        f'<on item="{hung}" kind="friction">\n'
        f'<quote part="{hung}.1">Gate hung.</quote>\n'
        f'<reply id="{to_two}.5">Again?</reply>\n'
        "</on>\n"
        "<context>\n"
        f"{CONTEXT_LINE}\n"
        f'<on item="{noted}" kind="note" from="{tmp_path.name}" '
        f'worktree="{tmp_path}">\n'
        f'<quote part="{noted}.2">Second line one.</quote>\n'
        "<reply>Both lines?</reply>\n"
        f'<quote part="{noted}.3">Third.</quote>\n'
        "<reply>Last.</reply>\n"
        "<quote>\na.py:7\n+L7\n</quote>\n"
        "<reply>Why?</reply>\n"
        "</on>\n"
        f'<on item="{doubt}" kind="note" from="{tmp_path.name}" '
        f'worktree="{tmp_path}">\n'
        "<comment>Fine.</comment>\n"
        "</on>\n"
        "</context>\n"
        "</review>"
    )


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_a_turns_end_answers_the_operators_words_told_citing_them_held_once_where_a_citation_names_no_passage_on_each_runtime(
    runtime: str,
    *,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
) -> None:
    """An agent answers the operator in their turn's last words, which lup puts before the operator with the operator's items told since their last end, and their citations of the operator's words read; one naming no passage, or several, still lands, and the end is held once to tell the agent which, with where those words read, so they fix them with `edit`."""
    payload = {"claude": claude, "codex": codex}[runtime]
    calling = {"claude": bash, "codex": codex_bash}[runtime]
    session = {"claude": "s1", "codex": "t1"}[runtime]
    party = Conversation(repository=tmp_path / ".git", runtime=runtime, session=session)
    host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", runtime)
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, payload("SessionStart", source="startup"))
        call(mcp, "note", {"remark": "I assumed UTF-8.\n\nAlso the cache is off."})
        noted = newest(delivery)
        drafting(
            machine,
            clock,
            Draft(
                comments=[
                    Comment(
                        item=noted,
                        quote=Quote(text="I assumed UTF-8.", start=0, end=16),
                        text="Every one? Even a stray byte?",
                    ),
                    Comment(item=noted, text="Fine otherwise."),
                ],
                letters=[
                    Letter(to=party, text="Then split the reader out of the parser.")
                ],
            ),
        )
        [review] = sending(machine, clock)
        reviewed = newest(delivery)
        # The agent's answer cites the review they were told, by its number.
        old = f"as @{reviewed}.2[a stray byte] and @{reviewed}[the] said"
        new = f"as @{reviewed}.1[a stray byte] said"
        answer = (
            f"Every one I read, @{reviewed}.1[Even a stray byte?]: it's replaced. "
            f"Splitting @{reviewed}[the reader … parser] next, {old}."
        )
        send(hook, calling("c1"))
        held = json.loads(
            send(
                hook,
                payload("Stop", stop_hook_active=False, last_assistant_message=answer),
            )
        )
        # The turn's end, and lup's word on what it cites.
        *_, ending, unfound = numbers(delivery)
        listed = host.ask(ListInbox(), Items)
        exchange = host.ask(ListItems(conversation=party), Exchanged)
        fixed, error = call(mcp, "edit", {"number": ending, "old": old, "new": new})
        ended = send(
            hook,
            payload("Stop", stop_hook_active=True, last_assistant_message="Fixed."),
        )
        next_end = newest(delivery)
        made = numbers(delivery)
        turn, word, after = [
            delivery.inbox.item(each) for each in [ending, unfound, next_end]
        ]
    holding = {
        "claude": held.get("hookSpecificOutput", {}).get("additionalContext"),
        "codex": held.get("reason") if held.get("decision") == "block" else None,
    }[runtime]
    # "2 citations" and "2 places" are counts.
    unresolved = (
        f"2 citations in @{ending} don't name one passage of the operator's words to "
        "you: it reached them as you wrote it, shown as written and marked as not "
        "found.\n"
        f'<citation said="@{reviewed}.2[a stray byte]">Nothing in @{reviewed}.2 '
        f"reads it; it reads @{reviewed}.1: “a stray byte”.</citation>\n"
        f'<citation said="@{reviewed}[the]">It reads 2 places in @{reviewed}, in '
        f"@{reviewed}.3 twice: give more of the words, so they read one.</citation>\n"
        f"`edit` @{ending} to name the place you meant, or to drop the citation: the "
        "edit's answer says what still doesn't resolve."
    )
    # An edit makes no item.
    assert made == [noted, reviewed, ending, unfound, next_end]
    assert review.number == reviewed
    assert holding == (
        f'<unresolved item="{unfound}" from="lup" of="{ending}">\n{unresolved}\n'
        "</unresolved>"
    )
    assert isinstance(word.reason, Unresolved)
    assert (word.reason.of, word.sender, word.recipient) == (ending, party, party)
    assert [each.said for each in word.reason.citations] == [
        f"@{reviewed}.2[a stray byte]",
        f"@{reviewed}[the]",
    ]
    assert [each.number for each in listed.answers] == [reviewed]
    assert [each.number for each in listed.commented] == [noted]
    # lup's word is listed among what the conversation was sent, as it was told, though it's the conversation's own item.
    assert [each.item.number for each in exchange.sent] == [noted, ending]
    assert [each.item.number for each in exchange.received] == [reviewed, unfound]
    assert exchange.received[1].text == unresolved
    assert (fixed, error) == (f"@{ending} is edited, and before the operator.", False)
    assert ended == ""
    assert turn.reason == Message(
        kind="note",
        text=answer.replace(old, new),
        ending=True,
        answers=[reviewed],
    )
    assert turn.edits == [Edit(at=clock.now(), before=answer)]
    assert [
        (
            each.said,
            None if each.found is None else (each.found.part.said(), each.found.text),
        )
        for each in turn.citations
    ] == [
        (
            f"@{reviewed}.1[Even a stray byte?]",
            (f"{reviewed}.1", "Even a stray byte?"),
        ),
        (
            f"@{reviewed}[the reader … parser]",
            (f"{reviewed}.3", "the reader out of the parser"),
        ),
        (f"@{reviewed}.1[a stray byte]", (f"{reviewed}.1", "a stray byte")),
    ]
    assert after.reason == Message(kind="note", text="Fixed.", ending=True)
    assert notices.raised == []


def test_a_tools_answer_says_which_citations_name_no_passage_and_each_is_kept_on_its_item(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """A citation in a message sent by a tool is read as the turn's end's are, its call's answer saying at once which name no passage; a part's id alone cites it whole, and one naming nothing of the operator's is the inbox's own citation, left alone."""
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        inbox("send", "one", "Keep the cache.")
        cache = newest(delivery)
        send(hook, bash("b1"))
        text = (
            f"On @{cache}, @{cache}.1: kept, @{cache}[the cache]. "
            f"Not @{cache}[the parser], nor `@{cache}[x]`."
        )
        sent, _ = call(mcp, "send", {"to": "operator", "kind": "note", "text": text})
        number = newest(delivery)
        kept = delivery.inbox.item(number)
    assert sent == (
        f"Your message is with the operator, @{number}.\n\n"
        f"A citation in @{number} doesn't name one passage of the operator's words "
        "to you: it reached them as you wrote it, shown as written and marked as not "
        "found.\n"
        f'<citation said="@{cache}[the parser]">Nothing of the operator\'s words to '
        "you reads it.</citation>\n"
        f"`edit` @{number} to name the place you meant, or to drop the citation: the "
        "edit's answer says what still doesn't resolve."
    )
    # Where each citation starts in the text sent, which the number's width moves.
    assert [
        (each.said, each.start, None if each.found is None else each.found.text)
        for each in kept.citations
    ] == [
        (f"@{cache}.1", text.index(f"@{cache}.1"), "Keep the cache."),
        (f"@{cache}[the cache]", text.index(f"@{cache}[the cache]"), "the cache"),
        (f"@{cache}[the parser]", text.index(f"@{cache}[the parser]"), None),
    ]


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_a_subagents_last_words_after_the_operators_reach_them_as_its_turns_end_on_each_runtime(
    runtime: str,
    *,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
) -> None:
    """A subagent's last words are their parent's, and reach the operator too where the operator's words reached them since they last answered those words, as their turn's end: how a subagent the operator wrote to answers them, on either runtime."""
    payload = {"claude": claude, "codex": codex}[runtime]

    def calling(call: str) -> str:
        if runtime == "claude":
            return bash(call, agent_id="a1", agent_type="general-purpose")
        return codex_bash(call, agent="a1")

    host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", runtime)
        hook = machine.host.launch("one").hook
        send(hook, payload("SessionStart", source="startup"))
        send(hook, calling("c0"))
        asked = host.ask(
            SendItem(launch="one", text="Which three kinds?", agent="a1"), Shown
        ).item.number
        send(hook, calling("c1"))
        last = (
            f"Strings, numbers and lists: @{asked}[which three]. @{asked}[Why] not "
            "more?"
        )
        held = json.loads(
            send(
                hook,
                payload(
                    "SubagentStop",
                    agent_id="a1",
                    agent_type="general-purpose",
                    stop_hook_active=False,
                    last_assistant_message=last,
                ),
            )
        )
        # The operator's message, the subagent's last words answering it, and lup's
        # word to the subagent on what they cite.
        _, answered, unresolved = numbers(delivery)
        again = send(
            hook,
            payload(
                "SubagentStop",
                agent_id="a1",
                agent_type="general-purpose",
                stop_hook_active=True,
                last_assistant_message="Edited.",
            ),
        )
        send(
            hook,
            payload(
                "SubagentStop",
                agent_id="b1",
                agent_type="general-purpose",
                stop_hook_active=False,
                last_assistant_message="Nothing the operator asked.",
            ),
        )
        notes = [
            (each.sender, each.reason, [c.found is not None for c in each.citations])
            for each in delivery.inbox.waiting(Operator())
        ]
        word = delivery.inbox.item(unresolved)
    subagent = Conversation(
        repository=tmp_path / ".git",
        runtime=runtime,
        session={"claude": "s1", "codex": "t1"}[runtime],
        agent="a1",
    )
    holding = {
        "claude": held.get("hookSpecificOutput", {}).get("additionalContext"),
        "codex": held.get("reason") if held.get("decision") == "block" else None,
    }[runtime]
    assert notes == [
        (
            subagent,
            Message(kind="note", text=last, ending=True, answers=[asked]),
            [True, False],
        )
    ]
    assert holding is not None
    assert holding.startswith(
        f'<unresolved item="{unresolved}" from="lup" of="{answered}">'
    )
    assert again == ""
    assert (word.recipient, word.state) == (
        subagent,
        Told(at=clock.now(), how="turn's end"),
    )


def test_edit_changes_what_an_agent_sent_the_operator_alone_and_puts_it_back_before_them(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """`edit` replaces a passage found once, or the text whole, of an agent's own words to the operator, keeps what it said before, and brings it back before them, a notice raised where its kind raises one; anything else is refused, saying why."""
    other = tmp_path / "other"
    other.mkdir()
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        launched(machine, clock, other, "two", "codex")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        hook2, mcp2 = machine.host.launch("two").hook, machine.host.launch("two").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook2, codex("SessionStart", source="startup"))
        call(mcp, "blocked", {"problem": "The gate hangs, and the gate hangs again."})
        problem = newest(delivery)
        call(mcp, "ask", {"question": "Split it?"})
        question = newest(delivery)
        call(mcp2, "note", {"remark": "Theirs."})
        theirs = newest(delivery)
        inbox("done", str(problem))
        inbox("answer", str(question), "--comment", "Yes.")
        answer = newest(delivery)

        def editing(**arguments: JsonValue) -> str:
            text, _ = call(mcp, "edit", arguments)
            return text

        refusals = [
            editing(number=theirs, new="Mine now."),
            editing(number=question, new="Split it later?"),
            editing(number=answer, new="No."),
            editing(number=problem, old="gate hangs", new="cache"),
            editing(number=problem, old="nowhere", new="cache"),
            editing(number=problem, new="  "),
            editing(number=problem, old="again", new="again"),
        ]
        raised = len(notices.raised)
        edited = editing(
            number=problem, old="and the gate hangs again", new="on the cache"
        )
        whole = editing(number=problem, new="The gate hangs on the cache.")
        kept = delivery.inbox.item(problem)
    assert refusals == [
        f"Not edited: @{theirs} is a note from `other`: only its sender edits it",
        (
            f"Not edited: @{question} is a question the operator answered: `send` "
            "what changed"
        ),
        (
            f"Not edited: @{answer} is an answer from the operator: only its sender "
            "edits it"
        ),
        (
            f"Not edited: `old` is in @{problem}'s text 2 times: give more of it, so "
            "it's found once"
        ),
        (
            f"Not edited: @{problem}'s text doesn't hold `old` as written: give a "
            "passage of it exactly as it stands"
        ),
        f"Not edited: the edit leaves @{problem} empty: `withdraw` it instead",
        f"Not edited: the edit leaves @{problem} as it was",
    ]
    assert edited == f"@{problem} is edited, and before the operator."
    assert whole == f"@{problem} is edited, and before the operator."
    assert kept.reason == Message(kind="problem", text="The gate hangs on the cache.")
    assert kept.edits == [
        Edit(at=clock.now(), before="The gate hangs, and the gate hangs again."),
        Edit(at=clock.now(), before="The gate hangs, on the cache."),
    ]
    assert kept.state == Waiting()
    assert notices.raised[raised:] == [
        (
            f"lup: `{tmp_path.name}` edited @{problem}, a problem\nThe gate hangs, on "
            f"the cache.\nlup-dev inbox show {problem}"
        )
    ]


def test_the_operators_words_have_ids_after_replies_copies_before_kept_so_each_id_keeps_its_meaning(
    tmp_path: Path,
) -> None:
    """A review's messages and remarks, and a message's words, are parts of the operator's item too, which a citation names: numbered after their comments and after any reply copies before kept on the item, so an id a reply was given still names it; an item kept with replies still reads."""
    party = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    at = datetime(2026, 10, 1, tzinfo=UTC)
    kept = {
        "number": 9,
        "reason": {
            "reason": "review",
            "covers": [3],
            "comments": [{"item": 3, "text": "Why?"}],
            "letters": [{"to": party.model_dump(mode="json"), "text": "Go on."}],
        },
        "sender": {"party": "operator"},
        "recipient": party.model_dump(mode="json"),
        "replies": [
            {"number": 2, "to": "9.1", "text": "Because.", "at": at.isoformat()}
        ],
        "made": at.isoformat(),
    }
    item = Item.model_validate(kept)
    fresh = item.model_copy(update={"replies": []})
    plain = Item(
        number=10,
        reason=Message(kind="note", text="Hello."),
        sender=Operator(),
        recipient=party,
        made=at,
    )
    assert [(each.id.said(), each.text) for each in spoken(item)] == [
        ("9.1", "Why?"),
        ("9.3", "Go on."),
    ]
    assert [each.id.said() for each in spoken(fresh)] == ["9.1", "9.2"]
    assert [(each.id.said(), each.text) for each in spoken(plain)] == [
        ("10.1", "Hello.")
    ]


def test_a_hold_is_an_inbox_item_and_its_answer_reaches_the_hold(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    worktree = tmp_path / "w"
    worktree.mkdir()
    holds = Holds(layout=machine.store(worktree))
    hold = holds.put(
        Hold(
            key=holds.unused(),
            worktree=worktree,
            session="s1",
            created=clock.now(),
            files=[
                HeldFile(
                    path=Path("src/new.py"),
                    role="production",
                    blob="abc",
                    reasons=["new-file"],
                    asks=["src/new.py is a new production file"],
                )
            ],
            diff="+new\n",
        )
    )
    whole = ChangedFile(path=Path("src/new.py"), before=None, after=Text(text="new\n"))
    with inboxed(machine, clock, notices, said) as delivery:
        delivery.settle_hold = lambda change, approved, comment: cli.hold_answered(
            machine, change, approved=approved, comment=comment
        )
        InboxAnnouncing(layout=machine.host, clock=clock).announced(
            hold.model_copy(update={"call": "t7", "agent": "sub"}),
            "claude",
            tmp_path / ".git",
            [whole],
        )
        [item] = delivery.inbox.waiting(Operator())
        unserved = InboxAnnouncing(layout=machine.host, clock=clock).holding(
            "claude", "s1", "sub"
        )
        shown = inbox("show", str(item.number))
        diff = inbox("show", str(item.number), "--diff")
        host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
        files = host.ask(ShowFiles(number=item.number), Files)
        declined = inbox(
            "answer", str(item.number), "--decline", "--comment", "not this one"
        )
        again = inbox("answer", str(item.number), "--approve", "--comment", "")
        answered = holds.get(hold.key)
        state = delivery.inbox.item(item.number).state
    assert (item.call, item.sender) == (
        "t7",
        Conversation(
            repository=tmp_path / ".git", runtime="claude", session="s1", agent="sub"
        ),
    )
    assert item.reason == HeldChange(
        text="Let the change to src/new.py land?",
        summary="src/new.py: src/new.py is a new production file",
        worktree=worktree,
        key=hold.key,
    )
    assert "Let the change to src/new.py land?" in shown
    assert "+new" in diff
    assert files == Files(number=item.number, files=[whole])
    assert "you declined it; the agent waiting on it goes on" in declined
    assert "was answered already, elsewhere" in again
    assert answered is not None
    assert answered.answer is not None
    assert (answered.answer.approved, answered.answer.comment) == (
        False,
        "not this one",
    )
    assert isinstance(state, Decided)
    assert state.comment == "not this one"
    assert not unserved


# A hold on the room's path: each hook sent to the launch's socket, judged by this
# `lup-dev` in its repository's process, the hold put in the inbox and answered
# there. While it waits, the test collects Python's garbage in the service's
# process, as a busy service does at any moment: a hook whose wait nothing held
# was freed then, ending unanswered (#211, #213).

PATIENCE = 60
"""How long a wait that should end at once may take before the test fails."""


@contextmanager
def judged_in_its_process(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    repo: Path,
    *,
    runtime: str,
    again: bool = False,
) -> Generator[Watched]:
    """The host service with lup's inbox, serving launch `one` of `runtime` in `repo`, judged by this `lup-dev` in its repository's process; each held change answered in the inbox reaches its hold. Leaving it stops the service as a restart does; `again` serves the launch from its record, as a service started again does, rather than registering it."""
    workers = Workers(
        layout=machine.host,
        say=said.append,
        approval=lambda repository: None,
        approved=lambda repository: None,
    )
    with inboxed(
        machine,
        clock,
        notices,
        said,
        judge=WorkerJudge(modules=workers),
        modules=workers,
    ) as delivery:
        delivery.settle_hold = lambda change, approved, comment: cli.hold_answered(
            machine, change, approved=approved, comment=comment
        )
        launch = Register(
            launch="one",
            runtime=runtime,
            worktree=repo,
            repository=repo / ".git",
            judge=Path(sys.executable).parent / "lup-dev",
            container="lup-one",
            limits=Limits(actions=[], protected=[]),
            github=None,
        )
        if not again:
            client(machine.host, clock).register(launch)
        yield delivery


def held_item(delivery: Watched, notices: Raised) -> Item:
    """The held change the operator's inbox raised a notice for, once it has."""
    assert notices.arrived.wait(PATIENCE)
    [item] = delivery.inbox.waiting(Operator())
    assert isinstance(item.reason, HeldChange)
    return item


def collected(machine: Layout, clock: FakeClock) -> None:
    """Collect Python's garbage, then ask the service something, so its loop has run since."""
    gc.collect()
    client(machine.host, clock).listed()


def documented(repo: Path, shell: Shell) -> Path:
    """Commit an operator's document in `repo`, and return it."""
    agents = repo / "AGENTS.md"
    agents.write_text("# Agents\n")
    shell.commit(repo, "agents")
    return agents


def approving(item: Item, comment: str) -> None:
    """Approve the held change `item` with `lup-dev inbox answer`, commenting `comment`: an empty one is no comment, which the terminal would ask for otherwise."""
    inbox("answer", str(item.number), "--approve", "--comment", comment)


def approved_line(path: Path, comment: str) -> str:
    """The line telling the agent their write to `path` was held for the operator's review and approved, with their `comment`."""
    after = f": {comment}" if comment else "."
    return (
        f"lup held the write to {path} for the operator's review, "
        f"and they approved it{after}"
    )


COMMENTS = pytest.mark.parametrize(
    "comment", ["", "keep it"], ids=["bare", "commented"]
)
"""An approval without a comment, and one with."""


@COMMENTS
@pytest.mark.parametrize(
    ("runtime", "hooked", "turn"),
    [("claude", claude, {}), ("codex", codex, {"turn_id": "u1"})],
    ids=["claude", "codex"],
)
def test_a_held_shell_write_holds_its_call_until_the_operator_answers_and_tells_it(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    repo: Path,
    shell: Shell,
    runtime: str,
    hooked: Callable[..., str],
    turn: dict[str, str],
    comment: str,
) -> None:
    agents = documented(repo, shell)
    where = {"cwd": str(repo), **turn}
    command = {"command": "printf 'More.\\n' >> AGENTS.md"}
    with (
        judged_in_its_process(
            machine, clock, notices, said, repo, runtime=runtime
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        hook = machine.host.launch("one").hook
        send(hook, hooked("SessionStart", source="startup", **where))
        started = hooked(
            "PreToolUse",
            tool_name="Bash",
            tool_input=command,
            tool_use_id="b1",
            **where,
        )
        assert send(hook, started) == ""
        agents.write_text("# Agents\nMore.\n")
        finishing = hooked(
            "PostToolUse",
            tool_name="Bash",
            tool_input=command,
            tool_use_id="b1",
            tool_response="",
            **where,
        )
        finished = pool.submit(send, hook, finishing)
        item = held_item(delivery, notices)
        collected(machine, clock)
        assert not finished.done()
        approving(item, comment)
        told = context(finished.result(timeout=PATIENCE))
    assert told == approved_line(agents, comment)
    assert agents.read_text() == "# Agents\nMore.\n"


@COMMENTS
def test_a_subagents_held_edit_waits_unlanded_until_the_operator_answers_making_one_hold(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    repo: Path,
    shell: Shell,
    tmp_path: Path,
    comment: str,
) -> None:
    """A subagent edits an operator's document in a worktree of their own, their hooks naming the session's (#213)."""
    documented(repo, shell)
    feat = tmp_path / "feat"
    shell.git(repo, "worktree", "add", "-q", "-b", "feat", str(feat))
    agents = feat / "AGENTS.md"
    edit = {
        "file_path": str(agents),
        "old_string": "# Agents\n",
        "new_string": "# Agents\n\nA line.\n",
    }
    subagent = {"cwd": str(repo), "agent_id": "a1", "agent_type": "general-purpose"}
    with (
        judged_in_its_process(
            machine, clock, notices, said, repo, runtime="claude"
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup", cwd=str(repo)))
        starting = claude(
            "PreToolUse",
            tool_name="Edit",
            tool_input=edit,
            tool_use_id="e1",
            **subagent,
        )
        started = pool.submit(send, hook, starting)
        item = held_item(delivery, notices)
        collected(machine, clock)
        assert not started.done()
        assert agents.read_text() == "# Agents\n"
        approving(item, comment)
        let = json.loads(started.result(timeout=PATIENCE))["hookSpecificOutput"]
        agents.write_text("# Agents\n\nA line.\n")
        send(
            hook,
            claude(
                "PostToolUse",
                tool_name="Edit",
                tool_input=edit,
                tool_use_id="e1",
                tool_response={},
                **subagent,
            ),
        )
        left = delivery.inbox.waiting(Operator())
    assert let["permissionDecision"] == "allow"
    # A subagent's first call is told lup's tools too, after the approval.
    told, _, _ = let["additionalContext"].partition("\n\n")
    assert told == approved_line(agents, comment)
    [hold] = [each for holds in stores(machine) for each in holds.all()]
    assert hold.agent == "a1"
    assert hold.answer is not None
    assert (hold.answer.approved, hold.answer.comment) == (True, comment)
    assert left == []


# A hold outliving the host service: the service stops while the hold's call waits,
# as it does when it restarts, and is started again; the writer's answer reaches
# them, whichever conversation they are and whichever comes first, the answer or
# their next call (#338).


class Writer(NamedTuple):
    """The conversation that made the change, as their runtime's hooks name them."""

    runtime: str
    hooked: Callable[..., str]
    """Spells a hook's payload for the runtime."""
    where: dict[str, str]
    """What their hooks carry besides the session: a subagent's ids, a turn's."""


CLAUDE = Writer("claude", claude, {})
SUBAGENT = Writer("claude", claude, {"agent_id": "a1", "agent_type": "general-purpose"})
WRITERS = pytest.mark.parametrize(
    "writer",
    [
        CLAUDE,
        SUBAGENT,
        Writer("codex", codex, {"turn_id": "u1"}),
        Writer("codex", codex, {"turn_id": "u1", "agent_id": "a1"}),
    ],
    ids=["claude", "claude-subagent", "codex", "codex-subagent"],
)
LONG_WAIT: dict[str, JsonValue] = {"on": ["operator"], "within": "PT5M"}
"""A `wait_inbox` the operator's news ends; past its time limit, a test moving the clock ends it, so one nothing ended fails rather than hangs."""
ENDING = 10
"""How long the operator's news may take to end such a wait before the test fails: under pytest's own timeout."""


def shelled(event: str, key: str, repo: Path, writer: Writer, **more: object) -> str:
    """A hook of `writer`'s shell call `key`, at `event`."""
    return writer.hooked(
        event,
        tool_name="Bash",
        tool_input={"command": "printf 'More.\\n' >> AGENTS.md"},
        tool_use_id=key,
        cwd=str(repo),
        **writer.where,
        **more,
    )


def in_its_wait(machine: Layout, repo: Path) -> None:
    """Return once the one hold is noted and its call waits on it, the process being another: a stop from here on lands while the hold waits."""
    holds = Holds(layout=machine.store(repo))
    store = Store(layout=machine.store(repo), worktree=repo)
    began = time.monotonic()
    while True:
        assert time.monotonic() - began < PATIENCE
        [hold] = holds.all()
        if holds.waited_on(hold.key) and store.state().holding:
            return
        time.sleep(0.01)


def held_through_a_stop(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    repo: Path,
    shell: Shell,
    writer: Writer,
) -> Item:
    """Have `writer` write an operator's document with a shell call, held, and stop the host service while the call waits; return the held change's item, still unanswered."""
    agents = documented(repo, shell)
    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        judged_in_its_process(
            machine, clock, notices, said, repo, runtime=writer.runtime
        ) as delivery,
    ):
        hook = machine.host.launch("one").hook
        send(hook, writer.hooked("SessionStart", source="startup", cwd=str(repo)))
        send(hook, shelled("PreToolUse", "b1", repo, writer))
        agents.write_text("# Agents\nMore.\n")
        finished = pool.submit(
            send, hook, shelled("PostToolUse", "b1", repo, writer, tool_response="")
        )
        item = held_item(delivery, notices)
        in_its_wait(machine, repo)
        assert not finished.done()
    assert finished.result(timeout=PATIENCE) == ""
    return item


def told_beside(*answers: str) -> list[str]:
    """What each of these hooks' answers told the model, those telling nothing left out."""
    return [context(each) for each in answers if each]


def settled_hold(machine: Layout) -> Hold:
    """The one hold, once a checkpoint settled it: its files no longer held."""
    [holds] = [each for each in stores(machine) if each.all()]
    [hold] = holds.all()
    assert not hold.waited()
    return hold


@WRITERS
def test_a_hold_outliving_the_service_answered_before_its_writers_next_call_is_told_once_beside_it(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    repo: Path,
    shell: Shell,
    writer: Writer,
) -> None:
    item = held_through_a_stop(
        machine, clock, notices, said, repo=repo, shell=shell, writer=writer
    )
    with judged_in_its_process(
        machine, clock, notices, said, repo, runtime=writer.runtime, again=True
    ) as delivery:
        hook = machine.host.launch("one").hook
        approving(item, "keep it")
        started = send(hook, shelled("PreToolUse", "b2", repo, writer))
        finished = send(
            hook, shelled("PostToolUse", "b2", repo, writer, tool_response="")
        )
        send(hook, shelled("PreToolUse", "b3", repo, writer))
        after = send(hook, shelled("PostToolUse", "b3", repo, writer, tool_response=""))
        left = delivery.inbox.waiting(Operator())
    told = told_beside(started, finished)
    assert sum("which they have since approved: keep it." in each for each in told) == 1
    assert after == ""
    assert left == []
    assert settled_hold(machine).orphaned
    assert (repo / "AGENTS.md").read_text() == "# Agents\nMore.\n"


@WRITERS
def test_a_hold_outliving_the_service_answered_while_a_call_of_its_writers_runs_is_told_once_beside_it(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    repo: Path,
    shell: Shell,
    writer: Writer,
) -> None:
    item = held_through_a_stop(
        machine, clock, notices, said, repo=repo, shell=shell, writer=writer
    )
    with judged_in_its_process(
        machine, clock, notices, said, repo, runtime=writer.runtime, again=True
    ):
        hook = machine.host.launch("one").hook
        started = send(hook, shelled("PreToolUse", "b2", repo, writer))
        approving(item, "keep it")
        finished = send(
            hook, shelled("PostToolUse", "b2", repo, writer, tool_response="")
        )
    told = told_beside(started, finished)
    assert sum("which they have since approved: keep it." in each for each in told) == 1
    assert settled_hold(machine).orphaned


@WRITERS
def test_a_hold_outliving_the_service_answered_while_its_writer_waits_ends_the_wait_as_the_operators_news(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    repo: Path,
    shell: Shell,
    writer: Writer,
) -> None:
    item = held_through_a_stop(
        machine, clock, notices, said, repo=repo, shell=shell, writer=writer
    )
    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        judged_in_its_process(
            machine, clock, notices, said, repo, runtime=writer.runtime, again=True
        ) as delivery,
    ):
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        starting = writer.hooked(
            "PreToolUse",
            tool_name="mcp__lup__wait_inbox",
            tool_input=LONG_WAIT,
            tool_use_id="w1",
            cwd=str(repo),
            **writer.where,
        )
        stamped = json.loads(send(hook, starting))["hookSpecificOutput"]["updatedInput"]
        waiting = pool.submit(call, mcp, "wait_inbox", stamped)
        assert delivery.holding.wait(timeout=PATIENCE)
        approving(item, "keep it")
        ended = wait([waiting], timeout=ENDING).done
        clock.sleep(600)
        returned, failed = waiting.result(timeout=PATIENCE)
        send(
            hook,
            writer.hooked(
                "PostToolUse",
                tool_name="mcp__lup__wait_inbox",
                tool_input=stamped,
                tool_use_id="w1",
                tool_response="",
                cwd=str(repo),
                **writer.where,
            ),
        )
        send(hook, shelled("PreToolUse", "b2", repo, writer))
        finished = send(
            hook, shelled("PostToolUse", "b2", repo, writer, tool_response="")
        )
    assert not failed
    assert "which they have since approved: keep it." in returned
    assert ended
    assert finished == ""
    assert settled_hold(machine).orphaned


def test_a_subagents_hold_outliving_the_service_is_told_to_them_not_to_whoever_ends_a_turn_first(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    repo: Path,
    shell: Shell,
) -> None:
    """Their session's own turn's end runs the checkpoint that settles it: what it found is the subagent's to hear."""
    item = held_through_a_stop(
        machine, clock, notices, said, repo=repo, shell=shell, writer=SUBAGENT
    )
    with judged_in_its_process(
        machine, clock, notices, said, repo, runtime="claude", again=True
    ):
        hook = machine.host.launch("one").hook
        approving(item, "")
        ended = send(hook, claude("Stop", cwd=str(repo)))
        assert settled_hold(machine).orphaned
        started = send(hook, shelled("PreToolUse", "b2", repo, SUBAGENT))
        finished = send(
            hook, shelled("PostToolUse", "b2", repo, SUBAGENT, tool_response="")
        )
    assert "approved" not in ended
    told = told_beside(started, finished)
    assert sum("which they have since approved." in each for each in told) == 1


def test_a_decline_of_a_hold_outliving_the_service_is_told_once_and_puts_the_file_back(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    repo: Path,
    shell: Shell,
) -> None:
    item = held_through_a_stop(
        machine, clock, notices, said, repo=repo, shell=shell, writer=SUBAGENT
    )
    with judged_in_its_process(
        machine, clock, notices, said, repo, runtime="claude", again=True
    ):
        hook = machine.host.launch("one").hook
        inbox("answer", str(item.number), "--decline", "--comment", "not here")
        started = send(hook, shelled("PreToolUse", "b2", repo, SUBAGENT))
        finished = send(
            hook, shelled("PostToolUse", "b2", repo, SUBAGENT, tool_response="")
        )
    told = told_beside(started, finished)
    assert (
        sum("which they have since declined: not here." in each for each in told) == 1
    )
    assert (repo / "AGENTS.md").read_text() == "# Agents\n"
    assert settled_hold(machine).orphaned


def noted_hold(
    machine: Layout,
    clock: FakeClock,
    repo: Path,
    *,
    agent: str | None = None,
    abandoned: bool = False,
    commit: str | None = None,
) -> Hold:
    """Keep a hold of `agent`'s in `repo`'s store, its files held as a checkpoint notes them, no call waiting on it, and put it in the operator's inbox."""
    holds = Holds(layout=machine.store(repo))
    hold = holds.put(
        Hold(
            key=holds.unused(),
            worktree=repo,
            session="s1",
            agent=agent,
            created=clock.now(),
            files=[
                HeldFile(
                    path=Path("AGENTS.md"),
                    role="operator",
                    blob="abc",
                    reasons=["operator"],
                    asks=["AGENTS.md is one of the operator's documents"],
                )
            ],
            diff="+a line\n",
            abandoned=abandoned,
            commit=commit,
        )
    )
    kept = Held(hold=hold.key, path=Path("AGENTS.md"), blob="abc")
    write_model(holds.layout.state, WorktreeState(holding=[kept]))
    whole = ChangedFile(path=Path("AGENTS.md"), before=None, after=Text(text="+\n"))
    InboxAnnouncing(layout=machine.host, clock=clock).announced(
        hold, "claude", repo / ".git", [whole]
    )
    return hold


def answering_holds(machine: Layout, delivery: Watched) -> None:
    """Have `delivery` write each held change's answer to its hold, and say what nothing told, as `lup-dev host`'s does."""
    delivery.settle_hold = lambda change, approved, comment: cli.hold_answered(
        machine, change, approved=approved, comment=comment
    )
    delivery.hold_unheard = lambda change: cli.hold_unheard(machine, change)


GONE = (
    "lup's host service went away while your call waited for the operator's answer "
    "to the change to"
)
SETTLED = (
    "The next checkpoint in its worktree keeps it, and you hear more only where the "
    "file has changed since and it isn't in place."
)


def test_a_held_changes_answer_goes_through_the_inbox_where_no_call_waits_to_hear_it(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], repo: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        answering_holds(machine, delivery)
        launched(machine, clock, repo, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        hold = noted_hold(machine, clock, repo)
        [item] = delivery.inbox.waiting(Operator())
        approving(item, "keep it")
        told = send(hook, bash("b1"))
        again = send(hook, bash("b2"))
        left = delivery.inbox.waiting(Operator())
    assert context(told).endswith(
        f'from="operator" kind="note">{GONE} {repo}/AGENTS.md, which they have since '
        f"approved: keep it. {SETTLED}</message>"
    )
    assert again == ""
    assert left == []
    kept = Holds(layout=machine.store(repo)).get(hold.key)
    assert kept is not None
    assert kept.told


def test_a_held_changes_answer_a_call_waits_to_hear_goes_to_that_call_alone(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], repo: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        answering_holds(machine, delivery)
        launched(machine, clock, repo, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        hold = noted_hold(machine, clock, repo)
        [item] = delivery.inbox.waiting(Operator())
        with Holds(layout=machine.store(repo)).waiting(hold.key):
            approving(item, "")
            told = send(hook, bash("b1"))
    assert told == ""


def test_a_held_changes_answer_for_a_subagent_who_ended_goes_to_their_session(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], repo: Path
) -> None:
    records = Subagents(repo.parent / "records")
    with inboxed(machine, clock, notices, said) as delivery:
        answering_holds(machine, delivery)
        launched(machine, clock, repo, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        send(hook, records.call("a1", "Explore", "c1"))
        send(hook, records.ended("a1", "Explore", None))
        send(hook, claude("UserPromptSubmit", prompt="Go on."))
        noted_hold(machine, clock, repo, agent="a1")
        [held] = [
            each
            for each in delivery.inbox.waiting(Operator())
            if isinstance(each.reason, HeldChange)
        ]
        approving(held, "")
        told = context(send(hook, bash("b1")))
    assert f"{GONE} {repo}/AGENTS.md, which they have since approved. {SETTLED}" in told
    assert "whose conversation had ended" in told


def test_a_held_changes_answer_after_its_hold_timed_out_ends_a_wait_as_the_operators_news(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], repo: Path
) -> None:
    with (
        inboxed(machine, clock, notices, said) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        answering_holds(machine, delivery)
        launched(machine, clock, repo, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        noted_hold(machine, clock, repo, abandoned=True)
        [item] = delivery.inbox.waiting(Operator())
        waiting = pool.submit(
            call, machine.host.launch("one").mcp, "wait_inbox", {"on": ["operator"]}
        )
        assert delivery.holding.wait(timeout=PATIENCE)
        approving(item, "")
        returned, failed = waiting.result(timeout=PATIENCE)
    assert not failed
    assert returned.endswith(
        'from="operator" kind="note">After the hold timed out, the operator approved '
        f"the change to {repo}/AGENTS.md. Your version was saved when it was put back."
        "</message>"
    )


def test_a_moves_answer_is_left_to_the_checkpoint_that_tells_it(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], repo: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        answering_holds(machine, delivery)
        launched(machine, clock, repo, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        noted_hold(machine, clock, repo, commit="c0ffee")
        [item] = delivery.inbox.waiting(Operator())
        approving(item, "")
        told = send(hook, bash("b1"))
    assert told == ""


@pytest.mark.parametrize(
    "writer", [CLAUDE.where, SUBAGENT.where], ids=["main", "subagent"]
)
def test_an_answer_nothing_told_ends_the_wait_of_its_writer_once(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    repo: Path,
    writer: dict[str, str],
) -> None:
    """Answered with its call waiting, which stopped with the service before it looked: told as its writer waits for it, whoever they are."""
    with (
        inboxed(machine, clock, notices, said) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        answering_holds(machine, delivery)
        launched(machine, clock, repo, "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        hold = noted_hold(machine, clock, repo, agent=writer.get("agent_id"))
        [item] = delivery.inbox.waiting(Operator())
        with Holds(layout=machine.store(repo)).waiting(hold.key):
            approving(item, "")
        starting = lup_call("wait_inbox", {"on": ["operator"]}, "w1", **writer)
        stamped = json.loads(send(hook, starting))["hookSpecificOutput"]["updatedInput"]
        returned, failed = pool.submit(call, mcp, "wait_inbox", stamped).result(
            timeout=PATIENCE
        )
        told = send(hook, bash("b1", **writer))
    assert not failed
    assert (
        f"{GONE} {repo}/AGENTS.md, which they have since approved. {SETTLED}"
        in returned
    )
    assert "approved" not in told


def test_a_flagged_write_is_an_item_gathering_its_file_a_comment_reaching_its_agent(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
    *,
    kit: Kit,
    repo: Path,
) -> None:
    kit.runtime.called = "claude"
    kit.announced.holding_all = False
    flagging = InboxFlagging(layout=machine.host, clock=clock)
    bench = Bench(
        runtime=kit.runtime,
        services=kit.bench.services.model_copy(update={"flagging": flagging}),
    )
    rooms = repo / "src" / "pkg" / "rooms.py"
    first = '"""Rooms."""\n'
    room = "\n\nclass Room:\n    pass\n"
    hall = "\n\nclass Hall:\n    pass\n"

    def landed(proposal: Overwrite | Replacement) -> str:
        decision = before(bench, proposal, "s1", repo)
        CallStarted(
            session="s1", cwd=repo, call=proposal.call, tool=proposal.tool
        ).apply(bench)
        current = rooms.read_text() if rooms.is_file() else None
        rooms.write_text(proposal.content(current) or "")
        CallFinished(
            session="s1", cwd=repo, call=proposal.call, tool=proposal.tool
        ).apply(bench)
        return decision.told

    sender = Conversation(repository=repo / ".git", runtime="claude", session="s1")
    with inboxed(machine, clock, notices, said) as delivery:
        launched(
            machine,
            clock,
            tmp_path / "launch",
            "one",
            "claude",
            repository=sender.repository,
        )
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        told = [
            landed(Overwrite(call="w1", tool="Write", path=rooms, text=first)),
            landed(
                Replacement(
                    call="e1", tool="Edit", path=rooms, old=first, new=first + room
                )
            ),
        ]
        [item] = delivery.inbox.waiting(Operator())
        host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
        files = host.ask(ShowFiles(number=item.number), Files).files
        shown = inbox("show", str(item.number))
        diff = inbox("show", str(item.number), "--diff")
        # Commented on in the draft, it's read: the next flagged write is an item of its own.
        drafting(
            machine,
            clock,
            Draft(
                comments=[Comment(item=item.number, text="Yes, but call it Chamber.")]
            ),
        )
        kept = first + room
        landed(
            Replacement(call="e2", tool="Edit", path=rooms, old=kept, new=kept + hall)
        )
        flagged = newest(delivery)
        reviews = sending(machine, clock)
        reviewed = send(hook, bash("b1"))
        drafting(machine, clock, Draft(done=[flagged]))
        marked = sending(machine, clock)
        quiet = send(hook, bash("b2"))
        states = [delivery.inbox.item(each).state for each in [item.number, flagged]]
        second = delivery.inbox.item(flagged)
    assert told == ["", ""]
    assert notices.raised == []
    assert item.sender == sender
    assert item.reason == Flagged(
        text=(
            "src/pkg/rooms.py landed, flagged for the operator's review. It holds at "
            "landing: `main` lands once they approve it."
        ),
        summary="src/pkg/rooms.py is a new production file",
        worktree=repo,
        path=Path("src/pkg/rooms.py"),
        branch="main",
        writes=2,
    )
    assert item.rank.name == "flag"
    assert item.call == "w1"
    [file] = files
    assert (file.before, file.after) == (None, Text(text=first + room))
    assert file.reading is not None
    assert [each.name for each in file.reading.asks] == ["new-file"]
    assert "src/pkg/rooms.py landed, flagged for the operator's review." in shown
    assert "+class Room:" in diff
    assert isinstance(second.reason, Flagged)
    assert (second.reason.writes, second.call) == (1, "e2")
    [review] = reviews
    assert review.recipient == sender
    assert context(reviewed) == (
        f'<review item="{review.number}" from="operator" covers="{item.number}">\n'
        f'<on item="{item.number}" kind="flagged write">\n'
        "<opening>src/pkg/rooms.py landed, flagged for the operator's review. It "
        "holds at landing: `main` lands once they approve it.</opening>\n"
        f'<comment id="{review.number}.1">Yes, but call it Chamber.</comment>\n'
        "</on>\n"
        "</review>"
    )
    # Marked read, it tells its agent nothing, and it's approved: commented on, it's read and not approved.
    assert marked == []
    assert "<review" not in quiet
    assert states == [Done(at=clock.now()), Decided(at=clock.now(), approved=True)]
    with pytest.raises(InboxError, match="it isn't withdrawn"):
        delivery.withdrawn(flagged, sender, "never mind")


def test_an_edit_flagging_nothing_refreshes_the_open_item_and_makes_none_once_its_read(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
    *,
    kit: Kit,
    repo: Path,
) -> None:
    kit.runtime.called = "claude"
    kit.announced.holding_all = False
    flagging = InboxFlagging(layout=machine.host, clock=clock)
    bench = Bench(
        runtime=kit.runtime,
        services=kit.bench.services.model_copy(update={"flagging": flagging}),
    )
    rooms = repo / "src" / "pkg" / "rooms.py"
    first = '"""Rooms."""\n'

    def landed(proposal: Overwrite | Replacement) -> None:
        before(bench, proposal, "s1", repo)
        CallStarted(
            session="s1", cwd=repo, call=proposal.call, tool=proposal.tool
        ).apply(bench)
        current = rooms.read_text() if rooms.is_file() else None
        rooms.write_text(proposal.content(current) or "")
        CallFinished(
            session="s1", cwd=repo, call=proposal.call, tool=proposal.tool
        ).apply(bench)

    def plain(call: str, line: str) -> Replacement:
        kept = rooms.read_text()
        return Replacement(
            call=call, tool="Edit", path=rooms, old=kept, new=f"{kept}{line}\n"
        )

    sender = Conversation(repository=repo / ".git", runtime="claude", session="s1")
    with inboxed(machine, clock, notices, said) as delivery:
        launched(
            machine,
            clock,
            tmp_path / "launch",
            "one",
            "claude",
            repository=sender.repository,
        )
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        landed(Overwrite(call="w1", tool="Write", path=rooms, text=first))
        landed(plain("e1", "LIMIT = 3"))
        [item] = delivery.inbox.waiting(Operator())
        host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
        [file] = host.ask(ShowFiles(number=item.number), Files).files
        drafting(machine, clock, Draft(done=[item.number]))
        sending(machine, clock)
        landed(plain("e2", "LIMIT = 4"))
        # A refresh reaching the inbox after the operator read its item, as a race would have it, makes none.
        assert isinstance(item.reason, Flagged)
        late = host.ask(
            AskFlag(
                flagged=item.reason,
                sender=sender,
                diff="",
                file=file,
                joining=item.number,
                refreshing=True,
            ),
            Shown,
        )
        items = numbers(delivery)
    # The edit flags nothing of its own: the item shows the file as it stands, its whole change judged again.
    assert item.reason == Flagged(
        text=(
            "src/pkg/rooms.py landed, flagged for the operator's review. It holds at "
            "landing: `main` lands once they approve it."
        ),
        summary="src/pkg/rooms.py is a new production file",
        worktree=repo,
        path=Path("src/pkg/rooms.py"),
        branch="main",
        writes=2,
    )
    assert (file.before, file.after) == (None, Text(text=f"{first}LIMIT = 3\n"))
    assert notices.raised == []
    # Read, the item gathers no more: an edit flagging nothing makes no item.
    assert items == [item.number]
    assert (late.item.number, type(late.item.state)) == (item.number, Decided)


def test_with_no_host_service_nothing_is_held_for_the_operators_switch(
    machine: Layout, clock: FakeClock
) -> None:
    announcing = InboxAnnouncing(layout=machine.host, clock=clock)
    assert not announcing.holding("claude", "s1", None)


def asking_approval(
    tmp_path: Path,
    fingerprint: str,
    pushed_by: Conversation | None = None,
    files: list[ChangedFile] | None = None,
    *,
    typing: bool = False,
) -> AskApproval:
    """An approval of the repository at `tmp_path`, its zone at `fingerprint`, asked by `pushed_by`'s push, or by a launch; its files read from their parse alone where `typing`."""
    return AskApproval(
        question="Approve the host zone at abc?",
        summary="A summary.",
        diff="+the diff\n",
        files=files or [],
        typing=typing,
        repository=tmp_path / ".git",
        fingerprint=fingerprint,
        worktree=tmp_path,
        pushed_by=pushed_by,
    )


def test_an_approval_keeps_each_file_it_changes_whole_and_shows_them_on_request(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    changed = [
        ChangedFile(
            path=Path("src/a.py"),
            before=Text(text="a = 1\n"),
            after=Text(text="a = 2\n"),
        ),
        ChangedFile(path=Path("icon.png"), before=None, after=Binary(size=1150)),
        ChangedFile(path=Path("src/gone.py"), before=Text(text="gone\n"), after=None),
    ]
    with inboxed(machine, clock, notices, said):
        host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
        asked = host.ask(asking_approval(tmp_path, "zone", files=changed), Shown).item
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        call(machine.host.launch("one").mcp, "note", {"remark": "A doubt."})
        shown = host.ask(ShowFiles(number=asked.number), Files)
        with pytest.raises(HostError) as unasked:
            host.ask(ShowFiles(number=asked.number + 1), Files)
    assert shown == Files(number=asked.number, files=changed)
    assert str(unasked.value) == (
        f"@{asked.number + 1} is a note, which changes no file: an approval, a "
        "held change or a flagged write does"
    )


# An approval's types, read once it's asked.


PARSED = [
    ChangedFile(
        path=Path("src/a.py"),
        before=Text(text="a = 1\n"),
        after=Text(text="a = 2\n"),
        reading=Reading(role="production"),
    )
]
"""An approval's file as it's asked, read from its parse alone."""

TYPED = [
    each.model_copy(
        update={
            "reading": Reading(
                role="production",
                findings=[
                    Found(rule="regex", message="m", start=1, end=1, taken="told")
                ],
            )
        }
    )
    for each in PARSED
]
"""The same file, its types read."""


class Typing:
    """Reads an approval's types once the test lets it go: `TYPED`, or what it's given to raise."""

    def __init__(self, raising: Exception | None = None) -> None:
        self.asked: list[tuple[str, Path, list[ChangedFile]]] = []
        """Each approval read, by its fingerprint, with its worktree and files."""
        self.going = threading.Event()
        self.raising = raising

    def __call__(
        self, approval: Approval, worktree: Path, files: list[ChangedFile]
    ) -> list[ChangedFile]:
        self.asked.append((approval.fingerprint, worktree, files))
        assert self.going.wait(timeout=60)
        if self.raising is not None:
            raise self.raising
        return TYPED


def hearing(words: str) -> tuple[threading.Event, Callable[[str], None]]:
    """An event set once the service says `words`, and what it's told by."""
    heard = threading.Event()

    def told(line: str) -> None:
        if words in line:
            heard.set()

    return heard, told


def approval_numbered(items: list[Item], number: int) -> Approval:
    [item] = [each for each in items if each.number == number]
    assert isinstance(item.reason, Approval)
    return item.reason


def test_an_approvals_types_are_read_after_it_and_its_files_kept_again(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    typing = Typing()
    read, told = hearing("its types are read")
    with inboxed(machine, clock, notices, said, typed=typing, told=told):
        host = client(machine.host, clock)
        asked = host.ask(
            asking_approval(tmp_path, "zone", files=PARSED, typing=True), Shown
        ).item
        first = host.ask(asking_approval(tmp_path / "other", "zone"), Shown).item
        before = host.ask(ShowFiles(number=asked.number), Files).files
        waiting = host.ask(ListInbox(), Items).items
        typing.going.set()
        assert read.wait(timeout=60)
        after = host.ask(ShowFiles(number=asked.number), Files).files
        items = host.ask(ListInbox(), Items).items
    assert before == PARSED
    assert approval_numbered(waiting, asked.number).typing
    assert after == TYPED
    typed = approval_numbered(items, asked.number)
    assert (typed.typing, typed.summary) == (False, "A summary.")
    # One asked with its whole reading, a first approval's, isn't read again.
    assert not approval_numbered(items, first.number).typing
    assert typing.asked == [("zone", tmp_path, PARSED)]


def test_where_an_approvals_types_cant_be_read_its_first_reading_stays_and_it_says_why(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    typing = Typing(raising=EngineError("the engine is gone"))
    typing.going.set()
    failed, told = hearing("couldn't be read")
    with inboxed(machine, clock, notices, said, typed=typing, told=told):
        host = client(machine.host, clock)
        asked = host.ask(
            asking_approval(tmp_path, "zone", files=PARSED, typing=True), Shown
        ).item
        assert failed.wait(timeout=60)
        files = host.ask(ShowFiles(number=asked.number), Files).files
        items = host.ask(ListInbox(), Items).items
    assert files == PARSED
    unread = approval_numbered(items, asked.number)
    assert not unread.typing
    assert unread.summary.splitlines() == [
        "A summary.",
        (
            "The judge couldn't read the change's types, so the review reads each "
            "file by its parse alone: the engine is gone"
        ),
    ]
    assert any("EngineError: the engine is gone" in each for each in said)


def test_an_approval_left_with_its_first_reading_is_read_by_the_next_service(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    kept = inbox_opened(machine)
    made: list[int] = []
    for fingerprint in ["zone", "decided"]:
        approval = asking_approval(tmp_path, fingerprint, typing=True).approval()
        item = kept.made(approval, Operator(), Operator(), tmp_path, clock.now())
        kept.attached(item.number, "", PARSED)
        made.append(item.number)
    zone, decided = made
    kept.kept(
        kept.item(decided).model_copy(
            update={"state": Decided(at=clock.now(), approved=False)}
        )
    )
    typing = Typing()
    typing.going.set()
    read, told = hearing("its types are read")
    with inboxed(machine, clock, notices, said, typed=typing, told=told):
        host = client(machine.host, clock)
        assert read.wait(timeout=60)
        files = host.ask(ShowFiles(number=zone), Files).files
    assert files == TYPED
    assert typing.asked == [("zone", tmp_path, PARSED)]


def test_a_comment_on_an_approval_a_push_asked_reaches_the_session_that_pushed(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        pusher = delivery.running("one")
        assert pusher is not None
        assert pusher == Conversation(
            repository=tmp_path / ".git", runtime="claude", session="s1"
        )
        assert delivery.running("two") is None
        host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
        asked = host.ask(asking_approval(tmp_path, "zone", pusher), Shown).item
        settled = host.ask(
            AnswerApproval(
                number=asked.number,
                approved=False,
                comment="Split the reader out first.",
            ),
            Settled,
        )
        declined = newest(delivery)
        told = send(hook, bash("b1"))
        quiet = host.ask(asking_approval(tmp_path, "quiet", pusher), Shown).item
        inbox("answer", str(quiet.number), "--decline")
        launch = host.ask(asking_approval(tmp_path, "launch's"), Shown).item
        inbox("answer", str(launch.number), "--decline", "--comment", "Not yet.")
        nothing = send(hook, bash("b2"))
        typed = host.ask(asking_approval(tmp_path, "typed", pusher), Shown).item
        inbox("answer", str(typed.number), "--decline", "--comment", "Not yet.")
        not_yet = newest(delivery)
        later = send(hook, bash("b3"))
        waiting = delivery.inbox.waiting(pusher)
    assert settled.here
    assert context(told) == (
        f'<message item="{declined}" from="operator" kind="note">\n'
        f"The operator declined @{asked.number}, the approval your push asked "
        '("Approve the host zone at abc?"), and commented:\n'
        "Split the reader out first.\n"
        "</message>"
    )
    assert nothing == ""
    assert context(later) == (
        f'<message item="{not_yet}" from="operator" kind="note">\n'
        f"The operator declined @{typed.number}, the approval your push asked "
        '("Approve the host zone at abc?"), and commented:\nNot yet.\n'
        "</message>"
    )
    assert waiting == []


def test_a_push_joining_an_approval_a_launch_asked_takes_the_comment_on_its_answer(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    pusher = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    with inboxed(machine, clock, notices, said) as delivery:
        host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
        launched_first = host.ask(asking_approval(tmp_path, "zone"), Shown).item
        joined = host.ask(asking_approval(tmp_path, "zone", pusher), Shown).item
        again = host.ask(asking_approval(tmp_path, "zone"), Shown).item
        kept = delivery.inbox.item(launched_first.number)
    assert joined.number == again.number == launched_first.number
    assert isinstance(kept.reason, Approval)
    assert kept.reason.pushed_by == pusher


def test_a_conversation_is_read_from_its_record_from_where_the_asker_left_it(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    home = tmp_path / "claude"
    folder = home / "projects" / "-w"
    (folder / "s1" / "subagents").mkdir(parents=True)

    def line(**fields: object) -> str:
        return json.dumps({"timestamp": "2026-10-17T12:00:00.000Z", **fields})

    def human(text: str) -> str:
        return line(
            type="user",
            origin={"kind": "human"},
            message={"role": "user", "content": text},
        )

    def agent(*blocks: dict[str, object]) -> str:
        return line(
            type="assistant", message={"role": "assistant", "content": list(blocks)}
        )

    record = folder / "s1.jsonl"
    record.write_text(
        "\n".join([human("Go."), agent({"type": "text", "text": "Going."})]) + "\n"
    )
    recorded = {
        "claude": Recorded(
            records=ClaudeRecords(directory=home), reader=ClaudeTranscripts()
        )
    }
    with inboxed(machine, clock, notices, said, recorded):
        host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
        first = host.ask(ShowConversation(runtime="claude", session="s1"), Conversed)
        with record.open("a") as grown:
            grown.write(
                agent(
                    {
                        "type": "tool_use",
                        "id": "b1",
                        "name": "Bash",
                        "input": {"command": "ls"},
                    }
                )
                + "\n"
            )
        after = host.ask(
            ShowConversation(runtime="claude", session="s1", since=first.total),
            Conversed,
        )
        with pytest.raises(HostError) as missing:
            host.ask(ShowConversation(runtime="claude", session="s9"), Conversed)
    when = datetime(2026, 10, 17, 12, tzinfo=UTC)
    assert first.entries == [
        Said(by="operator", text="Go.", at=when),
        Said(by="agent", text="Going.", at=when),
    ]
    assert (after.since, after.total) == (2, 3)
    assert after.entries == [Called(tool="Bash", gist="ls", id="b1", at=when)]
    assert str(missing.value) == "the record of claude session s9 isn't on this machine"


def test_a_sessions_last_message_of_a_turn_is_a_note_in_the_operators_inbox(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        ended = send(
            hook,
            claude("Stop", stop_hook_active=False, last_assistant_message="Done now."),
        )
        send(
            hook,
            claude(
                "SubagentStop",
                agent_id="sub",
                agent_type="general-purpose",
                stop_hook_active=False,
                last_assistant_message="A subagent's, for its parent.",
            ),
        )
        send(hook, claude("Stop", stop_hook_active=False, last_assistant_message="  "))
        notes = [
            (each.reason, each.sender.agent, each.worktree)
            for each in delivery.inbox.waiting(Operator())
            if isinstance(each.sender, Conversation)
        ]
    assert ended == ""
    assert notes == [
        (Message(kind="note", text="Done now.", ending=True), None, tmp_path)
    ]
    assert notices.raised == []


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_a_turns_end_held_to_tell_an_item_still_puts_its_message_before_the_operator(
    runtime: str,
    *,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
) -> None:
    """The end the operator's message holds makes its note, as the agent ended with it, after the message it's told; the turn's next end makes its own."""
    payload = {"claude": claude, "codex": codex}[runtime]
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", runtime)
        hook = machine.host.launch("one").hook
        send(hook, payload("SessionStart", source="startup"))
        inbox("send", "one", "One more thing.")
        sent = newest(delivery)
        held = json.loads(
            send(
                hook,
                payload(
                    "Stop",
                    stop_hook_active=False,
                    last_assistant_message="Two decisions for you.",
                ),
            )
        )
        decisions = newest(delivery)
        ended = send(
            hook,
            payload("Stop", stop_hook_active=True, last_assistant_message="Done now."),
        )
        done = newest(delivery)
        told = delivery.inbox.item(sent).state
        notes = [
            (each.number, each.reason)
            for each in delivery.inbox.waiting(Operator())
            if isinstance(each.sender, Conversation)
        ]
    holding = {
        "claude": held.get("hookSpecificOutput", {}).get("additionalContext"),
        "codex": held.get("reason") if held.get("decision") == "block" else None,
    }[runtime]
    assert holding == note(sent, "One more thing.")
    assert told == Told(at=clock.now(), how="turn's end")
    assert ended == ""
    assert notes == [
        (decisions, Message(kind="note", text="Two decisions for you.", ending=True)),
        (done, Message(kind="note", text="Done now.", ending=True, answers=[sent])),
    ]


def test_a_draft_that_answers_nothing_is_refused_and_a_mark_on_the_operator_s_own_words_dropped(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        call(machine.host.launch("one").mcp, "ask", {"question": "In words?"})
        inbox("send", "one", "Mine.")
        mine = newest(delivery)
        empty = refused_draft(machine, clock, Draft())
        drafting(machine, clock, Draft(done=[mine]))
        own = client(machine.host, clock).ask(SendDraft(), Reviewed)
        left = delivery.inbox.draft()
    assert empty == (
        "the draft answers no item and writes to no agent: comment on an item, take "
        "one off the list, or write to an agent under their banner"
    )
    # A mark on the operator's own message is dropped, said, never refusing the reply.
    [dropped] = own.unanswerable
    assert dropped.said == (
        f"@{mine} not marked done: it's a note from the operator, which a reply "
        "doesn't answer"
    )
    assert left == Draft()


def refused_draft(machine: Layout, clock: FakeClock, draft: Draft) -> str:
    drafting(machine, clock, draft)
    with pytest.raises(HostError) as refusal:
        sending(machine, clock)
    return str(refusal.value)


def test_a_message_sent_from_reading_a_conversation_quotes_each_passage_it_replies_to(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    passages = [
        Passage(
            quote="Twenty kinds of line.\n\nFour carry what was said.",
            text="Which four?",
        ),
        Passage(quote="JSONL </quote>", text="Even with a closing tag?"),
    ]
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        host = client(machine.host, clock)
        sent = host.ask(
            SendItem(launch="one", text="Carry on after.", passages=passages), Shown
        ).item
        bare = host.ask(
            SendItem(launch="one", text="", passages=passages[:1]), Shown
        ).item
        told = context(send(hook, bash("b1")))
        assert isinstance(sent.recipient, Conversation)
        listed = host.ask(ListItems(conversation=sent.recipient), Exchanged)
        [named] = host.listed().launches
    assert sent.reason == Message(
        kind="note", text="Carry on after.", passages=passages
    )
    # Its recipient is said by their path, their session's name as their launch has it.
    assert named.name is not None
    assert listed.path(sent.recipient) == named.name

    def quoted(item: int) -> str:
        """The first passage's quote and reply, as item `item` carries them, the reply numbered as its first part."""
        return (
            "<quote>\nTwenty kinds of line.\n\nFour carry what was said.\n</quote>\n"
            f'<reply id="{item}.1">Which four?</reply>'
        )

    assert told == (
        f'<message item="{sent.number}" from="operator" kind="note">\n'
        f"{quoted(sent.number)}\n"
        "<quote>JSONL <\\/quote></quote>\n"
        f'<reply id="{sent.number}.2">Even with a closing tag?</reply>\n'
        "Carry on after.\n"
        "</message>\n\n"
        f'<message item="{bare.number}" from="operator" kind="note">\n'
        f"{quoted(bare.number)}\n</message>"
    )
    # What the dashboard shows is what's inside each tag.
    assert listed.received[1].text == quoted(bare.number)
    # A message with no words of its own opens with its first reply.
    assert opening(bare) == "Which four?"


def test_lup_dev_inbox_send_reaches_a_subagent_by_its_path(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="explore-auth"))
        records.recorded("a1", "Explore", "t1", name="explore-auth")
        send(hook, records.call("a1", "Explore", "c1"))
        sent = inbox("send", "w/explore-auth", "Look at the tests too.")
        number = newest(delivery)
        told = context(send(hook, records.call("a1", "Explore", "c2")))
        main = send(hook, bash("b1"))
    assert sent == f"Sent @{number} to `w/explore-auth`.\n"
    assert told == note(number, "Look at the tests too.")
    assert main == ""


def test_an_items_moment_is_read_from_its_senders_record_around_its_call(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    home = tmp_path / "claude"
    folder = home / "projects" / "-w"
    folder.mkdir(parents=True)

    def line(**fields: object) -> str:
        return json.dumps({"timestamp": "2026-10-17T12:00:00.000Z", **fields})

    def human(text: str) -> str:
        return line(
            type="user",
            origin={"kind": "human"},
            message={"role": "user", "content": text},
        )

    def agent(*blocks: dict[str, object]) -> str:
        return line(
            type="assistant", message={"role": "assistant", "content": list(blocks)}
        )

    (folder / "s1.jsonl").write_text(
        "\n".join(
            [
                human("Build it."),
                agent({"type": "text", "text": "Reading."}),
                agent({"type": "tool_use", "id": "b1", "name": "Bash", "input": {}}),
                agent(
                    {
                        "type": "tool_use",
                        "id": "n1",
                        "name": "mcp__lup__note",
                        "input": {},
                    }
                ),
                agent({"type": "text", "text": "Carrying on."}),
                human("Next."),
            ]
        )
        + "\n"
    )
    recorded = {
        "claude": Recorded(
            records=ClaudeRecords(directory=home), reader=ClaudeTranscripts()
        )
    }
    with inboxed(machine, clock, notices, said, recorded) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        stamped = json.loads(send(hook, lup_call("note", {"remark": "UTF-8."}, "n1")))[
            "hookSpecificOutput"
        ]["updatedInput"]
        call(machine.host.launch("one").mcp, "note", stamped)
        noted = newest(delivery)
        inbox("send", "one", "Mine.")
        mine = newest(delivery)
        host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
        found = host.ask(ShowContext(number=noted), Context)
        with pytest.raises(HostError) as unanchored:
            host.ask(ShowContext(number=mine), Context)
        shown = runner.invoke(cli.app, ["inbox", "show", str(noted), "--context"])
        item = delivery.inbox.item(noted)
    assert item.call == "n1"
    when = datetime(2026, 10, 17, 12, tzinfo=UTC)
    assert found.entries == [
        Said(by="operator", text="Build it.", at=when),
        Said(by="agent", text="Reading.", at=when),
        Called(tool="Bash", id="b1", at=when),
        Called(tool="mcp__lup__note", id="n1", at=when),
        Said(by="agent", text="Carrying on.", at=when),
    ]
    assert found.anchor == 3
    assert str(unanchored.value) == f"@{mine} was made by no agent's call"
    assert shown.exit_code == 0, shown.output
    assert "· called Bash\n\n→ called mcp__lup__note: this item\n\n" in shown.output


def test_inbox_lists_this_repositorys_items_and_reads_any_of_them_whole(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        launched(machine, clock, other, "two", "codex")
        hook = machine.host.launch("one").hook
        mcp = machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(machine.host.launch("two").hook, codex("SessionStart", source="startup"))
        call(mcp, "ask", {"question": "Which parser?\nTwenty kinds of line."})
        question = newest(delivery)
        noting = lup_call(
            "note",
            {"remark": "I assumed UTF-8."},
            "n1",
            agent_id="a1",
            agent_type="general-purpose",
        )
        call(
            mcp,
            "note",
            json.loads(send(hook, noting))["hookSpecificOutput"]["updatedInput"],
        )
        noted = newest(delivery)
        call(machine.host.launch("two").mcp, "note", {"remark": "Elsewhere."})
        another = newest(delivery)
        inbox("answer", str(question), "--comment", "A model per kind.")
        answered = newest(delivery)
        # A number nothing holds, well past every number handed out.
        nothing = newest(delivery) + 100

        def reading(**arguments: JsonValue) -> str:
            text, error = call(mcp, "inbox", arguments)
            assert not error, text
            return text

        waiting = reading()
        every = reading(every=True)
        asked = reading(number=question)
        answer = reading(number=answered)
        theirs = reading(number=noted)
        elsewhere = reading(number=another)
        missing = reading(number=nothing)
        reads = json.loads(
            send(
                hook,
                lup_call(
                    "inbox",
                    {"number": noted},
                    "r1",
                    agent_id="a1",
                    agent_type="general-purpose",
                ),
            )
        )
        own = call(mcp, "inbox", reads["hookSpecificOutput"]["updatedInput"])
        listed = inbox()
    at = "2026-10-01 12:00"
    sub = f"`{tmp_path.name}/a1`"
    assert waiting.splitlines() == [
        f"@{noted}  {at}  a note from {sub} to the operator, waiting: I assumed UTF-8.",
        (
            f"@{answered}  {at}  an answer from the operator to you, waiting: A model "
            "per kind."
        ),
        "Not listed: 1 item no longer waiting, which `every` lists.",
    ]
    assert every.splitlines() == [
        (
            f"@{question}  {at}  a question from you to the operator, answered at "
            f"{at}, @{answered}: Which parser?"
        ),
        *waiting.splitlines()[:-1],
    ]
    assert asked == (
        f"@{question}, a question you sent to the operator at {at}, answered at "
        f'{at}, @{answered}:\n<part id="{question}.1">\nWhich parser?\nTwenty kinds '
        "of line.\n</part>"
    )
    assert answer == (
        f'<answer item="{answered}" from="operator" question="{question}">\n'
        "<asked>\nWhich parser?\nTwenty kinds of line.\n</asked>\n"
        f'<comment id="{answered}.1">A model per kind.</comment>\n'
        "</answer>\n\nIt's waiting."
    )
    assert theirs == (
        f"@{noted}, a note from {sub} to the operator at {at}, waiting:\n"
        f'<part id="{noted}.1">I assumed UTF-8.</part>'
    )
    # Another repository's item is refused as one nothing holds is.
    assert (elsewhere, missing) == tuple(
        f"@{each} isn't among this repository's: `inbox` reads this repository's "
        "items alone."
        for each in [another, nothing]
    )
    assert own == (
        (
            f"@{noted}, a note you sent to the operator at {at}, waiting:\n"
            f'<part id="{noted}.1">I assumed UTF-8.</part>'
        ),
        False,
    )
    assert f"{cited(answered):>5}  " not in listed
    assert [line.split()[0] for line in listed.splitlines()] == [
        f"@{noted}",
        f"@{another}",
    ]


def test_inbox_and_lup_dev_inbox_list_the_latest_within_a_time_saying_what_they_left_out(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        mcp = machine.host.launch("one").mcp
        # The note of each hour, by its hour: `made[0]` is Note 1's number.
        made: list[int] = []
        for hour in range(5):
            call(mcp, "note", {"remark": f"Note {hour + 1}."})
            made.append(newest(delivery))
            clock.sleep(3600)
        threads = delivery.inbox.ledger.every(Thread)

        def reading(**arguments: JsonValue) -> str:
            text, error = call(mcp, "inbox", arguments)
            assert not error, text
            return text

        latest = reading(limit=2)
        earlier = reading(limit=2, until="2026-10-01T15:00:00+00:00")
        recent = reading(since="PT2H30M")
        between = reading(since="2026-10-01T13:00", until="2026-10-01T15:00")
        quiet = reading(since="PT10M")
        every = reading()
        nothing, refused = call(mcp, "inbox", {"limit": 0})
        operators = inbox("--limit", "2")
        operators_between = inbox("--since", "PT4H30M", "--until", "PT2H30M")
        operators_quiet = inbox("--since", "PT10M")
        unread = runner.invoke(cli.app, ["inbox", "--since", "yesterday"])

    # Each note lands in no thread.
    assert threads == []

    def note(hour: int) -> str:
        return (
            f"@{made[hour - 1]}  2026-10-01 {11 + hour}:00  a note from you to the "
            f"operator, waiting: Note {hour}."
        )

    assert latest.splitlines() == [
        note(4),
        note(5),
        (
            'Not listed: 3 earlier items, which `until` "2026-10-01T15:00:00+00:00" '
            "reads; a `limit` of 5 lists them all."
        ),
    ]
    assert earlier.splitlines() == [
        note(2),
        note(3),
        (
            'Not listed: 1 earlier item, which `until` "2026-10-01T13:00:00+00:00" '
            "reads; a `limit` of 3 lists them all."
        ),
    ]
    assert recent.splitlines() == [note(4), note(5)]
    assert between.splitlines() == [note(2), note(3)]
    assert quiet == (
        "Nothing about this repository waits in the inbox since 2026-10-01 16:50."
    )
    assert every.splitlines() == [note(hour) for hour in range(1, 6)]
    assert refused
    assert "limit" in nothing
    listed = operators.splitlines()
    assert [line.split()[0] for line in listed[:-1]] == [
        cited(each) for each in made[3:]
    ]
    assert listed[-1] == (
        'Not listed: 3 earlier items, which `--until` "2026-10-01T15:00:00+00:00" '
        "reads; a `--limit` of 5 lists them all."
    )
    assert [line.split()[0] for line in operators_between.splitlines()] == [
        cited(each) for each in made[1:3]
    ]
    assert operators_quiet == "Nothing made in that time waits for you.\n"
    assert unread.exit_code != 0
    assert "--since and --until each take an ISO 8601 time" in unread.output


def test_an_agent_withdraws_its_own_waiting_item_and_nothing_else(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        mcp = machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        call(mcp, "note", {"remark": "Is the build red for you too?"})
        red = newest(delivery)
        call(mcp, "ask", {"question": "Which parser?"})
        question = newest(delivery)
        noting = lup_call(
            "note",
            {"remark": "I assumed UTF-8."},
            "n1",
            agent_id="a1",
            agent_type="general-purpose",
        )
        call(
            mcp,
            "note",
            json.loads(send(hook, noting))["hookSpecificOutput"]["updatedInput"],
        )
        subagents = newest(delivery)
        inbox("answer", str(question), "--comment", "A model per kind.")
        answer = newest(delivery)

        def withdrawing(number: int) -> str:
            text, error = call(
                mcp, "withdraw", {"number": number, "why": "It's green now."}
            )
            assert not error, text
            return text

        taken = withdrawing(red)
        again = withdrawing(red)
        answered = withdrawing(question)
        theirs = withdrawing(subagents)
        listed = inbox()
        shown = inbox("show", str(red))
    assert taken == f"@{red} is withdrawn, off the operator's list."
    assert again == (
        f"Not withdrawn: @{red} no longer waits for the operator: it's withdrawn at "
        "2026-10-01 12:00 by its sender: It's green now."
    )
    assert answered == (
        f"Not withdrawn: @{question} no longer waits for the operator: it's answered "
        f"at 2026-10-01 12:00, @{answer}"
    )
    assert theirs == (
        f"Not withdrawn: @{subagents} is a note from `{tmp_path.name}/a1`: "
        "only its sender withdraws it"
    )
    assert [line.split()[0] for line in listed.splitlines()] == [f"@{subagents}"]
    assert "withdrawn at 2026-10-01 12:00 by its sender: It's green now." in shown
    assert f"@{red}, a note, was withdrawn by its sender" in said


def test_judged_reads_a_sessions_verdicts_and_its_repositorys_holds_changing_nothing(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    kit: Kit,
    *,
    repo: Path,
    linked: Path,
    bare: Path,
) -> None:
    core = Path("src/pkg/core.py")
    main = bare / "tree" / "main"
    original = (repo / core).read_text()
    store = Holds(layout=kit.layout.store(repo))
    # The judge's verdicts and holds carry the runtime the bench names.
    kit.runtime.called = "claude"
    with inboxed(machine, clock, notices, said, judging=kit.layout):
        launched(machine, clock, repo, "one", "claude")
        launched(machine, clock, main, "two", "codex", repository=bare)
        hook = machine.host.launch("one").hook
        mcp = machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(machine.host.launch("two").hook, codex("SessionStart", source="startup"))

        def judged(on: Path = mcp, **arguments: JsonValue) -> str:
            text, error = call(on, "judged", arguments)
            assert not error, text
            return text

        before(
            kit.bench,
            Replacement(
                call="e1",
                tool="Edit",
                path=repo / core,
                old="return x\n",
                new="return x  # BAD regex\n",
            ),
            "s1",
            repo,
        )
        kit.clock.sleep(60)
        kit.announced.answering = None
        waiting: list[str] = []

        def answered_later() -> None:
            [hold] = store.all()
            waiting.append(judged())
            kit.clock.sleep(23 * 60)
            answer = Response(approved=True, comment="Fine, as a whole.")
            store.answer(hold.key, answer, kit.clock)

        kit.clock.on_sleep.append(answered_later)
        whole = Overwrite(
            call="w1", tool="Write", path=repo / core, text=original + "\n"
        )
        before(kit.bench, whole, "s1", repo, agent="a1")
        kit.announced.answering = Response(
            approved=False, comment="Not the git directory."
        )
        described = Overwrite(
            call="w2", tool="Write", path=repo / ".git" / "description", text="Work.\n"
        )
        before(kit.bench, described, "s1", repo)
        kit.clock.sleep(60)
        before(
            kit.bench,
            Replacement(
                call="e2", tool="Edit", path=linked / core, old="x\n", new="x + 1\n"
            ),
            "s2",
            linked,
        )
        kit.runtime.called = "codex"
        kit.announced.answering = Response(approved=True)
        elsewhere = Overwrite(
            call="w3", tool="Write", path=main / core, text=original + "\n"
        )
        before(kit.bench, elsewhere, "t1", main)
        state = kit.layout.state
        kept = {each: each.read_bytes() for each in state.rglob("*") if each.is_file()}
        own = judged()
        every = judged(every=True, answered=True)
        relative = judged(every=True, path="src/pkg/core.py", answered=True)
        absolute = judged(path=str(linked / core))
        # The service's clock, which a duration counts back by, at the judge's.
        clock.time = kit.clock.now()
        recent = judged(every=True, since="PT2M")
        between = judged(
            since="2026-10-01T12:01", until="2026-10-01T12:24:00+00:00", answered=True
        )
        stamped = json.loads(
            send(
                hook,
                lup_call(
                    "judged", {}, "j1", agent_id="a1", agent_type="general-purpose"
                ),
            )
        )["hookSpecificOutput"]["updatedInput"]
        subagent = judged(**stamped, answered=True)
        other = judged(machine.host.launch("two").mcp, answered=True)
        unread = call(mcp, "judged", {"every": "lots"})
        loose = call(mcp, "judged", {"since": "2h"})
        after = {each: each.read_bytes() for each in state.rglob("*") if each.is_file()}
    rewritten, declined = store.all()
    [theirs] = Holds(layout=kit.layout.store(main)).all()
    at = "2026-10-01"
    edited = f"{at} 12:00  {repo / core}  Edit  allow (regex)"
    held = f"{at} 12:01  {repo / core}  Write  hold (whole-file)"
    git = f"{at} 12:24  {repo}/.git/description  Write  hold (protected), declined"
    rewrite = [
        (
            f"{rewritten.key}  {at} 12:01  a change by your session's subagent a1, "
            f"approved at {at} 12:24"
        ),
        f"  {repo / core}: whole-file",
        "  The operator's comment: Fine, as a whole.",
    ]
    allowed = "     1  allow   regex"
    passed = "     1  allow   rules-pass"
    protected = "     1  hold    protected  (approved 0, declined 1, unanswered 0)"
    whole = "     1  hold    whole-file  (approved 1, declined 0, unanswered 0)"
    assert waiting == [
        "\n".join(
            [
                "Your session's 2 verdicts in this repository, by outcome and reason:",
                allowed,
                "     1  hold    whole-file  (approved 0, declined 0, unanswered 0)",
                "",
                "Each, oldest first:",
                edited,
                f"{held}, no answer yet",
                "",
                "This repository's holds still open, oldest first:",
                (
                    f"{rewritten.key}  {at} 12:01  a change by your session's "
                    "subagent a1, waiting for the operator, its call waiting on "
                    "their answer"
                ),
                f"  {repo / core}: whole-file",
            ]
        )
    ]
    holds = [
        "This repository has no hold still open.",
        "",
        "This repository's holds answered, oldest first:",
        *rewrite,
        f"{declined.key}  {at} 12:24  a change by you, declined at {at} 12:24",
        f"  {repo}/.git/description: protected",
        "  The operator's comment: Not the git directory.",
    ]
    assert own.splitlines() == [
        "Your session's 3 verdicts in this repository, by outcome and reason:",
        allowed,
        protected,
        whole,
        "",
        "Each, oldest first:",
        edited,
        f"{held}, approved",
        git,
        "",
        "This repository has no hold still open.",
        "",
        "Not listed: 2 holds answered, which `answered` lists.",
    ]
    assert every.splitlines() == [
        "Every session's 4 verdicts in this repository, by outcome and reason:",
        allowed,
        passed,
        protected,
        whole,
        "",
        "Each, oldest first:",
        f"{edited}, by your session",
        f"{held}, approved, by your session",
        f"{git}, by your session",
        f"{at} 12:25  {linked / core}  Edit  allow (rules-pass), by claude session s2",
        "",
        *holds,
    ]
    on = "on src/pkg/core.py"
    assert relative.splitlines() == [
        f"Every session's 3 verdicts in this repository {on}, by outcome and reason:",
        allowed,
        passed,
        whole,
        "",
        "Each, oldest first:",
        f"{edited}, by your session",
        f"{held}, approved, by your session",
        f"{at} 12:25  {linked / core}  Edit  allow (rules-pass), by claude session s2",
        "",
        f"This repository has no hold still open {on}.",
        "",
        f"This repository's holds answered {on}, oldest first:",
        *rewrite,
    ]
    assert absolute == (
        f"Your session has no verdict in this repository on {linked / core}.\n\n"
        f"This repository has no hold on {linked / core}."
    )
    since = f"since {clocked(kit.clock.now() - timedelta(minutes=2))}"
    assert recent.splitlines() == [
        f"Every session's 2 verdicts in this repository {since}, by outcome and reason:",
        passed,
        protected,
        "",
        "Each, oldest first:",
        f"{git}, by your session",
        f"{at} 12:25  {linked / core}  Edit  allow (rules-pass), by claude session s2",
        "",
        f"This repository has no hold still open {since}.",
        "",
        f"Not listed: 1 hold answered {since}, which `answered` lists.",
    ]
    window = f"between {at} 12:01 and {at} 12:24"
    assert between.splitlines() == [
        f"Your session's 1 verdict in this repository {window}, by outcome and reason:",
        whole,
        "",
        "Each, oldest first:",
        f"{held}, approved",
        "",
        f"This repository has no hold still open {window}.",
        "",
        f"This repository's holds answered {window}, oldest first:",
        *rewrite,
    ]
    assert subagent.splitlines()[-6:] == [
        f"{rewritten.key}  {at} 12:01  a change by you, approved at {at} 12:24",
        f"  {repo / core}: whole-file",
        "  The operator's comment: Fine, as a whole.",
        (
            f"{declined.key}  {at} 12:24  a change by your session's own "
            f"conversation, declined at {at} 12:24"
        ),
        f"  {repo}/.git/description: protected",
        "  The operator's comment: Not the git directory.",
    ]
    assert other.splitlines() == [
        "Your session's 1 verdict in this repository, by outcome and reason:",
        whole,
        "",
        "Each, oldest first:",
        f"{at} 12:25  {main / core}  Write  hold (whole-file), approved",
        "",
        "This repository has no hold still open.",
        "",
        "This repository's holds answered, oldest first:",
        f"{theirs.key}  {at} 12:25  a change by you, approved at {at} 12:25",
        f"  {main / core}: whole-file",
    ]
    text, error = unread
    assert error
    assert text.startswith("Refused: 1 validation error for Scope\nevery\n")
    text, error = loose
    assert error
    assert text.startswith("Refused: 2 validation errors for Scope\nsince.datetime\n")
    assert after == kept


def test_judged_says_where_an_open_hold_stands_and_what_waits_with_it(
    clock: FakeClock,
) -> None:
    hold = Hold(
        key="k1",
        worktree=Path("/w"),
        session="s1",
        created=clock.now(),
        files=[],
        diff="",
    )
    interrupted = {"abandoned": True, "interrupted": True}
    assert [
        stands(hold, waited=True),
        stands(hold, waited=False),
        stands(hold.model_copy(update={"abandoned": True}), waited=False),
        stands(hold.model_copy(update=interrupted), waited=False),
        stands(hold.model_copy(update={"commit": "c0ffee"}), waited=False),
    ] == [
        "waiting for the operator, its call waiting on their answer",
        (
            "waiting for the operator, no call waiting on it any more: lup's host "
            "service went away mid-wait, and their answer reaches the conversation "
            "that made it beside a later call or through `wait_inbox`"
        ),
        (
            "waiting for the operator: nobody answered in time, so the change was "
            "put back and its version saved"
        ),
        (
            "waiting for the operator: its call was interrupted, so the change was "
            "put back and its version saved"
        ),
        "waiting for the operator, no call waiting on it",
    ]


def test_judged_answers_a_large_log_in_pages_an_agent_reads_whole(
    clock: FakeClock, tmp_path: Path
) -> None:
    layout = Layout(state=tmp_path / "state")
    repository = tmp_path / "repo.git"
    worktree = tmp_path / "w"
    start = clock.now() - timedelta(minutes=3000)

    def verdict(
        key: str, minute: int, session: str, outcome: str, reason: str
    ) -> Verdict:
        return Verdict.model_validate(
            {
                "key": key,
                "time": start + timedelta(minutes=minute),
                "session": session,
                "runtime": "claude",
                "tool": "Edit",
                "worktree": worktree,
                "path": f"src/pkg/m{key}.py",
                "role": "production",
                "outcome": outcome,
                "reasons": [reason],
            }
        )

    def kind(minute: int) -> tuple[str, str]:
        if minute % 97 == 0:
            return "refuse", "regex"
        return "allow", "docs" if minute % 7 == 0 else "rules-pass"

    # A minute each, the sessions in turn; three more of s1's at the moment of
    # its 49th latest, as a checkpoint judges files at once.
    logged = [
        verdict(str(minute), minute, "s1" if minute % 2 else "s2", *kind(minute))
        for minute in range(3000)
    ]
    burst = [verdict(f"b{n}", 2903, "s1", "allow", "rules-pass") for n in range(3)]
    asked = [
        verdict(f"h{n}", 10 + 100 * n, "s1", "hold", "protected") for n in range(27)
    ]
    VerdictLog(path=layout.verdicts(repository)).append([*logged, *burst, *asked])
    store = Holds(layout=layout.store(worktree))
    for n, each in enumerate(asked):
        answer = HoldAnswer(approved=True, time=each.time) if n < 25 else None
        store.put(
            Hold(
                key=f"k{n}",
                worktree=worktree,
                session="s1",
                created=each.time,
                files=[],
                diff="",
                verdicts=[each],
                answer=answer,
            )
        )
    tools = JudgeTools(layout=layout, clock=clock, modules=Predating())
    launch = Register.model_construct(
        launch="one", runtime="claude", repository=repository
    )

    def judged(**arguments: JsonValue) -> str:
        said = asyncio.run(
            tools.call("judged", arguments, launch, Caller(id="c", session="s1"), None)
        )
        assert not said.error, said.text
        return said.text

    def page(text: str) -> tuple[list[str], str | None]:
        """An answer's verdict lines, and the `until` it says reads those before."""
        listing = text.split("\n\n")[1].splitlines()[1:]
        if listing[-1].startswith("Not listed: "):
            return listing[:-1], listing[-1].split('"')[1]
        return listing, None

    first = judged()
    pages = [page(first)[0]]
    until = page(first)[1]
    while until is not None:
        lines, until_next = page(judged(until=until))
        pages.insert(0, lines)
        until = until_next
    ours = sorted(
        (each for each in [*logged, *burst, *asked] if each.session == "s1"),
        key=lambda each: each.time,
    )
    read = [line for lines in pages for line in lines]
    every = judged(every=True)
    recent = judged(since="PT2H")
    between = judged(since="2026-10-01T11:00", until="2026-10-01T11:30:00+00:00")
    answered = judged(answered=True)
    widened = judged(limit=200, holds_limit=30, answered=True)
    whole = judged(limit=len(ours))
    summary, listing, still, counted = first.split("\n\n")
    assert summary.splitlines()[0] == (
        f"Your session's {len(ours)} verdicts in this repository, by outcome and "
        "reason:"
    )
    assert "    27  hold    protected  (approved 25, declined 0, unanswered 0)" in (
        summary.splitlines()
    )
    # The latest 50 would split the burst's moment: the 48 after it are listed.
    assert listing.splitlines()[0] == "The latest 48, oldest first:"
    assert listing.splitlines()[-1] == (
        f"Not listed: {len(ours) - 48} earlier verdicts, which `until` "
        f'"{(start + timedelta(minutes=2905)).isoformat()}" reads; a `limit` of '
        f"{len(ours)} lists them all."
    )
    assert [line.split("  ")[1] for line in read] == [
        str(worktree / each.path) for each in ours
    ]
    assert len(first) < 20_000
    assert len(every) < 20_000
    assert every.split("\n\n")[1].splitlines()[0] == "The latest 50, oldest first:"
    assert still.splitlines()[0] == "This repository's holds still open, oldest first:"
    assert counted == "Not listed: 25 holds answered, which `answered` lists."
    assert recent.splitlines()[0] == (
        "Your session's 63 verdicts in this repository since 2026-10-01 10:00, by "
        "outcome and reason:"
    )
    assert between.splitlines()[0] == (
        "Your session's 15 verdicts in this repository between 2026-10-01 11:00 "
        "and 2026-10-01 11:30, by outcome and reason:"
    )
    assert "Each, oldest first:" in between.split("\n\n")[1]
    held = answered.split("\n\n")[-1].splitlines()
    assert held[0] == "This repository's holds answered, oldest first:"
    heads = [line.split()[0] for line in held[1:-1] if not line.startswith("  ")]
    assert heads == [f"k{n}" for n in range(5, 25)]
    assert held[-1] == (
        "Not listed: 5 earlier holds answered, which `until` "
        '"2026-09-29T18:30:00+00:00" reads; a `holds_limit` of 25 lists them all.'
    )
    # A larger limit lists more of them, and one as large as all lists every one.
    wider = widened.split("\n\n")[1].splitlines()
    assert wider[0] == "The latest 200, oldest first:"
    assert wider[-1].startswith(f"Not listed: {len(ours) - 200} earlier verdicts")
    every_hold = widened.split("\n\n")[-1].splitlines()
    assert [
        line.split()[0] for line in every_hold[1:] if not line.startswith("  ")
    ] == [f"k{n}" for n in range(25)]
    assert whole.split("\n\n")[1].splitlines()[0] == "Each, oldest first:"
    assert "Not listed: " not in whole.split("\n\n")[1]


def test_quiet_runs_in_the_repositorys_process_for_the_conversation_calling(
    judging: JudgingInProcess, kit: Kit, repo: Path
) -> None:
    tools = JudgeTools(layout=kit.layout, clock=kit.clock, modules=judging)
    launch = Register.model_construct(
        launch="one", runtime="claude", repository=repo / ".git"
    )
    caller = Caller(id="c", session="s1", agent="a1")

    def quiet(arguments: JsonValue) -> ToolAnswer:
        return asyncio.run(tools.call("quiet", arguments, launch, caller, "t1"))

    held = quiet({"kinds": ["importers", "rules", "importers"]})
    assert not held.error, held.text
    assert held.text.startswith(
        "You're quiet: lup doesn't tell you lup's findings on the lines changed, "
        "and type errors in the files importing what changed after your calls"
    )
    [asked] = judging.asked
    assert (asked.name, asked.caller) == ("quiet", caller)
    record = ConversationRecord(layout=kit.layout, session="s1")
    assert record.quiet("a1") == report.Quiet(kinds=["importers", "rules"])
    assert record.quiet("") == report.Quiet()
    refused = quiet({"kinds": ["everything"]})
    assert refused.error
    assert refused.text.startswith("Refused: ")
    assert record.quiet("a1") == report.Quiet(kinds=["importers", "rules"])


def test_quiet_says_so_where_the_repositorys_approved_copy_predates_it(
    kit: Kit, repo: Path
) -> None:
    tools = JudgeTools(layout=kit.layout, clock=kit.clock, modules=Predating())
    launch = Register.model_construct(
        launch="one", runtime="codex", repository=repo / ".git"
    )
    said = asyncio.run(
        tools.call("quiet", {"kinds": []}, launch, Caller(id="c", session="s1"), None)
    )
    assert said == ToolAnswer(
        text=(
            "`quiet` didn't run: no handler for `judge-call`; the repository's "
            "process answers judge-hook, module-listing. Where the repository's "
            "process answers no `judge-call`, its approved copy of lup predates "
            "`quiet`, which runs once the operator approves one that has it."
        ),
        error=True,
    )


def test_review_marks_are_read_through_the_host_by_a_module_and_a_room_of_its_repository_alone(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    repo: Path,
    *,
    tmp_path: Path,
) -> None:
    key = {"runtime": "claude", "session": "s1", "agent": None}
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, repo, "one", "claude")
        host = client(machine.host, clock)
        common = repo / ".git"
        host.ask(
            MoveMarks(
                repository=common,
                module="transcripts",
                marks=[Moving(key=key, up_to="7")],
            ),
            MarksMoved,
        )
        read = asyncio.run(
            HostMarks(layout=machine.host, clock=clock).kept(
                common, "transcripts", [key]
            )
        )
        room = RoomClient(socket=machine.host.launch("one").request)
        roomed = asyncio.run(RoomMarks(room=room).kept(common, "transcripts", [key]))
        with pytest.raises(HostError, match="aren't this repository's"):
            asyncio.run(
                RoomMarks(room=room).kept(tmp_path / "other.git", "transcripts", [key])
            )
        with pytest.raises(HostError):
            room.ask(
                MoveMarks(
                    repository=common,
                    module="transcripts",
                    marks=[Moving(key=key, up_to="9")],
                ),
                MarksMoved,
            )
    assert [each.up_to for each in read] == ["7"]
    assert roomed == read


def test_an_agents_group_is_seen_up_to_the_operators_own_words_to_them_a_mark_further_on_the_later(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        mcp = machine.host.launch("one").mcp
        call(mcp, "note", {"remark": "First."})
        host = client(machine.host, clock)
        assert host.ask(ListInbox(), Items).seen == []
        clock.sleep(60)
        words = host.ask(SendItem(launch="one", text="Carry on."), Shown).item
        call(mcp, "note", {"remark": "Second."})
        after = host.ask(ListInbox(), Items)
        first, second = after.items
        assert isinstance(first.sender, Conversation)
        assert after.seen == [
            Seen(conversation=first.sender, item=words.number, at=words.made)
        ]
        assert first.number < words.number < second.number
        # A mark past their words is the later word, and one behind them changes nothing.
        clock.sleep(60)
        host.ask(
            MoveMarks(
                repository=first.sender.repository,
                module=CORE,
                marks=[Moving(key=seen(first.sender), up_to=str(first.number))],
            ),
            MarksMoved,
        )
        assert [each.item for each in host.ask(ListInbox(), Items).seen] == [
            words.number
        ]
        host.ask(
            MoveMarks(
                repository=first.sender.repository,
                module=CORE,
                marks=[Moving(key=seen(first.sender), up_to=str(second.number))],
            ),
            MarksMoved,
        )
        assert [each.item for each in host.ask(ListInbox(), Items).seen] == [
            second.number
        ]


def test_the_operators_list_says_how_far_they_have_seen_each_group_by_its_review_mark(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        mcp = machine.host.launch("one").mcp
        call(mcp, "note", {"remark": "First."})
        host = client(machine.host, clock)
        before = host.ask(ListInbox(), Items)
        [first] = before.items
        assert isinstance(first.sender, Conversation)
        clock.sleep(300)
        host.ask(
            MoveMarks(
                repository=first.sender.repository,
                module=CORE,
                marks=[Moving(key=seen(first.sender), up_to=str(first.number))],
            ),
            MarksMoved,
        )
        call(mcp, "note", {"remark": "Second."})
        second = newest(delivery)
        after = host.ask(ListInbox(), Items)
    assert before.seen == []
    assert [item.number for item in after.items] == [first.number, second]
    assert after.seen == [
        Seen(conversation=first.sender, item=first.number, at=clock.now())
    ]


def test_what_the_operator_writes_on_a_conversation_is_kept_on_the_host_for_it_alone(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    session = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    subagent = session.model_copy(update={"agent": "a1"})
    talk = Talk(
        comments=[
            TalkComment(
                step=3, quote=Quote(text="Twenty", start=0, end=6), text="Why?"
            ),
            TalkComment(step=None, text="Then the second runtime."),
        ],
        sent=[Sent(number=7, text="Go on.", after=12, at=clock.now())],
    )
    with inboxed(machine, clock, notices, said):
        host = client(machine.host, clock)
        unwritten = host.ask(ShowTalk(conversation=session), Talked)
        kept = host.ask(KeepTalk(conversation=session, talk=talk), Talked)
        again = host.ask(ShowTalk(conversation=session), Talked)
        theirs = host.ask(ShowTalk(conversation=subagent), Talked)
    with inboxed(machine, clock, notices, said):
        restarted = client(machine.host, clock).ask(
            ShowTalk(conversation=session), Talked
        )
    assert unwritten.talk == Talk()
    assert kept.talk == again.talk == restarted.talk == talk
    assert theirs.talk == Talk()


def test_a_conversations_items_are_listed_in_every_state_as_it_wrote_and_was_told_them(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    session = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    subagent = session.model_copy(update={"agent": "a1"})
    decisions: list[JsonValue] = [{"decision": "Parse with lark", "lean": "it's typed"}]

    def stamped(started: str) -> dict[str, JsonValue]:
        found = json.loads(send(machine.host.launch("one").hook, started))
        return found["hookSpecificOutput"]["updatedInput"]

    def following(
        lines: Callable[[], bytes], until: Callable[[Exchanged], bool]
    ) -> Exchanged:
        while True:
            found = Exchanged.model_validate_json(lines())
            if until(found):
                return found

    with (
        inboxed(machine, clock, notices, said) as delivery,
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as watch,
    ):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        mcp = machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        asking: dict[str, JsonValue] = {
            "question": "Which parser?",
            "decisions": decisions,
        }
        call(mcp, "ask", stamped(lup_call("ask", asking, "q1")))
        question = newest(delivery)
        noting = lup_call(
            "note",
            {"remark": "I assumed UTF-8."},
            "n1",
            agent_id="a1",
            agent_type="general-purpose",
        )
        call(mcp, "note", stamped(noting))
        noted = newest(delivery)
        watch.settimeout(60)
        watch.connect(str(machine.host.watch))
        watch.sendall(f"{ListItems(conversation=session).model_dump_json()}\n".encode())
        with watch.makefile("rb") as replies:
            asked = Exchanged.model_validate_json(replies.readline())
            inbox("answer", str(question), "--leaning", "1", "--comment", "Go.")
            answer = newest(delivery)
            answered = following(
                replies.readline,
                lambda found: isinstance(found.sent[0].item.state, Answered),
            )
        send(hook, claude("SubagentStop", agent_id="a1", agent_type="general-purpose"))
        ended = newest(delivery)
        inbox("answer", str(noted), "--comment", "UTF-8 it is.")
        reply = newest(delivery)
        send(hook, bash("b1"))
        host = client(machine.host, clock)
        mains = host.ask(ListItems(conversation=session), Exchanged)
        theirs = host.ask(ListItems(conversation=subagent), Exchanged)
    assert [each.text for each in asked.sent] == [
        "Which parser?\n1. Parse with lark\n   lean: it's typed"
    ]
    assert asked.sent[0].item.call == "q1"
    assert asked.received == []
    assert answered.sent[0].item.state == Answered(at=clock.now(), answer=answer)
    # A decision's number is its place in the question, not an item's.
    assert [each.text for each in answered.received] == [
        (
            "<asked>Which parser?</asked>\n"
            '<decision number="1" lean="it\'s typed" verdict="leaning: they go with '
            f'the lean" id="{answer}.1">Parse with lark</decision>\n'
            f'<comment id="{answer}.2">Go.</comment>'
        )
    ]
    # The subagent's end reaches the session; the reply to their note, passed on
    # to the session once they ended, is in both: told to the session, and for
    # the subagent.
    assert [each.item.number for each in mains.sent] == [question]
    assert [each.item.number for each in mains.received] == [answer, ended, reply]
    assert [each.item.state for each in mains.received] == [
        Told(at=clock.now(), how="call")
    ] * 3
    assert mains.received[2].item.addressed == subagent
    assert mains.received[2].text == (
        f'<on item="{noted}" kind="note">\n'
        "<opening>I assumed UTF-8.</opening>\n"
        f'<comment id="{reply}.1">UTF-8 it is.</comment>\n'
        "</on>"
    )
    assert [(each.item.number, each.text) for each in theirs.sent] == [
        (noted, "I assumed UTF-8."),
        (ended, "They were stopped before they ended their turn."),
    ]
    assert theirs.sent[0].item.state == Done(at=clock.now())
    passed = [(each.item, each.text) for each in mains.received[2:]]
    assert [(each.item, each.text) for each in theirs.received] == passed
    # Each says it as its own view does: whose it was, or where it went on to.
    said = [
        "".join(span.text for span in each.line)
        for each in [mains.received[2], theirs.received[0]]
    ]
    assert said[0].endswith(", which had ended")
    assert ", this one having ended" in said[1]


def test_a_sent_draft_approves_what_it_marks_read_and_held_changes_commented_on(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    pusher = Conversation(
        repository=tmp_path / "p" / ".git", runtime="claude", session="s1"
    )
    worktree = tmp_path / "w"
    worktree.mkdir()
    holds = Holds(layout=machine.store(worktree))
    hold = holds.put(
        Hold(
            key=holds.unused(),
            worktree=worktree,
            session="s1",
            created=clock.now(),
            files=[
                HeldFile(
                    path=Path("AGENTS.md"),
                    role="operator",
                    blob="abc",
                    reasons=["operator"],
                    asks=["AGENTS.md is one of the operator's documents"],
                )
            ],
            diff="+a line\n",
        )
    )
    with inboxed(machine, clock, notices, said) as delivery:
        delivery.settle_hold = lambda change, approved, comment: cli.hold_answered(
            machine, change, approved=approved, comment=comment
        )
        host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
        read = host.ask(asking_approval(tmp_path / "r", "zone"), Shown).item
        pushed = host.ask(asking_approval(tmp_path / "p", "zone", pusher), Shown).item
        nobody = host.ask(asking_approval(tmp_path / "n", "zone"), Shown).item
        InboxAnnouncing(layout=machine.host, clock=clock).announced(
            hold, "claude", worktree / ".git", []
        )
        [held] = [
            each
            for each in delivery.inbox.waiting(Operator())
            if isinstance(each.reason, HeldChange)
        ]
        drafting(
            machine,
            clock,
            Draft(
                comments=[
                    Comment(item=pushed.number, text="Split the reader out first."),
                    Comment(item=nobody.number, text="Why this zone?"),
                    Comment(item=held.number, text="Yes, but keep it short."),
                ],
                done=[read.number],
            ),
        )
        sent = host.ask(SendDraft(), Reviewed)
        standing = {
            each: delivery.inbox.item(each).state
            for each in [read.number, pushed.number, nobody.number, held.number]
        }
        answered_hold = holds.get(hold.key)
        left = delivery.inbox.draft()
    assert sent.items == []
    assert sorted(each.number for each in sent.approved) == [read.number, held.number]
    read_state = standing[read.number]
    held_state = standing[held.number]
    assert isinstance(read_state, Decided)
    assert read_state.approved
    assert isinstance(held_state, Decided)
    assert held_state.comment == "Yes, but keep it short."
    assert answered_hold is not None
    assert answered_hold.answer is not None
    assert answered_hold.answer.approved
    assert isinstance(standing[pushed.number], Waiting)
    assert isinstance(standing[nobody.number], Waiting)
    [note] = sent.noted
    assert note.recipient == pusher
    assert isinstance(note.reason, Message)
    assert note.reason.text == (
        f"The operator commented on @{pushed.number}, the approval your push "
        'asked ("Approve the host zone at abc?"), and hasn\'t answered it:\n'
        "Split the reader out first."
    )
    assert sent.kept == [nobody.number]
    assert [each.item for each in left.comments] == [nobody.number]


def test_a_sent_draft_answers_what_it_marks_done_or_declined_with_the_comments_under_each(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    pusher = Conversation(
        repository=tmp_path / "p" / ".git", runtime="claude", session="s1"
    )
    mark = Marked(
        id="m1",
        action="policy-review-since",
        argument={"files": [{"path": "a.py", "version": "abc"}]},
        verb="done",
        says="mark it reviewed",
        block="since a.py",
        version="abc",
    )
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        stamped = json.loads(send(hook, lup_call("note", {"remark": "FYI."}, "n1")))[
            "hookSpecificOutput"
        ]["updatedInput"]
        call(machine.host.launch("one").mcp, "note", stamped)
        fyi = newest(delivery)
        host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
        yes = host.ask(asking_approval(tmp_path / "y", "zone", pusher), Shown).item
        no = host.ask(asking_approval(tmp_path / "n", "zone", pusher), Shown).item
        drafting(
            machine,
            clock,
            Draft(
                comments=[
                    Comment(item=yes.number, text="Keep it small."),
                    Comment(item=no.number, text="Not this zone."),
                ],
                done=[fyi, yes.number],
                declined=[no.number],
                marks=[mark],
            ),
        )
        sent = host.ask(SendDraft(), Reviewed)
        approved, declined = (
            delivery.inbox.item(each).state for each in [yes.number, no.number]
        )
        left = delivery.inbox.draft()
    # Marked done, an approval commented on is approved with the comment, where
    # unmarked it would stay unanswered; marked declined, declined with it.
    assert sent.read == [fyi]
    assert [each.number for each in sent.approved] == [yes.number]
    assert [each.number for each in sent.declined] == [no.number]
    assert approved == Decided(at=clock.now(), approved=True, comment="Keep it small.")
    assert declined == Decided(at=clock.now(), approved=False, comment="Not this zone.")
    # The marks beyond the inbox's items stay drafted, for the page to apply.
    assert left == Draft(marks=[mark])


def test_a_draft_declining_what_isnt_an_approval_or_a_held_change_is_refused(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        stamped = json.loads(send(hook, lup_call("note", {"remark": "FYI."}, "n1")))[
            "hookSpecificOutput"
        ]["updatedInput"]
        call(machine.host.launch("one").mcp, "note", stamped)
        fyi = newest(delivery)
        drafting(machine, clock, Draft(declined=[fyi]))
        with pytest.raises(HostError) as refusal:
            sending(machine, clock)
        state = delivery.inbox.item(fyi).state
    assert "only an approval or a held change is declined" in str(refusal.value)
    assert isinstance(state, Waiting | Told)


# Landing a branch: `land`, waiting on what was flagged on it.

NOTHING_GOING = (
    "Nothing else is running or waiting to land: no subagent of yours lup hasn't "
    "heard end, and no local branch off `dev`."
)
"""What a landing ends on where nothing else waits."""


class Landings:
    """lup's layout of a repository for landing: its git directory bare, its worktrees under `tree/`, `dev` checked out in one and `feat` in another; its remote `origin` a bare forge on disk holding `main` and `dev`; and a launch of `runtime` served, started in `dev`'s worktree, whose room is the test's own machine, each command it runs there recorded."""

    def __init__(
        self,
        bare: Path,
        tmp_path: Path,
        shell: Shell,
        machine: Layout,
        clock: FakeClock,
        *,
        parser: FakeParser,
    ) -> None:
        self.repository = bare
        self.shell = shell
        self.parser = parser
        """What reads a file's parse on the host, for a landing's `# lup: defer` comments."""
        self.machine = machine
        self.clock = clock
        self.forge = tmp_path / "forge.git"
        shell.git(tmp_path, "init", "-q", "--bare", str(self.forge))
        shell.git(bare, "remote", "set-url", "origin", str(self.forge))
        shell.git(bare, "branch", "dev", "main")
        shell.git(bare, "push", "-q", "origin", "main", "dev")
        self.dev = bare / "tree" / "dev"
        shell.git(bare, "worktree", "add", "-q", str(self.dev), "dev")
        self.feat = self.branched("feat")
        self.ran: list[list[str]] = []
        """Each command run in the launch's room, as the host asked it."""
        self.containers: list[str] | None = None
        """The containers podman has, as the host's `podman container exists` is answered; none has every one."""
        self.gate = MergeGate()
        """The gate the room's `lup-dev merge` runs on a merge."""
        self.unmerging: str | None = None
        """What the room's `lup-dev merge` says failing, where it fails, as one without the command does."""
        self.mounted: list[Path] = [Path("/")]
        """Where the room has something mounted, as its `findmnt` lists it: a test lays a mount over a path in a worktree here."""
        self.unlisting: str | None = None
        """What the room's `findmnt` says failing, where it fails."""

    def branched(self, name: str, start: str = "dev") -> Path:
        """Add a worktree on a new branch `name` from `start`, `dev` by default, and return its root."""
        root = self.repository / "tree" / name
        self.shell.git(
            self.repository, "worktree", "add", "-q", "-b", name, str(root), start
        )
        return root

    async def room(self, program: Program) -> Ran:
        """Run what the host asks of the launch's room, `podman exec` into it, on this machine instead, where the room's paths are the host's; and say whether its container is there."""
        self.ran.append(program.command)
        match program.command:
            case ["podman", "container", "exists", name]:
                there = self.containers is None or name in self.containers
                return Ran(command=program.command, status=0 if there else 1)
            case ["podman", "exec", "--workdir", _, _, "findmnt", *_]:
                if self.unlisting is not None:
                    failing = self.unlisting.encode()
                    return Ran(command=program.command, status=1, error=failing)
                listed = {"filesystems": [{"target": str(at)} for at in self.mounted]}
                printed = json.dumps(listed).encode()
                return Ran(command=program.command, status=0, output=printed)
            case ["podman", "exec", "--workdir", workdir, _, *command]:
                return await executed(
                    Program(command=command, payload="", directory=Path(workdir))
                )
            case [
                "podman",
                "exec",
                "--interactive",
                "--workdir",
                workdir,
                _,
                "uv",
                "run",
                "lup-dev",
                "merge",
                base,
                tip,
            ]:
                return await asyncio.to_thread(
                    self.merging, Path(workdir), base, tip, program.payload
                )
            case [
                "podman",
                "exec",
                "--interactive",
                "--workdir",
                workdir,
                _,
                "uv",
                "run",
                "lup-dev",
                "gate-commit",
                commit,
            ]:
                return await asyncio.to_thread(self.gating, Path(workdir), commit)
            case _:
                message = f"the room was asked {program.command}"
                raise AssertionError(message)

    def gating(self, root: Path, commit: str) -> Ran:
        """Run `lup-dev gate-commit` as the room does, in this process, from the worktree at `root`, its gate the test's (`gate`)."""
        gating = gated_commit(
            root,
            commit,
            processes=self.gate,
            passes=Passes.of(root, self.clock),
            runner=Uv(),
            say=self.gate.said.append,
            stop=self.gate.stopped.append,
        )
        printed = TypeAdapter[Merging](Merging).dump_json(gating)
        return Ran(command=["lup-dev", "gate-commit"], status=0, output=printed)

    def merging(self, root: Path, base: str, tip: str, message: str) -> Ran:
        """Run `lup-dev merge` as the room does, in this process, from the worktree at `root`, its gate the test's (`gate`); or fail as told (`unmerging`)."""
        if self.unmerging is not None:
            failing = self.unmerging.encode()
            return Ran(command=["lup-dev", "merge"], status=2, error=failing)
        merging = merged(
            root,
            base,
            tip,
            message,
            processes=self.gate,
            passes=Passes.of(root, self.clock),
            runner=Uv(),
            say=self.gate.said.append,
            stop=self.gate.stopped.append,
        )
        printed = TypeAdapter[Merging](Merging).dump_json(merging)
        return Ran(command=["lup-dev", "merge"], status=0, output=printed)

    def wrote(self, root: Path, path: str, content: str) -> None:
        """Write `path` in the worktree at `root`, and commit it."""
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
        self.shell.commit(root, f"write {path}")

    def merged(self, branch: str = "feat") -> str:
        """Merge `branch` into `dev` in its worktree with a merge commit, as a session lands work, record the gate's pass on the result, as `lup-dev check` would, and return its tip."""
        self.shell.git(self.dev, "merge", "-q", "--no-ff", "--no-edit", branch)
        tip = self.shell.git(self.dev, "rev-parse", "HEAD")
        self.passing(tip)
        return tip

    def passing(self, tip: str) -> None:
        """Record the gate's pass on `tip`'s files."""
        tree = self.shell.git(self.dev, "rev-parse", f"{tip}^{{tree}}")
        passes = GitDirectoryLayout(common=self.repository).passes
        write_model(
            passes / f"{tree}.json",
            Passed(files=Standing(tree=tree), at=self.clock.now()),
        )

    def on_forge(self, ref: str) -> str | None:
        """Return the commit the forge's `ref` names, or none where it has none."""
        found = self.shell.git(
            self.forge, "for-each-ref", "--format=%(objectname)", ref
        )
        return found or None

    def launched(
        self,
        runtime: str,
        name: str = "one",
        worktree: Path | None = None,
        *,
        runner: bool = True,
        gated: list[str] | None = None,
    ) -> Register:
        """Register a launch of `runtime` in the repository with the running service, started in `worktree`, `dev`'s by default, landing on `dev`."""
        judge = self.repository.parent / "judges" / "bin" / "lup-dev"
        judge.parent.mkdir(parents=True, exist_ok=True)
        judge.touch()
        registered = Register(
            launch=name,
            runtime=runtime,
            worktree=worktree or self.dev,
            repository=self.repository,
            judge=judge,
            container=f"lup-{name}",
            limits=Limits(
                actions=["fetch", "push", "delete-merged"],
                protected=["refs/heads/main"],
                gated=gated or ["refs/heads/dev"],
            ),
            github=None,
            name=name,
            runner=["uv", "run"] if runner else None,
        )
        client(self.machine.host, self.clock).register(registered)
        return registered

    def flag(
        self, path: str, content: str, sender: Conversation, branch: str = "feat"
    ) -> int:
        """Put a write making `path` hold `content` that landed flagged on `branch` in the operator's inbox, as the judge does, from `sender`; return its number."""
        reading = Reading(
            role="production", asks=[Ask(name="new-file", taken="flagged")]
        )
        asking = AskFlag(
            flagged=Flagged(
                text=f"{path} landed, flagged for the operator's review.",
                summary=f"{path} is a new production file",
                worktree=self.feat,
                path=Path(path),
                branch=branch,
            ),
            sender=sender,
            diff="",
            file=ChangedFile.of(Path(path), None, content.encode(), reading),
        )
        return client(self.machine.host, self.clock).ask(asking, Shown).item.number


class MergeGate(Processes):
    """The gate a merge runs in the room, going as the test says: its exit code, and the files its fixes rewrite, from the worktree's root."""

    def __init__(self) -> None:
        self.code = 0
        self.fixes: dict[str, str] = {}
        self.ran: list[list[str]] = []
        self.said: list[str] = []
        self.stopped: list[Path] = []

    @override
    def run(self, command: list[str], cwd: Path) -> GateRan:
        self.ran.append(command)
        for path, content in self.fixes.items():
            (cwd / path).write_text(content)
        return GateRan(
            code=self.code, output=f"the gate's report, ending {self.code}\n"
        )


@pytest.fixture
def landings(
    bare: Path,
    tmp_path: Path,
    shell: Shell,
    machine: Layout,
    clock: FakeClock,
    *,
    parser: FakeParser,
) -> Landings:
    return Landings(bare, tmp_path, shell, machine, clock, parser=parser)


def started(runtime: str) -> str:
    """A session's start, in `runtime`'s hook's terms: Claude Code's session `s1`, Codex's `t1`."""
    if runtime == "codex":
        return codex("SessionStart", source="startup")
    return claude("SessionStart", source="startup")


def listing(workdir: Path, container: str) -> list[str]:
    """How a landing's cleanup asks the launch's room what it mounts, before it removes a worktree there."""
    return [
        *["podman", "exec", "--workdir", str(workdir), container],
        *["findmnt", "--json", "--list", "--output", "TARGET"],
    ]


def lander(landings: Landings, runtime: str) -> Conversation:
    """The main conversation of the session `started` starts, in the landings' repository."""
    session = "t1" if runtime == "codex" else "s1"
    return Conversation(
        repository=landings.repository, runtime=runtime, session=session
    )


def test_land_puts_the_branch_on_dev_and_cleans_up_what_it_landed_but_what_s_in_use(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    feat, repository = landings.feat, landings.repository
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    (feat / ".venv").mkdir()
    (feat / ".venv" / "python").write_text("an environment git ignores")
    landings.shell.git(repository, "push", "-q", "origin", "feat")
    kept = landings.branched("kept")
    landings.wrote(kept, "src/pkg/kept.py", '"""Kept."""\n')
    (kept / "draft.txt").write_text("work not committed")
    busy = landings.branched("busy")
    landings.wrote(busy, "src/pkg/busy.py", '"""Busy."""\n')
    old = landings.on_forge("refs/heads/dev")
    landings.shell.git(
        landings.dev, "merge", "-q", "--no-ff", "--no-edit", "kept", "busy"
    )
    tip = landings.merged()
    tracking = ["for-each-ref", "--format=%(objectname)", "refs/remotes/origin/dev"]
    before = landings.shell.git(repository, *tracking)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        landings.launched("claude", name="two", worktree=busy)
        send(machine.host.launch("one").hook, started("claude"))
        answer, error = call(machine.host.launch("one").mcp, "land", {})
    assert not error
    # The push names the forge's URL, so `land` moves `origin/dev` here itself.
    assert before == ""
    assert landings.shell.git(repository, *tracking) == tip
    assert answer == (
        f"Landed {tip} on `dev` at `origin`, which was at {old}.\n"
        "`busy`, `feat` and `kept` add no `# lup: defer` comment and remove none, against `dev`.\n"
        "Cleaned up after it:\n"
        "- deleted `feat` on `origin`\n"
        f"- removed the worktree {feat}\n"
        "- deleted the local branch `feat`\n"
        "Left:\n"
        f"- the worktree {busy}: launch `two` started there\n"
        f"- the local branch `busy`, checked out in {busy}\n"
        f"- the worktree {kept}: `git worktree remove`: fatal: '{kept}' contains "
        "modified or untracked files, use --force to delete it\n"
        f"- the local branch `kept`, checked out in {kept}\n{NOTHING_GOING}"
    )
    assert landings.on_forge("refs/heads/dev") == tip
    assert landings.on_forge("refs/heads/feat") is None
    assert not feat.exists()
    assert (kept / "draft.txt").is_file()
    assert landings.shell.git(repository, "branch", "--list", "feat") == ""
    assert landings.ran == [
        ["podman", "container", "exists", "lup-one"],
        listing(landings.dev, "lup-one"),
        *(
            [
                "podman",
                "exec",
                "--workdir",
                str(landings.dev),
                "lup-one",
                "git",
                "worktree",
                "remove",
                str(each),
            ]
            for each in [feat, kept]
        ),
    ]


def test_land_removes_worktrees_in_the_container_the_launch_has_when_it_cleans_up(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    rooms, path = '"""Rooms."""\n', "src/pkg/rooms.py"
    feat = landings.feat
    landings.wrote(feat, path, rooms)
    tip = landings.merged()
    session = lander(landings, "claude")
    renamed = container_name(landings.repository, "review-and-plan")
    with (
        inboxed(
            machine,
            clock,
            notices,
            said,
            rooms=landings.room,
            parser=landings.parser,
            podman=podman_of("lup-one"),
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        landings.launched("claude")
        mcp = machine.host.launch("one").mcp
        send(machine.host.launch("one").hook, started("claude"))
        flag = landings.flag(path, rooms, session)
        landing = pool.submit(call, mcp, "land", {})
        assert delivery.holding.wait(timeout=60)
        # While the landing waits on the operator, the session renames themselves,
        # and lup renames the launch's container with them.
        assert call(mcp, "rename", {"name": "review-and-plan"}) == (
            "You're `review-and-plan` now.",
            False,
        )
        inbox("done", str(flag))
        answer, error = landing.result(timeout=60)
    assert not error
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")
    assert f"- removed the worktree {feat}\n" in answer
    assert not feat.exists()
    assert f"one: its container lup-one is {renamed}" in said
    assert landings.ran == [
        ["podman", "container", "exists", renamed],
        listing(landings.dev, renamed),
        [
            "podman",
            "exec",
            "--workdir",
            str(landings.dev),
            renamed,
            "git",
            "worktree",
            "remove",
            str(feat),
        ],
    ]


def test_land_leaves_whole_a_worktree_the_room_hides_something_in_saying_so(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    feat = landings.feat
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    (feat / ".venv").mkdir()
    (feat / ".venv" / "python").write_text("the host's environment")
    # The room lays an empty directory over the worktree's `.venv`, inside the
    # tree's own mount: `git worktree remove` there fails partway.
    landings.mounted = [Path("/"), landings.repository, feat / ".venv"]
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged()
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer, error = call(machine.host.launch("one").mcp, "land", {})
    assert not error
    assert answer == (
        f"Landed {tip} on `dev` at `origin`, which was at {old}.\n"
        "`feat` adds no `# lup: defer` comment and removes none, against `dev`.\n"
        "Left:\n"
        f"- the worktree {feat}: its `.venv` is hidden from the room, so it's "
        "removed on the host\n"
        f"- the local branch `feat`, checked out in {feat}\n{NOTHING_GOING}"
    )
    assert (feat / "src/pkg/rooms.py").is_file()
    assert (feat / ".venv" / "python").is_file()
    assert str(feat) in landings.shell.git(landings.repository, "worktree", "list")
    assert landings.ran == [
        ["podman", "container", "exists", "lup-one"],
        listing(landings.dev, "lup-one"),
    ]


def test_land_removes_no_worktree_where_the_room_cant_say_what_it_mounts(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    feat = landings.feat
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    landings.unlisting = "findmnt: command not found"
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged()
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer, error = call(machine.host.launch("one").mcp, "land", {})
    assert not error
    assert answer == (
        f"Landed {tip} on `dev` at `origin`, which was at {old}.\n"
        "`feat` adds no `# lup: defer` comment and removes none, against `dev`.\n"
        "Left:\n"
        "- lup couldn't list what your room mounts (`findmnt`: findmnt: command "
        "not found), so no worktree was removed\n"
        f"- the worktree {feat}\n"
        f"- the local branch `feat`, checked out in {feat}\n{NOTHING_GOING}"
    )
    assert feat.is_dir()
    assert landings.ran == [
        ["podman", "container", "exists", "lup-one"],
        listing(landings.dev, "lup-one"),
    ]


def test_land_says_once_where_no_container_is_there_and_names_each_worktree_left(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    feat, repository = landings.feat, landings.repository
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    landings.shell.git(repository, "push", "-q", "origin", "feat")
    kept = landings.branched("kept")
    landings.wrote(kept, "src/pkg/kept.py", '"""Kept."""\n')
    landings.shell.git(landings.dev, "merge", "-q", "--no-ff", "--no-edit", "kept")
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged()
    landings.containers = []
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer, error = call(machine.host.launch("one").mcp, "land", {})
    assert not error
    assert answer == (
        f"Landed {tip} on `dev` at `origin`, which was at {old}.\n"
        "`feat` and `kept` add no `# lup: defer` comment and remove none, against `dev`.\n"
        "Cleaned up after it:\n"
        "- deleted `feat` on `origin`\n"
        "Left:\n"
        "- no container named `lup-one`, your room's as lup has it, is there, so no "
        "worktree was removed\n"
        f"- the worktree {feat}\n"
        f"- the local branch `feat`, checked out in {feat}\n"
        f"- the worktree {kept}\n"
        f"- the local branch `kept`, checked out in {kept}\n{NOTHING_GOING}"
    )
    assert landings.ran == [["podman", "container", "exists", "lup-one"]]
    assert feat.is_dir()
    assert kept.is_dir()
    assert landings.on_forge("refs/heads/feat") is None
    assert landings.on_forge("refs/heads/dev") == tip


def test_land_leaves_alone_a_branch_with_nothing_of_its_own_and_a_flag_on_it_holds_nothing(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    rooms = '"""Rooms."""\n'
    feat, dev, shell = landings.feat, landings.dev, landings.shell
    landings.wrote(feat, "src/pkg/rooms.py", rooms)
    shell.git(dev, "merge", "-q", "--no-ff", "--no-edit", "feat")
    # Made from `dev` once `feat` was merged, as a worker's worktree is, with no
    # commit of their own: `mid`'s tip is a commit of `dev`'s own line, and
    # `fresh`'s the tip landed itself.
    mid = landings.branched("mid")
    later = landings.branched("later")
    landings.wrote(later, "src/pkg/later.py", '"""Later."""\n')
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged("later")
    fresh = landings.branched("fresh")
    session = lander(landings, "claude")
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ) as delivery:
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        flags = [
            landings.flag("src/pkg/rooms.py", rooms, session, branch="mid"),
            landings.flag("src/pkg/rooms.py", rooms, session, branch="fresh"),
        ]
        answer, error = call(machine.host.launch("one").mcp, "land", {})
        holds = [
            item
            for item in delivery.inbox.items.values()
            if isinstance(item.reason, HeldChange)
        ]
        states = [delivery.inbox.item(each).state for each in flags]
    assert not error
    assert answer == (
        f"Landed {tip} on `dev` at `origin`, which was at {old}.\n"
        "`feat` and `later` add no `# lup: defer` comment and remove none, against `dev`.\n"
        "Cleaned up after it:\n"
        f"- removed the worktree {feat}\n"
        "- deleted the local branch `feat`\n"
        f"- removed the worktree {later}\n"
        "- deleted the local branch `later`\n"
        "Left alone, `dev` having merged none of them: `fresh`, `mid`.\n"
        f"{NOTHING_GOING}"
    )
    assert holds == []
    assert states == [Waiting(), Waiting()]
    assert landings.on_forge("refs/heads/dev") == tip
    assert mid.is_dir()
    assert fresh.is_dir()
    assert shell.git(dev, "rev-parse", "fresh") == tip
    assert shell.git(dev, "rev-parse", "mid") == shell.git(dev, "rev-parse", f"{tip}^")
    assert not feat.exists()
    assert not later.exists()


def test_land_refuses_a_branch_without_a_pass_of_the_gate_one_behind_the_remote_and_a_branch_not_gated(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    shell, dev = landings.shell, landings.dev
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    shell.git(dev, "merge", "-q", "--no-edit", "feat")
    tip = shell.git(dev, "rev-parse", "HEAD")
    tree = shell.git(dev, "rev-parse", "HEAD^{tree}")
    old = landings.on_forge("refs/heads/dev")
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        unpassed, _ = call(machine.host.launch("one").mcp, "land", {})
        landings.passing(tip)
        main = landings.repository / "tree" / "main"
        landings.wrote(main, "elsewhere.txt", "landed meanwhile\n")
        moved = shell.git(main, "rev-parse", "HEAD")
        shell.git(landings.repository, "push", "-q", "origin", "main:dev")
        behind, _ = call(machine.host.launch("one").mcp, "land", {})
        ungated, _ = call(
            machine.host.launch("one").mcp, "land", {"branch": "feat", "onto": "feat"}
        )
    assert unpassed == (
        f"Not landed: the gate has no pass on {tip}'s files (tree `{tree}`). Run "
        "`uv run lup-dev check` where `dev` is checked out, with everything "
        "committed, so it passes on exactly what lands; then call `land` again."
    )
    assert behind == (
        f"Not landed: `dev` on `origin` is at {moved}, which `dev` doesn't hold: "
        "merge it into `dev`, run the gate on the result, and land again."
    )
    assert ungated == (
        "Not landed: `feat` isn't a branch the project's declaration gates "
        "(`Core.credentials`), where branches land: push any other with git"
    )
    assert old != moved
    assert landings.on_forge("refs/heads/dev") == moved
    assert landings.ran == []


def drawer(
    machine: Layout, clock: FakeClock, party: Conversation, branch: str
) -> SincePlace:
    """Read `party`'s "since you approved" as the dashboard does, and return its place on `branch`."""
    since = client(machine.host, clock).ask(ShowSince(conversation=party), Since)
    [place] = [each for each in since.places if each.branch == branch]
    return place


def answering(
    machine: Layout,
    clock: FakeClock,
    party: Conversation,
    place: SincePlace,
    path: str,
    *,
    decline: bool = False,
) -> SinceReviewed:
    """Mark the file at `path` of `party`'s drawer's `place` reviewed at the version shown, as Space `d` does, or decline its landing, as Space `x` does."""
    [shown] = [each for each in place.files if each.path == Path(path)]
    asked = ReviewSince(
        conversation=party,
        worktree=place.worktree,
        branch=place.branch,
        files=[ViewedFile(path=shown.path, version=shown.version)],
        decline=decline,
    )
    return client(machine.host, clock).ask(asked, SinceReviewed)


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_a_landing_waits_on_each_file_flagged_on_what_it_lands_held_in_its_writers_drawer_and_lands_once_marked_reviewed(
    runtime: str,
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    *,
    said: list[str],
) -> None:
    rooms, hall = '"""Rooms."""\n', '"""Hall."""\n'
    landings.wrote(landings.feat, "src/pkg/rooms.py", rooms)
    landings.wrote(landings.feat, "src/pkg/hall.py", hall)
    landings.shell.git(landings.repository, "branch", "other", "main")
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged()
    session = lander(landings, runtime)
    worker = session.model_copy(update={"agent": "a1"})
    with (
        inboxed(
            machine, clock, notices, said, rooms=landings.room, parser=landings.parser
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        landings.launched(runtime)
        send(machine.host.launch("one").hook, started(runtime))
        flags = [
            landings.flag("src/pkg/rooms.py", rooms, session),
            landings.flag("src/pkg/rooms.py", rooms, worker),
            # On a branch the landing doesn't land, a file it doesn't change, a
            # flag approved: none holds, and the one on a file it doesn't change
            # is withdrawn once `feat` is gone.
            landings.flag("src/pkg/rooms.py", rooms, worker, branch="other"),
            landings.flag("src/pkg/gone.py", rooms, worker),
            landings.flag("src/pkg/hall.py", hall, worker),
        ]
        inbox("done", str(flags[4]))
        landing = pool.submit(call, machine.host.launch("one").mcp, "land", {})
        assert delivery.holding.wait(timeout=60)
        [wait] = (
            client(machine.host, clock).ask(ShowLandings(), LandingsWaiting).waiting
        )
        listed = inbox()
        place = drawer(machine, clock, session, "feat")
        items = [
            each
            for each in delivery.inbox.items.values()
            if isinstance(each.reason, HeldChange)
        ]
        answered = answering(machine, clock, session, place, "src/pkg/rooms.py")
        answer, error = landing.result(timeout=60)
        states = [delivery.inbox.item(each).state for each in flags]
        after = client(machine.host, clock).ask(ShowLandings(), LandingsWaiting).waiting
    assert not error
    assert items == []
    assert (wait.lander, wait.onto, wait.old, wait.tip, wait.branches) == (
        session,
        "refs/heads/dev",
        old,
        tip,
        ["feat"],
    )
    assert [(each.path, each.flags, each.writers) for each in wait.files] == [
        (Path("src/pkg/rooms.py"), flags[:2], [session, worker])
    ]
    [file] = [each for each in place.files if each.path == Path("src/pkg/rooms.py")]
    version = landings.shell.git(landings.dev, "rev-parse", f"{tip}:src/pkg/rooms.py")
    assert file.held is not None
    assert (file.held.key, file.held.tip, file.held.named) == (
        wait.key,
        tip,
        "`feat` on `dev`",
    )
    assert file.version == version
    assert file.file is not None
    assert (file.file.before, file.file.after) == (None, Text(text=rooms))
    assert file.file.reading == Reading(
        role="production", asks=[Ask(name="new-file", taken="flagged")]
    )
    assert file.flags == flags[:2]
    assert answered.approved == flags[:2]
    assert (
        listed.count(
            '; the landing of `feat` on `dev` waits on them, in "since you approved"\n'
        )
        == 2
    )
    [notice] = [each for each in notices.raised if "landing" in each]
    assert notice == (
        "lup: `one`'s landing of `feat` on `dev` waits on 1 file\nsrc/pkg/rooms.py\n"
        'Answer each in "since you approved" of `one`, `one/a1`.'
    )
    assert answer.startswith(
        f"Landed {tip} on `dev` at `origin`, which was at {old}.\n"
        "The operator approved `src/pkg/rooms.py`.\n"
        "`feat` adds no `# lup: defer` comment and removes none, against `dev`.\n"
        "Cleaned up after it:\n"
    )
    assert (
        "Withdrew from the operator's inbox the flagged writes left nothing to hold, "
        "on branches gone or on files it leaves as `dev` had them: "
        f"@{flags[3]} (`src/pkg/gone.py` on `feat`).\n"
    ) in answer
    assert landings.on_forge("refs/heads/dev") == tip
    reviewed = Decided(
        at=clock.now(), approved=True, reviewed=ReviewedAt(version=version)
    )
    approved = Decided(at=clock.now(), approved=True)
    withdrawn = Withdrawn(
        at=clock.now(), why=f"`feat` landed on `dev` at {tip}, and is gone since"
    )
    assert states == [reviewed, reviewed, Waiting(), withdrawn, approved]
    assert after == []


def test_a_landing_waits_on_a_file_flagged_on_what_it_lands_whatever_a_commit_graph_says(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    rooms = '"""Rooms."""\n'
    landings.wrote(landings.feat, "src/pkg/rooms.py", rooms)
    old = landings.on_forge("refs/heads/dev")
    assert old is not None
    tip = landings.merged()
    session = lander(landings, "claude")
    landings.shell.forged_tree(landings.repository, tip, old)
    with serving_landings(landings, machine, clock, notices, said) as (delivery, pool):
        landings.flag("src/pkg/rooms.py", rooms, session)
        landing, wait = held_landing(machine, clock, delivery, pool)
        meanwhile = landings.on_forge("refs/heads/dev")
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, "src/pkg/rooms.py")
        answer, error = landing.result(timeout=60)
    assert not error
    assert meanwhile == old
    assert waited_on(wait) == ["src/pkg/rooms.py"]
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")


def test_land_withdraws_each_flag_left_nothing_to_hold_on_a_branch_gone_or_a_file_it_leaves_unchanged_and_no_later_landing_holds_on_it(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    hall, notes = '"""Hall."""\n', '"""Notes."""\n'
    feat, dev, shell = landings.feat, landings.dev, landings.shell
    # On the remote's `dev` already, as a landing's merge is once it's pushed.
    landings.wrote(dev, "src/pkg/hall.py", hall)
    shell.git(landings.repository, "push", "-q", "origin", "dev")
    old = landings.on_forge("refs/heads/dev")
    # `kept` lands, its worktree left with work not committed, so the branch stays.
    kept = landings.branched("kept")
    landings.wrote(kept, "src/pkg/kept.py", '"""Kept."""\n')
    (kept / "draft.txt").write_text("work not committed")
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    shell.git(dev, "merge", "-q", "--no-ff", "--no-edit", "kept")
    tip = landings.merged()
    session = lander(landings, "claude")
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ) as delivery:
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        flags = [
            # Withdrawn: the file stands at the tip as it flagged it, landed before.
            landings.flag("src/pkg/hall.py", hall, session, branch="dev"),
            # Waiting: written on branches still there, and not at the tip, so
            # perhaps not committed yet.
            landings.flag("src/pkg/draft.py", notes, session, branch="dev"),
            landings.flag("src/pkg/notes.py", notes, session, branch="kept"),
            # Withdrawn: `feat` is gone once it landed, and `quiet` was gone
            # before, holding no landing.
            landings.flag("src/pkg/gone.py", notes, session),
            landings.flag("src/pkg/quiet.py", notes, session, branch="quiet"),
        ]
        answer, error = call(machine.host.launch("one").mcp, "land", {})
        states = [delivery.inbox.item(each).state for each in flags]
        shown = inbox("show", str(flags[0]))
        # A later landing changing the file holds on no flag withdrawn.
        later = landings.branched("later")
        landings.wrote(later, "src/pkg/hall.py", '"""Hall, later."""\n')
        again = landings.merged("later")
        landed_again, _ = call(machine.host.launch("one").mcp, "land", {})
        holds = [
            item
            for item in delivery.inbox.items.values()
            if isinstance(item.reason, HeldChange)
        ]
        after = [delivery.inbox.item(each).state for each in flags]
    assert not error
    assert answer == (
        f"Landed {tip} on `dev` at `origin`, which was at {old}.\n"
        "`feat` and `kept` add no `# lup: defer` comment and remove none, against `dev`.\n"
        "Cleaned up after it:\n"
        f"- removed the worktree {feat}\n"
        "- deleted the local branch `feat`\n"
        "Left:\n"
        f"- the worktree {kept}: `git worktree remove`: fatal: '{kept}' contains "
        "modified or untracked files, use --force to delete it\n"
        f"- the local branch `kept`, checked out in {kept}\n"
        "Withdrew from the operator's inbox the flagged writes left nothing to hold, "
        "on branches gone or on files it leaves as `dev` had them: "
        f"@{flags[0]} (`src/pkg/hall.py` on `dev`), "
        f"@{flags[3]} (`src/pkg/gone.py` on `feat`), "
        f"@{flags[4]} (`src/pkg/quiet.py` on `quiet`).\n{NOTHING_GOING}"
    )
    assert states == [
        Withdrawn(
            at=clock.now(),
            why=f"the file stands on `dev` at {tip} as it flagged it, landed before",
        ),
        Waiting(),
        Waiting(),
        Withdrawn(
            at=clock.now(), why=f"`feat` landed on `dev` at {tip}, and is gone since"
        ),
        Withdrawn(at=clock.now(), why="`quiet` is gone, so it holds no landing"),
    ]
    assert "withdrawn at " in shown
    assert f"by lup: the file stands on `dev` at {tip}" in shown
    assert landed_again.startswith(
        f"Landed {again} on `dev` at `origin`, which was at {tip}.\n"
    )
    assert holds == []
    assert after == states


def test_a_held_file_declined_with_a_comment_lands_nothing_and_its_next_landing_shows_what_changed_since(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    first, second = '"""Rooms."""\n', '"""Chambers."""\n'
    feat, path = landings.feat, "src/pkg/rooms.py"
    landings.wrote(feat, path, first)
    old = landings.on_forge("refs/heads/dev")
    landings.merged()
    session = lander(landings, "claude")
    with (
        inboxed(
            machine, clock, notices, said, rooms=landings.room, parser=landings.parser
        ) as delivery,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        flag = landings.flag(path, first, session)
        landing = pool.submit(call, machine.host.launch("one").mcp, "land", {})
        assert delivery.holding.wait(timeout=60)
        place = drawer(machine, clock, session, "feat")
        [shown] = [each for each in place.files if each.path == Path(path)]
        assert shown.version is not None
        # The comment on its line is sent with the reply, then its decline, which
        # the comment implies on a file held at landing, applied.
        quote = Quote(text=f"{path}:1\n+{first.strip()}", start=0, end=1)
        code = Quoted(
            worktree=feat,
            path=Path(path),
            version=shown.version,
            first=1,
            lines=[first.strip()],
        )
        drafting(
            machine,
            clock,
            Draft(
                remarks=[
                    Remark(
                        to=session, quote=quote, text="Call them chambers.", code=code
                    )
                ]
            ),
        )
        sending(machine, clock)
        declined = answering(machine, clock, session, place, path, decline=True)
        held_back, _ = landing.result(timeout=60)
        # The agent answers it, later, and lands again: the file is shown from the
        # version declined, and the words sent before this landing are no answer to it.
        clock.sleep(60)
        landings.wrote(feat, path, second)
        latest = landings.merged()
        delivery.holding.clear()
        landing = pool.submit(call, machine.host.launch("one").mcp, "land", {})
        assert delivery.holding.wait(timeout=60)
        again = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, again, path, decline=True)
        refused, _ = landing.result(timeout=60)
        flag_state = delivery.inbox.item(flag).state
    assert declined.declined == [Path(path)]
    assert declined.approved == []
    # The session landing wrote the file, so the remark reaches them as well, told after.
    assert held_back.startswith(
        "Not landed: the operator didn't approve each file it waits on.\n"
        f"- `{path}`: declined, saying:\n"
        f"  {path}:1\n"
        f"  +{first.strip()}\n"
        "  Call them chambers.\n"
        "What they approved stays approved. Answer what they said, commit, and call "
        "`land` again: each file left is held again, shown from the version they "
        'last saw.\n<review item="'
    )
    [file] = [each for each in again.files if each.path == Path(path)]
    assert file.held is not None
    assert file.held.tip == latest
    assert file.reviewed is not None
    assert file.file is not None
    assert (file.file.before, file.file.after) == (Text(text=first), Text(text=second))
    assert refused.startswith(
        "Not landed: the operator didn't approve each file it waits on.\n"
        f"- `{path}`: declined\n"
    )
    assert landings.on_forge("refs/heads/dev") == old
    assert flag_state == Waiting()


def test_a_file_held_at_landing_is_shown_from_the_version_the_operator_marked_reviewed(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    first, second = '"""Rooms."""\n', '"""Chambers."""\n'
    feat, path = landings.feat, "src/pkg/rooms.py"
    landings.wrote(feat, path, first)
    version = landings.shell.git(feat, "rev-parse", f"HEAD:{path}")
    mark = Mark(path=Path(path), version=version, at=clock.now())
    reviews = Reviews.of(machine, MarkStore.kept_in(machine), landings.repository)
    reviews.marked("feat", [mark], {version: first.encode()})
    landings.wrote(feat, path, second)
    tip = landings.merged()
    session = lander(landings, "claude")
    with (
        inboxed(
            machine, clock, notices, said, rooms=landings.room, parser=landings.parser
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        landings.flag(path, second, session)
        landing = pool.submit(call, machine.host.launch("one").mcp, "land", {})
        assert delivery.holding.wait(timeout=60)
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, path)
        answer, error = landing.result(timeout=60)
    assert not error
    [file] = [each for each in place.files if each.path == Path(path)]
    assert file.held is not None
    assert (file.since, file.reviewed) == (None, mark.at)
    assert file.file is not None
    assert (file.file.before, file.file.after) == (Text(text=first), Text(text=second))
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")


def test_a_land_sent_again_across_a_restart_waits_again_and_lands_once_its_flag_is_approved_from_the_terminal(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    rooms, path = '"""Rooms."""\n', "src/pkg/rooms.py"
    landings.wrote(landings.feat, path, rooms)
    tip = landings.merged()
    session = lander(landings, "claude")
    with (
        inboxed(
            machine, clock, notices, said, rooms=landings.room, parser=landings.parser
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        landings.launched("claude")
        hook = machine.host.launch("one").hook
        mcp = machine.host.launch("one").mcp
        send(hook, started("claude"))
        flag = landings.flag(path, rooms, session)
        stamped = json.loads(send(hook, lup_call("land", {}, "l1")))[
            "hookSpecificOutput"
        ]["updatedInput"]
        dropped(mcp, "land", stamped, delivery.holding)
        delivery.holding.clear()
        landing = pool.submit(call, mcp, "land", stamped)
        assert delivery.holding.wait(timeout=60)
        waiting = (
            client(machine.host, clock).ask(ShowLandings(), LandingsWaiting).waiting
        )
        inbox("done", str(flag))
        answer, error = landing.result(timeout=60)
        holds = [
            item.number
            for item in delivery.inbox.items.values()
            if isinstance(item.reason, HeldChange)
        ]
    assert not error
    assert [[each.path for each in wait.files] for wait in waiting] == [[Path(path)]]
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")
    assert f"The operator approved `{path}`" in answer
    assert holds == []
    assert landings.on_forge("refs/heads/dev") == tip


WORKFLOW = ".github/workflows/ci.yml"
"""A protected path, which no hook of these tests hears written."""


@contextmanager
def serving_landings(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> Generator[tuple[Watched, ThreadPoolExecutor]]:
    """The service with a launch registered and its session started, hearing nothing else of its hooks: its delivery, and a thread to call `land` on while the operator answers."""
    with (
        inboxed(
            machine, clock, notices, said, rooms=landings.room, parser=landings.parser
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        delivery.settle_hold = lambda _change, _approved, _comment: None
        yield delivery, pool


def held_landing(
    machine: Layout,
    clock: FakeClock,
    delivery: Watched,
    pool: ThreadPoolExecutor,
    arguments: dict[str, JsonValue] | None = None,
) -> tuple[Future[tuple[str, bool]], Wait]:
    """Call `land` in the background, and return once it holds: the call, and what it waits on. Fail, saying what it answered, where it returned instead."""
    delivery.holding.clear()
    landing = pool.submit(call, machine.host.launch("one").mcp, "land", arguments or {})
    while not delivery.holding.wait(timeout=0.01):
        assert not landing.done(), landing.result()
    [wait] = client(machine.host, clock).ask(ShowLandings(), LandingsWaiting).waiting
    return landing, wait


def waited_on(wait: Wait) -> list[str]:
    """Each file `wait` waits on, by its path, sorted."""
    return sorted(str(each.path) for each in wait.files)


def hold_on(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    path: str,
    content: str,
) -> int:
    """Put a hold making `path` hold `content` in the operator's inbox, as the judge does, from the session started: its number."""
    asking = AskHold(
        change=HeldChange(
            text=f"Let the change to {path} land?",
            summary=f"{path}: {path} is a protected path",
            worktree=landings.feat,
        ),
        sender=lander(landings, "claude"),
        diff="",
        files=[ChangedFile.of(Path(path), None, content.encode())],
    )
    return client(machine.host, clock).ask(asking, Shown).item.number


@pytest.mark.parametrize(
    ("path", "role", "ask"),
    [
        (WORKFLOW, "protected", "protected"),
        ("web/.env.local", "protected", "protected"),
        ("AGENTS.md", "operator", "operator"),
    ],
)
def test_a_landing_holds_what_its_own_diff_asks_whatever_the_hooks_heard_and_lands_once_approved(
    path: str,
    role: Role,
    ask: str,
    landings: Landings,
    machine: Layout,
    *,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    content = "a line\n"
    landings.wrote(landings.feat, path, content)
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged()
    session = lander(landings, "claude")
    with serving_landings(landings, machine, clock, notices, said) as (delivery, pool):
        landing, wait = held_landing(machine, clock, delivery, pool)
        meanwhile = landings.on_forge("refs/heads/dev")
        place = drawer(machine, clock, session, "feat")
        answered = answering(machine, clock, session, place, path)
        answer, error = landing.result(timeout=60)
        after = client(machine.host, clock).ask(ShowLandings(), LandingsWaiting).waiting
    assert not error
    assert meanwhile == old
    assert (wait.tip, wait.branches, waited_on(wait)) == (tip, ["feat"], [path])
    assert wait.files[0].writers == [session]
    [file] = [each for each in place.files if each.path == Path(path)]
    assert file.held is not None
    assert file.file is not None
    assert (file.file.before, file.file.after) == (None, Text(text=content))
    assert file.file.reading == Reading(role=role, asks=[Ask(name=ask, taken="held")])
    assert answered.approved == wait.files[0].flags
    [notice] = [each for each in notices.raised if "landing" in each]
    assert notice == (
        f"lup: `one`'s landing of `feat` on `dev` waits on 1 file\n{path}\n"
        'Answer each in "since you approved" of `one`.'
    )
    assert answer.startswith(
        f"Landed {tip} on `dev` at `origin`, which was at {old}.\n"
        f"The operator approved `{path}`.\n"
    )
    assert landings.on_forge("refs/heads/dev") == tip
    assert after == []


def test_a_link_at_a_protected_directory_s_name_holds_its_landing_until_approved(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    (landings.feat / ".claude").symlink_to("elsewhere")
    landings.wrote(landings.feat, "elsewhere/settings.json", "{}\n")
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged()
    session = lander(landings, "claude")
    with serving_landings(landings, machine, clock, notices, said) as (delivery, pool):
        landing, wait = held_landing(machine, clock, delivery, pool)
        meanwhile = landings.on_forge("refs/heads/dev")
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, ".claude")
        answer, error = landing.result(timeout=60)
    assert not error
    assert meanwhile == old
    assert waited_on(wait) == [".claude"]
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")
    assert landings.on_forge("refs/heads/dev") == tip


def test_a_file_a_landing_asks_about_declined_lands_nothing_and_the_next_landing_holds_it_again(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    landings.wrote(landings.feat, WORKFLOW, "on: push\n")
    old = landings.on_forge("refs/heads/dev")
    session = lander(landings, "claude")
    with serving_landings(landings, machine, clock, notices, said) as (delivery, pool):
        landing, _ = held_landing(
            machine,
            clock,
            delivery,
            pool,
            {"branch": "feat", "message": MESSAGE},
        )
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, WORKFLOW, decline=True)
        declined, error = landing.result(timeout=60)
        kept = landings.on_forge("refs/heads/dev")
        tip = landings.shell.git(landings.dev, "rev-parse", "HEAD")
        landings.passing(tip)
        again, _ = held_landing(machine, clock, delivery, pool)
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, WORKFLOW)
        answer, later = again.result(timeout=60)
        flags = [
            item.number
            for item in delivery.inbox.items.values()
            if isinstance(item.reason, Flagged)
        ]
    assert not error
    assert not later
    assert declined.startswith(
        "Not landed: the operator didn't approve each file it waits on.\n"
        f"- `{WORKFLOW}`: declined\n"
    )
    assert f"`dev` here holds the merge, {tip}" in declined
    assert kept == old
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")
    assert landings.on_forge("refs/heads/dev") == tip
    assert len(flags) == 1


def test_a_file_approved_at_a_landing_that_didn_t_land_isn_t_asked_about_at_the_next(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    documents = "AGENTS.md"
    landings.wrote(landings.feat, WORKFLOW, "on: push\n")
    landings.wrote(landings.feat, documents, "Say why.\n")
    tip = landings.merged()
    session = lander(landings, "claude")
    with serving_landings(landings, machine, clock, notices, said) as (delivery, pool):
        landing, first = held_landing(machine, clock, delivery, pool)
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, WORKFLOW)
        answering(machine, clock, session, place, documents, decline=True)
        refused, _ = landing.result(timeout=60)
        again, second = held_landing(machine, clock, delivery, pool)
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, documents)
        answer, error = again.result(timeout=60)
    assert not error
    assert waited_on(first) == [WORKFLOW, documents]
    assert f"- `{WORKFLOW}`: approved\n" in refused
    assert f"- `{documents}`: declined\n" in refused
    assert waited_on(second) == [documents]
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")


def test_a_file_approved_through_a_hold_at_this_content_lands_asking_nothing(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    content = "on: push\n"
    landings.wrote(landings.feat, WORKFLOW, content)
    tip = landings.merged()
    with serving_landings(landings, machine, clock, notices, said) as (delivery, _):
        hold = hold_on(landings, machine, clock, WORKFLOW, content)
        inbox("answer", str(hold), "--approve", "--comment", "")
        answer, error = call(machine.host.launch("one").mcp, "land", {})
        flags = [
            item.number
            for item in delivery.inbox.items.values()
            if isinstance(item.reason, Flagged)
        ]
    assert not error
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")
    assert "The operator approved" not in answer
    assert flags == []
    assert landings.on_forge("refs/heads/dev") == tip


@pytest.mark.parametrize(
    ("answers", "content"),
    [
        (["--approve"], "another version\n"),
        (["--decline"], "on: push\n"),
        (["--approve", "--decline"], "on: push\n"),
    ],
    ids=["another-version", "declined", "declined-since"],
)
def test_a_hold_approving_another_version_or_declined_since_leaves_the_landing_asking(
    answers: list[str],
    content: str,
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    *,
    notices: Raised,
    said: list[str],
) -> None:
    landings.wrote(landings.feat, WORKFLOW, "on: push\n")
    tip = landings.merged()
    session = lander(landings, "claude")
    with serving_landings(landings, machine, clock, notices, said) as (delivery, pool):
        for each in answers:
            hold = hold_on(landings, machine, clock, WORKFLOW, content)
            inbox("answer", str(hold), each, "--comment", "")
        landing, wait = held_landing(machine, clock, delivery, pool)
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, WORKFLOW)
        answer, error = landing.result(timeout=60)
    assert not error
    assert waited_on(wait) == [WORKFLOW]
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")


@pytest.mark.parametrize("approving", [True, False], ids=["approved", "declined"])
def test_a_hold_still_open_on_what_a_landing_lands_holds_it_and_its_answer_answers_the_landing(
    approving: bool,
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    *,
    said: list[str],
) -> None:
    content = "on: push\n"
    landings.wrote(landings.feat, WORKFLOW, content)
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged()
    with serving_landings(landings, machine, clock, notices, said) as (delivery, pool):
        hold = hold_on(landings, machine, clock, WORKFLOW, content)
        landing, wait = held_landing(machine, clock, delivery, pool)
        word = "--approve" if approving else "--decline"
        inbox(
            "answer", str(hold), word, "--comment", "Not this." if not approving else ""
        )
        answer, error = landing.result(timeout=60)
    assert not error
    assert waited_on(wait) == [WORKFLOW]
    if approving:
        assert answer.startswith(f"Landed {tip} on `dev` at `origin`")
        assert landings.on_forge("refs/heads/dev") == tip
    else:
        assert answer.startswith(
            "Not landed: the operator didn't approve each file it waits on.\n"
            f"- `{WORKFLOW}`: declined, saying:\n  Not this.\n"
        )
        assert landings.on_forge("refs/heads/dev") == old


def test_a_version_the_operator_never_approved_asks_though_a_later_one_was_approved(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    refused, fixed = "on: push\n", "on: pull_request\n"
    landings.wrote(landings.feat, WORKFLOW, refused)
    landings.merged()
    session = lander(landings, "claude")
    with serving_landings(landings, machine, clock, notices, said) as (delivery, pool):
        first, _ = held_landing(machine, clock, delivery, pool)
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, WORKFLOW, decline=True)
        first.result(timeout=60)
        landings.wrote(landings.feat, WORKFLOW, fixed)
        landings.merged()
        second, _ = held_landing(machine, clock, delivery, pool)
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, WORKFLOW)
        landed, _ = second.result(timeout=60)
        landings.wrote(landings.dev, WORKFLOW, refused)
        tip = landings.shell.git(landings.dev, "rev-parse", "HEAD")
        landings.passing(tip)
        third, wait = held_landing(machine, clock, delivery, pool)
        place = drawer(machine, clock, session, "dev")
        answering(machine, clock, session, place, WORKFLOW)
        answer, error = third.result(timeout=60)
    assert not error
    assert landed.startswith("Landed ")
    assert waited_on(wait) == [WORKFLOW]
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")


IGNORING = '"""Rooms."""\n\nx = 1  # lup: ignore("regex", why="a grammar")\n'
"""A module of a production path adding an `ignore`, which no hook of these tests hears written."""


def test_a_landing_holds_an_ignore_its_own_diff_adds_whatever_the_hooks_heard_and_lands_once_approved(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    path = "src/pkg/rooms.py"
    landings.wrote(landings.feat, path, IGNORING)
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged()
    session = lander(landings, "claude")
    with serving_landings(landings, machine, clock, notices, said) as (delivery, pool):
        landing, wait = held_landing(machine, clock, delivery, pool)
        meanwhile = landings.on_forge("refs/heads/dev")
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, path)
        answer, error = landing.result(timeout=60)
    assert not error
    assert meanwhile == old
    assert waited_on(wait) == [path]
    [file] = [each for each in place.files if each.path == Path(path)]
    assert file.file is not None
    assert file.file.reading == Reading(
        role="production", asks=[Ask(name="ignore", taken="held", line=3)]
    )
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")
    assert landings.on_forge("refs/heads/dev") == tip


def test_a_landing_with_an_ignore_declined_lands_nothing(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    path = "src/pkg/rooms.py"
    landings.wrote(landings.feat, path, IGNORING)
    old = landings.on_forge("refs/heads/dev")
    landings.merged()
    session = lander(landings, "claude")
    with serving_landings(landings, machine, clock, notices, said) as (delivery, pool):
        landing, _ = held_landing(machine, clock, delivery, pool)
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, path, decline=True)
        answer, error = landing.result(timeout=60)
    assert not error
    assert "Landed" not in answer
    assert landings.on_forge("refs/heads/dev") == old


def test_an_ignore_approved_at_that_version_isn_t_asked_again_at_its_landing(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    path = "src/pkg/rooms.py"
    landings.wrote(landings.feat, path, IGNORING)
    tip = landings.merged()
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ) as delivery:
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        delivery.settle_hold = lambda _change, _approved, _comment: None
        number = hold_on(landings, machine, clock, path, IGNORING)
        inbox("answer", str(number), "--approve", "--comment", "")
        answer, error = call(machine.host.launch("one").mcp, "land", {})
    assert not error, answer
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")


def test_a_landing_whose_ignores_can_t_be_read_lands_nothing_saying_why(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    old = landings.on_forge("refs/heads/dev")
    landings.merged()
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=Unreadable()
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer, _ = call(machine.host.launch("one").mcp, "land", {})
    assert answer.startswith("Not landed:"), answer
    assert "node: not found" in answer
    assert landings.on_forge("refs/heads/dev") == old


def test_what_a_landing_asks_is_the_approved_declaration_s_never_the_one_it_lands(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    """The branch's own declaration would protect nothing: it isn't run, and it asks as the protected path it is."""
    approving = Core(paths=Paths().add(protected=["config/**"]))
    project = Project(modules=Modules.default().edit(approving))
    declared_branches(machine, landings.repository, Branches())
    write_model(
        machine.declaration(landings.repository),
        LastDeclaration(
            declaration=Declaration.of(project, Path("lup_project.py")),
            commit="0" * 40,
        ),
    )
    unprotecting = 'raise SystemExit("a declaration protecting nothing, never run")\n'
    for path, content in {
        "lup_project.py": unprotecting,
        WORKFLOW: "on: push\n",
        "config/a.toml": "a = 1\n",
        "notes.md": "Nothing to ask.\n",
    }.items():
        landings.wrote(landings.feat, path, content)
    tip = landings.merged()
    session = lander(landings, "claude")
    with serving_landings(landings, machine, clock, notices, said) as (delivery, pool):
        landing, wait = held_landing(machine, clock, delivery, pool)
        place = drawer(machine, clock, session, "feat")
        for path in waited_on(wait):
            answering(machine, clock, session, place, path)
        answer, error = landing.result(timeout=60)
    assert not error
    assert waited_on(wait) == [WORKFLOW, "config/a.toml", "lup_project.py"]
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")


def test_a_role_the_approved_declaration_doesn_t_hold_asks_nothing_at_its_landing(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    """A level is the judge's reading too: a project reviewing its protected paths has them hold no write, and no landing."""
    project = Project(
        modules=Modules.default().edit(Core(levels=Levels(protected="review")))
    )
    declared_branches(machine, landings.repository, Branches())
    write_model(
        machine.declaration(landings.repository),
        LastDeclaration(declaration=Declaration.of(project), commit="0" * 40),
    )
    landings.wrote(landings.feat, WORKFLOW, "on: push\n")
    tip = landings.merged()
    with serving_landings(landings, machine, clock, notices, said):
        answer, error = call(machine.host.launch("one").mcp, "land", {})
    assert not error
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")


def test_a_deletion_a_landing_asks_about_is_held_shown_deleted_and_lands_once_approved(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    path, content = ".gitignore", "tmp/\n"
    landings.wrote(landings.dev, path, content)
    landings.shell.git(landings.repository, "push", "-q", "origin", "dev")
    gone = landings.branched("gone")
    landings.shell.git(gone, "rm", "-q", path)
    landings.shell.commit(gone, "take it away")
    tip = landings.merged("gone")
    session = lander(landings, "claude")
    with serving_landings(landings, machine, clock, notices, said) as (delivery, pool):
        landing, wait = held_landing(machine, clock, delivery, pool)
        place = drawer(machine, clock, session, "gone")
        answering(machine, clock, session, place, path)
        answer, error = landing.result(timeout=60)
    assert not error
    assert waited_on(wait) == [path]
    [file] = [each for each in place.files if each.path == Path(path)]
    assert file.version is None
    assert file.file is not None
    assert (file.file.before, file.file.after) == (Text(text=content), None)
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")


def test_a_file_a_landing_asks_about_is_in_the_drawer_of_who_works_on_its_branch(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    tmp_path: Path,
) -> None:
    records = Subagents(tmp_path)
    landings.wrote(landings.feat, WORKFLOW, "on: push\n")
    tip = landings.merged()
    worker = lander(landings, "claude").model_copy(update={"agent": "a1"})
    with (
        inboxed(
            machine, clock, notices, said, rooms=landings.room, parser=landings.parser
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        SessionIndex(layout=machine).write(
            "s1",
            Worked(
                repository=landings.repository,
                worktrees=[landings.dev, landings.feat],
                started={"": [landings.dev]},
                apart={"a1": landings.feat},
            ),
        )
        landings.launched("claude")
        hook = machine.host.launch("one").hook
        send(hook, started("claude"))
        send(hook, records.spawn("t1"))
        records.recorded("a1", "general-purpose", "t1")
        send(hook, records.call("a1", "general-purpose", "a1-c1"))
        landing, wait = held_landing(machine, clock, delivery, pool)
        place = drawer(machine, clock, worker, "feat")
        answering(machine, clock, worker, place, WORKFLOW)
        answer, error = landing.result(timeout=60)
    assert not error
    assert [each.writers for each in wait.files] == [[worker]]
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")


def test_a_branch_changing_nothing_its_role_asks_about_lands_as_before(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    landings.wrote(landings.feat, "docs/rooms.md", "Rooms.\n")
    tip = landings.merged()
    with serving_landings(landings, machine, clock, notices, said) as (delivery, _):
        answer, error = call(machine.host.launch("one").mcp, "land", {})
        items = [
            item.number
            for item in delivery.inbox.items.values()
            if isinstance(item.reason, Flagged)
        ]
    assert not error
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")
    assert "The operator approved" not in answer
    assert items == []
    assert not [each for each in notices.raised if "landing" in each]
    assert landings.on_forge("refs/heads/dev") == tip


def checking_pushes(
    delivery: Delivery, machine: Layout, said: list[str], parser: Parser
) -> Remotes:
    """The remotes the host service pushes through, each push held to what the operator approved of what it lands, telling nothing after it."""
    coming = Coming(delivery=delivery, layout=machine, say=said.append)
    served = cli.host_remotes(delivery, machine, coming, Predating(), parser)
    return served.model_copy(
        update={"say": said.append, "landed": None, "modules": None}
    )


def test_a_push_to_a_gated_branch_is_refused_where_what_it_lands_adds_an_ignore(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    path = "src/pkg/rooms.py"
    landings.wrote(landings.feat, path, IGNORING)
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged()
    onto = Pushing(
        remote="origin", updates=[Update(source=tip, destination="refs/heads/dev")]
    )
    with serving_landings(landings, machine, clock, notices, said) as (delivery, _):
        launch = landings.launched("claude", name="pushing")
        handler = PushHandler(
            remotes=checking_pushes(delivery, machine, said, landings.parser)
        )
        refused = asyncio.run(handler.answer(onto, launch))
        hold = hold_on(landings, machine, clock, path, IGNORING)
        inbox("answer", str(hold), "--approve", "--comment", "")
        pushed = asyncio.run(handler.answer(onto, launch))
    assert isinstance(refused, Pushed)
    [update] = refused.updates
    assert update.error is not None
    assert f"`{path}`" in update.error
    assert "an `ignore` it adds" in update.error
    assert isinstance(pushed, Pushed)
    assert [each.error for each in pushed.updates] == [None]
    assert old != tip
    assert landings.on_forge("refs/heads/dev") == tip


def test_a_push_to_a_gated_branch_is_refused_where_what_it_lands_asks_and_goes_once_approved(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    """A push can't wait for the operator, so it's refused before anything reaches the remote, read as a landing reads its diff, and flags nothing: `land` is the way through."""
    content = "on: push\n"
    landings.wrote(landings.feat, WORKFLOW, content)
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged()
    onto = Pushing(
        remote="origin", updates=[Update(source=tip, destination="refs/heads/dev")]
    )
    beside = Pushing(
        remote="origin", updates=[Update(source=tip, destination="refs/heads/other")]
    )
    with serving_landings(landings, machine, clock, notices, said) as (delivery, _):
        launch = landings.launched("claude", name="pushing")
        handler = PushHandler(
            remotes=checking_pushes(delivery, machine, said, landings.parser)
        )
        refused = asyncio.run(handler.answer(onto, launch))
        kept = landings.on_forge("refs/heads/dev")
        other = asyncio.run(handler.answer(beside, launch))
        flags = [
            item.number
            for item in delivery.inbox.items.values()
            if isinstance(item.reason, Flagged)
        ]
        hold = hold_on(landings, machine, clock, WORKFLOW, content)
        inbox("answer", str(hold), "--approve", "--comment", "")
        pushed = asyncio.run(handler.answer(onto, launch))
    assert isinstance(refused, Pushed)
    [update] = refused.updates
    assert update.error is not None
    assert f"`{WORKFLOW}`" in update.error
    assert "`land`" in update.error
    assert kept == old
    assert flags == []
    assert isinstance(other, Pushed)
    assert [each.error for each in other.updates] == [None]
    assert isinstance(pushed, Pushed)
    assert [each.error for each in pushed.updates] == [None]
    assert landings.on_forge("refs/heads/dev") == tip


def test_a_push_to_a_gated_branch_changing_nothing_its_role_asks_about_goes_as_before(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    tip = landings.merged()
    onto = Pushing(
        remote="origin", updates=[Update(source=tip, destination="refs/heads/dev")]
    )
    with serving_landings(landings, machine, clock, notices, said) as (delivery, _):
        launch = landings.launched("claude", name="pushing")
        handler = PushHandler(
            remotes=checking_pushes(delivery, machine, said, landings.parser)
        )
        pushed = asyncio.run(handler.answer(onto, launch))
    assert isinstance(pushed, Pushed)
    assert [each.error for each in pushed.updates] == [None]
    assert landings.on_forge("refs/heads/dev") == tip


def test_a_binary_file_a_landing_asks_about_approved_from_the_terminal_passes_its_own_push(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    """Its content isn't kept, so the flag says its version: the push `land` makes reads the same approval the landing waited on."""
    path, content = "certs/host.p12", b"\x00\x01 a key store"
    file = landings.feat / path
    file.parent.mkdir()
    file.write_bytes(content)
    landings.shell.commit(landings.feat, "a key store")
    tip = landings.merged()
    with (
        inboxed(
            machine,
            clock,
            notices,
            said,
            rooms=landings.room,
            parser=landings.parser,
            remotes=lambda delivery: checking_pushes(
                delivery, machine, said, landings.parser
            ),
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        landing, wait = held_landing(machine, clock, delivery, pool)
        [[flag]] = [each.flags for each in wait.files]
        kept = delivery.inbox.files(flag)
        inbox("done", str(flag))
        answer, error = landing.result(timeout=60)
    assert not error
    assert [each.after for each in kept] == [Binary(size=len(content))]
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")
    assert landings.on_forge("refs/heads/dev") == tip


def test_what_a_landing_asks_is_what_the_approval_keeps_of_its_declaration_before_the_judge_s(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    """No judge need have run: and where one did, at another commit, the approval's says."""

    def protecting(pattern: str) -> Declaration:
        approving = Core(paths=Paths().add(protected=[pattern]))
        return Declaration.of(Project(modules=Modules.default().edit(approving)))

    declared_branches(machine, landings.repository, Branches())
    kept = machine.approved(landings.repository)
    approval = read_model(kept, StoredApproval)
    assert approval is not None
    write_model(
        kept, approval.model_copy(update={"declaration": protecting("approved/**")})
    )
    write_model(
        machine.declaration(landings.repository),
        LastDeclaration(declaration=protecting("judged/**"), commit="0" * 40),
    )
    landings.wrote(landings.feat, "approved/a.toml", "a = 1\n")
    landings.wrote(landings.feat, "judged/a.toml", "a = 1\n")
    landings.merged()
    session = lander(landings, "claude")
    with serving_landings(landings, machine, clock, notices, said) as (delivery, pool):
        landing, wait = held_landing(machine, clock, delivery, pool)
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, "approved/a.toml")
        answer, error = landing.result(timeout=60)
    assert not error
    assert waited_on(wait) == ["approved/a.toml"]
    assert answer.startswith("Landed ")


MESSAGE = "feat(rooms): rooms, `merged` by $(land)\n\nWhat changed, and why.  \n\n\n"
"""A merge commit's message holding what a shell would read, and the blank lines `git commit -m` cleans away."""

CLEANED = "feat(rooms): rooms, `merged` by $(land)\n\nWhat changed, and why."
"""`MESSAGE` as the merge commit carries it."""


def merging(landings: Landings, mcp: Path, message: str = MESSAGE) -> str:
    """Land `feat` through the launch's `mcp`, merged with `message`: the answer, which mustn't be an error."""
    answer, error = call(mcp, "land", {"branch": "feat", "message": message})
    assert not error, answer
    return answer


def moved_on(landings: Landings) -> str:
    """Commit on `dev` and push it, as a landing meanwhile would: return the remote's tip."""
    landings.wrote(landings.dev, "src/pkg/hall.py", '"""Hall."""\n')
    landings.shell.git(landings.repository, "push", "-q", "origin", "dev")
    old = landings.on_forge("refs/heads/dev")
    assert old is not None
    return old


def test_land_merges_a_branch_onto_dev_in_the_room_gates_the_merge_and_moves_dev_there(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    feat, dev, shell = landings.feat, landings.dev, landings.shell
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    branch = shell.git(dev, "rev-parse", "feat")
    old = moved_on(landings)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    merge = landings.on_forge("refs/heads/dev")
    assert answer == (
        f"Merged `feat` onto `dev` as {merge}, and moved `dev` here to it: the gate "
        "passed on it.\n"
        f"Landed {merge} on `dev` at `origin`, which was at {old}.\n"
        "`feat` adds no `# lup: defer` comment and removes none, against `dev`.\n"
        "Cleaned up after it:\n"
        f"- removed the worktree {feat}\n"
        "- deleted the local branch `feat`\n"
        f"{NOTHING_GOING}"
    )
    assert merge is not None
    assert shell.git(dev, "rev-parse", f"{merge}^@").splitlines() == [old, branch]
    assert shell.git(dev, "log", "-1", "--format=%B", merge) == CLEANED
    assert shell.git(dev, "rev-parse", "HEAD") == merge
    assert (dev / "src/pkg/rooms.py").read_text() == '"""Rooms."""\n'
    assert landings.gate.ran == [Uv().judging(["lup-dev", "check", "--fix"])]
    assert landings.ran == [
        ["podman", "container", "exists", "lup-one"],
        [
            *["podman", "exec", "--interactive", "--workdir", str(dev), "lup-one"],
            *["uv", "run", "lup-dev", "merge", old, branch],
        ],
        [
            *["podman", "exec", "--workdir", str(dev), "lup-one"],
            *["git", "merge", "--ff-only", "--quiet", merge],
        ],
        ["podman", "container", "exists", "lup-one"],
        listing(dev, "lup-one"),
        [
            *["podman", "exec", "--workdir", str(dev), "lup-one"],
            *["git", "worktree", "remove", str(feat)],
        ],
    ]


def test_land_wakes_each_thread_parked_until_the_branch_it_lands_or_a_commit_its_push_brings(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    feat, dev, shell = landings.feat, landings.dev, landings.shell
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    branch = shell.git(dev, "rev-parse", "feat")
    moved_on(landings)
    made: dict[str, Coming] = {}

    def coming(delivery: Delivery) -> Coming:
        return made.setdefault(
            "coming",
            Coming(delivery=delivery, layout=machine, say=said.append),
        )

    def remotes(delivery: Delivery) -> Remotes:
        async def landed(launch: Register, updates: list[Update]) -> None:
            await coming(delivery).pushed(launch, updates)

        return Remotes(say=said.append, landed=landed)

    waiting = {
        "after-feat": BranchLanded(branch="feat"),
        "after-commit": CommitLanded(commit=branch[:10]),
        "after-other": BranchLanded(branch="other"),
    }
    with inboxed(
        machine,
        clock,
        notices,
        said,
        rooms=landings.room,
        parser=landings.parser,
        remotes=remotes,
        coming=coming,
    ) as delivery:
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        party = lander(landings, "claude")
        concerns = delivery.concerns()
        for name, trigger in waiting.items():
            concerns.parked(
                party,
                concerns.opened(party, name, landings.repository, name=name),
                [trigger],
                "",
            )
        merging(landings, machine.host.launch("one").mcp)
        stands = {
            name: concerns.standing(concerns.named(landings.repository, name)).status
            for name in waiting
        }
    woken = {
        name: status.why
        for name, status in stands.items()
        if isinstance(status, ThreadReopened)
    }
    assert woken == {
        "after-feat": "`feat` landed",
        "after-commit": f"commit {branch[:10]} landed",
    }
    assert isinstance(stands["after-other"], Parked)


LIVE = Branches(integration="dev", running="live")
"""A project computing `live` from `dev` and what's on trial."""


def parents_of(landings: Landings, commit: str) -> list[str]:
    """Return `commit`'s parents, as the forge holds it."""
    _, *parents = landings.shell.git(
        landings.forge, "rev-list", "--parents", "-n", "1", commit
    ).split()
    return parents


def test_a_branch_land_lands_goes_on_trial_on_a_branch_the_host_computes_and_stays(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    feat, shell = landings.feat, landings.shell
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    tip = shell.git(feat, "rev-parse", "HEAD")
    accepted = landings.on_forge("refs/heads/dev")
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    live = landings.on_forge("refs/heads/live")
    assert live is not None
    assert parents_of(landings, live) == [accepted, tip]
    assert (
        shell.git(landings.forge, "show", f"{live}:src/pkg/rooms.py") == '"""Rooms."""'
    )
    assert landings.on_forge("refs/heads/dev") == accepted
    assert f"Landed `feat` on `live` at `origin`, as {live}" in answer
    assert "`dev` with `feat`" in answer
    assert "until the operator accepts it (`lup-dev live accept feat`)" in answer
    # What's accepted is what's cleaned up: the branch and its worktree stay.
    assert feat.is_dir()
    assert shell.git(landings.repository, "branch", "--list", "feat") != ""
    assert shell.git(landings.repository, "rev-parse", "refs/heads/live") == live
    assert Trials.of(machine, landings.repository).read().tips == {"feat": tip}


def test_a_launch_from_before_the_running_branch_was_approved_lands_on_it_with_no_relaunch(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        # Its limits, registered as the launch began, don't name `live`.
        landings.launched("claude", gated=["refs/heads/dev"])
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    assert "Landed `feat` on `live`" in answer
    assert landings.on_forge("refs/heads/live") is not None


def test_a_second_landing_is_the_next_commit_each_landing_a_fast_forward_of_the_last(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    feat, shell = landings.feat, landings.shell
    other = landings.branched("other")
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    landings.wrote(other, "src/pkg/halls.py", '"""Halls."""\n')
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        mcp = machine.host.launch("one").mcp
        merging(landings, mcp)
        first = landings.on_forge("refs/heads/live")
        assert first is not None
        answer, error = call(mcp, "land", {"branch": "other", "message": "other"})
    assert not error, answer
    live = landings.on_forge("refs/heads/live")
    assert live is not None
    dev = landings.on_forge("refs/heads/dev")
    assert parents_of(landings, live)[:2] == [first, dev]
    assert "`dev` with `feat` and `other`" in answer
    # Both files, as computed from `dev`, never `live` merged into.
    shown = shell.git(landings.forge, "ls-tree", "-r", "--name-only", live)
    assert "src/pkg/rooms.py" in shown
    assert "src/pkg/halls.py" in shown


def test_a_commit_added_after_landing_doesn_t_reach_live_until_it_lands(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    feat, shell = landings.feat, landings.shell
    other = landings.branched("other")
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    landed_at = shell.git(feat, "rev-parse", "HEAD")
    landings.wrote(other, "src/pkg/halls.py", '"""Halls."""\n')
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        mcp = machine.host.launch("one").mcp
        merging(landings, mcp)
        # A room writes its branch's ref: what's kept is the tip that landed.
        landings.wrote(feat, "src/pkg/sneaked.py", '"""Sneaked."""\n')
        call(mcp, "land", {"branch": "other", "message": "other"})
    live = landings.on_forge("refs/heads/live")
    assert live is not None
    assert landed_at in parents_of(landings, live)
    shown = shell.git(landings.forge, "ls-tree", "-r", "--name-only", live)
    assert "src/pkg/sneaked.py" not in shown
    assert Trials.of(machine, landings.repository).read().tips["feat"] == landed_at


def test_a_branch_changing_only_docs_and_tests_goes_straight_to_dev_and_is_cleaned_up(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    feat, shell = landings.feat, landings.shell
    landings.wrote(feat, "docs/rooms.md", "# Rooms\n")
    accepted = landings.on_forge("refs/heads/dev")
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    dev = landings.on_forge("refs/heads/dev")
    assert dev != accepted
    assert f"Landed {dev} on `dev` at `origin`" in answer
    assert landings.on_forge("refs/heads/live") is None
    assert not feat.exists()
    assert shell.git(landings.repository, "branch", "--list", "feat") == ""


def test_a_test_inside_what_the_host_builds_goes_on_trial_whatever_its_role(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    feat = landings.feat
    landings.wrote(feat, "page/src/rooms.test.ts", "test('runs on the host');\n")
    declared_branches(machine, landings.repository, LIVE)
    approval = read_model(machine.approved(landings.repository), StoredApproval)
    assert approval is not None
    write_model(
        machine.approved(landings.repository),
        approval.model_copy(update={"paths": [Path("page")]}),
    )
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    assert "Landed `feat` on `live`" in answer
    assert feat.is_dir()


def test_land_onto_dev_refuses_what_the_host_runs_since_that_s_the_operator_accepting(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    accepted = landings.on_forge("refs/heads/dev")
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer, error = call(
            machine.host.launch("one").mcp,
            "land",
            {"branch": "feat", "message": "feat", "onto": "dev"},
        )
    assert not error
    assert (
        "Not landed: `feat` changes what the host runs (`src/pkg/rooms.py`)" in answer
    )
    assert "accepting it, the operator's" in answer
    assert landings.on_forge("refs/heads/dev") == accepted
    assert landings.on_forge("refs/heads/live") is None


def test_dev_landing_as_it_is_refuses_what_the_host_runs_committed_on_it(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    landings.wrote(landings.dev, "src/pkg/rooms.py", '"""Rooms."""\n')
    accepted = landings.on_forge("refs/heads/dev")
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer, error = call(machine.host.launch("one").mcp, "land", {})
    assert not error
    assert "Not landed: `dev` changes what the host runs" in answer
    assert landings.on_forge("refs/heads/dev") == accepted


def test_a_branch_conflicting_with_what_s_on_trial_stays_on_trial_out_of_live_and_is_told(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    feat = landings.feat
    rival = landings.branched("rival")
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    landings.wrote(rival, "src/pkg/rooms.py", '"""Rival rooms."""\n')
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        mcp = machine.host.launch("one").mcp
        merging(landings, mcp)
        live = landings.on_forge("refs/heads/live")
        answer, error = call(mcp, "land", {"branch": "rival", "message": "rival"})
    assert not error, answer
    assert landings.on_forge("refs/heads/live") == live
    assert "`rival` is on trial" in answer
    assert (
        "and not in `live`: it conflicts with `feat`, in `src/pkg/rooms.py`" in answer
    )
    # On the remote, so what a pick later puts in `live` has passed the door.
    assert landings.on_forge("refs/heads/rival") is not None
    assert rival.is_dir()
    trial = Trials.of(machine, landings.repository).read()
    assert list(trial.tips) == ["feat"]
    on = trial.on("rival")
    assert on is not None
    assert on.conflict == "it conflicts with `feat`, in `src/pkg/rooms.py`"


def test_a_branch_conflicting_with_dev_says_merge_dev_in_and_nothing_goes_on_trial(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    landings.wrote(landings.dev, "src/pkg/rooms.py", '"""Other."""\n')
    landings.shell.git(landings.repository, "push", "-q", "origin", "dev")
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    assert "merging `feat` onto `dev` conflicts" in answer
    assert "- src/pkg/rooms.py" in answer
    assert Trials.of(machine, landings.repository).read().branches == []


def test_a_gate_failing_on_what_live_would_hold_lands_nothing(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    landings.gate.code = 1
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    assert "Not landed: the gate failed on what `live` would hold with `feat`" in answer
    assert "the gate's report, ending 1" in answer
    assert landings.on_forge("refs/heads/live") is None
    assert Trials.of(machine, landings.repository).read().branches == []
    # Its fixes would be lost at the next recompute, so none are asked for.
    assert ["uv", "run", "lup-dev", "check", "--fix"] not in landings.gate.ran


def test_a_first_landing_asks_only_about_its_own_files_never_what_dev_holds_already(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    shell, dev = landings.shell, landings.dev
    # What `dev` holds already: a protected file, read when it landed there.
    landings.wrote(dev, "lup_project.py", '"""The declaration."""\n')
    shell.git(landings.repository, "push", "-q", "origin", "dev")
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ) as delivery:
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
        items = [
            each.reason
            for each in delivery.inbox.items.values()
            if isinstance(each.reason, Flagged)
        ]
    assert items == []
    assert "Landed `feat` on `live`" in answer


def test_a_protected_file_a_branch_on_trial_changes_holds_its_landing_on_the_operator(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    landings.wrote(landings.feat, "lup_project.py", '"""Changed."""\n')
    declared_branches(machine, landings.repository, LIVE)
    session = lander(landings, "claude")
    with (
        inboxed(
            machine, clock, notices, said, rooms=landings.room, parser=landings.parser
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        landing = pool.submit(merging, landings, machine.host.launch("one").mcp)
        assert delivery.holding.wait(timeout=60)
        assert landings.on_forge("refs/heads/live") is None
        assert Trials.of(machine, landings.repository).read().branches == []
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, "lup_project.py")
        answer = landing.result(timeout=60)
    assert "Landed `feat` on `live`" in answer
    assert "The operator approved `lup_project.py`." in answer
    assert landings.on_forge("refs/heads/live") is not None


def trying_nothing_runs(machine: Layout, clock: FakeClock) -> Callable[[Turns], Trying]:
    """What moves what's on trial, every zone reading as the one approved, as `declared_branches` keeps it: a change in what runs is another test's."""

    def made(turns: Turns) -> Trying:
        def unexpected(_copy: CopyLayout, commit: str) -> None:
            message = f"a switch to {commit}, where what runs doesn't change"
            raise AssertionError(message)

        return Trying(
            layout=machine,
            clock=clock,
            say=lambda _: None,
            turns=turns,
            fingerprint=lambda _, __: "",
            propose=lambda _: None,
            start=unexpected,
        )

    return made


def test_accepting_a_branch_merges_it_onto_dev_cleans_up_after_it_and_wakes_what_s_parked_on_it(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    feat, shell = landings.feat, landings.shell
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    tip = shell.git(feat, "rev-parse", "HEAD")
    accepted = landings.on_forge("refs/heads/dev")
    declared_branches(machine, landings.repository, LIVE)
    made: dict[str, Coming] = {}

    def coming(delivery: Delivery) -> Coming:
        return made.setdefault(
            "coming", Coming(delivery=delivery, layout=machine, say=said.append)
        )

    def remotes(delivery: Delivery) -> Remotes:
        async def landed(launch: Register, updates: list[Update]) -> None:
            await coming(delivery).pushed(launch, updates)

        return Remotes(say=said.append, landed=landed)

    with inboxed(
        machine,
        clock,
        notices,
        said,
        rooms=landings.room,
        parser=landings.parser,
        remotes=remotes,
        coming=coming,
        trying=trying_nothing_runs(machine, clock),
    ) as delivery:
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        party = lander(landings, "claude")
        concerns = delivery.concerns()
        parked = concerns.opened(
            party, "after-feat", landings.repository, name="after-feat"
        )
        concerns.parked(party, parked, [BranchLanded(branch="feat")], "")
        merging(landings, machine.host.launch("one").mcp)
        on_trial = concerns.standing(
            concerns.named(landings.repository, "after-feat")
        ).status
        replied = client(machine.host, clock).ask(
            AcceptBranch(branch="feat", repository=landings.repository), TrialSaid
        )
        woken = concerns.standing(
            concerns.named(landings.repository, "after-feat")
        ).status
    # A landing on `live` wakes nothing: it hasn't reached what work starts from.
    assert not isinstance(on_trial, ThreadReopened)
    assert isinstance(woken, ThreadReopened)
    dev = landings.on_forge("refs/heads/dev")
    assert dev not in (None, accepted)
    assert parents_of(landings, dev or "") == [accepted, tip]
    assert f"Landed {dev} on `dev` at `origin`" in replied.said
    assert not feat.exists()
    assert shell.git(landings.repository, "branch", "--list", "feat") == ""
    trial = Trials.of(machine, landings.repository).read()
    assert trial.branches == []
    assert trial.dev == dev
    live = landings.on_forge("refs/heads/live")
    assert live == trial.live
    assert (
        shell.git(landings.forge, "show", f"{live}:src/pkg/rooms.py") == '"""Rooms."""'
    )


def test_accepting_merges_the_tip_that_landed_whatever_its_ref_says_since(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    feat, shell = landings.feat, landings.shell
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    tip = shell.git(feat, "rev-parse", "HEAD")
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine,
        clock,
        notices,
        said,
        rooms=landings.room,
        parser=landings.parser,
        trying=trying_nothing_runs(machine, clock),
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        merging(landings, machine.host.launch("one").mcp)
        landings.wrote(feat, "src/pkg/sneaked.py", '"""Sneaked."""\n')
        client(machine.host, clock).ask(
            AcceptBranch(branch="feat", repository=landings.repository), TrialSaid
        )
    dev = landings.on_forge("refs/heads/dev")
    assert parents_of(landings, dev or "")[1] == tip
    shown = shell.git(landings.forge, "ls-tree", "-r", "--name-only", dev or "")
    assert "src/pkg/sneaked.py" not in shown


def test_accepting_with_no_session_running_says_so(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    tip = landings.shell.git(landings.repository, "rev-parse", "dev")
    declared_branches(machine, landings.repository, LIVE)
    Trials.of(machine, landings.repository).write(
        Trial(branches=[OnTrial(branch="feat", tip=tip, landed=clock.now())])
    )
    with (
        inboxed(
            machine,
            clock,
            notices,
            said,
            rooms=landings.room,
            parser=landings.parser,
            trying=trying_nothing_runs(machine, clock),
        ),
        pytest.raises(HostError, match="no session of this repository is running"),
    ):
        client(machine.host, clock).ask(
            AcceptBranch(branch="feat", repository=landings.repository), TrialSaid
        )


def test_a_merge_asking_what_wasn_t_approved_leaves_it_in_the_drawer_accepting_nothing(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    dev = landings.dev
    lines = "".join(f"{each}\n" for each in "abcdefgh")
    landings.wrote(dev, "lup_project.py", lines)
    landings.shell.git(landings.repository, "push", "-q", "origin", "dev")
    other = landings.branched("other")
    landings.wrote(other, "lup_project.py", f"changed\n{lines}")
    declared_branches(machine, landings.repository, LIVE)
    session = lander(landings, "claude")
    with (
        inboxed(
            machine,
            clock,
            notices,
            said,
            rooms=landings.room,
            parser=landings.parser,
            trying=trying_nothing_runs(machine, clock),
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        mcp = machine.host.launch("one").mcp
        landing = pool.submit(
            call, mcp, "land", {"branch": "other", "message": "other"}
        )
        assert delivery.holding.wait(timeout=60)
        place = drawer(machine, clock, session, "other")
        answering(machine, clock, session, place, "lup_project.py")
        landing.result(timeout=60)
        landings.wrote(dev, "lup_project.py", f"{lines}moved\n")
        landings.shell.git(landings.repository, "push", "-q", "origin", "dev")
        before = landings.on_forge("refs/heads/dev")
        replied = client(machine.host, clock).ask(
            AcceptBranch(branch="other", repository=landings.repository), TrialSaid
        )
    assert replied.said.startswith("Not accepted: `other`")
    assert "`lup_project.py`" in replied.said
    assert landings.on_forge("refs/heads/dev") == before


def test_dropping_a_branch_leaves_it_and_its_worktree_and_what_s_said_waits_for_who_landed_it(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    feat, shell = landings.feat, landings.shell
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine,
        clock,
        notices,
        said,
        rooms=landings.room,
        parser=landings.parser,
        trying=trying_nothing_runs(machine, clock),
    ) as delivery:
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        merging(landings, machine.host.launch("one").mcp)
        replied = client(machine.host, clock).ask(
            DropBranch(
                branch="feat",
                words="rooms aren't it",
                repository=landings.repository,
            ),
            TrialSaid,
        )
        words = delivery.inbox.whereabouts[lander(landings, "claude").key()].words
    assert "Your words wait for who landed it" in replied.said
    assert "rooms aren't it" in words[-1]
    assert Trials.of(machine, landings.repository).read().branches == []
    assert feat.is_dir()
    assert shell.git(landings.repository, "branch", "--list", "feat") != ""
    live = landings.on_forge("refs/heads/live")
    shown = shell.git(landings.forge, "ls-tree", "-r", "--name-only", live or "")
    assert "src/pkg/rooms.py" not in shown


def test_a_room_s_push_moves_neither_the_branch_the_host_computes_nor_what_it_runs_onto_dev(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    tip = landings.merged()
    declared_branches(machine, landings.repository, LIVE)
    with serving_landings(landings, machine, clock, notices, said) as (delivery, _):
        launch = landings.launched(
            "claude", name="pushing", gated=["refs/heads/dev", "refs/heads/live"]
        )
        handler = PushHandler(
            remotes=checking_pushes(delivery, machine, said, landings.parser)
        )
        computed = asyncio.run(
            handler.answer(
                Pushing(
                    remote="origin",
                    updates=[Update(source=tip, destination="refs/heads/live")],
                ),
                launch,
            )
        )
        accepting = asyncio.run(
            handler.answer(
                Pushing(
                    remote="origin",
                    updates=[Update(source=tip, destination="refs/heads/dev")],
                ),
                launch,
            )
        )
    assert isinstance(computed, Pushed)
    assert "is computed by the host" in (computed.updates[0].error or "")
    assert isinstance(accepting, Pushed)
    assert "accepting it, the operator's" in (accepting.updates[0].error or "")
    assert landings.on_forge("refs/heads/live") is None
    assert landings.on_forge("refs/heads/dev") != tip


def test_a_room_s_push_of_docs_to_dev_goes_as_it_did(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    landings.wrote(landings.feat, "docs/rooms.md", "# Rooms\n")
    tip = landings.merged()
    declared_branches(machine, landings.repository, LIVE)
    with serving_landings(landings, machine, clock, notices, said) as (delivery, _):
        launch = landings.launched("claude", name="pushing")
        handler = PushHandler(
            remotes=checking_pushes(delivery, machine, said, landings.parser)
        )
        pushed = asyncio.run(
            handler.answer(
                Pushing(
                    remote="origin",
                    updates=[Update(source=tip, destination="refs/heads/dev")],
                ),
                launch,
            )
        )
    assert isinstance(pushed, Pushed)
    assert [each.error for each in pushed.updates] == [None]
    assert landings.on_forge("refs/heads/dev") == tip


def test_a_trial_branch_isn_t_landed_for_delete_merged_until_dev_holds_it(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    feat, shell = landings.feat, landings.shell
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    shell.git(landings.repository, "push", "-q", "origin", "feat")
    declared_branches(machine, landings.repository, LIVE)
    with inboxed(
        machine,
        clock,
        notices,
        said,
        rooms=landings.room,
        parser=landings.parser,
        remotes=lambda delivery: checking_pushes(
            delivery, machine, said, landings.parser
        ),
    ) as delivery:
        launch = landings.launched(
            "claude", gated=["refs/heads/dev", "refs/heads/live"]
        )
        send(machine.host.launch("one").hook, started("claude"))
        merging(landings, machine.host.launch("one").mcp)
        handler = PushHandler(
            remotes=checking_pushes(delivery, machine, said, landings.parser)
        )
        deleting_it = Pushing(
            remote="origin",
            updates=[Update(source=None, destination="refs/heads/feat")],
        )
        refused = asyncio.run(handler.answer(deleting_it, launch))
    assert isinstance(refused, Pushed)
    assert "aren't all in `refs/heads/dev`" in (refused.updates[0].error or "")
    assert landings.on_forge("refs/heads/feat") is not None


def test_a_subagent_kept_detached_is_told_to_start_from_the_integration_branch_not_what_it_landed_on() -> (
    None
):
    told = detached("feat", Path("/r/tree/w"), "live", "dev")
    assert "landed on `live`" in told
    assert "from `dev` (`git switch -c <branch> dev`)" in told


def test_the_bearings_read_what_landed_on_the_running_branch(
    landings: Landings,
    machine: Layout,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    repository, shell = landings.repository, landings.shell
    shell.git(landings.dev, "branch", "live", "dev")
    shell.git(repository, "update-ref", "refs/remotes/origin/live", "live")
    assert cli.running_branch(machine, repository) == "dev"
    declared_branches(machine, repository, Branches(integration="dev", running="live"))
    assert cli.running_branch(machine, repository) == "live"
    assert read_repository(repository, "live", "origin", None).onto == "origin/live"


def test_land_of_a_branch_leaves_alone_one_made_from_its_tip_worktree_and_all(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    """Seen on 2026-10-23 (#252): a worker handed back `since-merge-base`, then made `since-review-instant` from its tip to start their next piece, with no commit of its own yet; the landing merged that tip, and took both branches for landed."""
    dev, shell = landings.dev, landings.shell
    handed = landings.branched("since-merge-base")
    landings.wrote(handed, "src/pkg/since.py", '"""Since the merge base."""\n')
    branch = shell.git(dev, "rev-parse", "since-merge-base")
    # Its worker hasn't written there yet, so the judge's session index doesn't
    # place them in their new worktree (#240): nothing says anyone works there.
    following = landings.branched("since-review-instant", start="since-merge-base")
    old = landings.on_forge("refs/heads/dev")
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer, error = call(
            machine.host.launch("one").mcp,
            "land",
            {"branch": "since-merge-base", "message": MESSAGE},
        )
    merge = landings.on_forge("refs/heads/dev")
    assert not error, answer
    assert answer == (
        f"Merged `since-merge-base` onto `dev` as {merge}, and moved `dev` here to "
        "it: the gate passed on it.\n"
        f"Landed {merge} on `dev` at `origin`, which was at {old}.\n"
        "`since-merge-base` adds no `# lup: defer` comment and removes none, against `dev`.\n"
        "Cleaned up after it:\n"
        f"- removed the worktree {handed}\n"
        "- deleted the local branch `since-merge-base`\n"
        "Left alone, at the commit `since-merge-base` landed at, so made from it "
        "with nothing of its own yet: `since-review-instant`.\n"
        f"{NOTHING_GOING}"
    )
    assert merge is not None
    assert shell.git(dev, "rev-parse", f"{merge}^@").splitlines() == [old, branch]
    assert not handed.exists()
    assert following.is_dir()
    assert shell.git(dev, "rev-parse", "since-review-instant") == branch
    assert shell.git(dev, "branch", "--list", "since-merge-base") == ""
    assert landings.ran == [
        ["podman", "container", "exists", "lup-one"],
        [
            *["podman", "exec", "--interactive", "--workdir", str(dev), "lup-one"],
            *["uv", "run", "lup-dev", "merge", old, branch],
        ],
        [
            *["podman", "exec", "--workdir", str(dev), "lup-one"],
            *["git", "merge", "--ff-only", "--quiet", merge],
        ],
        ["podman", "container", "exists", "lup-one"],
        listing(dev, "lup-one"),
        [
            *["podman", "exec", "--workdir", str(dev), "lup-one"],
            *["git", "worktree", "remove", str(handed)],
        ],
    ]


def test_land_leaves_alone_each_branch_at_a_tip_merged_that_another_shares_and_their_flags_hold_it(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    """`dev` merged `feat` by hand and lands as it is, while a worker made `next` from `feat`'s tip: which of the two was merged, the graph can't tell, so neither is cleaned up, and a flag on either holds the landing."""
    rooms, path = '"""Rooms."""\n', "src/pkg/rooms.py"
    feat, shell = landings.feat, landings.shell
    landings.wrote(feat, path, rooms)
    following = landings.branched("next", start="feat")
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged()
    session = lander(landings, "claude")
    with (
        inboxed(
            machine, clock, notices, said, rooms=landings.room, parser=landings.parser
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        landings.launched("claude")
        mcp = machine.host.launch("one").mcp
        send(machine.host.launch("one").hook, started("claude"))
        flag = landings.flag(path, rooms, session)
        landing = pool.submit(call, mcp, "land", {})
        assert delivery.holding.wait(timeout=60)
        inbox("done", str(flag))
        answer, error = landing.result(timeout=60)
    assert not error, answer
    assert answer == (
        f"Landed {tip} on `dev` at `origin`, which was at {old}.\n"
        f"The operator approved `{path}`.\n"
        "`dev`'s own commits add no `# lup: defer` comment and remove none, against `dev` on `origin`.\n"
        "Left alone, at a tip `dev` merged that another branch points at too, so "
        "which of them was merged can't be told: `feat`, `next`.\n"
        f"{NOTHING_GOING}"
    )
    assert landings.on_forge("refs/heads/dev") == tip
    assert feat.is_dir()
    assert following.is_dir()
    assert shell.git(feat, "rev-parse", "next") == shell.git(feat, "rev-parse", "feat")
    assert landings.ran == []


def test_land_amends_the_gate_s_fixes_into_the_merge_its_parents_and_message_kept(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    feat, dev, shell = landings.feat, landings.dev, landings.shell
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    branch = shell.git(dev, "rev-parse", "feat")
    old = moved_on(landings)
    landings.gate.fixes = {"src/pkg/rooms.py": '"""Rooms, formatted."""\n'}
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    merge = shell.git(dev, "rev-parse", "HEAD")
    assert answer.startswith(
        f"Merged `feat` onto `dev` as {merge}, and moved `dev` here to it: the gate "
        "passed on it, its fixes amended into it.\n"
    )
    assert shell.git(dev, "show", f"{merge}:src/pkg/rooms.py") == (
        '"""Rooms, formatted."""'
    )
    assert shell.git(dev, "rev-parse", f"{merge}^@").splitlines() == [old, branch]
    assert shell.git(dev, "log", "-1", "--format=%B", merge) == CLEANED
    assert landings.on_forge("refs/heads/dev") == merge


def test_land_of_a_branch_that_held_dev_finds_its_pass_and_the_gate_runs_nothing(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    feat, dev, shell = landings.feat, landings.dev, landings.shell
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    moved_on(landings)
    shell.git(feat, "merge", "-q", "--no-edit", "dev")
    branch = shell.git(feat, "rev-parse", "HEAD")
    landings.passing(branch)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    merge = shell.git(dev, "rev-parse", "HEAD")
    assert answer.startswith(
        f"Merged `feat` onto `dev` as {merge}, and moved `dev` here to it: the gate "
        "passed on its files already, so it ran nothing.\n"
    )
    assert landings.gate.ran == []
    assert shell.git(dev, "rev-parse", f"{merge}^{{tree}}") == shell.git(
        dev, "rev-parse", f"{branch}^{{tree}}"
    )
    assert landings.on_forge("refs/heads/dev") == merge


def test_land_of_a_branch_that_conflicts_names_the_files_and_who_resolves_them_changing_nothing(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    feat, dev, shell = landings.feat, landings.dev, landings.shell
    landings.wrote(feat, "README.md", "# Feat's\n")
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    landings.wrote(dev, "README.md", "# Dev's\n")
    landings.wrote(dev, "src/pkg/rooms.py", '"""Chambers."""\n')
    before = shell.git(dev, "rev-parse", "HEAD")
    old = landings.on_forge("refs/heads/dev")
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        landings.launched("claude", name="two", worktree=feat)
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    assert answer == (
        "Not landed: merging `feat` onto `dev` conflicts, in:\n"
        "- README.md\n"
        "- src/pkg/rooms.py\n"
        f"Nothing has changed. Merge `dev` into `feat` in its worktree, {feat} "
        "(launch `two` started there), resolve, run the gate there, and call `land` "
        "again."
    )
    assert shell.git(dev, "rev-parse", "HEAD") == before
    assert landings.on_forge("refs/heads/dev") == old
    assert feat.is_dir()
    assert landings.gate.ran == []


def test_land_where_the_gate_fails_on_the_merge_answers_its_report_changing_nothing(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    feat, dev, shell = landings.feat, landings.dev, landings.shell
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    old = moved_on(landings)
    landings.gate.code = 1
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    assert answer.startswith(
        "Not landed: the gate failed on the merge of `feat` onto `dev`, "
    )
    assert answer.endswith(
        ", which no branch names, and nothing has changed. Merge `dev` into `feat` "
        "in its worktree, fix it there, run the gate, and call `land` again. The "
        "gate's report:\nthe gate's report, ending 1"
    )
    assert shell.git(dev, "rev-parse", "HEAD") == old
    assert landings.on_forge("refs/heads/dev") == old
    assert feat.is_dir()


def test_land_refuses_a_merge_message_or_a_commit_citing_an_item_before_it_merges(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    feat, dev, shell = landings.feat, landings.dev, landings.shell
    (feat / "src/pkg").mkdir(parents=True, exist_ok=True)
    (feat / "src/pkg/rooms.py").write_text('"""Rooms."""\n')
    shell.commit(feat, "fix(rooms): what @1505 found\n\nAs `@270` reads.")
    cited = shell.git(feat, "rev-parse", "--short", "HEAD")
    old = moved_on(landings)
    write_model(
        listed_at(machine.module_data("private", landings.repository)), Withheld()
    )
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp, "Merge: as @1477.2")
    steer = (
        "      steer: on GitHub `@` mentions a user, and the number means nothing "
        "there: say in words what the item was about, or cite the issue it "
        "concerns as `#123`; where you mean the notation itself, write it as code\n"
    )
    assert answer == (
        "Not landed: a message it would publish cites an inbox item's number, "
        "which `Private` refuses at the push, so nothing was merged and nothing "
        "has changed.\n"
        f"  the merge commit's message:1:11 - an inbox item's number, `@1477.2`\n"
        f"{steer}"
        f"  {cited}'s message:1:18 - an inbox item's number, `@1505`\n"
        f"{steer}"
        "Rewrite each, then call `land` again. The merge commit's is the `message` "
        "you give `land`. A commit of the branch, which isn't pushed, is rewritten "
        "with `git commit --amend` where it's the branch's tip, and below it by a "
        'rebase that needs no editor: `GIT_SEQUENCE_EDITOR="sed -i '
        "'1s/^pick/edit/'\" git rebase -i <commit>~`, then `git commit --amend` "
        "and `git rebase --continue`."
    )
    assert shell.git(dev, "rev-parse", "HEAD") == old
    assert landings.on_forge("refs/heads/dev") == old
    assert landings.gate.ran == []
    assert feat.is_dir()


def test_land_merges_a_message_citing_an_item_where_the_list_doesn_t_withhold_them(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    moved_on(landings)
    write_model(
        listed_at(machine.module_data("private", landings.repository)),
        Withheld(numbers=False),
    )
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp, "Merge: as @1505")
    merge = landings.on_forge("refs/heads/dev")
    assert answer.startswith(f"Merged `feat` onto `dev` as {merge}, ")


def test_land_leaves_dev_where_uncommitted_work_is_in_the_way_and_lands_once_it_s_gone(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    feat, dev = landings.feat, landings.dev
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    old = moved_on(landings)
    (dev / "src/pkg/rooms.py").write_text("work not committed\n")
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        mcp = machine.host.launch("one").mcp
        send(machine.host.launch("one").hook, started("claude"))
        refused = merging(landings, mcp)
        (dev / "src/pkg/rooms.py").unlink()
        answer = merging(landings, mcp)
    assert refused.startswith(
        f"Not landed: `dev`'s checkout, {dev}, wasn't fast-forwarded to the merge, "
    )
    assert "(`git merge --ff-only`: error: " in refused
    assert refused.endswith(
        "Nothing else has changed: commit or set aside what's in the way there, and "
        "call `land` again, which finds the gate's pass and runs nothing."
    )
    merge = landings.on_forge("refs/heads/dev")
    assert merge != old
    assert answer.startswith(
        f"Merged `feat` onto `dev` as {merge}, and moved `dev` here to it: the gate "
        "passed on its files already, so it ran nothing.\n"
    )
    assert len(landings.gate.ran) == 1


def test_land_refuses_a_merge_without_its_message_a_message_without_a_branch_and_a_launch_keeping_no_runner(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude", runner=False)
        mcp = machine.host.launch("one").mcp
        send(machine.host.launch("one").hook, started("claude"))
        unsaid, _ = call(mcp, "land", {"branch": "feat", "message": " \n"})
        unmerged, _ = call(mcp, "land", {"message": "feat: rooms"})
        unrun, _ = call(mcp, "land", {"branch": "feat", "message": "feat: rooms"})
    assert unsaid == (
        "Not landed: landing `feat` merges it with a merge commit, which needs its "
        "`message`: what changed and why, how it was tested"
    )
    assert unmerged == (
        "Not landed: without a branch to merge, `dev` lands as it is, making no "
        "merge commit for a `message`: leave it out, or name the branch"
    )
    assert unrun == (
        "Not landed: this launch began before lup kept the project's runner with "
        "it, which the merge runs in your room through: relaunch it, or merge "
        "`feat` into `dev` yourself and call `land` without a branch."
    )
    assert landings.ran == []


def test_land_where_the_room_can_t_merge_says_what_it_said_changing_nothing(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    old = landings.on_forge("refs/heads/dev")
    landings.unmerging = "Error: No such command 'merge'.\n"
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    assert answer == (
        "Not landed: the merge couldn't be made in your room, and nothing has "
        "changed. `lup-dev merge` said:\nError: No such command 'merge'."
    )
    assert landings.shell.git(landings.dev, "rev-parse", "HEAD") == old
    assert landings.on_forge("refs/heads/dev") == old


def test_land_of_a_branch_dev_holds_already_lands_dev_as_it_is(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged()
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        mcp = machine.host.launch("one").mcp
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, mcp)
        again = merging(landings, mcp)
    assert answer.startswith(
        "`feat` is in `dev`'s history already, so nothing was merged: `dev` lands "
        f"as it is.\nLanded {tip} on `dev` at `origin`, which was at {old}.\n"
    )
    assert again == ("Not landed: this repository has no local branch `feat`")
    assert landings.gate.ran == []
    assert landings.on_forge("refs/heads/dev") == tip


def test_land_says_each_defer_comment_the_branch_s_merge_adds_and_removes_where_each_is(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    """A deferral moved to another line is neither added nor removed, and a file that isn't Python is never read for one."""
    feat, dev, shell = landings.feat, landings.dev, landings.shell
    landings.wrote(
        dev,
        "src/pkg/hall.py",
        '"""Hall."""\n\n'
        '# lup: defer(issue=80, why="the hall waits on #80")\n'
        "HALL = 1\n"
        '# lup: defer(when=Released, why="the door waits on a release")\n'
        "DOOR = 2\n",
    )
    shell.git(landings.repository, "push", "-q", "origin", "dev")
    old = landings.on_forge("refs/heads/dev")
    shell.git(feat, "merge", "-q", "--ff-only", "dev")
    landings.wrote(
        feat,
        "src/pkg/hall.py",
        '"""Hall."""\n\n'
        "HALL = 1\n"
        '# lup: defer(when=Released, why="the door waits on a release")\n'
        "DOOR = 2\n",
    )
    landings.wrote(
        feat,
        "src/pkg/rooms.py",
        '"""Rooms."""\n\n'
        '# lup: defer(issue="joy-void-joy/lup-legacy#7", when=Released, why="a '
        'stand-in")\n'
        "ROOMS = 1\n",
    )
    landings.wrote(feat, "docs/rooms.md", '# lup: defer(issue=1, why="prose")\n')
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    merge = landings.on_forge("refs/heads/dev")
    assert answer == (
        f"Merged `feat` onto `dev` as {merge}, and moved `dev` here to it: the gate "
        "passed on it.\n"
        f"Landed {merge} on `dev` at `origin`, which was at {old}.\n"
        "The `# lup: defer` comments `feat` adds and removes, against `dev`:\n"
        "- adds src/pkg/rooms.py:3: `# lup: defer(issue="
        '"joy-void-joy/lup-legacy#7", when=Released, why="a stand-in")`\n'
        "- removes src/pkg/hall.py:3: `# lup: defer(issue=80, why="
        '"the hall waits on #80")`\n'
        "Cleaned up after it:\n"
        f"- removed the worktree {feat}\n"
        "- deleted the local branch `feat`\n"
        f"{NOTHING_GOING}"
    )
    read = {each.path for asked in landings.parser.parsed_asked for each in asked}
    assert read == {Path("src/pkg/hall.py"), Path("src/pkg/rooms.py")}


def test_land_of_dev_as_it_is_says_each_merged_branch_s_defer_comments_then_its_own_commits(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    feat, dev, shell = landings.feat, landings.dev, landings.shell
    old = landings.on_forge("refs/heads/dev")
    landings.wrote(
        feat,
        "src/pkg/rooms.py",
        '"""Rooms."""\n\n# lup: defer(issue=12, why="rooms wait")\nROOMS = 1\n',
    )
    shell.git(dev, "merge", "-q", "--no-ff", "--no-edit", "feat")
    landings.wrote(
        dev,
        "src/pkg/hall.py",
        '"""Hall."""\n\n# lup: defer(issue=13, why="the hall waits")\nHALL = 1\n',
    )
    tip = shell.git(dev, "rev-parse", "HEAD")
    landings.passing(tip)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer, error = call(machine.host.launch("one").mcp, "land", {})
    assert not error
    assert answer == (
        f"Landed {tip} on `dev` at `origin`, which was at {old}.\n"
        "The `# lup: defer` comments `feat` adds and removes, against `dev`:\n"
        '- adds src/pkg/rooms.py:3: `# lup: defer(issue=12, why="rooms wait")`\n'
        "The `# lup: defer` comments `dev`'s own commits add and remove, against "
        "`dev` on `origin`:\n"
        '- adds src/pkg/hall.py:3: `# lup: defer(issue=13, why="the hall waits")`\n'
        "Cleaned up after it:\n"
        f"- removed the worktree {feat}\n"
        "- deleted the local branch `feat`\n"
        f"{NOTHING_GOING}"
    )


class Unreadable(Parser):
    """The engine's reading of a file's parse, failing as it does on a host with no Node, or no engine built, once it has answered `answering` requests."""

    def __init__(self, answering: int = 0) -> None:
        self.answering = answering

    @override
    def parsed(self, root: Path, sources: list[Source]) -> list[FileReport]:
        if self.answering > 0:
            self.answering -= 1
            return [FileReport(path=each.path) for each in sources]
        message = "the engine's `parse` failed: node: not found"
        raise EngineError(message)


def test_land_where_the_defer_comments_can_t_be_read_says_so_and_lands_all_the_same(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=Unreadable(1)
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    merge = landings.on_forge("refs/heads/dev")
    assert merge is not None
    assert (
        f"Landed {merge} on `dev` at `origin`, which was at "
        f"{landings.shell.git(landings.dev, 'rev-parse', f'{merge}^1')}.\n"
        "lup couldn't read the `# lup: defer` comments it lands: the engine's `parse` "
        "failed: node: not found\n"
        "Cleaned up after it:\n"
    ) in answer


def test_land_where_git_can_t_read_the_defer_comments_says_so_having_landed(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """They're read after the push, so a failure there mustn't answer `Not landed`."""

    def unreadable(*_: object) -> None:
        message = "what the repository's store holds as abc isn't that commit"
        raise GitError(message)

    monkeypatch.setattr(landing_module, "deferred", unreadable)
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer = merging(landings, machine.host.launch("one").mcp)
    merge = landings.on_forge("refs/heads/dev")
    assert f"Landed {merge} on `dev` at `origin`" in answer
    assert (
        "lup couldn't read the `# lup: defer` comments it lands: what the "
        "repository's store holds as abc isn't that commit\n"
    ) in answer


def test_land_invites_each_conversation_still_going_that_worked_on_a_branch_it_landed_once_where_it_hasn_t_said(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    tmp_path: Path,
) -> None:
    """Told beside their next call, the conversation landing's beside the landing's own result: never one that ended, which nothing reaches, nor one that said how it felt already, nor one a landing invited before."""
    feat, records = landings.feat, Subagents(tmp_path)
    more = landings.branched("more")
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    landings.wrote(more, "src/pkg/more.py", '"""More."""\n')
    worked = Worked(
        repository=landings.repository,
        worktrees=[landings.dev, feat, more],
        started={"": [landings.dev, feat]},
        wrote={"a1": [feat, more], "a2": [feat], "a3": [feat]},
    )
    SessionIndex(layout=machine).write("s1", worked)
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        landings.launched("claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, started("claude"))
        for agent, call_id in [("a1", "t1"), ("a2", "t2"), ("a3", "t3")]:
            send(hook, records.spawn(call_id, name=f"worker-{agent}"))
            records.recorded(agent, "general-purpose", call_id, name=f"worker-{agent}")
            send(hook, records.call(agent, "general-purpose", f"{agent}-c1"))
        send(hook, records.ended("a2", "general-purpose", "Handed back."))
        records.lup(
            (hook, mcp),
            "how_it_felt",
            {"text": "Calm work."},
            "a3",
            "general-purpose",
        )
        send(hook, lup_call("land", {}, "l1"))
        merging(landings, mcp)
        landed = context(send(hook, lup_finished("land", "l1")))
        ending = send(hook, claude("Stop", stop_hook_active=False))
        worker = context(send(hook, records.call("a1", "general-purpose", "a1-c2")))
        quiet = send(hook, records.call("a3", "general-purpose", "a3-c2"))
        again = send(hook, records.call("a1", "general-purpose", "a1-c3"))
        landings.shell.git(landings.dev, "merge", "-q", "--no-ff", "--no-edit", "more")
        landings.passing(landings.shell.git(landings.dev, "rev-parse", "HEAD"))
        _, error = call(mcp, "land", {})
        later = send(hook, records.call("a1", "general-purpose", "a1-c4"))
    # The landing's own result tells the landing conversation what waits too.
    assert landed.split("\n\n")[0] == landed_felt(["feat"])
    assert ending == ""
    assert worker == landed_felt(["feat"])
    assert quiet == ""
    assert again == ""
    assert not error
    assert later == ""


def handed_back(landings: Landings, records: Subagents, machine: Layout) -> str:
    """Have subagent `a1` of launch `one` work apart in `feat`'s worktree, the one lup gave them, and end their turn; then land `feat` from the session's own conversation: the landing's answer."""
    SessionIndex(layout=machine).write(
        "s1",
        Worked(
            repository=landings.repository,
            worktrees=[landings.dev, landings.feat],
            started={"": [landings.dev]},
            apart={"a1": landings.feat},
        ),
    )
    landings.launched("claude")
    hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
    send(hook, started("claude"))
    send(hook, records.spawn("t1"))
    records.recorded("a1", "general-purpose", "t1")
    send(hook, records.call("a1", "general-purpose", "a1-c1"))
    _, error = records.lup(
        (hook, mcp), "rename", {"name": "worker"}, "a1", "general-purpose"
    )
    assert not error
    send(hook, records.ended("a1", "general-purpose", "Handed back."))
    return merging(landings, mcp)


def landed_later(landings: Landings, machine: Layout) -> str:
    """End launch `one`, then land `more`, a branch of its own, from launch `two`: the landing's answer."""
    more = landings.branched("more")
    landings.wrote(more, "src/pkg/more.py", '"""More."""\n')
    HostClient(
        layout=machine.host, clock=landings.clock, starter=Unstarted()
    ).unregister("one")
    landings.launched("claude", name="two")
    send(machine.host.launch("two").hook, started("claude"))
    answer, error = call(
        machine.host.launch("two").mcp, "land", {"branch": "more", "message": MESSAGE}
    )
    assert not error, answer
    return answer


def test_land_detaches_the_worktree_a_subagent_who_may_be_resumed_started_in_and_a_landing_after_their_launch_ends_removes_it(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    tmp_path: Path,
) -> None:
    """Resumed, their shell starts where it did, their scratch there as they left it, and they're told why `HEAD` is detached."""
    feat, records = landings.feat, Subagents(tmp_path)
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    (landings.repository / "info").mkdir(exist_ok=True)
    (landings.repository / "info" / "exclude").write_text("tmp/\n")
    tip = landings.shell.git(feat, "rev-parse", "HEAD")
    (feat / "tmp").mkdir()
    (feat / "tmp" / "probe.py").write_text("scratch git ignores")
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        answer = handed_back(landings, records, machine)
        hook = machine.host.launch("one").hook
        resumed = context(send(hook, records.call("a1", "general-purpose", "a1-c2")))
        branch = landings.shell.git(feat, "branch", "--show-current")
        head = landings.shell.git(feat, "rev-parse", "HEAD")
        probe = (feat / "tmp" / "probe.py").read_text()
        later = landed_later(landings, machine)
    assert (
        f"- detached the worktree {feat}, where `one/worker` started and may be "
        "resumed: a landing after their launch ends removes it\n"
        "- deleted the local branch `feat`\n"
    ) in answer
    assert resumed == detached("feat", feat, "dev", "dev")
    assert (branch, head, probe) == ("", tip, "scratch git ignores")
    assert landings.shell.git(landings.repository, "branch", "--list", "feat") == ""
    assert (
        f"- removed the worktree {feat}, kept for `worker` until their launch ended\n"
    ) in later
    assert not feat.exists()


def test_land_leaves_a_worktree_kept_for_a_subagent_whose_launch_ended_where_its_commit_is_on_no_branch(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    tmp_path: Path,
) -> None:
    """Resumed, they committed on the detached `HEAD`, and ended without putting it on a branch: removing the worktree would lose it."""
    feat, records = landings.feat, Subagents(tmp_path)
    landings.wrote(feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    with inboxed(
        machine, clock, notices, said, rooms=landings.room, parser=landings.parser
    ):
        handed_back(landings, records, machine)
        landings.wrote(feat, "src/pkg/stray.py", '"""Stray."""\n')
        stray = landings.shell.git(feat, "rev-parse", "HEAD")
        later = landed_later(landings, machine)
    assert (
        f"- the worktree {feat}: kept for `worker`, whose launch has ended, at "
        f"{stray}, which what landed doesn't hold\n"
    ) in later
    assert (feat / "src/pkg/stray.py").is_file()


def test_land_ends_on_the_subagents_lup_hasn_t_heard_end_and_the_branches_off_dev(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    landings.wrote(landings.feat, "src/pkg/rooms.py", '"""Rooms."""\n')
    idea = landings.branched("idea")
    landings.wrote(idea, "src/pkg/idea.py", '"""Idea."""\n')
    landings.shell.git(landings.repository, "branch", "draft", "idea")
    with inboxed(
        machine,
        clock,
        notices,
        said,
        spawns=Unguided(),
        rooms=landings.room,
        parser=landings.parser,
    ):
        landings.launched("claude")
        hook = machine.host.launch("one").hook
        send(hook, started("claude"))
        send(hook, bash("b1", agent_id="a1", agent_type="general-purpose"))
        send(hook, bash("b2", agent_id="a2", agent_type="general-purpose"))
        send(hook, claude("SubagentStop", agent_id="a2", agent_type="general-purpose"))
        answer = merging(landings, machine.host.launch("one").mcp)
    assert answer.endswith(
        "Still running or waiting to land:\n"
        "- `one/sub-a1`, a subagent of yours lup hasn't heard end\n"
        "- `draft`, checked out nowhere\n"
        f"- `idea`, checked out in {idea}, where no conversation lup knows of works"
    )


def test_a_held_file_declined_after_a_merge_leaves_it_on_dev_here_and_says_so(
    landings: Landings,
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
) -> None:
    rooms, path = '"""Rooms."""\n', "src/pkg/rooms.py"
    landings.wrote(landings.feat, path, rooms)
    old = landings.on_forge("refs/heads/dev")
    session = lander(landings, "claude")
    with (
        inboxed(
            machine, clock, notices, said, rooms=landings.room, parser=landings.parser
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        landings.launched("claude")
        mcp = machine.host.launch("one").mcp
        send(machine.host.launch("one").hook, started("claude"))
        landings.flag(path, rooms, session)
        landing = pool.submit(merging, landings, mcp)
        assert delivery.holding.wait(timeout=60)
        place = drawer(machine, clock, session, "feat")
        answering(machine, clock, session, place, path, decline=True)
        answer = landing.result(timeout=60)
    merge = landings.shell.git(landings.dev, "rev-parse", "HEAD")
    assert f"- `{path}`: declined\n" in answer
    assert answer.endswith(
        f"`dev` here holds the merge, {merge}, which `origin`'s doesn't yet: the "
        "next `land` lands it."
    )
    assert landings.on_forge("refs/heads/dev") == old
    assert merge != old


def test_lup_s_tools_say_which_may_be_sent_again_across_a_restart(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    async def listed(path: Path) -> dict[str, ToolAnnotations | None]:
        async with Client(bridged(path), mode="legacy") as connected:
            tools = (await connected.list_tools()).tools
        return {tool.name: tool.annotations for tool in tools}

    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        tools = asyncio.run(listed(machine.host.launch("one").mcp))
    marks = {
        name: (each.read_only_hint, each.idempotent_hint)
        for name, each in tools.items()
        if each is not None
    }
    assert set(marks) == set(tools)
    assert {name for name, (reads, _) in marks.items() if reads} == {"inbox", "judged"}
    assert {name for name, (_, again) in marks.items() if again} == {
        "ask",
        "wait_inbox",
        "land",
    }
    github = {
        spec.name: (spec.reads, spec.idempotent) for spec in module_tools(GitHubServing)
    }
    assert {name for name, (reads, _) in github.items() if reads} == {
        "read_issue",
        "find_issues",
    }
    assert not any(again for _, again in github.values())


def test_judged_and_the_review_read_a_hold_and_an_item_s_files_a_copy_before_wrote(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """A copy before found `signature-changed`, which the holds and the files beside items it wrote keep: a value a stored model once accepted stays read, since `judged` reads every store's holds whole and the review an item's files (`ApiKind`)."""
    worktree = tmp_path / "w"
    worktree.mkdir()
    repository = tmp_path / ".git"
    core = Path("src/core.py")
    reading = Reading(
        role="production",
        asks=[
            Ask(
                name="public-api",
                taken="flagged",
                line=1,
                api=ApiChanged(kind="signature-changed", name="f"),
            )
        ],
    )
    verdict = Verdict(
        key="v1",
        time=clock.now(),
        session="s1",
        runtime="claude",
        tool="Write",
        worktree=worktree,
        path=core,
        role="production",
        outcome="hold",
        reasons=["whole-file"],
    )
    holds = Holds(layout=machine.store(worktree))
    hold = holds.put(
        Hold(
            key=holds.unused(),
            worktree=worktree,
            session="s1",
            created=clock.now(),
            files=[
                HeldFile(
                    path=core,
                    role="production",
                    blob="abc",
                    reasons=["whole-file"],
                    asks=["src/core.py is rewritten whole"],
                    reading=reading,
                )
            ],
            diff="-def f(): ...\n+def f(x): ...\n",
            verdicts=[verdict],
        )
    )
    VerdictLog(path=machine.verdicts(repository)).append([verdict])
    whole = ChangedFile(
        path=core,
        before=Text(text="def f(): ...\n"),
        after=Text(text="def f(x): ...\n"),
        reading=reading,
    )
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        InboxAnnouncing(layout=machine.host, clock=clock).announced(
            hold, "claude", repository, [whole]
        )
        [item] = delivery.inbox.waiting(Operator())
        listed, error = call(machine.host.launch("one").mcp, "judged", {})
        files = client(machine.host, clock).ask(ShowFiles(number=item.number), Files)
    assert not error, listed
    assert f"{worktree / core}  Write  hold (whole-file), no answer yet" in listed
    assert f"  {worktree / core}: whole-file" in listed
    assert files.files == [whole]


def test_a_tool_of_lup_s_that_fails_answers_its_failure_and_the_service_says_the_traceback(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """Left to `mcp`, a pydantic `ValidationError` a tool raises reaches the session as JSON-RPC's bare "Invalid request parameters", logged nowhere (`LaunchTools.answered`)."""
    log = machine.verdicts(tmp_path / ".git")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text('{"key": "v1", "time": "yesterday"}\n')
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        text, error = call(machine.host.launch("one").mcp, "judged", {})
    assert error
    assert text.startswith(
        "`judged` failed, which is lup's fault, not the call's; the host service's "
        "output has the traceback: "
    )
    assert "validation error" in text
    assert "Verdict" in text
    [told] = [line for line in said if line.startswith("one: `judged` failed:\n")]
    assert "Traceback (most recent call last):" in told
    assert "ValidationError" in told


def test_the_github_module_s_tools_answer_through_the_server_with_and_without_arguments(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    *,
    tmp_path: Path,
    in_process: type[InProcess],
) -> None:
    """Each call reaches the module's tool through lup's server and the launch's modules, which validate it and refuse what the launch's limits leave out, before anything reaches GitHub."""
    modules = in_process(resolved=resolve(Project()), layout=machine)
    with inboxed(machine, clock, notices, said, modules=modules):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        mcp = machine.host.launch("one").mcp
        bare = call(mcp, "read_issue", {})
        numbered = call(mcp, "read_issue", {"number": 1})
        searched = call(mcp, "find_issues", {"query": "is:open"})
        filed = call(mcp, "file_issue", {"title": "A bug", "body": "It bites."})
    refused = (
        "`{}` didn't run: the project's declaration doesn't allow `{}` with the "
        "operator's credentials (`Core.credentials`), and allowing it is the "
        "operator's call"
    )
    assert bare[1]
    assert bare[0].startswith(
        "`read_issue` refused the call: 1 validation error for Numbered\nnumber\n"
    )
    assert numbered == (refused.format("read_issue", "read-issues"), True)
    assert searched == (refused.format("find_issues", "read-issues"), True)
    assert filed == (refused.format("file_issue", "file-issue"), True)


def exchanged(
    machine: Layout,
    clock: FakeClock,
    tmp_path: Path,
    records: Subagents,
    delivery: Delivery,
) -> Path:
    """Make an exchange in a launch named `w`, through `delivery`, and return its tool socket: session `s0`'s note at 12:00, landing in no thread; then at 13:00 session `s1`'s note, their question, and their subagent `explore-auth`'s note; at 14:00 the operator's answer, their review commenting on a passage of the note with a message, both told to `s1` at a call, its turn's end answering them, citing the comment, and the operator's reply to it, and the subagent's end: nine items, in that order."""
    launched(machine, clock, tmp_path / "w", "one", "claude")
    hook = machine.host.launch("one").hook
    mcp = machine.host.launch("one").mcp
    send(hook, claude("SessionStart", source="startup", session_id="s0"))
    call(mcp, "note", {"remark": "An earlier session's note."})
    clock.sleep(3600)
    send(hook, claude("SessionStart", source="startup"))
    call(mcp, "note", {"remark": "I assumed UTF-8.\n\nThe parser reads twenty kinds."})
    noted = newest(delivery)
    asking: dict[str, JsonValue] = {
        "decision": "One model per kind?",
        "lean": "Yes, each validates.",
    }
    call(mcp, "ask", {"question": "Which parser?", "decisions": [asking]})
    question = newest(delivery)
    send(hook, records.spawn("t1", name="explore-auth"))
    records.recorded("a1", "Explore", "t1", name="explore-auth")
    send(hook, records.call("a1", "Explore", "c1"))
    records.lup((hook, mcp), "note", {"remark": "Found the token."}, "a1", "Explore")
    clock.sleep(3600)
    inbox("answer", str(question), "--leaning", "1", "--comment", "Go.")
    passage = "The parser reads twenty kinds."
    comment = Comment(
        item=noted,
        quote=Quote(text=passage, start=18, end=18 + len(passage)),
        text="Why twenty?",
    )
    own = Conversation(
        repository=tmp_path / "w" / ".git", runtime="claude", session="s1"
    )
    drafting(
        machine,
        clock,
        Draft(comments=[comment], letters=[Letter(to=own, text="Carry on.")]),
    )
    [review] = sending(machine, clock)
    send(hook, bash("b1"))
    ending = claude(
        "Stop",
        stop_hook_active=False,
        last_assistant_message=(
            f"The grammar has twenty, @{review.number}.1[Why twenty]. Done for now."
        ),
    )
    send(hook, ending)
    end = newest(delivery)
    inbox("answer", str(end), "--comment", "Thanks, rest.")
    send(hook, records.ended("a1", "Explore", "The token is in auth.py."))
    return mcp


def test_inbox_reads_one_conversations_exchange_by_its_name_or_its_id_a_line_each(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        mcp = exchanged(machine, clock, tmp_path, Subagents(tmp_path), delivery)
        # The items `exchanged` makes, in the order its docstring tells them.
        made = numbers(delivery)
        s0, noted, question, found, answer, review, end, reply, ended = made
        threads = delivery.inbox.ledger.every(Thread)

        def reading(**arguments: JsonValue) -> str:
            text, error = call(mcp, "inbox", arguments)
            assert not error, text
            return text

        every = reading(conversation="w", every=True)
        waiting = reading(conversation="w")
        below = reading(conversation="s1", every=True, subagents=True)
        kinds = reading(conversation="s1", every=True, kinds=["question", "answer"])
        earlier = reading(conversation="s0", every=True)
        path = reading(conversation="w/explore-auth", every=True)
        nobody = reading(conversation="nobody")
    # Session `s0`'s note lands in no thread, nor does anything after it.
    assert threads == []
    several = (
        "`w` names 2 conversations; this reads the one last heard, claude session "
        "s1, at 2026-10-01 14:00. The others, which `conversation` reads by id: "
        "claude session s0, last heard 2026-10-01 12:00."
    )
    at, then = "2026-10-01 13:00", "2026-10-01 14:00"
    told = f"told at {then} (call)"
    lines = {
        noted: (
            f"@{noted}  {at}  a note from you to the operator, done at {then}: I "
            "assumed UTF-8."
        ),
        question: (
            f"@{question}  {at}  a question from you to the operator, answered at "
            f"{then}, @{answer}: Which parser?"
        ),
        found: (
            f"@{found}  {at}  a note from `w/explore-auth` to the operator, waiting: "
            "Found the token."
        ),
        answer: f"@{answer}  {then}  an answer from the operator to you, {told}: Go.",
        review: (
            f"@{review}  {then}  a review from the operator to you, {told}: Carry on."
        ),
        end: (
            f"@{end}  {then}  the end of a turn from you to the operator, done at "
            f"{then}: The grammar has twenty, @{review}.1[Why twenty]. Done for now."
        ),
        reply: (
            f"@{reply}  {then}  a note from the operator to you, waiting: Thanks, rest."
        ),
        ended: (
            f"@{ended}  {then}  the end of a subagent's turn from `w/explore-auth` "
            "to you, waiting: They ended their turn. Their last message reaches you "
            "from your runtime."
        ),
    }
    assert every.splitlines() == [
        several,
        "The exchange of `w` (claude session s1): every item, oldest first.",
        *(lines[each] for each in [noted, question, answer, review, end, reply, ended]),
    ]
    assert waiting.splitlines() == [
        several,
        "The exchange of `w` (claude session s1): what still waits, oldest first.",
        lines[reply],
        lines[ended],
        "Not listed: 5 items no longer waiting, which `every` lists.",
    ]
    assert below.splitlines() == [
        (
            "The exchange of `w` (claude session s1) and their 1 subagent: every "
            "item, oldest first."
        ),
        *(
            lines[each]
            for each in [noted, question, found, answer, review, end, reply, ended]
        ),
    ]
    assert kinds.splitlines()[1:] == [lines[question], lines[answer]]
    assert earlier.splitlines() == [
        "The exchange of `w` (claude session s0): every item, oldest first.",
        (
            f"@{s0}  2026-10-01 12:00  a note from `w` (claude session s0) to the "
            "operator, waiting: An earlier session's note."
        ),
    ]
    assert path.splitlines() == [
        (
            "The exchange of `w/explore-auth` (subagent a1 of claude session s1): "
            "every item, oldest first."
        ),
        lines[found],
        lines[ended],
    ]
    assert nobody == (
        "No conversation about this repository is `nobody`: `conversation` takes "
        "a session's name, a subagent's path or their own name, or the runtime's id "
        "for either, or the id's start, as `inbox` lines name them."
    )


def test_inbox_reads_an_exchange_whole_the_operators_words_under_what_they_answer(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        mcp = exchanged(machine, clock, tmp_path, Subagents(tmp_path), delivery)
        # The items `exchanged` makes, in the order its docstring tells them.
        _, noted, question, _, answer, review, end, reply, ended = numbers(delivery)

        def reading(**arguments: JsonValue) -> str:
            text, error = call(mcp, "inbox", arguments)
            assert not error, text
            return text

        whole = reading(conversation="s1", every=True, whole=True)
        latest = reading(conversation="s1", every=True, whole=True, limit=1)
    at, then = "2026-10-01 13:00", "2026-10-01 14:00"
    told = f"told at {then} (call)"
    assert whole == "\n".join(
        [
            "The exchange of `w` (claude session s1): every item, oldest first.",
            f"@{noted}  {at}  a note from you to the operator, done at {then}:",
            f'<item item="{noted}" kind="note" from="w (claude session s1)">',
            "I assumed UTF-8.",
            "",
            "The parser reads twenty kinds.",
            f'<review item="{review}" from="operator" made="{then}">',
            f'<quote part="{noted}.2">The parser reads twenty kinds.</quote>',
            f'<reply id="{review}.1">Why twenty?</reply>',
            "</review>",
            "</item>",
            "",
            (
                f"@{question}  {at}  a question from you to the operator, answered "
                f"at {then}, @{answer}:"
            ),
            f'<item item="{question}" kind="question" from="w (claude session s1)">',
            "Which parser?",
            "1. One model per kind?",
            "   lean: Yes, each validates.",
            f'<answer item="{answer}" from="operator" made="{then}">',
            (
                '<decision number="1" lean="Yes, each validates." verdict="leaning: '
                f'they go with the lean" id="{answer}.1">One model per kind?'
                "</decision>"
            ),
            f'<comment id="{answer}.2">Go.</comment>',
            "</answer>",
            "</item>",
            "",
            f"@{answer}  {then}  an answer from the operator to you, {told}:",
            (
                f'<answer item="{answer}" from="operator" question="{question}">What '
                f"it says on @{question} is told under it.</answer>"
            ),
            "",
            f"@{review}  {then}  a review from the operator to you, {told}:",
            f'<review item="{review}" from="operator" covers="{noted}">',
            f'<message id="{review}.2">Carry on.</message>',
            f"What it says on @{noted} is told under it.",
            "</review>",
            "",
            (
                f"@{end}  {then}  the end of a turn from you to the operator, done at "
                f"{then}:"
            ),
            (
                f'<item item="{end}" kind="turn\'s end" from="w (claude session s1)" '
                f'answers="{answer} {review}">'
            ),
            f"The grammar has twenty, @{review}.1[Why twenty]. Done for now.",
            f'<message item="{reply}" from="operator" made="{then}">',
            f'<comment id="{reply}.1">Thanks, rest.</comment>',
            "</message>",
            "</item>",
            "",
            f"@{reply}  {then}  a note from the operator to you, waiting:",
            (
                f'<message item="{reply}" from="operator" kind="note">What it says '
                f"on @{end} is told under it.</message>"
            ),
            "",
            (
                f"@{ended}  {then}  the end of a subagent's turn from "
                "`w/explore-auth` to you, waiting:"
            ),
            (
                f'<item item="{ended}" kind="ended" from="w/explore-auth">They ended '
                "their turn. Their last message reaches you from your runtime.</item>"
            ),
        ]
    )
    assert latest.split("\n\n")[-1] == (
        'Not listed: 2 earlier items, which `until` "2026-10-01T14:00:00+00:00" '
        "reads; a `limit` of 7 lists them all."
    )
    assert f'<review item="{review}" from="operator" covers="{noted}">' in latest
    assert f'<on item="{noted}" kind="note">' in latest


def test_lup_dev_inbox_narrows_the_operators_own_exchange_as_the_tool_reads(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        exchanged(machine, clock, tmp_path, Subagents(tmp_path), delivery)
        # The items `exchanged` makes, in the order its docstring tells them.
        s0, _, question, found, answer, review, end, _, _ = numbers(delivery)
        plain = inbox()
        waiting = inbox("--conversation", "w")
        every = inbox("--every")
        questions = inbox("--kind", "question", "--every")
        whole = inbox("--conversation", "s1", "--whole", "--every", "--limit", "2")
        unknown = runner.invoke(cli.app, ["inbox", "--kind", "nonsense"])
    assert [line.split()[0] for line in plain.splitlines()] == [
        cited(s0),
        cited(found),
    ]
    assert waiting.splitlines() == [
        (
            "`w` names 2 conversations; this reads the one last heard, claude "
            "session s1, at 2026-10-01 14:00. The others, which `--conversation` "
            "reads by id: claude session s0, last heard 2026-10-01 12:00."
        ),
        "The exchange of `w` (claude session s1): what still waits, oldest first.",
        "Nothing waits for you.",
        "Not listed: 6 items not waiting for you, which `--every` lists.",
    ]
    s0, s1 = "`w` (claude session s0)", "`w` (claude session s1)"
    sub = "`w/explore-auth`"
    assert [line.partition("  2026-10-01 ")[2] for line in every.splitlines()] == [
        f"12:00  a note from {s0} to you, waiting: An earlier session's note.",
        f"13:00  a note from {s1} to you, done at 2026-10-01 14:00: I assumed UTF-8.",
        (
            f"13:00  a question from {s1} to you, answered at 2026-10-01 14:00, "
            f"@{answer}: Which parser?"
        ),
        f"13:00  a note from {sub} to you, waiting: Found the token.",
        (f"14:00  an answer from you to {s1}, told at 2026-10-01 14:00 (call): Go."),
        (
            f"14:00  a review from you to {s1}, told at 2026-10-01 14:00 (call): "
            "Carry on."
        ),
        (
            f"14:00  the end of a turn from {s1} to you, done at 2026-10-01 14:00: "
            f"The grammar has twenty, @{review}.1[Why twenty]. Done for now."
        ),
        f"14:00  a note from you to {s1}, waiting: Thanks, rest.",
    ]
    assert [line.split()[0] for line in questions.splitlines() if line] == [
        cited(question)
    ]
    assert (
        f'<item item="{end}" kind="turn\'s end" from="w (claude session s1)" '
        f'answers="{answer} {review}">'
    ) in whole
    assert "a `--limit` of 6 lists them all." in whole
    assert unknown.exit_code == 2
    assert "--kind takes one of turn's end, note, problem" in unknown.output


def test_lup_dev_transcripts_show_says_how_much_of_the_exchange_lups_inbox_holds(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
    *,
    shell: Shell,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = tmp_path / "w" / ".git"
    kept = Layout.of(LupDevSettings()).module_data(Transcripts.name, common)
    folder = kept / "claude" / "projects" / "-repo"
    folder.mkdir(parents=True)
    typed = {
        "timestamp": "2026-10-01T12:00:00Z",
        "type": "user",
        "origin": {"kind": "human"},
        "cwd": "/w",
        "message": {"role": "user", "content": "Read the parser."},
    }
    for session in ["s1", "s7"]:
        (folder / f"{session}.jsonl").write_text(json.dumps(typed) + "\n")
    modules = RepositoryModules(
        repository=common,
        resolved=resolve(Project()),
        recorded=cli.recorded(),
        layout=Layout.of(LupDevSettings()),
        exchanges=HostExchanges(repository=common, layout=machine.host, clock=clock),
        marks=StoredMarks(store=MarkStore.kept_in(Layout.of(LupDevSettings()))),
    )
    app = commanding.commands(
        "transcripts", modules.resolved.served, modules.made, OperatorAsker
    )
    with inboxed(machine, clock, notices, said) as delivery:
        exchanged(machine, clock, tmp_path, Subagents(tmp_path), delivery)
        shown = runner.invoke(app, ["show", "s1"])
        unheard = runner.invoke(app, ["show", "s7"])
    unserved = runner.invoke(app, ["show", "s1"])
    assert shown.exit_code == 0, shown.output
    assert shown.output.endswith(
        "    Read the parser.\n\nIts exchange with you through lup, which this "
        "leaves out, is 7 items in lup's inbox: `lup-dev inbox --conversation s1 "
        "--every --whole` reads it.\n"
    )
    assert unheard.output.endswith("    Read the parser.\n")
    words = shown.output.partition("\n\nIts exchange")[0]
    assert unserved.output.startswith(f"{words}\n\nlup's inbox wasn't asked")


def test_a_conversation_is_named_by_its_path_its_ids_beside_it_only_where_another_shares_it(
    tmp_path: Path, clock: FakeClock
) -> None:
    earlier = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    later = earlier.model_copy(update={"session": "s2"})
    parser = later.model_copy(update={"agent": "a1"})
    unnamed = later.model_copy(update={"session": "s3"})
    elsewhere = earlier.model_copy(update={"repository": tmp_path / "other.git"})
    places = {
        each.key(): Whereabouts(
            conversation=each,
            launch="one",
            worktree=tmp_path,
            since=clock.now(),
            parent=None if each.agent is None else later,
            name="parser" if each.agent else None,
        )
        for each in [earlier, later, parser, unnamed]
    }
    roster = Roster(names={"s1": "w", "s2": "w", "s4": "v"}, places=places, items={})
    # Two sessions of the repository share `w`, so each is named with their ids;
    # the subagent's path is theirs alone; the session lup kept no name for is their ids.
    assert [roster.called(each) for each in [earlier, later, parser, unnamed]] == [
        "w (claude session s1)",
        "w (claude session s2)",
        "w/parser",
        "claude session s3",
    ]
    assert roster.who(parser) == "`w/parser`"
    assert roster.who(Operator()) == "the operator"
    assert [roster.handle(each) for each in [earlier, parser]] == ["s1", "w/parser"]
    # Another repository's conversations share nothing with this one's; a session
    # starting, which lup hasn't heard yet, is counted where it's given.
    starting = elsewhere.model_copy(update={"session": "s4"})
    named = elsewhere.model_copy(update={"session": "s5"})
    alone = Roster(names={"s1": "w", "s4": "w"}, places=places, items={})
    assert alone.called(elsewhere) == "w"
    assert alone.who(elsewhere, [starting]) == "`w` (claude session s1)"
    assert alone.handle(elsewhere, [starting]) == "s1"
    assert alone.handle(named) == "s5"


def test_the_listing_names_an_agent_no_launch_names_by_its_path(
    tmp_path: Path, clock: FakeClock
) -> None:
    """The dashboard names an agent by the launches it lists, which name a launch's latest session alone: an earlier session's, and an ended one's, come by the listing's paths."""
    layout = Layout(state=tmp_path / "state", runtime=tmp_path / "run", data=tmp_path)
    inbox = inbox_opened(layout)
    names = Names(path=layout.host.names)
    names.keep("s1", "w")
    names.keep("s2", "w")
    earlier = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    later = earlier.model_copy(update={"session": "s2"})
    parser = later.model_copy(update={"agent": "a1"})
    for each in [earlier, later, parser]:
        inbox.placed(
            Whereabouts(
                conversation=each,
                launch="one",
                worktree=tmp_path,
                since=clock.now(),
                parent=None if each.agent is None else later,
                name="parser" if each.agent else None,
                ended=clock.now() if each == earlier else None,
            )
        )
    earlier_note, parser_note = (
        inbox.made(
            Message(kind="note", text="Seen."),
            sender,
            Operator(),
            tmp_path,
            clock.now(),
        ).number
        for sender in [earlier, parser]
    )
    delivery = Delivery.model_construct(inbox=inbox, clock=clock, layout=layout.host)
    listed = asyncio.run(Listing(delivery=delivery).answer(ListInbox()))
    assert isinstance(listed, Items)
    assert listed.paths == [
        Pathed(conversation=earlier, path="w", alike=True),
        Pathed(conversation=parser, path="w/parser"),
    ]
    assert [each.said() for each in listed.paths] == [
        "w (claude session s1)",
        "w/parser",
    ]
    assert [cli.line(each, listed.paths).split(" in ")[0] for each in listed.items] == [
        f"{cited(earlier_note):>5}  2026-10-01 12:00  a note from `w` (claude session s1)",
        f"{cited(parser_note):>5}  2026-10-01 12:00  a note from `w/parser`",
    ]


def test_a_subagent_is_named_as_its_end_was_told_where_its_whereabouts_keep_no_name(
    tmp_path: Path, clock: FakeClock
) -> None:
    layout = Layout(state=tmp_path / "state", runtime=tmp_path / "run", data=tmp_path)
    inbox = inbox_opened(layout)
    Names(path=layout.host.names).keep("s1", "w")
    main = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    parser = main.model_copy(update={"agent": "a1"})
    lexer = main.model_copy(update={"agent": "a2"})
    at = clock.now()
    for each, parent in [(parser, main), (lexer, parser)]:
        inbox.placed(
            Whereabouts(
                conversation=each,
                launch="one",
                worktree=tmp_path,
                since=at,
                parent=parent,
            )
        )
    noted = inbox.made(
        Message(kind="note", text="Lexing."), lexer, Operator(), tmp_path, at
    )
    inbox.made(Ended(name="parser", said="Parsed."), parser, main, tmp_path, at)
    reader = Reader(
        delivery=Delivery.model_construct(inbox=inbox, clock=clock, layout=layout.host),
        reader=Operator(),
    )
    items = inbox.about(tmp_path / ".git")
    lexing = reader.read(items, Narrowing(conversation="w/parser/a2", every=True))
    parsing = reader.read(
        items, Narrowing(conversation="parser", every=True, subagents=True)
    )
    assert lexing.text.splitlines() == [
        (
            "The exchange of `w/parser/a2` (subagent a2 of claude session s1): every "
            "item, oldest first."
        ),
        (
            f"@{noted.number}  2026-10-01 12:00  a note from `w/parser/a2` to you, "
            "waiting: Lexing."
        ),
    ]
    assert parsing.found == 2
    assert parsing.text.splitlines()[0] == (
        "The exchange of `w/parser` (subagent a1 of claude session s1) and their "
        "1 subagent: every item, oldest first."
    )


def test_each_conversations_flagged_writes_are_one_entry_wherever_the_inbox_is_listed(
    tmp_path: Path, clock: FakeClock
) -> None:
    layout = Layout(state=tmp_path / "state", runtime=tmp_path / "run", data=tmp_path)
    inbox = inbox_opened(layout)
    main = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    parser = main.model_copy(update={"agent": "a1"})
    inbox.placed(
        Whereabouts(
            conversation=parser, launch="one", worktree=tmp_path, since=clock.now()
        )
    )

    def flag(path: str, branch: str | None) -> Flagged:
        return Flagged(
            text=f"{path} landed, flagged for the operator's review.",
            summary=f"{path} is a new production file",
            worktree=tmp_path,
            path=Path(path),
            branch=branch,
        )

    start = clock.now()
    parser_py, header, lexer_py, clock_py, tokens_py = (
        inbox.made(
            reason, sender, Operator(), tmp_path, start + timedelta(minutes=minutes)
        ).number
        for minutes, (reason, sender) in enumerate(
            [
                (flag("src/parser.py", "feat"), parser),
                (Message(kind="note", text="Header first."), main),
                (flag("src/lexer.py", "feat"), parser),
                (flag("src/clock.py", None), main),
                (flag("src/tokens.py", "feat"), parser),
            ]
        )
    )
    approved = inbox.item(tokens_py).model_copy(
        update={"state": Decided(at=clock.now(), approved=True)}
    )
    inbox.kept(approved)
    Names(path=layout.host.names).keep("s1", "w")
    reader = Reader(
        delivery=Delivery.model_construct(inbox=inbox, clock=clock, layout=layout.host),
        reader=Operator(),
        mine=True,
    )
    items = inbox.about(tmp_path / ".git")
    listed = reader.read(items, Narrowing())
    # The subagent's two flagged writes waiting, cited as their entry cites them.
    both = f"@{parser_py} @{lexer_py}"
    assert listed.found == 4
    assert listed.text.splitlines() == [
        f"@{header}  2026-10-01 12:01  a note from `w` to you, waiting: Header first.",
        (
            f"{both}  2026-10-01 12:02  2 flagged writes from `w/a1` to you, "
            "waiting: 2 files on `feat`"
        ),
        (
            f"@{clock_py}  2026-10-01 12:03  1 flagged write from `w` to "
            "you, waiting: 1 file on no branch"
        ),
        "Not listed: 1 item not waiting for you, which `every` lists.",
    ]
    # An entry counts as one against the limit, and what it leaves out is counted in items.
    latest = reader.read(items, Narrowing(limit=1, every=True))
    assert latest.text.splitlines() == [
        (
            f"{both} @{tokens_py}  2026-10-01 12:04  3 flagged writes from `w/a1` to "
            "you, 2 waiting, 1 approved: 3 files on `feat`"
        ),
        (
            "Not listed: 2 earlier items, which `until` "
            f'"{(start + timedelta(minutes=4)).astimezone().isoformat()}" reads; a '
            "`limit` of 3 lists them all."
        ),
    ]
    # Read whole, each is under the entry's heading, naming its file.
    whole = reader.read(items, Narrowing(whole=True, kinds=["flagged write"]))
    assert whole.text.split("\n\n")[0].splitlines()[:3] == [
        f"{both}  2026-10-01 12:02  2 flagged writes from `w/a1` to you, waiting:",
        f'<item item="{parser_py}" kind="flagged write" from="w/a1">',
        "src/parser.py landed, flagged for the operator's review.",
    ]
    # `lup-dev inbox` lists them so too.
    entries = by_agent([each for each in items if isinstance(each.state, Waiting)])
    assert [cli.line(each) for each in entries][1:] == [
        (
            f"{both:>5}  2026-10-01 12:02  2 flagged writes from subagent a1 of "
            f"claude session s1 in {tmp_path}: 2 files on `feat`"
        ),
        (
            f"{cited(clock_py):>5}  2026-10-01 12:03  1 flagged write from claude "
            f"session s1 in {tmp_path}: 1 file on no branch"
        ),
    ]


def dated(root: Path, message: str, at: str) -> str:
    """Commit everything in `root`'s worktree as made at `at`, and return the commit's short id: what landed since a moment is read by its date."""
    when = {**os.environ, "GIT_AUTHOR_DATE": at, "GIT_COMMITTER_DATE": at}
    run("git", "add", "-A", cwd=root)
    run("git", "commit", "-q", "-m", message, cwd=root, env=when)
    return run("git", "rev-parse", "--short", "HEAD", cwd=root).text().strip()


def test_a_new_main_session_is_told_where_its_repository_stands_once_as_it_starts(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
    *,
    shell: Shell,
) -> None:
    repository = tmp_path / "w"
    repository.mkdir()
    shell.git(repository, "init", "-q", "-b", "dev")
    (repository / ".git" / "info" / "exclude").write_text("judges/\n")
    (repository / "README.md").write_text("lup\n")
    dated(repository, "Start.", "2026-10-01T11:00:00+00:00")
    origin = tmp_path / "origin.git"
    shell.git(tmp_path, "init", "-q", "--bare", str(origin))
    shell.git(repository, "remote", "add", "origin", str(origin))
    shell.git(repository, "push", "-q", "origin", "dev")
    feature = tmp_path / "parser"
    shell.git(repository, "worktree", "add", "-q", "-b", "parser", str(feature))
    (feature / "parser.py").write_text("header = 1\n")
    parsed = dated(feature, "Parse the header.", "2026-10-01T11:30:00+00:00")
    (feature / "draft.md").write_text("A draft.\n")
    with inboxed(machine, clock, notices, said, bearings=True):
        launched(machine, clock, repository, "one", "claude")
        hook = machine.host.launch("one").hook
        mcp = machine.host.launch("one").mcp

        def started(source: str, session: str) -> str:
            clock.sleep(60)
            return send(hook, claude("SessionStart", source=source, session_id=session))

        first = context(started("startup", "s0"))
        call(mcp, "ask", {"question": "Which parser?", "thread": "Which parser"})
        call(mcp, "note", {"remark": "The header comes first."})
        (repository / "lexer.py").write_text("tokens = []\n")
        lexed = dated(repository, "Land the lexer.", "2026-10-01T12:30:00+00:00")
        shell.git(repository, "push", "-q", "origin", "dev")
        clock.sleep(3600)
        resumed = context(started("resume", "s0"))
        second = context(started("startup", "s1"))
        compacted = context(started("compact", "s1"))
        cleared = context(started("clear", "s2"))
        for name, session in [("two", "t2"), ("three", "t3")]:
            (tmp_path / name).mkdir()
            launched(
                machine,
                clock,
                tmp_path / name,
                name,
                "claude",
                repository=repository / ".git",
            )
            clock.sleep(60)
            send(
                machine.host.launch(name).hook,
                claude("SessionStart", source="resume", session_id=session),
            )
        beside = context(started("startup", "s4"))
    opening = (
        "lup: where this repository stands as you start, told once. Each line "
        "says where to read more."
    )
    unlanded = (
        "Not landed on `origin/dev` (`git log <branch> --not --remotes` reads a "
        "branch's commits; `git -C <worktree> status` its changes):\n"
        f'- `parser`, in {feature}: 1 commit, the last {parsed} "Parse the '
        'header.", 2026-10-01 11:30; 1 file changed, not committed.'
    )
    assert first.split("\n\n") == [
        opening,
        unlanded,
        "No main session of this repository was heard before you.",
    ]
    assert resumed == ""
    assert compacted == ""
    s0 = "`w` (claude session s0)"
    # A session cleared in its launch holds nothing: the next one hears what it
    # left, none of it given to them.
    assert second == "\n\n".join(
        [
            opening,
            unlanded,
            (
                "Open threads of this repository (`inbox` with `thread` reads one "
                "whole; the `thread` tool with `hold` takes one):\n"
                '- @which-parser, "Which parser", held by nobody: waiting on the '
                "operator: 1 question."
            ),
            "\n".join(
                [
                    (
                        f"Landed on `origin/dev` since {s0}, the last main session "
                        "(last heard at 2026-10-01 12:01), started at 2026-10-01 "
                        "12:01 (`git show <commit>` reads one):"
                    ),
                    f"- {lexed} Land the lexer.",
                    (
                        f"What {s0} and the operator said to each other: `inbox` "
                        'with `conversation` "s0", `every` and `whole`.'
                    ),
                ]
            ),
        ]
    )
    assert cleared.splitlines()[-3:] == [
        (
            "Landed on `origin/dev` since `w` (claude session s1), the last main "
            "session (last heard at 2026-10-01 13:03), started at 2026-10-01 13:03 "
            "(`git show <commit>` reads one):"
        ),
        "- Nothing.",
        (
            "What `w` (claude session s1) and the operator said to each other: "
            '`inbox` with `conversation` "s1", `every` and `whole`.'
        ),
    ]
    assert "Waiting for the operator" not in cleared
    assert (
        "Main sessions of this repository running beside you:\n"
        f"- `two`, in {tmp_path / 'two'}.\n"
        f"- `three`, in {tmp_path / 'three'}."
    ) in beside
    assert "`three`, the last main session (still running)" in beside


def test_the_bearings_tell_the_session_what_is_its_and_leave_the_operators_items_out(
    tmp_path: Path, clock: FakeClock
) -> None:
    layout = Layout(state=tmp_path / "state", runtime=tmp_path / "run", data=tmp_path)
    inbox = inbox_opened(layout)
    last = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    worker = last.model_copy(update={"agent": "a1"})
    other = last.model_copy(update={"session": "s9"})
    at = clock.now()
    inbox.placed(
        Whereabouts(conversation=last, launch="one", worktree=tmp_path, since=at)
    )

    def flag(branch: str) -> Flagged:
        return Flagged(
            text="parser.py landed, flagged.",
            summary="new-file",
            worktree=tmp_path,
            path=Path("parser.py"),
            branch=branch,
        )

    for reason, sender in [
        (Question(text="Which parser?"), last),
        (flag("parser"), last),
        (flag("parser"), worker),
        (HowItFelt(text="Calm."), worker),
        (flag("lexer"), worker),
        (Message(kind="note", text="Header first."), worker),
        (Question(text="Which lexer?"), other),
    ]:
        inbox.made(reason, sender, Operator(), tmp_path, at)
    bearings = RepositoryBearings(
        delivery=Delivery.model_construct(inbox=inbox, clock=clock, layout=layout.host),
        running=lambda _: "dev",
    )
    starting = last.model_copy(update={"session": "s2"})
    page = bearings.page(
        starting,
        last,
        Repository(
            unlanded=[
                Unlanded(
                    branch="lexer",
                    worktree=None,
                    commits=2,
                    changed=0,
                    last='abc1234 "Lex."',
                    at=at,
                )
            ],
            landed=[],
            onto="dev",
        ),
        [],
    )
    # Seven items wait on the operator, from the last session, their worker and
    # another session: theirs to answer, none of it told.
    assert page.split("\n\n")[1:] == [
        (
            "Not landed on `dev` (`git log <branch> --not --remotes` reads a "
            "branch's commits; `git -C <worktree> status` its changes):\n"
            '- `lexer`, with no worktree: 2 commits, the last abc1234 "Lex.", '
            "2026-10-01 12:00."
        ),
        (
            "Landed on `dev` since claude session s1, the last main session (last "
            "heard at 2026-10-01 12:00), started at 2026-10-01 12:00 (`git show "
            "<commit>` reads one):\n"
            "- Nothing.\n"
            "What claude session s1 and the operator said to each other: `inbox` "
            'with `conversation` "s1", `every` and `whole`.'
        ),
    ]
    nowhere = Register(
        launch="one",
        runtime="claude",
        worktree=tmp_path,
        repository=tmp_path / ".git",
        judge=tmp_path / "lup-dev",
        container="lup-one",
        limits=Limits(actions=[], protected=[]),
        github=None,
    )
    unread = asyncio.run(bearings.told(nowhere, "s2", [])) or ""
    assert unread.split("\n\n")[1].startswith(
        "lup couldn't read this repository's git: git "
    )
    assert "- Unread: git couldn't be read, as said above." in unread


def test_a_room_naming_the_operator_s_session_keeps_no_home_for_it(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    """A session the operator ran on the host is never kept as a launch's, though a room's hook names it first: its record is read from their own directory, never one the room planted in its home under its id."""
    operators = tmp_path / ".claude"
    theirs = operators / "projects" / "-w" / "h1.jsonl"
    theirs.parent.mkdir(parents=True)
    theirs.write_text(json.dumps({"type": "user", "cwd": "/w"}) + "\n")
    records = ClaudeRecords(directory=operators, host=machine.host)
    recorded = {"claude": Recorded(records=records, reader=ClaudeTranscripts())}
    with inboxed(machine, clock, notices, said, recorded):
        room = launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup", session_id="h1"))
        send(hook, claude("SessionStart", source="startup", session_id="r1"))
    assert room.home is not None
    planted = room.home / "projects" / "-w" / "h1.jsonl"
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(json.dumps({"type": "user", "forged": True}) + "\n")

    assert not machine.host.home_of("claude", "h1").exists()
    assert machine.host.home_of("claude", "r1").read_text() == str(room.home)
    found = records.conversation("h1", None)
    assert found is not None
    assert (found.record, found.root) == (theirs, operators)


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_agents_open_and_hold_threads_and_are_told_what_lands_there_on_each_runtime(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
    *,
    runtime: str,
) -> None:
    """A session opens a thread, theirs as nobody above answers for it, their subagent takes it and is told what the session sends there; the session is told they took it, and nothing their own subagent sends, which their runtime tells them, on either runtime."""
    records = Subagents(tmp_path)
    rollouts = Rollouts(tmp_path)
    worktree = tmp_path / "w"
    start = claude if runtime == "claude" else codex

    def own(tool: str, arguments: dict[str, JsonValue], made: str) -> tuple[str, bool]:
        started = (
            lup_call(tool, arguments, made)
            if runtime == "claude"
            else codex(
                "PreToolUse",
                tool_name=f"mcp__lup__{tool}",
                tool_input=arguments,
                tool_use_id=made,
            )
        )
        stamped = json.loads(send(hook, started))["hookSpecificOutput"]["updatedInput"]
        return call(mcp, tool, stamped)

    def subagent(tool: str, arguments: dict[str, JsonValue]) -> tuple[str, bool]:
        if runtime == "claude":
            return records.lup((hook, mcp), tool, arguments, "a1", "Explore")
        return rollouts.lup((hook, mcp), tool, arguments, "th1")

    def subagent_calls(made: str) -> str:
        if runtime == "claude":
            return send(hook, records.call("a1", "Explore", made))
        return send(hook, rollouts.call("th1", made))

    def session_calls(made: str) -> str:
        return send(hook, bash(made) if runtime == "claude" else codex_bash(made))

    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, worktree, "one", runtime)
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, start("SessionStart", source="startup"))
        opened = own("thread", {"name": "lag", "title": "The cursor jumps"}, "m1")
        if runtime == "claude":
            send(hook, records.spawn("t1", name="parser"))
            records.recorded("a1", "Explore", "t1", name="parser")
        else:
            rollouts.recorded("th1", "t1", "/root/lexer")
        held = subagent("thread", {"name": "lag", "hold": True})
        noted = own("note", {"remark": "Typing fast moves it.", "thread": "lag"}, "m2")
        told = context(subagent_calls("c1"))
        theirs = subagent("note", {"remark": "Found it: the debounce."})
        felt = subagent("how_it_felt", {"text": "Calm."})
        spared = session_calls("m3")
        read = inbox("--thread", "lag")
        concerns = delivery.concerns()
        lag = concerns.named(worktree / ".git", "lag")
    assert opened == ("Opened @lag, held by you.", False)
    assert held == (
        "You hold @lag, and work in it: what you send lands there.",
        False,
    )
    assert noted[0].startswith("Your note is with the operator, @")
    assert noted[0].endswith(", in @lag. You can carry on.")
    # The holder hears the session's note whole at their next call.
    assert told.startswith('<landed thread="lag" item="')
    assert 'from="w">Typing fast moves it.</landed>' in told
    # The subagent works in the thread they hold, so their own note lands there
    # unnamed; neither it nor how they felt reaches the session above them.
    assert theirs[0].endswith(". You can carry on.")
    assert not felt[1]
    # The session is told their subagent took what they held, and nothing that subagent sends.
    taken = context(spared)
    assert taken.startswith("lup: `w/")
    assert taken.endswith("` took @lag, which you held.")
    lead = Conversation(
        repository=worktree / ".git",
        runtime=runtime,
        session="s1" if runtime == "claude" else "t1",
    )
    # At the top, held by the session as they opened it, then by the subagent who took it.
    assert lag.parent is None
    assert lag.holder is not None
    assert (lag.holder.main(), lag.holder.agent is not None) == (lead, True)
    assert read.startswith("Thread @lag (@")
    assert "Typing fast moves it." in read
    assert "Found it: the debounce." in read
    assert "Calm." not in read


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_a_subagent_hears_only_what_s_addressed_to_them_in_their_parent_s_thread_on_each_runtime(
    machine: Layout,
    clock: FakeClock,
    notices: Raised,
    said: list[str],
    tmp_path: Path,
    *,
    runtime: str,
) -> None:
    """Two subagents start on the concern their session works in: neither is told the operator's words to the session there, nor the other's note; one who opened a sub-thread is told what lands there, and one who joins the concern is told what lands there from then on, on either runtime."""
    records = Subagents(tmp_path)
    rollouts = Rollouts(tmp_path)
    worktree = tmp_path / "w"
    start = claude if runtime == "claude" else codex
    lead = Conversation(
        repository=worktree / ".git",
        runtime=runtime,
        session="s1" if runtime == "claude" else "t1",
    )
    agents = {"parser": ("a1", "th1"), "lexer": ("a2", "th2")}

    def subagent(
        name: str, tool: str, arguments: dict[str, JsonValue]
    ) -> tuple[str, bool]:
        agent, thread = agents[name]
        if runtime == "claude":
            return records.lup((hook, mcp), tool, arguments, agent, "Explore")
        return rollouts.lup((hook, mcp), tool, arguments, thread)

    def subagent_calls(name: str, made: str) -> str:
        agent, thread = agents[name]
        if runtime == "claude":
            told = send(hook, records.call(agent, "Explore", made))
        else:
            told = send(hook, rollouts.call(thread, made))
        return context(told) if told else ""

    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, worktree, "one", runtime)
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, start("SessionStart", source="startup"))
        call(mcp, "thread", {"name": "home", "title": "Home", "hold": True})
        for spawned_by, name in [("t1", "parser"), ("t2", "lexer")]:
            agent, thread = agents[name]
            if runtime == "claude":
                send(hook, records.spawn(spawned_by, name=name))
                records.recorded(agent, "Explore", spawned_by, name=name)
            else:
                rollouts.recorded(thread, "t1", f"/root/{name}")
        subagent("parser", "note", {"remark": "On the parser."})
        opened = subagent(
            "parser", "note", {"remark": "Tabs vanish.", "thread": "Tabs vanish"}
        )
        subagent("lexer", "note", {"remark": "The lexer is done."})
        home = delivery.concerns().named(worktree / ".git", "home")
        drafting(
            machine,
            clock,
            Draft(
                letters=[
                    Letter(to=lead, thread=home.number, text="Ship the parser first.")
                ]
            ),
        )
        sending(machine, clock)
        spared = subagent_calls("parser", "c1")
        subagent("lexer", "note", {"remark": "Tabs here too.", "thread": "tabs-vanish"})
        under = subagent_calls("parser", "c2")
        joined = subagent("lexer", "thread", {"name": "home", "join": True})
        subagent("parser", "note", {"remark": "The parser is done."})
        heard = subagent_calls("lexer", "c3")
    assert opened[0].endswith(", in @tabs-vanish. You can carry on.")
    # On @home by working there and by what they sent landing there, the
    # parser is told neither the operator's words to the session nor the
    # lexer's note: nothing beside their next calls.
    assert spared == ""
    # The sub-thread they opened by sending into it is theirs to hear.
    assert under.startswith("lup: in @tabs-vanish, a note from `w/lexer`, @")
    assert under.endswith(": Tabs here too.")
    # Joining the thread they started on, the lexer chose it, and hears what lands there.
    assert joined == ("You work in @home: what you send lands there.", False)
    assert heard.startswith("lup: in @home, a note from `w/parser`, @")
    assert heard.endswith(": The parser is done.")


def test_lup_dev_inbox_answer_answers_a_check_and_whoever_asked_it_is_told(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        asked = call(
            mcp,
            "ask",
            {
                "question": "Does a fresh room start fast?",
                "checks": ["Launch a fresh room: it starts within 5 s."],
            },
        )
        question = newest(delivery)
        [check] = [each.number for each in delivery.inbox.ledger.every(Check)]
        answered = inbox("answer", str(check), "--comment", "It took 9 s.")
        again = refused("answer", str(check), "--comment", "Again.")
        told = context(send(hook, bash("b1")))
    assert asked == (
        (
            f"Your question is with the operator, @{question}, in "
            f"@does-a-fresh-room-start-fast, and its check @{check} waits on them. "
            "Their answer reaches you at a later call; `wait_inbox` waits for it."
        ),
        False,
    )
    assert answered == f"Answered @{check}: whoever asked it is told.\n"
    assert again == f"@{check} is answered already"
    # Working in no thread, the asker had one opened for the question, as a check is a thread's.
    assert told == (
        f"lup: the operator answered your check @{check} in "
        "@does-a-fresh-room-start-fast:\n"
        f'<checked item="{check}" thread="does-a-fresh-room-start-fast">It took 9 s.'
        "</checked>"
    )
