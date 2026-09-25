"""Point a Claude agent at an Anthropic-compatible local endpoint."""

import asyncio

from pydantic import AnyHttpUrl, BaseModel, Field

from lup import Claude, CustomModel
from lup.providers.claude import ClaudeCompatibleEndpoint


class Summary(BaseModel, frozen=True):
    """A minimal structured result submitted by this example's agent."""

    summary: str = Field(min_length=1)


async def main() -> None:
    # The endpoint is a field of the agent rather than a transform to
    # choreograph: naming a base URL is the whole of pointing an agent
    # somewhere else, and an omitted key sends the placeholder credential a
    # local endpoint expects. The endpoint's own model id is outside Claude
    # Code's catalog, so it is named as one on purpose.
    agent = Claude(
        model=CustomModel(id="local-model"),
        system_prompt="Submit a concise structured summary.",
        endpoint=ClaudeCompatibleEndpoint(base_url=AnyHttpUrl("http://localhost:4000")),
    )
    result = await agent.ask("Confirm the compatible endpoint.", Summary)
    print(result.output.summary)


if __name__ == "__main__":
    asyncio.run(main())
