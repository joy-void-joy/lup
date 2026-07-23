"""Provider-owned profile and compatible-endpoint transform tests."""

from pathlib import Path

import pytest
from pydantic import AnyHttpUrl, SecretStr

from lup.adapters.claude.config import (
    ClaudeCompatibilityTransform,
    ClaudeCompatibleEndpoint,
    ClaudeProfileRegistry,
    ClaudeProfileResolver,
    ClaudeProfileSelection,
)
from lup.adapters.claude.runtime import ClaudeSessionConfig
from lup.adapters.codex.config import (
    CodexCompatibilityTransform,
    CodexCompatibleEndpoint,
    CodexProfileRegistry,
    CodexProfileResolver,
    CodexProfileSelection,
)
from lup.adapters.codex.runtime import CodexSessionConfig
from lup.runtime.routing import (
    ExactModelMatcher,
    ModelRoute,
    ModelRouter,
    PrefixModelMatcher,
)
from tests.unit.test_background_runtime import RecordingFactory


def test_claude_profile_precedence_and_immutability(tmp_path: Path) -> None:
    registry = ClaudeProfileRegistry(
        profiles={
            "active": ClaudeProfileSelection(config_directory=tmp_path / "active"),
            "explicit": ClaudeProfileSelection(config_directory=tmp_path / "explicit"),
        },
        active="active",
        default=ClaudeProfileSelection(config_directory=tmp_path / "default"),
    )
    resolver = ClaudeProfileResolver(registry)
    original = ClaudeSessionConfig(model="claude", environment={"KEEP": "1"})

    active = resolver.resolve(None).apply(original)
    explicit = resolver.resolve("explicit").apply(original)

    assert active.environment["CLAUDE_CONFIG_DIR"] == str(tmp_path / "active")
    assert explicit.environment["CLAUDE_CONFIG_DIR"] == str(tmp_path / "explicit")
    assert explicit.environment["KEEP"] == "1"
    assert "CLAUDE_CONFIG_DIR" not in original.environment
    with pytest.raises(KeyError, match="unknown Claude profile"):
        resolver.resolve("missing")


def test_claude_compatible_endpoint_owns_auth_and_aliases() -> None:
    original = ClaudeSessionConfig(model="served-model", environment={"KEEP": "1"})
    transformed = ClaudeCompatibilityTransform(
        ClaudeCompatibleEndpoint(
            base_url=AnyHttpUrl("http://localhost:8000/v1"),
            api_key=SecretStr("secret"),
            auth_style="api_key",
        )
    ).apply(original)

    assert transformed.environment["ANTHROPIC_BASE_URL"] == ("http://localhost:8000/v1")
    assert transformed.environment["ANTHROPIC_API_KEY"] == "secret"
    assert transformed.environment["ANTHROPIC_AUTH_TOKEN"] == ""
    assert transformed.environment["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == ("served-model")
    assert "ANTHROPIC_BASE_URL" not in original.environment


def test_codex_home_and_named_overlay_remain_distinct(tmp_path: Path) -> None:
    resolver = CodexProfileResolver(
        CodexProfileRegistry(
            profiles={
                "work": CodexProfileSelection(
                    codex_home=tmp_path / "account",
                    named_profile="fast",
                )
            },
            active="work",
        )
    )
    original = CodexSessionConfig(model="gpt", cwd=tmp_path)
    transformed = resolver.resolve(None).apply(original)

    assert transformed.environment["CODEX_HOME"] == str(tmp_path / "account")
    assert transformed.named_profile == "fast"
    assert original.named_profile is None
    assert original.environment == {}


def test_codex_compatible_endpoint_uses_structured_provider_config(
    tmp_path: Path,
) -> None:
    original = CodexSessionConfig(model="local", cwd=tmp_path)
    transformed = CodexCompatibilityTransform(
        CodexCompatibleEndpoint(
            identifier="local_provider",
            base_url=AnyHttpUrl("http://localhost:8000/v1"),
            api_key=SecretStr("secret"),
        )
    ).apply(original)

    assert transformed.model_provider == "local_provider"
    assert transformed.environment["LUP_OPENAI_COMPAT_API_KEY"] == "secret"
    assert transformed.provider_config == {
        "model_provider": "local_provider",
        "model_providers": {
            "local_provider": {
                "name": "local_provider",
                "base_url": "http://localhost:8000/v1",
                "env_key": "LUP_OPENAI_COMPAT_API_KEY",
            }
        },
    }
    assert original.provider_config is None


def test_model_router_uses_explicit_recipe_then_first_match() -> None:
    broad = RecordingFactory()
    exact = RecordingFactory()
    router = ModelRouter(
        [
            ModelRoute(
                name="broad",
                matcher=PrefixModelMatcher("model-"),
                recipe=lambda: broad,
            ),
            ModelRoute(
                name="exact",
                matcher=ExactModelMatcher("model-special"),
                recipe=lambda: exact,
            ),
        ]
    )

    assert router.resolve("model-special") is broad
    assert router.resolve("unmatched", recipe="exact") is exact
    with pytest.raises(LookupError, match="unknown factory recipe"):
        router.resolve("model-special", recipe="missing")
    with pytest.raises(LookupError, match="no configured route"):
        router.resolve("other")
