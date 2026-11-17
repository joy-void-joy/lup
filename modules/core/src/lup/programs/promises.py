"""The programs' promises: what a caller can count on of running a program.

Unlike every other promise, these start real programs, each a small one that
either ends as told or waits for good to open a named pipe nothing writes, so
no verdict depends on how loaded the machine is (`README.md` here, *Its
promises*).
"""

import asyncio
import errno
import os
import signal
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import lup
from lup.programs import (
    ProgramFailedError,
    ProgramMissingError,
    ProgramOverdueError,
    ProgramOverflowError,
    Ran,
    awaited,
    detached,
    run,
    spawned,
    started,
)
from lup.testing import Testing, raises

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Generator

SAYING = "cat; printf said >&2; exit 3"
"""A script printing what it's given, saying `said` beside, and ending with 3."""

INTERLEAVED = "printf a; printf b >&2; printf c"
"""A script printing and saying by turns: `a`, `b` said, `c`."""

LEAVING = 'cat "$1" & exec cat "$1"'
"""A script leaving a child in its process group, each waiting to open the
named pipe `$1` for good."""

LEFT_THEN_SAYING = 'cat "$1" & printf started > "$2"; exec cat "$1"'
"""`LEAVING`, saying on the named pipe `$2` once its child is started."""

ESCAPING = (
    'setsid sh -c \'printf left > "$2"; exec cat "$1"\' sh "$1" "$2" & exec cat "$1"'
)
"""A script leaving a process outside its process group, which the group's kill
doesn't reach, holding its output and waiting to open the named pipe `$1` for
good; that process says on the named pipe `$2` once it's out."""

TRICKY = "$HOME `true` 'quoted' \"too\" ; | & > * \\n %s"
"""An argument a shell would read as much more than text."""


def looped[T](story: Callable[[], Coroutine[None, None, T]]) -> T:
    """Run `story` on an event loop of asyncio's own, in a thread of its own, and return what it gives.

    The harness's loop starts no process (`lup/testing/README.md`, *Time and
    order*), and a thread runs one loop at a time, so a loop that does runs
    in a thread beside it, the promise waiting on it.
    """
    with ThreadPoolExecutor(max_workers=1) as apart:
        return apart.submit(asyncio.run, story()).result()


@contextmanager
def scratch() -> Generator[Path]:
    """Hold a directory of its own for as long as the block runs."""
    with tempfile.TemporaryDirectory() as directory:
        yield Path(directory)


def fifo(path: Path) -> Path:
    """Make a named pipe at `path`, and return it.

    Opening one waits until another opens it the other way, so a program
    opening one that nothing writes waits until it's killed.
    """
    os.mkfifo(path)
    return path


