"""Serving a module's methods, and calling them through their doors: the doors' environment side.

Resolving a declaration lists every class of methods each module serves
(`Doors.of`), each made with its module, refusing what two methods would share:
a tool's name across the project's modules, an action's or a command's name
within one. Calling through a door (`Doors.call`, `.act` and `.run`) finds the
method, checks who calls, reads what it's given as the model it takes, and runs
it on its class made afresh, answering `Accepted` or `Refused`: what the harness
and the services call (`README.md` in `lup/doors/`, *Calling through a door*).
"""

from pydantic import JsonValue, PydanticUserError, ValidationError

from lup.declaration.errors import ProjectError
from lup.declaration.grammar import listed
from lup.declaration.module import Module
from lup.doors.action import ActionDoor
from lup.doors.command import CommandDoor
from lup.doors.door import (
    Accepted,
    Door,
    DoorError,
    Method,
    Refused,
    RefusedError,
    Rejection,
    served,
)
from lup.doors.parties import Party, said
from lup.doors.serving import ModuleServing, Serving
from lup.doors.tool import ToolDoor, ToolSpec
from lup.types import Model


def refused(given: JsonValue, reason: str) -> Refused:
    """Return a call refused, with what was sent and why."""
    return Refused(rejection=Rejection(submitted=given, reason=reason))


class Serves(Model):
    """One class of a module's methods, with the module it's made with."""

    module: Module
    serving: type[ModuleServing]

    def made(self) -> ModuleServing:
        """Make the class afresh with its module, for one call."""
        return self.serving(module=self.module)

    def said(self) -> str:
        """Name the class and its module, as a refusal does."""
        return f"`{self.serving.__name__}` of `{self.module.name}`"


class Entry(Model, arbitrary_types_allowed=True):
    """One method a module serves behind a door: its class, with the module, and its name."""

    serves: Serves
    name: str
    method: Method

    async def answered(self, given: JsonValue, by: Party) -> Accepted | Refused:
        """Run the method on `given`, called by `by`, and say what came of it.

        Refused where `by` isn't who it's for, where `given` isn't what it
        takes, and where the method refuses (`RefusedError`); whatever else it
        raises goes up as raised.
        """
        method = self.method
        if not method.admits(by):
            reason = (
                f"`{method.taken.qualified}` of `{self.serves.module.name}` is called "
                f"by {said(method.parties())}, never by `{type(by).__name__}`"
            )
            return refused(given, reason)
        try:
            value = method.validated(given)
        except ValidationError as wrong:
            reason = f"`{self.name}` doesn't take what it was given: {wrong}"
            return refused(given, reason)
        try:
            output = await method.called(self.serves.made(), value, by)
        except RefusedError as refusal:
            return refused(given, str(refusal))
        return Accepted(value=value, output=output)


class Keyed(Model):
    """A name a method is reached by, where it's shared: a tool's across modules, an action's or a command's within its module."""

    name: str
    scope: str = ""
    """The module whose names it shares, by its name; none where it's every
    module's."""
    entry: Entry


def distinct(what: str, keyed: list[Keyed]) -> None:
    """Raise `ProjectError` where two methods are reached by one name, naming both."""
    pairs = [
        (one, other)
        for at, one in enumerate(keyed)
        for other in keyed[at + 1 :]
        if one.scope == other.scope and one.name == other.name
    ]
    if pairs:
        clashes = [
            f"`{one.name}` by {one.entry.serves.said()} and {other.entry.serves.said()}"
            for one, other in pairs
        ]
        message = (
            f"{what} is one method's, and {'; '.join(clashes)} share one: drop or "
            "rename one"
        )
        about = [each.entry.serves.module.name for pair in pairs for each in pair]
        raise ProjectError(message, about=list(dict.fromkeys(about)))


def made_with(serves: Serves) -> None:
    """Raise `ProjectError` where the class can't be made with the module listing it: its `module` is narrowed to another's, or names a class that isn't defined."""
    try:
        serves.made()
    except ValidationError as wrong:
        message = (
            f"{serves.said()} narrows its `module` to another module's class, so "
            f"it can't be made with the module listing it: {wrong}"
        )
        raise ProjectError(message, about=[serves.module.name]) from wrong
    except PydanticUserError as undefined:
        message = (
            f"{serves.said()} names a class that isn't defined where it's made: "
            f"{undefined}"
        )
        raise ProjectError(message, about=[serves.module.name]) from undefined


