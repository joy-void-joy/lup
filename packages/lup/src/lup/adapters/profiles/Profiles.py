"""The profile seam: one verb, ``select``.

A profile names an account — a complete backend login with its own
credentials, settings, and history, reused across projects.
:class:`ProfileSupport` is the whole contract: ``select(name, client)``
takes an already-built client and returns one running as that account.
Everything else — how a name resolves, what an account physically is,
where an implementation keeps its bookkeeping — is that implementation's
own concern, kept beside this module (e.g.
:mod:`lup.adapters.profiles.claude`). An engine with no implementation
raises :class:`~lup.adapters.errors.UnsupportedOperationError` from
``Engine.profiles()``.
"""

from abc import ABC, abstractmethod

from lup.adapters.clients.Client import Client


class ProfileSupport(ABC):
    """A backend's account-profile capability: put a client on an account."""

    @abstractmethod
    def select(self, name: str | None, client: Client) -> Client:
        """Return *client* running as the named account.

        ``name=None`` selects the implementation's own active or default
        account. The given client is left untouched; the returned one is
        a rebound handle.
        """
