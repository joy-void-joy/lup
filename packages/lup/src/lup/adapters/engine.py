"""The Engine seam and the ``create_client()`` / ``query()`` frontend.

An :class:`Engine` is one backend, complete: it knows how to construct a
:class:`~lup.adapters.common.Client` from neutral options and how to build
its background agents. Engines are precise implementations; everything
generic (one-shot execution, post-hoc streaming, the debounced background
loop) lives on the base classes they return.

:func:`create_client` is the only public door. It resolves the engine —
from an explicit instance, an id, or the model name — inside
:func:`engine_for_id`, the one sanctioned dispatch point. There is no
registry to mutate: a downstream backend is an :class:`Engine` subclass
passed as ``engine=``.

What an engine cannot honor surfaces as behavior at construction:
:func:`enforce_supported` applies the options' ``on_unsupported`` policy
(sessions raise, the one-shot ``query()`` drops with a log line).
"""

import logging
from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel

from lup.adapters.common import (
    Client,
    PermissionMode,
    UnsupportedOperationError,
    UnsupportedOptionsError,
)
from lup.background import BackgroundAgentParams, BaseBackgroundAgent
from lup.options import LupAgentOptions
from lup.trace import TraceLogger
from lup.types import LupResponse

logger = logging.getLogger(__name__)

type EngineId = Literal["claude", "codex", "openai-compat", "claude-compat"]
"""Ids of the shipped engines. Custom engines are passed as instances, so
their ids live outside this literal."""

CLAUDE_MODEL_PREFIXES: tuple[str, ...] = ("claude-",) # lup: I think this structure is wrong. There shouldn't be any reference to claude in non-claude folder.
CLAUDE_MODEL_ALIASES: frozenset[str] = frozenset({"haiku", "sonnet", "opus"})
CODEX_MODEL_PREFIXES: tuple[str, ...] = ("gpt-", "o1-", "o3-", "o4-", "o5-", "codex-")


class Engine(ABC): #lup: Very unclear. How is that different from client? Why isn't this in common.py?
    """One backend, complete: client construction and background agents.

    Engines are stateless and cheap — configuration arrives per call as
    :class:`~lup.options.LupAgentOptions`. An engine consumes the
    mechanism payloads that belong to it (in-process hooks and tool
    servers on Claude; served groups, env relay, and writable roots on
    Codex) and ignores the others'; intent knobs it cannot honor go
    through :func:`enforce_supported`.
    """

    id: str

    @abstractmethod
    def client(self, opts: LupAgentOptions) -> Client:
        """Construct a configured :class:`Client`. Nothing connects yet."""

    def background(self, params: BackgroundAgentParams) -> BaseBackgroundAgent: #lup: Same remark: Why an UnsupportedOperationError instead of making an abstractmethod
        """Build a background agent for this engine.

        Engines without background support inherit this raising default.
        """
        raise UnsupportedOperationError(
            f"background agents are not supported on the {self.id} engine"
        )


def enforce_supported(
    opts: LupAgentOptions, *, engine: str, unsupported: tuple[str, ...]
) -> LupAgentOptions:
    #lup: Unclear what this is and why this is needed. Smell like poor design
    """Apply the options' ``on_unsupported`` policy to an engine's blind spots.

    ``unsupported`` names the intent-knob fields this engine cannot honor;
    any of them that are set either fail the construction (``raise``, the
    session default) or are cleared with a log line (``drop``, the
    one-shot policy). Mechanism payloads meant for other engines are not
    checked here — each engine consumes its own and ignores the rest.
    """
    offenders = [name for name in unsupported if getattr(opts, name) is not None]
    if not offenders:
        return opts
    if opts.on_unsupported == "raise":
        raise UnsupportedOptionsError(engine, offenders)
    logger.info(
        "options %s are not supported on the %s engine (model=%r); "
        "proceeding without them.",
        sorted(offenders),
        engine,
        opts.model,
    )
    return opts.model_copy(update=dict.fromkeys(offenders, None))


def engine_id_for_model(model: str) -> EngineId:
    #lup: Same here.
    """Infer the engine for a model name by prefix.

    Claude models (``claude-*`` and the short aliases) run on the Claude
    engine, GPT/O-series/Codex models on the Codex engine, and everything
    else on the OpenAI-compatible engine. Models behind a configured
    compatible endpoint that should get the Claude scaffolding instead
    (GLM and friends) name their engine explicitly: ``engine="claude-compat"``.
    """
    if model.startswith(CLAUDE_MODEL_PREFIXES) or model in CLAUDE_MODEL_ALIASES:
        return "claude"
    if model.startswith(CODEX_MODEL_PREFIXES):
        return "codex"
    return "openai-compat"


def engine_for_id(engine_id: str) -> Engine: #lup: Like if the whole idea is "Having default constructors", better to just have default constructor in the claude and codex folder. And just have one big router relating model name to their respective engine
    """Instantiate a shipped engine by id — the one sanctioned dispatch.

    One lazy import per engine keeps SDK imports deferred: ``import lup``
    works with neither SDK installed, and each engine pulls in only its
    own.
    """
    match engine_id:
        case "claude":
            from lup.adapters.claude.engine import ClaudeEngine

            return ClaudeEngine()
        case "claude-compat":
            from lup.adapters.claude.engine import ClaudeCompatEngine

            return ClaudeCompatEngine()
        case "codex":
            from lup.adapters.codex.engine import CodexEngine

            return CodexEngine()
        case "openai-compat":
            from lup.adapters.codex.engine import OpenAICompatEngine

            return OpenAICompatEngine()
        case _:
            raise ValueError(
                f"Unknown engine {engine_id!r}. Shipped ids: claude, codex, "
                "openai-compat, claude-compat; pass an Engine instance for a "
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
) -> Client: #lup: same, why is this needed?
    """Build a configured :class:`Client` — the one door to every engine.

    The keyword form is the nested-call tier: raw system prompt, nothing
    persists, no SDK sandbox — what a tool that needs an LLM call wants.
    Session-grade construction (harness prompt, hooks, tool servers,
    persistence) passes a full ``options`` object instead; combining the
    two forms raises rather than silently ignoring keywords.

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
) -> LupResponse: #lup: Yeah, good
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
