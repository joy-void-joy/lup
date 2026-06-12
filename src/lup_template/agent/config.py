"""Configuration management using pydantic-settings.

This is a TEMPLATE. Customize for your domain.

Key patterns:
1. Multiple env files (.env, .env.local) - local overrides shared
2. Optional API keys with startup warnings
3. validation_alias for explicit env var names
4. Singleton instance for easy import

Usage:
    from lup_template.agent.config import settings
    print(settings.model)
"""

import logging
import os
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Agent-specific settings use a prefix (e.g., AGENT_MODEL).
    """

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        extra="ignore",
    )

    @model_validator(mode="after")
    def warn_missing_optional_keys(self) -> Self:
        """Warn at startup if optional API keys are missing.

        Customize this for your domain's optional dependencies.
        """
        missing = []

        # TODO: Add checks for your optional API keys
        # if not self.some_api_key:
        #     missing.append("SOME_API_KEY")

        if missing:
            logger.warning(
                "Missing API keys (some tools may fail): %s", ", ".join(missing)
            )
        return self

    # ==========================================================================
    # OPTIONAL API KEYS (tools degrade gracefully without these)
    # ==========================================================================

    # TODO: Add optional API keys for your domain
    # exa_api_key: str | None = Field(
    #     default=None,
    #     validation_alias="EXA_API_KEY",
    #     description="Exa search API key",
    # )

    # ==========================================================================
    # LLM ROUTING (optional)
    # ==========================================================================

    openrouter_api_key: str | None = Field(
        default=None,
        validation_alias="OPENROUTER_API_KEY",
        description="OpenRouter API key (enables routing through OpenRouter when set)",
    )

    # ==========================================================================
    # SDK SELECTION
    # ==========================================================================

    agent_sdk: Literal["claude", "codex", "openai"] = Field(
        default="claude",
        validation_alias="AGENT_SDK",
        description=(
            "Which agent SDK backend to use (claude, codex, openai). The "
            "reviewer and background agents follow AGENT_AUX_MODEL, which "
            "defaults to a backend-native model. Subagent specs pin their "
            "own models — the template's pin Anthropic ones, so they need "
            "Anthropic credentials on codex/openai unless overridden."
        ),
    )

    openai_base_url: str | None = Field(
        default=None,
        validation_alias="OPENAI_BASE_URL",
        description="Base URL for OpenAI-compatible API (vLLM, Ollama, TGI, etc.)",
    )

    openai_api_key: str | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
        description="API key for OpenAI-compatible API",
    )

    openai_model_provider: str | None = Field(
        default=None,
        validation_alias="OPENAI_MODEL_PROVIDER",
        description="Codex model_provider for OpenAI-compatible endpoints",
    )

    codex_sandbox: str | None = Field(
        default=None,
        validation_alias="CODEX_SANDBOX",
        description="Codex sandbox mode: read_only, workspace_write, danger_full_access",
    )

    codex_effort: str | None = Field(
        default=None,
        validation_alias="CODEX_EFFORT",
        description="Codex reasoning effort: none, minimal, low, medium, high, xhigh",
    )

    codex_approval_policy: str | None = Field(
        default=None,
        validation_alias="CODEX_APPROVAL_POLICY",
        description="Codex approval policy for tool use",
    )

    codex_usd_per_mtok_input: float | None = Field(
        default=None,
        validation_alias="CODEX_USD_PER_MTOK_INPUT",
        description="USD per million input tokens (enables budget enforcement on codex/openai)",
    )

    codex_usd_per_mtok_output: float | None = Field(
        default=None,
        validation_alias="CODEX_USD_PER_MTOK_OUTPUT",
        description="USD per million output tokens (enables budget enforcement on codex/openai)",
    )

    codex_usd_per_mtok_cached_input: float | None = Field(
        default=None,
        validation_alias="CODEX_USD_PER_MTOK_CACHED_INPUT",
        description="USD per million cached input tokens (defaults to the input rate)",
    )

    reasoning_effort: str | None = Field(
        default=None,
        validation_alias="AGENT_REASONING_EFFORT",
        description=(
            "Backend-agnostic reasoning effort. Valid levels differ by "
            "backend: Claude accepts low, medium, high, xhigh, max; "
            "Codex/OpenAI accept none, minimal, low, medium, high, xhigh "
            "(CODEX_EFFORT overrides this on those backends)."
        ),
    )

    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = (
        Field(
            default="bypassPermissions",
            validation_alias="AGENT_PERMISSION_MODE",
            description="Claude SDK permission mode for the main agent session",
        )
    )

    # ==========================================================================
    # MODEL SETTINGS
    # ==========================================================================

    model: str = Field(
        default="claude-opus-4-6",
        validation_alias="AGENT_MODEL",
        description="Model to use (provider-specific identifier)",
    )

    max_thinking_tokens: int | None = Field(
        default=128_000 - 1,
        validation_alias="AGENT_MAX_THINKING_TOKENS",
        description="Max thinking tokens (None = model default)",
    )

    aux_model: str | None = Field(
        default=None,
        validation_alias="AGENT_AUX_MODEL",
        description=(
            "Model for auxiliary agents (reviewer, background agents). "
            "None resolves per backend: a sonnet-class reviewer on claude, "
            "the session model on codex/openai — so AGENT_SDK=codex/openai "
            "runs without Anthropic credentials."
        ),
    )

    # ==========================================================================
    # PATHS
    # ==========================================================================

    notes_path: str = Field(
        default="./notes",
        validation_alias="AGENT_NOTES_PATH",
        description="Base path for notes folders",
    )

    logs_path: str = Field(
        default="./logs",
        validation_alias="AGENT_LOGS_PATH",
        description="Base path for trace logs",
    )

    # ==========================================================================
    # LIMITS
    # ==========================================================================

    max_budget_usd: float | None = Field(
        default=None,
        validation_alias="AGENT_MAX_BUDGET_USD",
        description="Maximum budget per session (None = unlimited)",
    )

    max_turns: int | None = Field(
        default=None,
        validation_alias="AGENT_MAX_TURNS",
        description="Maximum agent turns per session (None = unlimited)",
    )

    sandbox_timeout_seconds: int = Field(
        default=30,
        validation_alias="AGENT_SANDBOX_TIMEOUT_SECONDS",
        description="Timeout for sandbox code execution",
    )


# Singleton instance
settings = Settings.model_validate({})


def aux_model() -> str:
    """Backend-coherent model for auxiliary agents (reviewer, backgrounds).

    Explicit ``AGENT_AUX_MODEL`` wins. Otherwise Claude sessions get a
    sonnet-class reviewer and Codex/OpenAI sessions reuse the session
    model — the one model the account is known to accept.
    """
    if settings.aux_model:
        return settings.aux_model
    return "claude-sonnet-4-6" if settings.agent_sdk == "claude" else settings.model


# Route notes/logs paths into lup.paths so every consumer (history,
# devtools, traces) honors the configured locations
if settings.notes_path != "./notes" or settings.logs_path != "./logs":
    from pathlib import Path

    from lup.paths import configure

    configure(
        notes_dir=Path(settings.notes_path).resolve(),
        logs_dir=Path(settings.logs_path).resolve(),
    )

# Route through OpenRouter when the key is set
if settings.openrouter_api_key:
    os.environ.setdefault("ANTHROPIC_BASE_URL", "https://openrouter.ai/api")
    os.environ.setdefault("ANTHROPIC_AUTH_TOKEN", settings.openrouter_api_key)
    os.environ.setdefault("ANTHROPIC_API_KEY", "")
    logger.info("OpenRouter enabled — routing API calls through openrouter.ai")
