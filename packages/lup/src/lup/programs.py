"""Running a program: `run` waits for it and returns how it ended, `detached` starts one that outlives its caller.

    ran = run("git", "status", "--porcelain", cwd=root)
    ran.text()                                    # what it printed
    run("gh", "auth", "status", checked=False).status
    run("uv", "tool", "install", package, shown=True)
    detached("lup-dev", "host", log=log)

The program's arguments are a list, never a line a shell reads. A program
ending with a status its caller doesn't accept raises `ProgramFailedError`, carrying
how it ended; one that can't be started raises `ProgramMissingError`.

A program is started from C, as `subprocess` does, never by forking Python: a
process whose other threads hold locks can fork into a child that never gets
them back, which Python warns of, and which `filelock` refuses outright.
"""

# lup: ignore("subprocess", why="lup's one runner of programs, which every other module uses")
import subprocess
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
    nothing where it was shown on the terminal."""
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
