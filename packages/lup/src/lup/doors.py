"""The doors a module's method is reached through, each a decorator in `lup`'s namespace: `lup.tool`, `lup.request` and `lup.on`.

A door exists only where the contract differs: who calls a method, what it
takes, what it returns. Each is a decorator, typed with its contract, so pyright
holds the method behind it to what the door takes and returns:
- `@lup.tool`, or `@lup.tool(reads=True)`: an agent calls it, through MCP. It
  takes a model and returns another, or `str` for an answer in words (`Tool`).
  Its marks say whether a call may be sent again (`ToolDoor`).
- `@lup.request`: code in a room asks it, sending the model it takes, whose
  `kind` routes it; it returns the reply.
- `@lup.on(Stopped)`, stacked for several: lup runs it at an event, its class
  one of `lup.events`'. It takes the event and returns nothing; at
  `Publishing`, the one event a hook answers, it returns its refusals
  (`lup.publishing`). One taking `Publishing` beside another event is refused,
  since nothing at the others is refused.

A method takes one model, its docstring describing it, and its name, with its
module's, routing it: a tool's name is the method's. Where it needs whoever asks
it, it takes them too, as `by`, typed as who it's for: `by: Agent`, `by: Room`.
`by` hands the method its caller, and narrows who may ask it to what its type
admits. Left out, the method is for its door's default askers, where the door
has some. Who comes through each door, and checking `by` against them when a
class of methods is defined and before each call, are the environment's that
serves them (`lup_dev.declaration.serving`), since what a caller is, a launch
and its conversation, is the environment's.

Several doors on one method only within one audience: today, the events a hook
runs at, stacked. Each decorator puts its door on the method (`Served`): read
through an instance, it's that instance's method, called as any (`await
serving.read_issue(asked, by=agent)`); read through its class, it says its
doors and what it takes. pyright holds a stacked hook to the event of its
innermost `on`; each other `on` checks its event as it's applied, refusing one
the method's parameter doesn't admit.

A plain function given to an agent from code is a tool too: `@lup.tool` on
`async def weather(asked: City) -> Forecast` makes a `Tool`, which an ask serves.
"""

import inspect
from collections.abc import Awaitable, Callable
from functools import partial
from types import GenericAlias, UnionType
from typing import Concatenate, Self, get_args, get_origin, overload

from pydantic import BaseModel

from lup.errors import LupError
from lup.events import Event, Observed, Publishing, events
from lup.publishing import Refusal
from lup.tools.tool import AgentTool, Tool, ToolSpec, is_model, summary_of
from lup.types import Model

type Answer = BaseModel | str | list[Refusal] | None
"""What a method behind a door answers: a tool's model or words, a request's
reply, a hook's refusals at `Publishing`, or nothing."""

type Annotation = type | GenericAlias | UnionType | None
"""A type as a signature writes it: a class, a generic alias (`list[Refusal]`),
a union, or `None`."""


def spelled(annotation: Annotation) -> str:
    """Say a type as a signature writes it.

    >>> spelled(Publishing | None), spelled(list[Refusal])
    ('`Publishing | None`', '`list[Refusal]`')
    """

    def bare(each: Annotation) -> str:
        match each:
            case GenericAlias():
                arguments = ", ".join(bare(argument) for argument in get_args(each))
                return f"{bare(get_origin(each))}[{arguments}]"
            case UnionType():
                return " | ".join(bare(arm) for arm in get_args(each))
            case None:
                return "None"
            case type() if each is type(None):
                return "None"
            case type():
                return each.__name__

    return f"`{bare(annotation)}`"


class DoorError(LupError):
    """A function can't be reached through a door: it takes or returns other than the door's contract says, or two doors of different audiences are put on it."""


