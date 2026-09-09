"""Run one typed Claude turn, from the package's own front door."""

import asyncio

from pydantic import BaseModel, Field

from lup import create_claude


class Summary(BaseModel, frozen=True):
    """A minimal structured result submitted by this example's agent."""

    summary: str = Field(min_length=1)


async def main() -> None:
    client = create_claude(
        model="claude-opus-5",
        system_prompt="Return a concise summary through submit_output.",
    )
    result = await client.query("Summarize why typed boundaries help.", Summary)
    print(result.output.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
