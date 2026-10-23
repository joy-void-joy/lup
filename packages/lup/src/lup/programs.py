"""Running a program: `run` waits for it and returns how it ended, `awaited` does so on an event loop, `started` keeps one running beside it, and `detached` starts one that outlives its caller.

    ran = run("git", "status", "--porcelain", cwd=root)
    ran.text()                                    # what it printed
    run("gh", "auth", "status", checked=False).status
    run("uv", "tool", "install", package, shown=True)
    detached("lup-dev", "host", log=log)
    ran = await awaited("gh", "api", "--input=-", stdin=body)
    worker = await started("lup-dev", "worker", socket)
    worker.input.write(line)
    await worker.output.readline()
    await worker.ended()

The program's arguments are a list, never a line a shell reads. A program
ending with a status its caller doesn't accept raises `ProgramFailedError`, carrying
how it ended; one that can't be started raises `ProgramMissingError`.

A program is started from C, as `subprocess` does, never by forking Python: a
process whose other threads hold locks can fork into a child that never gets
them back, which Python warns of, and which `filelock` refuses outright.

On an event loop that goes on serving while a program runs, as the host
service's does, `awaited` waits for one without holding a thread, and kills it
where the wait is cancelled, as by a timeout around it, so nothing runs on past
the caller's interest in it. `started` starts one the caller talks to over its
input and output for as long as it runs, as the service does with each
launch's process and the dashboard, and `Running.ended` ends it by closing its
input.
"""

import asyncio

# lup: ignore("subprocess", why="lup's one runner of programs, which every other module uses")
import subprocess
from typing import TYPE_CHECKING

from lup.errors import LupError
from lup.types import Model

if TYPE_CHECKING:
    from datetime import timedelta
    from pathlib import Path


class Ran(Model):
    """How a program ended: its command, its status, what it printed and what it said beside."""

    command: list[str]
    status: int
    output: bytes = b""
    """What it printed: its standard output, its standard error too where merged;
    nothing where it was shown on the terminal, or discarded."""
    error: bytes = b""
    """What it wrote to its standard error, where kept apart."""

    def text(self) -> str:
        """Return what it printed, as text, its trailing newline left out."""
        return self.output.decode(errors="replace").removesuffix("\n")

    def said(self) -> str:
        """Return what it wrote to its standard error, as text, its trailing whitespace left out."""
        return self.error.decode(errors="replace").rstrip()


class ProgramError(LupError):
    """A program couldn't be run, or ended as its caller doesn't accept."""


class ProgramMissingError(ProgramError):
    """A program couldn't be started: it isn't there, or can't be run."""


class ProgramFailedError(ProgramError):
    """A program ended with a status its caller doesn't accept."""

    def __init__(self, ran: Ran) -> None:
        """Keep how it ended, and say it: its command, its status, and what it said."""
        self.ran = ran
        said = ran.said() or ran.text()
        told = f": {said}" if said else ""
        message = f"`{' '.join(ran.command)}` ended with status {ran.status}{told}"
        super().__init__(message)


class ProgramOverflowError(ProgramError):
    """A program printed more than its caller takes, and was killed for it."""


def run(
    program: str | Path,
    *arguments: str,
    cwd: Path | None = None,
    stdin: bytes | str | None = None,
    env: dict[str, str] | None = None,
    ok: list[int] | None = None,
    checked: bool = True,
    merged: bool = False,
    shown: bool = False,
) -> Ran:
    """Run `program` with `arguments` to its end, and return how it ended.

    - `cwd`: where it runs; the caller's directory by default.
    - `stdin`: what goes on its standard input; nothing by default, never the
      caller's own but where it's `shown`.
    - `env`: its whole environment, where given; the caller's by default.
    - `ok`: the statuses it may end with; only 0 by default. `checked=False`
      takes any.
    - `merged`: its standard error joins its output, in the order written.
    - `shown`: it prints to the caller's terminal, and nothing is captured.

    Raise `ProgramMissingError` where it can't be started, and `ProgramFailedError` where
    it ends with a status not accepted.
    """
    command = [str(program), *arguments]
    captured = None if shown else subprocess.PIPE
    apart = subprocess.STDOUT if merged else captured
    given = stdin.encode() if isinstance(stdin, str) else stdin
    closed = None if shown or given is not None else subprocess.DEVNULL
    try:
        finished = subprocess.run(
            command,
            cwd=cwd,
            input=given,
            stdin=closed,
            env=env,
            stdout=captured,
            stderr=apart,
            check=False,
        )
    except OSError as missing:
        message = f"`{program}` can't be run: {missing}"
        raise ProgramMissingError(message) from missing
    ran = Ran(
        command=command,
        status=finished.returncode,
        output=finished.stdout or b"",
        error=finished.stderr or b"",
    )
    if checked and ran.status not in (ok or [0]):
        raise ProgramFailedError(ran)
    return ran


