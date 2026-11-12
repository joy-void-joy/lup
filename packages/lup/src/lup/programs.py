"""Running a program: `run` waits for it and returns how it ended, `awaited` does so on an event loop, `started` keeps one running beside it to talk to over its input and output, `spawned` one with its output the caller's, and `detached` starts one that outlives its caller.

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
where the wait is cancelled, so nothing runs on past the caller's interest in
it. `started` starts one the caller talks to over its input and output for as
long as it runs, as the service does with each repository's process and the
dashboard, and `Running.ended` ends it by closing its input.

`run` and `awaited` each take `within`, the longest the program may run: past
it, it's killed and `ProgramOverdueError` raised. A program reading what
someone else writes can wait for good: git reading a ref a room made a FIFO
nothing writes waits in `open` until it's killed (`docs/field-notes.md`,
*Host-side git in a repository the room writes*). `awaited` starts each
program as the leader of a process group of its own, and kills the group:
asyncio's wait for a program returns only once every pipe it was given has
closed, so a child it left holding one, as git leaves `ssh` for a push, would
hold the wait past the program's own end. `run` kills the program alone, and
returns at once: `subprocess` waits for it, not for its pipes.
"""

import asyncio
import os
import shlex
import signal

# lup: ignore("subprocess", why="lup's one runner of programs, which every other module uses")
import subprocess
from collections import deque
from datetime import timedelta
from typing import TYPE_CHECKING

from lup.errors import LupError
from lup.types import Model

if TYPE_CHECKING:
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


class ProgramOverdueError(ProgramError):
    """A program ran past the time its caller gave it, and was killed for it."""

    def __init__(self, command: list[str], within: timedelta) -> None:
        """Keep the command and the time it had, and say both."""
        self.command = command
        self.within = within
        message = (
            f"`{shlex.join(command)}` ran past {within.total_seconds():g} s, and "
            "was killed"
        )
        super().__init__(message)


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
    within: timedelta | None = None,
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
    - `within`: the longest it may run; past it, it's killed. As long as it
      takes by default.

    Raise `ProgramMissingError` where it can't be started, `ProgramOverdueError`
    where it runs past `within`, and `ProgramFailedError` where it ends with a
    status not accepted.
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
            timeout=None if within is None else within.total_seconds(),
        )
    except OSError as missing:
        message = f"`{program}` can't be run: {missing}"
        raise ProgramMissingError(message) from missing
    except subprocess.TimeoutExpired as late:
        raise ProgramOverdueError(command, timedelta(seconds=late.timeout)) from late
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
    kept: int | None = None,
    within: timedelta | None = None,
) -> Ran:
    """Run `program` with `arguments` to its end on the event loop, which goes on meanwhile, and return how it ended.

    `cwd`, `stdin`, `env`, `ok`, `checked`, `merged` and `within` are `run`'s,
    its input never the caller's own. Beside them:
    - `discarded`: what it prints goes nowhere, and nothing is captured, as for
      a program leaving a process behind that would hold a pipe open, such as
      a clipboard's program serving what was copied.
    - `limit`: the most it may print on its standard output, in bytes; past
      it, it's killed.
    - `kept`: the most of each of its outputs kept, in bytes, give or take a
      read's 64 KiB: their end, what came before read and dropped as it runs,
      and said in a line first; it runs on. For a program another chose, whose
      output would be held whole otherwise, as a room's command is. `limit`
      takes its standard output where both are given.

    It runs as the leader of a process group of its own, and where it's killed,
    past `within` or `limit` or as the wait is cancelled, the whole group is,
    before anything goes on. Raise `ProgramMissingError` where it can't be
    started, `ProgramOverdueError` where it runs past `within`,
    `ProgramOverflowError` where it prints past `limit`, and `ProgramFailedError`
    where it ends with a status not accepted.
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
            process_group=0,
        )
    except OSError as missing:
        message = f"`{program}` can't be run: {missing}"
        raise ProgramMissingError(message) from missing

    def kill() -> None:
        """Kill it, and what it started that's still in its process group: one whose group has gone is left as it is."""
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return

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
                kill()
                await emptied(reader)
                return None
        return bytes(kept)

    async def tailed(reader: asyncio.StreamReader | None) -> bytes:
        """Read `reader` to its end, keeping its last `kept` bytes, give or take a read, and saying first how many before them were dropped."""
        if reader is None:
            return b""
        chunks: deque[bytes] = deque()
        held = 0
        dropped = 0
        while chunk := await reader.read(64 * 1024):
            chunks.append(chunk)
            held += len(chunk)
            while kept is not None and held - len(chunks[0]) >= kept:
                gone = chunks.popleft()
                held -= len(gone)
                dropped += len(gone)
        said = b"".join(chunks)
        if not dropped:
            return said
        return f"[{dropped:,} bytes before this left out]\n".encode() + said

    async def ended() -> None:
        """Kill it and its group, and wait for them, their pipes read to their end."""
        kill()
        await asyncio.gather(emptied(process.stdout), emptied(process.stderr))
        await process.wait()

    try:
        async with asyncio.timeout(None if within is None else within.total_seconds()):
            printed = (
                drained(process.stdout, limit)
                if kept is None or limit is not None
                else tailed(process.stdout)
            )
            output, error, _ = await asyncio.gather(
                printed, tailed(process.stderr), fed()
            )
            status = await process.wait()
    except TimeoutError as late:
        await ended()
        if within is None:
            raise
        raise ProgramOverdueError(command, within) from late
    finally:
        if process.returncode is None:
            await ended()
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


