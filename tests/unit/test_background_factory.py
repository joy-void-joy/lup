"""Background factory behavior across SDKs.

The factory must fail loudly where a backend cannot honor a request —
silently dropping tools was how the Codex path shipped broken before.
"""

import pytest

from lup.adapters.background.common import create_background_agent


def build_message() -> str | None:
    return None


class TestCreateBackgroundAgent:
    def test_codex_rejects_tools(self) -> None:
        with pytest.raises(ValueError, match="cannot use tools"):
            create_background_agent(
                "codex",
                name="observer",
                system_prompt="summarize",
                build_message=build_message,
                builtin_tools=["Read"],
            )

    def test_codex_requires_explicit_model(self) -> None:
        with pytest.raises(ValueError, match="explicit model"):
            create_background_agent(
                "codex",
                name="observer",
                system_prompt="summarize",
                build_message=build_message,
            )

    def test_unknown_sdk_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown engine"):
            create_background_agent(
                "gemini",
                name="observer",
                system_prompt="summarize",
                build_message=build_message,
            )
