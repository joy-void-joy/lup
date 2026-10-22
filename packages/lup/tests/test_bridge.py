"""lup's MCP bridge: a runtime's lines carried to a stand-in server on a Unix socket, which stops and starts again under it.

The bridge runs in a thread of the test, as it runs in a room: its runtime's side
is a queue of lines in and the lines it writes out, its server's a socket
server in threads of its own. Nothing waits on the clock: each step waits for
the line it expects, and the bridge tries the server again every hundredth of a
second.
"""

import contextlib
import io
import json
import queue
import socket
import socketserver
import subprocess
import sys
import threading
from typing import TYPE_CHECKING, override

import pytest

from lup.sessions import bridge
from lup.sessions.bridge import Bridge, Json

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path

type Message = dict[str, Json]

PATIENT = 30.0
"""How long a step waits for the line it expects before failing the test."""


class Said(io.StringIO):
    """The runtime's side of the bridge's output: each line, as a message."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: queue.Queue[Message] = queue.Queue()

    @override
    def write(self, text: str) -> int:
        for each in text.splitlines():
            self.lines.put(json.loads(each))
        return len(text)


class Runtime:
    """What a runtime sends the bridge, and what it hears back."""

    def __init__(self) -> None:
        self.inbox: queue.Queue[str | None] = queue.Queue()
        self.said = Said()

    def lines(self) -> Iterator[str]:
        while (each := self.inbox.get()) is not None:
            yield each

    def send(self, message: Message) -> None:
        self.inbox.put(json.dumps(message) + "\n")

    def call(self, ident: int, name: str, meta: Message | None = None) -> None:
        """Call the tool `name` under `ident`, its `_meta` as `meta` frames it, where a runtime frames one."""
        self.send(
            {
                "jsonrpc": "2.0",
                "id": ident,
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": {},
                    **({} if meta is None else {"_meta": meta}),
                },
            }
        )

    def list_tools(self, ident: int) -> None:
        self.send({"jsonrpc": "2.0", "id": ident, "method": "tools/list"})

    def heard(self) -> Message:
        return self.said.lines.get(timeout=PATIENT)

    def close(self) -> None:
        self.inbox.put(None)


INITIALIZE: Message = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "runtime", "version": "1"},
    },
}
INITIALIZED: Message = {"jsonrpc": "2.0", "method": "notifications/initialized"}

CLIENTS: dict[str, Json] = {
    "claude": {"name": "claude-code", "version": "2.1.306"},
    "codex": {"name": "codex-mcp-client", "version": "0.162.1"},
}
"""How each runtime names itself on its `initialize`."""

RUNTIMES = pytest.mark.parametrize("client", list(CLIENTS))
"""The runtimes, each framing its introduction and its calls its own way, which the bridge carries as they are."""


def introduction(client: str) -> Message:
    """The `initialize` request of `client`, one of `CLIENTS`."""
    return {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": CLIENTS[client],
        },
    }


def framed(client: str, ident: int) -> Message:
    """How `client` frames a call's `_meta`: Claude Code's `claudecode/toolUseId`, Codex's `callId` with its thread and session (`docs/field-notes.md`, *MCP in a launched session*)."""
    if client == "codex":
        return {"callId": f"call_{ident}", "threadId": "t1", "sessionId": "s1"}
    return {"claudecode/toolUseId": f"toolu_{ident}"}


TOOLS: list[Json] = [
    {
        "name": "inbox",
        "description": "Read the inbox.",
        "inputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True, "idempotentHint": False},
    },
    {
        "name": "wait_inbox",
        "description": "Wait for the inbox.",
        "inputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": False, "idempotentHint": True},
    },
    {
        "name": "note",
        "description": "Tell the operator.",
        "inputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": False, "idempotentHint": False},
    },
]
"""What the stand-in lists, as lup's server lists its tools with their marks: a read, a call that finds its wait again, and one that acts."""


