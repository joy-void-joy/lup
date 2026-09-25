"""Resolve a Claude profile onto the agent it configures."""

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from lup import Claude
from lup.providers.claude.config import (
    ClaudeProfileRegistry,
    ClaudeProfileSelection,
    claude_profile_selector,
)


class Summary(BaseModel, frozen=True):
    """A minimal structured result submitted by this example's agent."""

    summary: str = Field(min_length=1)


async def main() -> None:
    base = Claude(
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
    agent = claude_profile_selector(registry).session_factory(base)
    result = await agent.ask("Describe immutable configuration.", Summary)
    print(result.output.summary)


if __name__ == "__main__":
    asyncio.run(main())
