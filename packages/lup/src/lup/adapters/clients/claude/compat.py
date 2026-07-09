"""The ``claude-compat`` engine: Claude scaffolding on compatible endpoints.

One of two homes for open models, chosen by API protocol: an endpoint
speaking the Anthropic protocol runs here, keeping the full Claude
scaffolding — hooks, permission modes, native subagents — while an
OpenAI-protocol endpoint runs on ``openai-compat``
(:mod:`lup.adapters.clients.codex.compat`) through the bare Codex runtime.

The native-option override carries the full endpoint setup:

- ``ANTHROPIC_BASE_URL`` — the endpoint the scaffolding talks to.
- Credential header — ``auth_style`` routes ``api_key`` to either
  ``ANTHROPIC_AUTH_TOKEN`` (bearer; hosted gateways) or ``ANTHROPIC_API_KEY``
  (native ``x-api-key``; local servers) and blanks the unused one, so an
  ambient Anthropic key never leaks to the endpoint. A caller who supplies
  no key gets a placeholder, since a local endpoint ignores auth but the CLI
  still needs a non-empty credential.
- Model-alias mapping — ``map_model_aliases`` points Claude's
  ``opus``/``sonnet``/``haiku`` aliases (the last being the small/fast
  background model) at ``opts.model`` via ``ANTHROPIC_DEFAULT_*_MODEL``, so a
  single-model endpoint is never asked for a model it does not serve.
- Nonessential-traffic silencing — telemetry, error reporting, and the bug
  command are disabled unconditionally: pointed away from Anthropic, none of
  that traffic concerns the served model.

Deliberately absent: the engine forces no thinking capacity (whether an
open model supports extended thinking is the caller's per-model lever on
:class:`LupAgentOptions`), no ``IS_SANDBOX`` (a container/permission
bootstrap signal orthogonal to the endpoint), and no per-request
timeout/header/retry fields (the SDK defaults stand). Everything else —
option translation, refusal, backgrounds — reuses
:func:`build_claude_options` and the ``claude`` engine.
"""

import claude_agent_sdk as claude

from lup.adapters.clients.claude.create import compose_claude
from lup.adapters.clients.claude.translate import build_claude_options
from lup.adapters.clients.Client import Client
from lup.adapters.clients.refusal import refuse_unconsumed
from lup.adapters.options import LupAgentOptions

DISABLE_NONESSENTIAL_TRAFFIC_ENV = {
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "DISABLE_BUG_COMMAND": "1",
}
"""Claude Code traffic with no bearing on the served model — disabled on
every compat run, since a run pointed away from Anthropic has no use for it."""

ANTHROPIC_MODEL_ALIAS_ENV = [
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
]
"""Env vars resolving Claude's built-in model aliases. Pointed at the one
served model so a single-model endpoint never sees an alias it lacks — the
``HAIKU`` slot is the small/fast model the harness uses for background work."""

PLACEHOLDER_CREDENTIAL = "dummy"
"""Stand-in when the caller supplies no ``api_key``: a local endpoint ignores
auth, but the CLI still needs a non-empty credential to avoid interactive
login or reaching for an ambient Anthropic key."""


def set_endpoint_credential(env: dict[str, str], opts: LupAgentOptions) -> None:
    """Route the endpoint credential into its header and blank the other.

    ``auth_style`` picks the bearer (``ANTHROPIC_AUTH_TOKEN``) or native
    ``x-api-key`` (``ANTHROPIC_API_KEY``) header; the unused one is emptied so
    an ambient Anthropic key inherited by the SDK subprocess is not sent to
    the compatible endpoint.
    """
    credential = opts.api_key or PLACEHOLDER_CREDENTIAL
    match opts.auth_style:
        case "auth_token":
            env["ANTHROPIC_AUTH_TOKEN"] = credential
            env["ANTHROPIC_API_KEY"] = ""
        case "api_key":
            env["ANTHROPIC_API_KEY"] = credential
            env["ANTHROPIC_AUTH_TOKEN"] = ""


def build_claude_compat_options(opts: LupAgentOptions) -> claude.ClaudeAgentOptions:
    """Translate to native options, then point the SDK env at the endpoint."""
    if not opts.base_url:
        raise ValueError(
            "the claude-compat engine needs base_url — the "
            "Anthropic-compatible endpoint the Claude scaffolding should "
            "talk to (OPENAI_BASE_URL / LupAgentOptions.base_url)."
        )
    native = build_claude_options(opts)
    env = native.env
    env["ANTHROPIC_BASE_URL"] = opts.base_url
    set_endpoint_credential(env, opts)
    if opts.map_model_aliases:
        for var in ANTHROPIC_MODEL_ALIAS_ENV:
            env[var] = opts.model
    env.update(DISABLE_NONESSENTIAL_TRAFFIC_ENV)
    return native


def create_claude_compat(options: LupAgentOptions) -> Client:
    """Build a Claude SDK client pointed at an Anthropic-compatible endpoint.

    Refuses the same intent knobs as ``claude`` (``turn_timeout_seconds``):
    the translation is :func:`build_claude_options` plus env, so it reads the
    same knobs and leaves the same one unread.
    """
    return compose_claude(
        refuse_unconsumed("claude-compat", options, build_claude_compat_options)
    )
