"""lup's inbox: items told once, at a call, a turn's end, a held call, a session's start and an idle session's wake; the tools, and the judge's `judged` beside them; `lup-dev inbox`.

The host service serves in a thread of its own, on sockets under the test's
directory, with a stub judge and each runtime's own adapter as its courier. No
agent, no network, no real clock: a held call is known to hold through an event
the delivery sets, and every wait's timeout only ends a test that would
otherwise hang.
"""

import asyncio
import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from mcp import Client
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.types import TextContent, jsonrpc_message_adapter
from pydantic import Field
from typer.testing import CliRunner

from lup.github.tools import GitHubTools
from lup.rooms import Podman
from lup.rooms.engine import Exited, Process
from lup.tools.speaking import SPEAKING
from lup_dev import Modules, Project, cli
from lup_dev.adapters.claude import ClaudeRecords, ClaudeTranscripts
from lup_dev.codescan.engine import EngineError
from lup_dev.declaration.resolve import resolve
from lup_dev.host.client import HostClient, Starter
from lup_dev.host.courier import Conversation as Caller
from lup_dev.host.courier import Heard, Posted, Spawned, Spawns
from lup_dev.host.protocol import HostError, Limits, Register, Stop
from lup_dev.host.records import Called, Recorded, Said
from lup_dev.host.service import Asked, HostService, Judged, Naming
from lup_dev.host.watch import Changes
from lup_dev.inbox.delivery import Delivery, clocked, opening
from lup_dev.inbox.notices import Notices, NotifySend
from lup_dev.inbox.protocol import (
    AnswerApproval,
    AskApproval,
    Context,
    Conversed,
    Drafted,
    Exchanged,
    Files,
    Items,
    KeepDraft,
    KeepTalk,
    ListInbox,
    ListItems,
    Reviewed,
    SendDraft,
    Settled,
    ShowContext,
    ShowConversation,
    ShowDraft,
    ShowFiles,
    Shown,
    ShowTalk,
    Talked,
)
from lup_dev.inbox.protocol import routes as inbox_routes
from lup_dev.inbox.store import (
    Answer,
    Answered,
    Approval,
    Binary,
    ChangedFile,
    Comment,
    Conversation,
    Decided,
    Done,
    Draft,
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
    Question,
    Quote,
    Rank,
    Reading,
    Reason,
    Review,
    Sent,
    Talk,
    TalkComment,
    Text,
    Told,
    Waiting,
    ranked,
)
from lup_dev.inbox.store import Stop as Stopped
from lup_dev.inbox.tools import specs
from lup_dev.inbox.typed import TypeReader
from lup_dev.launch.room import RoomError
from lup_dev.layout import InboxLayout, Layout
from lup_dev.policy.before import Overwrite, Replacement, before
from lup_dev.policy.checkpoint import Bench, CallFinished, CallStarted
from lup_dev.policy.flags import InboxFlagging
from lup_dev.policy.holds import Answer as HoldAnswer
from lup_dev.policy.holds import HeldFile, Hold, Holds, InboxAnnouncing, Response
from lup_dev.policy.tools import JudgeTools, stands
from lup_dev.policy.verdicts import Verdict, VerdictLog

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator

    from conftest import FakeClock, Kit
    from mcp.client._transport import TransportStreams
    from pydantic import JsonValue

    from lup_dev.layout import HostLayout

runner = CliRunner()


# The host service in a thread of its own, and a session's side of its sockets,
# as `test_host.py` drives them.


