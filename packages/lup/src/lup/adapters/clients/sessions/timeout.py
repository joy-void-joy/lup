"""The turn-timeout verb: wall-clock governance composed over any sessions.

Engines whose runtime cannot bound a single turn (the Codex app-server)
compose this wrapper instead of implementing timeouts inline — their
``create`` recipe decides, per the translated ``turn_timeout_seconds``
knob.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from lup.adapters.clients.sessions.Session import Session
from lup.adapters.clients.sessions.Sessions import Sessions
from lup.adapters.errors import TurnTimeoutError
from lup.telemetry.trace import TraceLogger
from lup.types import LupResponse


class TimeoutSession(Session):
    """Caps each ``send`` at a wall-clock budget, cancelling client-side."""

    def __init__(self, inner: Session, *, seconds: float) -> None:
        self.inner = inner
        self.seconds = seconds
        self.id = inner.id

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        try:
            async with asyncio.timeout(self.seconds):
                response = await self.inner.send(
                    prompt, trace_logger=trace_logger, prefix=prefix
                )
        except TimeoutError as exc:
            raise TurnTimeoutError(
                f"turn exceeded the {self.seconds}s wall-clock timeout and "
                "was cancelled client-side; close the conversation rather "
                "than reusing this session."
            ) from exc
        self.id = self.inner.id
        return response

    async def interrupt(self) -> None:
        await self.inner.interrupt()


class TimeoutSessions(Sessions):
    """Opens the inner engine's sessions with every turn wall-clocked."""

    def __init__(self, inner: Sessions, *, seconds: float) -> None:
        self.inner = inner
        self.seconds = seconds

    @asynccontextmanager
    async def open(self, *, resume: str | None = None) -> AsyncGenerator[Session, None]:
        async with self.inner.open(resume=resume) as session:
            yield TimeoutSession(session, seconds=self.seconds)
