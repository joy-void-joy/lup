"""Compose timeout, budget, retry, correction, persistence, and serialization."""

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from lup import Claude
from lup.sessions.layers import SessionLayers
from lup.sessions.middleware import (
    BudgetConfig,
    CorrectionConfig,
    PersistenceConfig,
    RecoveryConfig,
    TimeoutConfig,
)
from lup.types import Usage


class Summary(BaseModel, frozen=True):
    """A minimal structured result submitted by this example's agent."""

    summary: str = Field(min_length=1)


def reported_cost(usage: Usage) -> float:
    """Use provider-reported cost while treating an absent estimate as zero."""
    return usage.cost_usd or 0.0


async def main() -> None:
    agent = Claude(
        model="claude-opus-5",
        system_prompt="Submit a concise structured result.",
        layers=SessionLayers(
            timeout=TimeoutConfig(seconds=120),
            budget=BudgetConfig(maximum_usd=1.0, usage_cost=reported_cost),
            recovery=RecoveryConfig(retries=1),
            correction=CorrectionConfig(cycles=1),
            persistence=PersistenceConfig(directory=Path("tmp/example-results")),
            serialized=True,
        ),
    )
    result = await agent.ask("Explain this wrapper stack.", Summary)
    print(result.output.summary)


if __name__ == "__main__":
    asyncio.run(main())
