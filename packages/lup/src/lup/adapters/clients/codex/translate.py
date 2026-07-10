"""Neutral→native option translation for the Codex engine.

:func:`build_codex_native` is the engine's whole translation — what it
reads off :class:`~lup.adapters.options.LupAgentOptions` is exactly what
the engine honors (see :mod:`lup.adapters.clients.refusal`) — and
everything a run needs is computed here once, into one frozen-shape
:class:`~lup.adapters.clients.codex.native.CodexNativeConfig` the client
carries. The ``openai-compat`` engine reuses it and appends its
custom-provider definition afterward.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext

from lup.adapters.clients.codex.config import (
    build_mcp_config_overrides,
    build_sandbox_config_overrides,
)
from lup.adapters.clients.codex.native import CodexNativeConfig
from lup.adapters.options import LupAgentOptions

# Open on purpose: unmapped levels pass through for the runtime enum to judge.
CODEX_EFFORT_MAP: dict[str, str] = {  # lup: ignore[dict-str-payload]
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "xhigh",
}


def codex_effort(reasoning_effort: str | None) -> str | None:
    """Map a generic effort level to the Codex runtime's ``ReasoningEffort``.

    An unrecognized level passes through unchanged for the enum to reject.
    """
    if reasoning_effort is None:
        return None
    mapped = CODEX_EFFORT_MAP.get(reasoning_effort)  # lup: ignore[dict-get]
    return mapped or reasoning_effort


def subprocess_sandbox_cleanup(
    opts: LupAgentOptions,
) -> Callable[[], AbstractContextManager[object]]:
    """A factory for the session's sandbox-cleanup guard, entered once per open.

    The Codex/OpenAI tool subprocess may be killed before it can clean up its
    own container; each opened session enters a fresh guard so the parent
    removes the container however the subprocess died. A guard is single-use
    (``@contextmanager``), which is why the translation carries this factory
    rather than a guard instance. A ``nullcontext`` factory without the docker
    extra, or when the build names no session.
    """
    session_id, shared_dir = opts.session_id, opts.shared_dir
    if session_id is None or shared_dir is None:
        return nullcontext
    try:
        from lup.sandbox.container import sandbox_cleanup
    except ImportError:
        return nullcontext

    def open_guard() -> AbstractContextManager[object]:
        return sandbox_cleanup(session_id=session_id, shared_dir=shared_dir)

    return open_guard


def budget_if_priced(opts: LupAgentOptions) -> float | None:
    """The budget cap, read only when a ``usage_cost`` makes it enforceable.

    Reading ``max_budget_usd`` solely under a present ``usage_cost`` is what
    makes the codex engines refuse an unpriced budget: with no estimator the
    read never happens, so consume-tracking sees the knob unconsumed and
    flags it. The Codex runtime reports token counts, never cost, so a
    budget with nothing to price it against cannot be enforced.
    """
    if opts.usage_cost is not None:
        return opts.max_budget_usd
    return None


def build_codex_native(opts: LupAgentOptions) -> CodexNativeConfig:
    """Translate neutral options into the engine's native configuration.

    Reads the knobs the runtime honors — ``reasoning_effort``,
    ``turn_timeout_seconds``, and ``max_budget_usd`` (only when priced by
    ``usage_cost``) — and leaves ``max_turns``/``max_thinking_tokens``/
    ``permission_mode``/``tools`` unread, which is how they come to be
    refused: the runtime has no per-session turn cap, thinking budget,
    permission mode, or builtin-toolset restriction. The served-tool and
    native-sandbox ``config_overrides`` are rendered here, once.
    """
    overrides: list[str] = []  # lup: ignore[empty-collection] — conditional build
    if opts.served_tool_groups:
        overrides.extend(
            build_mcp_config_overrides(
                env=dict(opts.mcp_env), servers=opts.served_tool_groups
            )
        )
    if opts.writable_roots:
        overrides.extend(build_sandbox_config_overrides(list(opts.writable_roots)))
    return CodexNativeConfig(
        model=opts.model,
        system_prompt=opts.system_prompt,
        sandbox=opts.codex_sandbox,
        approval_policy=opts.approval_policy,
        output_schema=opts.output_schema,
        effort=codex_effort(opts.reasoning_effort),
        config_overrides=overrides,
        max_budget_usd=budget_if_priced(opts),
        usage_cost=opts.usage_cost,
        turn_timeout_seconds=opts.turn_timeout_seconds,
        cleanup=subprocess_sandbox_cleanup(opts),
        realtime_dir=opts.realtime_dir if opts.realtime else None,
    )
