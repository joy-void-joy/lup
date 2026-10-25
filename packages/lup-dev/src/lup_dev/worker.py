"""A repository's process: the judge, and the modules' tools, answers to the rooms' requests, and hooks, for each of its launches.

The host service starts it from the repository's approved copy,
`<judge> worker <socket> <repository>` (`lup_dev.host.workers`). It loads the
declaration the repository's launches are judged by, at the commit the operator
approved with the person's own layer approved beside it, resolves each module's
classes of methods from it, says it's ready on its output's first line,
and answers one request per connection on `<socket>` until its input closes,
which it does when the service ends it or dies. Each request carries the launch
it's for, so one process serves every launch of the repository, whichever
runtime runs it. Where the modules can't be made, it says why and answers the
judge's hooks alone, as the judge has a stand-in for a declaration that can't
load.

Each hook the judge reads is answered as `lup-dev hook <runtime>` answers it,
in a thread of its own (`threaded`), so hooks fired together are judged
together, and a hold waiting a day for the operator delays no other. A call to
the judge's own tools that ask the engine (`JudgeCalling`: `quiet`) runs on the
same services, with the runtime of the launch it's for. Judging
holds up in threads of one process: what it keeps between hooks is on disk,
under locks that exclude a thread as they do a process, and what it reaches
(the engine, ruff, the clock, the inbox) is made once for the process and
kept, since none of it holds state of its own.

Each of a module's methods runs on its class made afresh, with its module, the
module's own data directory for the repository, the other repositories the
declaration names, where each runtime keeps its records, and the publishing door
(this process's own hooks at `Publishing`), and is handed who asks it where it
takes `by`: an `Agent` for a tool, the launch and the conversation calling; a
`Room` for a request, the launch whose room sent it; `Lup` for a hook, the
launch the event is of and its conversation. Who asks is checked against who
the method may be asked by first (`ask`). A tool that can't do its work raises
a `LupDevError`, whose message is its answer; anything else that fails is told
the host service's way, its traceback said.

Each event runs every hook at it, of every class, in the order they're declared.
A hook that fails is told back whole, and the others still run. At `Publishing`
each hook's refusals are gathered, and a hook that fails there, or answers
anything but its refusals, refuses too: what a check couldn't look at doesn't
leave.
"""

import asyncio
import sys
import threading
import traceback
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, override

from pydantic import TypeAdapter, ValidationError

from lup.blocks import SHELL_TONES, Blocks, OfAgent
from lup.doors import served
from lup.events import Event, Publishing, events
from lup.publishing import Place, Published, Refusal
from lup.tools.serving import Answer
from lup.tools.tool import Accepted, Refused
from lup.types import Model
from lup_dev.clock import Clock
from lup_dev.declaration.load import load
from lup_dev.declaration.resolve import Resolved, Served, resolve
from lup_dev.declaration.serving import (
    Agent,
    Asker,
    Lup,
    ModuleServing,
    Operator,
    Publisher,
    Related,
    Room,
    ask,
    asked_by_room,
    at,
    listening,
    requests,
    tools,
)
from lup_dev.errors import LupDevError
from lup_dev.host.client import Detached, HostClient
from lup_dev.host.protocol import HostError, Register, Reply
from lup_dev.host.records import Recorded
from lup_dev.host.service import Dispatcher, Handler, Reading, Route, unix_server
from lup_dev.host.watch import Changes
from lup_dev.host.workers import (
    Called,
    Calling,
    Happened,
    Happening,
    HookJudged,
    JudgeCalling,
    JudgeHook,
    Listing,
    Offered,
    Relayed,
    Relaying,
    Sent,
    Viewed,
    Viewing,
)
from lup_dev.inbox.exchanges import Exchanges
from lup_dev.inbox.protocol import Exchanged, ListItems
from lup_dev.inbox.store import Conversation as Party
from lup_dev.layout import HostLayout, Layout
from lup_dev.policy.checkpoint import Services, Worktree
from lup_dev.private.withheld import related_of

