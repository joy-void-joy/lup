"""The engine contract: one backend, complete, behind one object.

An engine is everything one backend contributes: the conversation client
(:meth:`Engine.client`), the background agent (:meth:`Engine.background`),
the account-profile support (:meth:`Engine.profiles`), and the builtin
tool-name table (:meth:`Engine.builtin_tools`). The shipped engines live
in :mod:`lup.adapters.engines`; the id/model routers and the
``create_client()`` / ``query()`` doors in :mod:`lup.adapters.wiring`; a
custom backend is an ``Engine`` subclass instance passed as ``engine=``.

Every member is ``@abstractmethod`` — no concrete defaults and no raising
stubs, matching :mod:`lup.adapters.clients.Client`. A capability a
backend lacks is an explicit ``raise UnsupportedOperationError(...)``
written in that engine's own class, so reading one engine shows exactly
what it cannot do — and the devtools capability table is probed from
that behavior rather than declared.
"""

from abc import ABC, abstractmethod
from typing import ClassVar

from lup.adapters.background.Background import (
    BackgroundAgentParams,
    BaseBackgroundAgent,
)
from lup.adapters.clients.Client import Client
from lup.adapters.options import LupAgentOptions
from lup.adapters.profiles.Profiles import ProfileSupport


class Engine(ABC):
    """One backend, complete — cheap to hold, imports nothing heavy.

    Engine objects are import-light: every method pulls its
    implementation module (and that module's SDK) only when called, so
    ``import lup`` works with no SDK installed and each engine loads only
    its own.
    """

    id: ClassVar[str]
    """The engine's registry id (``"claude"``, ``"codex"``, ...)."""

    @abstractmethod
    def client(self, options: LupAgentOptions) -> Client:
        """Build this engine's configured client from neutral options.

        The translation refuses intent knobs it never reads
        (:mod:`lup.adapters.clients.refusal`) and ignores mechanism
        payloads that belong to other engines.
        """

    @abstractmethod
    def background(self, params: BackgroundAgentParams) -> BaseBackgroundAgent:
        """Build this engine's background agent.

        Each engine owns the validation and defaults that are properties
        of its backend (Codex rejects tools and requires an explicit
        model; Claude defaults to an opus-class model and can act
        through tools).
        """

    @abstractmethod
    def profiles(self) -> ProfileSupport:
        """This engine's account-profile support.

        An engine whose runner reads no account home from a config dir
        raises :class:`~lup.adapters.errors.UnsupportedOperationError`.
        """

    @abstractmethod
    def builtin_tools(self) -> frozenset[str]:
        """The engine's builtin tool-name table.

        Names what the backend's native activity surfaces as in lup
        traffic; whether that set is restrictable is the separate
        ``tools`` intent knob, judged by the client translation.
        """
