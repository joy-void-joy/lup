"""The clock the judge reads and waits on, so tests can drive it.

Holds wait for the operator and the turn end waits for the importers pass; both
read the time and sleep through this interface, never through `time` directly.
"""

import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import override


class Clock(ABC):
    """Tell the time and wait."""

    @abstractmethod
    def now(self) -> datetime:
        """Return the current time, timezone-aware."""

    @abstractmethod
    def sleep(self, seconds: float) -> None:
        """Wait `seconds` before returning."""


class SystemClock(Clock):
    """The machine's own clock."""

    @override
    def now(self) -> datetime:
        return datetime.now(UTC)

    @override
    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
