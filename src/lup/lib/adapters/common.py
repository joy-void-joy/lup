"""Agent adapter ABC.

Each SDK adapter implements this interface. Consumer code (core.py)
instantiates the appropriate adapter and calls ``run()``.
"""

from abc import ABC, abstractmethod

from lup.lib.trace import TraceLogger
from lup.lib.types import LupResponse


class AgentAdapter(ABC):
    """Run a prompt against an SDK backend and return collected results."""

    @abstractmethod
    async def run(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse: ...
