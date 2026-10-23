"""Running programs on an event loop: `awaited` to its end, `started` beside it.

Each program is a tiny one that ends as told or never ends by itself, so no
test waits on a clock: one that runs forever ends only where lup kills it.
"""

import asyncio
import os
import signal
import sys
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from lup.programs import (
    ProgramFailedError,
    ProgramMissingError,
    ProgramOverflowError,
    awaited,
    started,
)

if TYPE_CHECKING:
    from pathlib import Path

PYTHON = sys.executable


def python(code: str) -> list[str]:
    """Return the command running `code` in this Python."""
    return [PYTHON, "-c", code]


ECHOING = python(
    "import sys; data = sys.stdin.read(); sys.stdout.write(data.upper()); "
    "sys.stderr.write('said'); sys.exit(3)"
)


def test_awaited_gives_its_input_and_keeps_what_it_printed_and_said_apart() -> None:
    ran = asyncio.run(awaited(*ECHOING, stdin="hello", checked=False))
    assert ran.status == 3
    assert ran.output == b"HELLO"
    assert ran.said() == "said"


def test_awaited_merges_what_it_said_into_what_it_printed() -> None:
    ran = asyncio.run(awaited(*ECHOING, stdin="hello", ok=[3], merged=True))
    assert ran.text() == "HELLOsaid"
    assert ran.error == b""


def test_awaited_refuses_a_status_not_accepted_and_a_program_that_isnt_there(
    tmp_path: Path,
) -> None:
    with pytest.raises(ProgramFailedError) as failed:
        asyncio.run(awaited(*ECHOING, stdin="hello"))
    assert failed.value.ran.status == 3
    assert str(failed.value).endswith("ended with status 3: said")
    with pytest.raises(ProgramMissingError):
        asyncio.run(awaited(tmp_path / "nowhere"))


def test_awaited_kills_a_program_printing_past_its_limit() -> None:
    # `yes` prints until it's killed, so this ends only where the limit kills it.
    with pytest.raises(ProgramOverflowError, match="printed more than 10 bytes"):
        asyncio.run(awaited("yes", limit=10))
    printed = asyncio.run(awaited("printf", "0123456789", limit=10))
    assert printed.output == b"0123456789"


def test_awaited_discards_what_it_prints_and_never_waits_on_a_process_holding_it(
    tmp_path: Path,
) -> None:
    left = tmp_path / "left"
    # The program leaves a process behind that holds its output open and runs
    # until it's killed, as a clipboard's program leaves one serving what was
    # copied: read from a pipe, its output would never end.
    leaving = (
        f'sleep 1000 & echo $! > "{left}"; echo printed; echo said >&2; cat > /dev/null'
    )
    try:
        ran = asyncio.run(awaited("sh", "-c", leaving, stdin="copied", discarded=True))
    finally:
        os.kill(int(left.read_text()), signal.SIGKILL)
    assert ran.status == 0
    assert ran.output == ran.error == b""


def test_awaited_kills_its_program_where_the_wait_is_cancelled(tmp_path: Path) -> None:
    started = tmp_path / "started"
    # A pipe: the program's write blocks until the test reads, so nothing polls.
    os.mkfifo(started)
    sleeping = f'echo $$ > "{started}"; exec sleep 1000'

    async def cancelled() -> int:
        waiting = asyncio.create_task(awaited("sh", "-c", sleeping))
        pid = int(await asyncio.to_thread(started.read_text))
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        return pid

    pid = asyncio.run(cancelled())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def filling(started: Path, printed: Path) -> list[str]:
    """Return a program that says its pid on `started`, prints a mebibyte at once into a pipe made large enough to hold it, says so on `printed`, then waits to be killed.

    Each is a named pipe, so nothing polls. While the test holds the event loop
    until `printed`, nothing reads the output: once the loop goes on, asyncio
    reads past what it buffers for a stream nobody reads and stops reading the
    pipe, which then closes only where the rest is read.
    """
    return python(
        "import fcntl, os, signal, sys\n"
        f"open({str(started)!r}, 'w').write(str(os.getpid()))\n"
        "fcntl.fcntl(1, fcntl.F_SETPIPE_SZ, 1 << 20)\n"
        "sys.stdout.buffer.write(bytes(1 << 20))\n"
        "sys.stdout.flush()\n"
        f"open({str(printed)!r}, 'w').close()\n"
        "signal.pause()\n"
    )


def test_awaited_reads_a_program_killed_past_its_limit_to_its_end(
    tmp_path: Path,
) -> None:
    # Waiting on a program returns only once its pipes closed, so the output
    # past the limit is read to its end, or the wait never ended.
    started, printed = tmp_path / "started", tmp_path / "printed"
    os.mkfifo(started)
    os.mkfifo(printed)

    async def overflowed() -> int:
        waiting = asyncio.create_task(awaited(*filling(started, printed), limit=10))
        pid = int(await asyncio.to_thread(started.read_text))
        printed.read_text()  # The loop held: the mebibyte is printed, unread.
        with pytest.raises(ProgramOverflowError):
            await waiting
        return pid

    pid = asyncio.run(overflowed())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_awaited_reads_a_program_killed_where_the_wait_is_cancelled_to_its_end(
    tmp_path: Path,
) -> None:
    started, printed = tmp_path / "started", tmp_path / "printed"
    os.mkfifo(started)
    os.mkfifo(printed)

    async def cancelled() -> int:
        waiting = asyncio.create_task(awaited(*filling(started, printed)))
        pid = int(await asyncio.to_thread(started.read_text))
        printed.read_text()  # The loop held: the mebibyte is printed, unread.
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        return pid

    pid = asyncio.run(cancelled())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_started_talks_over_its_input_and_output_and_ends_when_its_input_closes() -> (
    None
):
    upper = python(
        "import sys\n"
        "for line in sys.stdin:\n"
        "    print(line.upper(), end='', flush=True)\n"
    )

    async def exercised() -> tuple[bytes, int | None, int, int | None]:
        running = await started(*upper)
        running.input.write(b"hi\n")
        await running.input.drain()
        line = await running.output.readline()
        before = running.status
        status = await running.ended()
        return line, before, status, running.status

    assert asyncio.run(exercised()) == (b"HI\n", None, 0, 0)


def test_started_kills_a_program_still_there_once_its_time_to_end_is_up() -> None:
    # It never reads its input, so closing it ends nothing: only the kill does.
    async def exercised() -> int:
        running = await started("sleep", "1000")
        return await running.ended(within=timedelta(0))

    assert asyncio.run(exercised()) == -9


def test_started_refuses_a_program_that_isnt_there(tmp_path: Path) -> None:
    with pytest.raises(ProgramMissingError, match="can't be started"):
        asyncio.run(started(tmp_path / "nowhere"))
