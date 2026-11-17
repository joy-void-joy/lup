"""How a program ended (`Ran`), and the errors raised where it couldn't be run or ended as its caller doesn't accept."""

import shlex
from typing import TYPE_CHECKING

from lup.errors import LupError
from lup.types import Model

if TYPE_CHECKING:
    from datetime import timedelta


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
        r"""Return what it printed, as text, its trailing newline left out.

        >>> Ran(command=["git", "branch", "--show-current"], status=0, output=b"dev\n").text()
        'dev'
        """
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
        message = f"`{shlex.join(ran.command)}` ended with status {ran.status}{told}"
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
