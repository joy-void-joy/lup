"""Everything a declared agent wraps its sessions in, as one field.

A timeout, a budget, retries, correction cycles, persistence, tracing, usage
and display are whole-turn decorators the engine already composes
(:mod:`lup.sessions.middleware`); here they are declared, on the agent, rather
than stacked around a client by hand. What wraps a session rather than its
turns — a journal, an allowance wait, a spending ceiling, a cleanup — is a
:class:`~lup.sessions.capabilities.SessionWrapper`, listed in ``wrappers``.

The order is the library's, stated once: the turn decorators sit closest to
the provider, in the order :class:`~lup.sessions.middleware.DecoratingSession`
documents, and the wrappers go around them, the first innermost and the last
outermost — so a recording listed last closes after everything else has run.
"""

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Self

from pydantic import BaseModel

from lup.sessions.capabilities import SessionEngine, SessionWrapper
from lup.sessions.events import SessionId
from lup.sessions.middleware import (
    BudgetConfig,
    CorrectionConfig,
    DecoratingSession,
    DisplayConfig,
    PersistenceConfig,
    RecoveryConfig,
    SerializedSession,
    TimeoutConfig,
    TracingConfig,
    UsageConfig,
)


class SessionLayers(
    BaseModel, frozen=True, arbitrary_types_allowed=True, extra="forbid"
):
    """The layers every session an agent opens is wrapped in."""

    timeout: TimeoutConfig | None = None
    budget: BudgetConfig | None = None
    recovery: RecoveryConfig | None = None
    correction: CorrectionConfig | None = None
    continuation: CorrectionConfig | None = None
    persistence: PersistenceConfig | None = None
    tracing: TracingConfig | None = None
    usage: UsageConfig | None = None
    display: DisplayConfig | None = None
    serialized: bool = False
    """Queue a turn behind the one still running, rather than refusing it."""

    wrappers: list[SessionWrapper] = []
    """What wraps each session around its turn decorators, innermost first."""

    def over(self, beneath: Self) -> Self:
        """These layers laid over ``beneath``: what is declared here wins, wrappers add.

        A field passed as ``None`` declares nothing, so a caller composing its
        layers from optional settings does not take away one ``beneath`` has.
        """
        chosen = {
            name: value
            for name in self.model_fields_set
            if (value := getattr(self, name)) is not None
        }
        chosen["wrappers"] = [*beneath.wrappers, *self.wrappers]
        return beneath.model_copy(update=chosen)

    def decorates(self) -> bool:
        """Whether any turn decorator is declared, so an engine is worth wrapping."""
        declared = (
            self.timeout,
            self.budget,
            self.recovery,
            self.correction,
            self.continuation,
            self.persistence,
            self.tracing,
            self.usage,
            self.display,
        )
        return any(layer is not None for layer in declared)

    def around(
        self,
        opened: AbstractAsyncContextManager[SessionEngine],
        resume: SessionId | None,
    ) -> AbstractAsyncContextManager[SessionEngine]:
        """The context opening a session with every layer declared here around it."""
        layered = self.decorated(opened)
        for wrapper in self.wrappers:
            layered = wrapper.around(layered, resume)
        return layered

    @asynccontextmanager
    async def decorated(
        self, opened: AbstractAsyncContextManager[SessionEngine]
    ) -> AsyncGenerator[SessionEngine]:
        """The session beneath, with the turn decorators and the queue declared."""
        async with opened as inner:
            if not self.decorates():
                yield SerializedSession(inner) if self.serialized else inner
                return
            decorating = DecoratingSession(
                inner,
                timeout=self.timeout,
                budget=self.budget,
                recovery=self.recovery,
                correction=self.correction,
                continuation=self.continuation,
                persistence=self.persistence,
                tracing=self.tracing,
                usage=self.usage,
                display=self.display,
            )
            try:
                yield SerializedSession(decorating) if self.serialized else decorating
            finally:
                await decorating.close()


class CleanupWrapper(SessionWrapper):
    """Run one cleanup when the session closes, however it closes.

    An application's resources that live exactly as long as a session — a
    sandbox container, a scratch directory — end here rather than in a
    ``finally`` every caller has to remember.
    """

    def __init__(self, cleanup: Callable[[], None]) -> None:
        self.cleanup = cleanup

    def around(
        self,
        opened: AbstractAsyncContextManager[SessionEngine],
        resume: SessionId | None,
    ) -> AbstractAsyncContextManager[SessionEngine]:
        return self.cleaned(opened)

    @asynccontextmanager
    async def cleaned(
        self, opened: AbstractAsyncContextManager[SessionEngine]
    ) -> AsyncGenerator[SessionEngine]:
        try:
            async with opened as engine:
                yield engine
        finally:
            self.cleanup()
