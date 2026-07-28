"""Run one typed Claude turn with the small ``query`` convenience API."""

import asyncio

from lup.adapters.claude.runtime import (
    ClaudeSessionConfig,
    create_claude_session_factory,
)
from lup.runtime.models import TurnInput, turn_request
from lup.runtime.query import query

from examples.common import Summary


async def main() -> None:
    factory = create_claude_session_factory(
        ClaudeSessionConfig(
            model="claude-opus-5",
            system_prompt="Return a concise summary through submit_output.",
        )
    )
    result = await query(
        factory,  # lup: Shouldn't it be factory.query? I find it a bit bulky with turn_request(TurnInput) too
        turn_request(TurnInput(text="Summarize why typed boundaries help."), Summary),
    )
    print(result.output.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
