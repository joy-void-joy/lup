"""The harness a promise reaches lup through: lup started on a declaration, its doors called as its parties call them, and values drawn for it.

A promise is handed the harness as `by`, typed `Testing`, and reaches lup only
through it and modules' public surface, which an import contract holds. What the
harness does is said here, on the library side, and done by the environment's
(`lup.environment.testing`), so loading a declaration imports neither hypothesis
nor the environment, and another harness, driving real agents, could check the
same promises (`README.md` here, *The harness*).
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, Field, JsonValue, SerializeAsAny

from lup.command_line.answering import Answerer, Here, Offered, Typed
from lup.declaration.module import Module
from lup.doors.door import Accepted, Refused
from lup.doors.parties import Party
from lup.doors.tool import ToolSpec
from lup.errors import LupError
from lup.running.plan import CORE, Plan
from lup.running.wire import (
    Caller,
    CommandCalled,
    ServiceCalled,
    ToolCalled,
    ViewCalled,
    replied,
)
from lup.types import Model, MutableModel
lazy from lup.command_line import line

if TYPE_CHECKING:
    from lup.declaration.project import Project
    from lup.doors.parties import Agent
    from lup.running import wire
    from lup.shell.wire import Sent as Frame
    from lup.shell.wire import Told
    from lup.told.guidance import Guidance

type Sent = BaseModel | list[BaseModel] | Mapping[str, JsonValue] | JsonValue
"""What a party sends through a door: a model, or a list of it, sent as its JSON,
or JSON as it is, which needn't be what the method takes."""


def sent(given: Sent) -> JsonValue:
    """Return what's sent as the JSON a party sends.

    >>> class Said(Model):
    ...     text: str
    >>> sent(Said(text="hi")), sent([Said(text="a")]), sent({"text": 1})
    ({'text': 'hi'}, [{'text': 'a'}], {'text': 1})
    """
    match given:
        case BaseModel():
            return given.model_dump(mode="json")
        case list():
            return [sent(one) for one in given]
        case Mapping():
            return dict(given)
        case _:
            return given


class ToolCall(Model):
    """An agent's call to a tool, by its name."""

    door: Literal["tool"] = "tool"
    tool: str
    arguments: JsonValue
    by: SerializeAsAny[Party]


class Ran(Model):
    """A command run, by its module's name and its own."""

    door: Literal["command"] = "command"
    module: str
    command: str
    arguments: JsonValue
    by: SerializeAsAny[Party]


class Served(Model):
    """A service called as code calls it, by its name."""

    door: Literal["service"] = "service"
    service: str
    given: JsonValue
    by: SerializeAsAny[Party]


class Viewed(Model):
    """A view read, by its module's name and its own."""

    door: Literal["view"] = "view"
    module: str
    view: str
    given: JsonValue
    by: SerializeAsAny[Party]


type Call = Annotated[ToolCall | Ran | Served | Viewed, Field(discriminator="door")]
"""One call through a door, as a party makes it: which door, what was sent, and
by whom."""


class Repository(Model):
    """A repository as lup finds one on disk: the text of its declaration's file, of its own local layer, and of the machine's layer, each where there's one."""

    declaration: str | None = None
    """Its declaration's file; none for a repository that declares nothing."""
    local: str | None = None
    """Its own local layer, which git ignores."""
    machine: str | None = None
    """The machine's layer, for every repository on it."""


class Step[S](Model):
    """One step of a run, as a law reads it: a slice of a call, from one `await` to the next, with the module's state before and after it.

    `S` is the module's state as a party sees it: what a door of the module
    that only reads answers (`README.md` here, *Laws*). Where calls overlap,
    each slice of each is a step of its own, so a law sees what that call
    changed, and when.
    """

    before: S
    call: Call
    """The call the slice belongs to."""
    answered: Accepted | Refused | None = None
    """What the call answered, on the slice that ended it; none on the
    slices before."""
    after: S

    def by(self) -> Party:
        """Return who made the call."""
        return self.call.by


class Kept(Model):
    """A promise the harness checked, which held in every run it made."""

    promise: str
    """The promise, by its class's name and its own: `CounterPromises.counts`."""


