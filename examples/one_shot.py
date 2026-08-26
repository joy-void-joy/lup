"""Run one typed Claude turn, from the package's own front door."""

import asyncio

from lup import create_claude

from examples.common import Summary


async def main() -> None:
    client = create_claude(
        model="claude-opus-5",
        system_prompt="Return a concise summary through submit_output.",
    )
    result = await client.query("Summarize why typed boundaries help.", Summary)
    print(result.output.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
