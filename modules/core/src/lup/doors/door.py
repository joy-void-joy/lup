"""What every door shares: reading a method's signature, the method served through its door, and the checks as a door is put on it.

A door is a class deriving from `Door`, a model of its settings: whom it brings
(`through`), whom a method leaving `by` out is for (`default`), and what it
holds a method to beyond what every door does (`contract`). Called on a method,
it makes a `Served`: a property of the method's class which, read through an
instance, is that instance's method, called as any, and read through the class,
the `Method` saying its door and what it takes. Adding a door is adding such a
class (`README.md` here, *A method behind a door*).
"""

import inspect
from annotationlib import Format, type_repr
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from functools import cache, partial
from string.templatelib import Template
from types import GenericAlias, UnionType
from typing import ClassVar, Concatenate, Self, TypeIs, get_args, get_origin, overload

from pydantic import BaseModel, JsonValue, SerializeAsAny, TypeAdapter

from lup.doors.parties import Party
from lup.errors import LupError
from lup.types import Model
lazy from lup.doors.parts import Part

type Answer = BaseModel | str | None
"""What a method a party calls through a door answers: a model, words, or
nothing, as its door allows."""

type Returned = Answer | Template | bool
"""What a method behind any door returns: what a party's call answers, a
section of guidance's template (`lup.told`), or a law's verdict
(`lup.testing`), neither of which a party calls."""

type Function = Callable[..., Awaitable[Returned] | bool]
"""A method as a door takes it: async, or, where its door allows, a law's
predicate, which answers its verdict at once."""

type Annotation = type | GenericAlias | UnionType | None
"""A type as a signature writes it: a class, a generic alias (`list[Said]`), a
union, or `None`."""


class DoorError(LupError):
    """A method can't be reached through a door: it isn't what the door takes or returns, or doesn't say who may call it where the door needs it to."""


class RefusedError(LupError):
    """A method won't do what it was asked, raised from its body: the call through its door answers `Refused`, its message saying why."""


def spelled(annotation: Annotation) -> str:
    """Say a type as a signature writes it, for a door's refusal.

    >>> spelled(int | None), spelled(list[str])
    ('`int | None`', '`list[str]`')
    """
    return f"`{type_repr(annotation)}`"


def is_model(annotation: Annotation) -> TypeIs[type[BaseModel]]:
    """Say whether an annotation is a pydantic model's class.

    >>> is_model(Model), is_model(str), is_model(list[Model])
    (True, False, False)
    """
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def shaped(
    function: Function, *, by_alone: bool = False, nothing: bool = False
) -> None:
    """Raise `DoorError` where `function` can't be behind a door of the usual shape, whatever its types say.

    A method behind such a door is async, and takes what `taking` says.
    """
    if not inspect.iscoroutinefunction(function):
        message = f"`{function.__qualname__}` is reached through a door, so it's async"
        raise DoorError(message)
    taking(function, by_alone=by_alone, nothing=nothing)


def taking(
    function: Function, *, by_alone: bool = False, nothing: bool = False
) -> None:
    """Raise `DoorError` where `function` doesn't take what a method behind a door takes, whatever its types say.

    It takes `self`, one model, then `by` where it needs who calls it, each
    annotated, says what it returns, and has a docstring; with `by_alone`, one
    taking `by` and no model fits too, as a scenario does (`lup.testing`), and
    with `nothing`, one taking nothing at all, as a section of guidance may
    (`lup.told`). Its annotations aren't evaluated here: one may name a class
    defined further down its file, which is read later (`Method.taken`).
    """
    name = function.__qualname__
    signature = inspect.signature(function, annotation_format=Format.FORWARDREF)
    parameters = list(signature.parameters.values())
    match parameters:
        case [inspect.Parameter(name="self"), inspect.Parameter(name="by")] if by_alone:
            pass
        case [inspect.Parameter(name="self")] if nothing:
            pass
        case [inspect.Parameter(name="self"), inspect.Parameter(name=given)] if (
            given != "by"
        ):
            pass
        case [inspect.Parameter(name="self"), _, inspect.Parameter(name="by")]:
            pass
        case [inspect.Parameter(name="self"), *taken]:
            named = ", ".join(f"`{each.name}`" for each in taken) or "nothing"
            alone = ", or `by` alone" if by_alone else ""
            message = (
                f"`{name}` takes {named}: a method behind its door takes one model, "
                f"then, where it needs who calls it, `by`{alone}"
            )
            raise DoorError(message)
        case _:
            message = f"`{name}` takes no `self`: a door is put on a method of a class"
            raise DoorError(message)
    bare = [
        f"`{each.name}`"
        for each in parameters[1:]
        if each.annotation is inspect.Parameter.empty
    ]
    if signature.return_annotation is inspect.Signature.empty:
        bare.append("what it returns")
    if bare:
        message = (
            f"`{name}` leaves {', '.join(bare)} without a type: its door reads "
            "each, so pyright and lup hold it to the door's contract"
        )
        raise DoorError(message)
    if not inspect.getdoc(function):
        message = (
            f"`{name}` needs a docstring: it describes it to whoever its door "
            "brings, an agent reading a tool, the operator a command's help"
        )
        raise DoorError(message)


