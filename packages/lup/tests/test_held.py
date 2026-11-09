"""Claude Code held over its stream-json wire, against the in-process stand-in that answers as the CLI was measured to: no process, no model."""

import asyncio
import errno
import inspect
import json
import os
import socket
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from lup.adapters.claude import Claude
from lup.adapters.claude.held import ClaudeHeld, HeldError
from lup.adapters.claude.standin import StandIn
from lup.rooms.engine import Pipes, ended
from lup.sessions import connected
from lup.sessions.terminal import Cli, TerminalSettings


def test_a_message_starts_a_turn_whose_start_and_end_are_said() -> None:
    said: list[str] = []

    async def talking() -> tuple[StandIn, ClaudeHeld, int]:
        piped = await StandIn.paired(session="s-1")
        assert isinstance(piped.run, StandIn)
        held = ClaudeHeld(pipes=piped.pipes, said=said.append)
        reading = asyncio.create_task(held.served())
        await held.send('<channel source="lup" wake="t0k3n">hello</channel>')
        status = await ended(piped, timedelta(seconds=5))
        await reading
        return piped.run, held, status

    standin, held, status = asyncio.run(talking())

    assert standin.prompts == ['<channel source="lup" wake="t0k3n">hello</channel>']
    assert held.session == "s-1"
    assert not held.turning
    assert said == ["A turn started.", "A turn ended: success, completed."]
    assert status == 0


def test_an_interrupt_is_answered_and_ends_the_turn_under_way() -> None:
    said: list[str] = []

    async def interrupting() -> tuple[StandIn, bool]:
        piped = await StandIn.paired(session="s-1", lingering=True)
        assert isinstance(piped.run, StandIn)
        standin = piped.run
        held = ClaudeHeld(pipes=piped.pipes, said=said.append)
        reading = asyncio.create_task(held.served())
        await held.send("run something long")
        await held.interrupt()
        turning = held.turning
        await ended(piped, timedelta(seconds=5))
        await reading
        return standin, turning

    standin, turning = asyncio.run(interrupting())

    assert standin.interrupts == 1
    assert not turning
    assert said == [
        "A turn started.",
        "A turn ended: error_during_execution, aborted_tools, an error.",
    ]


def test_an_interrupt_unanswered_within_its_patience_raises() -> None:
    async def unanswered() -> None:
        ours, theirs = socket.socketpair()
        reading, writing = await asyncio.open_unix_connection(sock=ours)
        held = ClaudeHeld(
            pipes=Pipes(input=writing, output=reading),
            said=lambda _: None,
            patience=timedelta(0),
        )
        try:
            await held.interrupt()
        finally:
            writing.close()
            theirs.close()

    with pytest.raises(HeldError, match="didn't answer the interrupt"):
        asyncio.run(unanswered())


def test_a_request_waiting_as_the_session_ends_fails_and_one_of_its_own_is_refused() -> (
    None
):
    said: list[str] = []

    async def ending() -> tuple[list[dict[str, object]], BaseException | None]:
        ours, theirs = socket.socketpair()
        reading, writing = await asyncio.open_unix_connection(sock=ours)
        heard, saying = await asyncio.open_unix_connection(sock=theirs)
        held = ClaudeHeld(
            pipes=Pipes(input=writing, output=reading),
            said=said.append,
            patience=timedelta(seconds=30),
        )
        reading_task = asyncio.create_task(held.served())
        interrupting = asyncio.create_task(held.interrupt())
        asked = json.loads(await heard.readline())
        saying.write(b"not json\n")
        saying.write(
            json.dumps(
                {
                    "type": "control_request",
                    "request_id": "cli-1",
                    "request": {"subtype": "can_use_tool"},
                }
            ).encode()
            + b"\n"
        )
        await saying.drain()
        refusal = json.loads(await heard.readline())
        saying.close()
        await reading_task
        failure = None
        try:
            await interrupting
        except HeldError as failed:
            failure = failed
        writing.close()
        return [asked, refusal], failure

    lines, failure = asyncio.run(ending())

    asked, refusal = lines
    assert asked == {
        "type": "control_request",
        "request_id": "lup-1",
        "request": {"subtype": "interrupt"},
    }
    assert refusal == {
        "type": "control_response",
        "response": {
            "subtype": "error",
            "request_id": "cli-1",
            "error": "lup's launcher takes no request of the session's",
        },
    }
    assert isinstance(failure, HeldError)
    assert "ended before answering" in str(failure)
    assert said == [
        "The session wrote a line of 9 bytes that isn't one of its messages.",
        (
            'The session asked the launcher {"subtype": "can_use_tool"}, which it '
            "doesn't answer: refused."
        ),
    ]


def test_the_held_command_is_the_terminal_s_on_stream_json_with_nothing_pushed() -> (
    None
):
    settings = TerminalSettings(
        directory=Path("/launch"),
        cli=Cli(program=Path("/opt/clis/claude")),
        messages=Path("/run/lup/messages.sock"),
    )
    terminal = Claude().terminal(settings)
    held = Claude().held(settings)

    assert "--messaging-socket-path" in terminal.command
    assert "--messaging-socket-path" not in held.command
    assert "-p" not in held.command
    assert held.command[-5:] == [
        "--output-format",
        "stream-json",
        "--verbose",
        "--input-format",
        "stream-json",
    ]


def test_a_held_room_s_first_program_puts_its_socket_on_the_runtime_s_input_and_output_which_proc_cant_open_again(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The wrapper run for real, the runtime a Python echoing a line: what it reads and writes is the socket, and opening its input again through `/proc`, as another process of the room would, is refused."""
    wrapper = tmp_path / "connected.py"
    wrapper.write_text(inspect.getsource(connected))
    place = tmp_path_factory.mktemp("s") / "session.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(place))
    listener.listen(1)
    echoing = (
        "import sys\nfor line in sys.stdin:\n"
        "    sys.stdout.write(line.upper())\n    sys.stdout.flush()"
    )
    with subprocess.Popen(  # noqa: S603
        [sys.executable, "-I", str(wrapper), str(place), sys.executable, "-c", echoing],
        stdin=subprocess.DEVNULL,
    ) as runtime:
        connection, _ = listener.accept()
        with connection, connection.makefile("rb") as answers:
            connection.sendall(b"hello\n")
            # Its answer means the runtime runs, in the wrapper's place, on the socket.
            echoed = answers.readline()
            reopened: OSError | None = None
            try:
                os.open(f"/proc/{runtime.pid}/fd/0", os.O_WRONLY)
            except OSError as refused:
                reopened = refused
            connection.shutdown(socket.SHUT_WR)
            rest = answers.read()
        status = runtime.wait(timeout=30)
    listener.close()

    assert echoed == b"HELLO\n"
    assert rest == b""
    assert status == 0
    assert isinstance(reopened, OSError)
    assert reopened.errno == errno.ENXIO
