"""Route a model name to one explicit, fully configured factory recipe."""

import asyncio
from pathlib import Path

from lup.adapters.claude.runtime import (
    ClaudeSessionConfig,
    create_claude_session_factory,
)
from lup.adapters.codex.runtime import CodexSessionConfig, create_codex_session_factory
from lup.runtime.contracts import SessionFactory
from lup.runtime.models import TurnInput, turn_request
from lup.runtime.query import query
from lup.runtime.routing import ModelRoute, ModelRouter, PrefixModelMatcher

from examples.common import Summary

MODEL = "claude-opus-4-6"


def claude_factory() -> SessionFactory:
    return create_claude_session_factory(
        ClaudeSessionConfig(
            model=MODEL,
            system_prompt="Submit a concise structured summary.",
        )
    )


def codex_factory() -> SessionFactory:
    return create_codex_session_factory(
        CodexSessionConfig(
            model="gpt-5.5",
            developer_instructions="Submit a concise structured summary.",
            cwd=Path.cwd(),
        )
    )


async def main() -> None:
    router = ModelRouter(
        [
            ModelRoute(
                name="claude",
                matcher=PrefixModelMatcher("claude-"),
                recipe=claude_factory,
            ),
            ModelRoute(
                name="codex",
                matcher=PrefixModelMatcher("gpt-"),
                recipe=codex_factory,
            ),
        ]
    )
    result = await query(
        router.resolve(MODEL),
        turn_request(TurnInput(text="Explain explicit model routing."), Summary),
    )
    print(result.output.summary)


if __name__ == "__main__":
    asyncio.run(main())
