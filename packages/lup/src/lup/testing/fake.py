"""The fake: it replaces the adapter, not the agent, and answers from a script.

A test's declaration goes through the real `ask`: its layers, the output tool
and its guard, the record. Only the turn is scripted. A typed answer is submitted
through the real output tool, so validation and its `before` hooks run as they
would on a real turn.

    fake_agents.answer(Translations, Translations(lines=["Bonjour"]))
    result = await translate(segment)
    assert fake_agents.calls[0].prompt == segment.model_dump_json()
"""

from pydantic import BaseModel, JsonValue

from lup.errors import LupError
from lup.sessions.contract import Adapter, RawTurn, Seam, TurnRequest
from lup.sessions.declaration import Declaration
from lup.sessions.results import Usage
from lup.types import Model, MutableModel


class UnscriptedAskError(LupError):
    """A test asked an agent for something its fake has no script for."""


class Submitting(Model):
    """Submit each of these to the output tool in turn, as the agent would."""

    submissions: list[JsonValue]


class Texting(Model):
    """Answer an untyped ask with this text."""

    text: str


class Failing(Model, arbitrary_types_allowed=True):
    """Fail the ask with this error, as the runtime would."""

    error: Exception


class Queued(Model, arbitrary_types_allowed=True):
    """A script waiting for the next ask of its output model, or of text."""

    output: type[BaseModel] | None
    script: Submitting | Texting | Failing


class FakeCall(Model, arbitrary_types_allowed=True):
    """One ask the fake answered: the declaration asked, the prompt, the answer's model."""

    declaration: Declaration
    prompt: str
    output: type[BaseModel] | None
    """The answer's model; none for an untyped ask."""


class FakeAgents(MutableModel, Seam, arbitrary_types_allowed=True):
    """Scripted answers for a test's asks, and every ask made, in order."""

    queued: list[Queued] = []
    calls: list[FakeCall] = []

    def answer[T: BaseModel](self, output: type[T], value: T) -> None:
        """Queue `value` as the accepted answer to the next ask for `output`."""
        self.queue(output, Submitting(submissions=[value.model_dump(mode="json")]))

    def answer_text(self, text: str) -> None:
        """Queue `text` as the answer to the next untyped ask."""
        self.queue(None, Texting(text=text))

    def reject_then[T: BaseModel](
        self, output: type[T], invalid: JsonValue, value: T
    ) -> None:
        """Queue a submission the output tool refuses, then `value`, for the next ask for `output`.

        `invalid` is what the agent submits first, such as arguments that don't
        validate, or a value a `before` hook denies.
        """
        submissions: list[JsonValue] = [invalid, value.model_dump(mode="json")]
        self.queue(output, Submitting(submissions=submissions))

    def fail(self, output: type[BaseModel] | None, error: Exception) -> None:
        """Make the next ask for `output`, or the next untyped one for none, raise `error`."""
        self.queue(output, Failing(error=error))

    def queue(
        self, output: type[BaseModel] | None, script: Submitting | Texting | Failing
    ) -> None:
        """Queue `script` for the next ask of `output`."""
        self.queued = [*self.queued, Queued(output=output, script=script)]

    def adapter(self, declaration: Declaration) -> Adapter:
        """Return the fake adapter `declaration`'s next ask runs on."""
        return FakeAdapter(agents=self, declaration=declaration)

    def take(self, output: type[BaseModel] | None, prompt: str) -> Submitting | Texting | Failing:
        """Remove and return the first script queued for `output`, or raise naming the ask."""
        matching = [each for each in self.queued if each.output is output]
        if not matching:
            name = "text" if output is None else output.__name__
            message = (
                f"nothing is scripted for an ask of {name}; the prompt was: {prompt}\n"
                "Script one with `fake_agents.answer`, `answer_text`, `reject_then` or `fail`."
            )
            raise UnscriptedAskError(message)
        [first, *_] = matching
        self.queued = [each for each in self.queued if each is not first]
        return first.script


class FakeAdapter(Model, Adapter, arbitrary_types_allowed=True):
    """Runs a turn from the fake's script, through the real toolbox."""

    agents: FakeAgents
    declaration: Declaration

    async def run(self, request: TurnRequest) -> RawTurn:
        """Answer the turn from the next script queued for its output model."""
        agents = self.agents
        call = FakeCall(
            declaration=self.declaration, prompt=request.prompt, output=request.output
        )
        agents.calls = [*agents.calls, call]
        session = f"fake-{len(agents.calls)}"
        match agents.take(request.output, request.prompt):
            case Failing(error=error):
                raise error
            case Texting(text=text):
                return RawTurn(text=text, usage=Usage(), session_id=session)
            case Submitting(submissions=submissions):
                toolbox = request.toolbox
                for submission in submissions:
                    await toolbox.call(toolbox.output or "", submission)
                toolbox.end()
                return RawTurn(text="", usage=Usage(), session_id=session)