if TYPE_CHECKING:
    from lup_dev.host.courier import Conversation


class Ran(Model):
    """One hook run at an event: why it failed, where it did, and what it refused."""

    failure: str | None = None
    """Why it failed, its traceback with it; none where it didn't."""
    refusals: list[Refusal] = []


ANSWER = TypeAdapter[list[Refusal] | None](list[Refusal] | None)
"""What a hook may return: its refusals at `Publishing`, nothing at any other
event."""


async def attempted(made: ModuleServing, name: str, now: Event, asker: Lup) -> Ran:
    """Run the hook `name` of `made` at `now`, asked by `asker`, and return how it went.

    A hook's failure is told back whole, its traceback with it, and doesn't keep
    the next from running. At `Publishing`, a hook that fails, or returns
    anything but its refusals, refuses what would leave; at any other event, a
    hook returning refusals has failed, since nothing there can be refused.
    """
    owner = type(made)
    method = served(owner)[name]
    who = f"`{owner.__name__}.{name}`"
    try:
        ask(owner, name, asker)
        answered = ANSWER.validate_python(await method.called(made, now, asker))
    except ValidationError as unread:
        failure = f"{who} answered {now.named()} with what isn't its refusals: {unread}"
        return failed(failure, now)
    except Exception:
        failure = f"{who} failed at {now.named()}:\n{traceback.format_exc()}"
        return failed(failure, now)
    refused = answered or []
    if refused and not isinstance(now, Publishing):
        return Ran(
            failure=(
                f"{who} refused at {now.named()}, where a hook only observes: only "
                "`Publishing` can be refused"
            )
        )
    return Ran(refusals=refused)


def failed(failure: str, now: Event) -> Ran:
    """Return a hook's failure at `now`: at `Publishing`, a refusal too, since what it couldn't check doesn't leave."""
    if not isinstance(now, Publishing):
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


class Answering(Model):
    """A module's method answering one kind of request: its class, with its module, and its name."""

    owner: Served
    name: str


class HostExchanges(Model, Exchanges, arbitrary_types_allowed=True):
    """The items as the host service holds them, for one repository's conversations."""

    repository: Path
    """The repository's git directory."""
    layout: HostLayout
    clock: Clock

    @override
    async def exchanged(self, viewed: OfAgent) -> Exchanged:
        """Ask the host service, as `inbox-list-items` is asked, off the event loop.

        Raise `HostError` where it can't be reached, saying why.
        """
        conversation = Party(
            repository=self.repository,
            runtime=viewed.runtime,
            session=viewed.session,
            agent=viewed.agent,
        )
        host = HostClient(layout=self.layout, clock=self.clock, starter=Detached())
        return await asyncio.to_thread(
            host.ask, ListItems(conversation=conversation), Exchanged
        )


