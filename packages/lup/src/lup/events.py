"""lup's events, one class each: what a module's hooks run at, and what each runtime's hooks are read as.

The classes are the one list of lup's events: a hook names its events by class
(`@lup.on(Stopped)`, `lup.doors`), each runtime's adapter maps its own hooks to
them and back, and the judge's events extend them with what the judge reads
(`lup_dev.policy.checkpoint`).
- lup's own: a launch opening (`Launched`), a launch ending once its session
  has fully stopped (`Stopped`), and something about to leave under the
  operator's name (`Publishing`), the one event a hook answers, returning its
  refusals (`lup.publishing`);
- a session's, which each runtime's hooks are read as (`SessionEvent`): a
  session started, resumed or cleared (`SessionStarted`); a turn starting on a
  prompt, the operator's or one a tool server pushed, or a prompt arriving in a
  turn (`TurnStarted`); a tool call about to run (`CallStarted`); a worktree
  asked for, for a conversation to work in apart (`WorktreeAsked`), which a
  runtime's hook makes; a tool call finished, whether it succeeded or failed
  (`CallFinished`); the session's own turn ending (`TurnEnded`); a subagent's
  conversation ending (`ConversationEnded`).

An event carries its own facts alone: which call, which tool, what would leave.
The launch it's of, and the conversation, travel with whoever asks a hook to
run (`lup_dev`'s `Lup`), since what a launch is belongs to the environment.

Where an event crosses a wire it's named in kebab case, derived from its class
(`named`: `CallStarted` is `call-started`) and carried as its `kind`, which
`Told` reads it back by. Nowhere else is an event spelled as a string.
"""

from types import UnionType
from typing import TYPE_CHECKING, Annotated, TypeAliasType, get_args

from pydantic import AfterValidator, GetCoreSchemaHandler, JsonValue, computed_field
from pydantic_core import CoreSchema, core_schema

from lup.publishing import Published
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Hashable


def kebab(name: str) -> str:
    """Return a class's name in kebab case, as an event's is said on a wire.

    >>> kebab("ConversationEnded")
    'conversation-ended'
    """
    return "".join(
        f"-{letter.lower()}" if letter.isupper() and at else letter.lower()
        for at, letter in enumerate(name)
    )


class Event(Model):
    """One of lup's events: a class of its own each, which a hook names it by, its fields what's known of it."""

    @classmethod
    def named(cls) -> str:
        """Return the event's name on a wire: its class's, in kebab case.

        >>> CallStarted.named()
        'call-started'
        """
        return kebab(cls.__name__)

    @computed_field
    @property
    def kind(self) -> str:
        """The event's name, which a wire carries it with (`named`)."""
        return self.named()


class Launched(Event):
    """A launch opened: its room started, and its session about to."""


class Stopped(Event):
    """A launch ended, its session fully stopped."""


class Publishing(Event):
    """Something is about to leave under the operator's name: a push, or a post.

    The one event a hook answers: each hook at it returns its refusals, and one
    refusal keeps it from leaving.
    """

    published: Published


class SessionStarted(Event):
    """A session started, resumed or was cleared."""


class TurnStarted(Event):
    """A conversation's turn started on a prompt, the operator's or one a tool server pushed, or a prompt arrived in their turn."""


class CallStarted(Event):
    """A tool call is about to run."""

    call: str
    """The runtime's id for the call."""
    tool: str
    """The tool called, by the runtime's name for it."""


class WorktreeAsked(Event):
    """The runtime asks for a worktree of the repository, for a conversation to work in apart, as a subagent it isolates: the hook answers where it made it."""

    name: str
    """The runtime's name for the worktree, which its branch takes."""


class CallFinished(Event):
    """A tool call finished, whether it succeeded or failed."""

    call: str
    """The runtime's id for the call."""
    tool: str
    """The tool called, by the runtime's name for it."""


class TurnEnded(Event):
    """The session's own conversation ended their turn."""


class ConversationEnded(Event):
    """A subagent's conversation ended their turn; the session's own goes on."""


type SessionEvent = (
    SessionStarted
    | TurnStarted
    | CallStarted
    | WorktreeAsked
    | CallFinished
    | TurnEnded
    | ConversationEnded
)
"""A session's events, which each runtime's hooks are read as: a runtime with no
hook for one declares the gap in its adapter."""

type Observed = Launched | Stopped | SessionEvent
"""The events a hook observes, answering nothing: every one but `Publishing`."""


def told(value: JsonValue | Event) -> str | None:
    """Return the name an event is read back by: its `kind`, on the wire or on the model."""
    match value:
        case Event():
            return value.named()
        case {"kind": str(kind)}:
            return kind
        case _:
            return None


def members(annotation: type | UnionType | TypeAliasType) -> list[type[Event]]:
    """Return the events a union of them names, an alias in it read through: `CallStarted | SessionEvent` names all of a session's."""
    match annotation:
        case TypeAliasType():
            return members(annotation.__value__)
        case UnionType():
            return [each for arm in get_args(annotation) for each in members(arm)]
        case type() if issubclass(annotation, Event):
            return [annotation]
        case _:
            message = f"{annotation!r} isn't one of lup's events"
            raise TypeError(message)


class ByKind:
    """Read a union of events by each one's `kind`, its name on the wire (`named`): `Annotated[SessionEvent, ByKind]`.

    pydantic picks the union's arm the `kind` names, each arm's name derived
    from its class, so no name is written twice.
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: type | UnionType | TypeAliasType, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        """Return the schema reading `source`, a union of events, by each one's `kind`."""
        choices: dict[Hashable, CoreSchema] = {
            each.named(): handler.generate_schema(each) for each in members(source)
        }
        return core_schema.tagged_union_schema(choices, discriminator=told)


type Told = Annotated[Launched | Stopped | Publishing | SessionEvent, ByKind]
"""Any of lup's events, as a wire carries it: read back by its `kind`."""


def known(name: str) -> str:
    """Return `name` where it's one of lup's events' names (`named`), else raise `ValueError` naming them.

    >>> known("stopped")
    'stopped'
    """
    names = [each.named() for each in events()]
    if name not in names:
        message = f"`{name}` isn't one of lup's events: {', '.join(names)}"
        raise ValueError(message)
    return name


type EventName = Annotated[str, AfterValidator(known)]
"""One of lup's events, by its name on a wire (`Event.named`)."""


def events() -> list[type[Event]]:
    """Return lup's events, in the order they come: a launch's, then a session's.

    >>> [each.named() for each in events()][:3]
    ['launched', 'stopped', 'publishing']
    """
    return [
        Launched,
        Stopped,
        Publishing,
        SessionStarted,
        TurnStarted,
        CallStarted,
        WorktreeAsked,
        CallFinished,
        TurnEnded,
        ConversationEnded,
    ]
