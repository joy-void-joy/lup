"""Map a backend id to the engine builders that construct its adapters.

The one place backend dispatch is sanctioned (it lives inside the adapter
layer, has exactly one entry per engine, and is open for downstream
extension). Consumers call :func:`build_adapter` for a session or
:func:`one_shot_adapter` for a single :func:`~lup.adapters.common.query`;
they never name an engine. A session builder takes the neutral
:class:`~lup.options.LupAgentOptions` and returns a
:class:`~lup.options.BuiltAdapter`; a one-shot builder takes a resolved
:class:`~lup.adapters.common.OneShotRequest` and returns a bare adapter.
"""

from lup.adapters.common import (
    AdapterCapabilities,
    Client,
    BackendCapabilities,
    OneShotBuilder,
    OneShotRequest,
)
from lup.options import AdapterBuilder, BuiltAdapter, LupAgentOptions
from lup.types import Backend


def build_claude_adapter(opts: LupAgentOptions) -> BuiltAdapter:
    """Construct the Claude adapter from neutral options."""
    from lup.adapters.claude.options import build_claude_adapter as build

    return build(opts)


def build_codex_adapter(opts: LupAgentOptions) -> BuiltAdapter:
    """Construct the Codex adapter from neutral options."""
    from lup.adapters.codex.options import build_codex_adapter as build

    return build(opts)


def build_openai_adapter(opts: LupAgentOptions) -> BuiltAdapter:
    """Construct the OpenAI-compatible adapter from neutral options."""
    from lup.adapters.codex.options import build_openai_adapter as build

    return build(opts)


BACKEND_BUILDERS: dict[Backend, AdapterBuilder] = {
    "anthropic": build_claude_adapter,
    "openai": build_codex_adapter,
    "openai-compatible": build_openai_adapter,
}


def build_adapter(backend: Backend, opts: LupAgentOptions) -> BuiltAdapter:
    """Build the adapter for *backend* from neutral options.

    Looks the engine builder up in :data:`BACKEND_BUILDERS` and delegates —
    the sanctioned replacement for a ``match backend`` in consumer code.
    """
    return BACKEND_BUILDERS[backend](opts)


def build_claude_one_shot(request: OneShotRequest) -> Client:
    """Construct the Claude one-shot adapter from a resolved request."""
    from lup.adapters.claude.options import build_claude_one_shot as build

    return build(request)


def build_codex_one_shot(request: OneShotRequest) -> Client:
    """Construct the Codex one-shot adapter from a resolved request."""
    from lup.adapters.codex.options import build_codex_one_shot as build

    return build(request)


def build_openai_one_shot(request: OneShotRequest) -> Client:
    """Construct the OpenAI-compatible one-shot adapter from a resolved request."""
    from lup.adapters.codex.options import build_openai_one_shot as build

    return build(request)


ONE_SHOT_BUILDERS: dict[Backend, OneShotBuilder] = {
    "anthropic": build_claude_one_shot,
    "openai": build_codex_one_shot,
    "openai-compatible": build_openai_one_shot,
}


def one_shot_adapter(backend: Backend, request: OneShotRequest) -> Client:
    """Build the one-shot adapter for *backend* from a resolved request.

    The one-shot counterpart of :func:`build_adapter`: ``query()`` resolves
    its options against the backend's capabilities and hands the result here.
    """
    return ONE_SHOT_BUILDERS[backend](request)


def backend_capabilities(backend: Backend) -> AdapterCapabilities:
    """The capabilities of *backend*, read off a probe adapter.

    Builds a minimal one-shot adapter that is never run — no session, no
    SDK subprocess. Instance-dependent entries therefore show their
    unconfigured value (Codex ``cost_reporting`` needs caller-supplied
    rates); the static support flags are what capability gating reads.
    """
    return one_shot_adapter(backend, OneShotRequest(model="")).capabilities


def canonical_capability_matrix() -> list[BackendCapabilities]:
    """The shipped backends' capabilities, in canonical display form.

    The single source for every rendering of the parity contract: the
    ``lup-devtools agent capabilities`` command, the README table, and
    the regression test that keeps the two identical. Codex/OpenAI are
    shown with budget rates configured (their best case) —
    ``cost_reporting`` degrades to ``none`` without ``CODEX_USD_PER_MTOK``
    rates.
    """
    from claude_agent_sdk import ClaudeAgentOptions

    from lup.adapters.claude.adapter import ClaudeAdapter
    from lup.adapters.codex.adapter import CodexAdapter, per_mtok_usage_cost
    from lup.adapters.codex.openai_compat import OpenAICompatibleAdapter

    rates = per_mtok_usage_cost(input_usd=1.0, output_usd=1.0)
    return [
        BackendCapabilities(
            name="claude", capabilities=ClaudeAdapter(ClaudeAgentOptions()).capabilities
        ),
        BackendCapabilities(
            name="codex",
            capabilities=CodexAdapter(
                model="gpt-5.5", system_prompt="", usage_cost=rates
            ).capabilities,
        ),
        BackendCapabilities(
            name="openai",
            capabilities=OpenAICompatibleAdapter(
                model="local", usage_cost=rates
            ).capabilities,
        ),
    ]