class Doors(Model):
    """Every class of methods a project's modules serve, each with its module: what's called through their doors."""

    served: list[Serves] = []

    @classmethod
    def of(cls, modules: list[Module]) -> Doors:
        """Return what `modules` serve, each class with the module listing it.

        Raise `ProjectError` where a class can't be made with the module listing
        it, where a method can't be behind its door once every class its
        annotations name is defined, or where two methods are reached by one
        name: a tool's across modules, an action's or a command's within a
        module.
        """
        doors = cls(
            served=[
                Serves(module=module, serving=serving)
                for module in modules
                for serving in module.held(Serving)
            ]
        )
        for each in doors.served:
            made_with(each)
        try:
            for entry in doors.entries():
                # lup: ignore("B018", why="reading a method's `taken` checks it against its door, which resolving does of every method once every class its annotations name is defined")
                entry.method.taken
        except DoorError as wrong:
            raise ProjectError(str(wrong), about=wrong.about) from wrong
        distinct("A tool's name", doors.keyed(ToolDoor))
        distinct("An action's name in its module", doors.keyed(ActionDoor, scoped=True))
        distinct(
            "A command's name in its module", doors.keyed(CommandDoor, scoped=True)
        )
        return doors

    def entries(self) -> list[Entry]:
        """List every method each class serves behind a door, in the order of their modules."""
        return [
            Entry(serves=each, name=name, method=method)
            for each in self.served
            for name, method in served(each.serving).items()
        ]

    def through(self, door: type[Door]) -> list[Entry]:
        """List every method behind a door of `door`'s class."""
        return [
            entry for entry in self.entries() if isinstance(entry.method.door, door)
        ]

    def keyed(self, door: type[Door], *, scoped: bool = False) -> list[Keyed]:
        """List every method behind a door of `door`'s class by its name, within its module where `scoped`."""
        return [
            Keyed(
                name=entry.name,
                scope=entry.serves.module.name if scoped else "",
                entry=entry,
            )
            for entry in self.through(door)
        ]

    def tools(self) -> list[ToolSpec]:
        """Return what a session is told of each tool the modules serve."""
        return [
            entry.method.door.spec(entry.method.taken)
            for entry in self.entries()
            if isinstance(entry.method.door, ToolDoor)
        ]

    async def call(
        self, tool: str, arguments: JsonValue, by: Party
    ) -> Accepted | Refused:
        """Call the tool named `tool` with `arguments`, called by `by`, and say what came of it."""
        found = [entry for entry in self.through(ToolDoor) if entry.name == tool]
        if not found:
            return refused(arguments, f"no module serves a tool `{tool}`")
        return await found[0].answered(arguments, by)

    async def act(
        self, module: str, action: str, given: JsonValue, by: Party
    ) -> Accepted | Refused:
        """Run the action `action` of the module named `module` on `given`, called by `by`, and say what came of it."""
        return await self.reached(ActionDoor, module, action, given, by)

    async def run(
        self, module: str, command: str, arguments: JsonValue, by: Party
    ) -> Accepted | Refused:
        """Run the command `command` of the module named `module` with `arguments`, called by `by`, and say what came of it.

        A command takes everything as arguments: one it needs and isn't given
        is refused at once, naming it, never asked for.
        """
        return await self.reached(CommandDoor, module, command, arguments, by)

    async def reached(
        self, door: type[Door], module: str, name: str, given: JsonValue, by: Party
    ) -> Accepted | Refused:
        """Run the method named `name` behind a door of `door`'s class of the module named `module` on `given`, called by `by`."""
        found = [
            entry
            for entry in self.through(door)
            if entry.serves.module.name == module and entry.name == name
        ]
        if not found:
            names = [
                entry.name
                for entry in self.through(door)
                if entry.serves.module.name == module
            ]
            reason = (
                f"`{name}` isn't {door.called} of `{module}`, whose are {listed(names)}"
            )
            return refused(given, reason)
        return await found[0].answered(given, by)
