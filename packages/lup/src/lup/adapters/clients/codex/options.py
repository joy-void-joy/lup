"""Translation-side helpers for the Codex engine.

What the engine reads off :class:`~lup.adapters.options.LupAgentOptions`
is what it honors (see :mod:`lup.adapters.clients.refusal`); the pieces
here shape those reads — the effort map, the priced-budget rule, and the
subprocess sandbox-cleanup guarantee a session carries.
"""

from contextlib import AbstractContextManager, nullcontext

from lup.adapters.options import LupAgentOptions

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
