"""The neutral seam: every engine behind ``create_client()`` and ``query()``.

An :class:`Engine` is one backend, complete: it constructs a
:class:`Client` from neutral options, and the client opens
:class:`Session`\\ s. ``query()`` is the self-contained one-shot (opens,
sends, closes — nothing to leak); ``session()`` is the explicit
multi-turn context, resumable across process runs via
``session(resume=...)`` and :attr:`Session.id`.

This module is SDK-free. :data:`ENGINE_ROUTER` — the one routing
structure — relates model-name patterns to lazily-imported engine
constructors, so ``import lup`` works with neither SDK installed and
each engine pulls in only its own. There is no registry to mutate: a
custom backend is an :class:`Engine` instance passed as ``engine=``.

The ABCs draw one deliberate line. ``@abstractmethod`` members
(:meth:`Session.send`, :meth:`Client.session`, :meth:`Engine.client`)
are what every engine must provide. Concrete defaults that raise
:class:`UnsupportedOperationError` (:meth:`Session.interrupt`,
:meth:`Engine.background`) or fall back (:meth:`Client.stream` replays a
finished turn) mark optional capabilities: the *absence* is part of the
contract — callers catch it at the point of use, and the devtools
capability table is probed from exactly this behavior (a ``stream``
override means live streaming, a ``background`` that raises means no
background support). Abstract members here would force identical
raising stubs into every engine, blur unsupported-by-design against
not-yet-implemented, and break the probes' override detection.

What an engine cannot honor likewise surfaces as behavior, not
declarations: construction applies the options' ``on_unsupported``
policy to the engine's declared blind spots (:attr:`Engine.unsupported`
via :meth:`Engine.enforce`), and unsupported operations raise at the
point of use.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from lup.background import BackgroundAgentParams, BaseBackgroundAgent
from lup.options import LupAgentOptions
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
    PermissionMode,
)

if TYPE_CHECKING:
    from lup.realtime_relay import RealtimeMailbox

logger = logging.getLogger(__name__)


class UnsupportedOperationError(NotImplementedError):
    """The engine behind this client cannot perform the requested operation.

    Raised at the point of use — ``interrupt()`` on a runtime with no
    interruption support, ``session(resume=...)`` on an engine that cannot
    restore threads. A ``NotImplementedError`` subclass, so generic
    ``except NotImplementedError`` handlers also catch it.
    """


class UnsupportedOptionsError(ValueError):
    """The engine cannot honor intent knobs the options carry.

    Raised at construction (``on_unsupported="raise"``, the session
    default), so a session that asked for, say, ``max_turns`` on a runtime
    without turn caps fails before it starts. ``fields`` names the
    offenders. With ``on_unsupported="drop"`` the engine clears them and
    logs instead — the one-shot ``query()`` policy.
    """

    def __init__(self, engine: str, fields: list[str]) -> None:
        self.engine = engine
        self.fields = sorted(fields)
        super().__init__(
            f"options {self.fields} are not supported on the {engine} engine; "
            "unset them or run on an engine that honors them."
        )


class TurnTimeoutError(RuntimeError):
    """A turn exceeded its wall-clock timeout and was cancelled client-side.

    Raised by engines that enforce ``turn_timeout_seconds`` when a single
    turn runs past it. The backend thread's state is undefined afterwards
    — close the session rather than sending further turns on it.
    """


class BudgetExceededError(RuntimeError):
    """A session refused to start a turn: accumulated cost reached the budget.

    Raised between turns by engines that enforce ``max_budget_usd``
    through their own usage accounting (the Codex runtime reports token
    counts, not cost). The turn that crossed the budget has already
    completed — this error stops the *next* one.
    """


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
    ) -> LupResponse: ...

    async def interrupt(self) -> None:
        """Signal the backend to stop the current response.

        Engines without interruption support inherit this default, which
        raises — catch :class:`UnsupportedOperationError` (or plain
        ``NotImplementedError``) where a no-op interrupt is acceptable.
        """
        raise UnsupportedOperationError(
            f"interrupt() is not supported on {type(self).__name__}"
        )


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
        :class:`UnsupportedOperationError`.
        """

    async def query(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        """Self-contained one-shot: open a session, send one prompt, close.

        Carries run-time arguments only — construction knobs (model,
        tools, budgets) were fixed when :func:`create_client` built this
        client.
        """
        async with self.session() as session:
            return await session.send(prompt, trace_logger=trace_logger, prefix=prefix)

    async def stream(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        """Run one prompt, yielding streaming events.

        The default runs the turn to completion and replays its blocks as
        events; engines with a live event stream override this.
        """
        response = await self.query(prompt, trace_logger=trace_logger, prefix=prefix)
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


type EngineId = Literal["claude", "codex", "openai-compat", "claude-compat"]
"""Ids of the shipped engines. Custom engines are passed as instances, so
their ids live outside this literal."""


class Engine(ABC):
    """One backend, complete: client construction and background agents.

    Engines are stateless and cheap — configuration arrives per call as
    :class:`~lup.options.LupAgentOptions`. An engine consumes the
    mechanism payloads that belong to it (in-process hooks and tool
    servers on Claude; served groups, env relay, and writable roots on
    Codex) and ignores the others'; the intent knobs it cannot honor are
    declared on :attr:`unsupported` and policed by :meth:`enforce`.
    """

    id: str

    unsupported: tuple[str, ...] = ()
    """Intent-knob field names this engine has no lever for.

    ``client()`` implementations route their options through
    :meth:`enforce`, which applies the options' ``on_unsupported`` policy
    to exactly these fields."""

    @abstractmethod
    def client(self, opts: LupAgentOptions) -> Client:
        """Construct a configured :class:`Client` from ``self.enforce(opts)``.

        Nothing connects yet — construction is offline and cheap.
        """

    def unsupported_in(self, opts: LupAgentOptions) -> list[str]:
        """The declared blind spots that *opts* actually sets.

        Override for conditional blind spots — the Codex engine refuses
        ``max_budget_usd`` only when no usage rates accompany it.
        """
        return [name for name in self.unsupported if getattr(opts, name) is not None]

    def enforce(self, opts: LupAgentOptions) -> LupAgentOptions:
        """Apply the options' ``on_unsupported`` policy to this engine's blind spots.

        With ``"raise"`` (the session default) any offending field fails
        the construction with :class:`UnsupportedOptionsError`; with
        ``"drop"`` (the one-shot ``query()`` policy) the offenders are
        cleared with a log line and construction proceeds. Mechanism
        payloads meant for other engines are not checked here — each
        engine consumes its own and ignores the rest.
        """
        offenders = self.unsupported_in(opts)
        if not offenders:
            return opts
        if opts.on_unsupported == "raise":
            raise UnsupportedOptionsError(self.id, offenders)
        logger.info(
            "options %s are not supported on the %s engine (model=%r); "
            "proceeding without them.",
            sorted(offenders),
            self.id,
            opts.model,
        )
        return opts.model_copy(update=dict.fromkeys(offenders, None))

    def background(self, params: BackgroundAgentParams) -> BaseBackgroundAgent:
        """Build a background agent for this engine.

        Engines without background support inherit this raising default.
        """
        raise UnsupportedOperationError(
            f"background agents are not supported on the {self.id} engine"
        )


def claude_engine() -> Engine:
    from lup.adapters.claude import ClaudeEngine

    return ClaudeEngine()


def claude_compat_engine() -> Engine:
    from lup.adapters.claude_compat import ClaudeCompatEngine

    return ClaudeCompatEngine()


def codex_engine() -> Engine:
    from lup.adapters.codex import CodexEngine

    return CodexEngine()


def openai_compat_engine() -> Engine:
    from lup.adapters.openai_compat import OpenAICompatEngine

    return OpenAICompatEngine()


class EngineRoute(BaseModel):
    """One row of the model-name router.

    ``prefixes`` and ``aliases`` are the model names the engine claims;
    ``load`` constructs it, importing the engine's module only when the
    row is chosen. A row with no patterns is reached by explicit id only.
    """

    id: EngineId
    prefixes: tuple[str, ...] = ()
    aliases: frozenset[str] = frozenset()
    load: Callable[[], Engine]

    def claims(self, model: str) -> bool:
        return model.startswith(self.prefixes) or model in self.aliases


ENGINE_ROUTER: tuple[EngineRoute, ...] = (
    EngineRoute(
        id="claude",
        prefixes=("claude-",),
        aliases=frozenset({"haiku", "sonnet", "opus"}),
        load=claude_engine,
    ),
    EngineRoute(
        id="codex",
        prefixes=("gpt-", "o1-", "o3-", "o4-", "o5-", "codex-"),
        load=codex_engine,
    ),
    EngineRoute(id="openai-compat", load=openai_compat_engine),
    EngineRoute(id="claude-compat", load=claude_compat_engine),
)
"""The router: every shipped engine, its model-name patterns, and its
lazily-imported constructor. Model names fall through the rows in order
and land on ``openai-compat`` when nothing claims them; ``claude-compat``
claims no names and is only ever chosen explicitly."""

SHIPPED_ENGINE_IDS: tuple[EngineId, ...] = tuple(route.id for route in ENGINE_ROUTER)
"""The shipped engine ids, in display order — the capability table
renders one column per entry."""


def engine_id_for_model(model: str) -> EngineId:
    """Infer the engine for a model name — the router's model column.

    The first route claiming the name wins; names no route claims run on
    the OpenAI-compatible engine. Models behind a configured compatible
    endpoint that should get the Claude scaffolding instead (GLM and
    friends) name their engine explicitly: ``engine="claude-compat"``.
    """
    for route in ENGINE_ROUTER:
        if route.claims(model):
            return route.id
    return "openai-compat"


def engine_for_id(engine_id: str) -> Engine:
    """Instantiate a shipped engine by id — the one sanctioned dispatch.

    Reads the router; each route imports only its own engine module, so
    SDK imports stay deferred until an engine is actually chosen.
    """
    for route in ENGINE_ROUTER:
        if route.id == engine_id:
            return route.load()
    raise ValueError(
        f"Unknown engine {engine_id!r}. Shipped ids: "
        f"{', '.join(SHIPPED_ENGINE_IDS)}; pass an Engine instance for a "
        "custom backend."
    )


def resolve_engine(
    engine: Engine | str | None = None, *, model: str | None = None
) -> Engine:
    """Resolve an engine: explicit instance > id > model-name inference."""
    match engine:
        case Engine():
            return engine
        case str():
            return engine_for_id(engine)
        case None:
            return engine_for_id(engine_id_for_model(model or ""))


def create_client(
    *,
    model: str | None = None,
    engine: Engine | str | None = None,
    options: LupAgentOptions | None = None,
    system_prompt: str | None = None,
    output_type: type[BaseModel] | None = None,
    tools: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    permission_mode: PermissionMode | None = None,
    max_turns: int | None = None,
    max_thinking_tokens: int | None = None,
    max_budget_usd: float | None = None,
    on_unsupported: Literal["raise", "drop"] = "raise",
) -> Client:
    """Build a configured :class:`Client` — the one door to every engine.

    The keyword form is the nested-call tier: raw system prompt, nothing
    persists, no SDK sandbox — what a tool that needs an LLM call wants.
    Session-grade construction (harness prompt, hooks, tool servers,
    persistence) passes a full ``options`` object instead; combining the
    two forms raises rather than silently ignoring keywords.

    Every argument is a construction knob, fixed for the client's
    lifetime; run-time arguments (the prompt, tracing) go to
    :meth:`Client.query` and :meth:`Session.send`.

    ``engine`` accepts a shipped id or a custom :class:`Engine` instance;
    left ``None``, it is inferred from the model name.
    """
    keyword_form = {
        "model": model,
        "system_prompt": system_prompt,
        "output_type": output_type,
        "tools": tools,
        "allowed_tools": allowed_tools,
        "permission_mode": permission_mode,
        "max_turns": max_turns,
        "max_thinking_tokens": max_thinking_tokens,
        "max_budget_usd": max_budget_usd,
    }
    if options is not None:
        given = sorted(
            name for name, value in keyword_form.items() if value is not None
        )
        if given:
            raise ValueError(
                f"create_client: a full options object was given together with "
                f"keyword arguments {given}, which would be silently ignored — "
                "set them on the options object instead."
            )
        opts = options
    else:
        if model is None:
            raise ValueError(
                "create_client needs model=... (or a full options= object)."
            )
        opts = LupAgentOptions(
            model=model,
            system_prompt=system_prompt or "",
            harness_prompt=False,
            persist_session=False,
            sdk_sandbox=False,
            output_schema=output_type.model_json_schema() if output_type else None,
            tools=tools,
            allowed_tools=allowed_tools or [],
            permission_mode=permission_mode,
            max_turns=max_turns,
            max_thinking_tokens=max_thinking_tokens,
            max_budget_usd=max_budget_usd,
            on_unsupported=on_unsupported,
        )
    return resolve_engine(engine, model=opts.model).client(opts)


async def query(
    prompt: str,
    *,
    model: str | None = None,
    engine: Engine | str | None = None,
    system_prompt: str | None = None,
    output_type: type[BaseModel] | None = None,
    trace_logger: TraceLogger | None = None,
    prefix: str = "",
    tools: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    permission_mode: PermissionMode | None = None,
    max_turns: int | None = None,
    max_thinking_tokens: int | None = None,
    max_budget_usd: float | None = None,
) -> LupResponse:
    """One-shot query — the one-liner for nested LLM calls inside tools.

    Sugar over :func:`create_client`: builds a call-tier client for the
    model's engine and runs a single self-contained query. Intent knobs
    the engine cannot honor are dropped with a log line rather than
    raising — a caller can express full intent and let the engine keep
    what it can.

    Returns a ``LupResponse`` — use ``.text`` for text or
    ``.output(MyModel)`` for structured output.
    """
    client = create_client(
        model=model or "claude-opus-4-6",
        engine=engine,
        system_prompt=system_prompt,
        output_type=output_type,
        tools=tools,
        allowed_tools=allowed_tools,
        permission_mode=permission_mode,
        max_turns=max_turns,
        max_thinking_tokens=max_thinking_tokens,
        max_budget_usd=max_budget_usd,
        on_unsupported="drop",
    )
    return await client.query(prompt, trace_logger=trace_logger, prefix=prefix)
