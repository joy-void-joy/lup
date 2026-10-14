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
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import TYPE_CHECKING, Literal, override

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.host.client import HostClient, Starter
from lup_dev.host.protocol import (
    HostError,
    Limits,
    Refused,
    Register,
    Reply,
    Request,
    Stop,
)
from lup_dev.host.service import (
    Answerer,
    Asked,
    Handler,
    HostService,
    Judged,
    Route,
    judged,
)
from lup_dev.layout import HostLayout, Layout

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator
    from pathlib import Path

    from conftest import FakeClock, Kit

    from lup_dev.clock import Clock

runner = CliRunner()


class Stub(Answerer):
    """Knows two runtimes, and says a hook its judge couldn't answer in a form of its own."""

    def runtimes(self) -> list[str]:
        return ["first", "second"]

    def unanswered(self, runtime: str, payload: str, failure: str) -> str:
        return f"{runtime} unanswered {payload}: {failure}\n"


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
        """Stop the service if it still serves, and wait for its thread."""
        if self.thread.is_alive():
            try:
                send(self.service.layout.control, Stop().model_dump_json())
            except FileNotFoundError, ConnectionRefusedError:
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
) -> HostService:
    return HostService(
        layout=layout,
        answerer=answerer or Stub(),
        judge=judge,
        say=said.append,
        routes=routes or [],
    )


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
        directory = host.register(launch(tmp_path, "one", "first"))
        assert directory == layout.launch("one").directory
        assert layout.launch("one").hook.is_socket()
        payload = '{"hook_event_name": "Stop"}'
        assert send(layout.launch("one").hook, payload) == f"first answers {payload}\n"
    judge = tmp_path / "judges" / "bin" / "lup-dev"
    assert (
        f"one: served, first in {tmp_path}, judged by {judge}, its sockets in "
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
        directory = host.register(launch(tmp_path, "one", "first"))
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
        directory = host.register(launch(tmp_path, "one", "first"))
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
        directory = host.register(registered)
        mounted = directory.stat().st_ino
        host.stop()
    with served(service(layout, Judge(), said)):
        assert directory.stat().st_ino == mounted
        assert send(layout.launch("one").hook, "again") == "first answers again\n"
        assert host.launches() == [registered]
        host.unregister("one")


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
        with pytest.raises(HostError, match="a launch named `one` is served already"):
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
            "no handler for `nope`; the service answers list, register, stop, "
            "unregister"
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
    assert registered.is_dir()


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