class Quiet:
    """A launch's judge that answers every hook with nothing."""

    async def __call__(self, asked: Asked) -> Judged:
        return Judged(status=0, output="", error="")


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
    """Send `payload` on the socket at `path`, as the room's hook does, and read back."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(path))
        connection.sendall(payload.encode())
        connection.shutdown(socket.SHUT_WR)
        with connection.makefile("rb") as stream:
            return stream.read().decode()


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
) -> Generator[Watched]:
    """A host service with lup's inbox, its delivery yielded, until the context ends; an item's moment read from `recorded`, the judge's stores from `judging`, or `machine`'s; an approval's types read by `typed`, where given, which tells `told` too; a subagent's spawn read by `spawns`, or by each runtime's adapter."""
    known = cli.Adapters(known=cli.adapters())
    couriers = cli.Couriers(adapters=known)
    changes = Changes()
    delivery = Watched(
        inbox=Inbox.opened(machine.inbox, changes),
        courier=couriers,
        layout=machine.host,
        notices=notices,
        clock=clock,
        say=said.append,
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
        routes=inbox_routes(delivery, recorded or {}),
        tools=cli.room_tools(delivery, judging or machine),
        judge=Quiet(),
        say=said.append,
        changes=changes,
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


def first_note(text: str) -> str:
    """How the first item, the operator's note, is told."""
    return f"lup's inbox, item 1: a note from the operator:\n{text}"


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
            f"Sent item 1 to `{tmp_path.name}`, claude session s1.\n"
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
    assert context(resumed) == (
        f"{first_note('First.')}\n\n"
        "lup's inbox, item 2: a note from the operator:\nSecond."
    )


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
    assert context(told) == "lup's inbox, item 2: a note from the operator:\nTwo."


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
        held = send(hook, claude("SubagentStop", agent_id="a1", stop_hook_active=False))
        let = send(hook, claude("SubagentStop", agent_id="a1", stop_hook_active=True))
    assert json.loads(held)["hookSpecificOutput"]["hookEventName"] == "SubagentStop"
    assert context(held) == (
        "lup's inbox, item 2: an answer from the operator, to the question of item "
        "1:\nAsked: May I?\nTheir answer: Yes."
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
        f"   1  2026-10-01 12:00  a question from `{tmp_path.name}` (claude session s1) "
        f"in {tmp_path}: "
        "Which parser?\n"
    )
    assert shown == (
        f"Item 1, a question from claude session s1 in {tmp_path} to the operator, "
        "made 2026-10-01 12:00, waiting:\nWhich parser?\n"
        "1. Parse with lark\n   Its lean: yes, it's typed\n"
        "2. Keep the cache\n   Its lean: no\n"
    )
    assert (
        answered == "Answered item 1: your answer, item 2, is for claude session s1.\n"
    )
    assert returned == (
        (
            "lup's inbox, item 2: an answer from the operator, to the question of "
            "item 1:\nAsked: Which parser?\n"
            "1. Parse with lark (lean: yes, it's typed): leaning: they go with the "
            "lean.\n"
            "2. Keep the cache (lean: no): undecided.\n"
            "Their comment on the whole: Go."
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
            "Your question is with the operator, item 1. Their answer reaches you "
            "at a later call; `wait_inbox` waits for it."
        ),
        False,
    )
    assert context(told) == (
        "lup's inbox, item 2: an answer from the operator, to the question of item "
        "1:\nAsked: Why?\nTheir answer: Because."
    )


class Socket:
    """A stand-in for a session's messaging socket: every line written to it, one connection each."""

    def __init__(self, path: Path) -> None:
        self.frames: list[str] = []
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
    assert context(told) == (
        f"{first_note('Wake up.')}\n\n"
        "lup's inbox, item 2: a note from the operator:\nAnd this."
    )
    assert "one: woke claude session s1 for items 1" in said


def bell(number: int) -> str:
    """The doorbell a wake rings for one note from the operator, item `number`."""
    return (
        f"lup's inbox: item {number}, a note from the operator. Call `wait_inbox` to "
        "read it: what's in your inbox comes through lup's own tools, never in a "
        "message like this one."
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
            "additionalContext": (
                "lup's inbox, item 2: a note from the operator:\nBetween calls."
            ),
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
        f"lup's inbox, item 1: a note from the operator, {size:,} bytes, too long to "
        "tell here. Call `wait_inbox` to read it whole."
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
    assert (
        answered == "Answered item 1: your answer, item 2, is for claude session s1.\n"
    )
    assert answer.addressed == Conversation(
        repository=tmp_path / ".git", runtime="claude", session="s1", agent="a1"
    )
    assert context(told) == (
        "lup's inbox, item 2: an answer from the operator (it was for subagent a1 "
        "of claude session s1, whose conversation had ended), to the question of "
        "item 1:\nAsked: Rename it?\nTheir answer: Yes."
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
        f"   1  2026-10-01 12:00  a note from `{tmp_path.name}` (claude session s1) "
        f"in {tmp_path}: A doubt.\n"
    )
    assert context(resumed) == "lup's inbox, item 2: a note from the operator:\nKept."
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
    assert wordless == "item 1 is a note: give your reply in words"
    assert ruled == "item 1 is a note, which takes a reply in words, not verdicts"
    assert replied == (
        "Replied to item 1: your reply, item 2, is for claude session s1.\n"
    )
    assert listed == "Nothing waits for you.\n"
    assert context(told) == (
        "lup's inbox, item 2: a note from the operator, replying to item 1, a note "
        'you sent ("A doubt."):\nNoted, go on.'
    )
    assert own == (
        "item 2 is a note from the operator: neither a question waiting for an "
        "answer nor a conversation's message to reply to"
    )
    assert again == (
        "Replied to item 1: your reply, item 3, is for claude session s1.\n"
    )


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
        "Your problem is with the operator, item 1. End your turn.",
        False,
    )
    assert noted == ("Your note is with the operator, item 2. Carry on.", False)
    assert sent == ("Your message is with the operator, item 3.", False)
    assert invalid[1]
    assert invalid[0].startswith("Refused: 1 validation error for Sending")
    assert listed.splitlines() == [
        (
            f"   1  2026-10-01 12:00  a problem from `{tmp_path.name}` (claude session "
            f"s1) in {tmp_path}: "
            "The build is broken."
        ),
        (
            f"   2  2026-10-01 12:00  a note from `{tmp_path.name}` (claude session "
            f"s1) in {tmp_path}: "
            "I assumed UTF-8."
        ),
        (
            f"   3  2026-10-01 12:00  a disagreement from `{tmp_path.name}` (claude "
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
        "got_in_the_way": "`uv run lup-dev check` printed: engine stale",
        "trying": "run the gate",
        "would_change": "say the rebuild's time first",
    }
    went: dict[str, JsonValue] = {"smooth": "The brief.", "felt": "Good."}
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
            call(mcp, "how_it_went", stamped(hook, lup_call("how_it_went", {}, "h1"))),
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
        missing = call(mcp, "friction", {"trying": "run the gate"})
        waiting = delivery.inbox.waiting(Operator())
        listed = inbox()
        shown = inbox("show", "1")
        replied = inbox("answer", "1", "--comment", "The rebuild is fixed.")
        reply = delivery.inbox.item(7)
        done = inbox("done", "2")
    assert [text for text, _ in answers] == [
        "Your friction is with the operator, item 1. Carry on.",
        "How it went is with the operator, item 2.",
        "Your stop is with the operator, item 3. End your turn.",
        "Your friction is with the operator, item 4. Carry on.",
        "How it went is with the operator, item 5.",
        "Your stop is with the operator, item 6. End your turn.",
    ]
    assert not any(error for _, error in answers)
    assert missing[1]
    assert missing[0].startswith("Refused: 1 validation error for Friction")
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
        (6, codex_session.model_copy(update={"agent": "b1"}), Operator(), "c3"),
    ]
    friction = Friction.model_validate(jammed)
    assert [each.reason for each in waiting] == [
        friction,
        HowItWent(),
        Stopped.model_validate(stopping),
        friction,
        HowItWent.model_validate(went),
        Stopped.model_validate(stopping),
    ]
    first = listed.splitlines()[0]
    assert first.startswith("   1  2026-10-01 12:00  a friction from `")
    assert first.endswith(
        f"(subagent a1 of claude session s1) in {tmp_path}: "
        "`uv run lup-dev check` printed: engine stale"
    )
    assert "how the work went from" in listed.splitlines()[1]
    assert listed.splitlines()[1].endswith(": Nothing notable.")
    assert "a stop by choice from" in listed.splitlines()[2]
    assert shown.endswith(
        "`uv run lup-dev check` printed: engine stale\n"
        "Trying: run the gate\n"
        "Would change: say the rebuild's time first\n"
    )
    assert replied.startswith(
        "Replied to item 1: your reply, item 7, is for subagent a1"
    )
    assert reply.reason == Message(kind="note", text="The rebuild is fixed.", of=1)
    assert reply.recipient == claude_session.model_copy(update={"agent": "a1"})
    assert done.startswith("Item 2")
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
        "item 1 asks 2 decisions, each taking one answer (`leaning`, `undecided`, "
        "`leave open`, or words); these were given for [1]"
    )
    assert "these were given for [1, 1, 2]" in twice
    assert wordless == "item 3 is a question answered in words: give them"
    assert not_done == "item 1 is a question: answer it, `lup-dev inbox answer 1`"
    assert done == "Item 2 is done.\n"
    assert (
        replied == "Replied to item 2: your reply, item 4, is for claude session s1.\n"
    )
    assert nothing == "the inbox holds no item 9"
    assert [line.split()[0] for line in listed.splitlines()] == ["1", "3"]


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
        told = delivery.answered(answer)
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
        "Asked: Which?\n"
        "1. First (lean: a): leaning: they go with the lean. They add: sure\n"
        "2. Second (lean: b): they answer: Sure, no strong preference.\n"
        "Their comment on the whole: Thanks."
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
    assert sent == "Sent item 1 to `reviewer`, claude session s2.\n"


