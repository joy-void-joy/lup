"""`Held`: the machine's part holding every session lup starts, from its start to its end, and `Sessions`, the module of the parts a session needs on the machine.

A session is kept for good once started: its project, its runtime, the id each
gives it, its worktree, its name. While it runs, a holder of its own holds its
runtime over its room's socket (`lup.sessions.held`), and its room runs its
runtime (`Rooms`). Every hook of its runtime reaches the machine through the
room's socket (`hooked`): read with the session's runtime as lup's event, what
waits for the agent told beside it, a call to lup's own tools by a subagent
stamped with the conversation making it.

Between hooks, a sweep looks at each session (`swept`): an idle one with
something told for it is woken with a turn; one idle past its profile's idle
time is ended, its room stopped; and one not running with something for it is
started again, its whole conversation resumed, so a reply always reaches it
(`README.md` here).
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import TypeAdapter, ValidationError

import lup
from lup.command_line.filled import Repository
from lup.doors.done import Done
from lup.doors.door import RefusedError
from lup.doors.events import Heeded, Starting
from lup.doors.parties import Agent, Machine, Operator
from lup.doors.parts import Data, Part, Runtime
from lup.hosting.carrying import Carrying, Hearing, Leaving, Naming, SessionRoom
from lup.hosting.containers import Named
from lup.hosting.projects import Locating, Projects, Telling
from lup.inbox.part import Inboxes
from lup.inbox.said import Ended, Ending, ToldItem, Untelling
from lup.inbox.said import Naming as Named2
from lup.rooms.layout import Kept
from lup.rooms.part import RoomFor, Rooms, WorktreeFor
from lup.running.plan import Name
from lup.runtimes.known import named
from lup.runtimes.runtime import Answer, Begin, Spoken, Stamp
from lup.sessions.events import (
    CallFinished,
    CallStarting,
    ConversationEnded,
    Happened,
    SessionEnded,
    SessionStarted,
    TurnEnded,
    TurnStarted,
)
from lup.sessions.held import Holds, Order, Standing
from lup.sessions.promises import SessionsPromises
from lup.sessions.said import Hooked
from lup.types import Model


class Stretch(Model):
    """One stretch of a session, from its runtime's start to its end: when it began, how, where, in which room, on which account."""

    began: datetime
    """When it began, an aware time."""
    begun: Literal["start", "resume", "fork"]
    worktree: Path
    container: str
    account: str


class Session(Model):
    """A session lup started, kept for good: its project, its runtime and the ids each gives it, where it works, what it's called, and each stretch it ran."""

    session: str
    """lup's id for the session, its own agent's."""
    repository: str
    common: Path
    """The project's common git directory on the machine."""
    runtime: str
    known_as: str | None = None
    """The runtime's own id for the session, once it's said."""
    worktree: Path
    name: str
    account: str = "default"
    model: str | None = None
    effort: str | None = None
    ended: bool = False
    """Whether it was ended, by the operator or by its own `stop`: a reply
    still starts it again."""
    stretches: list[Stretch] = []
    """Each stretch it ran, in order."""


class Known(Model):
    """Every session lup started, on every project."""

    sessions: list[Session] = []


class Nothing(Model):
    """Nothing: what reading every session takes."""


class Run(Model):
    """A session running: its room, its holder's control socket, and when it was last heard from or told something."""

    container: str
    sockets: Path
    control: Path
    busy: bool = False
    heard: float
    """When it was last heard from or told something, on the event loop's
    clock, which measures how long it's been idle."""


SESSIONS = TypeAdapter(dict[str, Session])


class NewSession(Model):
    """A session to start: in which project, on which runtime, called what, where, and the first words it's told."""

    repository: Repository
    """The project, as lup names it: one running (`lup machine open`)."""
    runtime: str = "claude"
    """The runtime, by lup's name for it: `claude` or `codex`."""
    name: Name | None = None
    """What it's called, and its branch and worktree where it gets new ones;
    left out, a name of its own."""
    worktree: Path | None = None
    """An existing worktree of the project to work in, that no running session
    holds; left out, a new one, on a new branch, from `start`."""
    start: Name = "dev"
    """The branch a new worktree starts from."""
    model: str | None = None
    effort: str | None = None
    said: str = ""
    """The first words it's told, its first turn; nothing to start it idle."""


