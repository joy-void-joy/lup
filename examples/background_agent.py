"""Debounce application state into a persistent typed background session."""

import asyncio

from pydantic import BaseModel, Field

from lup import Claude, Conversation, Turn, TurnResult
from lup.orchestration.background import BackgroundAgent, BackgroundConfig
from lup.sessions.errors import TurnError


class Summary(BaseModel, frozen=True):
    """A minimal structured result submitted by this example's agent."""

    summary: str = Field(min_length=1)


class DraftState(BaseModel, frozen=True):
    """Latest application state to summarize."""

    text: str


def summarize(session: Conversation, state: DraftState) -> Turn[Summary]:
    """Put the latest state to the session, asked as one typed turn."""
    return session.ask(f"Summarize the latest draft:\n\n{state.text}", Summary)


async def main() -> None:
    agent = Claude(
        model="claude-opus-5",
        system_prompt="Submit a concise structured summary.",
    )
    completion = asyncio.get_running_loop().create_future()

    async def completed(result: TurnResult[Summary]) -> None:
        completion.set_result(result)

    async def failed(error: TurnError) -> None:
        completion.set_exception(error)

    background = BackgroundAgent[DraftState, Summary](
        agent,
        summarize,
        completed,
        failed,
        BackgroundConfig(debounce_seconds=0.1),
    )
    await background.start()
    try:
        background.wake(DraftState(text="First draft"))
        background.wake(DraftState(text="Second draft replaces the first"))
        result = await completion
        print(result.output.summary)
    finally:
        await background.stop()


if __name__ == "__main__":
    asyncio.run(main())
