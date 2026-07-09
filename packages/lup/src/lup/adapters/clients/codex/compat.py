"""The ``openai-compat`` engine: OpenAI-protocol endpoints through Codex.

One of two homes for open models, chosen by API protocol: an endpoint
speaking the OpenAI protocol runs here on the Codex runtime (custom
``model_providers`` definition, native sandboxing, served tools), while
an Anthropic-protocol endpoint runs on ``claude-compat``
(:mod:`lup.adapters.clients.claude.compat`) and keeps the full Claude
scaffolding — hooks, permission modes, native subagents.

The whole engine is a translation: :func:`build_openai_compat_native`
runs the Codex translation and appends the custom-provider definition —
config-override lines plus the credential env — onto the same
:class:`~lup.adapters.clients.codex.options.CodexNativeConfig` shape the
plain ``codex`` engine produces, so the client class is shared, not
subclassed. Uses the same ``openai_codex`` SDK as the standard Codex
client — no additional dependencies needed.
"""

import logging

from lup.adapters.clients.Client import Client
from lup.adapters.clients.codex.create import compose_codex
from lup.adapters.clients.codex.options import CodexNativeConfig, build_codex_native
from lup.adapters.clients.refusal import refuse_unconsumed
from lup.adapters.options import LupAgentOptions

logger = logging.getLogger(__name__)

OPENAI_COMPAT_PROVIDER_ID = "lup_openai_compat"
"""Codex ``model_providers`` table id for the synthesized custom provider.

Built-in ids (``openai``, ``ollama``, ``lmstudio``) are reserved by the
Codex runtime, so the generated provider definition uses a namespaced id.
"""

OPENAI_COMPAT_API_KEY_ENV = "LUP_OPENAI_COMPAT_API_KEY"
"""Env var the generated provider's ``env_key`` points at.

Codex providers reference the API key by environment-variable *name*
(``env_key``), never an inline literal — the supplied ``api_key`` is
injected into the Codex subprocess env under this name.
"""


def build_openai_compat_native(opts: LupAgentOptions) -> CodexNativeConfig:
    """The Codex translation plus a custom-provider definition.

    Provider definitions live in the plural ``model_providers.<id>``
    table (``base_url`` + ``env_key``, where ``env_key`` names the
    environment variable holding the key — never an inline literal),
    and the top-level ``model_provider`` string selects one. A
    ``base_url`` is the signal to define the provider; without it the
    provider is assumed to live in the caller's own Codex config and is
    only selected (via ``model_provider`` on thread start).
    """
    native = build_codex_native(opts)
    native.model_provider = opts.model_provider
    if not opts.base_url:
        return native

    provider = opts.model_provider or OPENAI_COMPAT_PROVIDER_ID
    native.config_overrides.append(f'model_provider="{provider}"')
    native.config_overrides.append(f'model_providers.{provider}.name="{provider}"')
    native.config_overrides.append(
        f'model_providers.{provider}.base_url="{opts.base_url}"'
    )
    if opts.api_key:
        native.config_overrides.append(
            f'model_providers.{provider}.env_key="{OPENAI_COMPAT_API_KEY_ENV}"'
        )
        native.env[OPENAI_COMPAT_API_KEY_ENV] = opts.api_key
    return native


def create_openai_compat(options: LupAgentOptions) -> Client:
    """Build an OpenAI-compatible Codex client from neutral options.

    Refuses the same intent knobs as ``codex`` and, when persistent, wires
    the file-relay mailbox — the translation is
    :func:`build_openai_compat_native`, which reads the same honored knobs.
    """
    client = compose_codex(
        refuse_unconsumed("openai-compat", options, build_openai_compat_native)
    )
    if options.realtime and options.realtime_dir is not None:
        from lup.realtime.relay import RealtimeMailbox

        client.mailbox = RealtimeMailbox(options.realtime_dir)
    return client
