"""Point the Claude client at an Anthropic-compatible local endpoint."""

import asyncio

from lup import create_claude

from examples.common import Summary


async def main() -> None:
    # The endpoint is a constructor argument rather than a transform to
    # choreograph: naming a base URL is the whole of pointing a client
    # somewhere else, and an omitted key sends the placeholder credential a
    # local endpoint expects.
    client = create_claude(
        model="local-model",
        system_prompt="Submit a concise structured summary.",
        base_url="http://localhost:4000",
    )
    result = await client.query("Confirm the compatible endpoint.", Summary)
    print(result.output.summary)


if __name__ == "__main__":
    asyncio.run(main())
