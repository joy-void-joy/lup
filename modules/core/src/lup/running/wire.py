"""What crosses between a container running a project's parts and the program on the operator's machine: a call through a door, its answer, and how a container is started.

Each message is one JSON object, carrying the version of its shape (`format`),
read first (`read`): a reader meeting another version refuses in words, naming
both and how to update, never with a validation error about a field it doesn't
know. Who calls (`by`) is one of the core's parties, which only the program
names, from the socket a call came in on: a call is sent without one, and a
container's program refuses one that comes without it. `Machine` never crosses:
it's only ever a call made where the machine's own parts run.
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError

from lup.doors.door import Accepted, Refused, Rejection
from lup.doors.parties import Agent, Codebase, Operator
from lup.errors import LupError
from lup.running.plan import Plan
from lup.types import Model

type Caller = Annotated[Agent | Operator | Codebase, Field(discriminator="party")]
"""Who calls, as a call across containers names them: one of the core's
parties, which the program on the operator's machine vouches for, never the
machine itself."""


class FormatError(LupError):
    """A message of another version of its shape than its reader reads: a newer lup wrote it, or an older one."""


class Versioned(Model):
    """The version of a message's shape, read before the rest of it."""

    format: int


class ToolCalled(Model):
    """An agent's call to a tool, by its name."""

    format: int = 1
    kind: Literal["tool"] = "tool"
    tool: str
    given: JsonValue
    by: Caller | None = None
    """Who it's by, as the program on the operator's machine vouches from the
    socket it came in on: none as it's sent."""


class ServiceCalled(Model):
    """A codebase's call to a service, by its name."""

    format: int = 1
    kind: Literal["service"] = "service"
    service: str
    given: JsonValue
    by: Caller | None = None
    """Who it's by, as the program on the operator's machine vouches from the
    socket it came in on: none as it's sent."""


class CommandCalled(Model):
    """A command run, by its module's name and its own."""

    format: int = 1
    kind: Literal["command"] = "command"
    module: str
    command: str
    given: JsonValue
    by: Caller | None = None
    """Who it's by, as the program on the operator's machine vouches from the
    socket it came in on: none as it's sent."""


class ViewCalled(Model):
    """A view read, by its module's name and its own."""

    format: int = 1
    kind: Literal["view"] = "view"
    module: str
    view: str
    given: JsonValue
    by: Caller | None = None
    """Who it's by, as the program on the operator's machine vouches from the
    socket it came in on: none as it's sent."""


type Call = Annotated[
    ToolCalled | ServiceCalled | CommandCalled | ViewCalled,
    Field(discriminator="kind"),
]
"""A call through any door, as it crosses: the one of each kind it is."""


class Offering(Model):
    """Asking the program on the operator's machine what the caller may call: who they are, as the socket the question came in on says, and their project's plan."""

    format: int = 1
    kind: Literal["offering"] = "offering"
    repository: str | None = None
    """The project the operator asks about, where it's theirs: the one whose
    repository their `lup` runs in. A container's project is its own,
    whatever this says."""


type Asking = Annotated[Call | Offering, Field(discriminator="kind")]
"""What comes in on a socket of the program on the operator's machine: a call
through a door, or a question of what the caller may call."""


class Offer(Model):
    """What the program on the operator's machine says a caller may call: who they are, from the socket they asked on, and the plan of their project, the machine's own parts' beside it."""

    format: int = 1
    kind: Literal["offer"] = "offer"
    by: Caller
    plan: Plan


class Answered(Model):
    """A call the method ran: what it answered, as JSON."""

    format: int = 1
    kind: Literal["answered"] = "answered"
    output: JsonValue = None


class Declined(Model):
    """A call refused, before the method ran or by it: what was sent, and why."""

    format: int = 1
    kind: Literal["refused"] = "refused"
    rejection: Rejection


type Reply = Annotated[Answered | Declined, Field(discriminator="kind")]
"""A call's answer, as it crosses: answered or refused."""


def replied(answered: Accepted | Refused) -> Reply:
    """Return a call's answer as it crosses: what the method answered, as JSON, or the refusal."""
    match answered:
        case Accepted(output=BaseModel() as model):
            return Answered(output=model.model_dump(mode="json"))
        case Accepted(output=str() as words):
            return Answered(output=words)
        case Accepted():
            return Answered()
        case Refused(rejection=rejection):
            return Declined(rejection=rejection)


class Planning(Model):
    """How a container's program is asked for a declaration's plan, which it prints and ends."""

    format: int = 1
    kind: Literal["plan"] = "plan"
    root: Path
    """The project's tree, at the commit planned, as mounted in the container."""
    declaration: Path
    """Its declaration, relative to the root."""


class Start(Model):
    """How a container's program is started: which project, which of its parts, and where it listens and calls out."""

    format: int = 1
    kind: Literal["start"] = "start"
    root: Path
    """The project's tree, at the commit the container runs, as mounted in it."""
    declaration: Path
    """Its declaration, relative to the root."""
    repository: str
    """The repository whose code it runs, as lup names it: who a service its
    code calls is called by."""
    parts: list[str] | None = None
    """The parts it runs, each named `module.Part`; none for every part
    holding nothing, as the project's own container runs them."""
    listening: Path
    """The socket it answers calls on."""
    calling: Path
    """The program's socket, through which it calls a service of a part
    running elsewhere."""
    secrets: Path | None = None
    """The directory in memory holding each secret its parts hold, a file
    named for each, which the program reads and removes before any part
    starts; none where they hold none."""
    data: Path | None = None
    """The directory each part keeping data keeps it under, a directory named
    `module.Part` each; none where none keeps any."""
    runtime: Path | None = None
    """The directory in memory each part keeping what lasts while it runs
    keeps it under, a directory named `module.Part` each; none where none
    keeps any."""


class Host(Model):
    """How the machine's own parts are started, on the operator's machine, from the home repository's approved commit: its tree, its declaration, and where lup keeps its state."""

    format: int = 1
    kind: Literal["host"] = "host"
    root: Path
    """The home repository's tree, at the commit the operator approved."""
    declaration: Path
    """Its declaration, relative to the root."""
    repository: str
    """The home repository, as lup names it."""
    state: Path
    """Where the machine's parts keep their data, a directory each."""
    runtime: Path
    """Where the machine's parts keep what lasts while it runs, in memory:
    `$XDG_RUNTIME_DIR/lup`, a short path, since a socket's is limited to
    108 bytes."""


type Asked = Annotated[Planning | Start | Host, Field(discriminator="kind")]
"""What the program is given to do: plan, start a container's parts, or host the machine's."""


def read[M](text: bytes | str, kind: TypeAdapter[M], reads: int = 1) -> M:
    """Read a message of `kind` from `text`, its shape's version checked first: `read(line, TypeAdapter(Call))`.

    Raise `FormatError` where it's of another version than `reads`, saying
    which, and pydantic's `ValidationError` where it isn't a `kind` at all.
    """
    try:
        version = Versioned.model_validate_json(text).format
    except ValidationError as unread:
        message = (
            f"a message carries no version of its shape, so it isn't lup's: {unread}"
        )
        raise FormatError(message) from unread
    if version != reads:
        newer = "a newer lup wrote it" if version > reads else "an older lup wrote it"
        message = (
            f"a message is of version {version} of its shape, where this lup reads "
            f"{reads}: {newer}. Update lup to the same commit on both sides, with "
            "`lup update` on the operator's machine"
        )
        raise FormatError(message)
    return kind.validate_json(text)
