"""The ``claude-compat`` engine: Claude scaffolding on compatible endpoints.

One of two homes for open models, chosen by API protocol: an endpoint
speaking the Anthropic protocol runs here, keeping the full Claude
scaffolding — hooks, permission modes, native subagents — while an
OpenAI-protocol endpoint runs on ``openai-compat``
(:mod:`lup.adapters.clients.openai_compat`) through the bare Codex runtime.

Points the Claude SDK at ``opts.base_url`` via the SDK subprocess
environment (``ANTHROPIC_BASE_URL``/``ANTHROPIC_AUTH_TOKEN``), so open
models served behind an Anthropic-style API (GLM et al.) keep hooks,
permission modes, and native subagents. Everything else — option
translation, refusal — reuses :func:`build_claude_options`.
"""

import claude_agent_sdk as claude

from lup.adapters.clients.claude import ClaudeClient, build_claude_options
from lup.adapters.clients.common import Client, refuse_unconsumed
from lup.adapters.common import LupAgentOptions


def build_claude_compat_options(opts: LupAgentOptions) -> claude.ClaudeAgentOptions:
    """Translate to native options, then point the SDK env at the endpoint."""
    if not opts.base_url:
        raise ValueError(
            "the claude-compat engine needs base_url — the "
            "Anthropic-compatible endpoint the Claude scaffolding should "
            "talk to (OPENAI_BASE_URL / LupAgentOptions.base_url)."
        )
    native = build_claude_options(opts)
    native.env["ANTHROPIC_BASE_URL"] = opts.base_url
    if opts.api_key:
        native.env["ANTHROPIC_AUTH_TOKEN"] = (
            opts.api_key
        )  # lup: Are you sure this is enough? Please look at aimo3 and all the different options and things we had to change, I'm sure it was more
    return native


def create_claude_compat(options: LupAgentOptions) -> Client:
    """Build a Claude SDK client pointed at an Anthropic-compatible endpoint.

    Refuses the same intent knobs as ``claude`` (``turn_timeout_seconds``):
    the translation is :func:`build_claude_options` plus env, so it reads
    the same knobs and leaves the same one unread.
    """
    return ClaudeClient(
        refuse_unconsumed("claude-compat", options, build_claude_compat_options)
    )
