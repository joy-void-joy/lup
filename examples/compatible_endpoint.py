"""Point the Claude client at an Anthropic-compatible local endpoint."""

import asyncio

from pydantic import BaseModel, Field

from lup import CustomModel, create_claude


class Summary(BaseModel, frozen=True):
    """A minimal structured result submitted by this example's agent."""

    summary: str = Field(min_length=1)


async def main() -> None:
    # The endpoint is a constructor argument rather than a transform to
    # choreograph: naming a base URL is the whole of pointing a client
    # somewhere else, and an omitted key sends the placeholder credential a
    # local endpoint expects. The endpoint's own model id is outside Claude
    # Code's catalog, so it is named as one on purpose.
    client = create_claude(
        model=CustomModel(id="local-model"),
        system_prompt="Submit a concise structured summary.",
        base_url="http://localhost:4000",
    )
    result = await client.query("Confirm the compatible endpoint.", Summary)
    print(result.output.summary)


if __name__ == "__main__":
    asyncio.run(main())
