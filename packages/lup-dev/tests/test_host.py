"""The host service, on sockets under the test's directory, with a stub judge.

No test sleeps or reads the machine's clock: a service serves in a thread of its
own and says when it's bound, a client waits through the fake clock, and answers
that must overlap meet at a barrier, whose timeout only ends a test that would
otherwise hang.
"""

import asyncio
import json
import os
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, Literal, override

import pytest
from mcp import Client
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.types import TextContent, jsonrpc_message_adapter
from pydantic import JsonValue, ValidationError
from typer.testing import CliRunner

from lup.tools.hook import lup_hook
from lup.tools.serving import Answer
from lup.tools.tool import ToolSpec, lup_tool
from lup.types import Model
from lup_dev import (
    Core,
    Hooks,
    Module,
    ModuleHooks,
    Modules,
    ModuleTools,
    Moment,
    Project,
    Toolsets,
    cli,
)
from lup_dev.declaration.resolve import resolve
from lup_dev.host.client import (
    HostClient,
    RoomClient,
    Starter,
    requested,
    watching,
)
from lup_dev.host.courier import Conversation, Courier, Heard, Telling
from lup_dev.host.dashboard import (
    DashboardProcess,
    DashboardShown,
    ShowDashboard,
    Showing,
)
from lup_dev.host.protocol import (
    Activity,
    Done,
    HostError,
    Limits,
    Listed,
    ListLaunches,
    Refused,
    Register,
    Registered,
    Reply,
    Request,
    Stop,
)
from lup_dev.host.rooms import RoomHandler, RoomRoute, RoomTools
from lup_dev.host.service import (
    Answerer,
    Asked,
    Companion,
    Handler,
    HostService,
    Judged,
    Route,
    judged,
)
from lup_dev.host.workers import LaunchModules, Offered
from lup_dev.layout import HostLayout, Layout

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
    from pathlib import Path

    from conftest import FakeClock, InProcess, Kit
    from mcp.client._transport import TransportStreams

    from lup.sessions.terminal import Event
    from lup_dev.clock import Clock

runner = CliRunner()


class Stub(Answerer):
    """Knows two runtimes, and says a hook its judge couldn't answer in a form of its own."""

    def runtimes(self) -> list[str]:
        return ["first", "second"]

    def unanswered(self, runtime: str, payload: str, failure: str) -> str:
        return f"{runtime} unanswered {payload}: {failure}\n"


class Hears(Courier):
    """Hears every payload as a call of one session's own conversation, which the judge reads, and adds nothing."""

    def heard(self, runtime: str, payload: str) -> Heard:
        return Heard(event="call-started", session="s1", judged=True, fits=10_000)

    def told(self, runtime: str, payload: str, answer: str, telling: Telling) -> str:
        return answer

    def woken(self, runtime: str, session: str, text: str) -> str | None:
        return None


class Judge:
    """A launch's judge, answering each hook with its runtime and payload.

    `hold` waits until released, `fail` ends with status 1, `boom` raises, and
    every answer waits at a barrier for `together` answers in all. The test's
    thread releases it, so each wait runs in a thread, leaving the service's
    event loop free, as a judge's process does.
    """

    def __init__(self, together: int = 1) -> None:
        self.together = threading.Barrier(together, timeout=60)
        self.arrived = threading.Event()
        self.released = threading.Event()
        self.asked: list[Asked] = []

    async def __call__(self, asked: Asked) -> Judged:
        self.asked.append(asked)
        self.arrived.set()
        *_, runtime = asked.command
        match asked.payload:
            case "boom":
                message = "the stub fails"
                raise RuntimeError(message)
            case "fail":
                return Judged(status=1, output="", error="Traceback: it broke\n")
            case "hold":
                await asyncio.to_thread(self.released.wait)
            case _:
                pass
        await asyncio.to_thread(self.together.wait)
        return Judged(status=0, output=f"{runtime} answers {asked.payload}\n", error="")


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

    def start(self) -> Background:
        self.thread.start()
        self.bound.wait()
        if self.failure is not None:
            raise self.failure
        return self

    def stop(self) -> None:
        """Stop the service if it still serves, and wait for its thread.

        A service a test stopped itself may be gone (no socket, or none
        listening), or still shutting down, closing the connection it accepted
        for this `Stop`.
        """
        if self.thread.is_alive():
            try:
                send(self.service.layout.control, Stop().model_dump_json())
            except FileNotFoundError, ConnectionRefusedError, ConnectionResetError:
                pass
        self.thread.join(timeout=60)
        assert not self.thread.is_alive()


@contextmanager
def served(service: HostService) -> Generator[Background]:
    running = Background(service).start()
    try:
        yield running
    finally:
        running.stop()


class Recorded(Starter):
    """Records each start, and runs `then` for it."""

    def __init__(self, then: Callable[[], object] | None = None) -> None:
        self.started: list[Path] = []
        self.then = then

    def start(self, log: Path) -> None:
        self.started.append(log)
        if self.then is not None:
            self.then()