class Broken(Model, arbitrary_types_allowed=True):
    """A promise the harness checked, which a run broke: the smallest it found, and what broke it."""

    promise: str
    """The promise, by its class's name and its own: `CounterPromises.counts`."""
    drawn: list[JsonValue]
    """What the run drew from the harness, in order, as JSON."""
    calls: list[Call]
    """The calls the run made through lup's doors, in the order they started."""
    slices: list[Call] = []
    """The call each slice of the run belonged to, in the order the slices
    ran: how the calls interleaved, where they overlapped."""
    error: BaseException
    """What broke it: a law that didn't hold (`BrokenLawError`), an assertion
    that failed, or what the promise raised."""


class BrokenLawError(LupError, AssertionError):
    """A law didn't hold over a step of a run: a promise broken, as a failed assertion is."""

    def __init__(self, law: str, step: Step[BaseModel]) -> None:
        """Say that the law named `law` didn't hold over `step`."""
        super().__init__(f"the law `{law}` doesn't hold over this step: {step!r}")
        self.law = law
        self.step = step


class Reaching(ABC):
    """lup's doors, as the harness reaches a started lup's: what its modules serve, and each call answered."""

    @abstractmethod
    async def answered(self, call: Call) -> Accepted | Refused:
        """Make `call`, and say what came of it, every law the modules hold checked over it."""

    @abstractmethod
    async def checked(self, module: str, promise: str | None) -> list[Kept | Broken]:
        """Check the promise named `promise` of the module named `module`, or every one where none is named, as the gate does, and say how each fared."""

    @abstractmethod
    async def stopped(self) -> None:
        """Stop what's started: each class's methods run at `Stopping`, then what each runs since `Starting` cancelled."""


class ProgramRun(Model):
    """One run of a program a part asked for, as the harness's stand-in heard it."""

    program: str
    arguments: list[str]
    given: bytes | None = None
    """What it was given on its input."""
    env: dict[str, str] = {}
    """The variables it was run with beside the machine's own."""
    cwd: Path | None = None
    """The directory it was run from; none where it ran where its part runs."""


class Heard(MutableModel):
    """What the harness's stand-in for a part's programs heard: each run asked for, in order."""

    runs: list[ProgramRun] = []


class Answering(Model):
    """One answer a program stood in for gives: to a run whose arguments start with `when`."""

    when: list[str] = []
    """The arguments a run starts with, for it to get this answer; none for
    any run."""
    status: int = 0
    output: bytes | str = b""
    """What it prints, text written as UTF-8."""
    error: bytes | str = b""
    """What it writes on its standard error, text written as UTF-8."""


class Scripted(Model):
    """A program a part declares, stood in for in the harness: the answers it gives, the first whose `when` a run's arguments start with; a run none answers fails as a program that isn't there."""

    answers: list[Answering] = []


class Responding(ABC):
    """A program a part declares, stood in for by code a promise writes: it answers each run from its arguments and its input, as a store of git's objects answers what's asked of it."""

    @abstractmethod
    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Answer one run; none where the program as stood in for has no answer to it, which fails as a program that isn't there."""


class Acting(ABC):
    """A program a part declares, stood in for by code a promise writes that's told the whole of each run: its arguments, its input, the variables it's run with beside the machine's own and the directory it's run from, as one running the program for real needs, for what only the real program can say, as git merging."""

    @abstractmethod
    def ran(
        self,
        arguments: list[str],
        given: bytes | None,
        env: dict[str, str],
        cwd: Path | None,
    ) -> Answering:
        """Answer one run, whatever its status."""


class Crossing(ABC):
    """A started lup's parts, as a message crossing to their container reaches them: what the program on the operator's machine sends."""

    @abstractmethod
    async def crossed(self, text: bytes) -> bytes:
        """Answer one message that crossed to the container running the parts, as it would: its call through a door answered, or why it's refused."""


class Telling(ABC):
    """A started lup's guidance, as a session's start renders it."""

    @abstractmethod
    async def guidance(self, by: Agent) -> Guidance:
        """Render what the session `by` is told at its start of the modules: each section, on its part as made here."""


