"""A launch's own process, serving its modules: their tools, their answers to its room's requests, and their hooks.

The host service starts it from the launch's repository's approved copy,
`<judge> worker <socket>` (`lup_dev.host.workers`), the launch's registration on
its input's first line. It loads the declaration the launch's hooks are judged
by, at the commit the operator approved with the person's own layer approved
beside it, makes each module's tools, handlers and hooks from it, says it's ready
on its output's first line, and answers one request per connection on `<socket>`
until its input closes, which it does when the service ends it or dies.

Each call makes the tools' class afresh, with its module, the launch and the
conversation calling, so a tool reads them through `self`. A tool that can't do
its work raises a `LupDevError`, whose message is its answer; anything else that
fails is told the host service's way, its traceback said.

Each occasion makes each listening class of hooks afresh, with its module, the
launch, where the launch's runtime keeps its records, and the module's own data
directory for the repository, and runs its hooks at that moment in the order
they're declared. A hook that fails is told back whole, and the others still run.
"""

import asyncio
import sys
import traceback
from typing import TYPE_CHECKING, override

from lup.tools.serving import Answer
from lup.tools.tool import Accepted, Refused
from lup.types import Model
from lup_dev.declaration.load import load
from lup_dev.declaration.resolve import Handled, Hooked, Resolved, Served, resolve
from lup_dev.declaration.serving import (
    HEARD,
    ModuleHooks,
    Moment,
    MomentName,
    answering,
    at,
    listening,
)
from lup_dev.errors import LupDevError
from lup_dev.host.protocol import Register, Reply
from lup_dev.host.records import Records
from lup_dev.host.service import Dispatcher, Handler, Route
from lup_dev.host.watch import Changes
from lup_dev.host.workers import (
    Called,
    Calling,
    Happened,
    Happening,
    Listing,
    Occasion,
    Offered,
    Relayed,
    Relaying,
    Sent,
)
from lup_dev.layout import Layout
from lup_dev.policy.checkpoint import Services, Worktree

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path


def moment(occasion: Occasion) -> MomentName:
    """Return the moment of lup's that an occasion the service tells is."""
    match occasion:
        case "launched" | "stopped":
            return occasion
        case _:
            return HEARD[occasion]


async def attempted(made: ModuleHooks, name: str, now: Moment) -> str | None:
    """Run the hook `name` of `made` at `now`; return why it failed, or none.

    A hook's failure is told back whole, its traceback with it, and doesn't keep
    the next from running.
    """
    hook: Callable[[Moment], Awaitable[None]] = getattr(made, name)
    try:
        await hook(now)
    except Exception:
        return (
            f"`{type(made).__name__}.{name}` failed at {now.name}:\n"
            f"{traceback.format_exc()}"
        )
    return None