def send(path: Path, payload: str) -> str:
    """Send `payload` on the socket at `path`, as the room's hook does, and read back."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(path))
        connection.sendall(payload.encode())
        connection.shutdown(socket.SHUT_WR)
        with connection.makefile("rb") as stream:
            return stream.read().decode()


@pytest.fixture
def layout(tmp_path_factory: pytest.TempPathFactory) -> HostLayout:
    # A socket's path is limited in length, so the service's directory is short.
    base = tmp_path_factory.mktemp("host")
    return HostLayout(sockets=base / "run", state=base / "state")


@pytest.fixture
def said() -> list[str]:
    return []


def service(
    layout: HostLayout,
    judge: Callable[[Asked], Awaitable[Judged]],
    said: list[str],
    routes: list[Route] | None = None,
    answerer: Answerer | None = None,
    *,
    courier: Courier | None = None,
    room_routes: list[RoomRoute] | None = None,
    tools: list[RoomTools] | None = None,
    modules: LaunchModules | None = None,
    refresh: Callable[[Register], list[Path]] | None = None,
    clock: Clock | None = None,
    companions: list[Companion] | None = None,
) -> HostService:
    built = HostService(
        layout=layout,
        answerer=answerer or Stub(),
        courier=courier or Hears(),
        judge=judge,
        say=said.append,
        routes=routes or [],
        room_routes=room_routes or [],
        tools=tools or [],
        modules=modules,
        refresh=refresh,
        companions=companions or [],
    )
    return built if clock is None else built.model_copy(update={"clock": clock})


def launch(tmp_path: Path, name: str, runtime: str) -> Register:
    """A launch of `runtime` in `tmp_path`, its judge a file there."""
    judge = tmp_path / "judges" / "bin" / "lup-dev"
    judge.parent.mkdir(parents=True, exist_ok=True)
    judge.touch()
    return Register(
        launch=name,
        runtime=runtime,
        worktree=tmp_path,
        repository=tmp_path / ".git",
        judge=judge,
        container=f"lup-{name}",
        limits=Limits(actions=["fetch", "push"], protected=["refs/heads/main"]),
        github=None,
        name=name,
    )


def client(
    layout: HostLayout, clock: Clock, starter: Starter | None = None
) -> HostClient:
    return HostClient(layout=layout, clock=clock, starter=starter or Recorded())


def test_a_hook_is_answered_on_its_launchs_socket(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    with served(service(layout, Judge(), said)):
        directory = host.register(launch(tmp_path, "one", "first")).directory
        assert directory == layout.launch("one").directory
        assert directory.stat().st_mode & 0o777 == 0o700
        assert layout.launch("one").hook.is_socket()
        payload = '{"hook_event_name": "Stop"}'
        assert send(layout.launch("one").hook, payload) == f"first answers {payload}\n"
    judge = tmp_path / "judges" / "bin" / "lup-dev"
    assert (
        f"one: served as `one`, first in {tmp_path}, judged by {judge}, its sockets in "
        f"{directory}"
    ) in said
    assert "one: answered a hook" in said


def test_parallel_hooks_are_answered_at_once(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    with served(service(layout, Judge(together=3), said)):
        host.register(launch(tmp_path, "one", "first"))
        hook = layout.launch("one").hook
        with ThreadPoolExecutor(max_workers=3) as pool:
            answers = list(pool.map(send, [hook] * 3, ["a", "b", "c"]))
    assert answers == ["first answers a\n", "first answers b\n", "first answers c\n"]


def test_a_hold_leaves_the_service_answering(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    judge = Judge()
    with (
        served(service(layout, judge, said)),
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        host.register(launch(tmp_path, "one", "first"))
        held = pool.submit(send, layout.launch("one").hook, "hold")
        try:
            judge.arrived.wait()
            host.register(launch(tmp_path, "two", "second"))
            assert send(layout.launch("two").hook, "x") == "second answers x\n"
            assert not held.done()
        finally:
            judge.released.set()
        assert held.result() == "first answers hold\n"


def test_a_launchs_directory_goes_with_it(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    with served(service(layout, Judge(), said)):
        directory = host.register(launch(tmp_path, "one", "first")).directory
        (directory / "left.txt").write_text("what the room left\n")
        host.unregister("one")
        assert not directory.exists()
        assert not layout.record("one").exists()
        with pytest.raises(FileNotFoundError):
            send(layout.launch("one").hook, "x")
        with pytest.raises(HostError, match="no launch named `one` is served"):
            host.unregister("one")
    assert "one: ended" in said


def test_stopping_closes_the_sockets_and_keeps_the_launches(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    with served(service(layout, Judge(), said)) as running:
        directory = host.register(launch(tmp_path, "one", "first")).directory
        assert host.stop()
        running.thread.join(timeout=60)
    assert clock.slept == 0
    assert not host.answers()
    assert not layout.control.exists()
    assert not layout.launch("one").hook.exists()
    assert directory.is_dir()
    assert layout.record("one").is_file()
    assert not host.stop()
    assert said[-1] == "The host service stopped."


def test_a_service_started_again_serves_the_launches_where_their_rooms_mounted_them(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    registered = launch(tmp_path, "one", "first")
    with served(service(layout, Judge(), said)):
        directory = host.register(registered).directory
        mounted = directory.stat().st_ino
        host.stop()
    with served(service(layout, Judge(), said)):
        assert directory.stat().st_ino == mounted
        assert send(layout.launch("one").hook, "again") == "first answers again\n"
        assert host.launches() == [registered]
        host.unregister("one")


def test_a_service_started_again_brings_each_room_s_programs_up_to_its_copy(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    registered = launch(tmp_path, "one", "first")
    asked: list[Register] = []

    def refresh(served: Register) -> list[Path]:
        asked.append(served)
        return [tmp_path / "helper"]

    with served(service(layout, Judge(), said, refresh=refresh)):
        host.register(registered)
        host.stop()
    assert asked == []
    with served(service(layout, Judge(), said, refresh=refresh)):
        assert asked == [registered]
        host.unregister("one")
    assert f"one: {tmp_path / 'helper'} brought up to this copy's" in said


def test_a_record_it_cant_serve_is_said_and_left(
    layout: HostLayout, clock: FakeClock, said: list[str]
) -> None:
    layout.launches.mkdir(parents=True)
    layout.record("broken").write_text("not json\n")
    with served(service(layout, Judge(), said)):
        assert client(layout, clock).answers()
    assert any(
        line.startswith(f"{layout.record('broken')} isn't served") for line in said
    )
    assert layout.record("broken").is_file()


def test_a_second_start_finds_the_first(
    layout: HostLayout, clock: FakeClock, said: list[str]
) -> None:
    starter = Recorded()
    host = client(layout, clock, starter)
    with served(service(layout, Judge(), said)):
        host.ensure()
        assert starter.started == []
        with pytest.raises(HostError, match="a host service runs already"):
            Background(service(layout, Judge(), [])).start()
        assert host.answers()


def test_a_stale_control_socket_is_started_over(
    layout: HostLayout, clock: FakeClock, said: list[str]
) -> None:
    layout.sockets.mkdir(parents=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
        stale.bind(str(layout.control))
    assert layout.control.is_socket()
    started: list[Background] = []
    starter = Recorded(
        then=lambda: started.append(Background(service(layout, Judge(), said)).start())
    )
    host = client(layout, clock, starter)
    assert not host.answers()
    try:
        host.ensure()
        assert starter.started == [layout.log]
        assert host.answers()
    finally:
        for running in started:
            running.stop()


def test_a_started_service_is_waited_for_through_the_clock(
    layout: HostLayout, clock: FakeClock, said: list[str]
) -> None:
    started: list[Background] = []
    clock.on_sleep.append(
        lambda: started.append(Background(service(layout, Judge(), said)).start())
    )
    host = client(layout, clock)
    try:
        host.ensure()
        assert host.answers()
        assert clock.slept == host.poll.total_seconds()
    finally:
        for running in started:
            running.stop()


def test_a_service_that_never_answers_names_its_log(
    layout: HostLayout, clock: FakeClock
) -> None:
    host = client(layout, clock)
    with pytest.raises(HostError, match=r"what it printed is in .*service\.log"):
        host.ensure()
    assert clock.slept >= host.patience.total_seconds()


def test_what_the_service_cant_carry_out_is_refused(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    with served(service(layout, Judge(), said)):
        host.register(launch(tmp_path, "one", "first"))
        with pytest.raises(
            HostError, match="a launch with the id `one` is served already"
        ):
            host.register(launch(tmp_path, "one", "second"))
        with pytest.raises(
            HostError,
            match="no runtime named `third`; the service answers first, second",
        ):
            host.register(launch(tmp_path, "two", "third"))
        outside = {
            "kind": "register",
            "launch": "../out",
            "runtime": "first",
            "worktree": str(tmp_path),
        }
        refused = Refused.model_validate_json(send(layout.control, json.dumps(outside)))
        assert "one path segment" in refused.error
        unknown = Refused.model_validate_json(send(layout.control, '{"kind": "nope"}'))
        assert unknown.error == (
            "no handler for `nope`; the service answers list, register, rename, "
            "stop, unregister"
        )
        garbled = Refused.model_validate_json(send(layout.control, "hello"))
        assert garbled.error.startswith("a request is a JSON object with its kind")
        assert not (layout.launches / "out").exists()
        unjudged = launch(tmp_path, "three", "first").model_copy(
            update={"judge": tmp_path / "nowhere" / "lup-dev"}
        )
        with pytest.raises(HostError, match=r"nowhere/lup-dev, isn't there"):
            host.register(unjudged)
        assert not layout.launch("three").directory.exists()


def test_a_launch_is_answered_by_its_own_judge(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    judge = Judge()
    one = launch(tmp_path / "a", "one", "first")
    two = launch(tmp_path / "b", "two", "second")
    with served(service(layout, judge, said)):
        host.register(one)
        host.register(two)
        assert host.launches() == [one, two]
        send(layout.launch("one").hook, "x")
        send(layout.launch("two").hook, "y")
    assert judge.asked == [
        Asked(command=[str(one.judge), "hook", "first"], payload="x"),
        Asked(command=[str(two.judge), "hook", "second"], payload="y"),
    ]


def test_a_hook_its_judge_cant_answer_is_answered_in_the_runtimes_terms(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    with served(service(layout, Judge(), said)):
        registered = host.register(launch(tmp_path, "one", "first"))
        heard = send(layout.launch("one").hook, "fail")
    command = f"{tmp_path}/judges/bin/lup-dev hook first"
    assert heard == (
        f"first unanswered fail: `{command}` ended with status 1; what it said is "
        f"in the host service's output, {layout.log} when it runs in the background\n"
    )
    assert (
        f"one: `{command}` couldn't answer a hook (status 1). What it said:\n"
        "Traceback: it broke\n"
    ) in said
    assert registered.directory.is_dir()


def test_a_failed_answer_is_said_and_the_hook_hears_nothing(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    with served(service(layout, Judge(), said)):
        host.register(launch(tmp_path, "one", "first"))
        assert send(layout.launch("one").hook, "boom") == ""
        assert send(layout.launch("one").hook, "after") == "first answers after\n"
    [failed] = [
        line for line in said if line.startswith("one: answering a hook failed")
    ]
    assert "RuntimeError: the stub fails" in failed


class Echo(Request):
    kind: Literal["echo"] = "echo"
    text: str


class Echoed(Reply):
    kind: Literal["echoed"] = "echoed"
    text: str


class Echoing(Handler[Echo]):
    @override
    def request(self) -> type[Echo]:
        return Echo

    @override
    async def answer(self, request: Echo) -> Reply:
        return Echoed(text=request.text)


class Stopping(Handler[Stop]):
    @override
    def request(self) -> type[Stop]:
        return Stop

    @override
    async def answer(self, request: Stop) -> Reply:
        return Echoed(text="mine")


def test_a_module_registers_the_handler_for_its_kind(
    layout: HostLayout, clock: FakeClock, said: list[str]
) -> None:
    host = client(layout, clock)
    with served(service(layout, Judge(), said, [Route.to(Echoing())])):
        assert host.ask(Echo(text="hello"), Echoed).text == "hello"
    with pytest.raises(ValidationError, match="more than one handler for echo"):
        service(layout, Judge(), said, [Route.to(Echoing()), Route.to(Echoing())])
    with pytest.raises(ValidationError, match="more than one handler for stop"):
        service(layout, Judge(), said, [Route.to(Stopping())])


# A launch's room sockets: lup's tools, and the room's requests


class Quiet:
    """A launch's judge that answers every hook with nothing, keeping each payload it was asked."""

    def __init__(self) -> None:
        self.payloads: list[str] = []

    async def __call__(self, asked: Asked) -> Judged:
        self.payloads.append(asked.payload)
        return Judged(status=0, output="", error="")


