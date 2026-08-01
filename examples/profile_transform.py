"""Resolve a Claude profile into its configured session factory."""

import asyncio
from pathlib import Path

from lup.adapters.claude.config import (
    ClaudeProfileRegistry,
    ClaudeProfileResolver,
    ClaudeProfileSelection,
)
from lup.adapters.claude.runtime import ClaudeSessionConfig
from lup.runtime.models import TurnInput, turn_request

from examples.common import Summary


async def main() -> None:
    base = ClaudeSessionConfig(
        model="claude-opus-5",
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
    factory = ClaudeProfileResolver(registry).session_factory(base)
    result = await factory.query(
        turn_request(TurnInput(text="Describe immutable configuration."), Summary)
    )
    print(result.output.summary)


if __name__ == "__main__":
    asyncio.run(main())
