"""Neutral→native option translation for the Codex engine.

:func:`build_codex_native` is the engine's whole translation — what it
reads off :class:`~lup.adapters.options.LupAgentOptions` is exactly what
the engine honors (see :mod:`lup.adapters.clients.refusal`) — and
everything a run needs is computed here once, into one frozen-shape
:class:`CodexNativeConfig` the client carries (mirroring the Claude
engine's native ``ClaudeAgentOptions``). The ``openai-compat`` engine
reuses it and appends its custom-provider definition afterward.
"""

from contextlib import AbstractContextManager, nullcontext

from pydantic import BaseModel, model_validator

from lup.adapters.clients.codex.config import (
    build_mcp_config_overrides,
    build_sandbox_config_overrides,
)
from lup.adapters.options import LupAgentOptions
from lup.types import JsonObject, UsageCost

CODEX_EFFORT_MAP: dict[str, str] = {
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
    return CODEX_EFFORT_MAP.get(reasoning_effort, reasoning_effort)


def subprocess_sandbox_cleanup(
    opts: LupAgentOptions,
) -> AbstractContextManager[object]:
    """Guarantee the session's subprocess sandbox container dies on exit.

    The Codex/OpenAI tool subprocess may be killed before it can clean up its
    own container; the parent removes it. A no-op without the docker extra, or
    when the build names no session.
    """
    if opts.session_id is None or opts.shared_dir is None:
        return nullcontext()
    try:
        from lup.sandbox.container import sandbox_cleanup
    except ImportError:
        return nullcontext()
    return sandbox_cleanup(session_id=opts.session_id, shared_dir=opts.shared_dir)


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


class CodexNativeConfig(BaseModel):
    """The Codex engine's translated native configuration.

    Everything a client run needs, computed once at translation: the
    thread-start scalars, the fully rendered ``config_overrides`` lines
    and subprocess env, the turn-governance knobs, and the session's
    cleanup guarantee. The client only carries it — there is nothing left
    to assemble at run time, which is what lets ``openai-compat`` be a
    translation (appended provider lines) rather than a client subclass.
    """

    # ``usage_cost`` is a bare callable and ``cleanup`` a context manager —
    # pydantic accepts them only under arbitrary types.
    model_config = {"arbitrary_types_allowed": True}

    model: str
    system_prompt: str = ""
    model_provider: str | None = None
    """Codex model-provider selector for thread start; ``None`` runs on
    the account's default provider."""
    sandbox: str | None = None
    approval_policy: str | None = None
    output_schema: JsonObject | None = None
    effort: str | None = None
    config_overrides: list[str] = []
    env: dict[str, str] = {}
    """Extra env for the Codex subprocess (e.g. a provider's ``env_key``
    credential)."""
    max_budget_usd: float | None = None
    usage_cost: UsageCost | None = None
    turn_timeout_seconds: float | None = None
    cleanup: AbstractContextManager[object] | None = None

    @model_validator(mode="after")
    def require_priced_budget(self) -> "CodexNativeConfig":
        """A budget with nothing to price it against cannot be enforced."""
        if self.max_budget_usd is not None and self.usage_cost is None:
            raise ValueError(
                "max_budget_usd on the Codex runtime requires a usage_cost "
                "estimator — the SDK reports token counts, not cost. Build "
                "one with per_mtok_usage_cost(...)."
            )
        return self


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
    overrides: list[str] = []
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
        effort=opts.reasoning_effort,
        config_overrides=overrides,
        max_budget_usd=budget_if_priced(opts),
        usage_cost=opts.usage_cost,
        turn_timeout_seconds=opts.turn_timeout_seconds,
        cleanup=subprocess_sandbox_cleanup(opts),
    )