class RepositoryModules(Model, arbitrary_types_allowed=True):
    """A repository's modules, as its declaration resolves them: what they serve, and each answer, for whichever of its launches asks."""

    repository: Path
    """The repository's git directory."""
    resolved: Resolved
    recorded: dict[str, Recorded]
    """Where each runtime keeps its sessions' records, and how they're read, by
    the runtime's name: a launch's hooks read its own runtime's."""
    layout: Layout
    """Where lup keeps its data, each module's own among it."""
    exchanges: Exchanges
    """Where its views read the items of lup's inbox a conversation exchanged."""

    @classmethod
    def loaded(
        cls, repository: Path, services: Services, recorded: dict[str, Recorded]
    ) -> RepositoryModules:
        """Load the declaration the launches of the repository at `repository` are judged by, and resolve it whole.

        Raise `ProjectError` where it doesn't load or resolve.
        """
        root = Worktree.main(repository, services).loaded.root
        return cls(
            repository=repository,
            resolved=resolve(load(root).project),
            recorded=recorded,
            layout=services.layout,
            exchanges=HostExchanges(
                repository=repository,
                layout=services.layout.host,
                clock=services.clock,
            ),
        )

    @classmethod
    def of_worktree(
        cls,
        root: Path,
        repository: Path,
        recorded: dict[str, Recorded],
        layout: Layout,
        exchanges: Exchanges,
    ) -> RepositoryModules:
        """Load the declaration the worktree at `root` holds itself, as a room runs its modules' commands, the room containing them.

        Raise `ProjectError` where it doesn't load or resolve.
        """
        return cls(
            repository=repository,
            resolved=resolve(load(root).project),
            recorded=recorded,
            layout=layout,
            exchanges=exchanges,
        )

    def related(self) -> list[Related]:
        """Find on the host the other repositories the declaration names, for a module's methods."""
        return related_of(self.resolved.repositories, self.repository)

    def offered(self) -> Offered:
        """Return what the modules serve: each tool, each kind of request a room may send them, and each event their hooks run at."""
        listened = [
            event for each in self.resolved.served for event in listening(each.serving)
        ]
        return Offered(
            tools=[
                spec for each in self.resolved.served for spec in tools(each.serving)
            ],
            kinds=[
                kind
                for each in self.resolved.served
                for kind, name in requests(each.serving).items()
                if asked_by_room(each.serving, name)
            ],
            events=[event.named() for event in events() if event in listened],
        )

    def made(self, owner: Served) -> ModuleServing:
        """Make `owner`'s class afresh, with its module and the module's own context: what each of its methods runs on."""
        data = self.layout.module_data(owner.module.name, self.repository)
        data.mkdir(parents=True, exist_ok=True)
        return owner.serving(
            module=owner.module,
            data=data,
            related=self.related(),
            recorded=self.recorded,
            publisher=Hooks(modules=self),
            exchanges=self.exchanges,
        )

    def serving(self, name: str) -> Served | None:
        """Return the class serving the tool `name`, with its module; none where none does."""
        return next(
            (
                each
                for each in self.resolved.served
                if any(spec.name == name for spec in tools(each.serving))
            ),
            None,
        )

    def answering(self, kind: str) -> Answering | None:
        """Return the method answering requests of `kind`, with its class and module; none where none does."""
        return next(
            (
                Answering(owner=each, name=name)
                for each in self.resolved.served
                for answered, name in requests(each.serving).items()
                if answered == kind
            ),
            None,
        )

    def viewing(self, module: str, view: str) -> Served | None:
        """Return the class serving `module`'s view `view`, with its module; none where none does."""
        return next(
            (
                each
                for each in self.resolved.served
                if each.module.name == module
                and (method := served(each.serving).get(view)) is not None
                and method.viewing() is not None
            ),
            None,
        )

    async def view(self, viewing: Viewing) -> Blocks:
        """Answer one of the modules' views, for the operator, or for a room of one of the repository's launches.

        Raise `LupDevError` where no module of the repository has it, where its
        asker may not ask it, where what it's given isn't what it takes, or
        where what it answers names a tone neither the shell nor a module
        declares.
        """
        owner = self.viewing(viewing.module, viewing.view)
        if owner is None:
            message = (
                f"no module `{viewing.module}` of this repository has a view "
                f"`{viewing.view}`"
            )
            raise LupDevError(message)
        asker = Operator() if viewing.launch is None else Room(launch=viewing.launch)
        ask(owner.serving, viewing.view, asker)
        method = served(owner.serving)[viewing.view]
        try:
            argument = method.taken.model.annotation.model_validate(viewing.argument)
        except ValidationError as wrong:
            message = f"`{viewing.view}` doesn't take what it was given: {wrong}"
            raise LupDevError(message) from wrong
        blocks = await method.called(self.made(owner), argument, asker)
        if not isinstance(blocks, Blocks):
            message = f"`{viewing.view}` answered {blocks!r}, not blocks"
            raise LupDevError(message)
        known = [tone.name for tone in [*SHELL_TONES, *self.resolved.looks.tones]]
        unknown = [tone for tone in blocks.tones() if tone not in known]
        if unknown:
            message = (
                f"`{viewing.view}` names tones no module declares: {', '.join(unknown)}"
            )
            raise LupDevError(message)
        return blocks

    async def call(self, calling: Calling) -> Answer:
        """Run one call to a module's tool, asked by the conversation calling, and return what the agent reads."""
        name = calling.name
        owner = self.serving(name)
        if owner is None:
            return Answer(text=f"no module of this launch serves `{name}`", error=True)
        asker = Agent(launch=calling.launch, conversation=calling.caller)
        try:
            ask(owner.serving, name, asker)
            tool = served(owner.serving)[name].tool(self.made(owner), asker)
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

    async def answer(self, sent: Sent, asker: Asker) -> Reply:
        """Answer one request, sent by `asker`, with the module's method for its kind.

        Raise `LupDevError` where no module answers its kind, where its method
        isn't asked by such an asker, or where it doesn't reply.
        """
        found = self.answering(sent.kind)
        if found is None:
            message = f"no module of this launch answers `{sent.kind}`"
            raise LupDevError(message)
        owner, name = found.owner, found.name
        ask(owner.serving, name, asker)
        method = served(owner.serving)[name]
        request = method.taken.model.annotation.model_validate(sent.model_dump())
        reply = await method.called(self.made(owner), request, asker)
        if not isinstance(reply, Reply):
            message = f"`{owner.serving.__name__}.{name}` replied {reply!r}"
            raise LupDevError(message)
        return reply

    async def happen(self, happening: Happening) -> Happened:
        """Run every hook at the event `happening` tells, for its launch, and return what failed among them, and what they refused."""
        asker = Lup(launch=happening.launch, conversation=happening.conversation)
        now = happening.event
        ran = [
            await attempted(self.made(each), name, now, asker)
            for each in self.resolved.served
            for name in at(each.serving, type(now))
        ]
        return Happened(
            failures=[each.failure for each in ran if each.failure is not None],
            refusals=[refusal for each in ran for refusal in each.refusals],
        )


