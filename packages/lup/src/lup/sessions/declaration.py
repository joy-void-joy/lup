"""The fields every declaration has, its two compilations, and `ask`: the layers around the adapter.

A declaration compiles two ways (`DESIGN.md`, *Calling agents from code*): to its runtime's SDK
for an ask from code, and to its runtime's CLI for a terminal (`terminal`, in
`lup.sessions.terminal`'s terms). Each runtime's declaration is a `Declaration`,
which is an `Agent`, and answers `ask` through `Asking`, which runs the turn on the
adapter the seam chooses (its own runtime's, unless a test's fake stands in),
inside the declaration's layers:
- the timeout bounds the whole ask, and interrupts the turn when it passes;
- recovery retries an unavailable runtime, each attempt a fresh turn;
- submission: a typed ask's turn runs through the output tool and its guard,
  and an ask whose turn ended without an accepted answer raises;
- the trace keeps the ask's record, answered or failed.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar, TypeGuard

from pydantic import BaseModel
from tenacity import AsyncRetrying, retry_if_exception_type

from lup.observability.trace import Answered, Asked
from lup.sessions.contract import Adapter, RawTurn, TurnRequest, seam
from lup.sessions.errors import (
    AgentUnavailableError,
    OutputMissingError,
    ProblemReportedError,
    TurnTimeoutError,
)
from lup.sessions.layers import SessionLayers
from lup.sessions.results import TurnResult
from lup.sessions.submission import Toolbox
from lup.sessions.surface import Agent
from lup.tools.speaking import note, report
from lup.tools.submit import Submit
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from lup.sessions.terminal import Terminal, TerminalSettings
    from lup.tools.tool import AgentTool


class Declaration(Model, Agent, ABC):
    """The fields every agent's declaration has, whatever its runtime, and its compilation for a terminal."""

    runtime: ClassVar[str]
    """The runtime's name, as records and errors give it."""
    model: str | None = None
    """The runtime's model id, passed as given.

    None leaves it to the runtime: in a terminal, the person's own settings
    choose, and in an ask, the runtime's default, since an ask loads none of
    their settings.
    """
    system_prompt: str | None = None
    """Replaces the runtime's own system prompt.

    In an ask, none sends no prompt of lup's own, and either way the runtime's own
    prompt is left out, though a runtime may still add a line of its own. In a
    terminal, none keeps the runtime's own prompt.
    """
    layers: SessionLayers = SessionLayers()

    @abstractmethod
    def terminal(self, settings: TerminalSettings) -> Terminal:
        """Compile the declaration for a terminal: its runtime's CLI, with lup's settings.

        The model and effort are spelled as the runtime spells them, each only
        where the declaration gives it, so the person's own choice holds. A terminal
        session is the runtime's coding agent, which an empty prompt would leave
        without its tools' guidance, so with no `system_prompt` it keeps its own.
        """


class Ran(Model):
    """A turn that ended: what the adapter reported, and the toolbox it ran with."""

    raw: RawTurn
    toolbox: Toolbox


