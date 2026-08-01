"""The concrete session surface every consumer holds.

Consumers never hold a capability ABC. ``SessionFactory`` is a plain class
parametrized by one swappable ``SessionOpener`` engine: adapters, wrappers,
and tests supply the opener, and the behavior every caller shares — opening a
session, running one turn on it — lives here once.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from pydantic import BaseModel

from lup.runtime.models import SessionHandle, SessionId, TurnRequest, TurnResult

type SessionOpener = Callable[
    [SessionId | None], AbstractAsyncContextManager[SessionHandle]
]


class SessionFactory:
    """Open configured conversations and run turns on them."""

    def __init__(self, opener: SessionOpener) -> None:
        self.opener = opener

    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]:
        """Open a new or resumed session."""
        return self.opener(resume)

    async def query[T: BaseModel | None](
        self, request: TurnRequest[T]
    ) -> TurnResult[T]:
        """Open one session, run one turn, and always close the session."""
        async with self.open() as handle:
            turn = await handle.session.start(request)
            return await turn.turn.result()
