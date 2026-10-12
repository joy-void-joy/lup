"""What an adapter implements, and the seam a test's fake replaces it at.

An adapter runs one turn of a session on its runtime: it serves the toolbox's
tools, routes the model's calls to them, holds the turn open until the toolbox
lets it end, and reports the final message, the usage and the session's id. It
raises the errors in `lup.sessions.errors`, classified from what its runtime
reports in structured form.

`seam` is where an adapter is chosen. Unset, each declaration uses its runtime's
adapter; `lup.testing` sets it, to the fake in a test that asks for it and to a
refusal everywhere else, so a test never reaches a real agent.
"""

from abc import ABC, abstractmethod
from contextvars import ContextVar
from typing import TYPE_CHECKING

from pydantic import BaseModel

from lup.sessions.results import Usage
from lup.sessions.submission import Toolbox
from lup.types import Model

if TYPE_CHECKING:
    from lup.sessions.declaration import Declaration


class TurnRequest(Model, arbitrary_types_allowed=True):
    """One turn to run: the prompt, the tools the session serves, and the answer's model."""

    prompt: str
    toolbox: Toolbox
    output: type[BaseModel] | None = None
    """The model a typed turn's answer is; none for an untyped turn."""


class RawTurn(Model):
    """What an adapter reports once a turn has ended."""

    text: str
    """The final message's text."""
    usage: Usage
    session_id: str


class Adapter(ABC):
    """Runs turns on one runtime."""

    @abstractmethod
    async def run(self, request: TurnRequest) -> RawTurn:
        """Run one turn to its end, through the toolbox's guard, and report it."""


class Seam(ABC):
    """Chooses the adapter a declaration's asks run on, in place of its runtime's own."""

    @abstractmethod
    def adapter(self, declaration: Declaration) -> Adapter:
        """Return the adapter `declaration`'s next ask runs on."""


seam: ContextVar[Seam | None] = ContextVar("seam", default=None)
"""The seam in force; none runs each declaration on its runtime's own adapter."""