class Serving(Model, arbitrary_types_allowed=True):
    """A launch's modules, as its declaration resolves them: what they serve, and each answer."""

    launch: Register
    resolved: Resolved
    records: Records
    """Where the launch's runtime keeps its sessions' records."""
    layout: Layout
    """Where lup keeps its data, each module's own among it."""

    @classmethod
    def loaded(cls, launch: Register, services: Services, records: Records) -> Serving:
        """Load the declaration `launch`'s hooks are judged by, and resolve it whole.

        Raise `ProjectError` where it doesn't load or resolve.
        """
        worktree = Worktree.of(launch.worktree, launch.repository, services)
        root = worktree.loaded.root
        return cls(
            launch=launch,
            resolved=resolve(load(root).project),
            records=records,
            layout=services.layout,
        )

    def offered(self) -> Offered:
        """Return what the modules serve: each tool, each kind of request, and each occasion their hooks run at."""
        listened = [
            each for hooked in self.resolved.hooked for each in listening(hooked.hooks)
        ]
        told: list[Occasion] = ["launched", "stopped", *HEARD]
        return Offered(
            tools=[
                spec for each in self.resolved.served for spec in each.tools.specs()
            ],
            kinds=[answering(each.handler).named() for each in self.resolved.handled],
            occasions=[each for each in told if moment(each) in listened],
        )

    def serving(self, name: str) -> Served | None:
        """Return the class of tools serving the tool `name`, with its module; none where none does."""
        return next(
            (
                each
                for each in self.resolved.served
                if any(spec.name == name for spec in each.tools.specs())
            ),
            None,
        )

    def answering(self, kind: str) -> Handled | None:
        """Return the handler answering requests of `kind`, with its module; none where none does."""
        return next(
            (
                each
                for each in self.resolved.handled
                if answering(each.handler).named() == kind
            ),
            None,
        )

    async def call(self, calling: Calling) -> Answer:
        """Run one call to a module's tool, and return what the agent reads."""
        name = calling.name
        owner = self.serving(name)
        if owner is None:
            return Answer(text=f"no module of this launch serves `{name}`", error=True)
        made = owner.tools(
            module=owner.module, launch=self.launch, caller=calling.caller
        )
        [tool] = [tool for tool in made.tools() if tool.spec().name == name]
        try:
            result = await tool.call(calling.arguments)
        except LupDevError as failed:
            return Answer(text=f"`{name}` didn't run: {failed}", error=True)
        match result:
            case Accepted(answer=answer):
                return Answer(text=answer)
            case Refused(rejection=rejection):
                return Answer(
                    text=f"`{name}` refused the call: {rejection.reason}", error=True
                )

    async def answer(self, sent: Sent) -> Reply:
        """Answer one room's request with the module's handler for its kind.

        Raise `LupDevError` where no module answers its kind.
        """
        owner = self.answering(sent.kind)
        if owner is None:
            message = f"no module of this launch answers `{sent.kind}`"
            raise LupDevError(message)
        model = answering(owner.handler)
        request = model.model_validate(sent.model_dump())
        made = owner.handler(module=owner.module, launch=self.launch, request=request)
        return await made.answer()

    async def happen(self, happening: Happening) -> Happened:
        """Run every hook at the moment `happening` tells, and return what failed among them."""
        now = Moment(
            name=moment(happening.occasion),
            conversation=happening.conversation,
            call=happening.call,
            tool=happening.tool,
        )
        failures = [
            failure
            for hooked in self.resolved.hooked
            for failure in await self.ran(hooked, now)
        ]
        return Happened(failures=failures)

    async def ran(self, hooked: Hooked, now: Moment) -> list[str]:
        """Run one class's hooks at `now`, made afresh with its module's data directory; return what failed."""
        data = self.layout.module_data(hooked.module.name, self.launch.repository)
        data.mkdir(parents=True, exist_ok=True)
        made = hooked.hooks(
            module=hooked.module, launch=self.launch, records=self.records, data=data
        )
        return [
            failure
            for name in at(made, now.name)
            if (failure := await attempted(made, name, now)) is not None
        ]


class Listed(Model, Handler[Listing]):
    """Answers `Listing`: what the modules serve."""

    modules: Serving

    @override
    def request(self) -> type[Listing]:
        return Listing

    @override
    async def answer(self, request: Listing) -> Reply:
        return self.modules.offered()


class Calls(Model, Handler[Calling]):
    """Answers `Calling`: one call to a module's tool."""

    modules: Serving

    @override
    def request(self) -> type[Calling]:
        return Calling

    @override
    async def answer(self, request: Calling) -> Reply:
        return Called(answer=await self.modules.call(request))


class Relays(Model, Handler[Relaying]):
    """Answers `Relaying`: one room's request, passed to the module answering its kind."""

    modules: Serving

    @override
    def request(self) -> type[Relaying]:
        return Relaying

    @override
    async def answer(self, request: Relaying) -> Reply:
        sent = Sent.model_validate(request.request)
        reply = await self.modules.answer(sent)
        return Relayed(reply=reply.model_dump())


class Happens(Model, Handler[Happening]):
    """Answers `Happening`: the modules' hooks run at its moment."""

    modules: Serving

    @override
    def request(self) -> type[Happening]:
        return Happening

    @override
    async def answer(self, request: Happening) -> Reply:
        return await self.modules.happen(request)


async def serve(modules: Serving, socket: Path, say: Callable[[str], None]) -> None:
    """Answer on `socket` until standard input closes, having said on standard output that it's ready."""
    dispatcher = Dispatcher(
        routes={
            route.kind: route
            for route in [
                Route.to(Listed(modules=modules)),
                Route.to(Calls(modules=modules)),
                Route.to(Relays(modules=modules)),
                Route.to(Happens(modules=modules)),
            ]
        },
        answering=f"launch {modules.launch.launch}'s modules",
        say=say,
        changes=Changes(),
    )
    server = await asyncio.start_unix_server(dispatcher.connection, path=socket)
    sys.stdout.write("ready\n")
    sys.stdout.flush()
    try:
        await asyncio.to_thread(sys.stdin.read)
    finally:
        server.close()
        await server.wait_closed()


def worked(socket: Path, services: Services, records: dict[str, Records]) -> None:
    """Serve the modules of the launch whose registration is standard input's first line, on `socket`.

    `records` is where each runtime keeps its records, by the runtime's name: the
    launch's is its runtime's.
    """

    def said(line: str) -> None:
        sys.stderr.write(f"{line}\n")

    launch = Register.model_validate_json(sys.stdin.readline())
    serving = Serving.loaded(launch, services, records[launch.runtime])
    try:
        asyncio.run(serve(serving, socket, said))
    finally:
        socket.unlink(missing_ok=True)