class Taken(Model, arbitrary_types_allowed=True):
    """What a method behind a door takes and returns, its annotations evaluated."""

    name: str
    """The method's name: a tool's, a service's or a command's, which it's
    called by."""
    qualified: str
    """Its name within its class, as a refusal names it: `EchoPart.shout`."""
    description: str
    """Its docstring, which describes it: what an agent reads of a tool."""
    model: inspect.Parameter | None
    """The parameter taking its model: a tool's input, a command's arguments or one mark of a send, a
    command's arguments or a law's value; none where it takes `by` alone, as a
    scenario does."""
    by: inspect.Parameter | None
    """The parameter taking who calls it, typed as who may; none where it's left
    out, and its door's default callers may."""
    returned: Annotation
    """Its return annotation, as written."""

    @classmethod
    def of(cls, function: Function) -> Taken:
        """Read what `function`, shaped as a door takes it (`shaped`), takes and returns.

        Raise `NameError` where an annotation names a class that isn't defined
        (yet), and `DoorError` where what it returns isn't a type.
        """
        signature = inspect.signature(function)
        taken = list(signature.parameters.values())[1:]
        returned = signature.return_annotation
        if not (
            returned is None or isinstance(returned, type | GenericAlias | UnionType)
        ):
            message = (
                f"`{function.__qualname__}` returns {returned!r}, which isn't a type"
            )
            raise DoorError(message)
        return cls(
            name=function.__name__,
            qualified=function.__qualname__,
            description=inspect.getdoc(function) or "",
            model=next((each for each in taken if each.name != "by"), None),
            by=next((each for each in taken if each.name == "by"), None),
            returned=returned,
        )

    def given(self) -> inspect.Parameter:
        """Return the parameter taking its model.

        Raise `DoorError` where it takes `by` alone, which only a door of
        another shape takes.
        """
        if self.model is None:
            message = (
                f"`{self.qualified}` takes `by` alone, where its door takes a model "
                "first"
            )
            raise DoorError(message)
        return self.model

    def answers_model(self) -> bool:
        """Say whether it returns a pydantic model."""
        return is_model(self.returned)

    def gathers(self) -> bool:
        """Say whether it takes a list of its model, as a command the dashboard gives every mark of a send at once does."""
        return get_origin(self.given().annotation) is list

    def one(self) -> Annotation:
        """Return the type of the model it takes, or, where it takes a list of it, of each."""
        annotation = self.given().annotation
        return get_args(annotation)[0] if self.gathers() else annotation

    def spelled_model(self) -> str:
        """Say its model parameter, as a refusal names it: `said` typed `Said`."""
        model = self.given()
        return f"`{model.name}` typed {spelled(model.annotation)}"