class Taken(Model, arbitrary_types_allowed=True):
    """What a function takes and returns, read off its signature as a door is put on it: its model, who asks it, and its answer."""

    name: str
    description: str | None
    """Its docstring, which describes it: what an agent reads of a tool."""
    method: bool
    """Whether it takes `self` first: a method of a class, rather than a plain
    function."""
    model: inspect.Parameter
    """The parameter taking its model: a request, a tool's input, or the event
    a hook runs at, a union of events for one stacked at several."""
    by: inspect.Parameter | None
    """The parameter taking who asks it, typed as who may; none where it's left
    out, and its door's default askers may."""
    returned: Annotation
    """Its return annotation, as written."""

    @classmethod
    def of(cls, function: Callable[..., Awaitable[Answer]]) -> Taken:
        """Read what `function` takes and returns off its signature.

        Raise `DoorError` naming it where its annotations don't evaluate, or
        where it takes other than one model, after `self` for a method, then
        `by` where it says who asks it.
        """
        name = function.__name__
        try:
            signature = inspect.signature(function)
        except NameError as unnamed:
            message = (
                f"`{name}`'s annotations name `{unnamed.name}`, which isn't imported "
                "where it runs: its door reads them as it's put on, so import it "
                "outside `TYPE_CHECKING`"
            )
            raise DoorError(message) from unnamed
        parameters = list(signature.parameters.values())
        method = bool(parameters) and parameters[0].name == "self"
        match parameters[1:] if method else parameters:
            case [model]:
                by = None
            case [model, inspect.Parameter(name="by") as by]:
                pass
            case taken:
                named = ", ".join(f"`{each.name}`" for each in taken) or "nothing"
                message = (
                    f"`{name}` takes {named}: a method takes one model, then, where "
                    "it needs who asks it, `by`"
                )
                raise DoorError(message)
        returned = signature.return_annotation
        if not (
            returned is None or isinstance(returned, type | GenericAlias | UnionType)
        ):
            message = f"`{name}` returns {returned!r}, which isn't a type"
            raise DoorError(message)
        return cls(
            name=name,
            description=inspect.getdoc(function),
            method=method,
            model=model,
            by=by,
            returned=returned,
        )

    def answers_model(self) -> bool:
        """Say whether it returns a pydantic model."""
        return isinstance(self.returned, type) and issubclass(self.returned, BaseModel)

    def admits(self, event: type[Event]) -> bool:
        """Say whether its model's type admits `event`: the event's class, or one it derives from, alone or in a union."""
        annotation = self.model.annotation
        named = (
            get_args(annotation) if isinstance(annotation, UnionType) else [annotation]
        )
        return any(isinstance(each, type) and issubclass(event, each) for each in named)


