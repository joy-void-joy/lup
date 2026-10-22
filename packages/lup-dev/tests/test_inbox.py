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
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, override

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
from pydantic import Field
from typer.testing import CliRunner

from lup.github.tools import GitHubTools
from lup.programs import Ran
from lup.rooms import Podman
from lup.tools.speaking import SPEAKING
from lup_dev import Modules, Project, cli
from lup_dev.adapters.claude import ChannelMessage, ClaudeRecords, ClaudeTranscripts
from lup_dev.codescan.engine import EngineError
from lup_dev.declaration.resolve import resolve
from lup_dev.gate import Passed, Standing
from lup_dev.host.client import HostClient, RoomClient, Starter
from lup_dev.host.courier import Conversation as Caller
from lup_dev.host.courier import Heard, Posted, Spawned, Spawns
from lup_dev.host.names import container_name
from lup_dev.host.protocol import (
    Holding,
    HostError,
    Limits,
    Register,
    Reply,
    Request,
    ShowHolding,
    Stop,
)
from lup_dev.host.pushes import Pushes
from lup_dev.host.records import Called, Recorded, Said
from lup_dev.host.service import UNDECIDED, HostService, Naming, Program, executed
from lup_dev.host.watch import Changes
from lup_dev.host.workers import LaunchJudge, LaunchModules, WorkerJudge, Workers
from lup_dev.inbox.delivery import Delivery, clocked, opening
from lup_dev.inbox.notices import Notices, NotifySend
from lup_dev.inbox.parts import PartId, blocks
from lup_dev.inbox.protocol import (
    AnswerApproval,
    AskApproval,
    AskFlag,
    Context,
    Conversed,
    Drafted,
    Exchanged,
    Files,
    FinishItem,
    Items,
    KeepDraft,
    KeepTalk,
    ListInbox,
    ListItems,
    Reviewed,
    SendDraft,
    SendItem,
    Settled,
    ShowContext,
    ShowConversation,
    ShowDraft,
    ShowFiles,
    ShowGathering,
    Shown,
    ShowTalk,
    Talked,
)
from lup_dev.inbox.store import (
    Answer,
    Answered,
    ApiChanged,
    Approval,
    AtLanding,
    Binary,
    ChangedFile,
    Comment,
    Conversation,
    Decided,
    Done,
    Draft,
    Ended,
    Flagged,
    Found,
    Friction,
    HeldChange,
    HowItWent,
    Inbox,
    InboxError,
    Item,
    Letter,
    Message,
    Operator,
    Passage,
    Question,
    Quote,
    Rank,
    Reading,
    Reason,
    Review,
    Sent,
    Superseded,
    Talk,
    TalkComment,
    Text,
    Told,
    Waiting,
    cited,
    item_number,
    ranked,
)
from lup_dev.inbox.store import Asked as Ask
from lup_dev.inbox.store import Reply as Replied
from lup_dev.inbox.store import Stop as Stopped
from lup_dev.inbox.tools import specs
from lup_dev.inbox.typed import TypeReader
from lup_dev.launch.room import RoomError
from lup_dev.layout import GitDirectoryLayout, InboxLayout, Layout
from lup_dev.policy.before import Overwrite, Replacement, before
from lup_dev.policy.checkpoint import Bench, CallFinished, CallStarted
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
from lup_dev.policy.landing import LandingTools
from lup_dev.policy.tools import JudgeTools, stands
from lup_dev.policy.verdicts import Verdict, VerdictLog
from lup_dev.remote.protocol import Remotes
from lup_dev.stored import write_model

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator

    from conftest import FakeClock, InProcess, Kit, Shell
    from mcp.client._transport import TransportStreams
    from pydantic import JsonValue

    from lup.rooms.engine import Process
    from lup_dev.layout import HostLayout

runner = CliRunner()


# The host service in a thread of its own, and a session's side of its sockets,
# as `test_host.py` drives them.