def waited_on(pipe: Path) -> bool:
    """Say whether a process waits to read the named pipe `pipe`, letting it go on to the end of what's written there: nothing."""
    try:
        writing = os.open(pipe, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as nobody:
        if nobody.errno != errno.ENXIO:
            raise
        return False
    os.close(writing)
    return True


def released(pipe: Path) -> None:
    """Let a process waiting to read the named pipe `pipe` go on, to the end of what's written there: nothing; wait for one where none waits yet."""
    pipe.write_bytes(b"")


class ProgramsPromises(lup.Part):
    """What a caller can count on of running a program."""

    @lup.promise
    async def what_it_is_given_and_prints_arrives_whole(self, by: Testing) -> None:
        """What a program is given reaches its input whole, and what it prints and what it says come back apart, or joined in the order written where merged, through `run` and `awaited` alike."""
        given = by.any(str).encode()

        async def through_awaited() -> list[Ran]:
            return [
                await awaited("sh", "-c", SAYING, stdin=given, checked=False),
                await awaited("sh", "-c", INTERLEAVED, merged=True),
            ]

        said, merged = looped(through_awaited)
        for ran in (run("sh", "-c", SAYING, stdin=given, checked=False), said):
            assert ran.status == 3
            assert ran.output == given
            assert ran.error == b"said"
        for ran in (run("sh", "-c", INTERLEAVED, merged=True), merged):
            assert ran.output == b"abc"
            assert ran.error == b""

    @lup.promise
    async def a_status_not_accepted_raises_how_it_ended(self, by: Testing) -> None:
        """A program ending with a status its caller doesn't accept raises `ProgramFailedError`, carrying how it ended; one it accepts, or any where it doesn't check, is answered; through `run` and `awaited` alike."""
        with raises(ProgramFailedError) as failed:
            run("false")
        assert failed.raised().ran.command == ["false"]
        assert failed.raised().ran.status == 1
        assert run("false", ok=[1]).status == 1
        assert run("false", checked=False).status == 1
        assert run("true").status == 0

        async def through_awaited() -> list[int]:
            with raises(ProgramFailedError) as failed:
                await awaited("false")
            return [
                failed.raised().ran.status,
                (await awaited("false", ok=[1])).status,
                (await awaited("false", checked=False)).status,
                (await awaited("true")).status,
            ]

        assert looped(through_awaited) == [1, 1, 1, 0]

    @lup.promise
    async def a_program_that_isnt_there_is_missing(self, by: Testing) -> None:
        """Every way of running a program raises `ProgramMissingError` where it isn't there."""
        with scratch() as here:
            nowhere = here / "nowhere"
            with raises(ProgramMissingError):
                run(nowhere)
            with raises(ProgramMissingError):
                detached(nowhere, log=here / "log")

            async def on_a_loop() -> None:
                with raises(ProgramMissingError):
                    await awaited(nowhere)
                with raises(ProgramMissingError):
                    await started(nowhere)
                with raises(ProgramMissingError):
                    await spawned(nowhere)

            looped(on_a_loop)

    @lup.promise
    async def arguments_arrive_as_given(self, by: Testing) -> None:
        """A program's arguments reach it as given, never read by a shell, through `run` and `awaited` alike."""

        async def through_awaited() -> Ran:
            return await awaited("printf", "%s", TRICKY)

        assert run("printf", "%s", TRICKY).output == TRICKY.encode()
        assert looped(through_awaited).output == TRICKY.encode()

    @lup.promise
    async def a_program_past_its_time_is_killed(self, by: Testing) -> None:
        """A program running past `within` is killed, raising `ProgramOverdueError` with its command and the time it had; `awaited` kills what it started in its group too, so nothing it left waits on."""
        within = timedelta(milliseconds=10)
        with scratch() as here:
            blocked = fifo(here / "blocked")
            with raises(ProgramOverdueError) as late:
                run("cat", str(blocked), within=within)
            assert late.raised().command == ["cat", str(blocked)]
            assert late.raised().within == within

            async def through_awaited() -> timedelta:
                with raises(ProgramOverdueError) as late:
                    await awaited(
                        "sh", "-c", LEAVING, "sh", str(blocked), within=within
                    )
                return late.raised().within

            assert looped(through_awaited) == within
            assert not waited_on(blocked)

    @lup.promise
    async def a_program_printing_past_its_limit_is_killed(self, by: Testing) -> None:
        """A program printing more than `limit` on its output is killed, raising `ProgramOverflowError`; one printing no more is answered whole."""

        async def limited() -> bytes:
            with raises(ProgramOverflowError):
                await awaited("cat", "/dev/zero", limit=10)
            return (await awaited("printf", "0123456789", limit=10)).output

        assert looped(limited) == b"0123456789"

    @lup.promise
    async def past_kept_its_end_is_kept(self, by: Testing) -> None:
        """Where a program says more than `kept`, what's kept is its end, at least `kept` bytes and at most a read's 64 KiB more, what came before dropped as it runs on."""
        saying = "printf '%1000000s' '' >&2; printf end >&2; printf done"

        async def kept() -> Ran:
            return await awaited("sh", "-c", saying, kept=1000)

        ran = looped(kept)
        assert ran.output == b"done"
        assert ran.error.endswith(b" " * 997 + b"end")
        assert len(ran.error) < 1000 + 64 * 1024 + 1000

    @lup.promise
    async def discarded_output_is_waited_on_by_nothing(self, by: Testing) -> None:
        """Where what a program prints is discarded, `awaited` answers once it ends, though it left a process holding what would have been its output, and keeps nothing."""
        discarding = 'cat "$1" & printf printed; printf said >&2; cat > /dev/null'
        with scratch() as here:
            blocked = fifo(here / "blocked")

            async def discarded() -> Ran:
                return await awaited(
                    "sh",
                    "-c",
                    discarding,
                    "sh",
                    str(blocked),
                    stdin="copied",
                    discarded=True,
                )

            try:
                ran = looped(discarded)
            finally:
                released(blocked)
        assert ran.status == 0
        assert ran.output == ran.error == b""

    @lup.promise
    async def a_cancelled_wait_kills_what_it_waited_on(self, by: Testing) -> None:
        """Where the wait on `awaited` is cancelled, the program is killed with what it started in its group before the cancellation goes on, so nothing it left waits on."""
        with scratch() as here:
            blocked, saying = fifo(here / "blocked"), fifo(here / "started")

            async def cancelled() -> None:
                waiting = asyncio.create_task(
                    awaited(
                        "sh", "-c", LEFT_THEN_SAYING, "sh", str(blocked), str(saying)
                    )
                )
                await asyncio.to_thread(saying.read_bytes)
                waiting.cancel()
                with raises(asyncio.CancelledError):
                    await waiting

            looped(cancelled)
            assert not waited_on(blocked)

    @lup.promise
    async def what_left_its_group_is_let_go_past_letting(self, by: Testing) -> None:
        """Where a program `awaited` kills left a process outside its group holding its output, which the kill doesn't reach, the wait gives up on that past `letting` and goes on."""
        with scratch() as here:
            blocked, saying = fifo(here / "blocked"), fifo(here / "left")

            async def cancelled() -> None:
                waiting = asyncio.create_task(
                    awaited(
                        "sh",
                        "-c",
                        ESCAPING,
                        "sh",
                        str(blocked),
                        str(saying),
                        letting=timedelta(milliseconds=10),
                    )
                )
                await asyncio.to_thread(saying.read_bytes)
                waiting.cancel()
                with raises(asyncio.CancelledError):
                    await waiting

            try:
                looped(cancelled)
            finally:
                released(blocked)

    @lup.promise
    async def started_is_talked_to_until_its_input_closes(self, by: Testing) -> None:
        """A program `started` is talked to over its input and output while it runs, and ends once `ended` closes its input, answering its status."""

        async def talked() -> list[bytes | int | None]:
            running = await started("cat")
            running.input.write(b"hi\n")
            await running.input.drain()
            line = await running.output.readline()
            before = running.status
            status = await running.ended()
            return [line, before, status, running.status]

        assert looped(talked) == [b"hi\n", None, 0, 0]

    @lup.promise
    async def started_is_killed_once_its_time_to_end_is_up(self, by: Testing) -> None:
        """A program `started` that's still there once the time `ended` gives it is up is killed."""
        with scratch() as here:
            blocked = fifo(here / "blocked")

            async def ended() -> int:
                running = await started("cat", str(blocked))
                return await running.ended(within=timedelta(0))

            assert looped(ended) == -signal.SIGKILL
            assert not waited_on(blocked)

    @lup.promise
    async def spawned_answers_how_it_ended(self, by: Testing) -> None:
        """A program `spawned` is given no input, and answers how it ended: by itself, asked to, or made to; asking one that has ended does nothing."""
        with scratch() as here:
            blocked = fifo(here / "blocked")

            async def ended() -> list[int]:
                alone = await spawned("cat")
                asked = await spawned("cat", str(blocked))
                asked.terminate()
                made = await spawned("cat", str(blocked))
                made.kill()
                statuses = [await each.waited() for each in (alone, asked, made)]
                made.terminate()
                made.kill()
                return statuses

            assert looped(ended) == [0, -signal.SIGTERM, -signal.SIGKILL]
            assert not waited_on(blocked)

    @lup.promise
    async def detached_appends_to_its_log_in_a_session_of_its_own(
        self, by: Testing
    ) -> None:
        """A program `detached` runs in a session of its own, which its caller's ending doesn't reach, appending what it prints and says to its log after what was there, until `end` ends it."""
        logging = 'printf printed; printf said >&2; printf "" > "$1"; exec cat "$2"'
        with scratch() as here:
            saying, blocked = fifo(here / "started"), fifo(here / "blocked")
            log = here / "detached.log"
            log.write_bytes(b"before\n")
            apart = detached(
                "sh", "-c", logging, "sh", str(saying), str(blocked), log=log
            )
            saying.read_bytes()
            assert not apart.ended()
            assert os.getsid(apart.process.pid) == apart.process.pid
            apart.end(patience=timedelta(seconds=10))
            assert apart.ended()
            assert log.read_bytes() == b"before\nprintedsaid"
            assert not waited_on(blocked)
