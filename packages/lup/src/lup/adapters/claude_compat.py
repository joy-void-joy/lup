"""The ``claude-compat`` engine: Claude scaffolding on compatible endpoints.

One of two homes for open models, chosen by API protocol: an endpoint
speaking the Anthropic protocol runs here, keeping the full Claude
scaffolding — hooks, permission modes, native subagents — while an
OpenAI-protocol endpoint runs on ``openai-compat``
(:mod:`lup.adapters.openai_compat`) through the bare Codex runtime.
"""

from claude_agent_sdk import ClaudeAgentOptions

from lup.adapters.claude import ClaudeEngine
from lup.options import LupAgentOptions


class ClaudeCompatEngine(ClaudeEngine):
    """Anthropic-protocol-compatible endpoints through the Claude scaffolding.

    Points the Claude SDK at ``opts.compat.base_url`` via the SDK
    subprocess environment (``ANTHROPIC_BASE_URL``/``ANTHROPIC_AUTH_TOKEN``),
    so open models served behind an Anthropic-style API (GLM et al.) keep
    hooks, permission modes, and native subagents. Everything else —
    option translation, backgrounds, unsupported knobs — is inherited.
    """

    id = "claude-compat"

    def native_options(self, opts: LupAgentOptions) -> ClaudeAgentOptions:
        if not opts.compat.base_url:
            raise ValueError(
                "the claude-compat engine needs compat.base_url — the "
                "Anthropic-compatible endpoint the Claude scaffolding "
                "should talk to (OPENAI_BASE_URL / CompatOptions)."
            )
        native = super().native_options(opts)
        native.env["ANTHROPIC_BASE_URL"] = opts.compat.base_url
        if opts.compat.api_key:
            native.env["ANTHROPIC_AUTH_TOKEN"] = opts.compat.api_key
        return native
