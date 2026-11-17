"""Serving a module's methods, and calling them through their doors: the doors' environment side.

Resolving a declaration lists every part each module serves
(`Doors.of`), refusing a class that can't be made with the module listing it, a
method that can't be behind its door, and what two methods would share: a
tool's or a service's name across the project's modules, an action's or a
command's within one.

Starting what's served (`Doors.started`) makes each class once, with its module
and the secrets it holds, runs what each runs at `Starting`, and carries a
service's call made in it to the class serving it (`Running`). Calling through a
door (`Running.call`, `.act`, `.run`, `.serve`) finds the method, checks who
calls, reads what it's given as the model it takes, and runs it on its class,
answering `Accepted` or `Refused`: what the harness and the containers call
(`README.md` in `lup/doors/`, *Calling through a door*). Stopping
(`Running.stopped`) runs what each runs at `Stopping`, then cancels what it
started.
"""

import asyncio
from contextvars import ContextVar
from typing import override

from pydantic import BaseModel, JsonValue, PydanticUserError, ValidationError

from lup.declaration.errors import ProjectError
from lup.declaration.grammar import listed
from lup.declaration.module import Module
from lup.doors.action import ActionDoor
from lup.doors.command import CommandDoor
from lup.doors.door import (
    Accepted,
    Answer,
    Door,
    DoorError,
    Method,
    Refused,
    RefusedError,
    Rejection,
    served,
)
from lup.doors.events import Event, Starting, Stopping
from lup.doors.on import OnDoor
from lup.doors.parties import Code, Party, said
from lup.doors.parts import Part, Parts
from lup.doors.service import CARRYING, Carrier, ServiceDoor
from lup.doors.tool import ToolDoor, ToolSpec
from lup.types import Model, MutableModel


def refused(given: JsonValue, reason: str) -> Refused:
    """Return a call refused, with what was sent and why."""
    return Refused(rejection=Rejection(submitted=given, reason=reason))


class Serves(Model):
    """One part of a module, with the module listing it."""

    module: Module
    part: type[Part]

    def said(self) -> str:
        """Name the class and its module, as a refusal does."""
        return f"`{self.part.__name__}` of `{self.module.name}`"


class Entry(Model, arbitrary_types_allowed=True):
    """One method a module serves behind a door: its class, with the module, and its name."""

    serves: Serves
    name: str
    method: Method


class Keyed(Model):
    """A name a method is reached by, where it's shared: a tool's or a service's across modules, an action's or a command's within its module."""

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
    """Raise `ProjectError` where the class can't be made with the module listing it: the `module` it declares is typed as another module's class, or names a class that isn't defined."""
    try:
        admitted = serves.part.admits(serves.module)
    except PydanticUserError as undefined:
        message = (
            f"{serves.said()} names a class that isn't defined where it's made: "
            f"{undefined}"
        )
        raise ProjectError(message, about=[serves.module.name]) from undefined
    if not admitted:
        message = (
            f"{serves.said()} types its `module` as another module's class, so it "
            "can't be made with the module listing it"
        )
        raise ProjectError(message, about=[serves.module.name])


class Doors(Model):
    """Every part a project's modules serve, each with its module: what's started, and called through their doors."""

    served: list[Serves] = []

    @classmethod
    def of(cls, modules: list[Module]) -> Doors:
        """Return what `modules` serve, each class with the module listing it.

        Raise `ProjectError` where a class can't be made with the module listing
        it, where a method can't be behind its door once every class its
        annotations name is defined, or where two methods are reached by one
        name: a tool's or a service's across modules, an action's or a command's
        within a module.
        """
        doors = cls(
            served=[
                Serves(module=module, part=part)
                for module in modules
                for part in module.held(Parts)
            ]
        )
        for each in doors.served:
            made_with(each)
        try:
            for entry in doors.entries():
                entry.method.checked()
        except DoorError as wrong:
            raise ProjectError(str(wrong), about=wrong.about) from wrong
        distinct("A tool's name", doors.keyed(ToolDoor))
        distinct("A service's name", doors.keyed(ServiceDoor))
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
            for name, method in served(each.part).items()
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

    async def started(self, repository: str, secrets: dict[str, str]) -> Running:
        """Make each class once, with its module and the value of each secret it holds, run what each runs at `Starting`, and return them running, as the project of `repository`'s code.

        `secrets` holds the value of each secret by its name, as the operator
        stored it for the project. Raise `ProjectError` where a class holds a
        secret it doesn't give.
        """
        running = Running(
            doors=self,
            caller=Code(repository=repository),
            made=[
                Made(serves=each, made=each.part.made(each.module, secrets))
                for each in self.served
            ],
        )
        await running.at(Starting(), apart=True)
        return running


class Made(Model, arbitrary_types_allowed=True):
    """One part of a module, made once where it runs."""

    serves: Serves
    made: Part


CALLER = ContextVar[Party | None]("caller", default=None)
"""Whose code runs here, where it's a module's: the party a service it calls is
called by."""


