"""The host service: one per user, on the host, which rooms call for what only it can do.

`docs/host.md`. It listens on a control socket on the
host only, taking typed requests (`host/protocol.py`), each answered by the handler
routed its kind: the service's own register a launch, end one, list those served,
and stop the service; a module registers its own handlers with the service it
builds (`Route.to`).

Each launch it serves gets a directory of its own, which the launch's room mounts
at `/run/lup`, so the service knows which launch speaks by the socket it hears it
on. It holds three sockets:
- `hook.sock` takes a runtime's raw payload, read to the end. The service reads
  it through the `Courier` (`host/courier.py`), which says whether the launch's
  judge reads it. One it reads is put to the launch's judge (`LaunchJudge`): its
  repository's approved copy of `lup-dev`, in the repository's process, which
  stays running and answers each hook as `lup-dev hook <runtime>` would, so each
  session is judged by the code approved for its repository without paying a
  start of Python and an import of `lup-dev` at each hook (`host/workers.py`).
  One it doesn't read is answered by the service itself, without asking the
  judge, as no decision, which is never nothing (`UNDECIDED`). Every answer
  goes out through the `Courier` again, a call to lup's tools rewritten to
  carry lup's id for the conversation calling, and what the `Post` says waits
  for the conversation added: counted told once the answer is written, and put
  back where the hook was gone first. Hooks for
  parallel calls arrive at once and a hold waits for hours, so each is awaited
  on the event loop, which goes on serving meanwhile, and answered in a thread
  of its own in the repository's process. Where the judge can't answer (its process
  unable to start, ending as it answers, or failing on a payload it can't read),
  the service answers in the runtime's own terms through the `Answerer`, rather
  than closing empty, which the runtime would take as no decision.
- `mcp.sock` serves lup's tools, and `request.sock` the room's requests, each
  routed to the core's own (`host/rooms.py`) or to the launch's modules, which
  run in the same process of the repository's, held while the launch is open
  (`host/workers.py`). The control socket's kinds that
  only read are routed there too, each answered for the launch's repository
  alone (`Reading`); those that write never are.

Each launch is recorded beside its directory, so a service started after one
stopped serves the same launches, in the directories their rooms mounted. The
service stops without waiting for the answers in flight: the repositories'
processes are ended, and their hooks hear nothing, which the room's hook tells
from an answer: it fails rather than letting the call go on unjudged (`lost`,
`launch/session.py`), and a hold left with no call waiting on it is settled at a
later checkpoint (`docs/judging-writes.md`, *Asking the operator*).
"""

import asyncio
import select
import shutil
import traceback
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Self, override

from filelock import FileLock, Timeout
from pydantic import Field, JsonValue, ValidationError, model_validator

import lup
from lup.events import (
    CallFinished,
    CallStarted,
    ConversationEnded,
    Launched,
    SessionStarted,
    Stopped,
    TurnEnded,
    TurnStarted,
    WorktreeAsked,
)
from lup.programs import ProgramMissingError, Ran, awaited
from lup.rooms.engine import ContainerError, Podman
from lup.tools import speaking
from lup.tools.serving import Answer, Outbox, serve
from lup.tools.tool import Accepted, AgentTool, ToolSpec
from lup.tools.tool import Refused as Rejected
from lup.types import Model, MutableModel
from lup_dev.clock import Clock, SystemClock
from lup_dev.host.courier import (
    Conversation,
    Conversations,
    Courier,
    Heard,
    Post,
    Posted,
    Spawns,
    Telling,
    Waker,
)
from lup_dev.host.homes import kept
from lup_dev.host.names import Names, claimed, container_name, held, shaped, taken
from lup_dev.host.protocol import (
    Activity,
    Done,
    Holding,
    HostError,
    Listed,
    ListLaunches,
    Looks,
    Refused,
    Register,
    Registered,
    Rename,
    Renamed,
    Reply,
    Request,
    SetHolding,
    ShowHolding,
    Stop,
    Talker,
    Unregister,
    handle,
)
from lup_dev.host.pushes import Pushes
from lup_dev.host.records import Records
from lup_dev.host.rooms import SERVER, LaunchTools, RoomRoute, RoomTools, summaries
from lup_dev.host.watch import Changes, Touched
from lup_dev.host.workers import (
    Called,
    Calling,
    Happened,
    Happening,
    LaunchJudge,
    LaunchModules,
    Offered,
    Passed,
    Relayed,
    Relaying,
    RepositoryAsking,
    Sent,
)
from lup_dev.layout import HostLayout
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class Answerer(ABC):
    """What the service knows of each runtime lup knows: its name, and how it hears a hook its judge couldn't answer."""

    @abstractmethod
    def runtimes(self) -> list[str]:
        """Name the runtimes whose hooks the service answers."""

    @abstractmethod
    def unanswered(self, runtime: str, payload: str, failure: str) -> str:
        """Answer one of `runtime`'s hooks its launch's judge couldn't, saying `failure` in the runtime's own terms.

        What the hook prints: a payload in, whether or not it reads as one of the
        runtime's hooks.
        """


class Program(Model):
    """One program the service runs: `gh` for a launch, or git for its room; its command, what goes on its input, and where it runs."""

    command: list[str]
    payload: str
    """What goes on its standard input: a body for `gh`, or what git reads."""
    directory: Path | None = None
    """Where it runs; none for the service's own directory."""


async def executed(program: Program) -> Ran:
    """Run `program` to its end on the service's event loop, and return how it ended, whatever its status.

    Awaited (`lup.programs`, `awaited`), so it holds no thread for as long as it
    runs, `gh` waiting on GitHub's answer or git on a room's push
    (`remote/protocol.py`), and it's killed where the wait is cancelled. One
    that can't be started ends with status 127, as a shell says it, why on its
    standard error.
    """
    name, *arguments = program.command
    try:
        return await awaited(
            name,
            *arguments,
            cwd=program.directory,
            stdin=program.payload,
            checked=False,
        )
    except ProgramMissingError as missing:
        return Ran(command=program.command, status=127, error=str(missing).encode())


class Handler[R: Request](ABC):
    """Answers one kind of control request; a module registers its own with the service.

    A kind that writes is routed to one with `Route.to`; a kind that reads, to a
    `Reading`, which says what a room is shown of it, with `Route.reading`.
    """

    @abstractmethod
    def request(self) -> type[R]:
        """Return the model of the requests this answers: its `kind` routes them here."""

    @abstractmethod
    async def answer(self, request: R) -> Reply:
        """Answer one request on the service's event loop, off it where it blocks.

        A `HostError` refuses the request with its message.
        """


class Reading[R: Request](Handler[R], ABC):
    """Answers one kind of control request that only reads: the operator with all the service holds, and a launch's room with what's of its repository alone."""

    @abstractmethod
    async def scoped(self, request: R, repository: Path) -> Reply:
        """Answer one request from a room of the repository whose git directory is `repository`, with what's of it alone: no other repository's launches, items, names, worktrees or words.

        `repository` is the host's record of the launch the room runs, never
        what the room names. A `HostError` refuses the request with its
        message, as for what's another repository's.
        """


class Route(Model, arbitrary_types_allowed=True):
    """A handler as the service dispatches to it: its kind, its answer to the JSON, for a kind that only reads its answer to a room, and how it's watched where it says so."""

    kind: str
    answer: Callable[[str], Awaitable[Reply]]
    scoped: Callable[[str, Path], Awaitable[Reply]] | None = None
    """Its answer to a room of the repository whose git directory it's given,
    where its kind only reads (`Reading.scoped`); none for one that writes,
    which a room never reaches."""
    watch: Callable[[str], AsyncIterator[Reply]] | None = None
    """Its replies to one request watched, at once then each time it's answered
    again, at triggers of its own (`host/views.py`); none answers it again at
    each change, as the service's own kinds are."""

    @classmethod
    def to[R: Request](cls, handler: Handler[R]) -> Route:
        """Route the requests of `handler`'s kind to it, each read as its model: a kind that writes, which a room never reaches.

        A kind that reads is refused: it's routed with `reading`, its handler
        saying what a room is shown of it, so a room is never left without it.
        """
        model = handler.request()
        kind = model.named()
        if model.reads:
            message = (
                f"`{kind}` only reads, so it's routed with `Route.reading`, its "
                "handler saying what a room is shown of it"
            )
            raise TypeError(message)

        async def answered(raw: str) -> Reply:
            return await handler.answer(model.model_validate_json(raw))

        return cls(kind=kind, answer=answered)

    @classmethod
    def reading[R: Request](
        cls,
        handler: Reading[R],
        watch: Callable[[R], AsyncIterator[Reply]] | None = None,
    ) -> Route:
        """Route the requests of `handler`'s kind to it, each read as its model: a kind that only reads, which each launch's room is served for its repository alone, and which `watch` watches where it's given.

        A kind that writes is refused, since it would serve a room what acts.
        """
        model = handler.request()
        kind = model.named()
        if not model.reads:
            message = f"`{kind}` writes, so it's routed with `Route.to`: a room never reaches it"
            raise TypeError(message)

        async def answered(raw: str) -> Reply:
            return await handler.answer(model.model_validate_json(raw))

        async def scoped(raw: str, repository: Path) -> Reply:
            return await handler.scoped(model.model_validate_json(raw), repository)

        def watched(raw: str) -> AsyncIterator[Reply]:
            if watch is None:
                message = f"`{kind}` is watched at each change"
                raise TypeError(message)
            return watch(model.model_validate_json(raw))

        return cls(
            kind=kind,
            answer=answered,
            scoped=scoped,
            watch=None if watch is None else watched,
        )