class Hooks(Model, Publisher):
    """The publishing door of a repository's modules: every one of their hooks at `Publishing`, run for the launch publishing."""

    modules: RepositoryModules

    @override
    async def refusals(
        self,
        published: Published,
        launch: Register,
        conversation: Conversation | None,
    ) -> list[Refusal]:
        happening = Happening(
            launch=launch,
            event=Publishing(published=published),
            conversation=conversation,
        )
        happened = await self.modules.happen(happening)
        for failure in happened.failures:
            sys.stderr.write(f"{failure}\n")
        return happened.refusals


class Listed(Model, Reading[Listing]):
    """Answers `Listing`: what the modules serve, nothing where they couldn't be made."""

    modules: RepositoryModules | None

    @override
    def request(self) -> type[Listing]:
        return Listing

    @override
    async def answer(self, request: Listing) -> Reply:
        return Offered() if self.modules is None else self.modules.offered()

    @override
    async def scoped(self, request: Listing, repository: Path) -> Reply:
        message = "a repository's process answers the host service, never a room"
        raise HostError(message)


class Calls(Model, Handler[Calling]):
    """Answers `Calling`: one call to a module's tool."""

    modules: RepositoryModules

    @override
    def request(self) -> type[Calling]:
        return Calling

    @override
    async def answer(self, request: Calling) -> Reply:
        return Called(answer=await self.modules.call(request))


class JudgeCalls(Model, Handler[JudgeCalling], arbitrary_types_allowed=True):
    """Answers `JudgeCalling`: one call to the judge's own tools that asks the engine (`policy/tools.py`)."""

    call: Callable[[JudgeCalling], Awaitable[Answer]]
    """Runs it for the conversation calling, with the services judging makes
    once for the process and the runtime of the launch it's for (`cli.py`)."""

    @override
    def request(self) -> type[JudgeCalling]:
        return JudgeCalling

    @override
    async def answer(self, request: JudgeCalling) -> Reply:
        return Called(answer=await self.call(request))


