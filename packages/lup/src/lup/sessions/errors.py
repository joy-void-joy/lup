"""What an ask raises when it can't return an answer.

A failure is always one of these, never an empty result. Each is classified from
what the runtime reports in structured form, so a caller branches on the type.
Only `AgentUnavailableError` is retried, by the recovery layer.
"""

from typing import TYPE_CHECKING

from lup.errors import LupError

if TYPE_CHECKING:
    from datetime import datetime

    from lup.sessions.results import Rejection


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
    was refused.
    """

    def __init__(self, message: str, *, rejected: list[Rejection]) -> None:
        """Record the message and every refused attempt."""
        super().__init__(message)
        self.rejected = rejected


class ProblemReportedError(TurnError):
    """The agent stopped without an answer and said what's wrong.

    `problem` is its report, in its own words; `notes` the remarks it attached
    before reporting. It isn't retried: asking again gets the same problem.
    """

    def __init__(self, problem: str, *, notes: list[str]) -> None:
        """Record the agent's report and its notes."""
        super().__init__(f"the agent reported a problem instead of answering: {problem}")
        self.problem = problem
        self.notes = notes


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
