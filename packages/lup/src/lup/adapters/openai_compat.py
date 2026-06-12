# claude: ignore
"""OpenAI-compatible API adapter via the Codex SDK.

Routes open-source models (GLM-4, Llama, DeepSeek, etc.) through the
Codex runtime by setting the ``model_provider`` parameter on thread
start. The Codex CLI handles the actual OpenAI-compatible API calls,
sandboxing, and tool execution.

Uses the same ``openai_codex`` SDK as the standard Codex adapter —
no additional dependencies needed.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from collections.abc import Sequence

from lup.adapters.codex import (
    CodexAdapter,
    CodexHookConfig,
    CodexUsageNormalizer,
    UsageCost,
    require_codex_sdk,
)
from lup.adapters.common import Conversation
from lup.trace import TraceLogger
from lup.types import LupResponse

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


class OpenAICompatibleAdapter(CodexAdapter):
    """Run prompts via any OpenAI-compatible endpoint through Codex.

    Extends CodexAdapter by passing ``model_provider`` to route
    requests to a custom OpenAI-compatible API endpoint.
    """

    def __init__(
        self,
        *,
        model: str,
        system_prompt: str = "",
        base_url: str | None = None,
        api_key: str | None = None,
        model_provider: str | None = None,
        output_schema: dict[str, object] | None = None,
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

    def build_config_overrides(self) -> tuple[str, ...]:
        """Extend parent config with a Codex custom-provider definition.

        Provider definitions live in the plural ``model_providers.<id>``
        table (``base_url`` + ``env_key``, where ``env_key`` names the
        environment variable holding the key — never an inline literal),
        and the top-level ``model_provider`` string selects one. A
        ``base_url`` is the signal to define the provider; without it the
        provider is assumed to live in the caller's own Codex config and
        is only selected (via ``model_provider`` on thread start).
        """
        overrides = list(super().build_config_overrides())
        if not self.base_url:
            return tuple(overrides)

        provider = self.provider_id()
        overrides.append(f'model_provider="{provider}"')
        overrides.append(f'model_providers.{provider}.name="{provider}"')
        overrides.append(f'model_providers.{provider}.base_url="{self.base_url}"')
        if self.api_key:
            overrides.append(
                f'model_providers.{provider}.env_key="{OPENAI_COMPAT_API_KEY_ENV}"'
            )
        return tuple(overrides)

    @asynccontextmanager
    async def conversation(self) -> AsyncGenerator[Conversation, None]:
        require_codex_sdk()

        from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox

        config = CodexConfig(
            config_overrides=self.build_config_overrides(),
            env=self.provider_env() or None,
        )

        async with AsyncCodex(config=config) as codex:
            thread = await codex.thread_start(
                model=self.model,
                model_provider=self.model_provider,
                developer_instructions=self.system_prompt,
                sandbox=Sandbox(self.sandbox) if self.sandbox else None,
                approval_mode=(
                    ApprovalMode(self.approval_policy)
                    if self.approval_policy
                    else ApprovalMode.auto_review
                ),
            )
            yield self.make_conversation(thread)


async def openai_query(
    prompt: str,
    *,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
    model_provider: str | None = None,
    system_prompt: str = "",
    output_schema: dict[str, object] | None = None,
    trace_logger: TraceLogger | None = None,
    prefix: str = "",
) -> LupResponse:
    """One-shot query via an OpenAI-compatible endpoint through Codex.

    Args:
        prompt: The prompt to send.
        model: Model name (as known to the inference server).
        base_url: Base URL of the inference server.
        api_key: API key (many local servers don't require one).
        model_provider: Codex model provider identifier.
        system_prompt: System prompt override.
        output_schema: JSON schema for structured output.
        trace_logger: Optional trace logger.
        prefix: Display prefix for trace output.

    Returns:
        LupResponse with the result.
    """
    adapter = OpenAICompatibleAdapter(
        model=model,
        system_prompt=system_prompt,
        base_url=base_url,
        api_key=api_key,
        model_provider=model_provider,
        output_schema=output_schema,
    )
    return await adapter.run(prompt, trace_logger=trace_logger, prefix=prefix)
