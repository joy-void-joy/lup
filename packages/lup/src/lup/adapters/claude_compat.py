"""The ``claude-compat`` engine: Claude scaffolding on compatible endpoints.

One of two homes for open models, chosen by API protocol: an endpoint
speaking the Anthropic protocol runs here, keeping the full Claude
scaffolding — hooks, permission modes, native subagents — while an
OpenAI-protocol endpoint runs on ``openai-compat``
(:mod:`lup.adapters.openai_compat`) through the bare Codex runtime.

The native-option override carries the full endpoint setup, reconciled
against the aimo3 project's working Anthropic-compatible configuration
(GLM/vLLM served on Kaggle, OpenRouter locally):

- ``ANTHROPIC_BASE_URL`` — the endpoint the scaffolding talks to.
- Credential header — ``compat.auth_style`` routes ``compat.api_key`` to
  either ``ANTHROPIC_AUTH_TOKEN`` (bearer; hosted gateways) or
  ``ANTHROPIC_API_KEY`` (native ``x-api-key``; local servers) and blanks
  the unused one, so an ambient Anthropic key never leaks to the endpoint.
  A caller who supplies no key gets a placeholder, since a local endpoint
  ignores auth but the CLI still needs a non-empty credential.
- Model-alias mapping — ``compat.map_model_aliases`` points Claude's
  ``opus``/``sonnet``/``haiku`` aliases (the last being the small/fast
  background model) at ``opts.model`` via ``ANTHROPIC_DEFAULT_*_MODEL``, so
  a single-model endpoint is never asked for a model it does not serve.
- Nonessential-traffic silencing — telemetry, error reporting, and the bug
  command are disabled unconditionally: pointed away from Anthropic, none
  of that traffic concerns the served model.

Checked against aimo3 and deliberately not ported here, to settle the
doubt either way:

- Extended-thinking capacity (aimo3 zeroed ``max_thinking_tokens`` for
  vLLM) is the caller's per-model lever on
  :class:`~lup.options.LupAgentOptions` — some open models support thinking,
  some do not — so the engine does not force it.
- ``IS_SANDBOX`` is a container/permission-bootstrap signal orthogonal to
  the endpoint; forcing it would weaken the permission posture off Kaggle.
- Per-request API timeouts, custom headers, and retry knobs: aimo3 sets
  none, so the SDK defaults stand and no field is invented for them.

Everything else — option translation, backgrounds, unsupported knobs — is
inherited from the claude engine.
"""

from claude_agent_sdk import ClaudeAgentOptions

from lup.adapters.claude import ClaudeEngine
from lup.options import CompatOptions, LupAgentOptions

DISABLE_NONESSENTIAL_TRAFFIC_ENV = {
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "DISABLE_BUG_COMMAND": "1",
}
"""Claude Code traffic with no bearing on the served model — disabled on
every compat run, since a run pointed away from Anthropic has no use for it."""

ANTHROPIC_MODEL_ALIAS_ENV = (
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
)
"""Env vars resolving Claude's built-in model aliases. Pointed at the one
served model so a single-model endpoint never sees an alias it lacks — the
``HAIKU`` slot is the small/fast model the harness uses for background work."""

PLACEHOLDER_CREDENTIAL = "dummy"
"""Stand-in when the caller supplies no ``api_key``: a local endpoint ignores
auth, but the CLI still needs a non-empty credential to avoid interactive
login or reaching for an ambient Anthropic key."""


class ClaudeCompatEngine(ClaudeEngine):
    """Anthropic-protocol-compatible endpoints through the Claude scaffolding.

    Points the Claude SDK at ``opts.compat.base_url`` via the SDK subprocess
    environment, so open models served behind an Anthropic-style API keep
    hooks, permission modes, and native subagents. The full endpoint env
    setup — credentials, model-alias mapping, traffic silencing — is
    documented on the module.
    """

    id = "claude-compat"

    def native_options(self, opts: LupAgentOptions) -> ClaudeAgentOptions:
        compat = opts.compat
        if not compat.base_url:
            raise ValueError(
                "the claude-compat engine needs compat.base_url — the "
                "Anthropic-compatible endpoint the Claude scaffolding "
                "should talk to (OPENAI_BASE_URL / CompatOptions)."
            )
        native = super().native_options(opts)
        env = native.env
        env["ANTHROPIC_BASE_URL"] = compat.base_url
        set_endpoint_credential(env, compat)
        if compat.map_model_aliases:
            for var in ANTHROPIC_MODEL_ALIAS_ENV:
                env[var] = opts.model
        env.update(DISABLE_NONESSENTIAL_TRAFFIC_ENV)
        return native


def set_endpoint_credential(env: dict[str, str], compat: CompatOptions) -> None:
    """Route the endpoint credential into its header and blank the other.

    ``auth_style`` picks the bearer (``ANTHROPIC_AUTH_TOKEN``) or native
    ``x-api-key`` (``ANTHROPIC_API_KEY``) header; the unused one is emptied so
    an ambient Anthropic key inherited by the SDK subprocess is not sent to
    the compatible endpoint.
    """
    credential = compat.api_key or PLACEHOLDER_CREDENTIAL
    match compat.auth_style:
        case "auth_token":
            env["ANTHROPIC_AUTH_TOKEN"] = credential
            env["ANTHROPIC_API_KEY"] = ""
        case "api_key":
            env["ANTHROPIC_API_KEY"] = credential
            env["ANTHROPIC_AUTH_TOKEN"] = ""
