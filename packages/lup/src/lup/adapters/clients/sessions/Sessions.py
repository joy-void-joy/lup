"""The session verb: the one native building block every engine has.

:class:`Sessions` opens an engine's multi-turn sessions. It is the
component an engine must contribute to
:class:`~lup.adapters.clients.composed.ComposedClient` — the one-shot
and stream surfaces can both be filled generically from it.
"""

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager

from lup.adapters.clients.sessions.Session import Session


class Sessions(ABC):
    """Opens one engine's multi-turn sessions.

    An implementation holds the engine's translated native configuration
    and speaks its SDK; nothing connects until :meth:`open` is entered.
    """

    @abstractmethod
    def open(
        self, *, resume: str | None = None
    ) -> AbstractAsyncContextManager[Session]:
        """Open a session; ``resume`` continues a saved one.

        Implementations are ``@asynccontextmanager`` async generators
        yielding a :class:`~lup.adapters.clients.sessions.Session.Session`.
        The SDK client/thread is created on entry and cleaned up on exit.
        ``resume`` takes a previously saved
        :attr:`~lup.adapters.clients.sessions.Session.Session.id`; engines
        that cannot restore sessions raise
        :class:`~lup.adapters.errors.UnsupportedOperationError`.
        """
