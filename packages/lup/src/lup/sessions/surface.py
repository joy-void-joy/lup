"""`Agent`: what code that shouldn't care which runtime it gets holds.

Every declaration is an `Agent`, as is anything else a project writes to stand in
for one, so a function can take an agent without naming its runtime.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, overload

from pydantic import BaseModel

if TYPE_CHECKING:
    from lup.sessions.results import TurnResult
    from lup.tools.submit import Submit


class Agent(ABC):
    """An agent that answers a prompt, typed or as text."""

    @overload
    # lup: ignore("interface-shape", why="an overload is a signature, not behaviour (#47)")
    async def ask(self, prompt: str, output: None = None) -> TurnResult[str]: ...

    @overload
    # lup: ignore("interface-shape", why="an overload is a signature, not behaviour (#47)")
    async def ask[T: BaseModel](
        self, prompt: str, output: type[T] | Submit[T]
    ) -> TurnResult[T]: ...

    @abstractmethod
    async def ask[T: BaseModel](
        self, prompt: str, output: type[T] | Submit[T] | None = None
    ) -> TurnResult[T] | TurnResult[str]:
        """Ask `prompt`, and return the answer: an `output` model, or text without one.

        `output` is a model type, which gets the default output tool, or an output
        tool built with hooks that review the answer before it's accepted.
        """
