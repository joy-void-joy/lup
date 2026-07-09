"""Background dispatch behavior across engines.

An engine must fail loudly where its backend cannot honor a request —
silently dropping tools was how the Codex path shipped broken before.
"""

import pytest

from lup.adapters.background.BackgroundDriver import BackgroundAgentParams
from lup.adapters.wiring import resolve_engine


def build_message() -> str | None:
    return None


class TestEngineBackground:
    def test_codex_rejects_tools(self) -> None:
        with pytest.raises(ValueError, match="cannot use tools"):
            resolve_engine("codex").background(
                BackgroundAgentParams(
                    name="observer",
                    system_prompt="summarize",
                    build_message=build_message,
                    builtin_tools=["Read"],
                )
            )

    def test_codex_requires_explicit_model(self) -> None:
        with pytest.raises(ValueError, match="explicit model"):
            resolve_engine("codex").background(
                BackgroundAgentParams(
                    name="observer",
                    system_prompt="summarize",
                    build_message=build_message,
                )
            )

    def test_unknown_engine_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown engine"):
            resolve_engine("gemini")

    def test_compat_engines_delegate_their_base_background(self) -> None:
        """The compat engines build through their composed base engine."""
        params = BackgroundAgentParams(
            name="observer",
            system_prompt="summarize",
            build_message=build_message,
        )
        compat_agent = resolve_engine("claude-compat").background(params)
        base_agent = resolve_engine("claude").background(params)
        assert type(compat_agent.driver) is type(base_agent.driver)

        # Codex-side validation reaches through openai-compat's delegation.
        with pytest.raises(ValueError, match="explicit model"):
            resolve_engine("openai-compat").background(params)
