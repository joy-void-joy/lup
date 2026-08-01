"""The small typed one-turn convenience operation."""

from pydantic import BaseModel

from lup.runtime.factory import SessionFactory
from lup.runtime.models import TurnRequest, TurnResult


async def query[T: BaseModel | None](
    factory: SessionFactory, request: TurnRequest[T]
) -> TurnResult[T]:
    """Run one turn on the factory, spelled for composition-root call sites."""
    return await factory.query(request)
