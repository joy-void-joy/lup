# lup: ignore[import-re, re-call]
# MODEL_ROUTES is regex routing by design — model-name patterns ARE the table,
# so the regex rules are opted out file-wide.
"""The neutral seam: every engine behind ``create_client()`` and ``query()``.

An engine is one backend, complete
(:class:`~lup.adapters.engines.Engine.Engine`): it turns neutral
:class:`~lup.adapters.options.LupAgentOptions` into a
:class:`~lup.adapters.clients.Client.Client`, and the client opens
:class:`~lup.adapters.clients.sessions.Session.Session`\\ s. ``query()`` is the
self-contained one-shot (opens, sends, closes — nothing to leak);
``session()`` is the explicit multi-turn context, resumable across
process runs via ``session(resume=...)`` and ``Session.id``.

This module is SDK-free — an engine object imports an SDK only inside
the method that needs it — and holds the only dispatch, two plain
routers:

- :data:`ENGINES` maps each shipped engine id to its engine. Insertion
  order is the capability-table display order; anything needing the
  shipped ids iterates it.
- :data:`MODEL_ROUTES` maps a model-name regex to an engine, first match
  wins; the empty catch-all pattern keeps the table total.

There is no registry to mutate and no capability declarations to branch
on: a custom backend is an :class:`~lup.adapters.engines.Engine.Engine` instance
passed as ``engine=``, an engine refuses intent knobs it cannot honor
(``UnsupportedOptionsError``; ``query()`` drops them with a log line),
unsupported operations raise ``UnsupportedOperationError`` at the point
of use, and the devtools capability table is probed from that behavior
rather than declared.
"""

import logging
import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from lup.adapters.engines.claude import ClaudeEngine
from lup.adapters.engines.claude_compat import ClaudeCompatEngine
from lup.adapters.engines.codex import CodexEngine
from lup.adapters.engines.Engine import Engine
from lup.adapters.engines.openai_compat import OpenAICompatEngine
from lup.adapters.options import LupAgentOptions
from lup.telemetry.trace import TraceLogger
from lup.types import (
    LupResponse,
    PermissionMode,
)

if TYPE_CHECKING:
    from lup.adapters.clients.Client import Client

logger = logging.getLogger(__name__)


ENGINES: dict[str, Engine] = {
    engine.id: engine
    for engine in (
        ClaudeEngine(),
        CodexEngine(),
        OpenAICompatEngine(),
        ClaudeCompatEngine(),
    )
}
"""The id router: every shipped engine, in display order. The
capability table renders one column per entry, in this order."""

MODEL_ROUTES: dict[str, Engine] = {
    r"^claude-|^(?:haiku|sonnet|opus)$": ENGINES["claude"],
    r"^gpt-|^o\d+-|^codex-": ENGINES["codex"],
    r"": ENGINES["openai-compat"],
}
"""The model-name router: a regex per engine, first match wins. A
``claude-`` prefix and the bare aliases route to ``claude``; a
``gpt-``/``o<digit>-``/``codex-`` prefix routes to ``codex``; the empty
pattern matches anything left over, landing unknown models on
``openai-compat``. ``claude-compat`` is never inferred — open models
behind an Anthropic-style endpoint name it explicitly."""


def engine_for_model(model: str) -> Engine:
    """The engine a model name infers to — first :data:`MODEL_ROUTES` match.

    The empty catch-all pattern makes the table total; reaching past the
    loop means the table itself was edited out of totality.
    """
    for pattern, engine in MODEL_ROUTES.items():
        if re.search(pattern, model):
            return engine
    raise LookupError(
        f"No MODEL_ROUTES pattern matches model {model!r} — the table has "
        "lost its catch-all route."
    )


def resolve_engine(
    engine: "str | Engine | None" = None, *, model: str | None = None
) -> Engine:
    """Pick the engine: explicit instance > id in :data:`ENGINES` > model route."""
    match engine:
        case None:
            if model is None:
                raise ValueError(
                    "resolve_engine needs an engine id or instance, or a "
                    "model to infer one from."
                )
            return engine_for_model(model)
        case str():
            try:
                return ENGINES[engine]
            except KeyError:
                raise ValueError(
                    f"Unknown engine {engine!r}. Shipped ids: "
                    f"{', '.join(ENGINES)}; pass an Engine instance for a "
                    "custom backend."
                ) from None
        case _:
            return engine


def create_client(
    *,
    model: str | None = None,
    engine: "str | Engine | None" = None,
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

    ``engine`` accepts a shipped id, an
    :class:`~lup.adapters.engines.Engine.Engine` instance, or ``None`` to
    infer the engine from the model name.
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
    return resolve_engine(engine, model=opts.model).client(opts)


async def query(
    prompt: str,
    *,
    model: str = "claude-opus-4-6",
    engine: "str | Engine | None" = None,
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
