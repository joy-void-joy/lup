"""The ``openai-compat`` engine: OpenAI-protocol endpoints through Codex.

One of two homes for open models, chosen by API protocol: an endpoint
speaking the OpenAI protocol runs here on the Codex runtime (custom
``model_providers`` definition, native sandboxing, served tools), while
an Anthropic-protocol endpoint runs on ``claude-compat``
(:mod:`lup.adapters.clients.claude_compat`) and keeps the full Claude
scaffolding — hooks, permission modes, native subagents.

Uses the same ``openai_codex`` SDK as the standard Codex client —
no additional dependencies needed.
"""

import logging
from collections.abc import Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TYPE_CHECKING

from lup.adapters.clients.codex import (
    CodexClient,
    CodexHookConfig,
    CodexUsageNormalizer,
    budget_if_priced,
    subprocess_sandbox_cleanup,
)
from lup.adapters.clients.common import Client, refuse_unconsumed
from lup.adapters.common import LupAgentOptions
from lup.types import JsonObject, UsageCost

if TYPE_CHECKING:
    import openai_codex as codex

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


def build_openai_compat_client(opts: LupAgentOptions) -> "OpenAICompatClient":
    """Translate neutral options into an OpenAI-compatible Codex client.

    Identical to :func:`~lup.adapters.clients.codex.build_codex_client`
    except it carries the compat endpoint (``base_url``, ``api_key``,
    ``model_provider``) so the client can define a custom Codex provider.
    """
    return OpenAICompatClient(
        model=opts.model,
        system_prompt=opts.system_prompt,
        base_url=opts.base_url,
        api_key=opts.api_key,
        model_provider=opts.model_provider,
        output_schema=opts.output_schema,
        sandbox=opts.codex_sandbox,
        effort=opts.reasoning_effort,
        approval_policy=opts.approval_policy,
        mcp_tools=bool(opts.served_tool_groups),
        mcp_env=dict(opts.mcp_env),
        writable_roots=list(opts.writable_roots),
        mcp_servers=opts.served_tool_groups,
        max_budget_usd=budget_if_priced(opts),
        usage_cost=opts.usage_cost,
        turn_timeout_seconds=opts.turn_timeout_seconds,
        cleanup=subprocess_sandbox_cleanup(opts),
    )


def create_openai_compat(options: LupAgentOptions) -> Client:
    """Build an OpenAI-compatible Codex client from neutral options.

    Refuses the same intent knobs as ``codex`` and, when persistent, wires
    the file-relay mailbox — the translation is
    :func:`build_openai_compat_client`, which reads the same honored knobs.
    """
    client = refuse_unconsumed("openai-compat", options, build_openai_compat_client)
    if options.realtime and options.realtime_dir is not None:
        from lup.realtime_relay import RealtimeMailbox

        client.mailbox = RealtimeMailbox(options.realtime_dir)
    return client


class OpenAICompatClient(CodexClient):
    """Run prompts via any OpenAI-compatible endpoint through Codex.

    Extends CodexClient by defining a custom provider from ``base_url``
    and selecting it via ``model_provider`` when threads open.
    """

    def __init__(
        self,
        *,
        model: str,
        system_prompt: str = "",
        base_url: str | None = None,
        api_key: str | None = None,
        model_provider: str | None = None,
        output_schema: JsonObject | None = None,
        sandbox: str | None = None,
        effort: str | None = None,
        approval_policy: str | None = None,
        mcp_tools: bool = True,
        mcp_env: dict[str, str] | None = None,
        writable_roots: list[Path] | None = None,
        hook_overrides: list[CodexHookConfig] | None = None,
        usage_normalizer: CodexUsageNormalizer | None = None,
        mcp_servers: Sequence[str] = ("notes", "sandbox"),
        max_budget_usd: float | None = None,
        usage_cost: UsageCost | None = None,
        turn_timeout_seconds: float | None = None,
        cleanup: AbstractContextManager[object] | None = None,
    ) -> None:
        super().__init__(
            model=model,
            system_prompt=system_prompt,
            output_schema=output_schema,
            sandbox=sandbox,
            effort=effort,
            approval_policy=approval_policy,
            mcp_tools=mcp_tools,
            mcp_env=mcp_env,
            writable_roots=writable_roots,
            hook_overrides=hook_overrides,
            usage_normalizer=usage_normalizer,
            mcp_servers=mcp_servers,
            max_budget_usd=max_budget_usd,
            usage_cost=usage_cost,
            turn_timeout_seconds=turn_timeout_seconds,
            cleanup=cleanup,
        )
        self.base_url = base_url
        self.api_key = api_key
        self.model_provider = model_provider

    def provider_id(self) -> str:
        """Codex ``model_providers`` id this endpoint is defined under.

        An explicit ``model_provider`` names the table; otherwise the
        generated namespaced id is used (built-in ids are reserved).
        """
        return self.model_provider or OPENAI_COMPAT_PROVIDER_ID

    def provider_env(self) -> dict[str, str]:
        """Env vars the Codex subprocess needs for the custom provider.

        Codex resolves the provider key from the ``env_key`` env var, so
        the literal ``api_key`` is surfaced under that name whenever a
        ``base_url`` endpoint is configured.
        """
        if self.base_url and self.api_key:
            return {OPENAI_COMPAT_API_KEY_ENV: self.api_key}
        return {}

    def build_config_overrides(self) -> list[str]:
        """Extend parent config with a Codex custom-provider definition.

        Provider definitions live in the plural ``model_providers.<id>``
        table (``base_url`` + ``env_key``, where ``env_key`` names the
        environment variable holding the key — never an inline literal),
        and the top-level ``model_provider`` string selects one. A
        ``base_url`` is the signal to define the provider; without it the
        provider is assumed to live in the caller's own Codex config and
        is only selected (via ``model_provider`` on thread start).
        """
        overrides = super().build_config_overrides()
        if not self.base_url:
            return overrides

        provider = self.provider_id()
        overrides.append(f'model_provider="{provider}"')
        overrides.append(f'model_providers.{provider}.name="{provider}"')
        overrides.append(f'model_providers.{provider}.base_url="{self.base_url}"')
        if self.api_key:
            overrides.append(
                f'model_providers.{provider}.env_key="{OPENAI_COMPAT_API_KEY_ENV}"'
            )
        return overrides

    def codex_config(self) -> "codex.CodexConfig":
        """Extend the runtime config with the provider's API-key env."""
        import openai_codex as codex

        return codex.CodexConfig(
            config_overrides=tuple(self.build_config_overrides()),
            env=self.provider_env() or None,
        )