class Page(Model, ABC):
    """The dashboard's page, as a promise drives it: what it says on the server's socket, and what it's told."""

    token: str
    """The dashboard's token, which the page was handed in its address."""

    @abstractmethod
    async def say(self, frame: Frame | str) -> None:
        """Send the server `frame`, or text as it is, which needn't be a frame it reads."""

    @abstractmethod
    async def told(self) -> Told | None:
        """Return the next frame the server tells the page; none once it's closed the socket."""

    @abstractmethod
    async def leave(self) -> None:
        """Close the page, as the operator's tab closing does."""


class Opening(ABC):
    """The dashboard of a started lup, as the harness reaches it."""

    @abstractmethod
    async def page(self) -> Page:
        """Open a page of the dashboard, its socket open, nothing said yet."""


class Started(Model, arbitrary_types_allowed=True):
    """lup started on a declaration: its modules, and its doors, called as a party calls them.

    Each call answers `Accepted` or `Refused`, as a service relays it; nothing
    sent makes a call raise. Every law its modules hold is checked over each
    call, and one that doesn't hold raises `BrokenLawError`.
    """

    modules: list[Module]
    """The modules it's made of, every layer applied, in order."""
    specs: list[ToolSpec]
    """What a session is told of each tool its modules serve."""
    plan: Plan
    """Its declaration's plan, as the program on the operator's machine reads
    it."""
    doors: Reaching
    """Its doors, as the harness reaches them."""
    dashboards: Opening
    """Its dashboard, as the harness reaches it."""

    async def dashboard(self) -> Page:
        """Open a page of its dashboard, as the operator's browser does: its socket open, nothing said yet."""
        return await self.dashboards.page()

    crossing: Crossing
    """Its parts, as a message crossing to their container reaches them."""
    heard: Heard
    """Each run of a program its parts asked for, in order, as the harness's
    stand-in heard it."""
    telling: Telling
    """Its guidance, as a session's start renders it."""

    async def crossed(self, text: bytes) -> bytes:
        """Answer one message as the container running its parts would: a call through a door, carrying the version of its shape (`lup.running.wire`)."""
        return await self.crossing.crossed(text)

    def ran(self, program: str) -> list[list[str]]:
        """Return the arguments of each run of the program named `program` its parts asked for, in order, as the harness's stand-in heard them."""
        return [each.arguments for each in self.heard.runs if each.program == program]

    def tools(self) -> list[ToolSpec]:
        """Return what a session is told of each tool its modules serve."""
        return self.specs

    async def stopped(self) -> None:
        """Stop it before the promise ends, rather than as it does: each class's methods run at `Stopping`, then what each runs since `Starting` cancelled."""
        await self.doors.stopped()

    async def checked(
        self, module: str, promise: str | None = None
    ) -> list[Kept | Broken]:
        """Check the promise named `promise` of the module named `module`, or every one where none is named, as the gate does, and say how each fared."""
        return await self.doors.checked(module, promise)

    async def guidance(self, by: Agent) -> Guidance:
        """Render what the session `by` is told at its start of its modules: each section they serve, in the declaration's order, on its part as started here.

        Raise `GuidanceError`, naming its module, where a section doesn't
        render.
        """
        return await self.telling.guidance(by)

    async def call(self, tool: str, arguments: Sent, by: Party) -> Accepted | Refused:
        """Call the tool named `tool` with `arguments`, as `by` does, and say what came of it."""
        call = ToolCall(tool=tool, arguments=sent(arguments), by=by)
        return await self.doors.answered(call)

    async def run(
        self, module: str, command: str, arguments: Sent, by: Party
    ) -> Accepted | Refused:
        """Run the command `command` of the module named `module` with `arguments`, as `by` does, from the command line or the dashboard's key, and say what came of it."""
        call = Ran(module=module, command=command, arguments=sent(arguments), by=by)
        return await self.doors.answered(call)

    async def serve(self, service: str, given: Sent, by: Party) -> Accepted | Refused:
        """Call the service named `service` on `given`, as `by`'s code does, and say what came of it."""
        call = Served(service=service, given=sent(given), by=by)
        return await self.doors.answered(call)

    async def view(
        self, module: str, view: str, given: Sent, by: Party
    ) -> Accepted | Refused:
        """Read the view `view` of the module named `module` for `given`, as `by` does, and say what came of it: its `Blocks`, where it answered.

        Raise `BlockError` where what it answers names a kind neither the core
        nor its module declares.
        """
        call = Viewed(module=module, view=view, given=sent(given), by=by)
        return await self.doors.answered(call)

    async def typed(
        self,
        words: list[str],
        by: Caller,
        command: list[str] | None = None,
        *,
        here: Started | None = None,
    ) -> Typed:
        """Type `words` on the command line, `lup`, as `by` does in their terminal or their room, and say what it did: what it printed and how it ended, what the help it showed listed, and the call it made.

        It offers what this lup's plan lets `by` call, the core's methods at
        its top level, and makes its call through these doors, every law
        checked over it. Where `command` names modules, it's a project's own
        command instead, given those modules: it offers theirs alone, the
        first's at its top level. Where `here` is given, this lup stands for
        lup's program on the operator's machine and `here` for the worktree
        it's typed in: a command this lup's plan marks to run where it's typed
        is made through `here`'s doors instead (`Here`). Raise `BlockError`
        where a view it reads names a kind nobody declares, as `view` does.
        """
        harnessed = Harnessed(started=self, by=by, offering=command)
        top = CORE if command is None else next(iter(command), None)
        if here is None:
            return await line.typed(words, harnessed, "lup", top=top)
        worktree = here

        def made(party: Caller) -> Answerer:
            return Harnessed(started=worktree, by=party, offering=command)

        return await line.typed(
            words, Here(through=harnessed, here=made), "lup", top=top
        )


