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
from lup_dev.declaration.resolve import resolve
from lup_dev.host.client import HostClient, Starter
from lup_dev.host.courier import Conversation as Caller
from lup_dev.host.courier import Heard, Posted
from lup_dev.host.protocol import HostError, Limits, Register, Stop
from lup_dev.host.service import Asked, HostService, Judged
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.notices import Notices, NotifySend
from lup_dev.inbox.protocol import routes as inbox_routes
from lup_dev.inbox.store import (
    Answered,
    Conversation,
    Inbox,
    InboxError,
    Message,
    Operator,
    Told,
    Waiting,
)
from lup_dev.inbox.tools import specs
from lup_dev.launch.room import RoomError
from lup_dev.layout import InboxLayout, Layout

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator
    from pathlib import Path

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
    machine: Layout, clock: FakeClock, notices: Raised, said: list[str]
) -> Generator[Watched]:
    """A host service with lup's inbox, its delivery yielded, until the context ends."""
    known = cli.Adapters(known=cli.adapters())
    couriers = cli.Couriers(adapters=known)
    delivery = Watched(
        inbox=Inbox.opened(machine.inbox),
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
        post=delivery,
        routes=inbox_routes(delivery),
        tools=cli.room_tools(delivery),
        judge=Quiet(),
        say=said.append,
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
    """What a hook's answer tells the model beside its call or its start."""
    told = json.loads(answer)["hookSpecificOutput"]["additionalContext"]
    assert isinstance(told, str)
    return told


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
        assert send(hook, claude("SessionStart", source="startup")) == ""
        assert inbox("send", "one", "Look at the cache.") == (
            "Sent item 1 to claude session s1.\n"
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
        f"   1  2026-10-01 12:00  a question from claude session s1 in {tmp_path}: "
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
            "message": {"role": "user", "content": first_note("Wake up.")},
            "session_id": "s1",
        }
    ]
    assert frames[0].endswith("\n")
    assert woken.state == Told(at=clock.now(), how="wake")
    assert context(told) == "lup's inbox, item 2: a note from the operator:\nAnd this."
    assert "one: woke claude session s1, telling items 1" in said


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
        f"   1  2026-10-01 12:00  a note from claude session s1 in {tmp_path}: "
        "A doubt.\n"
    )
    assert context(resumed) == "lup's inbox, item 2: a note from the operator:\nKept."
    assert [place.launch for place in where.values()] == ["two"]


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
            f"   1  2026-10-01 12:00  a problem from claude session s1 in {tmp_path}: "
            "The build is broken."
        ),
        (
            f"   2  2026-10-01 12:00  a note from claude session s1 in {tmp_path}: "
            "I assumed UTF-8."
        ),
        (
            f"   3  2026-10-01 12:00  a disagreement from claude session s1 in "
            f"{tmp_path}: Not this way."
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
        not_a_question = refused("answer", "2", "--comment", "x")
        nothing = refused("show", "9")
        listed = inbox()
    assert missing == (
        "item 1 asks 2 decisions, each taking one verdict (`leaning`, `undecided` or "
        "`leave open`); these were given for [1]"
    )
    assert "these were given for [1, 1, 2]" in twice
    assert wordless == "item 3 is a question answered in words: give them"
    assert not_done == "item 1 is a question: answer it, `lup-dev inbox answer 1`"
    assert done == "Item 2 is done.\n"
    assert not_a_question == "item 2 isn't a question waiting for an answer"
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
            input="\nsure\nmaybe\nleave open\n\nThanks.\n",
        )
        answer = delivery.inbox.item(2).reason
    assert result.exit_code == 0, result.output
    assert "A verdict is `leaning`, `undecided` or `leave open`." in result.output
    assert answer.model_dump() == {
        "reason": "answer",
        "question": 1,
        "rulings": [
            {"decision": 1, "verdict": "leaning", "comment": "sure"},
            {"decision": 2, "verdict": "leave open", "comment": ""},
        ],
        "comment": "Thanks.",
    }


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
    assert by_worktree == "Sent item 1 to claude session s1.\n"
    assert isinstance(nowhere.exception, InboxError)
    assert (
        str(nowhere.exception)
        == "no launch served is `nowhere`, by its id or its worktree"
    )
    assert str(several.exception) == (
        f"several launches run in {tmp_path}: one, two; name one by its id"
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
        sealed = runner.invoke(cli.app, ["mount", "--ro", str(atlas)])
        open_ = runner.invoke(cli.app, ["mount", str(atlas), "--launch", "one"])
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
    assert cli.served_tools(resolve(Project())) == [*served, *github]
    dropped = Project(modules=Modules.default().drop("github"))
    assert cli.served_tools(resolve(dropped)) == served


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
