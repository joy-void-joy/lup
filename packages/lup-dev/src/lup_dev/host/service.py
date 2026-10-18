"""The host service: one per user, on the host, which rooms call for what only it can do.

`docs/launch.md`, *On the host: the service*. It listens on a control socket on the
host only, taking typed requests (`host/protocol.py`), each answered by the handler
routed its kind: the service's own register a launch, end one, list those served,
and stop the service; a module registers its own handlers with the service it
builds (`Route.to`).

Each launch it serves gets a directory of its own, which the launch's room mounts
at `/run/lup`, so the service knows which launch speaks by the socket it hears it
on. It holds three sockets:
- `hook.sock` takes a runtime's raw payload, read to the end. The service reads
  it through the `Courier` (`host/courier.py`), which says whether the launch's
  judge reads it. One it reads is answered by running the judge, its
  repository's approved copy of `lup-dev`, as a process of its own (`<judge>
  hook <runtime>`, the payload on its input, its answer what it prints), so each
  session is judged by the code approved for its repository; one it doesn't is
  answered by the service itself, without starting the judge, as no decision.
  Every answer goes out through the `Courier` again, a call to lup's tools
  rewritten to carry lup's id for the conversation calling, and what the `Post`
  says waits for the conversation added: counted told once the answer is
  written, and put back where the hook was gone first. Hooks for parallel
  calls arrive at once and a hold waits for hours, so each judge is spawned
  through asyncio and awaited on the event loop, which goes on serving meanwhile.
  Where the judge can't answer (its command missing, or ending with a failure, a
  payload it can't read among them), the service answers in the runtime's own
  terms through the `Answerer`, rather than closing empty, which the runtime
  would take as no decision.
- `mcp.sock` serves lup's tools, and `request.sock` the room's requests, each
  routed to the core's own (`host/rooms.py`) or to the launch's modules, which
  run in a process of the launch's own, of its repository's approved copy,
  started when the launch opens and stopped when it ends (`host/workers.py`).

Each launch is recorded beside its directory, so a service started after one
stopped serves the same launches, in the directories their rooms mounted. The
service stops without waiting for the answers in flight: their judges are
killed, and their hooks hear nothing.
"""

import asyncio
import shlex
import shutil
import traceback
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Self, override

from filelock import FileLock, Timeout
from pydantic import Field, JsonValue, ValidationError, model_validator

