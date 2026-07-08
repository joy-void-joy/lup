"""The neutral seam: every engine behind ``create_client()`` and ``query()``.

An engine is one backend, complete: a ``create_*`` factory that turns
neutral :class:`~lup.adapters.options.LupAgentOptions` into a
:class:`~lup.adapters.clients.Client.Client`,
and the client opens :class:`~lup.adapters.clients.Client.Session`\\ s.
``query()`` is the self-contained one-shot (opens, sends, closes —
nothing to leak); ``session()`` is the explicit multi-turn context,
resumable across process runs via ``session(resume=...)`` and
``Session.id``.

This module is SDK-free. Two plain routers relate names to engine
factories, and both keep their values lazy — thin module-level wrappers
that import the engine module only when called — so ``import lup`` works
with neither SDK installed and each engine pulls in only its own:

- :data:`ENGINES` maps each shipped engine id to its factory. Insertion
  order is the capability-table display order; anything needing the
  shipped ids iterates it.
- :data:`MODEL_ROUTES` maps a model-name regex to a factory, first match
  wins. The keys are regexes (not prefixes) so a future route can
  deconstruct a model name via named groups into subparams — e.g. a
  ``r"(?P<family>gpt)-(?P<size>\\d+)"`` key could read ``family``/``size``
  off the match. No route does that today; the shape is ready for it.

There is no registry to mutate and no capability declarations to branch
on: a custom backend is a factory callable passed as ``engine=``, an
engine refuses intent knobs it cannot honor (``UnsupportedOptionsError``;
``query()`` drops them with a log line), unsupported operations raise
``UnsupportedOperationError`` at the point of use, and the devtools
capability table is probed from that behavior rather than declared.
"""

import logging
import re
from collections.abc import Callable
from importlib import import_module
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from lup.adapters.options import LupAgentOptions
from lup.telemetry.trace import TraceLogger
from lup.types import (
    LupResponse,
    PermissionMode,
)

if TYPE_CHECKING:
    from lup.adapters.clients.Client import Client

logger = logging.getLogger(__name__)


type ClientFactory = Callable[[LupAgentOptions], "Client"]
"""One engine, as the seam sees it: neutral options in, a configured
:class:`~lup.adapters.clients.Client.Client` out. The shipped engines'
factories live in ``lup.adapters.clients.*``; a custom backend is any
callable of this shape passed as ``engine=``."""


def lazy_engine(module: str, factory: str) -> ClientFactory:
    """Build one engine's factory: the single object both routers key on by identity.

    The returned callable imports ``module``'s ``create_*`` only when first
    invoked, so ``import lup`` needs no SDK installed and each engine pulls in
    only its own optional dependency. Bind the result to one module-level name
    and reference that same object from both :data:`ENGINES` and
    :data:`MODEL_ROUTES`: :func:`engine_id_of` recovers an engine's id by object
    identity, so a per-engine factory must stay one object, never two lambdas.
    """

    def create(options: LupAgentOptions) -> "Client":
        create_native: ClientFactory = getattr(import_module(module), factory)
        return create_native(options)

    return create


claude_engine = lazy_engine("lup.adapters.clients.claude", "create_claude")
claude_compat_engine = lazy_engine(
    "lup.adapters.clients.claude_compat", "create_claude_compat"
)
codex_engine = lazy_engine("lup.adapters.clients.codex", "create_codex")
openai_compat_engine = lazy_engine(
    "lup.adapters.clients.openai_compat", "create_openai_compat"
)


ENGINES: dict[str, ClientFactory] = {
    "claude": claude_engine,
    "codex": codex_engine,
    "openai-compat": openai_compat_engine,
    "claude-compat": claude_compat_engine,
}
"""The id router: every shipped engine's factory, in display order. The
capability table renders one column per entry, in this order."""

MODEL_ROUTES: dict[str, ClientFactory] = {
    r"^claude-|^(?:haiku|sonnet|opus)$": claude_engine,
    r"^gpt-|^o\d+-|^codex-": codex_engine,
    r"": openai_compat_engine,
}
"""The model-name router: a regex per engine, first match wins. A
``claude-`` prefix and the bare aliases route to ``claude``; a
``gpt-``/``o<digit>-``/``codex-`` prefix routes to ``codex``; the empty
pattern matches anything left over, landing unknown models on
``openai-compat``. ``claude-compat`` is never inferred — open models
behind an Anthropic-style endpoint name it explicitly."""


def factory_for_model(model: str) -> ClientFactory:
    """The engine factory a model name infers to — first :data:`MODEL_ROUTES` match."""
    for pattern, factory in MODEL_ROUTES.items():
        if re.search(pattern, model):
            return factory
    return openai_compat_engine


def engine_id_of(factory: ClientFactory) -> str:
    """The :data:`ENGINES` id for a factory, for display and family checks.

    The routers share one factory object per engine, so a factory pulled
    out of :data:`MODEL_ROUTES` finds its id here by identity.
    """
    for engine_id, engine_factory in ENGINES.items():
        if engine_factory is factory:
            return engine_id
    raise ValueError(f"factory {factory!r} is not a shipped engine")


def resolve_factory(
    engine: "str | ClientFactory | None", *, model: str
) -> ClientFactory:
    """Pick the engine factory: explicit callable > id in :data:`ENGINES` > model route."""
    match engine:
        case None:
            return factory_for_model(model)
        case str():
            try:
                return ENGINES[engine]
            except KeyError:
                raise ValueError(
                    f"Unknown engine {engine!r}. Shipped ids: "
                    f"{', '.join(ENGINES)}; pass a factory callable for a "
                    "custom backend."
                ) from None
        case _:
            return engine


def create_client(
    *,
    model: str | None = None,
    engine: "str | ClientFactory | None" = None,
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
) -> "Client":
    """Build a configured :class:`~lup.adapters.clients.Client.Client` — the one door to every engine.

    The keyword form is the nested-call tier: raw system prompt, nothing
    persists, no SDK sandbox — what a tool that needs an LLM call wants.
    Session-grade construction (harness preset, hooks, tool servers,
    persistence) passes a full ``options`` object instead; combining the
    two forms raises rather than silently ignoring keywords.

    Every argument is a construction knob, fixed for the client's
    lifetime; run-time arguments (the prompt, tracing) go to
    ``Client.query`` and ``Session.send``.

    ``engine`` accepts a shipped id, a custom factory callable, or ``None``
    to infer the engine from the model name.
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
            persist_session=False,
            session_defaults=False,
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
    return resolve_factory(engine, model=opts.model)(opts)


async def query(
    prompt: str,
    *,
    model: str = "claude-opus-4-6",
    engine: "str | ClientFactory | None" = None,
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
        model=model,
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
