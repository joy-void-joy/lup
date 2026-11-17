"""Running a program beside its caller: `started`, talked to over its input and output; `spawned`, its output the caller's own; and `detached`, outliving its caller."""

import asyncio

# lup: ignore("subprocess", why="lup's one runner of programs, which every other module uses")
import subprocess
from typing import TYPE_CHECKING

from lup.programs.ended import ProgramError, ProgramMissingError
from lup.types import Model

if TYPE_CHECKING:
    from datetime import timedelta
    from pathlib import Path


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

    For a program the caller talks to for as long as it runs, such as a
    service's worker. What it writes to its standard error reaches the
    caller's own. Raise `ProgramMissingError` where it can't be started.
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

    For a program the caller talks to some other way, such as over a socket
    of its own. Raise `ProgramMissingError` where it can't be started.
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
    """A program started in a session of its own, for a caller that watches it: what `detached` returns."""

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
    """Start `program` in a session of its own, which outlives its caller, appending what it prints and says to `log`; return it, for a caller that watches it to end or sees it end.

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
