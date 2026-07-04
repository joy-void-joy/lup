"""The client seam: purely abstract ``Client``/``Session`` plus shared helpers.

The ABCs draw the contract and nothing else — every member is
``@abstractmethod``, no concrete defaults and no raising stubs. What an
engine cannot do it says in its own module: an engine without a live
event stream implements ``stream`` as a one-line call to
:func:`replay_stream`, an engine without a self-contained one-shot
implements ``query`` via :func:`query_via_session`, and an engine that
lacks a capability entirely writes its own explicit
``raise UnsupportedOperationError(...)`` at the point of use (``interrupt``
where there is no interruption, ``session(resume=...)`` where threads
cannot be restored). Reading one engine module shows exactly what it
cannot do.

Refusal of intent knobs is behavioral too: :func:`refuse_unconsumed`
runs an engine's translation over a :class:`ConsumeTracker` view of the
options and refuses any intent knob the caller set but the translation
never read — the engine has no lever for what it does not consume.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from pydantic import PrivateAttr

from lup.adapters.common import LupAgentOptions, UnsupportedOptionsError
from lup.trace import TraceLogger
from lup.types import (
    LupDoneEvent,
    LupEvent,
    LupResponse,
    LupTextBlock,
    LupTextEvent,
    LupThinkingBlock,
    LupThinkingEvent,
    LupToolResultBlock,
    LupToolResultEvent,
    LupToolUseBlock,
    LupToolUseEvent,
)

if TYPE_CHECKING:
    from lup.realtime_relay import RealtimeMailbox

logger = logging.getLogger(__name__)


class Session(ABC):
    """Multi-turn conversation session.

    Wraps a live SDK client or thread. ``send()`` sends a message and
    collects the full response. :attr:`id` is the engine-native session
    identifier once known — save it and pass it to
    ``Client.session(resume=...)`` to continue the conversation in a
    different process.
    """

    id: str | None = None
    """Engine-native session identifier (Claude session id, Codex thread
    id). ``None`` until the engine reports it — populated on open for
    resumed sessions, after the first turn otherwise."""

    @abstractmethod
    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        """Send one message and collect the full response."""

    @abstractmethod
    async def interrupt(self) -> None:
        """Signal the backend to stop the current response.

        Engines without interruption support raise
        :class:`~lup.adapters.common.UnsupportedOperationError` here.
        """


class Client(ABC):
    """A configured handle on one engine — cheap to build, nothing connected.

    ``query()`` runs a self-contained one-shot. ``session()`` opens the
    explicit multi-turn context; the engine's session-scoped resources
    (SDK client, container cleanup) live inside that context manager.
    """

    mailbox: "RealtimeMailbox | None" = None
    """Parent-side endpoint of the realtime file relay — not a caller knob.

    ``None`` unless the engine itself set it at construction: subprocess
    engines populate it when the options request persistent (sleep/wake)
    mode. Consumers only read it, to drive the relay loop."""

    @abstractmethod
    def session(
        self, *, resume: str | None = None
    ) -> AbstractAsyncContextManager[Session]:
        """Open a multi-turn session; ``resume`` continues a saved one.

        Implementations are ``@asynccontextmanager`` async generators
        yielding a :class:`Session`. The SDK client/thread is created on
        entry and cleaned up on exit. ``resume`` takes a previously saved
        :attr:`Session.id`; engines that cannot restore sessions raise
        :class:`~lup.adapters.common.UnsupportedOperationError`.
        """

    @abstractmethod
    async def query(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        """Self-contained one-shot: open a session, send one prompt, close.

        Engines with no native one-shot implement this as a one-line call
        to :func:`query_via_session`. Carries run-time arguments only —
        construction knobs were fixed when the engine's factory built this
        client.
        """

    @abstractmethod
    def stream(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        """Run one prompt, yielding streaming events.

        Engines with a live event stream yield as the turn unfolds; those
        without implement this as a one-line call to :func:`replay_stream`,
        which runs the turn to completion and replays its blocks.
        """


async def query_via_session(
    client: Client,
    prompt: str,
    *,
    trace_logger: TraceLogger | None = None,
    prefix: str = "",
) -> LupResponse:
    """Open a session, send one prompt, close — the self-contained one-shot.

    The shared ``Client.query`` body for engines whose one-shot is just a
    single-turn session.
    """
    async with client.session() as session:
        return await session.send(prompt, trace_logger=trace_logger, prefix=prefix)


async def replay_stream(
    client: Client,
    prompt: str,
    *,
    trace_logger: TraceLogger | None = None,
    prefix: str = "",
) -> AsyncGenerator[LupEvent, None]:
    """Run the turn to completion, then replay its blocks as events.

    The shared ``Client.stream`` body for engines without a live event
    stream. Preserves the block→event mapping every consumer expects.
    """
    response = await client.query(prompt, trace_logger=trace_logger, prefix=prefix)
    for block in response.blocks:
        match block:
            case LupThinkingBlock():
                yield LupThinkingEvent(thinking=block.thinking)
            case LupTextBlock():
                yield LupTextEvent(text=block.text)
            case LupToolUseBlock():
                yield LupToolUseEvent(id=block.id, name=block.name)
            case LupToolResultBlock():
                yield LupToolResultEvent(
                    tool_use_id=block.tool_use_id,
                    content=str(block.content),
                )
    yield LupDoneEvent(blocks=response.blocks)


INTENT_KNOBS: frozenset[str] = frozenset(
    {
        "max_turns",
        "max_thinking_tokens",
        "permission_mode",
        "tools",
        "reasoning_effort",
        "max_budget_usd",
        "turn_timeout_seconds",
    }
)
"""The scalar intent fields subject to consume-tracking refusal.

