"""Running a program to its end: `run`, its caller waiting, and `awaited`, on an event loop that goes on meanwhile.

Their reasons (arguments never a shell's line, a program started from C, a time
limit, and the process group `awaited` kills) are in `README.md` here.
"""

import asyncio
import os
import signal

# lup: ignore("subprocess", why="lup's one runner of programs, which every other module uses")
import subprocess
from collections import deque
from datetime import timedelta
from typing import TYPE_CHECKING

from lup.programs.ended import (
    ProgramFailedError,
    ProgramMissingError,
    ProgramOverdueError,
    ProgramOverflowError,
    Ran,
)

if TYPE_CHECKING:
    from pathlib import Path


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
    - `within`: the longest it may run; past it, it's killed, alone, and this
      returns at once: `subprocess` waits for the program, not for its pipes.
      As long as it takes by default.

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
    letting: timedelta = timedelta(seconds=10),
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
      output would be held whole otherwise. `limit` takes its standard output
      where both are given.
    - `letting`: once it's killed, how long its pipes may take to close, read
      to their end, before they're left to whatever holds them: a process
      that left its group, which the kill doesn't reach.

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

        A killed program's pipes are read to their end: asyncio stops reading
        a pipe whose buffer nobody reads, so one left unread past the kill
        would never reach its end, and stay open, paused, rather than close.
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
        """Kill it and its group, and wait for them, their pipes read to their end, `letting` at most: past it, a process outside the group holding one, it's left to that."""
        kill()
        draining = asyncio.ensure_future(
            asyncio.gather(emptied(process.stdout), emptied(process.stderr))
        )
        await asyncio.wait([draining], timeout=letting.total_seconds())
        # Still open past it: held by a process the kill didn't reach.
        draining.cancel()
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