class Host:
    """A stand-in for lup's server: it answers `initialize`, lists `TOOLS`, and answers each tool call with the tool's name, but holds a call to a tool among `holds`, which it puts in `held` unanswered."""

    def __init__(self, path: Path, holds: frozenset[str] = frozenset({"hold"})) -> None:
        self.path = path
        self.holds = holds
        self.heard: list[Message] = []
        self.held: queue.Queue[Message] = queue.Queue()
        self.connections: list[socket.socket] = []
        host = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                host.connections.append(self.connection)
                for raw in self.rfile:
                    message = json.loads(raw)
                    host.heard.append(message)
                    answer = host.answer(message)
                    if answer is not None:
                        self.wfile.write((json.dumps(answer) + "\n").encode())

        self.server = socketserver.ThreadingUnixStreamServer(str(path), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def answer(self, message: Message) -> Message | None:
        match message:
            case {"method": "initialize", "id": ident}:
                return {
                    "jsonrpc": "2.0",
                    "id": ident,
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {"listChanged": True}},
                        "serverInfo": {"name": "lup", "version": "1"},
                    },
                }
            case {"method": "tools/list", "id": ident}:
                return {"jsonrpc": "2.0", "id": ident, "result": {"tools": TOOLS}}
            case {"method": "tools/call", "params": {"name": str() as name}} if (
                name in self.holds
            ):
                self.held.put(message)
                return None
            case {"method": "tools/call", "id": ident, "params": {"name": name}}:
                return {
                    "jsonrpc": "2.0",
                    "id": ident,
                    "result": {"content": [{"type": "text", "text": name}]},
                }
            case _:
                return None

    def stop(self) -> None:
        # Each handler reads the bridge's connection until it closes, and closing
        # the server waits for every handler.
        self.server.shutdown()
        for each in self.connections:
            # One the bridge closed is closed already.
            with contextlib.suppress(OSError):
                each.shutdown(socket.SHUT_RDWR)
        self.server.server_close()
        self.thread.join(timeout=PATIENT)
        self.path.unlink(missing_ok=True)


@pytest.fixture
def path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # A socket's path is limited in length, so its directory is short.
    return tmp_path_factory.mktemp("mcp") / "mcp.sock"


@pytest.fixture
def runtime(path: Path) -> Generator[Runtime]:
    """A runtime with a bridge to `path`, running in a thread until the runtime closes its side."""
    runtime = Runtime()
    running = Bridge(path, runtime.said, retry=0.01)
    thread = threading.Thread(target=running.run, args=(runtime.lines(),), daemon=True)
    thread.start()
    yield runtime
    runtime.close()
    thread.join(timeout=PATIENT)
    assert not thread.is_alive()


def introduced(runtime: Runtime, client: str | None = None) -> None:
    """Introduce the runtime to the server, as `client` where one is named, and see it answered."""
    runtime.send(INITIALIZE if client is None else introduction(client))
    assert runtime.heard()["id"] == 0
    runtime.send(INITIALIZED)


def text(answer: Message) -> Json:
    match answer:
        case {"result": {"content": [{"text": said}]}}:
            return said
        case _:
            return None


def test_lines_go_across_both_ways(runtime: Runtime, path: Path) -> None:
    host = Host(path)
    introduced(runtime)
    runtime.call(1, "echo")
    answer = runtime.heard()
    host.stop()

    assert answer["id"] == 1
    assert text(answer) == "echo"
    assert [each.get("method") for each in host.heard] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]


def test_a_runtime_that_starts_before_its_server_is_heard_once_it_s_there(
    runtime: Runtime, path: Path
) -> None:
    runtime.send(INITIALIZE)
    host = Host(path)
    answer = runtime.heard()
    host.stop()
    assert answer["id"] == 0
    assert [each.get("method") for each in host.heard] == ["initialize"]


