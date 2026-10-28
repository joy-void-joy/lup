"""One turn's tools, every call made to them, and whether the turn may end.

The toolbox is a `Toolset` (`lup.tools.serving`): an adapter serves its specs,
routes each call the model makes to `Toolbox.call`, and asks `Toolbox.end` when
the model tries to end its turn. The calls recorded are the one source of what
the turn said: the last accepted call to the output tool is the answer, the
refused ones are the rejections, the last `blocked` or `stop` call is why the
turn ended without one, and the `note`, `friction` and `how_it_felt` calls are
what the agent said beside it. A typed turn can't end until an answer is
accepted, or the agent is blocked or stops, which is lup's own guard, the same
on every runtime.
"""

from typing import TYPE_CHECKING

from lup.sessions.results import Friction, HowItFelt
from lup.tools.serving import Answer, Toolset
from lup.tools.speaking import (
    Problem,
    Remark,
    Stop,
    blocked,
    friction,
    how_it_felt,
    note,
    stop,
)
from lup.tools.tool import Accepted, AgentTool, Refused, ToolSpec
from lup.types import Model, MutableModel

if TYPE_CHECKING:
    from pydantic import BaseModel, JsonValue

    from lup.sessions.results import Rejection


class Call(Model):
    """One call the model made: the tool it named, and what came of it."""

    tool: str
    outcome: Accepted | Refused


class End(Model):
    """The turn may end."""


class KeepGoing(Model):
    """The turn may not end yet; `reason` is what the model reads."""

    reason: str


class GiveUp(Model):
    """No answer was accepted within the attempts allowed: the ask stops."""

    reason: str


class Toolbox(MutableModel, Toolset, arbitrary_types_allowed=True):
    """The tools one turn serves, and the calls made to them."""

    tools: list[AgentTool]
    output: str | None = None
    """The tool whose accepted call is the turn's answer; none for an untyped turn."""
    attempts: int
    """Rejected answers and refused endings allowed, together."""
    calls: list[Call] = []
    refused_endings: int = 0

    def specs(self) -> list[ToolSpec]:
        """Return what the session tells the model about each tool."""
        return [tool.spec() for tool in self.tools]

    async def call(self, name: str, arguments: JsonValue) -> Answer:
        """Run the model's call to the tool `name`, record it, and return its answer."""
        found = {tool.spec().name: tool for tool in self.tools}.get(name)
        if found is None:
            known = ", ".join(tool.spec().name for tool in self.tools)
            return Answer(
                text=f"There's no tool named {name}; the tools are: {known}.",
                error=True,
            )
        outcome = await found.call(arguments)
        self.calls = [*self.calls, Call(tool=name, outcome=outcome)]
        match outcome:
            case Accepted(answer=answer):
                return Answer(text=answer)
            case Refused(rejection=rejection):
                return Answer(text=f"Refused: {rejection.reason}", error=True)

    def taken(self, tool: str | None) -> list[BaseModel]:
        """Return the inputs the tool named `tool` accepted, oldest first."""
        return [
            call.outcome.value
            for call in self.calls
            if call.tool == tool and isinstance(call.outcome, Accepted)
        ]

    def accepted(self) -> BaseModel | None:
        """Return the last answer the output tool accepted, if any."""
        answers = self.taken(self.output)
        return answers[-1] if answers else None

    def rejected(self) -> list[Rejection]:
        """Return the output tool's refused submissions, oldest first."""
        return [
            call.outcome.rejection
            for call in self.calls
            if call.tool == self.output and isinstance(call.outcome, Refused)
        ]

    def ending(self) -> Problem | Stop | None:
        """Return why the agent ended without an answer, its last `blocked` or `stop` call, if it made one."""
        endings = [
            call.outcome.value
            for call in self.calls
            if call.tool in (blocked.name, stop.name)
            and isinstance(call.outcome, Accepted)
        ]
        last = endings[-1] if endings else None
        return last if isinstance(last, Problem | Stop) else None

    def notes(self) -> list[str]:
        """Return the remarks the agent attached to its answer, oldest first."""
        return [
            taken.remark for taken in self.taken(note.name) if isinstance(taken, Remark)
        ]

    def frictions(self) -> list[Friction]:
        """Return what got in the agent's way, oldest first."""
        return [
            taken for taken in self.taken(friction.name) if isinstance(taken, Friction)
        ]

    def how_it_felt(self) -> HowItFelt | None:
        """Return how the agent said the work went, its last if it said twice; none where it didn't."""
        said = [
            taken
            for taken in self.taken(how_it_felt.name)
            if isinstance(taken, HowItFelt)
        ]
        return said[-1] if said else None

    def end(self, prefix: str = "") -> End | KeepGoing | GiveUp:
        """Say whether the turn may end, counting a refused ending against the attempts.

        A turn may end once it's answered, or once the agent is blocked or stops.
        `prefix` is what the runtime puts before lup's tool names, so the reason
        names each tool exactly as the model sees it.
        """
        answered = self.output is None or self.accepted() is not None
        if answered or self.ending() is not None:
            return End()
        used = len(self.rejected()) + self.refused_endings
        if used >= self.attempts:
            return GiveUp(reason=f"no answer was accepted after {used} attempts")
        self.refused_endings += 1
        return KeepGoing(
            reason=(
                f"Call the `{prefix}{self.output}` tool with your final answer, "
                f"`{prefix}{blocked.name}` if it can't be answered, or "
                f"`{prefix}{stop.name}` to stop by your own choice: your turn can't "
                "end until one is accepted."
            )
        )