from lup.tools.serving import Answer, serve
from lup.tools.tool import Accepted, AgentTool, ToolSpec, lup_tool
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
)
from lup_dev.host.names import Names, claimed, held, shaped, taken
from lup_dev.host.protocol import (
    Activity,
    Done,
    HostError,
    Listed,
    ListLaunches,
    Refused,
    Register,
    Registered,
    Rename,
    Renamed,
    Reply,
    Request,
    Stop,
    Talker,
    Unregister,
    handle,
)
from lup_dev.host.rooms import SERVER, LaunchTools, RoomRoute, RoomTools
from lup_dev.host.watch import Changes
from lup_dev.host.workers import (
    Called,
    Calling,
    Happened,
    Happening,
    LaunchModules,
    Offered,
    Passed,
    Relayed,
    Relaying,
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


class Asked(Model):
    """One program the service runs: a hook put to a launch's judge, `gh` for a launch, or git for its room; its command, and what goes on its input."""

    command: list[str]
    payload: str
    """What goes on its standard input: a hook's payload, or a body for `gh`."""
    directory: Path | None = None
    """Where it runs; none for the service's own directory."""


class Judged(Model):
    """How a program the service ran ended: its status, what it printed, and what it said beside."""

    status: int
    output: str
    """What it printed: the hook's answer, where `status` is 0."""
    error: str
    """What it wrote to its standard error, or why it couldn't run."""


async def judged(asked: Asked) -> Judged:
    """Run the program to its end, `asked.payload` on its input; kill it where the wait is cancelled.

    Spawned rather than forked: `sh` forks from the service's process and runs
    Python in the child before the program starts, which can deadlock in a
    process with threads, and it would hold a thread per program for as long as
    it runs: a judge for a hold's hours, `gh` for GitHub's answer, git for a
    room's push (`remote/protocol.py`).
    """
    program, *arguments = asked.command
    try:
        # lup: ignore("subprocess", why="the host service awaits each judge, each gh and git for a room on its event loop, which sh can't: it forks, and holds a thread per program")
        process = await asyncio.create_subprocess_exec(
            program,
            *arguments,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=asked.directory,
        )
    except OSError as missing:
        return Judged(
            status=127, output="", error=f"`{program}` doesn't run: {missing}"
        )
    try:
        output, error = await process.communicate(asked.payload.encode())
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    return Judged(
        status=await process.wait(),
        output=output.decode(errors="replace"),
        error=error.decode(errors="replace"),
    )


class Handler[R: Request](ABC):
    """Answers one kind of control request; a module registers its own with the service."""

    @abstractmethod
    def request(self) -> type[R]:
        """Return the model of the requests this answers: its `kind` routes them here."""

    @abstractmethod
    async def answer(self, request: R) -> Reply:
        """Answer one request on the service's event loop, off it where it blocks.

        A `HostError` refuses the request with its message.
        """


class Route(Model, arbitrary_types_allowed=True):
    """A handler as the service dispatches to it: its kind, and its answer to the JSON."""

    kind: str
    answer: Callable[[str], Awaitable[Reply]]

    @classmethod
    def to[R: Request](cls, handler: Handler[R]) -> Route:
        """Route the requests of `handler`'s kind to it, each read as its model."""
        model = handler.request()

        async def answered(raw: str) -> Reply:
            return await handler.answer(model.model_validate_json(raw))

        return cls(kind=model.named(), answer=answered)


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
        """Answer one request, its line read, at once and again at each change where its reply differs, one JSON line each, until its sender closes the connection.

        A refusal is the last line. The sender keeps its side open while it
        watches, so its closing is heard, and the watch ends with it.
        """
        raw = (await reader.readline()).decode()
        gone = asyncio.ensure_future(reader.read())
        sent = ""
        try:
            while not gone.done():
                seen = self.changes.count
                reply = await self.answered(raw)
                line = reply.model_dump_json()
                if line != sent:
                    writer.write(f"{line}\n".encode())
                    await writer.drain()
                    sent = line
                if isinstance(reply, Refused):
                    return
                changed = asyncio.ensure_future(self.changes.after(seen))
                await asyncio.wait([changed, gone], return_when=asyncio.FIRST_COMPLETED)
                changed.cancel()
        except ConnectionError as left:
            self.say(f"a watch's sender left: {left}")
        finally:
            gone.cancel()
            writer.close()

    async def answered(self, raw: str) -> Reply:
        """Answer one request with the route its kind names.

        A request that doesn't parse, or of no kind routed, is refused, as is one
        its handler refuses or fails on; a failure is said with its traceback.
        """
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
        try:
            return await route.answer(raw)
        except (HostError, ValidationError) as failure:
            return self.refused(str(failure))
        except Exception as failure:
            told = "".join(traceback.format_exception(failure))
            self.say(f"the `{kind}` handler failed:\n{told}")
            return self.refused(f"the `{kind}` handler failed: {failure!r}")

    def refused(self, error: str) -> Refused:
        """Refuse a request, saying why."""
        self.say(f"refused a request: {error}")
        return Refused(error=error)


class ModuleTools(Model, RoomTools, arbitrary_types_allowed=True):
    """A launch's modules' tools, as its session is served them: each call passed to the launch's modules' process."""

    modules: LaunchModules
    offered: Offered

    @override
    def specs(self) -> list[ToolSpec]:
        return self.offered.tools

    @override
    async def call(
        self, name: str, arguments: JsonValue, launch: Register, caller: Conversation
    ) -> Answer:
        """Pass the call to the launch's modules, and return what their tool answered.

        Where they can't answer, the answer says why.
        """
        try:
            reply = await self.modules.ask(
                launch, Calling(name=name, arguments=arguments, caller=caller)
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
        reply = await modules.ask(launch, Relaying(request=sent))
        match reply:
            case Relayed(reply=passed):
                return Passed.model_validate(passed)
            case _:
                message = f"the module answering `{kind}` replied {reply.kind}"
                raise HostError(message)

    return Route(kind=kind, answer=answered)


class Noted(Model):
    """A hook's conversation as it stands once what the hook says of subagents is noted, and what it's told of names."""

    conversation: Conversation
    said: list[str] = []


def name_spawns(naming: str) -> str:
    """Tell a conversation spawning a subagent without a name to give names, `naming` saying how."""
    return (
        "lup: that subagent goes without a name, so you and the operator can't "
        f"call it by one: give each subagent you spawn a name after its task "
        f"({naming}). It's asked to name itself meanwhile."
    )


def unnamed(path: str) -> str:
    """Ask a subagent spawned without a name to name itself: it knows its task."""
    return (
        f"lup: this subagent is `{path}` for now, with no name of its own: name "
        "yourself after your task with lup's `rename` tool (`explore-auth`), so "
        "the operator and other sessions can tell you apart."
    )


def named_here(name: str) -> str:
    """Tell a session starting its launch's name."""
    return (
        f"lup: this session is `{name}`: how the operator, lup's commands and "
        "other sessions call it. Once you know your task, name it after it with "
        "lup's `rename` tool, unless the operator named it."
    )


class Spoken(Model):
    """What a hook prints, and what it tells the conversation from its inbox."""

    answer: str
    posted: Posted = Posted()


class Served(Model, arbitrary_types_allowed=True):
    """A launch the service serves: its conversations, and the servers on its sockets."""

    launch: Register
    conversations: Conversations
    servers: list[asyncio.Server]
    """Its hook socket's, its tool server's and its requests' socket's."""
    offered: Offered = Offered()
    """What the launch's modules serve, in its process."""


async def closed(server: asyncio.Server) -> None:
    """Close `server` and the connections it holds, its socket file removed."""
    server.close()
    server.close_clients()
    await server.wait_closed()


class Launches(MutableModel, arbitrary_types_allowed=True):
    """The launches the service serves, each on its own sockets."""

    layout: HostLayout
    answerer: Answerer
    courier: Courier
    post: Post | None
    judge: Callable[[Asked], Awaitable[Judged]]
    """Runs a launch's judge for one hook; a test gives a stub."""
    tools: list[RoomTools]
    room_routes: list[RoomRoute]
    modules: LaunchModules | None
    """Serves each launch's modules in a process of its own; none serves none."""
    line_limit: int
    """The longest line lup's tool server reads: one MCP message."""
    say: Callable[[str], None]
    names: Names
    """The name each session last had, so a session resumed takes it back."""
    spawns: Spawns | None = None
    """How each runtime recorded its subagents' spawns; none reads nothing, so
    subagents go without names until they rename themselves."""
    refresh: Callable[[Register], list[Path]] | None = None
    """Brings the programs a recorded launch's room runs up to this copy's,
    returning those it rewrote; none leaves them as the launch wrote them."""
    changes: Changes
    """Told once each hook is answered, and each room's request."""
    clock: Clock
    """When each conversation's activity began."""
    served: dict[str, Served] = {}
    pending: list[asyncio.Task[None]] = []
    """What the launches' modules' hooks are running that nothing waits on."""
    activities: dict[str, Activity] = {}
    """By lup's id for each conversation, what its latest hook said it's doing,
    in memory."""

    async def open(self, registering: Register) -> Register:
        """Serve a launch: its name, its directory, its sockets inside, its record; and return it as it stands, named.

        Its name is the one it asks, made unique among those served (`claimed`).
        A launch served already, running a runtime the answerer doesn't know,
        whose judge isn't there, or asking exactly a name another holds, is
        refused. A directory left by a service before
        is used as it is, since the launch's room mounted it. Either way it's the
        operator's alone (mode 0700): a runtime's own messaging socket, placed in
        it, refuses a directory anyone else could reach (its adapter says which).
        """
        if registering.launch in self.served:
            message = f"a launch with the id `{registering.launch}` is served already"
            raise HostError(message)
        others = [served.launch for served in self.served.values()]
        request = registering.model_copy(update={"name": claimed(registering, others)})
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

        offered = await self.offered(request)
        own = {room.kind: bound(room, request) for room in self.room_routes}
        modules = self.modules
        relaying = (
            {}
            if modules is None
            else {kind: relayed(modules, request, kind) for kind in offered.kinds}
        )
        requests = Dispatcher(
            routes={**relaying, **own},
            answering="a room's request socket",
            say=said,
            changes=self.changes,
        )

        async def hook(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await self.hook(request, conversations, reader, writer)

        async def tools(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await self.tools_served(request, conversations, reader, writer)

        async with AsyncExitStack() as opening:
            hooks = await asyncio.start_unix_server(hook, path=sockets.hook)
            opening.push_async_callback(closed, hooks)
            served = await asyncio.start_unix_server(
                tools, path=sockets.mcp, limit=self.line_limit
            )
            opening.push_async_callback(closed, served)
            asked = await asyncio.start_unix_server(
                requests.connection, path=sockets.request
            )
            opening.pop_all()
        self.served[request.launch] = Served(
            launch=request,
            conversations=conversations,
            servers=[hooks, served, asked],
            offered=offered,
        )
        self.layout.record(request.launch).write_text(request.model_dump_json(indent=2))
        if "launched" in offered.occasions:
            self.background(self.happened(request, Happening(occasion="launched")))
        self.say(
            f"{request.launch}: served as `{request.name}`, {request.runtime} in "
            f"{request.worktree}, judged by {request.judge}, its sockets in "
            f"{sockets.directory}"
        )
        return request

    def renamed(self, launch: str, name: str) -> Register:
        """Rename launch `launch`, its record and its session's kept name with it, and return it as it stands.

        Raise `HostError` where no launch is served by that id, or another holds
        the name, saying which.
        """
        served = self.served.get(launch)
        if served is None:
            message = f"no launch served is `{launch}`"
            raise HostError(message)
        others = [each.launch for each in self.served.values()]
        holder = held(name, others, launch)
        if holder is not None:
            raise HostError(taken(holder))
        before = served.launch.name
        named = served.launch.model_copy(update={"name": name})
        self.served[launch] = served.model_copy(update={"launch": named})
        self.layout.record(launch).write_text(named.model_dump_json(indent=2))
        session = served.conversations.session
        if session is not None:
            self.names.keep(session, name)
        self.say(f"{launch}: renamed from `{before}` to `{name}`")
        return named

    def started(self, launch: str, session: str, title: str | None) -> str:
        """Name launch `launch` as its session `session` starts, and return its name.

        A name the runtime gives the session (`title`, as the operator renamed it
        in the runtime) is taken in a name's shape (`shaped`) where it's free; otherwise
        the name `session` last had, where it's free, as a session resumed in a
        later launch; otherwise the launch keeps its own. The name is kept as
        `session`'s.
        """
        current = self.served[launch].launch
        others = [each.launch for each in self.served.values()]
        given = None if title is None else shaped(title)
        wanted = [
            each
            for each in [given, self.names.last(session)]
            if each is not None and held(each, others, launch) is None
        ]
        name = next(iter(wanted), current.name or "")
        if name != current.name:
            self.renamed(launch, name)
        self.names.keep(session, name)
        return name

    async def offered(self, request: Register) -> Offered:
        """Start serving the launch's modules, and return what they serve that the core doesn't.

        Where they can't be served, it's said and the launch goes on with the
        core's tools alone; a tool or a kind of request the core serves already is
        said and left to the core.
        """
        if self.modules is None:
            return Offered()
        try:
            offered = await self.modules.open(request)
        except HostError as failed:
            self.say(f"{request.launch}: its modules aren't served: {failed}")
            return Offered()
        names = [spec.name for tools in self.tools for spec in tools.specs()]
        kinds = [room.kind for room in self.room_routes]
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
            occasions=offered.occasions,
        )

    def background(self, running: Coroutine[None, None, None]) -> None:
        """Run a launch's modules' hooks without waiting on them, keeping the task until it's done."""
        task = asyncio.create_task(running)
        self.pending = [*(each for each in self.pending if not each.done()), task]

    async def happened(self, request: Register, happening: Happening) -> None:
        """Tell the launch's modules an occasion their hooks run at, and say what failed among them."""
        if self.modules is None:
            return
        try:
            reply = await self.modules.ask(request, happening)
        except HostError as failed:
            self.say(
                f"{request.launch}: its modules' hooks didn't run at "
                f"{happening.occasion}: {failed}"
            )
            return
        match reply:
            case Happened(failures=failures):
                for failure in failures:
                    self.say(f"{request.launch}: {failure}")
            case _:
                self.say(
                    f"{request.launch}: its modules replied {reply.kind} at "
                    f"{happening.occasion}"
                )

    async def hook(
        self,
        request: Register,
        conversations: Conversations,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Answer one hook heard on a launch's socket, and close the connection.

        The payload is read to the end and answered. Where answering fails even
        so, the failure is said, with its traceback, and the connection closes
        unanswered: the room's hook prints nothing and ends with status 0, which
        the runtime takes as no decision. Where the hook is gone before its
        answer is written, what it would have told is put back as waiting.
        """
        payload = (await reader.read()).decode()
        try:
            spoken = await self.answered(request, conversations, payload)
        except Exception as failure:
            told = "".join(traceback.format_exception(failure))
            self.say(f"{request.launch}: answering a hook failed:\n{told}")
            spoken = Spoken(answer="")
        self.changes.changed()
        try:
            writer.write(spoken.answer.encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except ConnectionError as gone:
            self.say(f"{request.launch}: the hook was gone before its answer: {gone}")
            self.returned(spoken.posted)
            return
        self.say(f"{request.launch}: answered a hook")

    def returned(self, posted: Posted) -> None:
        """Put back as waiting what an answer that didn't reach its hook would have told."""
        if self.post is not None and posted.numbers:
            self.post.returned(posted)

    async def answered(
        self, request: Register, conversations: Conversations, payload: str
    ) -> Spoken:
        """Return what one hook prints: the judge's answer where it reads the hook, none where it doesn't, with what the courier adds.

        The conversation the hook names gets lup's id here the first time, and
        is told what the post says waits for it, in what room the judge's answer
        leaves. A payload the courier can't read goes to the judge as it is,
        which answers it or says it couldn't; where the courier can't add to the
        judge's answer, the answer goes out as the judge gave it, and what it
        would have told is put back. Either is said.
        """
        try:
            heard = self.courier.heard(request.runtime, payload)
        except ValueError as unread:
            self.say(
                f"{request.launch}: a hook lup couldn't read goes to its judge as it "
                f"is: {unread}"
            )
            return Spoken(answer=await self.judgement(request, payload))
        conversation = conversations.named(heard.session, heard.agent)
        noted = self.spawning(request, conversations, conversation, heard, payload)
        conversation, said = noted.conversation, noted.said
        self.activities = {**self.activities, conversation.id: self.activity(heard)}
        if heard.event in self.served[request.launch].offered.occasions:
            happening = Happening(
                occasion=heard.event,
                conversation=conversation,
                call=heard.call,
                tool=heard.tool,
            )
            self.background(self.happened(request, happening))
        answer = await self.judgement(request, payload) if heard.judged else ""
        starting = heard.event == "session-started" and heard.agent is None
        name = (
            self.started(request.launch, heard.session, heard.title)
            if starting
            else None
        )
        naming = [*([] if name is None else [named_here(name)]), *said]
        room = (
            heard.fits
            - len(answer.encode())
            - sum(len(each.encode()) for each in naming)
        )
        posted = (
            Posted()
            if self.post is None
            else await self.post.telling(request, conversation, heard, room)
        )
        telling = Telling(
            caller=conversation.id, items=[*naming, *posted.items], title=name
        )
        try:
            told = self.courier.told(request.runtime, payload, answer, telling)
        except ValueError as unread:
            self.say(
                f"{request.launch}: the judge's answer goes out as it gave it, since "
                f"lup couldn't add to it: {unread}"
            )
            self.returned(posted)
            return Spoken(answer=answer)
        return Spoken(answer=told, posted=posted)

    async def judgement(self, request: Register, payload: str) -> str:
        """Return the judge's answer to one hook, or where it can't answer, the runtime's word that it couldn't.

        What the judge said is the service's to tell, in full; the hook's answer
        points there. It waits for as long as judging does, a hold's wait for the
        operator included.
        """
        asked = Asked(
            command=[str(request.judge), "hook", request.runtime], payload=payload
        )
        ran = await self.judge(asked)
        if ran.status == 0:
            return ran.output
        command = shlex.join(asked.command)
        self.say(
            f"{request.launch}: `{command}` couldn't answer a hook (status "
            f"{ran.status}). What it said:\n{ran.error}"
        )
        failure = (
            f"`{command}` ended with status {ran.status}; what it said is in the "
            f"host service's output, {self.layout.log} when it runs in the "
            "background"
        )
        return self.answerer.unanswered(request.runtime, payload, failure)

    async def tools_served(
        self,
        request: Register,
        conversations: Conversations,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Serve lup's tools over one connection on a launch's `mcp.sock`, until it closes.

        Where serving breaks (a line past the limit, a connection reset), it's
        said with its traceback, and the connection closes.
        """
        offered = self.served[request.launch].offered
        modules = (
            []
            if self.modules is None
            else [ModuleTools(modules=self.modules, offered=offered)]
        )
        toolset = LaunchTools(
            launch=request,
            tools=[*self.tools, Naming(launches=self), *modules],
            conversations=conversations,
            say=self.say,
        )
        try:
            await serve(toolset, reader, writer, name=SERVER)
        except Exception as failure:
            told = "".join(traceback.format_exception(failure))
            self.say(f"{request.launch}: serving lup's tools failed:\n{told}")
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError as gone:
            self.say(
                f"{request.launch}: lup's tool server was gone before it closed: {gone}"
            )

    async def close(self, launch: str) -> None:
        """End a launch: its sockets closed, its record and directory removed.

        The directory goes with whatever the room left in it.
        """
        served = self.served.pop(launch, None)
        if served is None:
            message = f"no launch named `{launch}` is served"
            raise HostError(message)
        for server in served.servers:
            await closed(server)
        if "stopped" in served.offered.occasions:
            await self.happened(served.launch, Happening(occasion="stopped"))
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
        """Note what a hook says of subagents, and return the conversation as it stands, with what it's told of names.

        A subagent heard the first time is linked to its spawn as its runtime
        recorded it (`Spawns`, `Conversations.linked`): its parent, its kind,
        and the name its parent gave; one with no name is asked to name itself,
        beside a call, never as the reason its turn's end is held.
        A conversation spawning one without a name, where it could have given
        one, is told once to give names. Its launch's conversations are kept, so
        a service started again knows them.
        """
        said: list[str] = []
        if heard.agent is not None and not conversation.linked:
            spawned = (
                None
                if self.spawns is None
                else self.spawns.spawned(request.runtime, payload)
            )
            conversation = conversations.linked(conversation, spawned)
            calling = heard.event in ["call-started", "call-finished"]
            if conversation.name is None and calling:
                said.append(
                    unnamed(conversations.path(conversation, self.named(request)))
                )
        spawning = heard.spawning
        if spawning is not None and spawning.name is None and not conversation.nudged:
            conversation = conversations.kept(
                conversation.model_copy(update={"nudged": True})
            )
            said.append(name_spawns(spawning.naming))
        write_model(self.layout.conversations(request.launch), conversations)
        return Noted(conversation=conversation, said=said)

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

    def talkers(self, served: Served) -> list[Talker]:
        """Return a launch's conversations as the operator is shown them: its latest session's own, then each of its subagents under its parent, in the order heard; none before any hook named one."""
        conversations = served.conversations
        launch = self.named(served.launch)

        def talker(each: Conversation, depth: int) -> Talker:
            parent = None if each.parent is None else conversations.calling(each.parent)
            return Talker(
                path=conversations.path(each, launch),
                own=conversations.own(each, launch),
                session=each.session,
                agent=each.agent,
                kind=each.kind,
                parent=None if parent is None else conversations.path(parent, launch),
                depth=depth,
                activity=self.activities.get(each.id),
            )

        def under(parent: str, depth: int) -> list[Talker]:
            children = [
                each
                for each in conversations.known
                if each.parent == parent and each.agent is not None
            ]
            return [
                found
                for each in children
                for found in [talker(each, depth), *under(each.id, depth + 1)]
            ]

        main = conversations.main()
        return [] if main is None else [talker(main, 0), *under(main.id, 1)]

    def activity(self, heard: Heard) -> Activity:
        """Return what a hook says its conversation is doing, from the hook on: running the call it starts, between calls, or ended."""
        at = self.clock.now()
        match heard.event:
            case "call-started":
                return Activity(
                    state="calling", since=at, tool=heard.tool, lups=heard.served
                )
            case "conversation-ended":
                return Activity(state="ended", since=at)
            case _:
                return Activity(state="idle", since=at)

    def named(self, request: Register) -> str:
        """Return launch `request`'s name as it stands."""
        served = self.served.get(request.launch)
        current = request if served is None else served.launch
        return current.name or current.launch

    async def reopen(self) -> None:
        """Serve each launch recorded by a service before, where its room mounted it, its room's programs brought up to this copy's (`refresh`).

        A record that doesn't read as a launch's, or that this service can't serve,
        is said and left in place.
        """
        for record in sorted(self.layout.launches.glob("*.json")):
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
        """Close every launch's sockets and stop its modules, keeping its record and its directory."""
        for served in self.served.values():
            for server in served.servers:
                await closed(server)
            if self.modules is not None:
                await self.modules.close(served.launch)
        self.served = {}


class NewName(Model):
    """The name a session takes."""

    name: str = Field(
        description=(
            "This session's name from now on: letters, digits, `-`, `_` and `.`, "
            "after its task, such as `gate-on-push`."
        )
    )


class Namer(Model, arbitrary_types_allowed=True):
    """One conversation of a launch's session, renaming itself: the session's own, or a subagent."""

    launches: Launches
    launch: str
    caller: str
    """lup's id for the conversation calling."""

    async def rename(self, new: NewName) -> str:
        """Name this session or subagent after its task.

        Its name is how the operator, lup's commands and other sessions call
        it, and what the operator's inbox says items come from. Call it once
        you know your task, unless the operator or your parent named you; call
        it again when the task changes. From a subagent it names that subagent
        alone, never its session. A name another holds is refused, saying
        whose; pick another.
        """
        try:
            wanted = handle(new.name)
            served = self.launches.served[self.launch]
            caller = served.conversations.calling(self.caller)
            if caller is not None and caller.agent is not None:
                path = self.launches.subagent_renamed(self.launch, caller, wanted)
                return (
                    f"This subagent is `{path}` to lup and the operator. The name "
                    "your runtime gave you at your spawn, which your parent's own "
                    "tools use, stays as it was."
                )
            named = self.launches.renamed(self.launch, wanted)
        except (HostError, ValueError) as refused:
            return f"Not renamed: {refused}"
        return f"This session is `{named.name}`."

    def tools(self) -> list[AgentTool]:
        """Return the naming tool, bound to this launch."""
        return [lup_tool(self.rename)]


class Naming(Model, RoomTools, arbitrary_types_allowed=True):
    """The tool a session renames itself with, which the service serves beside the inbox's."""

    launches: Launches

    @override
    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in Namer.model_construct().tools()]

    @override
    async def call(
        self, name: str, arguments: JsonValue, launch: Register, caller: Conversation
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
        )


class Renaming(Model, Handler[Rename]):
    """Answers `Rename`: the launch renamed, as it stands replied."""

    launches: Launches

    @override
    def request(self) -> type[Rename]:
        return Rename

    @override
    async def answer(self, request: Rename) -> Reply:
        return Renamed(launch=self.launches.renamed(request.launch, request.name))


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


class Listing(Model, Handler[ListLaunches]):
    """Answers `ListLaunches`: each launch served, as it was registered."""

    launches: Launches

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
    """A program the service runs beside it: begun once the service listens, ended as it stops."""

    @abstractmethod
    async def begin(self) -> None:
        """Start the program; raise `HostError` where it can't, saying why, and the service goes on without it."""

    @abstractmethod
    async def end(self) -> None:
        """Stop the program, where it runs."""


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
    judge: Callable[[Asked], Awaitable[Judged]] = judged
    """Runs a launch's judge for one hook, as a process of its own; a test gives a stub."""
    routes: list[Route] = []
    """The handlers modules register on the control socket, beside the service's own."""
    room_routes: list[RoomRoute] = []
    """The handlers modules register for the room's requests, on each launch's
    `request.sock`."""
    tools: list[RoomTools] = []
    """The core's tools, served each launched session on its `mcp.sock`."""
    modules: LaunchModules | None = None
    """Serves each launch's modules, their tools and their answers to the room's
    requests, in a process of its own; none serves the core's alone."""
    line_limit: int = 16 * 1024 * 1024
    """The longest line lup's tool server reads, one MCP message: well above
    asyncio's 64 KiB, which a long message to the operator could pass."""
    spawns: Spawns | None = None
    """How each runtime recorded its subagents' spawns, read once at a
    subagent's first hook (`cli.py`'s adapters); none reads nothing."""
    refresh: Callable[[Register], list[Path]] | None = None
    """Brings the programs a recorded launch's room runs up to this copy's when
    the service serves it again, returning those it rewrote: git's remote
    helper and lup's MCP bridge (`cli.py`), so a restart on an approved copy
    reaches running rooms. None leaves them as the launch wrote them."""
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
            say=self.say,
            names=Names(path=self.layout.names),
            spawns=self.spawns,
            refresh=self.refresh,
            changes=self.changes,
            clock=self.clock,
        )
        stopped = asyncio.Event()
        own = [
            Route.to(Registering(launches=launches)),
            Route.to(Ending(launches=launches)),
            Route.to(Listing(launches=launches)),
            Route.to(Renaming(launches=launches)),
            Route.to(Stopping(stopped=stopped)),
        ]
        control = Dispatcher(
            routes={route.kind: route for route in [*own, *self.routes]},
            answering="the service",
            say=self.say,
            changes=self.changes,
        )
        try:
            await launches.reopen()
            server = await asyncio.start_unix_server(
                control.connection, path=self.layout.control
            )
            watches = await asyncio.start_unix_server(
                control.watching, path=self.layout.watch, limit=self.line_limit
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