def introduction() -> str:
    """What a subagent is told of lup's tools at its first hook, as the tests' service serves them: the inbox's, `judged` and `rename`, each by its docstring's first line."""
    served = [
        *specs(),
        *JudgeTools.model_construct().specs(),
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


def podman_having(monkeypatch: pytest.MonkeyPatch, *running: str) -> None:
    """Stand podman in for the command line, having the containers `running` and no other."""

    def answered(process: Process) -> Exited:
        match process.arguments:
            case ["podman", "container", "exists", name]:
                return Exited(status=0 if name in running else 1)
            case _:
                message = f"podman asked {process.arguments}"
                raise AssertionError(message)

    monkeypatch.setattr(cli, "Podman", lambda: Podman(execute=answered))


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
        "   1  2026-10-01 12:00  a note from `w/explore-auth/grep-tokens` "
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


def test_a_subagent_spawned_without_a_name_is_asked_and_its_parent_told_once(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path / "w", "one", "claude")
        hook = machine.host.launch("one").hook
        send(hook, claude("SessionStart", source="startup"))
        first_spawn = context(send(hook, records.spawn("t1")))
        second_spawn = send(hook, records.spawn("t2"))
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
    assert first_spawn == (
        "lup: that subagent goes without a name, so you and the operator can't call "
        "it by one: give each subagent you spawn a name after its task (`name` on "
        "`Agent`, which it takes though its schema doesn't list it). It's asked to "
        "name itself meanwhile."
    )
    assert second_spawn == ""
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
    assert by_worktree == f"Sent item 1 to `{tmp_path.name}`, claude session s1.\n"
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

    def recorded(process: Process) -> Exited:
        ran.append(process.arguments)
        return Exited(status=0)

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
        "item 1 tells its session.\n"
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


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["show", "1"],
        ["answer", "1", "--comment", "x"],
        ["done", "1"],
        ["send", "one", "x"],
    ],
)
def test_lup_dev_inbox_refuses_inside_an_agents_session(
    machine: Layout, monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    result = runner.invoke(cli.app, ["inbox", *arguments])
    assert isinstance(result.exception, InboxError)
    assert str(result.exception) == (
        "this runs inside a claude session, and the inbox is the operator's: run it "
        "in your own terminal"
    )
    assert not machine.host.control.exists()


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
    ]
    assert [spec.input_schema for spec in served[:5]] == [
        tool.spec().input_schema for tool in SPEAKING
    ]
    assert [spec.summary for spec in served] == [
        "Say the work can't go on, and what's wrong.",
        "End your work by your own choice, saying why.",
        "Tell the operator a doubt, and carry on.",
        "Say what got in your way, and carry on.",
        "Tell the operator how the work went, once.",
        "Ask the operator, with numbered decisions.",
        "Send a message to a party's inbox.",
        "Wait until something reaches your inbox.",
        "Read this repository's inbox, changing nothing.",
        "Take back an item the operator needn't see.",
    ]
    assert "inbox as a problem" in served[0].description
    github = GitHubTools.specs()
    judging = JudgeTools.model_construct().specs()
    assert [(spec.name, spec.summary) for spec in judging] == [
        ("judged", "Read the judge's verdicts and holds.")
    ]
    naming = Naming.model_construct().specs()
    assert [spec.name for spec in naming] == ["rename"]
    core = [*served, *judging, *naming]
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
        courier=cli.Couriers(adapters=known),
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
        return await delivery.telling(launch, caller, heard, room)

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
        Friction(got_in_the_way="The gate hung."),
        HowItWent(),
        Stopped(why="Nothing more is worth doing."),
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
    context_line = (
        "For context, what the operator said in the same reply on other agents' "
        "items and to other agents: not yours to act on, unless it says so."
    )
    assert returned[0] == (
        "lup's inbox, item 5: a review from the operator, of items 1, 2, 3:\n"
        'On item 1, a question yours ("Which parser?"):\n'
        "  On this passage:\n    > 1. Parse with lark\n    Yes.\n\n"
        f"{context_line}\n\n"
        f"On item 2, a note from claude session s2, in {tmp_path / 'two'}:\n"
        "    | I assumed UTF-8.\n  Fine by me."
    )
    assert context(told) == (
        "lup's inbox, item 6: a review from the operator, of items 1, 2, 3:\n"
        'On item 2, a note yours ("I assumed UTF-8."):\n  Fine by me.\n\n'
        'On item 3, a note yours ("Done reading."):\n  (read, with nothing to add)\n\n'
        f"{context_line}\n\n"
        f"On item 1, a question from claude session s1, in {tmp_path / 'one'}:\n"
        "    | Which parser?\n"
        "    | 1. Parse with lark (lean: yes, it's typed)\n"
        "    | 2. Keep the cache (lean: no)\n"
        "  On this passage:\n    > 1. Parse with lark\n    Yes."
    )


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
    context_line = (
        "For context, what the operator said in the same reply on other agents' "
        "items and to other agents: not yours to act on, unless it says so."
    )
    assert context(told_one) == (
        "lup's inbox, item 2: a review from the operator, of item 1:\n"
        "The operator's message to you:\nAlso rename the module.\n\n"
        'On item 1, a note yours ("I assumed UTF-8."):\n  Fine.\n\n'
        f"{context_line}\n\n"
        f"The operator's message to claude session s2, in {tmp_path / 'two'}:\n"
        "  Pick up the parser next."
    )
    assert context(told_two) == (
        "lup's inbox, item 3: a review from the operator, of item 1:\n"
        "The operator's message to you:\nPick up the parser next.\n\n"
        f"{context_line}\n\n"
        f"On item 1, a note from claude session s1, in {tmp_path / 'one'}:\n"
        "    | I assumed UTF-8.\n  Fine.\n\n"
        f"The operator's message to claude session s1, in {tmp_path / 'one'}:\n"
        "  Also rename the module."
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
            "lup's inbox: item 1, a review from the operator. Call `wait_inbox` to "
            "read it: what's in your inbox comes through lup's own tools, never in a "
            "message like this one."
        )
    ]
    assert context(told) == (
        "lup's inbox, item 1: a review from the operator:\n"
        "The operator's message to you:\nRename it."
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
        "lup's inbox, item 2: a review from the operator (it was for subagent a1 of "
        "claude session s1, whose conversation had ended), of item 1:\n"
        "The operator's message to you:\nThen stop there.\n\n"
        'On item 1, a question yours ("Rename it?"):\n  Yes.'
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
        text="src/pkg/rooms.py landed, flagged for the operator's review.",
        summary=(
            f"src/pkg/rooms.py: {rooms} is a new production file\n"
            f"src/pkg/rooms.py: {rooms} adds the class `Room`"
        ),
        worktree=repo,
        path=Path("src/pkg/rooms.py"),
        writes=2,
    )
    assert item.rank.name == "flag"
    assert item.call == "w1"
    [file] = files
    assert (file.before, file.after) == (None, Text(text=first + room))
    assert file.reading is not None
    assert [each.name for each in file.reading.asks] == ["new-file", "public-api"]
    assert "src/pkg/rooms.py landed, flagged for the operator's review." in shown
    assert "+class Room:" in diff
    assert isinstance(second.reason, Flagged)
    assert (second.reason.writes, second.call) == (1, "e2")
    [review] = reviews
    assert review.recipient == sender
    assert context(reviewed) == (
        "lup's inbox, item 3: a review from the operator, of item 1:\n"
        'On item 1, a flagged write yours ("src/pkg/rooms.py landed, flagged for '
        "the operator's review.\"):\n"
        "  Yes, but call it Chamber."
    )
    # Marked read, it tells its agent nothing.
    assert marked == []
    assert "lup's inbox" not in quiet
    assert [type(each) for each in states] == [Done, Done]
    with pytest.raises(InboxError, match="it isn't withdrawn"):
        delivery.withdrawn(2, sender, "never mind")


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
        f"item {asked.number + 1} is a note, which changes no file: an approval, a "
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
        "lup's inbox, item 2: a note from the operator:\n"
        f"The operator declined item {asked.number}, the approval your push asked "
        '("Approve the host zone at abc?"), and commented:\n'
        "Split the reader out first."
    )
    assert nothing == ""
    assert context(later) == (
        f"lup's inbox, item {typed.number + 1}: a note from the operator:\n"
        f"The operator declined item {typed.number}, the approval your push asked "
        '("Approve the host zone at abc?"), and commented:\nNot yet.'
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
        inbox("send", "one", "One more thing.")
        held = send(
            hook,
            claude(
                "Stop", stop_hook_active=False, last_assistant_message="Done, I think."
            ),
        )
        ended = send(
            hook,
            claude("Stop", stop_hook_active=True, last_assistant_message="Done now."),
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
    assert context(held) == first_note("One more thing.")
    assert ended == ""
    assert notes == [
        (Message(kind="note", text="Done now.", ending=True), None, tmp_path)
    ]
    assert notices.raised == []


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
    assert own == "item 2 is a note from the operator, which a review doesn't answer"


def refused_draft(machine: Layout, clock: FakeClock, draft: Draft) -> str:
    drafting(machine, clock, draft)
    with pytest.raises(HostError) as refusal:
        sending(machine, clock)
    return str(refusal.value)


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
    assert (
        sent == "Sent item 1 to `w/explore-auth`, subagent a1 of claude session s1.\n"
    )
    assert (
        told == "lup's inbox, item 1: a note from the operator:\nLook at the tests too."
    )
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
    assert str(unanchored.value) == "item 2 was made by no agent's call"
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
        f"2  {at}  a note from {sub} to the operator, waiting: I assumed UTF-8.",
        f"4  {at}  an answer from the operator to you, waiting: A model per kind.",
    ]
    assert every.splitlines() == [
        (
            f"1  {at}  a question from you to the operator, answered at {at}, "
            "item 4: Which parser?"
        ),
        *waiting.splitlines(),
    ]
    assert asked == (
        f"Item 1, a question you sent to the operator at {at}, answered at {at}, "
        "item 4:\nWhich parser?\nTwenty kinds of line."
    )
    assert answer == (
        "lup's inbox, item 4: an answer from the operator, to the question of item "
        "1:\nAsked: Which parser?\nTwenty kinds of line.\nTheir answer: A model per "
        "kind.\n\nIt's waiting."
    )
    assert theirs == (
        f"Item 2 is a note from {sub} to the operator, which isn't yours: only your "
        "own items are read whole. Its first line: I assumed UTF-8."
    )
    assert elsewhere == missing.replace("9", "3")
    assert missing == (
        "Item 9 isn't among this repository's: `inbox` reads this repository's "
        "items alone."
    )
    assert own == (
        f"Item 2, a note you sent to the operator at {at}, waiting:\nI assumed UTF-8.",
        False,
    )
    assert "   4  " not in listed
    assert [line.split()[0] for line in listed.splitlines()] == ["2", "3"]


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
    assert taken == "Item 1 is withdrawn, off the operator's list."
    assert again == (
        "Not withdrawn: item 1 no longer waits for the operator: it's withdrawn at "
        "2026-10-01 12:00 by its sender: It's green now."
    )
    assert answered == (
        "Not withdrawn: item 2 no longer waits for the operator: it's answered at "
        "2026-10-01 12:00, item 4"
    )
    assert theirs == (
        "Not withdrawn: item 3 is a note from subagent a1 of claude session s1: "
        "only its sender withdraws it"
    )
    assert [line.split()[0] for line in listed.splitlines()] == ["3"]
    assert "withdrawn at 2026-10-01 12:00 by its sender: It's green now." in shown
    assert "item 1, a note, was withdrawn by its sender" in said


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
    assert [
        stands(hold),
        stands(hold.model_copy(update={"abandoned": True})),
        stands(hold.model_copy(update={"commit": "c0ffee"})),
    ] == [
        "waiting for the operator, its call waiting on their answer",
        (
            "waiting for the operator: nobody answered in time, so the change was "
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
        f'"{(start + timedelta(minutes=2905)).isoformat()}" reads.'
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
        '"2026-09-29T18:30:00+00:00" reads.'
    )


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
        "Which parser?\n1. Parse with lark (lean: it's typed)"
    ]
    assert asked.sent[0].item.call == "q1"
    assert asked.received == []
    assert answered.sent[0].item.state == Answered(at=clock.now(), answer=3)
    assert [each.text for each in answered.received] == [
        (
            "Asked: Which parser?\n"
            "1. Parse with lark (lean: it's typed): leaning: they go with the lean.\n"
            "Their comment on the whole: Go."
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
    assert mains.received[1].text == "UTF-8 it is."
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
        f"The operator commented on item {pushed.number}, the approval your push "
        'asked ("Approve the host zone at abc?"), and hasn\'t answered it:\n'
        "Split the reader out first."
    )
    assert sent.kept == [nobody.number]
    assert [each.item for each in left.comments] == [nobody.number]
