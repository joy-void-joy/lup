"""What an ask raises when it can't return an answer.

A failure is always one of these, never an empty result. Each is classified from
what the runtime reports in structured form, so a caller branches on the type.
Only `AgentUnavailableError` is retried, by the recovery layer.
"""

from contextlib import contextmanager
from typing import TYPE_CHECKING

from lup.errors import LupError

if TYPE_CHECKING:
    from collections.abc import Generator
    from datetime import datetime

    from lup.sessions.results import Rejection, Usage


class TurnError(LupError):
    """An ask that returned no answer."""


class AgentUnavailableError(TurnError):
    """The runtime couldn't reach its model: overload, rate limit, a dropped connection, a server error."""


class UsageLimitReachedError(TurnError):
    """The account's usage window is spent; `reset_at` says when it resets, where reported."""

    def __init__(self, message: str, *, reset_at: datetime | None = None) -> None:
        """Record the message and the reset time the runtime reported."""
        super().__init__(message)
        self.reset_at = reset_at


class AuthMissingError(TurnError):
    """The runtime has no login it can use."""


class OutputMissingError(TurnError):
    """No answer was accepted within the submission layer's attempts.

    `rejected` holds every refused attempt in full: what was submitted, and why it
    was refused. `notes` holds the remarks the agent attached, and `usage` what
    the turn used, where the runtime reported it.
    """

    def __init__(
        self,
        message: str,
        *,
        rejected: list[Rejection],
        notes: list[str],
        usage: Usage | None,
    ) -> None:
        """Record the message, every refused attempt, the notes and the usage."""
        super().__init__(message)
        self.rejected = rejected
        self.notes = notes
        self.usage = usage


class ProblemReportedError(TurnError):
    """The agent stopped without an answer and said what's wrong.

    `problem` is its report, in its own words; `notes` the remarks it attached
    before reporting; `usage` what the turn used, where the runtime reported it.
    It isn't retried: asking again gets the same problem.
    """

    def __init__(self, problem: str, *, notes: list[str], usage: Usage | None) -> None:
        """Record the agent's report, its notes and the turn's usage."""
        super().__init__(
            f"the agent reported a problem instead of answering: {problem}"
        )
        self.problem = problem
        self.notes = notes
        self.usage = usage


class ToolsPresentError(TurnError):
    """The session loaded tools beyond lup's own, so the call stopped before the model ran."""

    def __init__(self, message: str, *, tools: list[str]) -> None:
        """Record the message and the tools the session loaded."""
        super().__init__(message)
        self.tools = tools


class TurnTimeoutError(TurnError, TimeoutError):
    """The ask's timeout passed, and the turn was interrupted.

    It is also the built-in `TimeoutError`, so code catching that catches it.
    """


class RuntimeMissingError(LupError):
    """A declaration names a runtime whose extra isn't installed."""


@contextmanager
def needs_extra(extra: str) -> Generator[None]:
    """Raise `RuntimeMissingError` naming `lup[<extra>]` where the block's import finds no runtime SDK.

    An adapter imports its runtime's SDK inside it, when an ask first needs it, so
    a missing extra is said where it's needed, rather than as an import error deep
    inside. A module of lup's own missing is a bug, and raised as it is.
    """
    try:
        yield
    except ModuleNotFoundError as missing:
        if missing.name is None or missing.name.startswith("lup"):
            raise
        message = (
            f"asking needs the `lup[{extra}]` extra, which isn't installed (no "
            f"module {missing.name!r}): install `lup[{extra}]`"
        )
        raise RuntimeMissingError(message) from missing


class RealCallInTestError(LupError):
    """A test reached a real agent, where it should have scripted the fake (`lup.testing`)."""
