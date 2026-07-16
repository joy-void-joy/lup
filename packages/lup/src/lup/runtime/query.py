"""The small typed one-turn convenience operation."""

from pydantic import BaseModel

from lup.runtime.contracts import SessionFactory
from lup.runtime.models import TurnRequest, TurnResult


async def query[T: BaseModel | None](
    factory: SessionFactory, request: TurnRequest[T]
) -> TurnResult[T]:
    """Open one session, run one turn, and always close the session."""
    async with factory.open() as handle:
        turn = await handle.session.start(request)
        return await turn.turn.result()