class Called(Model):
    """A session, by its name."""

    name: str


class SessionBegun(Done):
    """A session started, in a room of its own, held by lup."""

    line: ClassVar[str] = "started {name}, a {runtime} session in {worktree}"
    name: str
    runtime: str
    worktree: Path


class TurnInterrupted(Done):
    """A session's turn under way, interrupted."""

    line: ClassVar[str] = "interrupted {name}'s turn"
    name: str


class SessionFinished(Done):
    """A session ended: a reply starts it again."""

    line: ClassVar[str] = "ended {name}"
    name: str


def said(item: ToldItem) -> str:
    r"""Return an item told to an agent, as a tag saying whose it is.

    >>> said(ToldItem(number=12, by="operator", kind="message", text="Go on."))
    '<item item="12" from="operator" kind="message">\nGo on.\n</item>'
    """
    return (
        f'<item item="{item.number}" from="{item.by or "lup"}" kind="{item.kind}">\n'
        f"{item.text}\n</item>"
    )


class Held(Part, machine=True, shared=True):
    """The machine's part holding every session lup starts: starting each, telling it what's for it, waking it, interrupting it, ending it, and starting it again."""

    module: Sessions
    holder: lup.Program = lup.Program(
        name=sys.executable,
        optional=True,
        why="runs each session's holder, the machine's own code, with the machine's own Python",
    )
    """The machine's own Python, which runs each session's holder
    (`lup.environment.sessions.holder`), so a holder is always the code of the
    machine that starts it."""
    running_holder: list[str] = ["-I", "-m", "lup.environment.sessions.holder"]
    """The holder's arguments to the machine's Python, before its own."""
    registry: Data
    """Every session started, kept for good."""
    controls: Runtime
    """Each running session's holder's control socket, and its log."""
    running: dict[str, Run] = {}
    """Each session running, by lup's id for it."""
    sweeping: timedelta = timedelta(seconds=2)
    """How often the sweep looks at each session."""
    connecting: timedelta = timedelta(minutes=1)
    """How long a session's room has to connect its runtime to its holder."""

    def kept(self) -> dict[str, Session]:
        """Return every session started, by lup's id for it."""
        place = self.registry.path / "sessions.json"
        if not place.is_file():
            return {}
        return SESSIONS.validate_json(place.read_bytes())

    def keep(self, session: Session) -> None:
        """Keep `session`, in place of what was kept of it."""
        kept = {**self.kept(), session.session: session}
        (self.registry.path / "sessions.json").write_bytes(SESSIONS.dump_json(kept))

    def called(self, name: str) -> Session:
        """Return the session called `name`, or whose id it is.

        Raise `RefusedError` where none is.
        """
        found = [
            each for each in self.kept().values() if name in [each.name, each.session]
        ]
        if not found:
            message = f"no session lup started is called `{name}`"
            raise RefusedError(message)
        return found[-1]

    @lup.command
    async def start(self, starting: NewSession, by: Operator) -> SessionBegun:
        """Start a session in a room of its own, held by lup.

        It says what the session's called. Refused where the project isn't running, the runtime isn't one lup
        holds, the limit on sessions running is reached, or its room doesn't
        start.
        """
        del by
        named(starting.runtime)
        located = await Projects.located(Locating(repository=starting.repository))
        self.limited(starting.repository)
        session = str(uuid.uuid4())
        name = starting.name or f"{starting.runtime}-{uuid.UUID(session).time_low:08x}"
        worktree = (
            starting.worktree
            or (
                await Rooms.worktree(
                    WorktreeFor(
                        repository=starting.repository,
                        common=located.opening.common,
                        name=name,
                        start=starting.start,
                        packages=located.opened.plan.packages,
                    )
                )
            ).path
        )
        kept = Session(
            session=session,
            repository=starting.repository,
            common=located.opening.common,
            runtime=starting.runtime,
            worktree=worktree,
            name=name,
            model=starting.model,
            effort=starting.effort,
        )
        self.keep(kept)
        await self.opened(kept, Begin(begun="start", session=session))
        await Inboxes.agent_named(
            Named2(repository=kept.repository, agent=Agent.of(session), name=kept.name)
        )
        if starting.said:
            await self.ordered(session, Order(order="turn", text=starting.said))
        return SessionBegun(name=name, runtime=starting.runtime, worktree=worktree)

    def limited(self, repository: str) -> None:
        """Refuse a session past the limits on sessions running: on the machine, and of one repository."""
        running = [self.kept()[each] for each in self.running if each in self.kept()]
        if len(running) >= self.module.most:
            message = f"{len(running)} sessions run already, the most lup runs at once"
            raise RefusedError(message)
        own = [each for each in running if each.repository == repository]
        if len(own) >= self.module.most_per_repository:
            message = f"{len(own)} sessions of {repository} run already, the most lup runs of one"
            raise RefusedError(message)

    async def opened(self, session: Session, begin: Begin) -> Run:
        """Start a session's holder, then its room, which connects its runtime to the holder, and keep it running.

        Raise `RefusedError` where either doesn't start.
        """
        agent = Agent.of(session.session)
        guidance = await Projects.guided(
            Telling(repository=session.repository, agent=agent)
        )
        container = f"lup-{session.repository}-{session.session}"
        sockets = (await Carrying.directory(Naming(container=container))).path
        control = self.controls.path / f"{session.session}.sock"
        holds = Holds(
            session=session.session,
            runtime=session.runtime,
            begin=begin,
            worktree=session.worktree,
            room=sockets / "session.sock",
            control=control,
        )
        log = self.controls.path / f"{session.session}.log"
        started = await self.holder.ran(
            *self.running_holder,
            "start",
            "--log",
            str(log),
            given=holds.model_dump_json(),
        )
        if started.status != 0:
            message = f"{session.name}'s holder didn't start: {started.said()}"
            raise RefusedError(message)
        await Carrying.seated(
            SessionRoom(
                repository=session.repository,
                session=session.session,
                container=container,
                directory=sockets,
            )
        )
        located = await Projects.located(Locating(repository=session.repository))
        await Rooms.readied(
            RoomFor(
                repository=session.repository,
                common=session.common,
                session=session.session,
                runtime=session.runtime,
                begin=begin.model_copy(
                    update={"model": session.model, "effort": session.effort}
                ),
                worktree=session.worktree,
                guidance=guidance.text(),
                account=session.account,
                packages=located.opened.plan.packages,
                declaration=located.opening.declaration,
                serving=[each.named() for each in located.opened.plan.rooms()],
                kept=Kept(data=self.module.kept)
                if self.module.kept is not None
                else Kept(),
            )
        )
        run = Run(
            container=container,
            sockets=sockets,
            control=control,
            heard=asyncio.get_running_loop().time(),
        )
        self.running = {**self.running, session.session: run}
        stretch = Stretch(
            began=datetime.now(UTC),
            begun=begin.begun,
            worktree=session.worktree,
            container=container,
            account=session.account,
        )
        now = self.kept().get(session.session, session)
        self.keep(now.model_copy(update={"stretches": [*now.stretches, stretch]}))
        return run

    @lup.service
    async def known(self, nothing: Nothing, by: Machine) -> Known:
        """List every session lup started, on every project, each with the stretches it ran: where each ran and when, which a session's records don't say."""
        del nothing, by
        return Known(sessions=list(self.kept().values()))

    async def ordered(self, session: str, order: Order) -> Standing:
        """Tell the holder of the session lup knows as `session` `order`, and return where it stands after.

        Raise `RefusedError` where it isn't running, or its holder doesn't answer.
        """
        run = self.running.get(session)
        if run is None:
            message = "the session isn't running"
            raise RefusedError(message)
        answered = await self.holder.ran(
            *self.running_holder,
            "order",
            str(run.control),
            given=order.model_dump_json(),
        )
        if answered.status != 0:
            message = f"the session's holder didn't answer: {answered.said()}"
            raise RefusedError(message)
        try:
            return Standing.model_validate_json(answered.output)
        except ValidationError as wrong:
            message = f"the session's holder answered what lup doesn't read: {wrong}"
            raise RefusedError(message) from wrong

    @lup.command
    async def interrupt(self, called: Called, by: Operator) -> TurnInterrupted:
        """Interrupt the turn a session has under way.

        Its foreground command ends, and what waits for it is told at its next
        turn.
        """
        del by
        session = self.called(called.name)
        await self.ordered(session.session, Order(order="interrupt"))
        return TurnInterrupted(name=session.name)

    @lup.command
    async def end(self, called: Called, by: Operator) -> SessionFinished:
        """End a session once its turn under way finishes.

        Its runtime and room end then; a reply starts it again.
        """
        del by
        session = self.called(called.name)
        self.keep(session.model_copy(update={"ended": True}))
        if session.session in self.running:
            await self.ended(session)
        await Inboxes.agent_ended(
            Ending(repository=session.repository, agent=Agent.of(session.session))
        )
        return SessionFinished(name=session.name)

    async def ended(self, session: Session) -> None:
        """End a running session: its holder told to end, which closes its runtime's input, its room stopped, and calls from it refused from then on."""
        run = self.running.get(session.session)
        if run is None:
            return
        try:
            await self.ordered(session.session, Order(order="end"))
        except RefusedError:
            pass
        await Rooms.closed(Named(name=run.container))
        await Carrying.left(Leaving(session=session.session))
        self.running = {
            each: kept for each, kept in self.running.items() if each != session.session
        }

    @lup.service
    async def hooked(self, given: Hooked, by: Agent) -> Spoken:
        """Answer one of a session's hooks, as its runtime ran it in the room: read as lup's event, the agent told what waits for them, a subagent's call to lup's own tools stamped with their conversation.

        Raise `RefusedError` where the session isn't one lup started, or its
        runtime doesn't read the payload as one of the hook's.
        """
        session = self.kept().get(by.session)
        if session is None:
            message = "the room's session isn't one lup started"
            raise RefusedError(message)
        runtime = named(session.runtime)
        payload = given.payload.encode()
        try:
            heard = runtime.hooks.heard(given.hook, payload, by.session)
        except (ValueError, ValidationError) as wrong:
            message = f"`{given.hook}` isn't read as one of {session.runtime}'s hooks: {wrong}"
            raise RefusedError(message) from wrong
        self.heard(session, heard.event)
        await self.kept_words(session, heard.event)
        stamp = (
            Stamp(conversation=heard.conversation)
            if heard.ours and heard.conversation is not None
            else None
        )
        match heard.event:
            case TurnStarted() | CallStarting() | CallFinished() | SessionStarted():
                waiting = await self.telling(session, heard.event.agent)
            case _:
                waiting = ""
        heeded = (
            Heeded()
            if heard.event is None
            else await Carrying.heard(
                Hearing(
                    repository=session.repository,
                    session=session.session,
                    event=type(heard.event).__name__,
                    given=heard.event.model_dump(mode="json"),
                )
            )
        )
        told = "\n\n".join(each for each in [*heeded.told, waiting] if each)
        answer = Answer(stamp=stamp, told=told, refused=heeded.refused)
        return runtime.hooks.answered(given.hook, payload, answer)

    async def kept_words(self, session: Session, event: Happened | None) -> None:
        """Keep a conversation's last words of a turn in the inbox, answering what the operator told them since their last."""
        match event:
            case (
                TurnEnded(agent=agent, said=said)
                | ConversationEnded(agent=agent, said=said)
            ) if said:
                await Inboxes.turn_ended(
                    Ended(repository=session.repository, agent=agent, text=said)
                )
            case _:
                pass

    async def telling(self, session: Session, agent: Agent) -> str:
        """Return what waits for `agent`, told them once: each item whole, or, where they're more than a hook tells at once, each named, for `inbox` to read whole."""
        told = await Inboxes.told(Ending(repository=session.repository, agent=agent))
        whole = "\n\n".join(said(each) for each in told.items)
        if len(whole) <= self.module.telling:
            return whole
        return "\n".join(
            f'<item item="{each.number}" from="{each.by or "lup"}" kind="{each.kind}">'
            f"{len(each.text)} characters, read whole with `inbox` and number {each.number}</item>"
            for each in told.items
        )

    def heard(self, session: Session, event: Happened | None) -> None:
        """Keep what a session's event says of it: the runtime's id at its start, and whether its own conversation has a turn under way."""
        run = self.running.get(session.session)
        own = Agent.of(session.session)
        match event:
            case SessionStarted(known_as=known_as) if known_as != session.known_as:
                self.keep(session.model_copy(update={"known_as": known_as}))
            case TurnStarted(agent=agent) if run is not None and agent == own:
                run = run.model_copy(update={"busy": True})
            case TurnEnded(agent=agent) if run is not None and agent == own:
                run = run.model_copy(update={"busy": False})
            case SessionEnded():
                run = None
            case _:
                pass
        if run is not None and session.session in self.running:
            stamped = run.model_copy(
                update={"heard": asyncio.get_running_loop().time()}
            )
            self.running = {**self.running, session.session: stamped}

    @lup.on(Starting)
    async def swept(self, starting: Starting) -> None:
        """Look at each session every `sweeping`, as long as the part runs: one whose holder is gone is taken for stopped, one idle with something told for it is woken, one idle past its idle time is ended, and one not running with something for it is started again."""
        del starting
        while True:
            await asyncio.sleep(self.sweeping.total_seconds())
            await self.sweep()

    async def sweep(self) -> None:
        """Look at each session once, as the sweep does."""
        kept = self.kept()
        for session, run in list(self.running.items()):
            each = kept.get(session)
            if each is None:
                continue
            try:
                standing = await self.ordered(session, Order(order="standing"))
            except RefusedError:
                await self.gone(each)
                continue
            idle = timedelta(seconds=asyncio.get_running_loop().time() - run.heard)
            if not standing.busy and standing.up and idle > self.module.idle:
                await self.ended(each)
        repositories = list(dict.fromkeys(each.repository for each in kept.values()))
        for repository in repositories:
            untold = await Inboxes.untold(Untelling(repository=repository))
            for agent in untold.agents:
                each = kept.get(agent.session)
                if each is None or agent != Agent.of(each.session):
                    continue
                await self.woken(each)

    async def woken(self, session: Session) -> None:
        """Start a turn of a session's own conversation on what waits for it: where it runs idle, at once; where it isn't running, once it's started again, its conversation resumed."""
        run = self.running.get(session.session)
        if run is not None and run.busy:
            return
        if run is None:
            if session.known_as is None:
                return
            try:
                self.limited(session.repository)
                await self.opened(
                    session,
                    Begin(
                        begun="resume",
                        session=session.session,
                        known_as=session.known_as,
                    ),
                )
            except RefusedError:
                return
            await Inboxes.agent_started(
                Ending(repository=session.repository, agent=Agent.of(session.session))
            )
        told = await Inboxes.told(
            Ending(repository=session.repository, agent=Agent.of(session.session))
        )
        if not told.items:
            return
        text = "\n\n".join(said(each) for each in told.items)
        await self.ordered(
            session.session,
            Order(order="turn", text=f'<channel source="lup">\n{text}\n</channel>'),
        )
        woke = self.running.get(session.session)
        if woke is not None:
            stamped = woke.model_copy(
                update={"busy": True, "heard": asyncio.get_running_loop().time()}
            )
            self.running = {**self.running, session.session: stamped}

    async def gone(self, session: Session) -> None:
        """Take a session whose holder is gone for stopped: its room stopped, where it still runs, and calls from it refused from then on."""
        run = self.running.get(session.session)
        if run is None:
            return
        await Rooms.closed(Named(name=run.container))
        await Carrying.left(Leaving(session=session.session))
        self.running = {
            each: kept for each, kept in self.running.items() if each != session.session
        }


class Sessions(lup.Module):
    """Sessions lup starts and holds, each in a room of its own.

    On Claude Code or Codex: the machine's parts holding them and making their
    rooms.
    """

    name = "sessions"
    parts: lup.Parts = lup.Parts.of(Held, Rooms, SessionsPromises)
    idle: timedelta = timedelta(hours=1)
    """How long a session may stay idle before its process and room are
    stopped: about as long as the runtime's prompt cache lasts, so starting it
    again costs little."""
    most: int = 32
    """The most sessions running at once on the machine, against a loop of
    spawns rather than as a budget."""
    most_per_repository: int = 16
    """The most sessions of one repository running at once."""
    kept: Path | None = None
    """Where rooms keep what they share across sessions, each project's
    history and each account's logins: lup's data (`~/.local/share/lup`),
    shared with the second lup, where none is set."""
    telling: int = 9_000
    """The most characters of items a hook tells an agent whole: past it, each
    is named for `inbox` to read whole. Claude Code takes 10,000 characters of
    a hook's context, and Codex writes what's past about 10,000 bytes to a
    file."""