class Relays(Model, Handler[Relaying]):
    """Answers `Relaying`: one room's request, passed to the module answering its kind."""

    modules: RepositoryModules

    @override
    def request(self) -> type[Relaying]:
        return Relaying

    @override
    async def answer(self, request: Relaying) -> Reply:
        sent = Sent.model_validate(request.request)
        reply = await self.modules.answer(sent, Room(launch=request.launch))
        return Relayed(reply=reply.model_dump())


class Views(Model, Reading[Viewing]):
    """Answers `Viewing`: one of the modules' views, for the operator or a room."""

    modules: RepositoryModules

    @override
    def request(self) -> type[Viewing]:
        return Viewing

    @override
    async def answer(self, request: Viewing) -> Reply:
        return Viewed(blocks=await self.modules.view(request))

    @override
    async def scoped(self, request: Viewing, repository: Path) -> Reply:
        message = "a repository's process answers the host service, never a room"
        raise HostError(message)


class Happens(Model, Handler[Happening]):
    """Answers `Happening`: the modules' hooks run at its event."""

    modules: RepositoryModules

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

    judge: Callable[[str, str, Path | None], str]
    """Answers one of a runtime's hooks as `lup-dev hook` does: the runtime's
    name, the payload and the launch's own environments, where its room has
    them, in; what the hook prints out."""

    @override
    def request(self) -> type[JudgeHook]:
        return JudgeHook

    @override
    async def answer(self, request: JudgeHook) -> Reply:
        printed = await threaded(
            partial(self.judge, request.runtime, request.payload, request.environments)
        )
        return HookJudged(printed=printed)


def routes(
    modules: RepositoryModules | None,
    judge: Callable[[str, str, Path | None], str],
    called: Callable[[JudgeCalling], Awaitable[Answer]],
) -> list[Route]:
    """Return what a repository's process answers: the judge's hooks and its own tools that ask the engine, what its modules serve, and, where they were made, their tools, requests and hooks."""
    listed = [
        Route.to(Judges(judge=judge)),
        Route.to(JudgeCalls(call=called)),
        Route.reading(Listed(modules=modules)),
    ]
    if modules is None:
        return listed
    return [
        *listed,
        Route.to(Calls(modules=modules)),
        Route.to(Relays(modules=modules)),
        Route.reading(Views(modules=modules)),
        Route.to(Happens(modules=modules)),
    ]


async def serve(
    handlers: list[Route], socket: Path, repository: Path, say: Callable[[str], None]
) -> None:
    """Answer the requests of `repository`'s launches on `socket` with `handlers` until standard input closes, having said on standard output that it's ready.

    Its input closing ends it at once: the connections it's answering are
    closed, so a hold waiting in its thread doesn't keep it running.
    """
    dispatcher = Dispatcher(
        routes={route.kind: route for route in handlers},
        answering=f"{repository}'s process",
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
    repository: Path,
    services: Services,
    recorded: dict[str, Recorded],
    *,
    judge: Callable[[str, str, Path | None], str],
    called: Callable[[JudgeCalling], Awaitable[Answer]],
) -> None:
    """Serve the launches of the repository whose git directory is `repository`, on `socket`: their judge's hooks with `judge`, the judge's own tools that ask the engine with `called`, and the repository's modules.

    `recorded` is where each runtime keeps its records, and how they're read, by
    the runtime's name: a launch's hooks read its runtime's. Where the modules can't be made, the
    judge's hooks are answered alone, and why is said.
    """

    def said(line: str) -> None:
        sys.stderr.write(f"{line}\n")

    try:
        serving = RepositoryModules.loaded(repository, services, recorded)
    except LupDevError as failed:
        said(
            f"{repository}: its modules aren't served, and its judge answers its "
            f"launches' hooks alone: {failed}"
        )
        serving = None
    try:
        asyncio.run(serve(routes(serving, judge, called), socket, repository, said))
    finally:
        socket.unlink(missing_ok=True)
