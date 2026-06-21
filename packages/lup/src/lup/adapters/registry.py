"""Map a backend id to the engine builder that constructs its adapter.

The one place backend dispatch is sanctioned (it lives inside the adapter
layer, has exactly one entry per engine, and is open for downstream
extension). Consumers call :func:`build_adapter`; they never name an engine.
Each builder takes the neutral :class:`~lup.options.LupAgentOptions` and returns
a :class:`~lup.options.BuiltAdapter`.
"""

from lup.options import AdapterBuilder, BuiltAdapter, LupAgentOptions
from lup.types import Backend


def build_claude_adapter(opts: LupAgentOptions) -> BuiltAdapter:
    """Construct the Claude adapter from neutral options."""
    from lup.adapters.claude.options import build_claude_adapter as build

    return build(opts)


def build_codex_adapter(opts: LupAgentOptions) -> BuiltAdapter:
    """Construct the Codex adapter from neutral options."""
    from lup.adapters.codex_options import build_codex_adapter as build

    return build(opts)


def build_openai_adapter(opts: LupAgentOptions) -> BuiltAdapter:
    """Construct the OpenAI-compatible adapter from neutral options."""
    from lup.adapters.codex_options import build_openai_adapter as build

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