ECHO = ToolSpec(
    name="echo",
    description="Say who's calling.\n\nThe launch and the conversation.",
    input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
)


class Recording(RoomTools):
    """A module serving `echo`, answering with the launch and the conversation calling, and keeping each call."""

    def __init__(self, names: list[str] | None = None) -> None:
        self.names = names or ["echo"]
        self.calls: list[tuple[str, JsonValue, str, Conversation]] = []

    def specs(self) -> list[ToolSpec]:
        return [ECHO.model_copy(update={"name": name}) for name in self.names]

    async def call(
        self, name: str, arguments: JsonValue, launch: Register, caller: Conversation
    ) -> Answer:
        self.calls.append((name, arguments, launch.launch, caller))
        return Answer(text=f"{launch.launch} heard {caller.id}")


@asynccontextmanager
async def bridged(path: Path) -> AsyncGenerator[TransportStreams]:
    """Carry a client's messages over a connection to `path`, one JSON-RPC message a line, as the room's bridge carries them."""
    reader, writer = await asyncio.open_unix_connection(str(path))
    async with create_client_server_memory_streams() as (client, ours):
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
            yield client
        finally:
            writer.close()
            for task in tasks:
                task.cancel()
            await asyncio.wait(tasks)


def call(path: Path, name: str, arguments: dict[str, JsonValue]) -> tuple[str, bool]:
    """Call the tool `name` through lup's tool server on `path`, as a session would: its text, and whether it's an error."""

    async def called() -> tuple[str, bool]:
        async with Client(bridged(path), mode="legacy") as client:
            result = await client.call_tool(name, arguments)
        [content] = result.content
        assert isinstance(content, TextContent)
        return content.text, result.is_error

    return asyncio.run(called())


