"""Debounce application state into a persistent typed background session."""

import asyncio

from pydantic import BaseModel

from lup import TurnRequest, TurnResult, create_claude, turn_request
from lup.runtime.background import BackgroundAgent, BackgroundConfig
from lup.runtime.errors import TurnError

from examples.common import Summary


class DraftState(BaseModel, frozen=True):
    """Latest application state to summarize."""

    text: str

    def request(self) -> TurnRequest[Summary]:
        return turn_request(f"Summarize the latest draft:\n\n{self.text}", Summary)


async def main() -> None:
    client = create_claude(
        model="claude-opus-5",
        system_prompt="Submit a concise structured summary.",
    )
    completion = asyncio.get_running_loop().create_future()

    async def completed(result: TurnResult[Summary]) -> None:
        completion.set_result(result)

    async def failed(error: TurnError) -> None:
        completion.set_exception(error)

    agent = BackgroundAgent[DraftState, Summary](
        client,
        DraftState.request,
        completed,
        failed,
        BackgroundConfig(debounce_seconds=0.1),
    )
    await agent.start()
    try:
        agent.wake(DraftState(text="First draft"))
        agent.wake(DraftState(text="Second draft replaces the first"))
        result = await completion
        print(result.output.summary)
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
