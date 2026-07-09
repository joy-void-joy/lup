"""Engine components composed into the one concrete ``Client``.

There are no per-engine ``Client`` subclasses. An engine contributes the
small verbs it natively has — always its
:class:`~lup.adapters.clients.sessions.Sessions.Sessions`, plus a
:class:`~lup.adapters.clients.streams.Stream.Stream` when its SDK feeds
events live — and construction composes them here. Gaps fill generically:
``query`` runs one turn in a fresh session, and a missing live stream
becomes :class:`~lup.adapters.clients.streams.replay.ReplayStream`.
Extending an engine is contributing a new component that implements a
verb, never subclassing the client.
"""

from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from lup.adapters.clients.Client import Client
from lup.adapters.clients.sessions.Session import Session
from lup.adapters.clients.sessions.Sessions import Sessions
from lup.adapters.clients.streams.replay import ReplayStream
from lup.adapters.clients.streams.Stream import Stream
from lup.telemetry.trace import TraceLogger
from lup.types import LupEvent, LupResponse

if TYPE_CHECKING:
    from lup.realtime.relay import RealtimeMailbox


class ComposedClient(Client):
    """The one concrete ``Client``: an engine's components behind the seam.

    Args:
        sessions: The engine's session opener — the component every
            engine contributes.
        streams: The engine's live event stream, when its SDK has one;
            left ``None``, the slot is filled with :class:`ReplayStream`
            over the same sessions.
        mailbox: The realtime file-relay endpoint, when the engine's
            translation requested persistent mode — a composed slot, not
            a caller knob.
    """

    def __init__(
        self,
        sessions: Sessions,
        *,
        streams: Stream | None = None,
        mailbox: "RealtimeMailbox | None" = None,
    ) -> None:
        self.sessions = sessions
        self.streams = streams if streams is not None else ReplayStream(sessions)
        self.mailbox = mailbox

    def session(
        self, *, resume: str | None = None
    ) -> AbstractAsyncContextManager[Session]:
        return self.sessions.open(resume=resume)

    async def query(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        async with self.sessions.open() as session:
            return await session.send(prompt, trace_logger=trace_logger, prefix=prefix)

    def stream(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        return self.streams.run(prompt, trace_logger=trace_logger, prefix=prefix)
