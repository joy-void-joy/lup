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

from lup.adapters.codex import (
    CodexAdapter,
    CodexConversation,
    CodexHookConfig,
    CodexUsageNormalizer,
    require_codex_sdk,
)
from lup.adapters.common import Conversation
from lup.trace import TraceLogger
from lup.types import LupResponse

logger = logging.getLogger(__name__)


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
        hook_overrides: list[CodexHookConfig] | None = None,
        usage_normalizer: CodexUsageNormalizer | None = None,
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
            hook_overrides=hook_overrides,
            usage_normalizer=usage_normalizer,
        )
        self.base_url = base_url
        self.api_key = api_key
        self.model_provider = model_provider

    def build_config_overrides(self) -> tuple[str, ...]:
        """Extend parent config with OpenAI-compatible endpoint settings."""
        overrides = list(super().build_config_overrides())
        if self.base_url:
            overrides.append(f'model_provider.openai_compat.base_url="{self.base_url}"')
        if self.api_key:
            overrides.append(f'model_provider.openai_compat.api_key="{self.api_key}"')
        return tuple(overrides)

    @asynccontextmanager
    async def conversation(self) -> AsyncGenerator[Conversation, None]:
        require_codex_sdk()

        from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox

        config = CodexConfig(config_overrides=self.build_config_overrides())

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
            yield CodexConversation(
                thread,
                output_schema=self.output_schema,
                effort=self.effort,
                usage_normalizer=self.usage_normalizer,
            )


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
