"""Claude-specific profile and compatible-endpoint transforms."""

from pathlib import Path

from pydantic import BaseModel, Field

from lup.providers.claude import Claude, ClaudeCompatibleEndpoint
from lup.providers.claude.runtime import create_claude
from lup.providers.claude.login import CLAUDE_LOGIN
from lup.providers.config import ConfigTransform, ProfileResolver, ProfileSelector

PLACEHOLDER_CREDENTIAL = "dummy"


class ClaudeProfileSelection(BaseModel, frozen=True):
    """One complete Claude account/configuration home."""

    config_directory: Path | None = None
    """The configuration home a session is pointed at, or ``None`` for
    whichever one its environment already selects.

    ``None`` rather than ``~/.claude``, because naming that directory is not
    the selection naming none makes: Claude Code then reads
    ``~/.claude/.claude.json`` instead of the ``~/.claude.json`` beside it, and
    a session opened that way starts from a document the account never wrote.
    """


class ClaudeProfileRegistry(BaseModel, frozen=True):
    """Immutable account selection state supplied by an application."""

    profiles: dict[str, ClaudeProfileSelection] = {}
    active: str | None = None
    default: ClaudeProfileSelection = Field(default_factory=ClaudeProfileSelection)


class ClaudeConfigDirectoryTransform(ConfigTransform[Claude]):
    """Select a Claude config home without mutating the source config."""

    def __init__(self, selection: ClaudeProfileSelection) -> None:
        self.selection = selection

    def apply(self, config: Claude) -> Claude:
        environment = dict(config.environment)
        if self.selection.config_directory is not None:
            environment.update(
                CLAUDE_LOGIN.environment(self.selection.config_directory)
            )
        return config.model_copy(update={"environment": environment})


class ClaudeProfileResolver(ProfileResolver[Claude]):
    """Resolve explicit, active, then default Claude account selection."""

    def __init__(self, registry: ClaudeProfileRegistry) -> None:
        self.registry = registry

    def resolve(self, name: str | None) -> ConfigTransform[Claude]:
        selected = name or self.registry.active
        if selected is None:
            return ClaudeConfigDirectoryTransform(self.registry.default)
        try:
            profile = self.registry.profiles[selected]
        except KeyError as error:
            raise KeyError(f"unknown Claude profile {selected!r}") from error
        return ClaudeConfigDirectoryTransform(profile)


# The registry declares which account is selected; naming the resolver and the
# session factory that act on it would put both inside the declaration.
def claude_profile_selector(
    registry: ClaudeProfileRegistry,
) -> ProfileSelector[Claude]:
    """The surface a consumer holds over Claude account selection."""
    return ProfileSelector(ClaudeProfileResolver(registry), create_claude)


class ClaudeCompatibilityTransform(ConfigTransform[Claude]):
    """Point Claude scaffolding at one compatible endpoint."""

    def __init__(self, endpoint: ClaudeCompatibleEndpoint) -> None:
        self.endpoint = endpoint

    def apply(self, config: Claude) -> Claude:
        environment = dict(config.environment)
        environment["ANTHROPIC_BASE_URL"] = str(self.endpoint.base_url)
        credential = (
            self.endpoint.api_key.get_secret_value()
            if self.endpoint.api_key is not None
            else PLACEHOLDER_CREDENTIAL
        )
        if self.endpoint.auth_style == "auth_token":
            environment["ANTHROPIC_AUTH_TOKEN"] = credential
            environment["ANTHROPIC_API_KEY"] = ""
        else:
            environment["ANTHROPIC_API_KEY"] = credential
            environment["ANTHROPIC_AUTH_TOKEN"] = ""
        model = config.model_id()
        if self.endpoint.map_model_aliases and model is not None:
            environment.update(
                {
                    "ANTHROPIC_DEFAULT_FABLE_MODEL": model,
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
                    "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
                }
            )
        environment.update(
            {
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "DISABLE_TELEMETRY": "1",
                "DISABLE_ERROR_REPORTING": "1",
                "DISABLE_BUG_COMMAND": "1",
            }
        )
        return config.model_copy(update={"environment": environment})