def test_across_a_restart_a_held_call_to_a_tool_not_listed_fails_and_the_session_carries_on(
    runtime: Runtime, path: Path
) -> None:
    first = Host(path)
    introduced(runtime)
    runtime.call(1, "hold")
    first.held.get(timeout=PATIENT)
    first.stop()

    lost = runtime.heard()
    runtime.call(2, "waited")
    second = Host(path)
    changed = runtime.heard()
    waited = runtime.heard()
    runtime.call(3, "after")
    after = runtime.heard()
    second.stop()

    match lost:
        case {"id": 1, "error": {"message": str() as said}}:
            assert "went away while answering this call" in said
            assert "`hold` acts, so it wasn't sent again" in said
            assert "may have been carried out" in said
        case _:
            pytest.fail(f"the held call wasn't answered with an error: {lost}")
    assert changed == {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
    assert (waited["id"], text(waited)) == (2, "waited")
    assert (after["id"], text(after)) == (3, "after")
    match second.heard:
        case [
            {"method": "initialize", "id": str() as ours, "params": params},
            {"method": "notifications/initialized"},
            {"method": "tools/call", "id": 2},
            {"method": "tools/call", "id": 3},
        ]:
            assert ours.startswith("lup-bridge-")
            assert params == INITIALIZE["params"]
        case _:
            pytest.fail(f"the restarted server heard {second.heard}")


@RUNTIMES
def test_across_a_restart_a_call_that_reads_or_waits_is_sent_again_and_one_that_acts_fails(
    client: str, runtime: Runtime, path: Path
) -> None:
    first = Host(path, holds=frozenset({"wait_inbox", "inbox", "note"}))
    introduced(runtime, client)
    runtime.list_tools(1)
    assert runtime.heard()["id"] == 1
    runtime.call(2, "wait_inbox", framed(client, 2))
    runtime.call(3, "inbox", framed(client, 3))
    runtime.call(4, "note", framed(client, 4))
    for _ in range(3):
        first.held.get(timeout=PATIENT)
    first.stop()

    failed = runtime.heard()
    second = Host(path)
    changed = runtime.heard()
    waited = runtime.heard()
    read = runtime.heard()
    second.stop()

    match failed:
        case {"id": 4, "error": {"message": str() as said}}:
            assert "`note` acts, so it wasn't sent again" in said
            assert "may have been carried out" in said
        case _:
            pytest.fail(f"the call that acts wasn't answered with an error: {failed}")
    assert changed == {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
    assert (waited["id"], text(waited)) == (2, "wait_inbox")
    assert (read["id"], text(read)) == (3, "inbox")
    # The same lines again, the runtime's `_meta` and all, before the
    # restarted server listed anything; nothing of the call that acts.
    assert [each.get("method") for each in second.heard] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
        "tools/call",
    ]
    assert second.heard[2:] == [first.heard[-3], first.heard[-2]]
    match second.heard[2]:
        case {"id": 2, "params": {"name": "wait_inbox", "_meta": meta}}:
            assert meta == framed(client, 2)
        case _:
            pytest.fail(f"the call sent again lost its frame: {second.heard[2]}")


def test_a_call_sent_again_waits_for_the_server_as_a_new_one_does_and_fails_without_it(
    path: Path,
) -> None:
    runtime = Runtime()
    impatient = Bridge(path, runtime.said, retry=0.01, patience=0.0)
    thread = threading.Thread(
        target=impatient.run, args=(runtime.lines(),), daemon=True
    )
    thread.start()
    first = Host(path, holds=frozenset({"wait_inbox"}))
    introduced(runtime)
    runtime.list_tools(1)
    assert runtime.heard()["id"] == 1
    runtime.call(2, "wait_inbox")
    first.held.get(timeout=PATIENT)
    first.stop()
    answer = runtime.heard()
    runtime.close()
    thread.join(timeout=PATIENT)

    match answer:
        case {"id": 2, "error": {"message": str() as said}}:
            assert f"hasn't answered on {path}" in said
        case _:
            pytest.fail(f"the call sent again wasn't answered with an error: {answer}")


def test_a_server_that_takes_the_connection_but_never_answers_isn_t_joined(
    runtime: Runtime, path: Path
) -> None:
    first = Host(path)
    introduced(runtime)
    first.stop()
    # A server going away: it takes the bridge's connection, reads its
    # introduction, and closes without answering.
    listening = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listening.bind(str(path))
    listening.listen(1)
    listening.settimeout(PATIENT)
    taken, _ = listening.accept()
    with taken.makefile("r", encoding="utf-8") as lines:
        introduction = json.loads(lines.readline())
    taken.close()
    listening.close()
    path.unlink()

    runtime.call(2, "waited")
    second = Host(path)
    changed = runtime.heard()
    waited = runtime.heard()
    second.stop()

    match introduction:
        case {"method": "initialize", "id": str() as ours}:
            assert ours.startswith("lup-bridge-")
        case _:
            pytest.fail(f"the bridge sent the silent server {introduction}")
    assert changed == {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
    assert (waited["id"], text(waited)) == (2, "waited")


def test_a_request_the_server_never_takes_is_answered_with_an_error(
    path: Path,
) -> None:
    runtime = Runtime()
    impatient = Bridge(path, runtime.said, retry=0.01, patience=0.0)
    thread = threading.Thread(
        target=impatient.run, args=(runtime.lines(),), daemon=True
    )
    thread.start()
    runtime.call(1, "anything")
    answer = runtime.heard()
    runtime.close()
    thread.join(timeout=PATIENT)

    match answer:
        case {"id": 1, "error": {"message": str() as said}}:
            assert f"hasn't answered on {path}" in said
        case _:
            pytest.fail(f"the waiting call wasn't answered with an error: {answer}")


def test_the_script_runs_on_python_alone_and_ends_with_its_runtime(
    path: Path,
) -> None:
    host = Host(path)
    running = subprocess.Popen(
        [sys.executable, "-I", bridge.__file__, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert running.stdin is not None
    assert running.stdout is not None
    running.stdin.write(json.dumps(INITIALIZE) + "\n")
    running.stdin.flush()
    answer = json.loads(running.stdout.readline())
    running.stdin.close()
    status = running.wait(timeout=PATIENT)
    host.stop()

    assert answer["id"] == 0
    assert status == 0


def test_the_script_says_what_it_takes(path: Path) -> None:
    ran = subprocess.run(
        [sys.executable, "-I", bridge.__file__],
        capture_output=True,
        text=True,
        timeout=PATIENT,
        check=False,
    )
    assert ran.returncode == 1
    assert "takes one argument: the server's socket" in ran.stderr