def confined(route: Route, launch: Register) -> Route | None:
    """Route a room's requests of `route`'s kind to its answer for `launch`'s repository alone; none where its kind writes."""
    scoped = route.scoped
    if scoped is None:
        return None

    async def answered(raw: str) -> Reply:
        return await scoped(raw, launch.repository)

    return Route(kind=route.kind, answer=answered)


def bound(room: RoomRoute, launch: Register) -> Route:
    """Route a room's requests of `room`'s kind to its handler, as they come from `launch`'s room."""

    async def answered(raw: str) -> Reply:
        return await room.answer(raw, launch)

    return Route(kind=room.kind, answer=answered)


class Dispatcher(Model, arbitrary_types_allowed=True):
    """One typed request per connection, answered by the route its kind names, and one reply; on the watch socket, a request's replies as they change."""

    routes: dict[str, Route]
    answering: str
    """Who answers on the socket, as a refusal names it."""
    say: Callable[[str], None]
    changes: Changes
    """Told once each request is answered, since it may have changed what the
    service holds; waited on by each watch."""

    async def connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Answer one request, and close the connection.

        A connection that sends nothing only asks whether the socket answers. One
        whose sender left before its reply, as a terminal waiting on an approval
        does when it's interrupted, is said, and its reply dropped.
        """
        raw = (await reader.read()).decode()
        try:
            if raw:
                reply = await self.answered(raw)
                self.changes.changed()
                writer.write(reply.model_dump_json().encode())
                await writer.drain()
            writer.close()
            await writer.wait_closed()
        except ConnectionError as gone:
            self.say(f"a request's sender left before its reply: {gone}")

    async def watching(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Answer one request, its line read, at once and again where its reply differs, one JSON line each, until its sender closes the connection: at each change, or at its route's own triggers (`Route.watch`).

        A refusal is the last line. The sender keeps its side open while it
        watches, so its closing is heard, and the watch ends with it, its
        route's watch closed.
        """
        raw = (await reader.readline()).decode()
        gone = asyncio.ensure_future(reader.read())
        replies = self.replies(raw)
        coming: asyncio.Future[Reply | None] | None = None
        sent = ""
        try:
            while not gone.done():
                coming = asyncio.ensure_future(anext(replies, None))
                await asyncio.wait([coming, gone], return_when=asyncio.FIRST_COMPLETED)
                if not coming.done():
                    return
                reply = coming.result()
                if reply is None:
                    return
                line = reply.model_dump_json()
                if line != sent:
                    writer.write(f"{line}\n".encode())
                    await writer.drain()
                    sent = line
                if isinstance(reply, Refused):
                    return
        except ConnectionError as left:
            self.say(f"a watch's sender left: {left}")
        finally:
            gone.cancel()
            # The next reply, still awaited as the watch ends, is cancelled
            # before its replies are closed, which can't close while it runs.
            if coming is not None and not coming.done():
                coming.cancel()
                await asyncio.wait([coming])
            await replies.aclose()
            writer.close()

    async def replies(self, raw: str) -> AsyncGenerator[Reply]:
        """Yield the replies to one request watched: its answer at once, then again at each change, or as its route's own watch yields them (`Route.watch`), a refusal last.

        A route's watch that refuses or fails is refused as an answer is
        (`answered`).
        """
        routed = self.routed(raw)
        if isinstance(routed, Refused):
            yield routed
            return
        watch = routed.watch
        if watch is not None:
            try:
                async for reply in watch(raw):
                    yield reply
            except (HostError, ValidationError) as failure:
                yield self.refused(str(failure))
            except Exception as failure:
                yield self.failed(routed.kind, failure)
            return
        while True:
            seen = self.changes.count
            yield await self.answered(raw)
            await self.changes.after(seen)

    def routed(self, raw: str) -> Route | Refused:
        """Return the route one request's kind names, or refuse a request that doesn't parse, or of no kind routed."""
        try:
            kind = Request.model_validate_json(raw).kind
        except ValidationError as failure:
            return self.refused(f"a request is a JSON object with its kind: {failure}")
        route = self.routes.get(kind)
        if route is None:
            known = ", ".join(sorted(self.routes)) or "no kind"
            return self.refused(
                f"no handler for `{kind}`; {self.answering} answers {known}"
            )
        return route

    async def answered(self, raw: str) -> Reply:
        """Answer one request with the route its kind names.

        A request that doesn't parse, or of no kind routed, is refused, as is one
        its handler refuses or fails on; a failure is said with its traceback.
        """
        route = self.routed(raw)
        if isinstance(route, Refused):
            return route
        try:
            return await route.answer(raw)
        except (HostError, ValidationError) as failure:
            return self.refused(str(failure))
        except Exception as failure:
            return self.failed(route.kind, failure)

    def failed(self, kind: str, failure: Exception) -> Refused:
        """Refuse a request whose handler failed, saying the failure with its traceback."""
        told = "".join(traceback.format_exception(failure))
        self.say(f"the `{kind}` handler failed:\n{told}")
        return self.refused(f"the `{kind}` handler failed: {failure!r}")

    def refused(self, error: str) -> Refused:
        """Refuse a request, saying why."""
        self.say(f"refused a request: {error}")
        return Refused(error=error)


class ModulesTools(Model, RoomTools, arbitrary_types_allowed=True):
    """A launch's modules' tools, as its session is served them: each call passed to its repository's process."""

    modules: LaunchModules
    offered: Offered

    @override
    def specs(self) -> list[ToolSpec]:
        return self.offered.tools

    @override
    async def call(
        self,
        name: str,
        arguments: JsonValue,
        launch: Register,
        caller: Conversation,
        call: str | None,
    ) -> Answer:
        """Pass the call to the launch's modules, and return what their tool answered.

        Where they can't answer, the answer says why.
        """
        try:
            reply = await self.modules.ask(
                launch,
                Calling(launch=launch, name=name, arguments=arguments, caller=caller),
            )
        except HostError as failed:
            return Answer(text=f"`{name}` didn't run: {failed}", error=True)
        match reply:
            case Called(answer=answer):
                return answer
            case _:
                return Answer(
                    text=f"`{name}` didn't run: its module replied {reply.kind}",
                    error=True,
                )


def relayed(modules: LaunchModules, launch: Register, kind: str) -> Route:
    """Route a room's requests of `kind` to `launch`'s modules, their reply passed back whole."""

    async def answered(raw: str) -> Reply:
        sent = Sent.model_validate_json(raw).model_dump()
        reply = await modules.ask(launch, Relaying(launch=launch, request=sent))
        match reply:
            case Relayed(reply=passed):
                return Passed.model_validate(passed)
            case _:
                message = f"the module answering `{kind}` replied {reply.kind}"
                raise HostError(message)

    return Route(kind=kind, answer=answered)


def switched(
    conversations: Conversations, conversation: Conversation, depth: int = 0
) -> bool:
    """Say whether the operator's switch holds each flagged write of `conversation`: its own on, or that of a conversation above it among `conversations`, since the switch covers a conversation and its subagents; `depth` counts the conversations climbed, which never pass how many there are.

    >>> known = Conversations(known=[
    ...     Conversation(id="m", session="s1", holding=True),
    ...     Conversation(id="a", session="s1", agent="a1", parent="m"),
    ...     Conversation(id="b", session="s1", agent="b1", parent="a"),
    ...     Conversation(id="c", session="s1", agent="c1"),
    ... ])
    >>> [switched(known, each) for each in known.known]
    [True, True, True, False]
    """
    if conversation.holding:
        return True
    parent = (
        None
        if conversation.parent is None
        else conversations.calling(conversation.parent)
    )
    if parent is None or depth >= len(conversations.known):
        return False
    return switched(conversations, parent, depth + 1)


class Noted(Model):
    """A hook's conversation as it stands once what the hook says of subagents is noted, and what it's told of lup's tools and of names."""

    conversation: Conversation
    said: list[str] = []