class Harnessed(Model, Answerer, arbitrary_types_allowed=True):
    """The command line's calls answered through a started lup's doors, as the harness reaches them, by the party a promise names."""

    started: Started
    by: Caller
    offering: list[str] | None = None
    """The modules whose methods it offers, by name, as a project's own
    command does; none for every module, as `lup` offers them."""

    async def offered(self) -> Offered:
        """Return who the calls are by, and the started lup's plan, of the modules it offers alone."""
        plan = self.started.plan
        offering = self.offering
        return Offered(
            by=self.by, plan=plan if offering is None else plan.only(offering)
        )

    async def answered(self, call: wire.Call) -> wire.Reply:
        """Make `call` through the started lup's doors, by the party this names, every law checked over it, and return its reply."""
        by = self.by
        match call:
            case ToolCalled(tool=tool, given=given):
                answered = await self.started.call(tool, given, by)
            case CommandCalled(module=module, command=command, given=given):
                answered = await self.started.run(module, command, given, by)
            case ViewCalled(module=module, view=view, given=given):
                answered = await self.started.view(module, view, given, by)
            case ServiceCalled(service=service, given=given):
                answered = await self.started.serve(service, given, by)
        return replied(answered)

    async def stopped(self) -> None:
        """Stop nothing: the harness stops what it started once the promise ends."""


class Testing(Party, ABC):
    """The harness: what checks a module's promises, handed to each as `by`, starting lup for them and drawing the values they explore.

    A party of its own, since it's who calls a promise.
    """

    @abstractmethod
    async def started(
        self,
        declared: Project | Repository,
        secrets: Mapping[str, str] | None = None,
        repository: str = "harness",
        programs: Mapping[str, Scripted | Responding | Acting] | None = None,
        *,
        machine: bool = False,
    ) -> Started:
        """Start lup on a declaration: a `Project`, or a repository's files, read with their layers as lup reads a repository's, each class of its modules made once and started, as the code of `repository`, each program its parts run stood in for as `programs` scripts it; where `machine`, as the machine's own parts, a service their code calls being by `Machine`.

        `secrets` holds the value of each secret a class holds, by its name;
        left out, each is drawn. Raise `ProjectError` where it doesn't load or
        resolve, or where a secret a class holds isn't given, as lup's start
        does. What it started is stopped once the promise ends.
        """

    @abstractmethod
    def project(self) -> Project:
        """Return the project whose gate checks this promise, as its gate loads its declaration: what a promise about every project checks (`@lup.promise(every_project=True)`)."""

    @abstractmethod
    def any[T](self, kind: type[T]) -> T:
        """Return a value of `kind`, generated: each run of the promise draws another, and one that breaks it is shrunk to the smallest that does.

        A model's every field is explored, its defaults among the values.
        """
