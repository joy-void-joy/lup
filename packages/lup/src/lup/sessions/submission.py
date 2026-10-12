"""One turn's tools, every call made to them, and whether the turn may end.

An adapter serves the toolbox's specs, routes each call the model makes to
`Toolbox.call`, and asks `Toolbox.end` when the model tries to end its turn. The
calls recorded are the one source of the answer: the last accepted call to the
output tool is it, and the refused ones are the rejections. A typed turn can't end
until an answer is accepted, which is lup's own guard, the same on every runtime.
"""

from typing import TYPE_CHECKING

from lup.tools.tool import Accepted, AgentTool, Refused, ToolSpec
from lup.types import Model, MutableModel

if TYPE_CHECKING:
    from pydantic import BaseModel, JsonValue

    from lup.sessions.results import Rejection


class Answer(Model):
    """What a tool call returns to the model."""

    text: str
    error: bool = False


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


class Toolbox(MutableModel, arbitrary_types_allowed=True):
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
            return Answer(text=f"There's no tool named {name}; the tools are: {known}.", error=True)
        outcome = await found.call(arguments)
        self.calls = [*self.calls, Call(tool=name, outcome=outcome)]
        match outcome:
            case Accepted(answer=answer):
                return Answer(text=answer)
            case Refused(rejection=rejection):
                return Answer(text=f"Refused: {rejection.reason}", error=True)

    def accepted(self) -> BaseModel | None:
        """Return the last answer the output tool accepted, if any."""
        answers = [
            call.outcome.value
            for call in self.calls
            if call.tool == self.output and isinstance(call.outcome, Accepted)
        ]
        return answers[-1] if answers else None

    def rejected(self) -> list[Rejection]:
        """Return the output tool's refused submissions, oldest first."""
        return [
            call.outcome.rejection
            for call in self.calls
            if call.tool == self.output and isinstance(call.outcome, Refused)
        ]

    def end(self) -> End | KeepGoing | GiveUp:
        """Say whether the turn may end, counting a refused ending against the attempts."""
        if self.output is None or self.accepted() is not None:
            return End()
        used = len(self.rejected()) + self.refused_endings
        if used >= self.attempts:
            return GiveUp(reason=f"no answer was accepted after {used} attempts")
        self.refused_endings += 1
        return KeepGoing(
            reason=(
                f"Call the `{self.output}` tool with your final answer: "
                "your turn can't end until an answer is accepted."
            )
        )