def unnamed(path: str) -> str:
    """Ask a subagent spawned without a name to name themselves: they know their task."""
    return (
        f"lup: you're `{path}` for now, with no name of your own: name yourself "
        "after your task with lup's `rename` tool (`explore-auth`), so the "
        "operator and other sessions can tell you apart."
    )


def named_here(name: str) -> str:
    """Tell a session starting its launch's name."""
    return (
        f"lup: you're `{name}`: how the operator, lup's commands and other "
        "sessions call you. Once you know your task, name yourself after it with "
        "lup's `rename` tool, unless the operator named you."
    )


def renamed_there(name: str) -> str:
    """Tell a session the operator renamed it in its runtime, which lup took as its launch's name."""
    return (
        f"lup: the operator renamed you `{name}`: how they, lup's commands and "
        "other sessions call you from now on. Keep the name they gave."
    )


class Named(Model):
    """A launch's name as its session starts or takes a prompt, and what the hook's answer says of it."""

    name: str
    told: list[str] = []
    """What the conversation is told of its name: at a start, the name; at a
    prompt, that the operator renamed it, where they did."""
    title: str | None = None
    """The title the hook's answer gives the runtime: the name, where the hook
    takes a title and the runtime's own differs; none otherwise."""


class Titled(Model):
    """A title a hook's answer gives a session's runtime."""

    session: str
    """The runtime's id for the session."""
    title: str


def introduction(tools: list[ToolSpec]) -> str:
    """Tell a subagent the tools lup serves it, which its session's guidance lists and it doesn't read: each by its name and summary, as the guidance lists them (`summaries`).

    What a subagent's hooks say names its type, not its tools, and a type's
    name doesn't fix them (a project's agent of the same name replaces a
    built-in one), so it's told some types go without lup's.

    >>> from lup.tools.speaking import friction, how_it_felt
    >>> print(introduction([friction.spec(), how_it_felt.spec()]))
    lup, the environment you work in, serves you these tools, as it does your session's main conversation. Your tool search finds each by its name, with its full description. Some subagent types are given only their own tools, without lup's: where your tool search finds none of these, you're one of them.
    <BLANKLINE>
    - `friction`: Say what got in your way, and carry on.
    - `how_it_felt`: Tell your caller how it is for you.
    <BLANKLINE>
    `friction` and `how_it_felt` reach the operator directly, whatever your parent passes on.
    """
    opening = (
        "lup, the environment you work in, serves you these tools, as it does "
        "your session's main conversation. Your tool search finds each by its "
        "name, with its full description. Some subagent types are given only "
        "their own tools, without lup's: where your tool search finds none of "
        "these, you're one of them."
    )
    direct = (
        f"`{speaking.friction.name}` and `{speaking.how_it_felt.name}` reach the "
        "operator directly, whatever your parent passes on."
    )
    return "\n".join([opening, "", *summaries(tools), "", direct])


class Running(Model):
    """A main conversation the service serves: its launch as it stands, the launch's name, and its session, the latest heard in it."""

    launch: Register
    name: str
    session: str
    """The runtime's id for the session."""


class Bearings(ABC):
    """What a new main session is told, once, as it starts, of where its repository stands (`inbox/bearings.py`)."""

    @abstractmethod
    async def told(
        self, launch: Register, session: str, running: list[Running]
    ) -> str | None:
        """Return what session `session`'s own conversation, starting anew in `launch`, is told; `running` being the main conversations the service serves, its own among them. None tells nothing."""


class Spoken(Model):
    """What a hook prints, what it tells the conversation from its inbox, the title it gives the session's runtime, and the conversation it touched."""

    answer: str
    posted: Posted = Posted()
    titled: Titled | None = None
    """The title the answer gives the session's runtime, kept as the one lup
    left it with once the answer is written; none where it gives none."""
    touched: list[Touched] = []
    """The conversation the hook is of, at its event, told to `Changes` once
    it's answered, so a view of it watched is answered again; none for a hook
    lup couldn't read, or of one of the runtime's own agents."""


class Served(Model, arbitrary_types_allowed=True):
    """A launch the service serves: its conversations, and the servers on its sockets."""

    launch: Register
    conversations: Conversations
    servers: list[asyncio.Server]
    """Its hook socket's, its tool server's and its requests' socket's."""
    offered: Offered = Offered()
    """What the launch's modules serve, in its repository's process, as they
    did when it opened."""
    ending: asyncio.Event = Field(default_factory=asyncio.Event)
    """Set once the launch ends: a hook of its the judge is still answering is
    marked ended then, as one its runtime ended is (`Launches.judgement`), since
    the repository's process answering it outlives the launch."""


async def closed(server: asyncio.Server) -> None:
    """Close `server` and the connections it holds, its socket file removed."""
    server.close()
    server.close_clients()
    await server.wait_closed()


UNDECIDED = "{}\n"
"""What the service answers a hook where nothing is decided or told: an empty
JSON object, which both runtimes read as an answer deciding nothing (each
adapter says how), as they would read nothing printed. Every hook is answered
with something, so the room's hook tells an answer from a connection lost
before one, which `socat` ends as it ends an empty answer (`piped`,
`launch/session.py`)."""


@asynccontextmanager
async def hung_up(writer: asyncio.StreamWriter) -> AsyncGenerator[asyncio.Future[None]]:
    """Watch the connection `writer` writes to while the context is open: the future given is done once its peer has closed it whole.

    A room's hook has sent all it will before it waits for its answer, so the
    connection reads as ended from then on, and asyncio watches it no more. Its
    runtime ending the hook, as when the operator interrupts the call, is the
    peer closing it whole, which Linux reports as `EPOLLHUP`, never for a half
    closed: an epoll of the connection's own, asking for nothing else, wakes the
    loop on that alone. The service's own close of the connection takes it out
    of that epoll unheard.
    """
    loop = asyncio.get_running_loop()
    gone: asyncio.Future[None] = loop.create_future()
    connection = writer.get_extra_info("socket")
    if connection is None:
        yield gone
        return
    watch = select.epoll()

    def heard() -> None:
        loop.remove_reader(watch.fileno())
        if not gone.done():
            gone.set_result(None)

    try:
        watch.register(connection.fileno(), 0)
        loop.add_reader(watch.fileno(), heard)
        yield gone
    finally:
        loop.remove_reader(watch.fileno())
        watch.close()


type Answering = Callable[
    [asyncio.StreamReader, asyncio.StreamWriter], Coroutine[None, None, None]
]
"""What answers one connection to a server, from its reader and to its writer."""