def listed(path: Path) -> list[str]:
    """List the tools lup's tool server on `path` serves, by name."""

    async def tools() -> list[str]:
        async with Client(bridged(path), mode="legacy") as client:
            return [tool.name for tool in (await client.list_tools()).tools]

    return asyncio.run(tools())


def claude(event: str, **fields: object) -> str:
    """A Claude Code hook's payload, of session `s1` unless `fields` name another."""
    return json.dumps(
        {"session_id": "s1", "cwd": "/w", "hook_event_name": event, **fields}
    )


def lups(tool: str, call: str, **fields: object) -> str:
    """A Claude Code call to one of lup's tools, `mcp__lup__<tool>`."""
    return claude(
        "PreToolUse",
        tool_name=f"mcp__lup__{tool}",
        tool_input={"text": "hi"},
        tool_use_id=call,
        **fields,
    )


def stamped(answer: str) -> dict[str, JsonValue]:
    """The arguments a hook's answer rewrote a call's to."""
    return json.loads(answer)["hookSpecificOutput"]["updatedInput"]


def caller(answer: str) -> str:
    """The caller a hook's answer stamped a call with."""
    stamp = stamped(answer)["caller"]
    assert isinstance(stamp, str)
    return stamp


def on_claude(
    layout: HostLayout,
    judge: Callable[[Asked], Awaitable[Judged]],
    said: list[str],
    tools: list[RoomTools] | None = None,
    modules: LaunchModules | None = None,
) -> HostService:
    """A service answering Claude Code's hooks through its own adapter."""
    known = cli.Adapters(known=cli.adapters())
    return service(
        layout,
        judge,
        said,
        answerer=known,
        courier=cli.Couriers(adapters=known),
        tools=tools,
        modules=modules,
    )


