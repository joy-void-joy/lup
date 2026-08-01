"""Codex-specific profile and compatible-endpoint transforms."""

from pathlib import Path

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr

from lup.adapters.codex.runtime import (
    CodexSessionConfig,
    create_codex_session_factory,
)
from lup.runtime.config import ConfigTransform, ProfileResolver
from lup.runtime.factory import SessionFactory
from lup.types import JsonObject

OPENAI_COMPAT_API_KEY_ENV = "LUP_OPENAI_COMPAT_API_KEY"


class CodexProfileSelection(BaseModel):
    """A Codex account home and optional independently named config overlay."""

    model_config = ConfigDict(frozen=True)

    codex_home: Path | None = None
    named_profile: str | None = None


class CodexProfileRegistry(BaseModel):
    """Immutable Codex profile selection supplied by an application."""

    model_config = ConfigDict(frozen=True)

    profiles: dict[str, CodexProfileSelection] = Field(default_factory=dict)
    active: str | None = None
    default: CodexProfileSelection = Field(default_factory=CodexProfileSelection)


class CodexProfileTransform(ConfigTransform[CodexSessionConfig]):
    """Apply account-home and named-overlay inputs without conflating them."""

    def __init__(self, selection: CodexProfileSelection) -> None:
        self.selection = selection

    def apply(self, config: CodexSessionConfig) -> CodexSessionConfig:
        environment = dict(config.environment)
        if self.selection.codex_home is not None:
            environment["CODEX_HOME"] = str(self.selection.codex_home)
        return config.model_copy(
            update={
                "environment": environment,
                "named_profile": self.selection.named_profile,
            }
        )


class CodexProfileResolver(ProfileResolver[CodexSessionConfig]):
    """Resolve explicit, active, then default Codex profile selection."""

    def __init__(self, registry: CodexProfileRegistry) -> None:
        self.registry = registry

    def resolve(self, name: str | None) -> ConfigTransform[CodexSessionConfig]:
        """Resolve the selection as a transform, before any construction.

        The transform is the primitive rather than an intermediate step:
        selections compose with other config transforms and can be inspected
        or dry-run while no provider resource exists yet. Callers that only
        want the configured session use :meth:`session_factory`.
        """
        selected = name or self.registry.active
        if selected is None:
            return CodexProfileTransform(self.registry.default)
        try:
            profile = self.registry.profiles[selected]
        except KeyError as error:
            raise KeyError(f"unknown Codex profile {selected!r}") from error
        return CodexProfileTransform(profile)

    def session_factory(
        self, base: CodexSessionConfig, name: str | None = None
    ) -> SessionFactory:
        """Resolve the selection, apply it to the base config, and construct."""
        return create_codex_session_factory(self.resolve(name).apply(base))


class CodexCompatibleEndpoint(BaseModel):
    """All configuration owned by one OpenAI-compatible model provider."""

    model_config = ConfigDict(frozen=True)

    identifier: str = "lup_openai_compat"
    name: str | None = None
    base_url: AnyHttpUrl
    api_key: SecretStr | None = None
    api_key_environment: str = OPENAI_COMPAT_API_KEY_ENV

    def native_config(self) -> JsonObject:
        provider: JsonObject = {
            "name": self.name or self.identifier,
            "base_url": str(self.base_url),
        }
        if self.api_key is not None:
            provider["env_key"] = self.api_key_environment
        return {
            "model_provider": self.identifier,
            "model_providers": {self.identifier: provider},
        }


class CodexCompatibilityTransform(ConfigTransform[CodexSessionConfig]):
    """Attach a structured provider definition and its credential binding."""

    def __init__(self, endpoint: CodexCompatibleEndpoint) -> None:
        self.endpoint = endpoint

    def apply(self, config: CodexSessionConfig) -> CodexSessionConfig:
        environment = dict(config.environment)
        if self.endpoint.api_key is not None:
            environment[self.endpoint.api_key_environment] = (
                self.endpoint.api_key.get_secret_value()
            )
        return config.model_copy(
            update={
                "model_provider": self.endpoint.identifier,
                "provider_config": self.endpoint.native_config(),
                "environment": environment,
            }
        )
