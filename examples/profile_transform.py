"""Resolve an immutable Claude profile transform before factory construction."""

import asyncio
from pathlib import Path

from lup.adapters.claude.config import (
    ClaudeProfileRegistry,
    ClaudeProfileResolver,
    ClaudeProfileSelection,
)
from lup.adapters.claude.runtime import (
    ClaudeSessionConfig,
    create_claude_session_factory,
)
from lup.runtime.models import TurnInput, turn_request
from lup.runtime.query import query

from examples.common import Summary


async def main() -> None:
    base = ClaudeSessionConfig(
        model="claude-opus-4-6",
        system_prompt="Submit a concise structured summary.",
    )
    registry = ClaudeProfileRegistry(
        profiles={
            "work": ClaudeProfileSelection(
                config_directory=Path.home() / ".claude-work"
            )
        },
        active="work",
    )
    selected = ClaudeProfileResolver(registry).resolve(None).apply(base)
    result = await query(
        create_claude_session_factory(selected),
        turn_request(TurnInput(text="Describe immutable configuration."), Summary),
    )
    print(result.output.summary)


if __name__ == "__main__":
    asyncio.run(main())