async def unix_server(
    path: Path, answering: Answering, limit: int = 64 * 1024
) -> asyncio.Server:
    """Serve the Unix socket at `path`, as asyncio's `start_unix_server` does, but answering each connection with `answering` in a task held until it ends; `limit` is the longest line its readers read.

    asyncio's loop holds a task weakly, and a connection holds the task
    answering it only while the loop watches it for what its peer sends. Once the
    peer has sent everything, as a room's hook does before it waits for its
    answer, nothing the loop holds reaches the task. One then awaiting what the
    loop doesn't hold either, such as the reply on a connection it opened, whose
    reader asyncio holds weakly too, is a cycle of garbage, which Python's
    collector frees mid-wait: the connection closes unanswered. A hook held for
    the operator in a repository's process would end so, at once and with no
    decision, its call going on while the hold waits.
    """
    running: list[asyncio.Task[None]] = []

    async def held(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(answering(reader, writer))
        running.append(task)
        try:
            await task
        finally:
            running.remove(task)

    return await asyncio.start_unix_server(held, path=path, limit=limit)


class Launches(MutableModel, arbitrary_types_allowed=True):
    """The launches the service serves, each on its own sockets."""

    layout: HostLayout
    answerer: Answerer
    courier: Courier
    post: Post | None
    judge: LaunchJudge
    """Answers each launch's hooks its judge reads; a test gives a stub."""
    tools: list[RoomTools]
    room_routes: list[RoomRoute]
    reading: list[Route] = []
    """The control socket's routes whose kinds only read, which each launch's
    room is served for its repository alone (`confined`): set once the
    service's own handlers are made, since they're made over these launches."""
    modules: LaunchModules | None
    """Serves each launch's modules in its repository's process; none serves none."""
    line_limit: int
    """The longest line lup's tool server reads: one MCP message."""
    waker: Waker | None
    """Says what lup's tool server declares to each runtime, for it to take
    what's pushed to its session; none declares nothing."""
    pushes: Pushes
    """Each launch's open connections to lup's tool server, kept while each is
    served, for what's pushed to its session."""
    say: Callable[[str], None]
    names: Names
    """The name each session last had, so a session resumed takes it back, and
    its title in its runtime as lup last left it, so a title the operator gave
    there is told from lup's own."""
    spawns: Spawns | None = None
    """How each runtime recorded its subagents' spawns; none reads nothing, so
    subagents go without names until they rename themselves."""
    operators: dict[str, Records] = {}
    """Each runtime's records on this machine, by its name: a session whose
    record the operator's own directory holds is never kept as a launch's
    (`lup_dev.host.homes.kept`). A runtime missing here is checked for none."""
    bearings: Bearings | None = None
    """What a new main session is told of where its repository stands as it
    starts; none tells nothing."""
    refresh: Callable[[Register], list[Path]] | None = None
    """Brings the programs a recorded launch's room runs up to this copy's,
    returning those it rewrote; none leaves them as the launch wrote them."""
    podman: Podman | None = None
    """Renames a launch's container with it; none leaves each as it was named."""
    changes: Changes
    """Told once each hook is answered, and each room's request."""
    clock: Clock
    """When each conversation's activity began."""
    served: dict[str, Served] = {}
    opening: dict[str, Register] = {}
    """The launches whose registration is under way, by id, each named."""
    pending: list[asyncio.Task[None]] = []
    """What the launches' modules' hooks are running that nothing waits on."""

    def claims(self) -> list[Register]:
        """Return every launch holding a name: those served, and those whose registration is under way."""
        return [*(each.launch for each in self.served.values()), *self.opening.values()]

    async def open(self, registering: Register) -> Register:
        """Serve a launch: its name, its directory, its sockets inside, its record; and return it as it stands, named.

        Its name is the one it asks, made unique among those served (`claimed`),
        and its container is named after it (`container_name`), unless it names
        its own, as a record served again does.
        A launch served already, running a runtime the answerer doesn't know,
        whose judge isn't there, or asking exactly a name another holds, is
        refused. A directory left by a service before
        is used as it is, since the launch's room mounted it. Either way it's the
        operator's alone (mode 0700): a runtime's own messaging socket, placed in
        it, refuses a directory anyone else could reach (its adapter says which).
        """
        if registering.launch in self.served or registering.launch in self.opening:
            message = f"a launch with the id `{registering.launch}` is served already"
            raise HostError(message)
        name = claimed(registering, self.claims())
        container = registering.container or container_name(
            registering.repository, name
        )
        request = registering.model_copy(update={"name": name, "container": container})
        known = self.answerer.runtimes()
        if request.runtime not in known:
            message = (
                f"no runtime named `{request.runtime}`; "
                f"the service answers {', '.join(known)}"
            )
            raise HostError(message)
        if not request.judge.is_file():
            message = (
                f"the launch's judge, {request.judge}, isn't there: approving the "
                "repository's host zone (`lup-dev trust`) installs it"
            )
            raise HostError(message)
        sockets = self.layout.launch(request.launch)
        sockets.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        sockets.directory.chmod(0o700)
        kept = read_model(self.layout.conversations(request.launch), Conversations)
        conversations = kept or Conversations()

        def said(line: str) -> None:
            self.say(f"{request.launch}: {line}")

        async def hook(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await self.hook(request, conversations, reader, writer)

        async def tools(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await self.tools_served(request, conversations, reader, writer)

        # Its name is held while its modules start, so a launch registering
        # meanwhile can't claim it, and with it its container's name.
        self.opening[request.launch] = request
        try:
            offered = await self.offered(request)
            own = {room.kind: bound(room, request) for room in self.room_routes}
            reading = {
                route.kind: room
                for route in self.reading
                if (room := confined(route, request)) is not None
            }
            modules = self.modules
            relaying = (
                {}
                if modules is None
                else {kind: relayed(modules, request, kind) for kind in offered.kinds}
            )
            requests = Dispatcher(
                routes={**relaying, **reading, **own},
                answering="a room's request socket",
                say=said,
                changes=self.changes,
            )
            async with AsyncExitStack() as opening:
                hooks = await unix_server(sockets.hook, hook)
                opening.push_async_callback(closed, hooks)
                served = await unix_server(sockets.mcp, tools, self.line_limit)
                opening.push_async_callback(closed, served)
                asked = await unix_server(sockets.request, requests.connection)
                opening.pop_all()
            self.served[request.launch] = Served(
                launch=request,
                conversations=conversations,
                servers=[hooks, served, asked],
                offered=offered,
            )
        finally:
            del self.opening[request.launch]
        self.layout.record(request.launch).write_text(request.model_dump_json(indent=2))
        if Launched.named() in offered.events:
            launched = Happening(launch=request, event=Launched())
            self.background(self.happened(request, launched))
        self.say(
            f"{request.launch}: served as `{request.name}`, {request.runtime} in "
            f"{request.worktree}, judged by {request.judge}, its sockets in "
            f"{sockets.directory}"
        )
        return request

    async def renamed(self, launch: str, name: str) -> Register:
        """Rename launch `launch`, its record, its session's kept name and its container with it, and return it as it stands.

        Raise `HostError` where no launch is served by that id, or another holds
        the name or the container it would give, saying which.
        """
        served = self.served.get(launch)
        if served is None:
            message = f"no launch served is `{launch}`"
            raise HostError(message)
        holder = held(name, self.claims(), served.launch)
        if holder is not None:
            raise HostError(taken(holder, name))
        named = served.launch.model_copy(update={"name": name})
        self.recorded(named)
        session = served.conversations.session
        if session is not None:
            self.names.keep(session, name)
        self.say(f"{launch}: renamed from `{served.launch.name}` to `{name}`")
        await self.moved(named, container_name(named.repository, name))
        current = self.served.get(launch)
        return named if current is None else current.launch

    async def moved(self, launch: Register, container: str) -> None:
        """Rename `launch`'s container to `container` where podman has it, and record its name; otherwise it keeps its own.

        Where podman doesn't have it, the launch's room hasn't started yet, and
        its launcher runs it by the name recorded, or it's gone. Where podman
        can't rename it, that's said. The launch is read again once podman is
        done, since it may have been renamed again, or ended, meanwhile.
        """
        podman = self.podman
        before = launch.container
        if podman is None or before is None or before == container:
            return
        try:
            if not await asyncio.to_thread(podman.exists, before):
                return
            await asyncio.to_thread(podman.rename, before, container)
        except ContainerError as failed:
            self.say(
                f"{launch.launch}: its container keeps its name, {before}: {failed}"
            )
            return
        served = self.served.get(launch.launch)
        if served is not None:
            self.recorded(served.launch.model_copy(update={"container": container}))
        self.say(f"{launch.launch}: its container {before} is {container}")

    def recorded(self, launch: Register) -> None:
        """Keep `launch` as it stands, served and in its record."""
        served = self.served[launch.launch]
        self.served[launch.launch] = served.model_copy(update={"launch": launch})
        self.layout.record(launch.launch).write_text(launch.model_dump_json(indent=2))

    async def named_at(self, launch: str, heard: Heard) -> Named:
        """Name launch `launch` as its session starts or takes a prompt (`heard`), and return its name, with what the hook's answer says of it.

        Where the hook takes a title (`Heard.takes_title`), the runtime's title
        for the session is read against the one lup last left it with
        (`Names.title`): that one is lup's own, an old one a resume carries
        included, and the session's name outranks it; another is the operator's,
        as they renamed the session in the runtime, and is taken in a name's
        shape (`shaped`) where it's free. Either way it's kept as the one lup
        found, until an answer giving the runtime another is written (`hook`).
        At a start, the name the session last had comes next, where it's free,
        as a session resumed in a later launch; otherwise the launch keeps its
        own. The name is kept as the session's, and given as the runtime's title
        where the hook takes one and the runtime's differs. An operator's title
        that can't be taken is said: the runtime is given lup's name back.
        """
        current = self.served[launch].launch
        session = heard.session
        title = heard.title if heard.takes_title else None
        theirs = None if title in [None, self.names.title(session)] else title
        given = None if theirs is None else shaped(theirs)
        if title is not None:
            self.names.titled(session, title)
        starting = isinstance(heard.event, SessionStarted)
        last = self.names.last(session) if starting else None
        wanted = [
            each
            for each in [given, last]
            if each is not None and held(each, self.claims(), current) is None
        ]
        name = next(iter(wanted), current.name or "")
        if name != current.name:
            await self.renamed(launch, name)
        self.names.keep(session, name)
        if theirs is not None and name != given:
            self.say(
                f"{launch}: its session's title in its runtime, `{theirs}`, can't "
                f"be its name (not a name's shape, or another launch's), so the "
                f"runtime is given `{name}`"
            )
        gives = name if heard.takes_title and name and name != title else None
        renamed = [renamed_there(name)] if name == given != current.name else []
        told = [named_here(name)] if starting else renamed
        return Named(name=name, told=told, title=gives)

    async def offered(self, request: Register) -> Offered:
        """Hold the launch's repository's process, its judge and its modules, and return what the modules serve that the core doesn't.

        Where it can't start, it's said and the launch goes on with the core's
        tools alone, its judge's next hook starting the process again; a tool or
        a kind of request the core serves already is said and left to the core.
        """
        if self.modules is None:
            return Offered()
        try:
            offered = await self.modules.open(request)
        except HostError as failed:
            self.say(
                f"{request.launch}: its process didn't start, so its modules aren't "
                f"served, and its judge's next hook starts it again: {failed}"
            )
            return Offered()
        names = [spec.name for tools in self.tools for spec in tools.specs()]
        kinds = [room.kind for room in self.room_routes] + [
            route.kind for route in self.reading
        ]
        taken = [spec.name for spec in offered.tools if spec.name in names] + [
            kind for kind in offered.kinds if kind in kinds
        ]
        if taken:
            self.say(
                f"{request.launch}: its modules serve {', '.join(taken)}, which the "
                "core serves already, so the core's answer them"
            )
        return Offered(
            tools=[spec for spec in offered.tools if spec.name not in names],
            kinds=[kind for kind in offered.kinds if kind not in kinds],
            events=offered.events,
            looks=offered.looks,
        )

    def background(self, running: Coroutine[None, None, None]) -> None:
        """Run a launch's modules' hooks without waiting on them, keeping the task until it's done."""
        task = asyncio.create_task(running)
        self.pending = [*(each for each in self.pending if not each.done()), task]

    async def happened(self, request: Register, happening: Happening) -> None:
        """Tell the launch's modules an event their hooks run at, and say what failed among them."""
        if self.modules is None:
            return
        try:
            reply = await self.modules.ask(request, happening)
        except HostError as failed:
            self.say(
                f"{request.launch}: its modules' hooks didn't run at "
                f"{happening.event.named()}: {failed}"
            )
            return
        match reply:
            case Happened(failures=failures):
                for failure in failures:
                    self.say(f"{request.launch}: {failure}")
            case _:
                self.say(
                    f"{request.launch}: its modules replied {reply.kind} at "
                    f"{happening.event.named()}"
                )

    async def hook(
        self,
        request: Register,
        conversations: Conversations,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Answer one hook heard on a launch's socket, and close the connection.

        The payload is read to the end and answered, always with something:
        `UNDECIDED` where nothing is decided or told, so the room's hook tells an
        answer from a lost connection. Where answering fails even so, the
        failure is said, with its traceback, and the hook is answered in the
        runtime's terms as one its judge couldn't answer. Where the hook is gone
        before its answer is written, what it would have told is put back as
        waiting; otherwise a title the answer gives the session's runtime is
        kept as the one lup left it with (`Names.titled`). The launch is taken
        as it stands (`current`), not as the socket's closure had it at
        registration: a rename since changed its name and its container.
        """
        request = self.current(request)
        payload = (await reader.read()).decode()
        try:
            spoken = await self.answered(request, conversations, payload, writer)
        except Exception as failure:
            told = "".join(traceback.format_exception(failure))
            self.say(f"{request.launch}: answering a hook failed:\n{told}")
            failed = (
                f"the host service failed answering it, {failure!r}; its output "
                f"says more, {self.layout.log} when it runs in the background"
            )
            unanswered = self.answerer.unanswered(request.runtime, payload, failed)
            spoken = Spoken(answer=unanswered)
        self.changes.changed(spoken.touched)
        answer = spoken.answer if spoken.answer.strip() else UNDECIDED
        try:
            writer.write(answer.encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except ConnectionError as gone:
            self.say(f"{request.launch}: the hook was gone before its answer: {gone}")
            self.returned(spoken.posted)
            return
        if spoken.titled is not None:
            self.names.titled(spoken.titled.session, spoken.titled.title)
        self.say(f"{request.launch}: answered a hook")

    def returned(self, posted: Posted) -> None:
        """Put back as waiting what an answer that didn't reach its hook would have told."""
        if self.post is not None and posted.numbers:
            self.post.returned(posted)

    async def answered(
        self,
        request: Register,
        conversations: Conversations,
        payload: str,
        writer: asyncio.StreamWriter,
    ) -> Spoken:
        """Return what one hook prints: the judge's answer where it reads the hook, none where it doesn't, with what the courier adds.

        The conversation the hook names gets lup's id here the first time, and
        is told what the post says waits for it, in what room the judge's answer
        leaves; the post hears of the conversation that spawned it too, where a
        conversation did (`Conversations.spawner`), which hears of its end. The
        launch's conversations are kept, with what each is doing, so a service
        started again knows them. One of the runtime's own agents
        (`Conversation.internal`) is answered with nothing once it's linked: no
        judge reads its hooks, so none of its calls counts as running or holds;
        no module hears of it; nothing is told it, and what it's doing isn't
        kept, since it's no conversation of the operator's: its runtime runs it
        for its own features, each adapter saying how it's told apart
        (`Spawned.internal`).

        A session's own turn's end puts its last message, or the error from
        the model's API it ended on, before the operator (`Post.concluded`)
        before anything is told, so the note is theirs to read whether the end
        is held or let through. A session's own
        start, and its own prompt where the hook takes a title, name its launch
        (`named_at`); a session's own conversation starting anew is told its
        bearings beside its name (`Bearings`), once. A payload the courier can't read goes to the judge as it
        is, which answers it or says it couldn't; where the courier can't add to
        the judge's answer, the answer goes out as the judge gave it, and what
        it would have told is put back. Either is said.
        """
        try:
            heard = self.courier.heard(request.runtime, payload)
        except ValueError as unread:
            self.say(
                f"{request.launch}: a hook lup couldn't read goes to its judge as it "
                f"is: {unread}"
            )
            return Spoken(answer=await self.judgement(request, payload, writer))
        if request.home is not None:
            kept(
                self.layout,
                request.runtime,
                heard.session,
                request.home,
                self.operators.get(request.runtime),
            )
        conversation = conversations.named(heard.session, heard.agent)
        noted = self.spawning(request, conversations, conversation, heard, payload)
        conversation, said = noted.conversation, noted.said
        doing = self.activity(heard)
        if not conversation.internal and doing is not None:
            conversations.activities = {
                **conversations.activities,
                conversation.id: doing,
            }
        write_model(self.layout.conversations(request.launch), conversations)
        if conversation.internal:
            return Spoken(answer="")
        touched = [
            Touched(
                repository=request.repository,
                runtime=request.runtime,
                session=heard.session,
                agent=heard.agent,
                by=heard.event.named(),
            )
        ]
        if heard.event.named() in self.served[request.launch].offered.events:
            happening = Happening(
                launch=request, event=heard.event, conversation=conversation
            )
            self.background(self.happened(request, happening))
        answer = await self.judgement(request, payload, writer) if heard.judged else ""
        own = heard.agent is None
        starting = isinstance(heard.event, SessionStarted) and own
        prompted = isinstance(heard.event, TurnStarted) and own and heard.takes_title
        named = (
            await self.named_at(request.launch, heard) if starting or prompted else None
        )
        bearings = (
            await self.bearings.told(
                self.current(request), heard.session, self.running()
            )
            if starting and heard.fresh and self.bearings is not None
            else None
        )
        naming = [
            *([] if named is None else named.told),
            *([] if bearings is None else [bearings]),
            *said,
        ]
        room = (
            heard.fits
            - len(answer.encode())
            - sum(len(each.encode()) for each in naming)
        )
        if self.post is not None and isinstance(heard.event, TurnEnded) and own:
            await self.post.concluded(request, conversation, heard)
        parent = conversations.spawner(conversation)
        posted = (
            Posted()
            if self.post is None
            else await self.post.telling(request, conversation, parent, heard, room)
        )
        title = None if named is None else named.title
        telling = Telling(
            caller=conversation.id, items=[*naming, *posted.items], title=title
        )
        try:
            told = self.courier.told(request.runtime, payload, answer, telling)
        except ValueError as unread:
            self.say(
                f"{request.launch}: the judge's answer goes out as it gave it, since "
                f"lup couldn't add to it: {unread}"
            )
            self.returned(posted)
            return Spoken(answer=answer, touched=touched)
        titled = None if title is None else Titled(session=heard.session, title=title)
        return Spoken(answer=told, posted=posted, titled=titled, touched=touched)

    async def judgement(
        self, request: Register, payload: str, writer: asyncio.StreamWriter
    ) -> str:
        """Return the judge's answer to one hook, or where it can't answer, the runtime's word that it couldn't, saying why.

        What the judge said beside is the service's to tell, in full; the hook's
        answer points there. It waits for as long as judging does, a hold's wait
        for the operator included. Where the hook's runtime ends it meanwhile
        (`hung_up`), as when the operator interrupts its call, or the launch
        ends (`Served.ending`), the hook is marked ended (`HostLayout.ended`),
        so a hold its call waits on gives up as an interrupted call's
        (`docs/judging-writes.md`, *Asking the operator*), and the judge's
        answer, which nothing hears, is awaited still; the mark goes once it's
        given.
        """
        judging = asyncio.ensure_future(self.judge.judged(request, payload))
        ended = self.layout.ended(payload)
        served = self.served.get(request.launch)
        ending = asyncio.Event() if served is None else served.ending
        closing = asyncio.ensure_future(ending.wait())
        try:
            async with hung_up(writer) as gone:
                await asyncio.wait(
                    [judging, gone, closing], return_when=asyncio.FIRST_COMPLETED
                )
                if not judging.done():
                    ended.parent.mkdir(parents=True, exist_ok=True)
                    ended.touch()
                    why = (
                        "it ended while its judge was answering a hook"
                        if closing.done()
                        else "its runtime ended a hook its judge was answering"
                    )
                    self.say(
                        f"{request.launch}: {why}, so a hold its call waits on gives up"
                    )
            return await judging
        except HostError as failed:
            self.say(f"{request.launch}: its judge couldn't answer a hook: {failed}")
            failure = (
                f"{failed}; the host service's output says more, {self.layout.log} "
                "when it runs in the background"
            )
            return self.answerer.unanswered(request.runtime, payload, failure)
        finally:
            closing.cancel()
            if not judging.done():
                judging.cancel()
            ended.unlink(missing_ok=True)

    async def tools_served(
        self,
        request: Register,
        conversations: Conversations,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Serve lup's tools over one connection on a launch's `mcp.sock`, until it closes, keeping it among the launch's open connections meanwhile, for what's pushed to its session.

        The server declares what the launch's runtime reads to take what it
        pushes (`Waker.capabilities`). Where serving breaks (a line past the limit, a connection reset), it's
        said with its traceback, and the connection closes.
        """
        toolset = LaunchTools(
            launch=lambda: self.current(request),
            tools=self.toolsets(request),
            conversations=conversations,
            say=self.say,
        )
        outbox = Outbox()
        self.pushes.opened(request.launch, outbox)
        try:
            await serve(
                toolset,
                reader,
                writer,
                name=SERVER,
                experimental=(
                    {}
                    if self.waker is None
                    else self.waker.capabilities(request.runtime)
                ),
                outbox=outbox,
            )
        except Exception as failure:
            told = "".join(traceback.format_exception(failure))
            self.say(f"{request.launch}: serving lup's tools failed:\n{told}")
        finally:
            self.pushes.closed(request.launch, outbox)
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError as gone:
            self.say(
                f"{request.launch}: lup's tool server was gone before it closed: {gone}"
            )

    def toolsets(self, request: Register) -> list[RoomTools]:
        """Return what serves launch `request`'s session lup's tools: the core's, `rename`, and its modules'."""
        offered = self.served[request.launch].offered
        modules = (
            []
            if self.modules is None
            else [ModulesTools(modules=self.modules, offered=offered)]
        )
        return [*self.tools, Naming(launches=self), *modules]

    async def close(self, launch: str) -> None:
        """End a launch: its sockets closed, its hold on its repository's process let go, its record and directory removed.

        A hook of its the judge is still answering is marked ended
        (`judgement`), so a hold its call waits on gives up as an interrupted
        call's. The directory goes with whatever the room left in it.
        """
        served = self.served.pop(launch, None)
        if served is None:
            message = f"no launch named `{launch}` is served"
            raise HostError(message)
        served.ending.set()
        for server in served.servers:
            await closed(server)
        if Stopped.named() in served.offered.events:
            stopped = Happening(launch=served.launch, event=Stopped())
            await self.happened(served.launch, stopped)
        if self.modules is not None:
            await self.modules.close(served.launch)
        self.layout.record(launch).unlink(missing_ok=True)
        self.layout.conversations(launch).unlink(missing_ok=True)
        shutil.rmtree(self.layout.launch(launch).directory)
        self.say(f"{launch}: ended")

    def spawning(
        self,
        request: Register,
        conversations: Conversations,
        conversation: Conversation,
        heard: Heard,
        payload: str,
    ) -> Noted:
        """Note what a hook says of subagents, and return the conversation as it stands, with what it's told of lup's tools and of names.

        A subagent heard the first time is linked to its spawn as its runtime
        recorded it (`Spawns`, `Conversations.linked`): its parent, its kind,
        the name its parent gave, whether it reads its session's guidance, and
        whether it's one of the runtime's own agents, which no spawn links to
        and which is told nothing (`Conversation.internal`); one with no name
        is asked to name itself, beside a call, never as the reason its turn's
        end is held.
        A subagent that doesn't read the guidance is told once, at its first
        hook that isn't its turn's end, the tools lup serves it, which the
        guidance lists (`introduction`). Not at its end, which would hold it to
        read them.
        The conversation spawning one isn't asked to name it: the subagent
        knows its task, and what a spawning call is told comes beside its
        result, once the subagent has started.
        """
        first = heard.agent is not None and not conversation.linked
        if first:
            spawned = (
                None
                if self.spawns is None
                else self.spawns.spawned(request.runtime, payload)
            )
            conversation = conversations.linked(conversation, spawned)
        if conversation.internal:
            return Noted(conversation=conversation)
        calling = isinstance(heard.event, CallStarted | CallFinished)
        naming = (
            [unnamed(conversations.path(conversation, self.named(request)))]
            if first and conversation.name is None and calling
            else []
        )
        introducing: list[str] = []
        ending = isinstance(heard.event, TurnEnded | ConversationEnded)
        if heard.agent is not None and not conversation.introduced and not ending:
            conversation = conversations.kept(
                conversation.model_copy(update={"introduced": True})
            )
            tools = [spec for each in self.toolsets(request) for spec in each.specs()]
            introducing.append(introduction(tools))
        return Noted(conversation=conversation, said=[*introducing, *naming])

    def subagent_renamed(self, launch: str, subagent: Conversation, name: str) -> str:
        """Rename `subagent`, a subagent of launch `launch`, and return how it's called: its launch's name, then each name down to it.

        Raise `HostError` where another subagent of the launch has the name,
        saying which.
        """
        served = self.served[launch]
        conversations = served.conversations
        holder = conversations.holder(name, subagent.id)
        named = self.named(served.launch)
        if holder is not None:
            message = (
                f"`{name}` is `{conversations.path(holder, named)}`'s: pick another "
                "name"
            )
            raise HostError(message)
        renamed = conversations.kept(subagent.model_copy(update={"name": name}))
        write_model(self.layout.conversations(launch), conversations)
        path = conversations.path(renamed, named)
        self.say(f"{launch}: a subagent named itself `{path}`")
        return path

    def held(self, request: SetHolding) -> bool:
        """Turn the operator's switch for one conversation of a launch on or off, keep it with the launch's conversations, and return it as it stands.

        Raise `HostError` where no launch is served by that id, or no hook of it
        has named that conversation.
        """
        served = self.served.get(request.launch)
        if served is None:
            message = f"no launch served is `{request.launch}`"
            raise HostError(message)
        conversations = served.conversations
        found = [
            each
            for each in conversations.known
            if each.session == request.session and each.agent == request.agent
        ]
        if not found:
            message = (
                f"no conversation of launch `{request.launch}` is session "
                f"{request.session}"
                + ("" if request.agent is None else f"'s {request.agent}")
            )
            raise HostError(message)
        [conversation] = found
        conversations.kept(conversation.model_copy(update={"holding": request.on}))
        write_model(self.layout.conversations(request.launch), conversations)
        said = "holds" if request.on else "no longer holds"
        path = conversations.path(conversation, self.named(served.launch))
        self.say(f"{request.launch}: the operator {said} each flagged write of {path}")
        return request.on

    def holding(self, request: ShowHolding, repository: Path | None = None) -> bool:
        """Say whether the operator holds each flagged write of a conversation of `request`'s runtime, in whichever launch serves it, of `repository` alone where one's given; not where none does.

        The switch covers a conversation and its subagents: one is held where
        its own switch is on, or that of any conversation above it, up to its
        session's own.
        """
        return any(
            switched(served.conversations, each)
            for served in self.served.values()
            if served.launch.runtime == request.runtime
            and repository in (None, served.launch.repository)
            for each in served.conversations.known
            if each.session == request.session and each.agent == request.agent
        )

    def talkers(self, served: Served) -> list[Talker]:
        """Return a launch's conversations as the operator is shown them: its latest session's own, then each of its subagents under its parent, in the order heard; none before any hook named one.

        The runtime's own agents (`Conversation.internal`) aren't among them:
        no conversation spawned them, so they're no subagent of the operator's
        to show, to count as running or ended, or to wait on.
        """
        conversations = served.conversations
        launch = self.named(served.launch)

        def talker(each: Conversation, depth: int) -> Talker:
            parent = None if each.parent is None else conversations.calling(each.parent)
            return Talker(
                path=conversations.path(each, launch),
                own=each.own(launch),
                session=each.session,
                agent=each.agent,
                kind=each.kind,
                parent=None if parent is None else conversations.path(parent, launch),
                depth=depth,
                activity=conversations.activities.get(each.id),
                holding=each.holding,
            )

        def under(parent: str, depth: int) -> list[Talker]:
            children = [
                each
                for each in conversations.known
                if each.parent == parent
                and each.agent is not None
                and not each.internal
            ]
            return [
                found
                for each in children
                for found in [talker(each, depth), *under(each.id, depth + 1)]
            ]

        main = conversations.main()
        return [] if main is None else [talker(main, 0), *under(main.id, 1)]

    def activity(self, heard: Heard) -> Activity | None:
        """Return what a hook says its conversation is doing, from the hook on: running the call it starts, between calls, or ended; none where it says nothing of it.

        A worktree asked for names the session alone, whichever conversation
        asks, and comes while that conversation's call runs, so it leaves each
        as it was.
        """
        at = self.clock.now()
        match heard.event:
            case CallStarted(tool=tool):
                return Activity(state="calling", since=at, tool=tool, lups=heard.served)
            case ConversationEnded():
                return Activity(state="ended", since=at)
            case WorktreeAsked():
                return None
            case _:
                return Activity(state="idle", since=at)

    def running(self) -> list[Running]:
        """Return the main conversation of each launch served, as its latest hook named it; none for a launch no hook has named one of."""
        return [
            Running(
                launch=served.launch,
                name=self.named(served.launch),
                session=served.conversations.session,
            )
            for served in self.served.values()
            if served.conversations.session is not None
        ]

    def current(self, request: Register) -> Register:
        """Return launch `request` as it stands: as served, its name and its container with each rename since it registered; as given where it isn't served."""
        served = self.served.get(request.launch)
        return request if served is None else served.launch

    def named(self, request: Register) -> str:
        """Return launch `request`'s name as it stands."""
        current = self.current(request)
        return current.name or current.launch

    async def reopen(self) -> None:
        """Serve each launch recorded by a service before, where its room mounted it, its room's programs brought up to this copy's (`refresh`).

        A record that doesn't read as a launch's, or that this service can't serve,
        is said and left in place.
        """
        # Each launch's conversations are kept beside its record, and aren't a record.
        records = [
            each
            for each in sorted(self.layout.launches.glob("*.json"))
            if each
            != self.layout.conversations(each.stem.removesuffix(".conversations"))
        ]
        for record in records:
            try:
                request = Register.model_validate_json(record.read_text())
                await self.open(request)
            except (ValidationError, HostError) as failure:
                self.say(f"{record} isn't served again: {failure}")
                continue
            if self.refresh is not None:
                for refreshed in self.refresh(request):
                    self.say(f"{request.launch}: {refreshed} brought up to this copy's")

    async def shut(self) -> None:
        """Close every launch's sockets, keeping its record and its directory, and end every repository's process."""
        for served in self.served.values():
            for server in served.servers:
                await closed(server)
        if self.modules is not None:
            await self.modules.stop()
        self.served = {}


class NewName(Model):
    """The name you take."""

    name: str = Field(
        description=(
            "Your name from now on: letters, digits, `-`, `_` and `.`, after your "
            "task, such as `gate-on-push`."
        )
    )


class Namer(Model, arbitrary_types_allowed=True):
    """One conversation of a launch's session, renaming itself: the session's own, or a subagent."""

    launches: Launches
    launch: str
    caller: str
    """lup's id for the conversation calling."""

    async def rename(self, new: NewName) -> str:
        """Name yourself after your task.

        Your name is how the operator, lup's commands and other sessions call
        you, and what the operator's inbox says your items come from. Call it
        once you know your task, unless the operator or your parent named you;
        call it again when the task changes. From a subagent it names you
        alone, never your session. A name another holds is refused, saying
        whose; pick another.
        """
        try:
            wanted = handle(new.name)
            served = self.launches.served[self.launch]
            caller = served.conversations.calling(self.caller)
            if caller is not None and caller.agent is not None:
                path = self.launches.subagent_renamed(self.launch, caller, wanted)
                return (
                    f"You're `{path}` to lup and the operator now. The name your "
                    "runtime gave you at your spawn, which your parent's own tools "
                    "use, stays as it was."
                )
            named = await self.launches.renamed(self.launch, wanted)
        except (HostError, ValueError) as refused:
            return f"Not renamed: {refused}"
        return f"You're `{named.name}` now."

    def tools(self) -> list[AgentTool]:
        """Return the naming tool, bound to this launch."""
        return [lup.tool(self.rename)]


class Naming(Model, RoomTools, arbitrary_types_allowed=True):
    """The tool a session renames itself with, which the service serves beside the inbox's."""

    launches: Launches

    @override
    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in Namer.model_construct().tools()]

    @override
    async def call(
        self,
        name: str,
        arguments: JsonValue,
        launch: Register,
        caller: Conversation,
        call: str | None,
    ) -> Answer:
        """Rename `caller`, a conversation of `launch`, as it asks; arguments that don't validate are refused, saying why."""
        namer = Namer(launches=self.launches, launch=launch.launch, caller=caller.id)
        [tool] = [tool for tool in namer.tools() if tool.spec().name == name]
        match await tool.call(arguments):
            case Accepted(answer=answer):
                return Answer(text=answer)
            case Rejected(rejection=rejection):
                return Answer(text=f"Refused: {rejection.reason}", error=True)


class Registering(Model, Handler[Register]):
    """Answers `Register`: the launch served, its socket directory replied."""

    launches: Launches

    @override
    def request(self) -> type[Register]:
        return Register

    @override
    async def answer(self, request: Register) -> Reply:
        served = await self.launches.open(request)
        return Registered(
            directory=self.launches.layout.launch(served.launch).directory,
            name=served.name or "",
            container=served.container or "",
        )


class Renaming(Model, Handler[Rename]):
    """Answers `Rename`: the launch renamed, as it stands replied."""

    launches: Launches

    @override
    def request(self) -> type[Rename]:
        return Rename

    @override
    async def answer(self, request: Rename) -> Reply:
        return Renamed(launch=await self.launches.renamed(request.launch, request.name))


class HoldingSetting(Model, Handler[SetHolding]):
    """Answers `SetHolding`: the operator's switch for a conversation, as it stands."""

    launches: Launches

    @override
    def request(self) -> type[SetHolding]:
        return SetHolding

    @override
    async def answer(self, request: SetHolding) -> Reply:
        return Holding(on=self.launches.held(request))


class HoldingShowing(Model, Reading[ShowHolding]):
    """Answers `ShowHolding`: whether the operator holds each flagged write of a conversation; for a room, of a conversation of its repository's launches alone."""

    launches: Launches

    @override
    def request(self) -> type[ShowHolding]:
        return ShowHolding

    @override
    async def answer(self, request: ShowHolding) -> Reply:
        return Holding(on=self.launches.holding(request))

    @override
    async def scoped(self, request: ShowHolding, repository: Path) -> Reply:
        return Holding(on=self.launches.holding(request, repository))


class Ending(Model, Handler[Unregister]):
    """Answers `Unregister`: the launch ended."""

    launches: Launches

    @override
    def request(self) -> type[Unregister]:
        return Unregister

    @override
    async def answer(self, request: Unregister) -> Reply:
        await self.launches.close(request.launch)
        return Done()


class Listing(Model, Reading[ListLaunches], arbitrary_types_allowed=True):
    """Answers `ListLaunches`: each launch served, as it was registered, and how each repository's views look; for a room, its repository's alone, with whether each one's container runs."""

    launches: Launches
    asking: RepositoryAsking | None = None
    """Says how each repository's views look; none says nothing of them."""
    standing: Looks = Looks()
    """How lup's default declaration's views look, which stand in for a
    repository's until its process says its own."""

    def looks(self) -> dict[Path, Looks]:
        """Return how each repository's views look, as its process last said."""
        return {} if self.asking is None else self.asking.looks()

    @override
    def request(self) -> type[ListLaunches]:
        return ListLaunches

    @override
    async def answer(self, request: ListLaunches) -> Reply:
        served = list(self.launches.served.values())
        return Listed(
            launches=[each.launch for each in served],
            sessions=self.launches.names.all(),
            talkers={
                each.launch.launch: self.launches.talkers(each) for each in served
            },
            looks=self.looks(),
            standing=self.standing,
        )

    @override
    async def scoped(self, request: ListLaunches, repository: Path) -> Reply:
        """List the launches of `repository` alone, each session's name only for a session of theirs, and whether each one's container runs, which a room has no podman to ask."""
        served = [
            each
            for each in self.launches.served.values()
            if each.launch.repository == repository
        ]
        talkers = {each.launch.launch: self.launches.talkers(each) for each in served}
        names = self.launches.names.all()
        podman = self.launches.podman

        def runs(container: str | None) -> bool:
            return (
                podman is not None
                and container is not None
                and podman.exists(container)
            )

        return Listed(
            launches=[each.launch for each in served],
            sessions={
                talker.session: names[talker.session]
                for each in talkers.values()
                for talker in each
                if talker.session in names
            },
            talkers=talkers,
            running={
                each.launch.launch: await asyncio.to_thread(runs, each.launch.container)
                for each in served
            },
            looks={
                place: looks
                for place, looks in self.looks().items()
                if place == repository
            },
            standing=self.standing,
        )


class Stopping(Model, Handler[Stop], arbitrary_types_allowed=True):
    """Answers `Stop`: the service stops once the reply is written."""

    stopped: asyncio.Event

    @override
    def request(self) -> type[Stop]:
        return Stop

    @override
    async def answer(self, request: Stop) -> Reply:
        self.stopped.set()
        return Done()


class Companion(ABC):
    """What the service runs beside it, a program or work of its own: begun once the service listens, ended as it stops."""

    @abstractmethod
    async def begin(self) -> None:
        """Start it; raise `HostError` where it can't, saying why, and the service goes on without it."""

    @abstractmethod
    async def end(self) -> None:
        """Stop it, where it runs."""


class Serving(Model, arbitrary_types_allowed=True):
    """A service while it serves: it stops once `stopped` is set."""

    stopped: asyncio.Event


class HostService(Model, arbitrary_types_allowed=True):
    """The host service: the control socket, each launch's sockets, the handlers and tools modules register."""

    layout: HostLayout
    answerer: Answerer
    courier: Courier
    """Reads each runtime's hooks, and adds to their answers."""
    post: Post | None = None
    """What each conversation is told at its hooks, from its inbox; none tells
    nothing."""
    say: Callable[[str], None]
    """Where the service tells what it does: the terminal, or its log."""
    judge: LaunchJudge
    """Answers each launch's hooks its judge reads: in its repository's process,
    which serves its modules too (`WorkerJudge`); a test gives a stub."""
    routes: list[Route] = []
    """The handlers modules register on the control socket, beside the service's own."""
    room_routes: list[RoomRoute] = []
    """The handlers modules register for the room's requests, on each launch's
    `request.sock`."""
    tools: list[RoomTools] = []
    """The core's tools, served each launched session on its `mcp.sock`."""
    modules: LaunchModules | None = None
    """Serves each launch's modules, their tools and their answers to the room's
    requests, in its repository's process; none serves the core's alone."""
    asking: RepositoryAsking | None = None
    """Asks each repository's process with no launch, and says how each
    repository's views look, for the listing (`WorkersAsking`); none says
    nothing of them."""
    standing: Looks = Looks()
    """How lup's default declaration's views look, which the listing gives to
    stand in for a repository's until its process says its own (`cli.py`
    resolves it); none says nothing."""
    line_limit: int = 16 * 1024 * 1024
    """The longest line lup's tool server reads, one MCP message: well above
    asyncio's 64 KiB, which a long message to the operator could pass."""
    waker: Waker | None = None
    """Says what lup's tool server declares to each runtime, for it to take
    what's pushed to its session (`cli.py`'s adapters); none declares nothing."""
    pushes: Pushes = Field(default_factory=Pushes)
    """Each launch's open connections to lup's tool server, which the inbox
    pushes to its session through, given the same (`cli.py`)."""
    spawns: Spawns | None = None
    """How each runtime recorded its subagents' spawns, read once at a
    subagent's first hook (`cli.py`'s adapters); none reads nothing."""
    operators: dict[str, Records] = {}
    """Each runtime's records on this machine, by its name, for whether the
    operator's own directory holds a session (`Launches.operators`)."""
    bearings: Bearings | None = None
    """What a new main session is told of where its repository stands as it
    starts (`inbox/bearings.py`, which `cli.py` gives); none tells nothing."""
    refresh: Callable[[Register], list[Path]] | None = None
    """Brings the programs a recorded launch's room runs up to this copy's when
    the service serves it again, returning those it rewrote: git's remote
    helper and lup's MCP bridge (`cli.py`), so a restart on an approved copy
    reaches running rooms. None leaves them as the launch wrote them."""
    podman: Podman | None = None
    """Renames each launch's container with it, after its repository and its new
    name (`container_name`); none leaves each as it was named, as in tests."""
    changes: Changes = Field(default_factory=Changes)
    """Told wherever what the service holds may have changed, so each watch
    answers its request again: the service's own sockets tell it, and so does
    the inbox's store, given the same (`cli.py`)."""
    clock: Clock = Field(default_factory=SystemClock)
    """When each conversation's activity began; a test gives its own."""
    companions: list[Companion] = []
    """The programs it runs beside it, the dashboard's server among them
    (`host/dashboard.py`): each begun once it listens, a failure said, and ended
    as it stops."""

    @model_validator(mode="after")
    def distinct(self) -> Self:
        """Refuse two handlers for one kind, on the control socket and the room's alike, and two modules serving one tool."""
        kinds = Counter(
            [
                Register.named(),
                Unregister.named(),
                ListLaunches.named(),
                Stop.named(),
                *(route.kind for route in self.routes),
                *(route.kind for route in self.room_routes),
            ]
        )
        repeated = [kind for kind, count in kinds.items() if count > 1]
        if repeated:
            message = f"more than one handler for {', '.join(sorted(repeated))}"
            raise ValueError(message)
        names = Counter(spec.name for tools in self.tools for spec in tools.specs())
        twice = [name for name, count in names.items() if count > 1]
        if twice:
            message = f"more than one module serves {', '.join(sorted(twice))}"
            raise ValueError(message)
        return self

    async def begun(self) -> None:
        """Begin each companion, saying one that can't, which the service goes on without."""
        for companion in self.companions:
            try:
                await companion.begin()
            except HostError as failed:
                self.say(
                    f"The host service goes on without a program beside it: {failed}"
                )

    async def serve(self) -> None:
        """Serve until a `Stop` request, or until cancelled."""
        async with self.serving() as serving:
            await serving.stopped.wait()

    @asynccontextmanager
    async def serving(self) -> AsyncGenerator[Serving]:
        """Serve while the context is open: the control socket, and each launch recorded.

        The service holds a lock for its whole life, which the OS frees, so a second
        refuses to start while one runs; a control socket left by a service that
        died is replaced. On leaving, the sockets close, the launches stay recorded,
        and the judges of answers in flight are killed, unheard.
        """
        self.layout.sockets.mkdir(mode=0o700, parents=True, exist_ok=True)
        life = FileLock(self.layout.lock, timeout=0)
        try:
            life.acquire()
        except Timeout as running:
            message = f"a host service runs already, on {self.layout.control}"
            raise HostError(message) from running
        launches = Launches(
            layout=self.layout,
            answerer=self.answerer,
            courier=self.courier,
            post=self.post,
            judge=self.judge,
            tools=self.tools,
            room_routes=self.room_routes,
            modules=self.modules,
            line_limit=self.line_limit,
            waker=self.waker,
            pushes=self.pushes,
            say=self.say,
            names=Names(path=self.layout.names),
            spawns=self.spawns,
            operators=self.operators,
            bearings=self.bearings,
            refresh=self.refresh,
            podman=self.podman,
            changes=self.changes,
            clock=self.clock,
        )
        stopped = asyncio.Event()
        own = [
            Route.to(Registering(launches=launches)),
            Route.to(Ending(launches=launches)),
            Route.reading(
                Listing(launches=launches, asking=self.asking, standing=self.standing)
            ),
            Route.to(Renaming(launches=launches)),
            Route.to(HoldingSetting(launches=launches)),
            Route.reading(HoldingShowing(launches=launches)),
            Route.to(Stopping(stopped=stopped)),
        ]
        launches.reading = [
            route for route in [*own, *self.routes] if route.scoped is not None
        ]
        control = Dispatcher(
            routes={route.kind: route for route in [*own, *self.routes]},
            answering="the service",
            say=self.say,
            changes=self.changes,
        )
        try:
            await launches.reopen()
            server = await unix_server(self.layout.control, control.connection)
            watches = await unix_server(
                self.layout.watch, control.watching, self.line_limit
            )
            self.say(f"The host service listens on {self.layout.control}.")
            try:
                await self.begun()
                yield Serving(stopped=stopped)
            finally:
                for companion in self.companions:
                    await companion.end()
                await closed(watches)
                await closed(server)
        finally:
            await launches.shut()
            life.release()
            self.say("The host service stopped.")
