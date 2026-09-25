"""Codex-specific profile and compatible-endpoint transforms."""

from pathlib import Path

from pydantic import BaseModel, Field

from lup.providers.codex.login import CODEX_LOGIN
from lup.providers.codex import Codex, CodexCompatibleEndpoint
from lup.providers.config import ConfigTransform, ProfileResolver, ProfileSelector


class CodexProfileSelection(BaseModel, frozen=True):
    """One Codex account home, or ``None`` for whichever the environment selects."""

    codex_home: Path | None = None


class CodexProfileRegistry(BaseModel, frozen=True):
    """Immutable Codex profile selection supplied by an application."""

    profiles: dict[str, CodexProfileSelection] = {}
    active: str | None = None
    default: CodexProfileSelection = Field(default_factory=CodexProfileSelection)


class CodexProfileTransform(ConfigTransform[Codex]):
    """Select a Codex account home without mutating the source config."""

    def __init__(self, selection: CodexProfileSelection) -> None:
        self.selection = selection

    def apply(self, config: Codex) -> Codex:
        environment = dict(config.environment)
        if self.selection.codex_home is not None:
            environment.update(CODEX_LOGIN.environment(self.selection.codex_home))
        return config.model_copy(update={"environment": environment})


class CodexProfileResolver(ProfileResolver[Codex]):
    """Resolve explicit, active, then default Codex profile selection."""

    def __init__(self, registry: CodexProfileRegistry) -> None:
        self.registry = registry

    def resolve(self, name: str | None) -> ConfigTransform[Codex]:
        selected = name or self.registry.active
        if selected is None:
            return CodexProfileTransform(self.registry.default)
        try:
            profile = self.registry.profiles[selected]
        except KeyError as error:
            raise KeyError(f"unknown Codex profile {selected!r}") from error
        return CodexProfileTransform(profile)


# The registry declares which profile is selected; naming the resolver and the
# session factory that act on it would put both inside the declaration.
def codex_profile_selector(
    registry: CodexProfileRegistry,
) -> ProfileSelector[Codex]:
    """The surface a consumer holds over Codex profile selection."""
    return ProfileSelector(CodexProfileResolver(registry))


class CodexCompatibilityTransform(ConfigTransform[Codex]):
    """Attach a structured provider definition and its credential binding."""

    def __init__(self, endpoint: CodexCompatibleEndpoint) -> None:
        self.endpoint = endpoint

    def apply(self, config: Codex) -> Codex:
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
