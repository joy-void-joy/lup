"""lup's inbox: items told once, at a call, a turn's end, a held call, a session's start and an idle session's wake; the tools; `lup-dev inbox`.

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
from datetime import UTC, datetime
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
from lup.tools.speaking import Problem, Remark
from lup_dev import Modules, Project, cli
from lup_dev.adapters.claude import ClaudeRecords, ClaudeTranscripts
from lup_dev.declaration.resolve import resolve
from lup_dev.host.client import HostClient, Starter
from lup_dev.host.courier import Conversation as Caller
from lup_dev.host.courier import Heard, Posted
from lup_dev.host.protocol import HostError, Limits, Register, Stop
from lup_dev.host.records import Called, Recorded, Said
from lup_dev.host.service import Asked, HostService, Judged, Naming
from lup_dev.host.watch import Changes
from lup_dev.inbox.delivery import Delivery, opening
from lup_dev.inbox.notices import Notices, NotifySend
from lup_dev.inbox.protocol import (
    Context,
    Drafted,
    Items,
    KeepDraft,
    ListInbox,
    Reviewed,
    SendDraft,
    ShowContext,
    ShowDraft,
)
from lup_dev.inbox.protocol import routes as inbox_routes
from lup_dev.inbox.store import (
    Answer,
    Answered,
    Comment,
    Conversation,
    Decided,
    Done,
    Draft,
    HeldChange,
    Inbox,
    InboxError,
    Item,
    Message,
    Operator,
    Quote,
    Review,
    Told,
    Waiting,
)
from lup_dev.inbox.tools import specs
from lup_dev.launch.room import RoomError
from lup_dev.layout import InboxLayout, Layout
from lup_dev.policy.holds import HeldFile, Hold, Holds, InboxAnnouncing

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator

    from conftest import FakeClock
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
) -> Generator[Watched]:
    """A host service with lup's inbox, its delivery yielded, until the context ends; an item's moment read from `recorded`."""
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
    service = HostService(
        layout=machine.host,
        answerer=known,
        courier=couriers,
        spawns=cli.SpawnRecords(adapters=known),
        post=delivery,
        routes=inbox_routes(delivery, recorded or {}),
        tools=cli.room_tools(delivery),
        judge=Quiet(),
        say=said.append,
        changes=changes,
    )
    with served(service):
        yield delivery


def launched(
    machine: Layout, clock: FakeClock, tmp_path: Path, name: str, runtime: str
) -> Register:
    """Register a launch of `runtime` in `tmp_path` with the running service."""
    judge = tmp_path / "judges" / "bin" / "lup-dev"
    judge.parent.mkdir(parents=True, exist_ok=True)
    judge.touch()
    registered = Register(
        launch=name,
        runtime=runtime,
        worktree=tmp_path,
        repository=tmp_path / ".git",
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
    assert held == {"decision": "block", "reason": first_note("Before you stop.")}
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
        assert json.loads(send(hook, claude("Stop")))["decision"] == "block"
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
        held = json.loads(
            send(hook, claude("SubagentStop", agent_id="a1", stop_hook_active=False))
        )
        let = send(hook, claude("SubagentStop", agent_id="a1", stop_hook_active=True))
    assert held["decision"] == "block"
    assert held["reason"] == (
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
        "decision": "block",
        "reason": "lup's inbox, item 2: a note from the operator:\nBetween calls.",
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


def test_report_note_and_send_reach_the_operator_with_a_desktop_notice(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    with inboxed(machine, clock, notices, said):
        launched(machine, clock, tmp_path, "one", "claude")
        send(machine.host.launch("one").hook, claude("SessionStart", source="startup"))
        mcp = machine.host.launch("one").mcp
        reported = call(mcp, "report", {"problem": "The build is broken."})
        noted = call(mcp, "note", {"remark": "I assumed UTF-8."})
        sent = call(
            mcp,
            "send",
            {"to": "operator", "kind": "disagreement", "text": "Not this way."},
        )
        invalid = call(mcp, "send", {"to": "someone", "kind": "note", "text": "x"})
        listed = inbox()
    assert reported == (
        "Your report is with the operator, item 1. End your turn.",
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
    assert len(notices.raised) == 3


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


def test_a_subagent_is_shown_under_the_conversation_that_spawned_it_nested_ones_too(
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str], tmp_path: Path
) -> None:
    records = Subagents(tmp_path)
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
    assert first == ""
    assert nested == ""
    assert asked.startswith(
        "lup: this subagent is `w/explore-auth/general-purpose·a2` for now"
    )
    assert renamed[0].startswith("This subagent is `w/explore-auth/grep-tokens`")
    assert shown == [
        ("w", None, 0),
        ("w/explore-auth", "w", 1),
        ("w/explore-auth/grep-tokens", "w/explore-auth", 2),
    ]
    assert listing.output.splitlines()[1:] == [
        "  w",
        "    w/explore-auth  Explore",
        "      w/explore-auth/grep-tokens  general-purpose",
    ]
    assert listed == (
        "   1  2026-10-01 12:00  a note from `w/explore-auth/grep-tokens` "
        f"(subagent a2 of claude session s1) in {tmp_path / 'w'}: Found it.\n"
    )


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
        "report",
        "note",
        "ask",
        "send",
        "wait_inbox",
    ]
    assert served[0].input_schema == Problem.model_json_schema()
    assert served[1].input_schema == Remark.model_json_schema()
    assert [spec.summary for spec in served] == [
        "Stop, and tell the operator what's wrong.",
        "Tell the operator a doubt, and carry on.",
        "Ask the operator, with numbered decisions.",
        "Send a message to a party's inbox.",
        "Wait until something reaches your inbox.",
    ]
    assert "inbox as a problem" in served[0].description
    github = GitHubTools.specs()
    naming = Naming.model_construct().specs()
    assert [spec.name for spec in naming] == ["rename"]
    assert cli.served_tools(resolve(Project())) == [*served, *naming, *github]
    dropped = Project(modules=Modules.default().drop("github"))
    assert cli.served_tools(resolve(dropped)) == [*served, *naming]


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
        "items: not yours to act on, unless a comment says so."
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
    with inboxed(machine, clock, notices, said) as delivery:
        delivery.settle_hold = lambda change, approved, comment: cli.hold_answered(
            machine, change, approved=approved, comment=comment
        )
        InboxAnnouncing(layout=machine.host, clock=clock).announced(
            hold.model_copy(update={"call": "t7", "agent": "sub"}),
            "claude",
            tmp_path / ".git",
        )
        [item] = delivery.inbox.waiting(Operator())
        shown = inbox("show", str(item.number))
        diff = inbox("show", str(item.number), "--diff")
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
        "the draft answers no item: comment on one, or take one off the list"
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