async def awaited(
    program: str | Path,
    *arguments: str,
    cwd: Path | None = None,
    stdin: bytes | str | None = None,
    env: dict[str, str] | None = None,
    ok: list[int] | None = None,
    checked: bool = True,
    merged: bool = False,
    discarded: bool = False,
    limit: int | None = None,
) -> Ran:
    """Run `program` with `arguments` to its end on the event loop, which goes on meanwhile, and return how it ended.

    `cwd`, `stdin`, `env`, `ok`, `checked` and `merged` are `run`'s, its input
    never the caller's own. Beside them:
    - `discarded`: what it prints goes nowhere, and nothing is captured, as for
      a program leaving a process behind that would hold a pipe open, such as
      a clipboard's program serving what was copied.
    - `limit`: the most it may print on its standard output, in bytes; past
      it, it's killed.

    Where the wait is cancelled, as by a timeout around it, the program is
    killed before the cancellation goes on. Raise `ProgramMissingError` where it
    can't be started, `ProgramOverflowError` where it prints past `limit`, and
    `ProgramFailedError` where it ends with a status not accepted.
    """
    command = [str(program), *arguments]
    given = stdin.encode() if isinstance(stdin, str) else stdin
    printing = asyncio.subprocess.DEVNULL if discarded else asyncio.subprocess.PIPE
    saying = asyncio.subprocess.STDOUT if merged and not discarded else printing
    feeding = asyncio.subprocess.DEVNULL if given is None else asyncio.subprocess.PIPE
    try:
        # lup: ignore("subprocess", why="lup's one runner of programs, which every other module uses")
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            env=env,
            stdin=feeding,
            stdout=printing,
            stderr=saying,
        )
    except OSError as missing:
        message = f"`{program}` can't be run: {missing}"
        raise ProgramMissingError(message) from missing

    async def fed() -> None:
        """Write what it's given on its input, then close it.

        A program may end without reading all of it, which its status says
        how it took, as `run` and asyncio's own `communicate` take it, so a
        pipe it closed first isn't a failure of its own.
        """
        if process.stdin is None or given is None:
            return
        process.stdin.write(given)
        try:
            await process.stdin.drain()
        except BrokenPipeError, ConnectionResetError:
            return
        finally:
            process.stdin.close()

    async def emptied(reader: asyncio.StreamReader | None) -> None:
        """Read `reader` to its end, keeping nothing.

        A killed program's pipes are read to their end before it's waited on:
        asyncio stops reading a pipe whose buffer nobody reads, and waiting on
        a program returns only once each of its pipes has closed, so a program
        killed while it printed would be waited on forever.
        """
        if reader is None:
            return
        while await reader.read(64 * 1024):
            pass

    async def drained(
        reader: asyncio.StreamReader | None, most: int | None
    ) -> bytes | None:
        """Read `reader` to its end; none where it gives more than `most` bytes, the program killed at once and the rest read to its end, kept nowhere."""
        if reader is None:
            return b""
        kept = bytearray()
        while chunk := await reader.read(64 * 1024):
            kept += chunk
            if most is not None and len(kept) > most:
                process.kill()
                await emptied(reader)
                return None
        return bytes(kept)

    try:
        output, error, _ = await asyncio.gather(
            drained(process.stdout, limit), drained(process.stderr, None), fed()
        )
        status = await process.wait()
    finally:
        if process.returncode is None:
            process.kill()
            await asyncio.gather(emptied(process.stdout), emptied(process.stderr))
            await process.wait()
    if output is None:
        message = f"`{program}` printed more than {limit} bytes"
        raise ProgramOverflowError(message)
    ran = Ran(command=command, status=status, output=output, error=error or b"")
    if checked and ran.status not in (ok or [0]):
        raise ProgramFailedError(ran)
    return ran


class Running(Model, arbitrary_types_allowed=True):
    """A program running beside the event loop, which its caller talks to over its input and output: what `started` returns."""

    command: list[str]
    process: asyncio.subprocess.Process
    input: asyncio.StreamWriter
    """Its standard input, open until `ended` closes it."""
    output: asyncio.StreamReader
    """Its standard output."""

    @property
    def status(self) -> int | None:
        """Its status, once it has ended; none while it runs."""
        return self.process.returncode

    async def ended(self, within: timedelta | None = None) -> int:
        """End it: close its input, which it ends at, wait for it, and return its status.

        Where `within` is given and it's still there after it, it's killed.
        """
        self.input.close()
        if within is None:
            return await self.process.wait()
        try:
            return await asyncio.wait_for(
                self.process.wait(), timeout=within.total_seconds()
            )
        except TimeoutError:
            self.process.kill()
            return await self.process.wait()


async def started(program: str | Path, *arguments: str) -> Running:
    """Start `program` with `arguments` beside the event loop, its input and output the caller's to talk over, and return it running.

    What it writes to its standard error reaches the caller's own. Raise
    `ProgramMissingError` where it can't be started.
    """
    command = [str(program), *arguments]
    try:
        # lup: ignore("subprocess", why="lup's one runner of programs, which every other module uses")
        process = await asyncio.create_subprocess_exec(
            *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE
        )
    except OSError as missing:
        message = f"`{program}` can't be started: {missing}"
        raise ProgramMissingError(message) from missing
    if process.stdin is None or process.stdout is None:
        message = f"`{program}` started without its pipes"
        raise ProgramError(message)
    return Running(
        command=command, process=process, input=process.stdin, output=process.stdout
    )


def detached(
    program: str | Path, *arguments: str, log: Path, cwd: Path | None = None
) -> None:
    """Start `program` in a session of its own, which outlives its caller, appending what it prints to `log`.

    Raise `ProgramMissingError` where it can't be started.
    """
    command = [str(program), *arguments]
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as appended:
        try:
            subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=appended,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as missing:
            message = f"`{program}` can't be started: {missing}"
            raise ProgramMissingError(message) from missing