class Asking(Model, arbitrary_types_allowed=True):
    """One declaration's ask, on the adapter the seam chooses, inside its layers."""

    declaration: Declaration
    runtime_adapter: Adapter
    """The declaration's own runtime's adapter, used where no seam is set."""

    async def ask[T: BaseModel](
        self, prompt: str, output: type[T] | Submit[T] | None
    ) -> TurnResult[T] | TurnResult[str]:
        """Ask `prompt`, typed through `output`'s tool, or as text without one."""
        asked = Asked(
            runtime=self.declaration.runtime,
            model=self.declaration.model,
            system_prompt=self.declaration.system_prompt,
            prompt=prompt,
            started_at=datetime.now(UTC),
        )
        began = time.monotonic()
        if output is None:
            return await self.recorded(asked, began, self.text(prompt, began))
        return await self.recorded(asked, began, self.typed(prompt, output, began))

    async def recorded[R: BaseModel | str](
        self, asked: Asked, began: float, asking: Awaitable[TurnResult[R]]
    ) -> TurnResult[R]:
        """Await `asking`, and keep its record in the trace, answered or failed."""
        trace = self.declaration.layers.trace
        try:
            result = await asking
        except Exception as failed:
            if trace is not None:
                asked.failed(failed, elapsed(began)).append(trace)
            raise
        if trace is not None:
            asked.answered(Answered.of(result)).append(trace)
        return result

    async def typed[T: BaseModel](
        self, prompt: str, output: type[T] | Submit[T], began: float
    ) -> TurnResult[T]:
        """Ask for an answer of `output`'s model, through its tool and guard."""
        submit = Submit(output) if isinstance(output, type) else output
        ran = await self.run(prompt, submit)
        answer = ran.toolbox.accepted()
        rejected = ran.toolbox.rejected()
        if answers(answer, submit.input):
            return TurnResult[T](
                output=answer,
                usage=ran.raw.usage,
                duration=elapsed(began),
                session_id=ran.raw.session_id,
                rejected=rejected,
                notes=ran.toolbox.notes(),
            )
        attempts = len(rejected) + ran.toolbox.refused_endings
        message = f"no answer was accepted after {attempts} attempts"
        raise OutputMissingError(
            message,
            rejected=rejected,
            notes=ran.toolbox.notes(),
            usage=ran.raw.usage,
        )

    async def text(self, prompt: str, began: float) -> TurnResult[str]:
        """Ask for an answer as the final message's text."""
        ran = await self.run(prompt, None)
        return TurnResult[str](
            output=ran.raw.text,
            usage=ran.raw.usage,
            duration=elapsed(began),
            session_id=ran.raw.session_id,
            notes=ran.toolbox.notes(),
        )

    async def run[T: BaseModel](self, prompt: str, submit: Submit[T] | None) -> Ran:
        """Run one turn inside the timeout and recovery layers, retrying an unavailable runtime.

        Every turn serves `report` and `note`; a typed one serves `submit`, the
        output tool, too. A turn that ended with a reported problem raises it.
        """
        layers = self.declaration.layers
        chosen = seam.get()
        adapter = (
            self.runtime_adapter if chosen is None else chosen.adapter(self.declaration)
        )
        speaking: list[AgentTool] = [report, note]

        async def once() -> Ran:
            toolbox = Toolbox(
                tools=speaking if submit is None else [*speaking, submit],
                output=None if submit is None else submit.name,
                attempts=layers.submission.attempts,
            )
            request = TurnRequest(
                prompt=prompt,
                toolbox=toolbox,
                output=None if submit is None else submit.input,
            )
            raw = await adapter.run(request)
            return Ran(raw=raw, toolbox=toolbox)

        retrying = AsyncRetrying(
            stop=layers.recovery.stop,
            wait=layers.recovery.wait,
            retry=retry_if_exception_type(AgentUnavailableError),
            reraise=True,
        )
        seconds = None if layers.timeout is None else layers.timeout.total_seconds()
        try:
            async with asyncio.timeout(seconds):
                ran: Ran = await retrying(once)
        except TimeoutError as passed:
            message = f"the ask didn't finish within {layers.timeout}"
            raise TurnTimeoutError(message) from passed
        problem = ran.toolbox.reported()
        if problem is not None:
            raise ProblemReportedError(
                problem, notes=ran.toolbox.notes(), usage=ran.raw.usage
            )
        return ran


def elapsed(began: float) -> timedelta:
    """Return the time since `began`, a reading of the monotonic clock."""
    return timedelta(seconds=time.monotonic() - began)


def answers[T: BaseModel](answer: BaseModel | None, model: type[T]) -> TypeGuard[T]:
    """Say whether the accepted `answer` is an instance of the output `model`."""
    return isinstance(answer, model)