class Door(Model):
    """A door a method is reached through: what it holds a method to, and who may call one that doesn't say.

    Each door is a subclass, a model of its settings (`@lup.tool(reads=True)`),
    called on the method it's put on, with a signature typed with its contract.
    """

    called: ClassVar[str]
    """What the door makes a method, as a refusal names it: `a tool`."""
    default: ClassVar[list[type[Party]]] = []
    """Who may call a method leaving `by` out; none where each method says, as a
    command does."""
    named_across: ClassVar[bool] = False
    """Whether a method behind it is reached by its name across every module, as
    an agent names a tool, so two modules' can't share one; else within its
    module, whose name comes with it."""

    def shaped(self, function: Function) -> None:
        """Raise `DoorError` where `function` can't be behind this door, whatever its types say: as it's put on, with no annotation evaluated.

        Most doors take the usual shape (`shaped`); a door of another shape says
        its own here, as a promise's does.
        """
        shaped(function)

    def contract(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't what this door takes and returns."""

    def checked(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't what this door takes and returns, or doesn't say who may call it."""
        self.contract(taken)
        self.parties(taken)

    def parties(self, taken: Taken) -> list[type[Party]]:
        """Return who may call a method taking what `taken` says: the parties its `by` names, or this door's default where it leaves `by` out.

        Raise `DoorError` where `by` is typed as other than parties' classes, or
        is left out where this door has no default.
        """
        if taken.by is None:
            if not self.default:
                message = (
                    f"`{taken.qualified}` is {self.called}, which says who may call "
                    "it: `by` typed as a party, `by: Agent`, or a union of them"
                )
                raise DoorError(message)
            return self.default
        annotation = taken.by.annotation
        typed = (
            get_args(annotation) if isinstance(annotation, UnionType) else [annotation]
        )
        found: list[type[Party]] = [
            each
            for each in typed
            if isinstance(each, type) and issubclass(each, Party) and each is not Party
        ]
        if len(found) != len(typed):
            message = (
                f"`{taken.qualified}` takes `by` typed {spelled(annotation)}: who "
                "calls is a party, a class deriving from `Party` such as `Agent`, or "
                "a union of them"
            )
            raise DoorError(message)
        return found


class Method(property):
    """A method behind a door, read through its class: its function, its door, and what it takes.

    A property of its class, so a pydantic model holds it as it holds any
    property, not as a field, and its class lists it among its attributes, which
    is how a class's methods are found (`served`).
    """

    def __init__(self, function: Function, door: Door) -> None:
        """Put `door` on `function`, checking it as far as its annotations are defined yet.

        Raise `DoorError` where it can't be behind the door, or is behind
        another already.
        """
        if isinstance(function, Method):
            name = function.function.__qualname__
            message = (
                f"`{name}` is {function.door.called} already, and can't be "
                f"{door.called} too: a method is reached through one door"
            )
            raise DoorError(message, about=[name])
        self.function = function
        self.door = door
        with self.named():
            door.shaped(function)
            self.known = self.attempted()
        super().__init__(self.bound)

    @contextmanager
    def named(self) -> Generator[None]:
        """Name the method as what a `DoorError` raised within is about, where it names nothing yet."""
        try:
            yield
        except DoorError as wrong:
            wrong.about = wrong.about or [self.function.__qualname__]
            raise

    def attempted(self) -> Taken | None:
        """Read what the method takes and check it against its door; none where an annotation names a class not defined yet."""
        try:
            return self.read()
        except NameError:
            return None

    def read(self) -> Taken:
        """Read what the method takes and check it against its door."""
        taken = Taken.of(self.function)
        self.door.checked(taken)
        return taken

    @property
    def taken(self) -> Taken:
        """What the method takes and returns, its door's checks passed (`checked`)."""
        return self.checked()

    def checked(self) -> Taken:
        """Return what the method takes and returns, checked against its door.

        Read as the door is put on, or, where an annotation names a class defined
        further down its file, the first time it's needed: resolving a
        declaration checks every method its modules serve. Raise `DoorError`
        where it isn't what its door takes, or where an annotation names what's
        never defined where the method runs, as an import under `TYPE_CHECKING`
        alone is.
        """
        if self.known is None:
            name = self.function.__qualname__
            try:
                with self.named():
                    self.known = self.read()
            except NameError as unnamed:
                message = (
                    f"`{name}`'s annotations name `{unnamed.name}`, which isn't "
                    "defined where it runs: its door reads them, so import it "
                    "outside `TYPE_CHECKING`"
                )
                raise DoorError(message, about=[name]) from unnamed
        return self.known

    def bound(self, instance: BaseModel) -> Function:
        """Return the method of `instance`."""
        return partial(self.function, instance)

    def __set_name__(self, owner: type, name: str) -> None:
        """Refuse a class that isn't a part, which nothing serves, and a name a base of its class gives a field, which would hide the method."""
        refuse_unserved(owner, name, self.door)
        refuse_taken(owner, name)

    def parties(self) -> list[type[Party]]:
        """Return who may call it: the parties its `by` names, or its door's default."""
        return self.door.parties(self.taken)

    def admits(self, by: Party) -> bool:
        """Say whether `by` may call it."""
        return isinstance(by, tuple(self.parties()))

    def validated(self, given: JsonValue) -> BaseModel | list[BaseModel]:
        """Return `given` as the model the method takes, or a list of it.

        Raise pydantic's `ValidationError` where it isn't.
        """
        model = self.taken.given().annotation
        return TypeAdapter[BaseModel | list[BaseModel]](model).validate_python(given)

    async def called(
        self, instance: BaseModel, value: BaseModel | list[BaseModel], by: Party
    ) -> Answer:
        """Run the method of `instance` on `value`, handing it `by` where it takes who calls it.

        Raise `DoorError` where it answers a verdict or a template, as only a
        law or a section of guidance does: no party calls either.
        """
        if self.taken.by is None:
            called = self.function(instance, value)
        else:
            called = self.function(instance, value, by=by)
        answered = called if isinstance(called, bool) else await called
        if isinstance(answered, bool | Template):
            message = (
                f"`{self.taken.qualified}` answers a verdict or a template, as a "
                "law or a section of guidance does, which no party calls"
            )
            raise DoorError(message)
        return answered


class Served[S, **P, R: Awaitable[Returned] | bool](Method):
    """A method behind a door, typed as written: read through an instance, it's that instance's method; read through its class, the `Method` saying its door."""

    def __init__(self, function: Callable[Concatenate[S, P], R], door: Door) -> None:
        """Hold the function as written, behind `door`."""
        self.written = function
        super().__init__(function, door)

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


def refuse_unserved(owner: type, name: str, door: Door) -> None:
    """Raise `DoorError` where `owner` isn't a part: nothing serves a method behind a door of another class, so it would go unserved, and a promise unchecked, without a word."""
    if issubclass(owner, Part):
        return
    method = f"{owner.__qualname__}.{name}"
    message = (
        f"`{method}` is {door.called}, but `{owner.__qualname__}` isn't a part, so "
        "nothing serves it: put it in a class deriving from `Part`, which its "
        "module lists in `parts`"
    )
    raise DoorError(message, about=[method])


def refuse_taken(owner: type, name: str) -> None:
    """Raise `DoorError` where a class `owner` derives from gives `name` to a field of its model.

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


@cache
def served(owner: type) -> dict[str, Method]:
    """Return each method `owner`, or a class it derives from, serves behind a door, by its name, in the order declared.

    A method a subclass declares again stands in its base's place. A class's
    methods don't change once it's made, so each class's are read once, where
    every slice of a run asks them again.
    """
    return {
        name: value
        for klass in reversed(owner.__mro__)
        for name, value in vars(klass).items()
        if isinstance(value, Method)
    }


class Rejection(Model):
    """One refused call: what was sent, and why it was refused.

    `submitted` is what the caller sent, whether or not it reads as what the
    method takes.
    """

    submitted: JsonValue
    reason: str


class Accepted(Model):
    """A call a method behind a door ran: what it was given, read as its model, and what it answered."""

    value: SerializeAsAny[BaseModel] | list[SerializeAsAny[BaseModel]]
    """What it was given, as the model it takes, or a list of it."""
    output: SerializeAsAny[BaseModel] | str | None
    """What it answered: a model, words, or nothing, as its door allows."""

    def answer(self) -> str:
        """Return what a caller reads of the answer: its words, a model's JSON, or nothing.

        >>> class Said(Model):
        ...     text: str
        >>> Accepted(value=Said(text="hi"), output="Filed.").answer()
        'Filed.'
        >>> Accepted(value=Said(text="hi"), output=Said(text="hi")).answer()
        '{"text":"hi"}'
        """
        match self.output:
            case str() as words:
                return words
            case BaseModel() as model:
                return model.model_dump_json()
            case None:
                return ""


class Refused(Model):
    """A call refused before the method ran, or by the method itself (`RefusedError`): what was sent, and why."""

    rejection: Rejection
