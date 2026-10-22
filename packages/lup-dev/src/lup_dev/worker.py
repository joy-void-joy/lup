"""A launch's own process: its judge, and its modules' tools, answers to its room's requests, and hooks.

The host service starts it from the launch's repository's approved copy,
`<judge> worker <socket>` (`lup_dev.host.workers`), the launch's registration on
its input's first line. It loads the declaration the launch's hooks are judged
by, at the commit the operator approved with the person's own layer approved
beside it, makes each module's tools, handlers and hooks from it, says it's ready
on its output's first line, and answers one request per connection on `<socket>`
until its input closes, which it does when the service ends it or dies. Where
the modules can't be made, it says why and answers the judge's hooks alone, as
the judge has a stand-in for a declaration that can't load.

Each hook the judge reads is answered as `lup-dev hook <runtime>` answers it,
in a thread of its own (`threaded`), so hooks fired together are judged
together, and a hold waiting a day for the operator delays no other. Judging
holds up in threads of one process: what it keeps between hooks is on disk,
under locks that exclude a thread as they do a process, and what it reaches
(the engine, ruff, the clock, the inbox) is made once for the process and
kept, since none of it holds state of its own.

Each call makes the tools' class afresh, with its module, the launch, the
conversation calling and the door what it would publish goes through (this
process's own hooks at `publishing`), so a tool reads them through `self`. A tool
that can't do its work raises a `LupDevError`, whose message is its answer;
anything else that fails is told the host service's way, its traceback said.

Each occasion makes each listening class of hooks afresh, with its module, the
launch, where the launch's runtime keeps its records, the module's own data
directory for the repository and the other repositories the declaration names, and runs its hooks at that moment in the order
they're declared. A hook that fails is told back whole, and the others still run.
At `publishing` each hook's refusals are gathered, and a hook that fails there,
or answers anything but its refusals, refuses too: what a check couldn't look
at doesn't leave.
"""

import asyncio
import sys
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import Future
from functools import partial
from typing import TYPE_CHECKING, get_args, override

from pydantic import TypeAdapter, ValidationError

from lup.sessions.terminal import Event
from lup.tools.serving import Answer
from lup.tools.tool import Accepted, Refused
from lup.types import Model
from lup_dev.declaration.load import load
from lup_dev.declaration.resolve import Handled, Hooked, Resolved, Served, resolve
from lup_dev.declaration.serving import (
    Answered,
    Door,
    ModuleHooks,
    Moment,
    MomentName,
    Related,
    answering,
    at,
    heard,
    listening,
)
from lup_dev.errors import LupDevError
from lup_dev.host.protocol import HostError, Register, Reply
from lup_dev.host.publishing import Place, Published, Refusal
from lup_dev.host.records import Records
from lup_dev.host.service import Dispatcher, Handler, Reading, Route, unix_server
from lup_dev.host.watch import Changes
from lup_dev.host.workers import (
    Called,
    Calling,
    Happened,
    Happening,
    HookJudged,
    JudgeHook,
    Listing,
    Occasion,
    Offered,
    Relayed,
    Relaying,
    Sent,
)
from lup_dev.layout import Layout
from lup_dev.policy.checkpoint import Services, Worktree
from lup_dev.private.withheld import related_of

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from pathlib import Path

    from lup_dev.host.courier import Conversation


def moment(occasion: Occasion) -> MomentName | None:
    """Return the moment of lup's that an occasion the service tells is; none for a turn's start, which no module's hook runs at."""
    match occasion:
        case "launched" | "stopped" | "publishing":
            return occasion
        case _:
            return heard(occasion)


class Ran(Model):
    """One hook run at a moment: why it failed, where it did, and what it refused."""

    failure: str | None = None
    """Why it failed, its traceback with it; none where it didn't."""
    refusals: list[Refusal] = []


ANSWER = TypeAdapter[list[Refusal] | None](list[Refusal] | None)
"""What a hook may return: its refusals at a moment that's answered, nothing at
any other."""