An engine that reads one of these during translation honors it; one it
leaves unread has no lever for it and refuses it. Mechanism payloads
(tool servers, hooks, subagents, served groups, dirs, output schema) and
their helpers (``usage_cost``, the estimator behind ``max_budget_usd``)
are outside this set — they keep their consume-or-ignore-freely
semantics and are never policed."""


class ConsumeTracker(LupAgentOptions):
    """A translation-time view of options that records intent-knob reads.

    Each ``create_*`` translates through one of these; an intent knob the
    caller SET but the translation never READ is a knob the engine has no
    lever for. Only :data:`INTENT_KNOBS` reads are recorded, so reading a
    mechanism payload records nothing.

    The ``__getattribute__`` override is the whole mechanism: it records a
    read for an intent-knob field name and otherwise defers to the base
    lookup, leaving pydantic's own machinery untouched. Type checkers
    resolve known members from the class, not through ``__getattribute__``,
    so pyright still sees each field's real declared type.
    """

    _consumed: set[str] = PrivateAttr(default_factory=set)

    @classmethod
    def tracking(cls, opts: LupAgentOptions) -> "ConsumeTracker":
        """A tracker over ``opts``' fields with an empty read record.

        ``model_construct`` copies the validated fields without re-running
        validation and initializes the empty read set — no intent knob is
        touched before translation begins.
        """
        return cls.model_construct(**opts.__dict__)

    @property
    def consumed(self) -> set[str]:
        """The intent-knob field names the translation has read so far."""
        return self._consumed

    def __getattribute__(self, name: str) -> object:
        if name in INTENT_KNOBS:
            self._consumed.add(name)
        return super().__getattribute__(name)


def refuse_unconsumed[N](
    engine_id: str,
    opts: LupAgentOptions,
    translate: Callable[[LupAgentOptions], N],
) -> N:
    """Translate ``opts`` and refuse the intent knobs the translation ignored.

    Runs ``translate`` over a :class:`ConsumeTracker`; any intent knob the
    caller set but the translation never read is one the engine cannot
    honor. Under ``on_unsupported="raise"`` (the session default) those
    fail the construction with :class:`~lup.adapters.common.UnsupportedOptionsError`;
    under ``"drop"`` (the ``query()`` policy) they are logged and the
    already-untouched native result is returned as-is. Because the
    translation never read them, the native object already reflects their
    absence — dropping needs no re-translation.

    The alternative shape, weighed and set aside, is a per-engine intent
    model: each engine declares a small ``BaseModel`` of exactly the knobs
    it honors (Claude's would carry ``max_turns``/``max_thinking_tokens``/
    ``permission_mode``/``tools``/``reasoning_effort``/``max_budget_usd``,
    Codex's would omit them and carry ``turn_timeout_seconds``); refusal
    becomes "set fields absent from the model", conditional refusals become
    ``model_validator``s (Codex drops ``max_budget_usd`` unless
    ``usage_cost`` is present), and translation consumes the validated
    model. That shape makes the honored set a declared registry a reader
    can see at a glance, but it duplicates every knob's type across the
    neutral options and each engine's model, and the two can drift.
    Consume-tracking keeps the translation code itself as the single source
    of truth — what an engine reads is what it honors, with no second
    declaration to maintain — at the cost of a reflective override rather
    than a plain model. Both are sketched here so the choice can be made at
    review.
    """
    tracker = ConsumeTracker.tracking(opts)
    native = translate(tracker)
    offenders = sorted(
        knob
        for knob in INTENT_KNOBS
        if getattr(opts, knob) is not None and knob not in tracker.consumed
    )
    if offenders:
        match opts.on_unsupported:
            case "raise":
                raise UnsupportedOptionsError(engine_id, offenders)
            case "drop":
                logger.info(
                    "options %s are not supported on the %s engine (model=%r); "
                    "proceeding without them.",
                    offenders,
                    engine_id,
                    opts.model,
                )
    return native
