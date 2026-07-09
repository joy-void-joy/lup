"""The run-path display tap: what a turn shows and traces as it lands.

Both run paths compose one of these instead of calling the console
directly — the collector and live stream on Claude, the turn projection
on Codex — so display/trace is a slot, not welded-in behavior: silent
runs pass ``None``, tests pass a recorder, alternative frontends pass
their own sink.
"""

from collections.abc import Callable

from lup.telemetry.display import print_message
from lup.telemetry.trace import TraceLogger
from lup.types import LupMessage

type MessageTap = Callable[[LupMessage], None]
"""A sink invoked once per lup message as a turn produces it."""


def console_tap(
    *, prefix: str = "", trace_logger: TraceLogger | None = None
) -> MessageTap:
    """The default tap: color-coded console print, tracing when a logger is given."""

    def tap(message: LupMessage) -> None:
        print_message(message, prefix=prefix, trace=trace_logger)

    return tap