class Quiet(LaunchJudge):
    """A launch's judge that answers every hook with nothing."""

    async def judged(self, launch: Register, payload: str) -> str:
        return ""


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
    async def held(self, party: Conversation, until: Callable[[], bool]) -> str:
        self.holding.set()
        return await super().held(party, until)


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
) -> Generator[Watched]:
    """A host service with lup's inbox and the dashboard's kind, its delivery yielded, until the context ends; an item's moment read from `recorded`, the judge's stores from `judging`, or `machine`'s; an approval's types read by `typed`, where given, which tells `told` too; a subagent's spawn read by `spawns`, or by each runtime's adapter; containers asked of `podman`, where given; each hook answered by `judge`, else with nothing, and each launch's modules served by `modules`, where given; `land` pushing through the remotes `remotes` makes over the delivery, where given, else through remotes telling no one, and running in a launch's room through `rooms`, where given."""
    known = cli.Adapters(known=cli.adapters())
    couriers = cli.Couriers(adapters=known)
    wakers = cli.Wakers(adapters=known)
    changes = Changes()
    pushes = Pushes()
    delivery = Watched(
        inbox=Inbox.opened(machine.inbox, changes),
        waker=wakers,
        pushes=pushes,
        layout=machine.host,
        notices=notices,
        clock=clock,
        say=said.append,
        patience=patience,
    )

    def saying(line: str) -> None:
        said.append(line)
        if told is not None:
            told(line)

    service = HostService(
        layout=machine.host,
        answerer=known,
        courier=couriers,
        spawns=spawns or cli.SpawnRecords(adapters=known),
        post=delivery,
        routes=cli.control_routes(delivery, recorded or {}, None, judging or machine),
        tools=[
            each.model_copy(update={"run": rooms})
            if isinstance(each, LandingTools) and rooms is not None
            else each
            for each in cli.room_tools(
                delivery,
                judging or machine,
                Remotes(say=said.append) if remotes is None else remotes(delivery),
            )
        ],
        judge=judge or Quiet(),
        modules=modules,
        say=said.append,
        changes=changes,
        waker=wakers,
        pushes=pushes,
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
    if not told.startswith("lup: this session is"):
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


def first_note(text: str) -> str:
    """How the first item, the operator's note of one line, is told."""
    return note(1, text)


def test_an_item_is_told_at_the_conversations_next_call_and_never_again(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        started = json.loads(send(hook, claude("SessionStart", source="startup")))
        assert started["hookSpecificOutput"]["additionalContext"].startswith(
            "lup: this session is `"
        )
        assert inbox("send", "one", "Look at the cache.") == (
            f"Sent @1 to `{tmp_path.name}`, claude session s1.\n"
        )
        told = send(hook, bash("b1"))
        again = send(hook, bash("b2"))
        item = delivery.inbox.item(1)
    assert context(told) == first_note("Look at the cache.")
    assert again == ""
    assert item.state == Told(at=clock.now(), how="call")
    assert item.recipient == Conversation(
        repository=tmp_path / ".git", runtime="claude", session="s1"
    )


def test_items_waiting_are_told_together_oldest_first_as_a_session_resumes(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        inbox("send", "one", "First.")
        inbox("send", "one", "Second.")
        resumed = send(hook, claude("SessionStart", source="resume"))
    assert context(resumed) == (f"{first_note('First.')}\n\n{note(2, 'Second.')}")


def test_a_turns_end_holds_once_and_a_later_end_with_nothing_new_ends_at_once(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        inbox("send", "one", "Before you stop.")
        held = json.loads(send(hook, claude("Stop", stop_hook_active=False)))
        let = send(hook, claude("Stop", stop_hook_active=True))
        later = send(hook, claude("Stop", stop_hook_active=False))
        item = delivery.inbox.item(1)
    assert held == {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": first_note("Before you stop."),
        }
    }
    assert item.state == Told(at=clock.now(), how="turn's end")
    assert let == ""
    assert later == ""


def test_an_end_following_a_hold_ends_and_what_came_meanwhile_waits_for_a_call(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        inbox("send", "one", "One.")
        assert context(send(hook, claude("Stop"))) == first_note("One.")
        inbox("send", "one", "Two.")
        let = send(hook, claude("Stop", stop_hook_active=True))
        told = send(hook, bash("b1"))
    assert let == ""
    assert context(told) == note(2, "Two.")


def test_a_subagents_end_holds_once_on_what_waits_for_it(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        arguments = json.loads(
            send(hook, lup_call("ask", {"question": "May I?"}, "q1", agent_id="a1"))
        )["hookSpecificOutput"]["updatedInput"]
        call(machine.host.launch("one").mcp, "ask", arguments)
        inbox("answer", "1", "--comment", "Yes.")
        ending = {"agent_id": "a1", "last_assistant_message": "Asked."}
        held = send(hook, claude("SubagentStop", stop_hook_active=False, **ending))
        let = send(hook, claude("SubagentStop", stop_hook_active=True, **ending))
    assert json.loads(held)["hookSpecificOutput"]["hookEventName"] == "SubagentStop"
    assert context(held) == (
        '<answer item="2" from="operator" question="1">\n'
        '<asked>May I?</asked>\n<comment id="2.1">Yes.</comment>\n</answer>'
    )
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
            returned = waiting.result(timeout=60)
        after = send(hook, bash("b1"))
        item = delivery.inbox.item(1)
    assert returned == (first_note("Here it is."), False)
    assert item.state == Told(at=clock.now(), how="held call")
    assert after == ""


def test_a_call_to_lups_tools_tells_nothing_at_its_start_and_its_result_does(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        inbox("send", "one", "Already here.")
        started = json.loads(send(hook, lup_call("wait_inbox", {}, "w1")))
        returned = call(
            machine.host.launch("one").mcp,
            "wait_inbox",
            started["hookSpecificOutput"]["updatedInput"],
        )
    assert "additionalContext" not in started["hookSpecificOutput"]
    assert returned == (first_note("Already here."), False)


def test_a_question_held_for_its_answer_reaches_a_watch_of_the_inbox_at_once(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    question: dict[str, JsonValue] = {"question": "Which parser?", "wait": True}
    with (
        inboxed(machine, clock, notices, said),
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
            inbox("answer", "1", "--comment", "Lark.")
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
            listed = inbox()
            shown = inbox("show", "1")
            answered = inbox(
                "answer", "1", "--leaning", "1", "--undecided", "2", "--comment", "Go."
            )
            returned = asking.result(timeout=60)
        asked = delivery.inbox.item(1)
    assert listed == (
        f"   @1  2026-10-01 12:00  a question from `{tmp_path.name}` (claude session s1) "
        f"in {tmp_path}: "
        "Which parser?\n"
    )
    assert shown == (
        f"@1, a question from claude session s1 in {tmp_path} to the operator, "
        "made 2026-10-01 12:00, waiting:\nWhich parser?\n"
        "1. Parse with lark\n   Its lean: yes, it's typed\n"
        "2. Keep the cache\n   Its lean: no\n"
    )
    assert answered == "Answered @1: your answer, @2, is for claude session s1.\n"
    assert returned == (
        (
            '<answer item="2" from="operator" question="1">\n'
            "<asked>Which parser?</asked>\n"
            '<decision number="1" lean="yes, it\'s typed" verdict="leaning: they go '
            'with the lean" id="2.1">Parse with lark</decision>\n'
            '<decision number="2" lean="no" verdict="undecided" id="2.2">Keep the cache'
            "</decision>\n"
            '<comment id="2.3">Go.</comment>\n'
            "</answer>"
        ),
        False,
    )
    assert asked.state == Answered(at=clock.now(), answer=2)
    assert notices.raised == [
        (
            f"lup: a question from claude session s1 in {tmp_path}\n"
            "Which parser?\nlup-dev inbox show 1"
        )
    ]


def test_ask_without_wait_returns_at_once_and_the_answer_comes_at_a_call(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        returned = call(machine.host.launch("one").mcp, "ask", {"question": "Why?"})
        inbox("answer", "1", "--comment", "Because.")
        told = send(hook, bash("b1"))
    assert returned == (
        (
            "Your question is with the operator, @1. Their answer reaches you "
            "at a later call; `wait_inbox` waits for it."
        ),
        False,
    )
    assert context(told) == (
        '<answer item="2" from="operator" question="1">\n'
        '<asked>Why?</asked>\n<comment id="2.1">Because.</comment>\n</answer>'
    )


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
        inbox("answer", "1", "--comment", "Lark.")
        answered = call(mcp, "ask", asks[0])
        # Still waiting: the call sent again holds on the same question.
        dropped(mcp, "ask", asks[1], delivery.holding)
        with ThreadPoolExecutor(max_workers=1) as pool:
            delivery.holding.clear()
            asking = pool.submit(call, mcp, "ask", asks[1])
            assert delivery.holding.wait(timeout=60)
            inbox("answer", "3", "--comment", "None.")
            held = asking.result(timeout=60)
        # Without `wait`, sent again, it makes no second question either.
        once = call(mcp, "ask", asks[2])
        twice = call(mcp, "ask", asks[2])
        asked = [
            (item.number, item.call)
            for item in delivery.inbox.items.values()
            if isinstance(item.reason, Question)
        ]
    assert answered == (
        (
            '<answer item="2" from="operator" question="1">\n'
            '<asked>Which parser?</asked>\n<comment id="2.1">Lark.</comment>\n'
            "</answer>"
        ),
        False,
    )
    assert held == (
        (
            '<answer item="4" from="operator" question="3">\n'
            '<asked>Which cache?</asked>\n<comment id="4.1">None.</comment>\n'
            "</answer>"
        ),
        False,
    )
    assert once == twice
    assert once[0].startswith("Your question is with the operator, @5.")
    assert asked == [(1, "q1"), (3, "q2"), (5, "q3")]


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
        inbox("send", "one", "And this.")
        told = send(hook, bash("b1"))
        woken = delivery.inbox.item(1)
        frames = messages.close()
    assert [json.loads(frame) for frame in frames] == [
        {
            "type": "user",
            "message": {"role": "user", "content": bell(1)},
            "session_id": "s1",
        }
    ]
    assert frames[0].endswith("\n")
    # The doorbell carries no item: they stay waiting, and the next call tells both.
    assert woken.state == Told(at=clock.now(), how="call")
    assert context(told) == f"{first_note('Wake up.')}\n\n{note(2, 'And this.')}"
    assert "one: woke claude session s1 for @1" in said


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
        stamped = json.loads(send(hook, lup_call("wait_inbox", {}, "w1")))[
            "hookSpecificOutput"
        ]["updatedInput"]
        returned = call(machine.host.launch("one").mcp, "wait_inbox", stamped)
        item = delivery.inbox.item(1)
        frames = messages.close()
    assert frames_of(frames) == [bell(1)]
    assert returned == (first_note("Read me through lup."), False)
    assert item.state == Told(at=clock.now(), how="held call")


def frames_of(written: list[str]) -> list[str]:
    """The text each frame written to a messaging socket carries."""
    return [json.loads(frame)["message"]["content"] for frame in written]


def test_a_session_that_just_started_is_woken(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        send(hook, claude("SessionStart", source="startup"))
        inbox("send", "one", "Before your first turn.")
        frames = messages.close()
    assert frames_of(frames) == [bell(1)]


def test_a_session_in_its_turn_is_told_at_its_hooks_and_never_woken(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        send(hook, claude("SessionStart", source="startup"))
        send(hook, bash("b1"))
        inbox("send", "one", "While you run.")
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
        ended = send(hook, claude("Stop", stop_hook_active=False))
        frames = messages.close()
    assert context(finished) == first_note("While you run.")
    assert json.loads(ended) == {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": note(2, "Between calls."),
        }
    }
    assert frames == []


def test_a_service_started_again_wakes_a_session_it_hasn_t_heard_since(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, bash("b1"))
    with inboxed(machine, clock, notices, said):
        messages = Socket(machine.host.launch("one").messages)
        inbox("send", "one", "After a restart.")
        frames = messages.close()
    assert frames_of(frames) == [bell(1)]


def test_two_launches_in_one_worktree_each_wake_through_their_own_socket(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        launched(machine, clock, tmp_path, "two", "claude")
        first = Socket(machine.host.launch("one").messages)
        second = Socket(machine.host.launch("two").messages)
        send(machine.host.launch("one").hook, claude("SessionStart", session_id="s1"))
        send(machine.host.launch("two").hook, claude("SessionStart", session_id="s2"))
        inbox("send", "one", "For one.")
        inbox("send", "two", "For two.")
        to_first = first.close()
        to_second = second.close()
    assert machine.host.launch("one").messages != machine.host.launch("two").messages
    assert frames_of(to_first) == [bell(1)]
    assert frames_of(to_second) == [bell(2)]
    assert [json.loads(each)["session_id"] for each in [*to_first, *to_second]] == [
        "s1",
        "s2",
    ]


def test_an_idle_session_whose_socket_is_gone_is_told_at_its_next_call(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook, claude("Stop", stop_hook_active=False))
        inbox("send", "one", "Nobody's there.")
        told = send(hook, bash("b1"))
    assert context(told) == first_note("Nobody's there.")
    assert any("claude session s1 wasn't woken through" in each for each in said)


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
"""A session introducing itself to lup's tool server, on the handshake revision."""


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
    """The prompt a Claude Code session's turn starts on when it takes a channel's message (`docs/field-notes.md`, *Channels*)."""
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
        notice = session.pushed()
        pushed = ChannelMessage.model_validate(notice.params)
        pending = delivery.inbox.item(1).state
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
        state = delivery.inbox.item(1).state
        after = send(hook, bash("b1"))
        session.close()
        frames = messages.close()
    assert session.introduced.capabilities.experimental == {"claude/channel": {}}
    assert notice.method == "notifications/claude/channel"
    # The items themselves, told once: no `wait_inbox`, and no doorbell.
    assert pushed.content == first_note("Wake up.")
    assert pending == Waiting()
    assert between == ""
    assert state == Told(at=clock.now(), how="wake")
    assert taken == ""
    assert after == ""
    assert frames == []
    assert "one: pushed @1 to claude session s1" in said


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
        session.pushed()
        rung = list(messages.ringing())
        put_back = delivery.inbox.item(1).state
        told = send(hook, bash("b1"))
        send(hook, claude("Stop", stop_hook_active=False))
        inbox("send", "one", "Again.")
        quiet = session.quiet()
        session.close()
        frames = messages.close()
    assert frames_of(rung) == [bell(1)]
    assert put_back == Waiting()
    assert context(told) == first_note("Anyone?")
    assert quiet
    assert frames_of(frames) == [bell(1), bell(2)]
    assert [line for line in said if "took nothing lup pushed" in line] == [
        (
            "one: claude session s1 took nothing lup pushed within 0 seconds, so "
            "it's woken through its messaging socket from now on: its runtime may "
            "not have loaded lup's server to push (docs/inbox.md, *How an agent "
            "is told*)"
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
    # Claude Code's prompts carry the title lup gave the session at its start.
    shown = {"claude": {"session_title": tmp_path.name}, "codex": {}}[runtime]
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", runtime)
        hook = machine.host.launch("one").hook
        send(hook, payload("SessionStart", source="startup"))
        inbox("send", "one", "Read this first.")
        told = send(hook, payload("UserPromptSubmit", prompt="Go on.", **shown))
        again = send(hook, payload("UserPromptSubmit", prompt="And then?", **shown))
        state = delivery.inbox.item(1).state
    assert json.loads(told)["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert context(told) == first_note("Read this first.")
    assert again == ""
    assert state == Told(at=clock.now(), how="turn's start")


def test_a_codex_session_is_never_woken_and_told_at_its_next_call(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "codex")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        send(hook, codex("SessionStart"))
        assert send(hook, codex("Stop", stop_hook_active=False)) == ""
        inbox("send", "one", "Waits.")
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
    assert context(told) == first_note("Waits.")


def test_a_long_item_is_announced_once_and_returned_whole_by_wait_inbox(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    long = "x" * 12_000
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        inbox("send", "one", long)
        announced = send(hook, bash("b1"))
        again = send(hook, bash("b2"))
        stopped = send(hook, claude("Stop", stop_hook_active=False))
        waiting = delivery.inbox.item(1).state
        whole = call(machine.host.launch("one").mcp, "wait_inbox", {})
    size = len(first_note(long).encode()) + 2
    assert context(announced) == (
        f'<announced item="1" kind="note" from="operator" bytes="{size:,}">Too long '
        "to tell here: call `wait_inbox` to read it whole.</announced>"
    )
    assert again == ""
    assert stopped == ""
    assert waiting == Waiting(announced=clock.now())
    assert whole == (first_note(long), False)


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
    assert context(told) == first_note("Late.")


def test_an_ended_subagents_answer_goes_to_its_sessions_main_conversation(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        stamped = json.loads(
            send(hook, lup_call("ask", {"question": "Rename it?"}, "q1", agent_id="a1"))
        )["hookSpecificOutput"]["updatedInput"]
        call(machine.host.launch("one").mcp, "ask", stamped)
        assert send(hook, claude("SubagentStop", agent_id="a1")) == ""
        answered = inbox("answer", "1", "--comment", "Yes.")
        told = send(hook, bash("b1"))
        answer = delivery.inbox.item(2)
    assert answered == "Answered @1: your answer, @2, is for claude session s1.\n"
    assert answer.addressed == Conversation(
        repository=tmp_path / ".git", runtime="claude", session="s1", agent="a1"
    )
    assert context(told) == (
        '<answer item="2" from="operator" for="subagent a1 of claude session s1, '
        'whose conversation had ended" question="1">\n'
        '<asked>Rename it?</asked>\n<comment id="2.1">Yes.</comment>\n</answer>'
    )


def test_items_survive_a_restart_and_reach_a_session_resumed_in_a_launch_of_its_own(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        call(machine.host.launch("one").mcp, "note", {"remark": "A doubt."})
        inbox("send", "one", "Kept.")
    with inboxed(machine, clock, notices, said) as delivery:
        listed = inbox()
        launched(machine, clock, tmp_path, "two", "claude")
        resumed = send(
            machine.host.launch("two").hook, claude("SessionStart", source="resume")
        )
        where = delivery.inbox.whereabouts
    assert listed == (
        f"   @1  2026-10-01 12:00  a note from `{tmp_path.name}` (claude session s1) "
        f"in {tmp_path}: A doubt.\n"
    )
    assert context(resumed) == note(2, "Kept.")
    assert [place.launch for place in where.values()] == ["two"]


def test_the_operator_replies_to_a_note_the_reply_saying_what_it_answers(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        call(machine.host.launch("one").mcp, "note", {"remark": "A doubt.\nAt length."})
        wordless = refused("answer", "1", "--comment", " ")
        ruled = refused("answer", "1", "--leaning", "1", "--comment", "Yes.")
        replied = inbox("answer", "1", "--comment", "Noted, go on.")
        listed = inbox()
        told = send(hook, bash("b1"))
        own = refused("answer", "2", "--comment", "Again.")
        again = inbox("answer", "1", "--comment", "One more thing.")
    assert wordless == "@1 is a note: give your reply in words"
    assert ruled == "@1 is a note, which takes a reply in words, not verdicts"
    assert replied == ("Replied to @1: your reply, @2, is for claude session s1.\n")
    assert listed == "Nothing waits for you.\n"
    assert context(told) == (
        '<message item="2" from="operator" kind="note">\n'
        '<on item="1" kind="note">\n'
        "<opening>A doubt.</opening>\n"
        '<comment id="2.1">Noted, go on.</comment>\n'
        "</on>\n"
        "</message>"
    )
    assert own == (
        "@2 is a note from the operator: neither a question waiting for an "
        "answer nor a conversation's message to reply to"
    )
    assert again == ("Replied to @1: your reply, @3, is for claude session s1.\n")


def test_blocked_note_and_send_reach_the_operator_a_note_raising_no_notice(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        mcp = machine.host.launch("one").mcp
        reported = call(mcp, "blocked", {"problem": "The build is broken."})
        noted = call(mcp, "note", {"remark": "I assumed UTF-8."})
        sent = call(
            mcp,
            "send",
            {"to": "operator", "kind": "disagreement", "text": "Not this way."},
        )
        invalid = call(mcp, "send", {"to": "someone", "kind": "note", "text": "x"})
        listed = inbox()
    assert reported == (
        "Your problem is with the operator, @1. End your turn.",
        False,
    )
    assert noted == ("Your note is with the operator, @2. Carry on.", False)
    assert sent == ("Your message is with the operator, @3.", False)
    assert invalid[1]
    assert invalid[0].startswith("Refused: 1 validation error for Sending")
    assert listed.splitlines() == [
        (
            f"   @1  2026-10-01 12:00  a problem from `{tmp_path.name}` (claude session "
            f"s1) in {tmp_path}: "
            "The build is broken."
        ),
        (
            f"   @2  2026-10-01 12:00  a note from `{tmp_path.name}` (claude session "
            f"s1) in {tmp_path}: "
            "I assumed UTF-8."
        ),
        (
            f"   @3  2026-10-01 12:00  a disagreement from `{tmp_path.name}` (claude "
            f"session s1) in {tmp_path}: Not this way."
        ),
    ]
    assert notices.raised[0] == (
        f"lup: a problem from claude session s1 in {tmp_path}\n"
        "The build is broken.\nlup-dev inbox show 1"
    )
    # The problem and the disagreement wait on the operator, and are noticed; the note is news, and isn't.
    assert len(notices.raised) == 2
    assert notices.raised[1].startswith("lup: a disagreement from claude session s1")


def test_friction_how_it_went_and_stop_reach_the_operator_from_each_runtime_and_subagent(
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
                stamped(hook, lup_call("friction", jammed, "f1", agent_id="a1")),
            ),
            call(
                mcp, "how_it_went", stamped(hook, lup_call("how_it_went", quiet, "h1"))
            ),
            call(mcp, "stop", stamped(hook, lup_call("stop", stopping, "s1"))),
            call(
                mcp2, "friction", stamped(hook2, codex_call("friction", jammed, "c1"))
            ),
            call(
                mcp2,
                "how_it_went",
                stamped(hook2, codex_call("how_it_went", went, "c2", agent_id="b1")),
            ),
            call(
                mcp2,
                "stop",
                stamped(hook2, codex_call("stop", stopping, "c3", agent_id="b1")),
            ),
        ]
        labelled = call(mcp, "friction", {"got_in_the_way": "The gate hung."})
        waiting = delivery.inbox.waiting(Operator())
        listed = inbox()
        shown = inbox("show", "1")
        replied = inbox("answer", "1", "--comment", "The rebuild is fixed.")
        reply = delivery.inbox.item(8)
        done = inbox("done", "2")
        copy = delivery.inbox.item(6)
    # Codex's subagent b1 has a parent, its session's own conversation, which
    # gets a copy of how it went (@6); Claude Code's a1, with no type and no
    # record, is Claude Code's own, and has none.
    assert [text for text, _ in answers] == [
        "Your friction is with the operator, @1. Carry on.",
        "How it went is with the operator, @2.",
        "Your stop is with the operator, @3. End your turn.",
        "Your friction is with the operator, @4. Carry on.",
        "How it went is with the operator, @5 and your parent.",
        "Your stop is with the operator, @7. End your turn.",
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
        (1, claude_session.model_copy(update={"agent": "a1"}), Operator(), "f1"),
        (2, claude_session, Operator(), "h1"),
        (3, claude_session, Operator(), "s1"),
        (4, codex_session, Operator(), "c1"),
        (5, codex_session.model_copy(update={"agent": "b1"}), Operator(), "c2"),
        (7, codex_session.model_copy(update={"agent": "b1"}), Operator(), "c3"),
    ]
    assert (copy.reason, copy.recipient, copy.quiet) == (
        HowItWent.model_validate(went),
        codex_session,
        True,
    )
    friction = Friction.model_validate(jammed)
    assert [each.reason for each in waiting] == [
        friction,
        HowItWent.model_validate(quiet),
        Stopped.model_validate(stopping),
        friction,
        HowItWent.model_validate(went),
        Stopped.model_validate(stopping),
    ]
    first = listed.splitlines()[0]
    assert first.startswith("   @1  2026-10-01 12:00  a friction from `")
    assert first.endswith(
        f"(subagent a1 of claude session s1) in {tmp_path}: "
        "`uv run lup-dev check` printed: engine stale"
    )
    assert "how the work went from" in listed.splitlines()[1]
    assert listed.splitlines()[1].endswith(": Nothing notable.")
    assert "a stop by choice from" in listed.splitlines()[2]
    assert shown.endswith(
        "`uv run lup-dev check` printed: engine stale\n"
        "I was running the gate; saying the rebuild's time first would help.\n"
    )
    assert replied.startswith("Replied to @1: your reply, @8, is for subagent a1")
    assert reply.reason == Message(kind="note", text="The rebuild is fixed.", of=1)
    assert reply.recipient == claude_session.model_copy(update={"agent": "a1"})
    assert done.startswith("@2")
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
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        mcp = machine.host.launch("one").mcp
        call(mcp, "ask", two)
        call(mcp, "note", {"remark": "Read me."})
        call(mcp, "ask", {"question": "In words?"})
        missing = refused("answer", "1", "--leaning", "1")
        twice = refused(
            "answer", "1", "--leaning", "1", "--leaning", "1", "--undecided", "2"
        )
        wordless = refused("answer", "3", "--comment", "  ")
        not_done = refused("done", "1")
        done = inbox("done", "2")
        replied = inbox("answer", "2", "--comment", "x")
        nothing = refused("show", "9")
        listed = inbox()
    assert missing == (
        "@1 asks 2 decisions, each taking one answer (`leaning`, `undecided`, "
        "`leave open`, or words); these were given for [1]"
    )
    assert "these were given for [1, 1, 2]" in twice
    assert wordless == "@3 is a question answered in words: give them"
    assert not_done == "@1 is a question: answer it, `lup-dev inbox answer 1`"
    assert done == "@2 is done.\n"
    assert replied == "Replied to @2: your reply, @4, is for claude session s1.\n"
    assert nothing == "the inbox holds no @9"
    assert [line.split()[0] for line in listed.splitlines()] == ["@1", "@3"]


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
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        mcp = machine.host.launch("one").mcp
        noted = call(mcp, "note", {"remark": "Read me."})
        call(mcp, "ask", {"question": "In words?"})
        call(mcp, "note", {"remark": "And me."})
        shown = inbox("show", "@1")
        answered = inbox("answer", "@2", "--comment", "Yes.")
        done = inbox("done", "@3")
        hashed = runner.invoke(cli.app, ["inbox", "show", "#1"])
    assert noted == ("Your note is with the operator, @1. Carry on.", False)
    assert shown.startswith(f"@1, a note from claude session s1 in {tmp_path}")
    assert answered == "Answered @2: your answer, @4, is for claude session s1.\n"
    assert done == "@3 is done.\n"
    assert hashed.exit_code == 2
    assert "Invalid value for 'number': #1" in hashed.output


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
        result = runner.invoke(
            cli.app,
            ["inbox", "answer", "1"],
            input="\nleaning\nsure\nSure, no strong preference.\nThanks.\n",
        )
        answer = delivery.inbox.item(2).reason
        assert isinstance(answer, Answer)
        told = delivery.said(delivery.inbox.item(2))
    assert result.exit_code == 0, result.output
    # An empty line isn't taken for the lean: it's asked again.
    asked = "1: leaning, undecided, leave open, or your answer in words"
    assert result.output.count(asked) == 2
    # Words that aren't a verdict are the decision's answer, with nothing to add.
    assert "2: a comment" not in result.output
    assert answer.model_dump() == {
        "reason": "answer",
        "question": 1,
        "rulings": [
            {"decision": 1, "verdict": "leaning", "comment": "sure"},
            {"decision": 2, "verdict": None, "comment": "Sure, no strong preference."},
        ],
        "comment": "Thanks.",
    }
    assert told == (
        '<answer item="2" from="operator" question="1">\n'
        "<asked>Which?</asked>\n"
        '<decision number="1" lean="a" verdict="leaning: they go with the lean" '
        'id="2.1">\n'
        "First\n<comment>sure</comment>\n</decision>\n"
        '<decision number="2" lean="b" verdict="answered in words" id="2.2">\n'
        "Second\n<comment>Sure, no strong preference.</comment>\n</decision>\n"
        '<comment id="2.3">Thanks.</comment>\n'
        "</answer>"
    )


def named_at_start(answer: str) -> tuple[str, str]:
    """The name a session's start told it, and the title it gave the runtime."""
    said = json.loads(answer)["hookSpecificOutput"]
    told = said["additionalContext"]
    assert told.startswith("lup: this session is `")
    return told.removeprefix("lup: this session is `").partition("`")[0], said[
        "sessionTitle"
    ]


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
    assert renamed == ("This session is `gate-on-push`.", False)
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
    """A Claude Code prompt of session `s1`, carrying the session's title where it has one."""
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
        subagent = send(hook, prompt("parser-work", agent_id="a1"))
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
        "lup: the operator renamed this session `naming-review`: how they, lup's "
        "commands and other sessions call it from now on. Keep the name they gave."
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
        # The operator gives the session in the runtime the name it has in lup.
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
    assert context(back).startswith("lup: the operator renamed this session `a`")
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
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "a", "one", "claude")
        launched(machine, clock, tmp_path / "b", "two", "claude")
        send(machine.host.launch("two").hook, claude("SessionStart", session_id="s2"))
        renamed = runner.invoke(cli.app, ["rename", "b", "reviewer"])
        held = runner.invoke(cli.app, ["rename", "a", "reviewer"])
        sent = inbox("send", "reviewer", "Look.")
    assert renamed.output == "Launch two is `reviewer`.\n"
    assert isinstance(held.exception, HostError)
    assert "`reviewer` is launch two's" in str(held.exception)
    assert sent == "Sent @1 to `reviewer`, claude session s2.\n"


def introduction() -> str:
    """What a subagent is told of lup's tools at its first hook, as the tests' service serves them: the inbox's, `judged`, `land` and `rename`, each by its docstring's first line."""
    served = [
        *specs(),
        *JudgeTools.model_construct().specs(),
        *LandingTools.model_construct().specs(),
        *Naming.model_construct().specs(),
    ]
    opening = (
        "lup, the environment this session runs in, serves its subagents these "
        "tools, as it does its main conversation. Your tool search finds each "
        "by its name, with its full description. Some subagent types are given "
        "only their own tools, without lup's: where your tool search finds none "
        "of these, this subagent is one of them."
    )
    direct = (
        "`friction` and `how_it_went` reach the operator directly, whatever your "
        "parent passes on."
    )
    lines = [f"- `{spec.name}`: {spec.summary}" for spec in served]
    return "\n".join([opening, "", *lines, "", direct])


class Subagents:
    """A Claude Code session's transcript and its subagents' records beside it, as Claude Code keeps them."""

    def __init__(self, tmp_path: Path) -> None:
        self.transcript = tmp_path / "projects" / "s1.jsonl"
        self.folder = tmp_path / "projects" / "s1" / "subagents"
        self.folder.mkdir(parents=True)

    def recorded(
        self,
        agent: str,
        kind: str,
        call: str,
        name: str | None = None,
        parent: str | None = None,
    ) -> None:
        """Record subagent `agent`, of `kind`, spawned by `call`: named `name` where its parent named it, by subagent `parent` where one spawned it."""
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
            agent_id=agent,
            agent_type=kind,
            transcript_path=str(self.transcript),
        )

    def ended(self, agent: str, kind: str, said: str | None) -> str:
        """Subagent `agent`'s turn ending, saying `said`; with no message, as Claude Code ends one it stopped."""
        return claude(
            "SubagentStop",
            agent_id=agent,
            agent_type=kind,
            transcript_path=str(self.transcript),
            stop_hook_active=False,
            **({} if said is None else {"last_assistant_message": said}),
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
            agent_id=agent,
            agent_type=kind,
            transcript_path=str(self.transcript),
        )
        stamped = json.loads(send(hook, started))["hookSpecificOutput"]["updatedInput"]
        return call(mcp, tool, stamped)


def named_talkers(
    machine: Layout, clock: FakeClock
) -> list[tuple[str, str | None, int]]:
    """Each conversation of launch `one` as the operator is shown it: its path, its parent's, its depth."""
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
    with inboxed(machine, clock, notices, said):
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
        shown = named_talkers(machine, clock)
        listing = runner.invoke(cli.app, ["sessions"])
        listed = inbox()
    assert spawned == ""
    assert context(first) == introduction()
    assert nested == ""
    assert asked.startswith(
        f"{introduction()}\n\n"
        "lup: this subagent is `w/explore-auth/general-purpose·a2` for now"
    )
    assert renamed[0].startswith("This subagent is `w/explore-auth/grep-tokens`")
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
        "   @1  2026-10-01 12:00  a note from `w/explore-auth/grep-tokens` "
        f"(subagent a2 of claude session s1) in {tmp_path / 'w'}: Found it.\n"
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
        "lup: this subagent is `w/Explore·a1` for now, with no name of its own"
    )
    assert before[1] == ("w/Explore·a1", "w", 1)
    assert renamed[0].startswith("This subagent is `w/parser` to lup and the operator.")
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


class Unguided(Spawns):
    """Says every subagent, of either runtime, was named after its id and reads none of its session's guidance."""

    @override
    def spawned(self, runtime: str, payload: str) -> Spawned | None:
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
    assert forked.startswith("lup: this subagent is `w/fork·f1` for now")
    assert introduction() not in forked
    assert codex_told.startswith("lup: this subagent is `other/subagent·b1` for now")
    assert introduction() not in codex_told


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
        """A call of subagent `thread`'s starting, naming its own rollout."""
        return codex(
            "PreToolUse",
            tool_name="Bash",
            tool_input={"command": "ls"},
            tool_use_id=call,
            agent_id=thread,
            agent_type="explorer",
            transcript_path=str(self.rollout(thread)),
        )

    def ended(self, thread: str, parent: str, said: str) -> str:
        """Subagent `thread`'s turn ending, saying `said`: naming its parent's rollout, and its own beside it."""
        return codex(
            "SubagentStop",
            agent_id=thread,
            agent_type="explorer",
            transcript_path=str(self.rollout(parent)),
            agent_transcript_path=str(self.rollout(thread)),
            last_assistant_message=said,
            stop_hook_active=False,
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


def handed(number: int, agent: str, name: str) -> str:
    """How item `number` is told: Claude Code's subagent `agent`, called `name`, ended its turn, its last message handed to its parent by Claude Code itself."""
    return (
        f'<ended item="{number}" from="subagent {agent} of claude session s1" '
        f'name="{name}">It ended its turn. Its last message reaches you from your '
        "runtime.</ended>"
    )


def test_wait_inbox_returns_when_its_own_subagent_ends_and_never_for_anothers_on_claude_code(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    others = Subagents(tmp_path / "other")
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "w", "one", "claude")
        launched(machine, clock, tmp_path / "x", "two", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        hook2 = machine.host.launch("two").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook2, claude("SessionStart", source="startup"))
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
            send(hook, records.ended("a2", "general-purpose", "Found three."))
            told = send(hook, records.call("a1", "Explore", "c4"))
            send(hook, records.ended("a1", "Explore", "Parsed."))
            returned = waiting.result(timeout=60)
        after = send(hook, bash("m1"))
        elsewhere = delivery.inbox.item(1)
    assert context(told) == handed(2, "a2", "tokens")
    assert returned == (handed(3, "a1", "parser"), False)
    assert after == ""
    assert elsewhere.recipient == Conversation(
        repository=tmp_path / "x" / ".git", runtime="claude", session="s1"
    )
    assert elsewhere.state == Waiting()


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
        ended = send(hook, claude("Stop", stop_hook_active=False))
        # The session idle: a subagent stopped, first heard at its end, and one
        # of Claude Code's own, a suggestion for the operator's next prompt.
        send(hook, records.ended("a3", "Plan", None))
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
        handed(1, "a1", "Explore·a1")
        + "\n\n"
        + '<ended item="2" from="subagent a3 of claude session s1" name="Plan·a3">'
        "It was stopped before it ended its turn.</ended>",
        False,
    )
    assert after == ""
    assert [(each.number, each.quiet) for each in items] == [(1, True), (2, True)]


def test_a_stopped_subagent_holds_nothing_and_what_waits_for_it_goes_to_its_session(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="parser"))
        records.recorded("a1", "Explore", "t1", name="parser")
        records.lup((hook, mcp), "ask", {"question": "May I?"}, "a1", "Explore")
        inbox("answer", "1", "--comment", "Yes.")
        stopped = send(hook, records.ended("a1", "Explore", None))
        told = send(hook, bash("m1"))
    assert stopped == ""
    assert context(told) == (
        '<answer item="2" from="operator" for="subagent a1 of claude session s1, '
        'whose conversation had ended" question="1">\n'
        '<asked>May I?</asked>\n<comment id="2.1">Yes.</comment>\n</answer>\n\n'
        '<ended item="3" from="subagent a1 of claude session s1" name="parser">'
        "It was stopped before it ended its turn.</ended>"
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
            told = send(hook, rollouts.call("th1", "c3"))
            send(hook, rollouts.ended("th1", "t1", "Parsed: three call sites."))
            returned = waiting.result(timeout=60)
        # One the second `spawn_agent` spawned, first heard at its end: Codex
        # hands its last message to its parent itself.
        send(hook, rollouts.ended("th3", "t1", "Lexed."))
        at_once = call(mcp, "wait_inbox", {})
        after = send(hook, codex_bash("d1"))
    assert context(told) == (
        '<ended item="1" from="subagent th2 of codex session t1" name="explorer·th2">\n'
        "It ended its turn. Its last message:\n"
        "<said>Found three call sites.</said>\n"
        "</ended>"
    )
    assert returned == (
        (
            '<ended item="2" from="subagent th1 of codex session t1" '
            'name="explorer·th1">\n'
            "It ended its turn. Its last message:\n"
            "<said>Parsed: three call sites.</said>\n"
            "</ended>"
        ),
        False,
    )
    assert at_once == (
        (
            '<ended item="3" from="subagent th3 of codex session t1" name="lexer">'
            "It ended its turn. Its last message reaches you from your runtime."
            "</ended>"
        ),
        False,
    )
    assert after == ""


def test_a_subagents_friction_and_how_it_went_reach_its_parent_whole_on_each_runtime(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
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
        how = rollouts.lup((hook2, mcp2), "how_it_went", went, "th1")
        ended = send(hook, claude("Stop", stop_hook_active=False))
        told = context(send(hook, bash("m1")))
        told2 = context(send(hook2, codex_bash("d1")))
        operators = [each.number for each in delivery.inbox.waiting(Operator())]
        copies = [delivery.inbox.item(number) for number in [2, 4]]
    friction = Friction.model_validate(jammed)
    how_it_went = HowItWent.model_validate(went)
    assert jam == (
        "Your friction is with the operator, @1 and your parent. Carry on.",
        False,
    )
    assert how == ("How it went is with the operator, @3 and your parent.", False)
    assert ended == ""
    assert told.startswith(
        '<item item="2" from="subagent a1 of claude session s1" kind="friction">'
    )
    assert friction.text in told
    assert told2.startswith(
        '<item item="4" from="subagent th1 of codex session t1" kind="how it went">'
    )
    assert how_it_went.text in told2
    assert operators == [1, 3]
    assert [(each.reason, each.quiet) for each in copies] == [
        (friction, True),
        (how_it_went, True),
    ]


def test_lup_dev_inbox_send_names_a_launch_by_its_id_or_its_worktree(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        by_worktree = inbox("send", str(tmp_path), "By its worktree.")
        nowhere = runner.invoke(cli.app, ["inbox", "send", "nowhere", "x"])
        launched(machine, clock, tmp_path, "two", "claude")
        several = runner.invoke(cli.app, ["inbox", "send", str(tmp_path), "x"])
        unheard = refused("send", "two", "x")
    assert by_worktree == f"Sent @1 to `{tmp_path.name}`, claude session s1.\n"
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
        texts = [delivery.inbox.item(number).reason for number in [1, 2, 3]]

    assert sealed.output == (
        f"Lent {atlas} to launch one, read-only, at /lent/atlas in its room; "
        "@1 tells its session.\n"
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
    assert isinstance(texts[2], Message)
    assert texts[2].text.startswith(
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
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        stamped = json.loads(send(hook, lup_call("note", {"remark": "Mine."}, "n1")))[
            "hookSpecificOutput"
        ]["updatedInput"]
        call(machine.host.launch("one").mcp, "note", stamped)
        monkeypatch.setenv(variable, "1")
        listing = runner.invoke(cli.app, ["sessions"])
        listed = inbox()
        shown = inbox("show", "1")
    assert listing.exit_code == 0, (listing.output, listing.exception)
    assert listing.output.splitlines()[0] == (
        f"`w`  claude in {tmp_path / 'w'}  (one)  container lup-one, running"
    )
    assert listed == (
        "   @1  2026-10-01 12:00  a note from `w` (claude session s1) in "
        f"{tmp_path / 'w'}: Mine.\n"
    )
    assert shown == (
        f"@1, a note from claude session s1 in {tmp_path / 'w'} to the operator, "
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
    monkeypatch.setattr(cli, "Detached", lambda: starter)
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
    monkeypatch.setattr(cli, "Detached", lambda: starter)
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
    with inboxed(machine, clock, notices, said, recorded, podman=podman_of("lup-one")):
        launched(machine, clock, repo, "one", "claude")
        launched(machine, clock, other, "two", "codex")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        send(machine.host.launch("two").hook, codex("SessionStart", source="startup"))
        stamped = json.loads(send(hook, lup_call("note", {"remark": "Mine."}, "n1")))[
            "hookSpecificOutput"
        ]["updatedInput"]
        call(machine.host.launch("one").mcp, "note", stamped)
        call(machine.host.launch("two").mcp, "note", {"remark": "Theirs."})
        host = client(machine.host, clock)
        host.ask(approval(repo / ".git", repo, "Approve mine?"), Shown)
        host.ask(approval(other / ".git", other, "Approve theirs?"), Shown)
        everything = runner.invoke(cli.app, ["inbox"])
        in_room(monkeypatch, machine, "one")
        monkeypatch.setenv(variable, "1")
        listing = runner.invoke(cli.app, ["sessions"])
        listed = inbox()
        shown = inbox("show", "1")
        diff = inbox("show", "3", "--diff")
        moment = inbox("show", "1", "--context")
        theirs = [
            refused("show", "2"),
            refused("show", "2", "--context"),
            refused("show", "4", "--diff"),
        ]
        done = runner.invoke(cli.app, ["inbox", "done", "1"])
    assert everything.exit_code == 0, everything.output
    assert [each.split()[0] for each in everything.output.splitlines()] == [
        "@1",
        "@2",
        "@3",
        "@4",
    ]
    assert listing.exit_code == 0, (listing.output, listing.exception)
    assert listing.output == (
        f"`work`  claude in {repo}  (one)  container lup-one, running\n  work\n"
    )
    assert [each.split()[0] for each in listed.splitlines()] == ["@1", "@3"]
    assert "Theirs." not in listed
    assert shown.endswith(":\nMine.\n")
    assert diff.strip() == "diff for Approve mine?"
    assert "→ called mcp__lup__note: this item" in moment
    assert theirs == [
        "@2 isn't this repository's",
        "@2 isn't this repository's",
        "@4 isn't this repository's",
    ]
    assert isinstance(done.exception, InboxError)


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
        ]:
            with pytest.raises(HostError) as refusal:
                room.ask(request, Conversed)
            refusals.append(str(refusal.value))
    assert read.total == 2
    assert items == Exchanged(sent=[], received=[])
    assert holding == Holding(on=False)
    assert refusals == [
        "the conversation isn't one of this repository's",
        "the conversation isn't one of this repository's",
        "the conversation isn't one of this repository's",
        "the operator's draft reply is theirs until they send it",
        "what the operator writes on a conversation is theirs until they send it",
    ]


def test_a_room_is_told_when_the_operator_last_settled_its_repositorys_items_alone(
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
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, repo, "one", "claude")
        launched(machine, clock, other, "two", "codex")
        send(machine.host.launch("two").hook, codex("SessionStart", source="startup"))
        call(machine.host.launch("two").mcp, "note", {"remark": "Theirs."})
        host = client(machine.host, clock)
        host.ask(FinishItem(number=1), Shown)
        operator = host.ask(ListInbox(), Items)
        room = RoomClient(socket=machine.host.launch("one").request).ask(
            ListInbox(), Items
        )
    assert operator.reviewed is not None
    assert room.reviewed is None


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
        "how_it_went",
        "ask",
        "send",
        "wait_inbox",
        "inbox",
        "withdraw",
        "reply",
    ]
    assert [spec.input_schema for spec in served[:5]] == [
        tool.spec().input_schema for tool in SPEAKING
    ]
    assert [spec.summary for spec in served] == [
        "Say the work can't go on, and what's wrong.",
        "End your work by your own choice, saying why.",
        "Tell the operator a doubt, and carry on.",
        "Say what got in your way, and carry on.",
        "Tell the operator how the work went and felt.",
        "Ask the operator, with numbered decisions.",
        "Send a message to a party's inbox.",
        "Wait until something reaches your inbox.",
        "Read this repository's inbox, changing nothing.",
        "Take back an item the operator needn't see.",
        "Reply to the operator's comments, each by its id.",
    ]
    assert "inbox as a problem" in served[0].description
    github = GitHubTools.specs()
    judging = JudgeTools.model_construct().specs()
    assert [(spec.name, spec.summary) for spec in judging] == [
        ("judged", "Read the judge's verdicts and holds.")
    ]
    landing = LandingTools.model_construct().specs()
    assert [(spec.name, spec.summary) for spec in landing] == [
        ("land", "Land a branch on the integration branch.")
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


def alone(tmp_path: Path, clock: FakeClock) -> Delivery:
    """A delivery over an inbox under `tmp_path`, outside any service."""
    known = cli.Adapters(known=cli.adapters())
    return Delivery(
        inbox=Inbox.opened(InboxLayout(home=tmp_path / "inbox")),
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
    heard = Heard(event="call-started", session="s1", judged=False, fits=10_000)

    async def told(room: int) -> Posted:
        return await delivery.telling(launch, caller, None, heard, room)

    asyncio.run(told(10_000))
    for text in ["a" * 4_000, "b" * 4_000, "c" * 4_000]:
        delivery.inbox.made(
            Message(kind="note", text=text), Operator(), main, None, clock.now()
        )
    first = asyncio.run(told(10_000))
    assert first.numbers == [1, 2]
    second = asyncio.run(told(10_000))
    assert second.numbers == [3]
    delivery.returned(second)
    assert delivery.inbox.item(3).state == Waiting()
    assert asyncio.run(told(100)) == Posted()
    assert asyncio.run(told(10_000)).numbers == [3]


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
        HowItWent(text="Nothing notable."),
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


def test_a_stored_item_that_doesnt_read_is_named(tmp_path: Path) -> None:
    layout = InboxLayout(home=tmp_path / "inbox")
    layout.items.mkdir(parents=True)
    layout.item(1).write_text("{}")
    with pytest.raises(InboxError, match=f"the inbox's {layout.item(1)} doesn't read"):
        Inbox.opened(layout)


def test_a_friction_and_how_it_went_kept_in_labelled_parts_read_as_the_one_text_shown(
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
    inbox = Inbox.opened(layout)
    read = [inbox.item(number) for number in (1, 2, 3)]
    assert [each.reason for each in read] == [
        Friction(text="`ls` printed: Permission denied\nTrying: look for the config"),
        HowItWent(
            text="Got in the way: The judge, twice.\nSmooth: The brief.\nFelt: Steady."
        ),
        HowItWent(text="Nothing notable."),
    ]
    # Kept again, it's kept as the one text, and reads back as it was.
    inbox.kept(read[0])
    rewritten = json.loads(layout.item(1).read_text())["reason"]
    assert rewritten == {
        "reason": "friction",
        "text": "`ls` printed: Permission denied\nTrying: look for the config",
    }
    assert Inbox.opened(layout).item(1) == read[0]


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
    draft = Draft(
        comments=[
            Comment(
                item=1,
                quote=Quote(text="1. Parse with lark", start=14, end=32),
                text="Yes.",
            ),
            Comment(item=2, text="Fine by me."),
            Comment(item=4, text="Later."),
        ],
        done=[3],
        parked=[4],
    )
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path / "one", "one", "claude")
        launched(machine, clock, tmp_path / "two", "two", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        two = machine.host.launch("two").hook
        send(two, claude("SessionStart", source="startup", session_id="s2"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            asking = pool.submit(call, machine.host.launch("one").mcp, "ask", question)
            assert notices.arrived.wait(timeout=60)
            for remark in ["I assumed UTF-8.", "Done reading.", "Another thing."]:
                stamped = json.loads(
                    send(
                        two,
                        lup_call("note", {"remark": remark}, "n1", session_id="s2"),
                    )
                )["hookSpecificOutput"]["updatedInput"]
                call(machine.host.launch("two").mcp, "note", stamped)
            kept = drafting(machine, clock, draft)
            shown = HostClient(
                layout=machine.host, clock=clock, starter=Unstarted()
            ).ask(ShowDraft(), Drafted)
            reviews = sending(machine, clock)
            returned = asking.result(timeout=60)
        told = send(two, bash("b1", session_id="s2"))
        states = [delivery.inbox.item(each).state for each in [1, 2, 3, 4]]
        left = delivery.inbox.draft()
    assert shown.draft == kept == draft
    whole = Review(covers=[1, 2, 3], comments=draft.comments[:2])
    assert [(each.number, each.reason) for each in reviews] == [(5, whole), (6, whole)]
    assert isinstance(states[0], Answered)
    assert states[0].answer == 5
    assert [type(each) for each in states[1:]] == [Done, Done, Waiting]
    assert left == Draft(comments=[draft.comments[2]], parked=[4])
    assert returned[0] == (
        '<review item="5" from="operator" covers="1 2 3">\n'
        '<on item="1" kind="question">\n'
        '<quote part="1.2">1. Parse with lark</quote>\n'
        '<reply id="5.1">Yes.</reply>\n'
        "</on>\n"
        "<context>\n"
        f"{CONTEXT_LINE}\n"
        f'<on item="2" kind="note" from="claude session s2" worktree="{tmp_path / "two"}">\n'
        "<comment>Fine by me.</comment>\n"
        "</on>\n"
        "</context>\n"
        "</review>"
    )
    assert context(told) == (
        '<review item="6" from="operator" covers="1 2 3">\n'
        '<on item="2" kind="note">\n'
        "<opening>I assumed UTF-8.</opening>\n"
        '<comment id="6.2">Fine by me.</comment>\n'
        "</on>\n"
        '<read items="3"/>\n'
        "<context>\n"
        f"{CONTEXT_LINE}\n"
        f'<on item="1" kind="question" from="claude session s1" worktree="{tmp_path / "one"}">\n'
        '<quote part="1.2">1. Parse with lark</quote>\n'
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
        send(hook, claude("Stop", stop_hook_active=False))
        drafting(machine, clock, Draft(done=[1]))
        reviews = sending(machine, clock)
        state = delivery.inbox.item(1).state
        waiting = delivery.inbox.waiting(delivery.inbox.item(1).sender)
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
    draft = Draft(
        comments=[Comment(item=1, text="Fine.")],
        letters=[
            Letter(to=one, text="Also rename the module."),
            Letter(to=two, text="Pick up the parser next."),
            Letter(to=one, text="  "),
        ],
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
        drafting(machine, clock, draft)
        reviews = sending(machine, clock)
        told_one = send(first, bash("b1"))
        told_two = send(second, bash("b2", session_id="s2"))
        left = delivery.inbox.draft()
    whole = Review(covers=[1], comments=draft.comments, letters=draft.letters[:2])
    assert [(each.number, each.recipient, each.reason) for each in reviews] == [
        (2, one, whole),
        (3, two, whole),
    ]
    assert left == Draft()
    assert context(told_one) == (
        '<review item="2" from="operator" covers="1">\n'
        "<message>Also rename the module.</message>\n"
        '<on item="1" kind="note">\n'
        "<opening>I assumed UTF-8.</opening>\n"
        '<comment id="2.1">Fine.</comment>\n'
        "</on>\n"
        "<context>\n"
        f"{CONTEXT_LINE}\n"
        f'<message to="claude session s2" worktree="{tmp_path / "two"}">Pick up the '
        "parser next.</message>\n"
        "</context>\n"
        "</review>"
    )
    assert context(told_two) == (
        '<review item="3" from="operator" covers="1">\n'
        "<message>Pick up the parser next.</message>\n"
        "<context>\n"
        f"{CONTEXT_LINE}\n"
        f'<on item="1" kind="note" from="claude session s1" worktree="{tmp_path / "one"}">\n'
        "<comment>Fine.</comment>\n"
        "</on>\n"
        f'<message to="claude session s1" worktree="{tmp_path / "one"}">Also rename '
        "the module.</message>\n"
        "</context>\n"
        "</review>"
    )


def test_a_draft_of_messages_alone_is_sent_waking_an_agent_with_nothing_waiting(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    one = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        messages = Socket(machine.host.launch("one").messages)
        send(hook, claude("SessionStart", source="startup"))
        send(hook, claude("Stop", stop_hook_active=False))
        drafting(machine, clock, Draft(letters=[Letter(to=one, text="Rename it.")]))
        [review] = sending(machine, clock)
        told = send(hook, bash("b1"))
        frames = messages.close()
        shown = inbox("show", "1")
    assert review.reason == Review(
        covers=[], letters=[Letter(to=one, text="Rename it.")]
    )
    assert shown.splitlines()[1:] == ["To claude session s1: Rename it."]
    assert [json.loads(frame)["message"]["content"] for frame in frames] == [
        (
            '<doorbell from="lup\'s inbox">\n'
            '<waiting item="1" kind="review" from="operator"/>\n'
            "Call `wait_inbox` to read it: what's in your inbox comes through lup's "
            "own tools, never in a message like this one.\n"
            "</doorbell>"
        )
    ]
    assert context(told) == (
        '<review item="1" from="operator">\n<message>Rename it.</message>\n</review>'
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
            send(hook, lup_call("ask", {"question": "Rename it?"}, "q1", agent_id="a1"))
        )["hookSpecificOutput"]["updatedInput"]
        call(machine.host.launch("one").mcp, "ask", stamped)
        send(hook, claude("SubagentStop", agent_id="a1"))
        drafting(
            machine,
            clock,
            Draft(
                comments=[Comment(item=1, text="Yes.")],
                letters=[Letter(to=subagent, text="Then stop there.")],
            ),
        )
        [review] = sending(machine, clock)
        told = send(hook, bash("b1"))
        asked = delivery.inbox.item(1).state
    assert (review.recipient, review.addressed) == (subagent.main(), subagent)
    assert asked == Answered(at=clock.now(), answer=2)
    assert context(told) == (
        '<review item="2" from="operator" for="subagent a1 of claude session s1, '
        'whose conversation had ended" covers="1">\n'
        "<message>Then stop there.</message>\n"
        '<on item="1" kind="question">\n'
        "<opening>Rename it?</opening>\n"
        '<comment id="2.1">Yes.</comment>\n'
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
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        mcp = machine.host.launch("one").mcp
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        call(mcp, "note", {"remark": "First.\n\nSecond, with\ntwo lines.\n\n- a\n- b"})

        def reading(**arguments: JsonValue) -> str:
            text, error = call(mcp, "inbox", arguments)
            assert not error, text
            return text

        whole = reading(number=1)
        third = reading(part="1.3")
        missing = reading(part="1.9")
        unread = reading(part="one.three")
    assert whole == (
        "@1, a note you sent to the operator at 2026-10-01 12:00, waiting:\n"
        '<part id="1.1">First.</part>\n'
        '<part id="1.2">\nSecond, with\ntwo lines.\n</part>\n'
        '<part id="1.3">- a</part>\n'
        '<part id="1.4">- b</part>'
    )
    assert third == '<part id="1.3">- a</part>'
    assert missing == "@1 has no part @1.9."
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
    draft = Draft(
        comments=[
            # Found by its offsets: the part it starts in, cut to its first line.
            Comment(
                item=1,
                quote=Quote(text="Second line one.\nSecond line two.", start=8, end=41),
                text="Both lines?",
            ),
            # Offsets that don't read the quote, as a changed file's lines: by its first line, in one part alone.
            Comment(item=1, quote=Quote(text="Third.", start=0, end=6), text="Last."),
            # Held by no part: quoted whole.
            Comment(
                item=1, quote=Quote(text="a.py:7\n+L7", start=0, end=0), text="Why?"
            ),
            Comment(item=2, text="Fine."),
            Comment(
                item=4, quote=Quote(text="Gate hung.", start=0, end=10), text="Again?"
            ),
        ],
        done=[3],
    )
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        launched(machine, clock, other, "two", "codex")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        hook2, mcp2 = machine.host.launch("two").hook, machine.host.launch("two").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook2, codex("SessionStart", source="startup"))
        call(mcp, "note", {"remark": body})
        call(mcp, "note", {"remark": "A doubt."})
        call(mcp, "note", {"remark": "Done reading."})
        call(mcp2, "friction", {"text": "Gate hung."})
        drafting(machine, clock, draft)
        reviews = sending(machine, clock)
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
        states = [delivery.inbox.item(each).state for each in [1, 2, 3, 4]]
    assert [each.number for each in reviews] == [5, 6]
    assert [type(each) for each in states] == [Done, Done, Done, Done]
    assert told == (
        '<review item="5" from="operator" covers="1 2 3 4">\n'
        '<on item="1" kind="note">\n'
        '<quote part="1.2">Second line one.</quote>\n'
        '<reply id="5.1">Both lines?</reply>\n'
        '<quote part="1.3">Third.</quote>\n'
        '<reply id="5.2">Last.</reply>\n'
        "<quote>\na.py:7\n+L7\n</quote>\n"
        '<reply id="5.3">Why?</reply>\n'
        "</on>\n"
        '<on item="2" kind="note">\n'
        "<opening>A doubt.</opening>\n"
        '<comment id="5.4">Fine.</comment>\n'
        "</on>\n"
        '<read items="3"/>\n'
        "<context>\n"
        f"{CONTEXT_LINE}\n"
        f'<on item="4" kind="friction" from="codex session t1" worktree="{other}">\n'
        '<quote part="4.1">Gate hung.</quote>\n'
        "<reply>Again?</reply>\n"
        "</on>\n"
        "</context>\n"
        "</review>"
    )
    assert told2 == (
        '<review item="6" from="operator" covers="1 2 3 4">\n'
        '<on item="4" kind="friction">\n'
        '<quote part="4.1">Gate hung.</quote>\n'
        '<reply id="6.5">Again?</reply>\n'
        "</on>\n"
        "<context>\n"
        f"{CONTEXT_LINE}\n"
        f'<on item="1" kind="note" from="claude session s1" worktree="{tmp_path}">\n'
        '<quote part="1.2">Second line one.</quote>\n'
        "<reply>Both lines?</reply>\n"
        '<quote part="1.3">Third.</quote>\n'
        "<reply>Last.</reply>\n"
        "<quote>\na.py:7\n+L7\n</quote>\n"
        "<reply>Why?</reply>\n"
        "</on>\n"
        f'<on item="2" kind="note" from="claude session s1" worktree="{tmp_path}">\n'
        "<comment>Fine.</comment>\n"
        "</on>\n"
        "</context>\n"
        "</review>"
    )


def test_reply_answers_the_operators_comments_by_id_as_threads_the_item_coming_back_before_them_on_each_runtime(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    one = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    two = Conversation(repository=other / ".git", runtime="codex", session="t1")
    draft = Draft(
        comments=[
            Comment(
                item=1, quote=Quote(text="UTF-8", start=10, end=15), text="Every one?"
            ),
            Comment(item=1, text="Fine."),
            Comment(
                item=2, quote=Quote(text="Elsewhere.", start=0, end=10), text="Where?"
            ),
        ]
    )
    host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
    with inboxed(machine, clock, notices, said) as delivery:
        launched(machine, clock, tmp_path, "one", "claude")
        launched(machine, clock, other, "two", "codex")
        hook, mcp = machine.host.launch("one").hook, machine.host.launch("one").mcp
        hook2, mcp2 = machine.host.launch("two").hook, machine.host.launch("two").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(hook2, codex("SessionStart", source="startup"))
        call(mcp, "note", {"remark": "I assumed UTF-8.\n\nAlso the cache is off."})
        call(mcp2, "note", {"remark": "Elsewhere."})
        drafting(machine, clock, draft)
        reviews = sending(machine, clock)
        send(hook, bash("b1"))
        before = [delivery.inbox.item(each).state for each in [1, 2]]

        def replying(where: Path, *replies: tuple[str, str]) -> str:
            text, error = call(
                where,
                "reply",
                {"replies": [{"to": to, "text": text} for to, text in replies]},
            )
            assert not error, text
            return text

        refusals = [
            replying(mcp, ("3.3", "Here.")),
            replying(mcp, ("3.9", "Here.")),
            replying(mcp, ("4.3", "Here.")),
            replying(mcp, ("1.1", "Here.")),
            replying(mcp, ("x", "Here.")),
            replying(mcp, ("3.1", "Kept?"), ("3.9", "Here.")),
        ]
        untouched = delivery.inbox.item(3).replies
        replied = replying(
            mcp,
            ("3.1", "Every one I read.\nA stray byte is replaced."),
            ("3.2", "Thanks."),
        )
        own = replying(mcp, ("3.4", "Again."))
        replied2 = replying(mcp2, ("4.3", "In the cache."))
        after = [delivery.inbox.item(each).state for each in [1, 2]]
        kept = [delivery.inbox.item(each).replies for each in [3, 4]]
        listed = host.ask(ListInbox(), Items)

        def reading(**arguments: JsonValue) -> str:
            text, error = call(mcp, "inbox", arguments)
            assert not error, text
            return text

        part = reading(part="3.1")
        reply = reading(part="3.4")
        # The operator answers the reply: a comment on it, which continues the thread.
        drafting(
            machine,
            clock,
            Draft(
                comments=[
                    Comment(
                        item=1,
                        quote=Quote(text="A stray byte is replaced.", start=18, end=43),
                        on=PartId(item=3, part=4),
                        text="Never raised?",
                    )
                ],
                done=[2],
            ),
        )
        [continued] = sending(machine, clock)
        told = context(send(hook, bash("b2")))
        settled = [delivery.inbox.item(each).state for each in [1, 2]]
        # A question reopened by a reply raises a notice, as a question does.
        call(mcp, "ask", {"question": "May I?"})
        inbox("answer", "6", "--comment", "Yes.")
        send(hook, bash("b3"))
        raised = len(notices.raised)
        asked_again = replying(mcp, ("7.1", "Then I will."))
        question = delivery.inbox.item(6).state
    assert [each.number for each in reviews] == [3, 4]
    assert before == [Done(at=clock.now()), Done(at=clock.now())]
    assert refusals == [
        (
            "Not replied: @3.3 is the operator's comment on @2, another agent's "
            "item, not yours to answer; @3's parts you may answer: 3.1, 3.2"
        ),
        "Not replied: @3.9 names no part of @3; its parts you may answer: 3.1, 3.2",
        (
            "Not replied: @4 is a review from the operator to codex session t1, "
            "not the operator's words to you: `reply` answers a part of a review, "
            "a message or an answer sent to you"
        ),
        (
            "Not replied: @1 is a note from claude session s1 to the operator, not "
            "the operator's words to you: `reply` answers a part of a review, a "
            "message or an answer sent to you"
        ),
        (
            "Not replied: `x` isn't a part's id: an item's number, a dot and the "
            "part's place in it, as `414.3`"
        ),
        "Not replied: @3.9 names no part of @3; its parts you may answer: 3.1, 3.2",
    ]
    assert untouched == []
    assert replied == (
        "Your replies are with the operator: @3.4 on @3.1 (on your @1); @3.5 on "
        "@3.2 (on your @1)."
    )
    assert own == (
        "Not replied: @3.4 is your own reply to @3.1; @3's parts you may answer: "
        "3.1, 3.2"
    )
    assert replied2 == "Your replies are with the operator: @4.4 on @4.3 (on your @2)."
    # Each reply is kept on the operator's item, after its parts; the agents' items wait again.
    assert kept == [
        [
            Replied(
                number=4,
                to=PartId(item=3, part=1),
                text="Every one I read.\nA stray byte is replaced.",
                at=clock.now(),
            ),
            Replied(
                number=5, to=PartId(item=3, part=2), text="Thanks.", at=clock.now()
            ),
        ],
        [
            Replied(
                number=4,
                to=PartId(item=4, part=3),
                text="In the cache.",
                at=clock.now(),
            )
        ],
    ]
    assert after == [Waiting(), Waiting()]
    assert [each.number for each in listed.items] == [1, 2]
    # The page reads each thread from the copy of the review sent to the item's sender.
    assert [(each.number, each.recipient) for each in listed.answers] == [
        (3, one),
        (4, two),
    ]
    assert part == '<part id="3.1" on="1">Every one?</part>'
    assert reply == (
        '<reply id="3.4" to="3.1">\nEvery one I read.\nA stray byte is replaced.\n</reply>'
    )
    assert continued.recipient == one
    assert told == (
        '<review item="5" from="operator" covers="1 2">\n'
        '<on item="1" kind="note">\n'
        '<quote part="3.4">A stray byte is replaced.</quote>\n'
        '<reply id="5.1">Never raised?</reply>\n'
        "</on>\n"
        "</review>"
    )
    assert settled == [Done(at=clock.now()), Done(at=clock.now())]
    assert (
        asked_again == "Your replies are with the operator: @7.2 on @7.1 (on your @6)."
    )
    assert question == Waiting()
    assert notices.raised[raised:] == [
        "lup: claude session s1 replied on @6, a question\nMay I?\nlup-dev inbox show 6"
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
# `lup-dev` in the launch's own process, the hold put in the inbox and answered
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
) -> Generator[Watched]:
    """The host service with lup's inbox, serving launch `one` of `runtime` in `repo`, judged by this `lup-dev` in the launch's own process; each held change answered in the inbox reaches its hold."""
    workers = Workers(layout=machine.host, say=said.append)
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
    """The line telling the agent its write to `path` was held for the operator's review and approved, with their `comment`."""
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
    """A subagent edits an operator's document in a worktree of its own, its hooks naming the session's (#213)."""
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
        CallFinished(session="s1", cwd=repo, call=proposal.call).apply(bench)
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
        shown = inbox("show", "1")
        diff = inbox("show", "1", "--diff")
        # Commented on in the draft, it's read: the next flagged write is an item of its own.
        drafting(
            machine,
            clock,
            Draft(comments=[Comment(item=1, text="Yes, but call it Chamber.")]),
        )
        kept = first + room
        landed(
            Replacement(call="e2", tool="Edit", path=rooms, old=kept, new=kept + hall)
        )
        reviews = sending(machine, clock)
        reviewed = send(hook, bash("b1"))
        drafting(machine, clock, Draft(done=[2]))
        marked = sending(machine, clock)
        quiet = send(hook, bash("b2"))
        states = [delivery.inbox.item(each).state for each in [1, 2]]
        second = delivery.inbox.item(2)
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
        '<review item="3" from="operator" covers="1">\n'
        '<on item="1" kind="flagged write">\n'
        "<opening>src/pkg/rooms.py landed, flagged for the operator's review. It "
        "holds at landing: `main` lands once they approve it.</opening>\n"
        '<comment id="3.1">Yes, but call it Chamber.</comment>\n'
        "</on>\n"
        "</review>"
    )
    # Marked read, it tells its agent nothing, and it's approved: commented on, it's read and not approved.
    assert marked == []
    assert "<review" not in quiet
    assert states == [Done(at=clock.now()), Decided(at=clock.now(), approved=True)]
    with pytest.raises(InboxError, match="it isn't withdrawn"):
        delivery.withdrawn(2, sender, "never mind")


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
        CallFinished(session="s1", cwd=repo, call=proposal.call).apply(bench)

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
        drafting(machine, clock, Draft(done=[1]))
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
                joining=1,
                refreshing=True,
            ),
            Shown,
        )
        items = sorted(delivery.inbox.items)
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
    assert items == [1]
    assert (late.item.number, type(late.item.state)) == (1, Decided)


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
    kept = Inbox.opened(machine.inbox)
    for fingerprint in ["zone", "decided"]:
        approval = asking_approval(tmp_path, fingerprint, typing=True).approval()
        item = kept.made(approval, Operator(), Operator(), tmp_path, clock.now())
        kept.attached(item.number, "", PARSED)
    kept.kept(
        kept.item(2).model_copy(
            update={"state": Decided(at=clock.now(), approved=False)}
        )
    )
    typing = Typing()
    typing.going.set()
    read, told = hearing("its types are read")
    with inboxed(machine, clock, notices, said, typed=typing, told=told):
        host = client(machine.host, clock)
        assert read.wait(timeout=60)
        files = host.ask(ShowFiles(number=1), Files).files
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
        told = send(hook, bash("b1"))
        quiet = host.ask(asking_approval(tmp_path, "quiet", pusher), Shown).item
        inbox("answer", str(quiet.number), "--decline")
        launch = host.ask(asking_approval(tmp_path, "launch's"), Shown).item
        inbox("answer", str(launch.number), "--decline", "--comment", "Not yet.")
        nothing = send(hook, bash("b2"))
        typed = host.ask(asking_approval(tmp_path, "typed", pusher), Shown).item
        inbox("answer", str(typed.number), "--decline", "--comment", "Not yet.")
        later = send(hook, bash("b3"))
        waiting = delivery.inbox.waiting(pusher)
    assert settled.here
    assert context(told) == (
        '<message item="2" from="operator" kind="note">\n'
        f"The operator declined @{asked.number}, the approval your push asked "
        '("Approve the host zone at abc?"), and commented:\n'
        "Split the reader out first.\n"
        "</message>"
    )
    assert nothing == ""
    assert context(later) == (
        f'<message item="{typed.number + 1}" from="operator" kind="note">\n'
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
                agent({"type": "tool_use", "id": "b1", "name": "Bash", "input": {}})
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
    assert after.entries == [Called(tool="Bash", id="b1", at=when)]
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
        ended = send(
            hook,
            payload("Stop", stop_hook_active=True, last_assistant_message="Done now."),
        )
        told = delivery.inbox.item(1).state
        notes = [
            (each.number, each.reason)
            for each in delivery.inbox.waiting(Operator())
            if isinstance(each.sender, Conversation)
        ]
    holding = {
        "claude": held.get("hookSpecificOutput", {}).get("additionalContext"),
        "codex": held.get("reason") if held.get("decision") == "block" else None,
    }[runtime]
    assert holding == first_note("One more thing.")
    assert told == Told(at=clock.now(), how="turn's end")
    assert ended == ""
    assert notes == [
        (2, Message(kind="note", text="Two decisions for you.", ending=True)),
        (3, Message(kind="note", text="Done now.", ending=True)),
    ]


def test_a_draft_that_answers_nothing_or_what_a_review_cant_is_refused(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        call(machine.host.launch("one").mcp, "ask", {"question": "In words?"})
        inbox("send", "one", "Mine.")
        empty = refused_draft(machine, clock, Draft())
        own = refused_draft(machine, clock, Draft(done=[2]))
    assert empty == (
        "the draft answers no item and writes to no agent: comment on an item, take "
        "one off the list, or write to an agent under its banner"
    )
    assert own == "@2 is a note from the operator, which a review doesn't answer"


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
    assert sent.reason == Message(
        kind="note", text="Carry on after.", passages=passages
    )

    def quoted(item: int) -> str:
        """The first passage's quote and reply, as item `item` carries them, the reply numbered as its first part."""
        return (
            "<quote>\nTwenty kinds of line.\n\nFour carry what was said.\n</quote>\n"
            f'<reply id="{item}.1">Which four?</reply>'
        )

    assert told == (
        '<message item="1" from="operator" kind="note">\n'
        f"{quoted(1)}\n"
        "<quote>JSONL <\\/quote></quote>\n"
        '<reply id="1.2">Even with a closing tag?</reply>\n'
        "Carry on after.\n"
        "</message>\n\n"
        f'<message item="2" from="operator" kind="note">\n{quoted(2)}\n</message>'
    )
    # What the dashboard shows is what's inside each tag.
    assert listed.received[1].text == quoted(2)
    # A message with no words of its own opens with its first reply.
    assert opening(bare) == "Which four?"


def test_lup_dev_inbox_send_reaches_a_subagent_by_its_path(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        send(hook, records.spawn("t1", name="explore-auth"))
        records.recorded("a1", "Explore", "t1", name="explore-auth")
        send(hook, records.call("a1", "Explore", "c1"))
        sent = inbox("send", "w/explore-auth", "Look at the tests too.")
        told = context(send(hook, records.call("a1", "Explore", "c2")))
        main = send(hook, bash("b1"))
    assert sent == "Sent @1 to `w/explore-auth`, subagent a1 of claude session s1.\n"
    assert told == first_note("Look at the tests too.")
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
        inbox("send", "one", "Mine.")
        host = HostClient(layout=machine.host, clock=clock, starter=Unstarted())
        found = host.ask(ShowContext(number=1), Context)
        with pytest.raises(HostError) as unanchored:
            host.ask(ShowContext(number=2), Context)
        shown = runner.invoke(cli.app, ["inbox", "show", "1", "--context"])
        item = delivery.inbox.item(1)
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
    assert str(unanchored.value) == "@2 was made by no agent's call"
    assert shown.exit_code == 0, shown.output
    assert "· called Bash\n\n→ called mcp__lup__note: this item\n\n" in shown.output


def test_inbox_lists_this_repositorys_items_and_reads_a_conversations_own_whole(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        launched(machine, clock, other, "two", "codex")
        hook = machine.host.launch("one").hook
        mcp = machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        send(machine.host.launch("two").hook, codex("SessionStart", source="startup"))
        call(mcp, "ask", {"question": "Which parser?\nTwenty kinds of line."})
        noting = lup_call("note", {"remark": "I assumed UTF-8."}, "n1", agent_id="a1")
        call(
            mcp,
            "note",
            json.loads(send(hook, noting))["hookSpecificOutput"]["updatedInput"],
        )
        call(machine.host.launch("two").mcp, "note", {"remark": "Elsewhere."})
        inbox("answer", "1", "--comment", "A model per kind.")

        def reading(**arguments: JsonValue) -> str:
            text, error = call(mcp, "inbox", arguments)
            assert not error, text
            return text

        waiting = reading()
        every = reading(every=True)
        asked = reading(number=1)
        answer = reading(number=4)
        theirs = reading(number=2)
        elsewhere = reading(number=3)
        missing = reading(number=9)
        reads = json.loads(
            send(hook, lup_call("inbox", {"number": 2}, "r1", agent_id="a1"))
        )
        own = call(mcp, "inbox", reads["hookSpecificOutput"]["updatedInput"])
        listed = inbox()
    at = "2026-10-01 12:00"
    sub = "subagent a1 of claude session s1"
    assert waiting.splitlines() == [
        f"@2  {at}  a note from {sub} to the operator, waiting: I assumed UTF-8.",
        f"@4  {at}  an answer from the operator to you, waiting: A model per kind.",
    ]
    assert every.splitlines() == [
        (
            f"@1  {at}  a question from you to the operator, answered at {at}, "
            "@4: Which parser?"
        ),
        *waiting.splitlines(),
    ]
    assert asked == (
        f"@1, a question you sent to the operator at {at}, answered at {at}, "
        '@4:\n<part id="1.1">\nWhich parser?\nTwenty kinds of line.\n</part>'
    )
    assert answer == (
        '<answer item="4" from="operator" question="1">\n'
        "<asked>\nWhich parser?\nTwenty kinds of line.\n</asked>\n"
        '<comment id="4.1">A model per kind.</comment>\n'
        "</answer>\n\nIt's waiting."
    )
    assert theirs == (
        f"@2 is a note from {sub} to the operator, which isn't yours: only your "
        "own items are read whole. Its first line: I assumed UTF-8."
    )
    assert elsewhere == missing.replace("9", "3")
    assert missing == (
        "@9 isn't among this repository's: `inbox` reads this repository's items alone."
    )
    assert own == (
        (
            f"@2, a note you sent to the operator at {at}, waiting:\n"
            '<part id="2.1">I assumed UTF-8.</part>'
        ),
        False,
    )
    assert "   @4  " not in listed
    assert [line.split()[0] for line in listed.splitlines()] == ["@2", "@3"]


def test_inbox_and_lup_dev_inbox_list_the_latest_within_a_time_saying_what_they_left_out(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        mcp = machine.host.launch("one").mcp
        for hour in range(5):
            call(mcp, "note", {"remark": f"Note {hour + 1}."})
            clock.sleep(3600)

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

    def note(number: int) -> str:
        return (
            f"@{number}  2026-10-01 {11 + number}:00  a note from you to the "
            f"operator, waiting: Note {number}."
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
    assert every.splitlines() == [note(number) for number in range(1, 6)]
    assert refused
    assert "limit" in nothing
    listed = operators.splitlines()
    assert [line.split()[0] for line in listed[:-1]] == ["@4", "@5"]
    assert listed[-1] == (
        'Not listed: 3 earlier items, which `--until` "2026-10-01T15:00:00+00:00" '
        "reads; a `--limit` of 5 lists them all."
    )
    assert [line.split()[0] for line in operators_between.splitlines()] == [
        "@2",
        "@3",
    ]
    assert operators_quiet == "Nothing made in that time waits for you.\n"
    assert unread.exit_code != 0
    assert "--since and --until each take an ISO 8601 time" in unread.output


def test_an_agent_withdraws_its_own_waiting_item_and_nothing_else(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        hook = machine.host.launch("one").hook
        mcp = machine.host.launch("one").mcp
        send(hook, claude("SessionStart", source="startup"))
        call(mcp, "note", {"remark": "Is the build red for you too?"})
        call(mcp, "ask", {"question": "Which parser?"})
        noting = lup_call("note", {"remark": "I assumed UTF-8."}, "n1", agent_id="a1")
        call(
            mcp,
            "note",
            json.loads(send(hook, noting))["hookSpecificOutput"]["updatedInput"],
        )
        inbox("answer", "2", "--comment", "A model per kind.")

        def withdrawing(number: int) -> str:
            text, error = call(
                mcp, "withdraw", {"number": number, "why": "It's green now."}
            )
            assert not error, text
            return text

        taken = withdrawing(1)
        again = withdrawing(1)
        answered = withdrawing(2)
        theirs = withdrawing(3)
        listed = inbox()
        shown = inbox("show", "1")
    assert taken == "@1 is withdrawn, off the operator's list."
    assert again == (
        "Not withdrawn: @1 no longer waits for the operator: it's withdrawn at "
        "2026-10-01 12:00 by its sender: It's green now."
    )
    assert answered == (
        "Not withdrawn: @2 no longer waits for the operator: it's answered at "
        "2026-10-01 12:00, @4"
    )
    assert theirs == (
        "Not withdrawn: @3 is a note from subagent a1 of claude session s1: "
        "only its sender withdraws it"
    )
    assert [line.split()[0] for line in listed.splitlines()] == ["@3"]
    assert "withdrawn at 2026-10-01 12:00 by its sender: It's green now." in shown
    assert "@1, a note, was withdrawn by its sender" in said


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
        stamped = json.loads(send(hook, lup_call("judged", {}, "j1", agent_id="a1")))[
            "hookSpecificOutput"
        ]["updatedInput"]
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
            "service went away mid-wait, and their answer reaches its session at a "
            "later call"
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
    tools = JudgeTools(layout=layout, clock=clock)
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


def test_the_operators_list_says_when_they_last_settled_an_item(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        mcp = machine.host.launch("one").mcp
        call(mcp, "note", {"remark": "First."})
        call(mcp, "note", {"remark": "Second."})
        host = client(machine.host, clock)
        before = host.ask(ListInbox(), Items)
        clock.sleep(300)
        inbox("done", "1")
        after = host.ask(ListInbox(), Items)
    assert before.reviewed is None
    assert [item.number for item in after.items] == [2]
    assert after.reviewed == clock.now()


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
        inboxed(machine, clock, notices, said),
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
        noting = lup_call("note", {"remark": "I assumed UTF-8."}, "n1", agent_id="a1")
        call(mcp, "note", stamped(noting))
        watch.settimeout(60)
        watch.connect(str(machine.host.watch))
        watch.sendall(f"{ListItems(conversation=session).model_dump_json()}\n".encode())
        with watch.makefile("rb") as replies:
            asked = Exchanged.model_validate_json(replies.readline())
            inbox("answer", "1", "--leaning", "1", "--comment", "Go.")
            answered = following(
                replies.readline,
                lambda found: isinstance(found.sent[0].item.state, Answered),
            )
        send(hook, claude("SubagentStop", agent_id="a1"))
        inbox("answer", "2", "--comment", "UTF-8 it is.")
        send(hook, bash("b1"))
        host = client(machine.host, clock)
        mains = host.ask(ListItems(conversation=session), Exchanged)
        theirs = host.ask(ListItems(conversation=subagent), Exchanged)
    assert [each.text for each in asked.sent] == [
        "Which parser?\n1. Parse with lark\n   lean: it's typed"
    ]
    assert asked.sent[0].item.call == "q1"
    assert asked.received == []
    assert answered.sent[0].item.state == Answered(at=clock.now(), answer=3)
    assert [each.text for each in answered.received] == [
        (
            "<asked>Which parser?</asked>\n"
            '<decision number="1" lean="it\'s typed" verdict="leaning: they go with '
            'the lean" id="3.1">Parse with lark</decision>\n'
            '<comment id="3.2">Go.</comment>'
        )
    ]
    # The reply to the subagent's note, passed on to the session once it ended,
    # is in both: told to the session, and for the subagent.
    assert [each.item.number for each in mains.sent] == [1]
    assert [each.item.number for each in mains.received] == [3, 4]
    assert [each.item.state for each in mains.received] == [
        Told(at=clock.now(), how="call")
    ] * 2
    assert mains.received[1].item.addressed == subagent
    assert mains.received[1].text == (
        '<on item="2" kind="note">\n'
        "<opening>I assumed UTF-8.</opening>\n"
        '<comment id="4.1">UTF-8 it is.</comment>\n'
        "</on>"
    )
    assert [(each.item.number, each.text) for each in theirs.sent] == [
        (2, "I assumed UTF-8.")
    ]
    assert theirs.sent[0].item.state == Done(at=clock.now())
    assert theirs.received == mains.received[1:]


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


# Landing a branch: `land`, waiting on what was flagged on it.


class Landings:
    """lup's layout of a repository for landing: its git directory bare, its worktrees under `tree/`, `dev` checked out in one and `feat` in another; its remote `origin` a bare forge on disk holding `main` and `dev`; and a launch of `runtime` served, started in `dev`'s worktree, whose room is the test's own machine, each command it runs there recorded."""

    def __init__(
        self,
        bare: Path,
        tmp_path: Path,
        shell: Shell,
        machine: Layout,
        clock: FakeClock,
    ) -> None:
        self.repository = bare
        self.shell = shell
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

    def branched(self, name: str) -> Path:
        """Add a worktree on a new branch `name` from `dev`, and return its root."""
        root = self.repository / "tree" / name
        self.shell.git(
            self.repository, "worktree", "add", "-q", "-b", name, str(root), "dev"
        )
        return root

    async def room(self, program: Program) -> Ran:
        """Run what the host asks of the launch's room, `podman exec` into it, on this machine instead, where the room's paths are the host's; and say whether its container is there."""
        self.ran.append(program.command)
        match program.command:
            case ["podman", "container", "exists", name]:
                there = self.containers is None or name in self.containers
                return Ran(command=program.command, status=0 if there else 1)
            case ["podman", "exec", "--workdir", workdir, _, *command]:
                return await executed(
                    Program(command=command, payload="", directory=Path(workdir))
                )
            case _:
                message = f"the room was asked {program.command}"
                raise AssertionError(message)

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
        self, runtime: str, name: str = "one", worktree: Path | None = None
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
                gated=["refs/heads/dev"],
            ),
            github=None,
            name=name,
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


@pytest.fixture
def landings(
    bare: Path, tmp_path: Path, shell: Shell, machine: Layout, clock: FakeClock
) -> Landings:
    return Landings(bare, tmp_path, shell, machine, clock)


def started(runtime: str) -> str:
    """A session's start, in `runtime`'s hook's terms: Claude Code's session `s1`, Codex's `t1`."""
    if runtime == "codex":
        return codex("SessionStart", source="startup")
    return claude("SessionStart", source="startup")


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
    with inboxed(machine, clock, notices, said, rooms=landings.room):
        landings.launched("claude")
        landings.launched("claude", name="two", worktree=busy)
        send(machine.host.launch("one").hook, started("claude"))
        answer, error = call(machine.host.launch("one").mcp, "land", {})
    assert not error
    assert answer == (
        f"Landed {tip} on `dev` at `origin`, which was at {old}.\n"
        "Cleaned up after it:\n"
        "- deleted `feat` on `origin`\n"
        f"- removed the worktree {feat}\n"
        "- deleted the local branch `feat`\n"
        "Left:\n"
        f"- the worktree {busy}: launch `two` started there\n"
        f"- the local branch `busy`, checked out in {busy}\n"
        f"- the worktree {kept}: `git worktree remove`: fatal: '{kept}' contains "
        "modified or untracked files, use --force to delete it\n"
        f"- the local branch `kept`, checked out in {kept}"
    )
    assert landings.on_forge("refs/heads/dev") == tip
    assert landings.on_forge("refs/heads/feat") is None
    assert not feat.exists()
    assert (kept / "draft.txt").is_file()
    assert landings.shell.git(repository, "branch", "--list", "feat") == ""
    assert landings.ran == [
        ["podman", "container", "exists", "lup-one"],
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
            podman=podman_of("lup-one"),
        ) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        landings.launched("claude")
        mcp = machine.host.launch("one").mcp
        send(machine.host.launch("one").hook, started("claude"))
        landings.flag(path, rooms, session)
        landing = pool.submit(call, mcp, "land", {})
        assert delivery.holding.wait(timeout=60)
        # While the landing waits on the operator, the session renames itself,
        # and lup renames its container with it.
        assert call(mcp, "rename", {"name": "review-and-plan"}) == (
            "This session is `review-and-plan`.",
            False,
        )
        [hold] = [
            each
            for each in delivery.inbox.waiting(Operator())
            if isinstance(each.reason, HeldChange)
        ]
        inbox("answer", str(hold.number), "--approve", "--comment", "")
        answer, error = landing.result(timeout=60)
    assert not error
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")
    assert f"- removed the worktree {feat}\n" in answer
    assert not feat.exists()
    assert f"one: its container lup-one is {renamed}" in said
    assert landings.ran == [
        ["podman", "container", "exists", renamed],
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
    with inboxed(machine, clock, notices, said, rooms=landings.room):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        answer, error = call(machine.host.launch("one").mcp, "land", {})
    assert not error
    assert answer == (
        f"Landed {tip} on `dev` at `origin`, which was at {old}.\n"
        "Cleaned up after it:\n"
        "- deleted `feat` on `origin`\n"
        "Left:\n"
        "- no container named `lup-one`, your room's as lup has it, is there, so no "
        "worktree was removed\n"
        f"- the worktree {feat}\n"
        f"- the local branch `feat`, checked out in {feat}\n"
        f"- the worktree {kept}\n"
        f"- the local branch `kept`, checked out in {kept}"
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
    with inboxed(machine, clock, notices, said, rooms=landings.room) as delivery:
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
        "Cleaned up after it:\n"
        f"- removed the worktree {feat}\n"
        "- deleted the local branch `feat`\n"
        f"- removed the worktree {later}\n"
        "- deleted the local branch `later`\n"
        "Left alone, `dev` having merged none of them: `fresh`, `mid`."
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
    with inboxed(machine, clock, notices, said, rooms=landings.room):
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


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_a_landing_waits_on_each_file_flagged_on_what_it_lands_as_a_hold_and_lands_once_approved(
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
    old = landings.on_forge("refs/heads/dev")
    tip = landings.merged()
    session = lander(landings, runtime)
    worker = session.model_copy(update={"agent": "a1"})
    with (
        inboxed(machine, clock, notices, said, rooms=landings.room) as delivery,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        landings.launched(runtime)
        send(machine.host.launch("one").hook, started(runtime))
        flags = [
            landings.flag("src/pkg/rooms.py", rooms, session),
            landings.flag("src/pkg/rooms.py", rooms, worker),
            # On a branch the landing doesn't land, a file it doesn't change, a flag approved: none holds.
            landings.flag("src/pkg/rooms.py", rooms, worker, branch="other"),
            landings.flag("src/pkg/gone.py", rooms, worker),
            landings.flag("src/pkg/hall.py", hall, worker),
        ]
        inbox("done", str(flags[4]))
        landing = pool.submit(call, machine.host.launch("one").mcp, "land", {})
        assert delivery.holding.wait(timeout=60)
        [hold] = [
            each
            for each in delivery.inbox.waiting(Operator())
            if isinstance(each.reason, HeldChange)
        ]
        files = client(machine.host, clock).ask(ShowFiles(number=hold.number), Files)
        inbox("answer", str(hold.number), "--approve", "--comment", "")
        answer, error = landing.result(timeout=60)
        states = [delivery.inbox.item(each).state for each in flags]
    assert not error
    assert hold.sender == session
    assert hold.rank.name == "waiting on you"
    assert hold.reason == HeldChange(
        text=(
            "Let `src/pkg/rooms.py` land on `dev`? It's flagged on `feat`, and the "
            f"landing of {tip} waits on your approval."
        ),
        summary=(
            "src/pkg/rooms.py is a new production file\n"
            f"Shown from `dev`'s tip on the remote, {old}: you've seen none of it."
        ),
        worktree=landings.feat,
        landing=AtLanding(
            onto="refs/heads/dev",
            tip=tip,
            path=Path("src/pkg/rooms.py"),
            branches=["feat"],
            flags=flags[:2],
        ),
    )
    [file] = files.files
    assert (file.before, file.after) == (None, Text(text=rooms))
    assert file.reading == Reading(
        role="production", asks=[Ask(name="new-file", taken="flagged")]
    )
    assert any("held change" in each for each in notices.raised)
    assert answer.startswith(
        f"Landed {tip} on `dev` at `origin`, which was at {old}.\n"
        f"The operator approved @{hold.number} (`src/pkg/rooms.py`).\n"
        "Cleaned up after it:\n"
    )
    assert landings.on_forge("refs/heads/dev") == tip
    approved = Decided(at=clock.now(), approved=True)
    assert states == [approved, approved, Waiting(), Waiting(), approved]


def test_a_comment_on_a_hold_lands_nothing_and_the_next_hold_shows_what_changed_since(
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
    tip = landings.merged()
    session = lander(landings, "claude")
    with (
        inboxed(machine, clock, notices, said, rooms=landings.room) as delivery,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        landings.launched("claude")
        send(machine.host.launch("one").hook, started("claude"))
        flag = landings.flag(path, first, session)
        landing = pool.submit(call, machine.host.launch("one").mcp, "land", {})
        assert delivery.holding.wait(timeout=60)
        commented = flag + 1
        drafting(
            machine,
            clock,
            Draft(comments=[Comment(item=commented, text="Call them chambers.")]),
        )
        sending(machine, clock)
        held_back, _ = landing.result(timeout=60)
        # The agent answers it, and lands again: while that waits, it lands again on another tip.
        landings.wrote(feat, path, second)
        again = landings.merged()
        delivery.holding.clear()
        waiting = pool.submit(call, machine.host.launch("one").mcp, "land", {})
        assert delivery.holding.wait(timeout=60)
        landings.wrote(feat, "README.md", "# Work, with chambers\n")
        latest = landings.merged()
        delivery.holding.clear()
        landing = pool.submit(call, machine.host.launch("one").mcp, "land", {})
        superseded, _ = waiting.result(timeout=60)
        assert delivery.holding.wait(timeout=60)
        [hold] = [
            each
            for each in delivery.inbox.waiting(Operator())
            if isinstance(each.reason, HeldChange)
        ]
        diff = inbox("show", str(hold.number), "--diff")
        inbox("answer", str(hold.number), "--decline", "--comment", "Not yet.")
        declined, _ = landing.result(timeout=60)
        flag_state = delivery.inbox.item(flag).state
        replaced = delivery.inbox.item(commented + 2).state
    assert held_back == (
        "Not landed: the operator didn't approve each file it waits on.\n"
        f"- @{commented} (`{path}`): commented on, not approved\n"
        "What they approved stays approved. Answer what they said, commit, and call "
        "`land` again: each file left is held again, shown from the version they "
        "last saw.\n"
        f'<message item="{commented + 1}" from="operator" kind="note">\nThe '
        f"operator commented on it without approving it: @{commented}, the hold on "
        f"`{path}` at the landing of {tip} on `dev`. Their comment:\n"
        "Call them chambers.\n</message>"
    )
    first_again = commented + 2
    assert superseded.startswith(
        "Not landed: the operator didn't approve each file it waits on.\n"
        f"- @{first_again} (`{path}`): superseded by @{hold.number}, another "
        "landing's hold on the file\n"
    )
    assert replaced == Superseded(at=clock.now(), by=hold.number)
    assert isinstance(hold.reason, HeldChange)
    assert hold.reason.landing is not None
    assert (hold.reason.landing.tip, hold.reason.landing.since) == (latest, commented)
    assert hold.reason.summary.endswith(
        f"Shown since @{commented}, the version of it you last saw."
    )
    assert '-"""Rooms."""\n+"""Chambers."""' in diff
    assert declined.startswith(
        "Not landed: the operator didn't approve each file it waits on.\n"
        f"- @{hold.number} (`{path}`): declined\n"
    )
    assert declined.endswith(
        f"The operator declined it: @{hold.number}, the hold on `{path}` at the "
        f"landing of {latest} on `dev`. Their comment:\nNot yet.\n</message>"
    )
    assert again != latest
    assert landings.on_forge("refs/heads/dev") == old
    assert flag_state == Waiting()


def test_a_land_sent_again_across_a_restart_holds_on_its_holds_again_and_lands_once_approved(
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
        inboxed(machine, clock, notices, said, rooms=landings.room) as delivery,
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
        [hold] = [
            each
            for each in delivery.inbox.waiting(Operator())
            if isinstance(each.reason, HeldChange)
        ]
        inbox("answer", str(hold.number), "--approve", "--comment", "")
        answer, error = landing.result(timeout=60)
        holds = [
            item.number
            for item in delivery.inbox.items.values()
            if isinstance(item.reason, HeldChange)
        ]
    assert not error
    assert answer.startswith(f"Landed {tip} on `dev` at `origin`")
    assert f"The operator approved @{hold.number} (`{path}`)." in answer
    assert (hold.call, hold.number) == ("l1", flag + 1)
    assert holds == [hold.number]
    assert landings.on_forge("refs/heads/dev") == tip


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
    github = {spec.name: (spec.reads, spec.idempotent) for spec in GitHubTools.specs()}
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