async def attempted(made: ModuleHooks, name: str, now: Moment) -> Ran:
    """Run the hook `name` of `made` at `now`, and return how it went.

    A hook's failure is told back whole, its traceback with it, and doesn't keep
    the next from running. At a moment that's answered (`Answered`), a hook that
    fails, or returns anything but its refusals, refuses what would leave; at
    any other, a hook returning refusals has failed, since nothing there can be
    refused.
    """
    hook: Callable[[Moment], Awaitable[list[Refusal] | None]] = getattr(made, name)
    who = f"`{type(made).__name__}.{name}`"
    try:
        answered = ANSWER.validate_python(await hook(now))
    except ValidationError as unread:
        failure = f"{who} answered {now.name} with what isn't its refusals: {unread}"
        return failed(failure, now)
    except Exception:
        failure = f"{who} failed at {now.name}:\n{traceback.format_exc()}"
        return failed(failure, now)
    refused = answered or []
    if refused and now.name not in get_args(Answered.__value__):
        return Ran(
            failure=(
                f"{who} refused at {now.name}, where a hook only observes: only "
                f"{', '.join(get_args(Answered.__value__))} can be refused"
            )
        )
    return Ran(refusals=refused)


def failed(failure: str, now: Moment) -> Ran:
    """Return a hook's failure at `now`: at a moment that's answered, a refusal too, since what it couldn't check doesn't leave."""
    if now.name not in get_args(Answered.__value__):
        return Ran(failure=failure)
    [first, *_] = failure.splitlines()
    refusal = Refusal(
        what=f"a check that didn't run: {first}",
        place=Place(within="all of it"),
        steer=(
            "the host service's log has why; what can't be checked doesn't leave "
            "from a room, so tell the operator, who can publish it from their own "
            "terminal"
        ),
    )
    return Ran(failure=failure, refusals=[refusal])


class Serving(Model, Door, arbitrary_types_allowed=True):
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

    def related(self) -> list[Related]:
        """Find on the host the other repositories the declaration names, for a module's hooks and handlers."""
        return related_of(self.resolved.repositories, self.launch.repository)

    def offered(self) -> Offered:
        """Return what the modules serve: each tool, each kind of request, and each occasion their hooks run at."""
        listened = [
            each for hooked in self.resolved.hooked for each in listening(hooked.hooks)
        ]
        told: list[Occasion] = [
            "launched",
            "stopped",
            "publishing",
            *get_args(Event.__value__),
        ]
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
            module=owner.module, launch=self.launch, caller=calling.caller, door=self
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
        data = self.layout.module_data(owner.module.name, self.launch.repository)
        made = owner.handler(
            module=owner.module,
            launch=self.launch,
            request=request,
            data=data,
            related=self.related(),
        )
        return await made.answer()

    async def happen(self, happening: Happening) -> Happened:
        """Run every hook at the moment `happening` tells, and return what failed among them, and what they refused."""
        name = moment(happening.occasion)
        if name is None:
            return Happened()
        now = Moment(
            name=name,
            conversation=happening.conversation,
            call=happening.call,
            tool=happening.tool,
            published=happening.published,
        )
        ran = [
            each
            for hooked in self.resolved.hooked
            for each in await self.ran(hooked, now)
        ]
        return Happened(
            failures=[each.failure for each in ran if each.failure is not None],
            refusals=[refusal for each in ran for refusal in each.refusals],
        )

    async def ran(self, hooked: Hooked, now: Moment) -> list[Ran]:
        """Run one class's hooks at `now`, made afresh with its module's data directory; return how each went."""
        data = self.layout.module_data(hooked.module.name, self.launch.repository)
        data.mkdir(parents=True, exist_ok=True)
        made = hooked.hooks(
            module=hooked.module,
            launch=self.launch,
            records=self.records,
            data=data,
            related=self.related(),
        )
        return [await attempted(made, name, now) for name in at(made, now.name)]

    @override
    async def refusals(
        self, published: Published, conversation: Conversation | None
    ) -> list[Refusal]:
        happening = Happening(
            occasion="publishing", conversation=conversation, published=published
        )
        happened = await self.happen(happening)
        for failure in happened.failures:
            sys.stderr.write(f"{failure}\n")
        return happened.refusals