class Child(Model, arbitrary_types_allowed=True):
    """A program running beside the event loop, its input nothing and its output the caller's own: what `spawned` returns."""

    process: asyncio.subprocess.Process

    async def waited(self) -> int:
        """Wait for it to end, however it does, and return its status."""
        return await self.process.wait()

    def terminate(self) -> None:
        """Ask it to end (`SIGTERM`); nothing where it has ended."""
        if self.process.returncode is None:
            self.process.terminate()

    def kill(self) -> None:
        """Make it end (`SIGKILL`); nothing where it has ended."""
        if self.process.returncode is None:
            self.process.kill()


async def spawned(program: str | Path, *arguments: str) -> Child:
    """Start `program` with `arguments` beside the event loop, its input nothing, what it prints and says reaching the caller's own, and return it running.

    For a program the caller talks to some other way, as a held session's room
    over a socket of its own (`lup.rooms.room.Room.hold`). Raise
    `ProgramMissingError` where it can't be started.
    """
    command = [str(program), *arguments]
    try:
        # lup: ignore("subprocess", why="lup's one runner of programs, which every other module uses")
        process = await asyncio.create_subprocess_exec(
            *command, stdin=asyncio.subprocess.DEVNULL
        )
    except OSError as missing:
        message = f"`{program}` can't be started: {missing}"
        raise ProgramMissingError(message) from missing
    return Child(process=process)


class Apart(Model, arbitrary_types_allowed=True):
    """A program started in a session of its own, for a caller that watches it."""

    process: subprocess.Popen[bytes]

    def ended(self) -> bool:
        """Say whether it has ended."""
        return self.process.poll() is not None

    def end(self, patience: timedelta) -> None:
        """End it, asked first, then made to past `patience`; nothing where it has ended."""
        if self.ended():
            return
        self.process.terminate()
        try:
            self.process.wait(patience.total_seconds())
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


def detached(
    program: str | Path, *arguments: str, log: Path, cwd: Path | None = None
) -> Apart:
    """Start `program` in a session of its own, which outlives its caller, appending what it prints to `log`; return it, for a caller that watches it to end or see end.

    Raise `ProgramMissingError` where it can't be started.
    """
    command = [str(program), *arguments]
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as appended:
        try:
            process = subprocess.Popen(
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
    return Apart(process=process)
