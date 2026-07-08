"""Background dispatch behavior across engines.

An engine must fail loudly where its backend cannot honor a request —
silently dropping tools was how the Codex path shipped broken before.
"""

import pytest

from lup.adapters.background.Background import BackgroundAgentParams
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

    def test_compat_engines_inherit_their_base_background(self) -> None:
        """The compat engines run their base engine's background builder."""
        claude_like = type(resolve_engine("claude-compat"))
        codex_like = type(resolve_engine("openai-compat"))
        assert claude_like.background is type(resolve_engine("claude")).background
        assert codex_like.background is type(resolve_engine("codex")).background