class Listed(Model, Reading[Listing]):
    """Answers `Listing`: what the modules serve, nothing where they couldn't be made."""

    modules: Serving | None

    @override
    def request(self) -> type[Listing]:
        return Listing

    @override
    async def answer(self, request: Listing) -> Reply:
        return Offered() if self.modules is None else self.modules.offered()

    @override
    async def scoped(self, request: Listing, repository: Path) -> Reply:
        message = "a launch's process answers the host service, never a room"
        raise HostError(message)


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


async def threaded[T](work: Callable[[], T]) -> T:
    """Run `work` in a thread of its own, and return what it returns, or raise what it raises.

    A thread of its own rather than a pool's: a hold waits a day inside its hook,
    and a pool whose threads all waited would queue the hooks after them. The
    thread is a daemon, so a hold waiting in it doesn't keep the process from
    ending when the service ends it. `SystemExit`, which ends a thread silently
    (a declaration's import raising it, say), is raised here as a `LupDevError`,
    so it fails its hook rather than leaving it unanswered.
    """
    finished: Future[T] = Future()

    def run() -> None:
        if not finished.set_running_or_notify_cancel():
            return
        try:
            finished.set_result(work())
        except Exception as failure:
            finished.set_exception(failure)
        except SystemExit as exited:
            message = f"judging ended its thread: {exited!r}"
            finished.set_exception(LupDevError(message))

    threading.Thread(target=run, daemon=True).start()
    return await asyncio.wrap_future(finished)


class Judges(Model, Handler[JudgeHook], arbitrary_types_allowed=True):
    """Answers `JudgeHook`: one hook put to the judge, in a thread of its own."""

    judge: Callable[[str, str], str]
    """Answers one of a runtime's hooks as `lup-dev hook` does: the runtime's
    name and the payload in, what the hook prints out."""

    @override
    def request(self) -> type[JudgeHook]:
        return JudgeHook

    @override
    async def answer(self, request: JudgeHook) -> Reply:
        printed = await threaded(partial(self.judge, request.runtime, request.payload))
        return HookJudged(printed=printed)


def routes(modules: Serving | None, judge: Callable[[str, str], str]) -> list[Route]:
    """Return what a launch's process answers: the judge's hooks, what its modules serve, and, where they were made, their tools, requests and hooks."""
    listed = [Route.to(Judges(judge=judge)), Route.reading(Listed(modules=modules))]
    if modules is None:
        return listed
    return [
        *listed,
        Route.to(Calls(modules=modules)),
        Route.to(Relays(modules=modules)),
        Route.to(Happens(modules=modules)),
    ]


async def serve(
    handlers: list[Route], socket: Path, launch: Register, say: Callable[[str], None]
) -> None:
    """Answer `launch`'s requests on `socket` with `handlers` until standard input closes, having said on standard output that it's ready.

    Its input closing ends it at once: the connections it's answering are
    closed, so a hold waiting in its thread doesn't keep it running.
    """
    dispatcher = Dispatcher(
        routes={route.kind: route for route in handlers},
        answering=f"launch {launch.launch}'s process",
        say=say,
        changes=Changes(),
    )
    server = await unix_server(socket, dispatcher.connection)
    sys.stdout.write("ready\n")
    sys.stdout.flush()
    try:
        await asyncio.to_thread(sys.stdin.read)
    finally:
        server.close()
        server.close_clients()
        await server.wait_closed()


def worked(
    socket: Path,
    services: Services,
    records: dict[str, Records],
    judge: Callable[[str, str], str],
) -> None:
    """Serve the launch whose registration is standard input's first line, on `socket`: its judge's hooks with `judge`, and its modules.

    `records` is where each runtime keeps its records, by the runtime's name: the
    launch's is its runtime's. Where its modules can't be made, the judge's hooks
    are answered alone, and why is said.
    """

    def said(line: str) -> None:
        sys.stderr.write(f"{line}\n")

    launch = Register.model_validate_json(sys.stdin.readline())
    try:
        serving = Serving.loaded(launch, services, records[launch.runtime])
    except LupDevError as failed:
        said(
            f"{launch.launch}: its modules aren't served, and its judge answers its "
            f"hooks alone: {failed}"
        )
        serving = None
    try:
        asyncio.run(serve(routes(serving, judge), socket, launch, said))
    finally:
        socket.unlink(missing_ok=True)