def test_a_call_on_a_launchs_mcp_socket_reaches_its_tools_with_its_conversation(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    tools = Recording()
    with served(on_claude(layout, Quiet(), said, [tools])):
        host.register(launch(tmp_path, "one", "claude"))
        host.register(launch(tmp_path, "two", "claude"))
        send(layout.launch("one").hook, claude("SessionStart", source="startup"))
        arguments = stamped(send(layout.launch("one").hook, lups("echo", "t1")))
        stamp = arguments["caller"]
        assert isinstance(stamp, str)
        assert listed(layout.launch("one").mcp) == ["echo", "rename"]
        heard = call(layout.launch("one").mcp, "echo", arguments)
        elsewhere = call(layout.launch("two").mcp, "echo", arguments)
    assert heard == (f"one heard {stamp}", False)
    assert tools.calls == [
        ("echo", {"text": "hi"}, "one", Conversation(id=stamp, session="s1"))
    ]
    assert elsewhere == (
        (
            f"lup doesn't know the conversation `{stamp}` this call names, so it "
            "wasn't run; calling it again names yours"
        ),
        True,
    )


def test_each_conversation_is_stamped_with_one_id_of_lups_own(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    with served(on_claude(layout, Quiet(), said)):
        host.register(launch(tmp_path, "one", "claude"))
        host.register(launch(tmp_path, "two", "claude"))
        hook = layout.launch("one").hook
        first = caller(send(hook, lups("echo", "t1")))
        again = caller(send(hook, lups("echo", "t2")))
        subagent = caller(send(hook, lups("echo", "t3", agent_id="a1")))
        resumed = caller(send(hook, lups("echo", "t4", session_id="s2")))
        other = caller(send(layout.launch("two").hook, lups("echo", "t5")))
    assert first == again
    assert len({first, subagent, resumed, other}) == 4


def test_a_hook_the_judge_doesnt_read_is_answered_without_it(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    judge = Quiet()
    started = claude("SessionStart", source="startup")
    write = claude(
        "PreToolUse",
        tool_name="Write",
        tool_input={"file_path": "a.md", "content": "a"},
        tool_use_id="t1",
    )
    unread = [
        claude(
            "PreToolUse",
            tool_name="Bash",
            tool_input={"command": "ls"},
            tool_use_id="t2",
        ),
        claude("Stop", stop_hook_active=False),
        claude("SubagentStop", agent_id="a1"),
    ]
    with served(on_claude(layout, judge, said)):
        host.register(launch(tmp_path, "one", "claude"))
        hook = layout.launch("one").hook
        answers = [send(hook, payload) for payload in [started, write, *unread]]
        lup_tool = json.loads(send(hook, lups("echo", "t3")))
    assert answers[1:] == ["", "", "", ""]
    named = json.loads(answers[0])["hookSpecificOutput"]
    assert named["sessionTitle"] == "one"
    assert named["additionalContext"].startswith("lup: this session is `one`")
    assert judge.payloads == [started, write]
    assert lup_tool["hookSpecificOutput"].keys() == {"hookEventName", "updatedInput"}


def test_a_call_without_its_caller_is_the_main_conversations(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    tools = Recording()
    with served(on_claude(layout, Quiet(), said, [tools])):
        host.register(launch(tmp_path, "one", "claude"))
        mcp = layout.launch("one").mcp
        before = call(mcp, "echo", {"text": "hi"})
        send(layout.launch("one").hook, claude("SessionStart", source="startup"))
        after = call(mcp, "echo", {"text": "hi"})
        nowhere = call(mcp, "nowhere", {})
    assert before == (
        (
            "lup can't tell who's calling: no hook of this session has reached it, "
            "so this call wasn't run"
        ),
        True,
    )
    [(_, _, _, main)] = tools.calls
    assert after == (f"one heard {main.id}", False)
    assert main == Conversation(id=main.id, session="s1")
    assert (
        f"one: a call to `echo` carried no `caller`, so it's taken as the main "
        f"conversation's, {main.id}"
    ) in said
    assert nowhere == ("lup serves no tool named `nowhere`", True)


class Answering(RoomHandler[Echo]):
    @override
    def request(self) -> type[Echo]:
        return Echo

    @override
    async def answer(self, request: Echo, launch: Register) -> Reply:
        return Echoed(text=f"{launch.launch}: {request.text}")


def test_a_rooms_request_is_answered_with_its_launch(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    routes = [RoomRoute.to(Answering())]
    with served(service(layout, Judge(), said, room_routes=routes)):
        host.register(launch(tmp_path, "one", "first"))
        host.register(launch(tmp_path, "two", "first"))
        one = RoomClient(socket=layout.launch("one").request)
        two = RoomClient(socket=layout.launch("two").request)
        assert one.ask(Echo(text="hi"), Echoed).text == "one: hi"
        assert two.ask(Echo(text="hi"), Echoed).text == "two: hi"
        with pytest.raises(HostError, match="no handler for `echo`; the service"):
            host.ask(Echo(text="hi"), Echoed)


def test_a_control_kind_sent_from_a_room_is_refused(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    with served(
        service(layout, Judge(), said, room_routes=[RoomRoute.to(Answering())])
    ):
        host.register(launch(tmp_path, "one", "first"))
        room = RoomClient(socket=layout.launch("one").request)
        for request in [Stop(), launch(tmp_path, "two", "first")]:
            with pytest.raises(HostError) as refused:
                room.ask(request, Echoed)
            assert str(refused.value) == (
                f"no handler for `{request.kind}`; a room's request socket answers echo"
            )
        assert host.launches() == [launch(tmp_path, "one", "first")]
    assert (
        "one: refused a request: no handler for `stop`; a room's request "
        "socket answers echo" in said
    )


def test_a_room_can_reach_no_service_outside_a_room(tmp_path: Path) -> None:
    room = RoomClient(socket=tmp_path / "request.sock")
    with pytest.raises(HostError, match="no host service answers on"):
        room.ask(Echo(text="hi"), Echoed)
    assert RoomClient().socket.as_posix() == "/run/lup/request.sock"


def test_the_room_sockets_go_with_the_launch_and_are_served_again_after_a_restart(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    sockets = layout.launch("one")
    routes = [RoomRoute.to(Answering())]
    with served(
        service(layout, Judge(), said, room_routes=routes, tools=[Recording()])
    ):
        host.register(launch(tmp_path, "one", "first"))
        assert sockets.mcp.is_socket()
        assert sockets.request.is_socket()
        host.stop()
    assert not sockets.mcp.exists()
    assert not sockets.request.exists()
    with served(
        service(layout, Judge(), said, room_routes=routes, tools=[Recording()])
    ):
        assert listed(sockets.mcp) == ["echo", "rename"]
        room = RoomClient(socket=sockets.request)
        assert room.ask(Echo(text="again"), Echoed).text == "one: again"
        host.unregister("one")
        assert not sockets.directory.exists()
        with pytest.raises(HostError, match="no host service answers"):
            room.ask(Echo(text="gone"), Echoed)


def test_a_session_connected_to_lups_tools_is_closed_with_its_launch(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)

    async def connected() -> bytes:
        reader, writer = await asyncio.open_unix_connection(str(sockets.mcp))
        await asyncio.to_thread(host.unregister, "one")
        heard = await reader.read()
        writer.close()
        return heard

    sockets = layout.launch("one")
    with served(service(layout, Judge(), said, tools=[Recording()])):
        host.register(launch(tmp_path, "one", "first"))
        assert asyncio.run(connected()) == b""
    assert "one: ended" in said
    assert not any("serving lup's tools failed" in line for line in said)


def test_two_modules_serving_one_tool_or_answering_one_kind_are_refused(
    layout: HostLayout, said: list[str]
) -> None:
    with pytest.raises(ValidationError, match="more than one module serves echo"):
        service(layout, Judge(), said, tools=[Recording(), Recording(["echo", "x"])])
    with pytest.raises(ValidationError, match="more than one handler for echo"):
        service(
            layout,
            Judge(),
            said,
            routes=[Route.to(Echoing())],
            room_routes=[RoomRoute.to(Answering())],
        )
    with pytest.raises(ValidationError, match="more than one handler for echo"):
        service(
            layout,
            Judge(),
            said,
            room_routes=[RoomRoute.to(Answering()), RoomRoute.to(Answering())],
        )


PAYLOAD = {
    "session_id": "s1",
    "hook_event_name": "PreToolUse",
    "tool_name": "Write",
    "tool_input": {"file_path": "README.md", "content": "# New\n"},
    "tool_use_id": "t1",
}


async def lup_dev_hook(asked: Asked) -> Judged:
    """A launch's copy of `lup-dev`, run in this process, in a thread: its own `hook` command."""
    _, *arguments = asked.command
    ran = await asyncio.to_thread(
        runner.invoke, cli.app, arguments, input=asked.payload
    )
    return Judged(status=ran.exit_code, output=ran.output, error="")


def test_the_service_answers_a_hook_as_the_hook_command_does(
    fakes: Kit,
    repo: Path,
    layout: HostLayout,
    clock: FakeClock,
    said: list[str],
    *,
    tmp_path: Path,
) -> None:
    raw = json.dumps({**PAYLOAD, "cwd": str(repo)})
    answerer = cli.Adapters(known=cli.adapters())
    one = launch(tmp_path, "one", "claude").model_copy(update={"worktree": repo})
    with served(service(layout, lup_dev_hook, said, answerer=answerer)):
        client(layout, clock).register(one)
        heard = send(layout.launch("one").hook, raw)
        unread = send(layout.launch("one").hook, "not a payload")
    printed = runner.invoke(cli.app, ["hook", "claude"], input=raw).output
    assert heard == printed
    assert json.loads(heard)["hookSpecificOutput"]["permissionDecision"] == "allow"
    warned = json.loads(unread)["systemMessage"]
    assert warned.startswith("lup's judge couldn't answer this hook")


def test_a_judge_runs_as_a_process_of_its_own(tmp_path: Path) -> None:
    judge = tmp_path / "lup-dev"
    judge.write_text('#!/bin/sh\necho "$@"\ncat\necho said >&2\nexit 3\n')
    judge.chmod(0o755)

    ran = asyncio.run(
        judged(Asked(command=[str(judge), "hook", "first"], payload="the payload"))
    )

    assert ran == Judged(status=3, output="hook first\nthe payload", error="said\n")
    missing = asyncio.run(
        judged(Asked(command=[str(tmp_path / "gone"), "hook"], payload=""))
    )
    assert missing.status == 127
    assert "gone" in missing.error


def test_a_judge_whose_wait_is_cancelled_is_killed(tmp_path: Path) -> None:
    judge = tmp_path / "lup-dev"
    started = tmp_path / "started"
    # A pipe: the judge's write blocks until the test reads, so nothing polls.
    os.mkfifo(started)
    judge.write_text(f"#!/bin/sh\necho $$ > {started}\nexec sleep 3600\n")
    judge.chmod(0o755)

    async def cancelled() -> int:
        waiting = asyncio.create_task(
            judged(Asked(command=[str(judge), "hook"], payload=""))
        )
        pid = int(await asyncio.to_thread(started.read_text))
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        return pid

    pid = asyncio.run(cancelled())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.fixture
def machine(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    clock: FakeClock,
) -> HostLayout:
    """The host service where the command line places it, with the fake clock."""
    xdg = tmp_path_factory.mktemp("xdg")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg / "run"))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg / "state"))
    monkeypatch.setattr(cli, "SystemClock", lambda: clock)
    return Layout(state=xdg / "state" / "lup", runtime=xdg / "run" / "lup").host


def test_host_stop_says_whether_a_service_ran(
    machine: HostLayout, said: list[str]
) -> None:
    assert runner.invoke(cli.app, ["host", "stop"]).output == "No host service runs.\n"
    with served(service(machine, Judge(), said)):
        result = runner.invoke(cli.app, ["host", "stop"])
        assert result.output == "Stopped the host service.\n"


def test_host_refuses_to_serve_beside_a_running_service(
    machine: HostLayout, said: list[str]
) -> None:
    with served(service(machine, Judge(), said)):
        result = runner.invoke(cli.app, ["host"])
    assert isinstance(result.exception, HostError)
    assert "a host service runs already" in str(result.exception)


# A launch's modules, served beside the core's tools.


class Words(Model):
    """What to shout."""

    text: str


class LoudTools(ModuleTools):
    """Loud's tool."""

    module: Loud

    @lup_tool
    async def shout(self, said: Words) -> str:
        """Shout, naming who's calling."""
        return f"{said.text.upper()}, {self.caller.id} of {self.launch.launch}"


class Loud(Module):
    """Shouting."""

    name = "loud"

    tools: Toolsets = Toolsets.of(LoudTools)


class Broken(LaunchModules):
    """A launch's modules that can't be served: its copy predates them."""

    @override
    async def open(self, launch: Register) -> Offered:
        message = "its copy predates `worker`"
        raise HostError(message)

    @override
    async def ask(self, launch: Register, request: Request) -> Reply:
        message = "nothing is served to ask"
        raise AssertionError(message)

    @override
    async def close(self, launch: Register) -> None:
        return None


def test_a_launch_s_modules_tools_are_served_beside_the_core_s_with_the_caller(
    layout: HostLayout,
    clock: FakeClock,
    said: list[str],
    tmp_path: Path,
    in_process: type[InProcess],
) -> None:
    host = client(layout, clock)
    modules = in_process(
        resolved=resolve(Project(modules=Modules.only(Core(), Loud())))
    )
    with served(on_claude(layout, Quiet(), said, [Recording()], modules)):
        host.register(launch(tmp_path, "one", "claude"))
        send(layout.launch("one").hook, claude("SessionStart", source="startup"))
        arguments = stamped(send(layout.launch("one").hook, lups("shout", "t1")))
        stamp = arguments["caller"]
        assert listed(layout.launch("one").mcp) == ["echo", "rename", "shout"]
        heard = call(layout.launch("one").mcp, "shout", arguments)
        host.unregister("one")
    assert heard == (f"HI, {stamp} of one", False)
    assert modules.closed == ["one"]


def test_a_launch_whose_modules_cant_be_served_gets_the_core_s_tools_alone(
    layout: HostLayout, clock: FakeClock, said: list[str], tmp_path: Path
) -> None:
    host = client(layout, clock)
    with served(service(layout, Judge(), said, tools=[Recording()], modules=Broken())):
        host.register(launch(tmp_path, "one", "first"))
        assert listed(layout.launch("one").mcp) == ["echo", "rename"]
    assert "one: its modules aren't served: its copy predates `worker`" in said


def test_a_module_s_tool_named_like_a_core_tool_is_left_to_the_core(
    layout: HostLayout,
    clock: FakeClock,
    said: list[str],
    tmp_path: Path,
    in_process: type[InProcess],
) -> None:
    host = client(layout, clock)
    core = Recording(["shout"])
    modules = in_process(
        resolved=resolve(Project(modules=Modules.only(Core(), Loud())))
    )
    with served(on_claude(layout, Quiet(), said, [core], modules)):
        host.register(launch(tmp_path, "one", "claude"))
        send(layout.launch("one").hook, claude("SessionStart", source="startup"))
        arguments = stamped(send(layout.launch("one").hook, lups("shout", "t1")))
        assert listed(layout.launch("one").mcp) == ["shout", "rename"]
        heard = call(layout.launch("one").mcp, "shout", arguments)
    assert heard == (f"one heard {arguments['caller']}", False)
    assert any("which the core serves already" in line for line in said)


class Moments(ModuleHooks):
    """Listens when a call starts, and when the launch opens and stops, so the service tells it."""

    module: Listener

    @lup_hook
    async def call_started(self, moment: Moment) -> None:
        """Listen."""

    @lup_hook(on=["launched", "stopped"])
    async def bounds(self, moment: Moment) -> None:
        """Listen."""


class Listener(Module):
    """Listening."""

    name = "listener"

    hooks: Hooks = Hooks.of(Moments)


def test_a_launch_s_modules_are_told_the_moments_they_listen_to(
    layout: HostLayout,
    clock: FakeClock,
    said: list[str],
    tmp_path: Path,
    in_process: type[InProcess],
) -> None:
    host = client(layout, clock)
    modules = in_process(
        resolved=resolve(Project(modules=Modules.only(Core(), Listener()))),
        layout=Layout(state=tmp_path / "state", data=tmp_path / "data"),
    )
    with served(on_claude(layout, Quiet(), said, [Recording()], modules)):
        host.register(launch(tmp_path, "one", "claude"))
        send(layout.launch("one").hook, claude("SessionStart", source="startup"))
        send(layout.launch("one").hook, lups("echo", "t1"))
        host.unregister("one")
    told = [each.occasion for each in modules.told]
    assert sorted(told) == ["call-started", "launched", "stopped"]
    assert told[-1] == "stopped"
    [call] = [each for each in modules.told if each.occasion == "call-started"]
    assert call.tool == "mcp__lup__echo"
    assert call.conversation is not None
    assert modules.closed == ["one"]


class Reads(Courier):
    """Hears each payload as the `Heard` it is, and adds nothing."""

    def heard(self, runtime: str, payload: str) -> Heard:
        return Heard.model_validate_json(payload)

    def told(self, runtime: str, payload: str, answer: str, telling: Telling) -> str:
        return answer

    def woken(self, runtime: str, session: str, text: str) -> str | None:
        return None


def hook(event: Event, **fields: object) -> str:
    """A hook of session `s1` the judge doesn't read, as `Reads` hears it."""
    return json.dumps(
        {"event": event, "session": "s1", "judged": False, "fits": 10_000, **fields}
    )


@contextmanager
def watched(layout: HostLayout, request: Request) -> Generator[Callable[[], str]]:
    """Watch `request` on the service's watch socket, its connection open both ways: each call reads its next reply's line, empty once the watch ends."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(60)
        connection.connect(str(layout.watch))
        connection.sendall(f"{request.model_dump_json()}\n".encode())
        with connection.makefile("rb") as stream:
            yield lambda: stream.readline().decode()


def names(listed: str) -> list[str | None]:
    return [each.name for each in Listed.model_validate_json(listed).launches]


def test_a_watch_answers_at_once_then_again_each_time_its_reply_changes(
    layout: HostLayout, said: list[str], tmp_path: Path, clock: FakeClock
) -> None:
    own = client(layout, clock)
    with (
        served(service(layout, Judge(), said)),
        watched(layout, ListLaunches()) as following,
    ):
        first = following()
        own.register(launch(tmp_path, "one", "first"))
        second = following()
        own.listed()
        own.rename("one", "renamed")
        third = following()
    assert names(first) == []
    assert names(second) == ["one"]
    assert names(third) == ["renamed"]


def test_a_hook_reaches_a_watch_each_conversation_saying_what_its_doing(
    layout: HostLayout, said: list[str], tmp_path: Path, clock: FakeClock
) -> None:
    own = client(layout, clock)
    with served(service(layout, Judge(), said, courier=Reads(), clock=clock)):
        own.register(launch(tmp_path, "one", "first"))
        hooks = layout.launch("one").hook
        with watched(layout, ListLaunches()) as following:
            before = following()
            send(hooks, hook("session-started"))
            started = following()
            send(hooks, hook("call-started", call="c1", tool="Bash"))
            calling = following()
            asking = hook(
                "call-started", agent="a1", call="c2", tool="mcp__lup__ask", served=True
            )
            send(hooks, asking)
            held = following()
            send(hooks, hook("conversation-ended", agent="a1"))
            ended = following()

    def doing(listed: str) -> list[tuple[str, Activity | None]]:
        talkers = Listed.model_validate_json(listed).talkers["one"]
        return [(each.path, each.activity) for each in talkers]

    at = clock.now()
    bash = Activity(state="calling", since=at, tool="Bash")
    assert doing(before) == []
    assert doing(started) == [("one", Activity(state="idle", since=at))]
    assert doing(calling) == [("one", bash)]
    assert doing(held) == [
        ("one", bash),
        (
            "one/subagent·a1",
            Activity(state="calling", since=at, tool="mcp__lup__ask", lups=True),
        ),
    ]
    assert doing(ended) == [
        ("one", bash),
        ("one/subagent·a1", Activity(state="ended", since=at)),
    ]


def test_what_a_conversation_is_doing_outlasts_a_restart_of_the_service(
    layout: HostLayout, said: list[str], tmp_path: Path, clock: FakeClock
) -> None:
    own = client(layout, clock)
    with served(service(layout, Judge(), said, courier=Reads(), clock=clock)):
        own.register(launch(tmp_path, "one", "first"))
        send(layout.launch("one").hook, hook("call-started", call="c1", tool="Bash"))
    with served(service(layout, Judge(), said, courier=Reads(), clock=clock)):
        listed = own.listed()
    [talker] = listed.talkers["one"]
    assert talker.activity == Activity(state="calling", since=clock.now(), tool="Bash")


def test_a_watch_of_what_cant_be_answered_is_refused_and_ends(
    layout: HostLayout, said: list[str]
) -> None:
    with (
        served(service(layout, Judge(), said)),
        watched(layout, Request(kind="nowhere")) as following,
    ):
        refused = Refused.model_validate_json(following())
        after = following()
    assert refused.error == (
        "no handler for `nowhere`; the service answers list, register, rename, "
        "stop, unregister"
    )
    assert after == ""


def test_a_client_on_an_event_loop_asks_watches_and_hears_the_service_stop(
    layout: HostLayout, said: list[str], tmp_path: Path
) -> None:
    async def watching_launches() -> tuple[list[list[str | None]], str]:
        seen: list[list[str | None]] = []
        try:
            async for listed in watching(layout.watch, ListLaunches(), Listed):
                seen.append([each.name for each in listed.launches])
                if len(seen) == 1:
                    one = launch(tmp_path, "one", "first")
                    await requested(layout.control, one, Registered)
                if len(seen) == 2:
                    await requested(layout.control, Stop(), Done)
        except HostError as closed:
            return seen, str(closed)
        return seen, "the watch ended without a word"

    with served(service(layout, Judge(), said)):
        seen, closed = asyncio.run(watching_launches())
    assert seen == [[], ["one"]]
    assert closed == "the host service closed the watch"


STAND_IN = """
import sys
from pathlib import Path

record = Path(sys.argv[1])
token = sys.stdin.readline().strip()
port = sys.argv[-1]
if port == "1":
    sys.exit(3)
with record.open("a") as kept:
    kept.write(f"started with {token} on {port}\\n")
print(f"http://127.0.0.1:{port}", flush=True)
sys.stdin.read()
with record.open("a") as kept:
    kept.write("ended\\n")
"""


def stand_in(tmp_path: Path, port: int = 8766) -> tuple[DashboardProcess, Path]:
    """A dashboard whose command is a stand-in script, recording how it was started and that it ended."""
    script = tmp_path / "dashboard.py"
    script.write_text(STAND_IN)
    record = tmp_path / "record"
    dashboard = DashboardProcess(
        command=[sys.executable, str(script), str(record)],
        port=port,
        token=tmp_path / "state" / "dashboard.token",
    )
    return dashboard, record


def shown(dashboard: DashboardProcess | None) -> Route:
    return Route.to(Showing(dashboard=dashboard, missing="no dashboard here"))


def test_the_dashboard_starts_with_the_service_its_token_kept_and_ends_with_it(
    layout: HostLayout, said: list[str], tmp_path: Path, clock: FakeClock
) -> None:
    dashboard, record = stand_in(tmp_path)
    with served(
        service(
            layout, Judge(), said, routes=[shown(dashboard)], companions=[dashboard]
        )
    ):
        first = client(layout, clock).ask(ShowDashboard(), DashboardShown)
    with served(
        service(
            layout, Judge(), said, routes=[shown(dashboard)], companions=[dashboard]
        )
    ):
        second = client(layout, clock).ask(ShowDashboard(), DashboardShown)
    token = dashboard.token.read_text()
    assert first.address == f"http://127.0.0.1:8766/#token={token}"
    assert second.address == first.address
    assert dashboard.token.stat().st_mode & 0o777 == 0o600
    assert record.read_text() == (
        f"started with {token} on 8766\nended\nstarted with {token} on 8766\nended\n"
    )


def test_a_dashboard_gone_is_started_again_when_its_address_is_asked(
    layout: HostLayout, said: list[str], tmp_path: Path, clock: FakeClock
) -> None:
    dashboard, record = stand_in(tmp_path)
    with served(
        service(
            layout, Judge(), said, routes=[shown(dashboard)], companions=[dashboard]
        )
    ):
        process = dashboard.process
        assert process is not None
        assert process.stdin is not None
        process.stdin.close()
        own = client(layout, clock)
        while process.returncode is None:
            own.listed()
        again = own.ask(ShowDashboard(), DashboardShown)
    assert again.address.startswith("http://127.0.0.1:8766/#token=")
    assert record.read_text().count("started with") == 2


def test_a_dashboard_that_cant_listen_or_isnt_there_is_said_and_the_service_goes_on(
    layout: HostLayout, said: list[str], tmp_path: Path, clock: FakeClock
) -> None:
    dashboard, _ = stand_in(tmp_path, port=1)
    with served(
        service(
            layout, Judge(), said, routes=[shown(dashboard)], companions=[dashboard]
        )
    ):
        listed = client(layout, clock).listed()
    with (
        served(service(layout, Judge(), said, routes=[shown(None)])),
        pytest.raises(HostError) as missing,
    ):
        client(layout, clock).ask(ShowDashboard(), DashboardShown)
    assert listed.launches == []
    [failed] = [line for line in said if "without a program beside it" in line]
    assert failed.endswith(
        "ended with status 3 before listening, as on a port another program holds "
        "(1, `LUP_DASHBOARD_PORT`); what it said is in the host service's output"
    )
    assert str(missing.value) == "no dashboard here"
