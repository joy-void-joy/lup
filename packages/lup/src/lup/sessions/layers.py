"""The layers every ask runs in, declared once on the agent: timeout, recovery, submission, trace."""

from datetime import timedelta
from pathlib import Path

from tenacity import stop_after_attempt, wait_exponential
from tenacity.stop import stop_base
from tenacity.wait import wait_base

from lup.types import Model


class Recovery(Model, arbitrary_types_allowed=True):
    """How an ask retries when the runtime can't reach its model.

    It takes tenacity's own strategies, which combine:
    `Recovery(stop=stop_after_attempt(5) | stop_after_delay(120))`. Only
    `AgentUnavailableError` is retried; the runtimes retry API errors themselves
    first, so this catches what they gave up on.
    """

    stop: stop_base = stop_after_attempt(3)
    wait: wait_base = wait_exponential(multiplier=1, max=30)


class Submission(Model):
    """How many refusals a typed ask allows before it gives up.

    Rejected answers and refused endings count together, when the agent tries to
    end its turn: past `attempts`, the guard lets the turn end, and the ask raises
    `OutputMissingError` with every rejected attempt. An agent that keeps
    submitting without trying to end is bounded by the timeout layer.
    """

    attempts: int = 3


class SessionLayers(Model):
    """The layers around every ask an agent makes."""

    timeout: timedelta | None = None
    """Bounds the whole ask, recovery and submission included; none waits as long as it takes."""
    recovery: Recovery = Recovery()
    submission: Submission = Submission()
    trace: Path | None = None
    """A JSON Lines file each ask's `CallRecord` is appended to; none keeps no trace."""
