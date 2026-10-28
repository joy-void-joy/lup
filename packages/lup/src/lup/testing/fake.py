"""The fake: it replaces the adapter, not the agent, and answers from a script.

A test's declaration goes through the real `ask`: its layers, the output tool
and its guard, the record. Only the turn is scripted. A typed answer, and what
the agent says beside it or instead (a note, a friction, how it felt, being
blocked, stopping), go through the real tools, so validation and `before` hooks
run as they would on a real turn.

    fake_agents.answer(Translations, Translations(lines=["Bonjour"]))
    result = await translate(segment)
    assert fake_agents.calls[0].prompt == segment.model_dump_json()
"""

from pydantic import BaseModel, JsonValue

from lup.errors import LupError
from lup.sessions.contract import Adapter, RawTurn, Seam, TurnRequest
from lup.sessions.declaration import Declaration
from lup.sessions.results import Friction, HowItFelt, Usage
from lup.tools.speaking import blocked, friction, how_it_felt, note, stop
from lup.types import Model, MutableModel


class UnscriptedAskError(LupError):
    """A test asked an agent for something its fake has no script for."""


class Saying(Model):
    """What the agent says beside its answer, before giving it, as it would call each tool."""

    notes: list[str] = []
    frictions: list[Friction] = []
    how_it_felt: HowItFelt | None = None


class Submitting(Saying):
    """Submit each of these to the output tool in turn, as the agent would."""

    submissions: list[JsonValue]


class Texting(Saying):
    """Answer an untyped ask with this text."""

    text: str


class Blocking(Saying):
    """Say the work can't go on, with this problem, instead of answering."""

    problem: str


class Stopping(Saying):
    """Stop by choice, saying this, instead of answering."""

    why: str


class Failing(Model, arbitrary_types_allowed=True):
    """Fail the ask with this error, as the runtime would."""

    error: Exception


type Script = Submitting | Texting | Blocking | Stopping | Failing


class Queued(Model, arbitrary_types_allowed=True):
    """A script waiting for the next ask of its output model, or of text."""

    output: type[BaseModel] | None
    script: Script


class FakeCall(Model, arbitrary_types_allowed=True):
    """One ask the fake answered: the declaration asked, the prompt, the answer's model."""

    declaration: Declaration
    prompt: str
    output: type[BaseModel] | None
    """The answer's model; none for an untyped ask."""


class FakeAgents(MutableModel, Seam, arbitrary_types_allowed=True):
    """Scripted answers for a test's asks, and every ask made, in order.

    Each script but `fail` takes what the agent says before it: `notes`,
    `frictions` and `how_it_felt`.
    """

    queued: list[Queued] = []
    calls: list[FakeCall] = []

    def answer[T: BaseModel](
        self,
        output: type[T],
        value: T,
        *,
        notes: list[str] | None = None,
        frictions: list[Friction] | None = None,
        how_it_felt: HowItFelt | None = None,
    ) -> None:
        """Queue `value` as the accepted answer to the next ask for `output`, after what the agent says."""
        submitting = Submitting(
            submissions=[value.model_dump(mode="json")],
            notes=notes or [],
            frictions=frictions or [],
            how_it_felt=how_it_felt,
        )
        self.queue(output, submitting)

    def answer_text(
        self,
        text: str,
        *,
        notes: list[str] | None = None,
        frictions: list[Friction] | None = None,
        how_it_felt: HowItFelt | None = None,
    ) -> None:
        """Queue `text` as the answer to the next untyped ask, after what the agent says."""
        texting = Texting(
            text=text,
            notes=notes or [],
            frictions=frictions or [],
            how_it_felt=how_it_felt,
        )
        self.queue(None, texting)

    def reject_then[T: BaseModel](
        self, output: type[T], invalid: JsonValue, value: T
    ) -> None:
        """Queue a submission the output tool refuses, then `value`, for the next ask for `output`.

        `invalid` is what the agent submits first, such as arguments that don't
        validate, or a value a `before` hook denies.
        """
        submissions: list[JsonValue] = [invalid, value.model_dump(mode="json")]
        self.queue(output, Submitting(submissions=submissions))

    def blocked(
        self,
        output: type[BaseModel] | None,
        problem: str,
        *,
        notes: list[str] | None = None,
        frictions: list[Friction] | None = None,
        how_it_felt: HowItFelt | None = None,
    ) -> None:
        """Queue the agent saying it's blocked, instead of an answer, for the next ask of `output`."""
        blocking = Blocking(
            problem=problem,
            notes=notes or [],
            frictions=frictions or [],
            how_it_felt=how_it_felt,
        )
        self.queue(output, blocking)

    def stop(
        self,
        output: type[BaseModel] | None,
        why: str,
        *,
        notes: list[str] | None = None,
        frictions: list[Friction] | None = None,
        how_it_felt: HowItFelt | None = None,
    ) -> None:
        """Queue the agent stopping by choice, instead of an answer, for the next ask of `output`."""
        stopping = Stopping(
            why=why,
            notes=notes or [],
            frictions=frictions or [],
            how_it_felt=how_it_felt,
        )
        self.queue(output, stopping)

    def fail(self, output: type[BaseModel] | None, error: Exception) -> None:
        """Make the next ask for `output`, or the next untyped one for none, raise `error`."""
        self.queue(output, Failing(error=error))

    def queue(self, output: type[BaseModel] | None, script: Script) -> None:
        """Queue `script` for the next ask of `output`."""
        self.queued = [*self.queued, Queued(output=output, script=script)]

    def adapter(self, declaration: Declaration) -> Adapter:
        """Return the fake adapter `declaration`'s next ask runs on."""
        return FakeAdapter(agents=self, declaration=declaration)

    def take(self, output: type[BaseModel] | None, prompt: str) -> Script:
        """Remove and return the first script queued for `output`, or raise naming the ask."""
        matching = [each for each in self.queued if each.output is output]
        if not matching:
            name = "text" if output is None else output.__name__
            message = (
                f"nothing is scripted for an ask of {name}; the prompt was: {prompt}\n"
                "Script one with `fake_agents.answer`, `answer_text`, `reject_then`, "
                "`blocked`, `stop` or `fail`."
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
        toolbox = request.toolbox
        script = agents.take(request.output, request.prompt)
        if isinstance(script, Failing):
            raise script.error
        for remark in script.notes:
            await toolbox.call(note.name, {"remark": remark})
        for each in script.frictions:
            await toolbox.call(friction.name, each.model_dump(mode="json"))
        if script.how_it_felt is not None:
            went = script.how_it_felt.model_dump(mode="json")
            await toolbox.call(how_it_felt.name, went)
        match script:
            case Texting(text=text):
                return RawTurn(text=text, usage=Usage(), session_id=session)
            case Blocking(problem=problem):
                await toolbox.call(blocked.name, {"problem": problem})
            case Stopping(why=why):
                await toolbox.call(stop.name, {"why": why})
            case Submitting(submissions=submissions):
                for submission in submissions:
                    await toolbox.call(toolbox.output or "", submission)
        toolbox.end()
        return RawTurn(text="", usage=Usage(), session_id=session)