class Running(MutableModel, Carrier, arbitrary_types_allowed=True):
    """What a project's modules serve, each class made once and running: its doors called, and the services its code calls carried to their class.

    A service's call made in the code it runs is carried to the class serving
    it, here, as the project's own code (`caller`); a call from elsewhere comes
    through `serve`, with whoever carries it vouching for its caller.
    """

    doors: Doors
    caller: Code
    """The project whose code this is: who a service's call made here is
    by."""
    made: list[Made]
    started: list[asyncio.Task[None]] = []
    """What each class runs at `Starting`, going on as long as it runs."""

    def instance(self, entry: Entry) -> Part:
        """Return the class `entry` belongs to, as it was made here."""
        return next(each.made for each in self.made if each.serves == entry.serves)

    def tools(self) -> list[ToolSpec]:
        """Return what a session is told of each tool the modules serve."""
        return self.doors.tools()

    async def at(self, event: Event, *, apart: bool = False) -> None:
        """Run every method run at `event`'s class, each on its class: one after another, or, `apart`, each as a task that goes on as long as the class runs."""
        for entry in self.doors.through(OnDoor):
            door = entry.method.door
            if not (isinstance(door, OnDoor) and isinstance(event, door.event)):
                continue
            hook = self.hooked(entry, event)
            if apart:
                self.started.append(asyncio.create_task(hook))
            else:
                await hook

    async def hooked(self, entry: Entry, event: Event) -> None:
        """Run the method behind `entry` at `event`, on its class: nobody calls it, so it's handed no caller."""
        await self.ran(entry.method, self.instance(entry), event, self.caller)

    async def stopped(self) -> None:
        """Run every method run at `Stopping`, one after another, then cancel what each class runs since `Starting`, and wait for it to end."""
        await self.at(Stopping())
        for task in self.started:
            task.cancel()
        await asyncio.gather(*self.started, return_exceptions=True)
        self.started = []

    async def ran(
        self,
        method: Method,
        instance: Part,
        value: BaseModel | list[BaseModel],
        by: Party,
    ) -> Answer:
        """Run `method` of `instance` on `value`, handed `by`, as this project's code: a service it calls is carried here."""
        carrying = CARRYING.set(self)
        calling = CALLER.set(self.caller)
        try:
            return await method.called(instance, value, by)
        finally:
            CALLER.reset(calling)
            CARRYING.reset(carrying)

    async def answered(
        self, entry: Entry, given: JsonValue, by: Party
    ) -> Accepted | Refused:
        """Run the method behind `entry` on `given`, called by `by`, and say what came of it.

        Refused where `by` isn't who it's for, where `given` isn't what it
        takes, and where the method refuses (`RefusedError`); whatever else it
        raises goes up as raised.
        """
        method = entry.method
        if not method.admits(by):
            reason = (
                f"`{method.taken.qualified}` of `{entry.serves.module.name}` is "
                f"called by {said(method.parties())}, never by `{type(by).__name__}`"
            )
            return refused(given, reason)
        try:
            value = method.validated(given)
        except ValidationError as wrong:
            reason = f"`{entry.name}` doesn't take what it was given: {wrong}"
            return refused(given, reason)
        try:
            output = await self.ran(method, self.instance(entry), value, by)
        except RefusedError as refusal:
            return refused(given, str(refusal))
        return Accepted(value=value, output=output)

    async def call(
        self, tool: str, arguments: JsonValue, by: Party
    ) -> Accepted | Refused:
        """Call the tool named `tool` with `arguments`, called by `by`, and say what came of it."""
        found = [entry for entry in self.doors.through(ToolDoor) if entry.name == tool]
        if not found:
            return refused(arguments, f"no module serves a tool `{tool}`")
        return await self.answered(found[0], arguments, by)

    async def serve(
        self, service: str, given: JsonValue, by: Party
    ) -> Accepted | Refused:
        """Call the service named `service` on `given`, called by `by`, and say what came of it."""
        found = [
            entry for entry in self.doors.through(ServiceDoor) if entry.name == service
        ]
        if not found:
            return refused(given, f"no module serves a service `{service}`")
        return await self.answered(found[0], given, by)

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
        within = [
            entry
            for entry in self.doors.through(door)
            if entry.serves.module.name == module
        ]
        found = [entry for entry in within if entry.name == name]
        if not found:
            names = [entry.name for entry in within]
            reason = (
                f"`{name}` isn't {door.called} of `{module}`, whose are {listed(names)}"
            )
            return refused(given, reason)
        return await self.answered(found[0], given, by)

    @override
    async def carried(self, method: Method, value: BaseModel) -> Answer | JsonValue:
        """Carry a service's call made in this project's code to the class serving it, here, as the project's code.

        Raise `RefusedError` where it's refused.
        """
        found = [entry for entry in self.doors.entries() if entry.method is method]
        if not found:
            name = method.taken.qualified
            message = f"`{name}` isn't served by any module of this project"
            raise RefusedError(message, about=[name])
        answered = await self.answered(
            found[0], value.model_dump(mode="json"), CALLER.get() or self.caller
        )
        match answered:
            case Refused(rejection=rejection):
                raise RefusedError(rejection.reason, about=[method.taken.qualified])
            case Accepted(output=output):
                return output