class ToolDoor(Model):
    """A tool's door: an agent calls the method, its arguments the model it takes; its marks say whether a call may be sent again.

    `@lup.tool(reads=True)` is this door, put on the method it decorates.
    """

    reads: bool = False
    """Whether the tool only reads, changing nothing: MCP's `readOnlyHint`."""
    idempotent: bool = False
    """Whether a call sent again with the same arguments adds nothing to what
    the first did: MCP's `idempotentHint`."""

    def says(self) -> str:
        """Say the door, as an error names it."""
        return "a tool"

    def checked(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a tool's: one model in, a model or `str` out, and a docstring opening with its summary."""
        if not is_model(taken.model.annotation):
            message = (
                f"the tool `{taken.name}` takes `{taken.model.name}` typed "
                f"{spelled(taken.model.annotation)}: a tool takes one pydantic model"
            )
            raise DoorError(message)
        if not (taken.answers_model() or taken.returned is str):
            message = (
                f"the tool `{taken.name}` returns {spelled(taken.returned)}: a tool "
                "returns a pydantic model, or `str` for an answer in words"
            )
            raise DoorError(message)
        if taken.description is None:
            message = (
                f"the tool `{taken.name}` needs a docstring: it's what the model reads"
            )
            raise DoorError(message)
        summary_of(taken.name, taken.description)

    @overload
    def __call__[I: BaseModel, O: BaseModel | str](
        self, function: Callable[[I], Awaitable[O]], /
    ) -> Tool[I, O]: ...
    @overload
    def __call__[S, I: BaseModel, O: BaseModel | str, **P](
        self, function: Callable[Concatenate[S, I, P], Awaitable[O]], /
    ) -> Served[S, Concatenate[I, P], Awaitable[O]]: ...
    def __call__(
        self, function: Callable[..., Awaitable[BaseModel | str]], /
    ) -> Method | AgentTool:
        """Return `function` as a tool: a method served through this door, or a plain function's `Tool`."""
        return tooled(function, self)


class RequestDoor(Model):
    """A request's door: code in a room asks the method, sending the model it takes, whose `kind` routes it; the method returns the reply."""

    def says(self) -> str:
        """Say the door, as an error names it."""
        return "a request"

    def checked(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a request's: a method taking one model and returning another."""
        if not taken.method:
            message = f"the request `{taken.name}` is a method of a class of a module's"
            raise DoorError(message)
        if not (is_model(taken.model.annotation) and taken.answers_model()):
            message = (
                f"the request `{taken.name}` must take the request's model and "
                "return its reply's"
            )
            raise DoorError(message)

    def __call__[S, I: BaseModel, O: BaseModel, **P](
        self, method: Callable[Concatenate[S, I, P], Awaitable[O]], /
    ) -> Served[S, Concatenate[I, P], Awaitable[O]]:
        """Return `method` served through this door."""
        return Served(method, [self], first(method, self))


class OnDoor(Model):
    """A hook's door at one event: lup runs the method then, giving it the event."""

    event: type[Event]

    def says(self) -> str:
        """Say the door, as an error names it."""
        return f"a hook at `{self.event.__name__}`"

    def checked(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a hook's at this event: a method whose model's type admits it, returning its refusals at `Publishing` and nothing at any other."""
        if not taken.method:
            message = f"the hook `{taken.name}` is a method of a class of a module's"
            raise DoorError(message)
        if self.event not in events():
            message = (
                f"the hook `{taken.name}` runs at `{self.event.__name__}`, which "
                f"isn't one of lup's events: {', '.join(each.__name__ for each in events())}"
            )
            raise DoorError(message)
        if not taken.admits(self.event):
            message = (
                f"the hook `{taken.name}` runs at `{self.event.__name__}`, but takes "
                f"`{taken.model.name}` typed {spelled(taken.model.annotation)}, which "
                "doesn't admit it"
            )
            raise DoorError(message)
        answers = list[Refusal] if self.event is Publishing else None
        if taken.returned != answers:
            message = (
                f"the hook `{taken.name}` at `{self.event.__name__}` returns "
                f"{spelled(taken.returned)}: a hook at `Publishing` returns its "
                "refusals, `list[Refusal]`, and at any other event nothing"
            )
            raise DoorError(message)


class Observing[E: Event](OnDoor):
    """A hook's door at an event it observes, answering nothing: `@lup.on(Stopped)`."""

    event: type[E]

    @overload
    def __call__[S, I, **P](
        self, method: Served[S, Concatenate[I, P], Awaitable[None]], /
    ) -> Served[S, Concatenate[I | E, P], Awaitable[None]]: ...
    @overload
    def __call__[S, **P](
        self, method: Callable[Concatenate[S, E, P], Awaitable[None]], /
    ) -> Served[S, Concatenate[E, P], Awaitable[None]]: ...
    def __call__(self, method: Method | Callable[..., Awaitable[None]], /) -> Method:
        """Return `method` served at this event too."""
        return opened(method, self)


class Refusing(OnDoor):
    """A hook's door at `Publishing`, which it answers with its refusals: `@lup.on(Publishing)`."""

    event: type[Publishing] = Publishing

    @overload
    def __call__[S, **P](
        self,
        method: Served[S, Concatenate[Publishing, P], Awaitable[list[Refusal]]],
        /,
    ) -> Served[S, Concatenate[Publishing, P], Awaitable[list[Refusal]]]: ...
    @overload
    def __call__[S, **P](
        self,
        method: Callable[Concatenate[S, Publishing, P], Awaitable[list[Refusal]]],
        /,
    ) -> Served[S, Concatenate[Publishing, P], Awaitable[list[Refusal]]]: ...
    def __call__(
        self, method: Method | Callable[..., Awaitable[list[Refusal]]], /
    ) -> Method:
        """Return `method` served at `Publishing`."""
        return opened(method, self)


type Door = ToolDoor | RequestDoor | OnDoor
"""A door a method is reached through."""


class Method(property):
    """A method lup serves, read through its class: its function, each door it's reached through, and what it takes.

    A read-only property of its class, so a pydantic model holds it as it holds
    any property, not as a field; its class lists it among its attributes, so a
    class of methods finds its own (`served`).
    """

    def __init__(
        self,
        function: Callable[..., Awaitable[Answer]],
        doors: list[Door],
        taken: Taken,
    ) -> None:
        """Hold the function, which takes the instance first, its doors and what it takes."""
        self.function = function
        self.doors = doors
        self.taken = taken
        super().__init__(self.read)

    def read(self, instance: BaseModel) -> Callable[..., Awaitable[Answer]]:
        """Return the method of `instance`."""
        return partial(self.function, instance)

    def __set_name__(self, owner: type, name: str) -> None:
        """Refuse a name its class gives a field: the field would hide the method."""
        refuse_taken(owner, name)

    def through(self, door: Door) -> Method:
        """Return this method reached through `door` too.

        Raise `DoorError` naming it where `door` isn't of the audience its
        doors are: today, a hook's at several events alone; where it's a hook's
        at `Publishing` beside another event; or where it's a hook's at an
        event it runs at already.
        """
        name = self.taken.name
        if not all(isinstance(each, OnDoor) for each in [*self.doors, door]):
            message = (
                f"`{name}` is {self.doors[0].says()} already, and can't be "
                f"{door.says()} too: a method is reached through one audience's "
                "doors, and a tool, a request and a hook each have their own"
            )
            raise DoorError(message)
        hooked = [each.event for each in self.doors if isinstance(each, OnDoor)]
        if isinstance(door, OnDoor) and door.event in hooked:
            message = f"`{name}` runs at `{door.event.__name__}` already"
            raise DoorError(message)
        if isinstance(door, OnDoor) and Publishing in [*hooked, door.event]:
            message = (
                f"`{name}` runs at `Publishing` beside another event: a hook at "
                "`Publishing` returns its refusals, and at any other event nothing, "
                "so each is a method of its own"
            )
            raise DoorError(message)
        door.checked(self.taken)
        return Method(self.function, [*self.doors, door], self.taken)

    def events(self) -> list[type[Event]]:
        """Return the events it runs at, as a hook, in the order its doors were put on; none for a tool or a request."""
        return [each.event for each in self.doors if isinstance(each, OnDoor)]

    def tooled(self) -> ToolDoor | None:
        """Return its tool's door; none where it isn't a tool."""
        return next((each for each in self.doors if isinstance(each, ToolDoor)), None)

    def requested(self) -> bool:
        """Say whether it's a request."""
        return any(isinstance(each, RequestDoor) for each in self.doors)

    def spec(self) -> ToolSpec | None:
        """Return what a session is told about it as a tool, with no instance; none where it isn't one."""
        door = self.tooled()
        if door is None:
            return None
        return ToolSpec(
            name=self.taken.name,
            description=self.taken.description or "",
            input_schema=self.taken.model.annotation.model_json_schema(),
            reads=door.reads,
            idempotent=door.idempotent,
        )

    async def called(
        self, instance: BaseModel, value: BaseModel, asker: BaseModel | None
    ) -> Answer:
        """Run the method of `instance` on `value`, handing it `asker` where it takes who asks it.

        Raise `DoorError` where it takes `by` and no one asks.
        """
        if self.taken.by is None:
            return await self.function(instance, value)
        if asker is None:
            message = f"`{self.taken.name}` takes who asks it, `by`, and no one asked"
            raise DoorError(message)
        return await self.function(instance, value, by=asker)

    def tool(
        self, instance: BaseModel, asker: BaseModel | None = None
    ) -> Tool[BaseModel, BaseModel | str]:
        """Return it as a tool of `instance`, asked by `asker`, which validates each call and runs the method.

        Raise `DoorError` where it isn't a tool; a call answering other than a
        model or words fails, saying so.
        """
        door = self.tooled()
        if door is None:
            message = f"`{self.taken.name}` isn't a tool"
            raise DoorError(message)
        name = self.taken.name

        async def answered(value: BaseModel) -> BaseModel | str:
            answer = await self.called(instance, value, asker)
            if isinstance(answer, BaseModel | str):
                return answer
            message = f"the tool `{name}` answered {answer!r}, not a model or words"
            raise DoorError(message)

        return Tool[BaseModel, BaseModel | str](
            name=name,
            description=self.taken.description or "",
            input=self.taken.model.annotation,
            function=answered,
            reads=door.reads,
            idempotent=door.idempotent,
        )


class Served[S, **P, R: Awaitable[Answer]](Method):
    """A method lup serves, typed as written: read through an instance, it's that instance's method; read through its class, the `Method` saying its doors."""

    def __init__(
        self, function: Callable[Concatenate[S, P], R], doors: list[Door], taken: Taken
    ) -> None:
        """Hold the function as written, its doors and what it takes."""
        self.written = function
        super().__init__(function, doors, taken)

    @overload
    def __get__(self, instance: None, owner: type | None = None) -> Self: ...
    @overload
    def __get__(self, instance: S, owner: type | None = None) -> Callable[P, R]: ...
    def __get__(
        self, instance: S | None, owner: type | None = None
    ) -> Self | Callable[P, R]:
        """Return the method of `instance`, or this where read through its class."""
        if instance is None:
            return self
        return partial(self.written, instance)


def first(function: Callable[..., Awaitable[Answer]], door: Door) -> Taken:
    """Return what `function` takes, the first door put on it being `door`.

    Raise `DoorError` where it isn't async, or isn't what the door takes.
    """
    if not inspect.iscoroutinefunction(function):
        message = f"`{function.__name__}` is reached through a door, so it's async"
        raise DoorError(message)
    taken = Taken.of(function)
    door.checked(taken)
    return taken


def opened(method: Method | Callable[..., Awaitable[Answer]], door: Door) -> Method:
    """Return `method`, a function or a method already served, reached through `door` too.

    Raise `DoorError` where it can't be reached through `door`.
    """
    if isinstance(method, Method):
        return method.through(door)
    return Method(method, [door], first(method, door))


def tooled(
    function: Method | Callable[..., Awaitable[BaseModel | str]], door: ToolDoor
) -> Method | AgentTool:
    """Return `function` as a tool: a method served through `door`, or a plain function's `Tool`, carrying its marks.

    Raise `DoorError` where it isn't async, or isn't what a tool takes.
    """
    if isinstance(function, Method):
        return opened(function, door)
    taken = first(function, door)
    if taken.method:
        return Method(function, [door], taken)
    if taken.by is not None:
        message = (
            f"the tool `{taken.name}` takes `by`, which only a module's method, "
            "served to a launched session, is handed"
        )
        raise DoorError(message)
    return Tool[BaseModel, BaseModel | str](
        name=taken.name,
        description=taken.description or "",
        input=taken.model.annotation,
        function=function,
        reads=door.reads,
        idempotent=door.idempotent,
    )


@overload
def tool[I: BaseModel, O: BaseModel | str](
    function: Callable[[I], Awaitable[O]], /
) -> Tool[I, O]: ...
@overload
def tool[S, I: BaseModel, O: BaseModel | str, **P](
    function: Callable[Concatenate[S, I, P], Awaitable[O]], /
) -> Served[S, Concatenate[I, P], Awaitable[O]]: ...
@overload
def tool(*, reads: bool = False, idempotent: bool = False) -> ToolDoor: ...
def tool(
    function: Callable[..., Awaitable[BaseModel | str]] | None = None,
    /,
    *,
    reads: bool = False,
    idempotent: bool = False,
) -> Method | AgentTool | ToolDoor:
    """Make a function a tool, named for it and described by its docstring; given no function, the door, marked, to put on one.

    The function is async, takes one pydantic model and returns another, or
    `str` for an answer in words; a method takes `self` first, and `by` after
    its model where it needs who asks it. Its docstring's first line, standing
    alone, is the tool's summary, 50 characters at most (`summary_of`). A
    method becomes a `Served`, served to each launched session; a plain
    function, a `Tool` an ask serves. `reads` marks a tool that only reads,
    `idempotent` one a call sent again adds nothing to (`ToolDoor`):
    `@lup.tool(reads=True)` marks as `@lup.tool` does.
    """
    door = ToolDoor(reads=reads, idempotent=idempotent)
    return door if function is None else tooled(function, door)


def request[S, I: BaseModel, O: BaseModel, **P](
    method: Callable[Concatenate[S, I, P], Awaitable[O]], /
) -> Served[S, Concatenate[I, P], Awaitable[O]]:
    """Make a method a request: code in a room asks it, sending the model it takes, whose `kind` routes it, and it returns the reply.

    It says who may ask it, `by: Room`: a request has no default askers.
    """
    return RequestDoor()(method)


@overload
def on(event: type[Publishing], /) -> Refusing: ...
@overload
def on[E: Observed](event: type[E], /) -> Observing[E]: ...
def on(event: type[Publishing | Observed], /) -> OnDoor:
    """Return the door of a hook at `event`, to put on a method lup runs then; stacked, the method runs at each.

    The method takes the event, its parameter typed as a union for several. A
    hook at `Publishing` returns its refusals, `list[Refusal]`, an empty list
    letting what would leave go; at any other event it returns nothing.
    """
    if issubclass(event, Publishing):
        return Refusing()
    return Observing(event=event)


def refuse_taken(owner: type, name: str) -> None:
    """Raise `DoorError` where `owner`, or a class it derives from, gives `name` to a field of its model.

    pydantic drops a class's attribute named after a base's field, so a method
    named so would vanish without a word.
    """
    fields = [
        field
        for base in owner.__mro__[1:]
        if issubclass(base, BaseModel)
        for field in base.model_fields
    ]
    if name in fields:
        message = (
            f"`{owner.__name__}`'s method `{name}` takes the name of a field of its "
            "model, which would hide it: name it otherwise"
        )
        raise DoorError(message)


def served(owner: type) -> dict[str, Method]:
    """Return each method `owner`, or a class it derives from, serves, by its name, in the order declared.

    A method a subclass declares again stands in its base's place.
    """
    return {
        name: value
        for klass in reversed(owner.__mro__)
        for name, value in vars(klass).items()
        if isinstance(value, Method)
    }


def declared(owner: type) -> dict[str, ToolSpec]:
    """Return what a session is told about each tool `owner` serves, by its name, with no instance."""
    return {
        name: spec
        for name, method in served(owner).items()
        if (spec := method.spec()) is not None
    }


def bound(instance: BaseModel) -> list[AgentTool]:
    """Return each tool `instance`'s class serves, bound to it, none taking who asks it: the tools of a class made afresh for each call, which knows its caller."""
    tools: list[AgentTool] = [
        method.tool(instance)
        for method in served(type(instance)).values()
        if method.tooled() is not None
    ]
    return tools
