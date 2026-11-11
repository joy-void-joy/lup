"""A launch's last step with no terminal: its session held by its launcher, over its room's input and output (`docs/launch.md`, *A session held with no terminal*).

`launched` (`cli.py`) does a held launch's whole setup as a terminal's, then
hands its room to a `Holder` rather than opening it in a terminal. The holder:
- starts the room piped (`Room.hold`), its runtime held over its input and
  output by the adapter's session (`lup_dev.adapters.Holding`);
- serves the socket beside the launch's lock (`LaunchLayout.held`), which no
  room mounts, for the host service's requests (`lup_dev.host.holders`): the
  operator's words as the next turn, an interrupt, the session's end;
- calls the session up to the host (`CalledUp`) once the host heard its first
  hook, and otherwise ends it, saying why: a runtime running no hook would run
  without lup's judge;
- ends the session once its runtime exits, the host asks, or the launcher is
  asked to end (`SIGTERM`), its input closed first, so a turn under way
  finishes, then its room stopped.

**One writer.** A runtime may not refuse a second process writing the same
session: one let a terminal resume a session a held process was running, and
its one record branched (`docs/field-notes.md`, *A session held with no
terminal*). So each launch writing a session its launcher knows the id of
holds a lock on it for the room's life (`Writing`, `Layout.writer`), a held
launch always, since it names its session up front, and a terminal resuming one
by its id; the lock's launch is kept beside it, so a terminal finding a held
launch on it can end that launch and take the session over.
"""

import asyncio
import signal
import threading
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

from filelock import FileLock, Timeout

from lup.errors import LupError
from lup.rooms.engine import ContainerError, Pipes, Podman, ended
from lup.sessions.held import HeldSession
from lup.types import Model, MutableModel
from lup_dev.host.client import HostClient
from lup_dev.host.held import CalledUp
from lup_dev.host.holders import HeldEnd, HeldInterrupt, HeldPrompt
from lup_dev.host.protocol import Done, HostError, Reply, segment
from lup_dev.host.service import Dispatcher, Handler, Route, unix_server
from lup_dev.host.watch import Changes
from lup_dev.launch.session import LaunchError
from lup_dev.layout import HostPaths, LaunchSockets, Layout, RoomPaths

if TYPE_CHECKING:
    from lup.rooms.engine import Piped
    from lup.rooms.room import Room
    from lup.sessions.terminal import TerminalSettings


def untraceable(paths: HostPaths) -> str | None:
    """Say why a held session can't be kept from a process of its room, where it can't: where Yama lets any process of a user trace any other, one in the room could write the session's turns through the runtime's own memory, whatever its input is; none where Yama keeps a process to its own descendants, or stricter.

    Its kernel is the room's, so the host's setting is the room's.
    """
    try:
        scope = paths.ptrace_scope.read_text().strip()
    except OSError:
        scope = None
    if scope not in [None, "0"]:
        return None
    said = (
        f"isn't there ({paths.ptrace_scope})"
        if scope is None
        else f"is 0 ({paths.ptrace_scope})"
    )
    return (
        f"Yama's `ptrace_scope` {said}, so any process of a room may trace any "
        "other of its user, the held session's runtime among them, and write its "
        "turns as the operator's: a held session needs it at 1 or more "
        "(`sysctl kernel.yama.ptrace_scope=1`, which most distributions set)"
    )


class Writing(Model, arbitrary_types_allowed=True):
    """The lock on one session's writer, which the one launch writing it holds while its room runs, its launch kept beside it."""

    path: Path
    """The lock (`Layout.writer`)."""

    @classmethod
    def of(cls, layout: Layout, runtime: str, session: str) -> Writing:
        """Return the lock on `runtime`'s session `session`, refusing an id that can't name a file."""
        try:
            named = segment(session)
        except ValueError as unnamed:
            message = f"`{session}` can't be a session's id: {unnamed}"
            raise LaunchError(message) from unnamed
        return cls(path=layout.writer(runtime, named))

    @property
    def holder(self) -> Path:
        """Where the launch holding the lock is kept, by its id."""
        return self.path.with_suffix(".launch")

    def held_by(self) -> str | None:
        """Return the launch holding the lock, by its id; none where none does."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        probe = FileLock(self.path, timeout=0)
        try:
            probe.acquire()
        except Timeout:
            return self.holder.read_text().strip() if self.holder.is_file() else "?"
        probe.release()
        return None

    def taken(self, launch: str, within: timedelta = timedelta(0)) -> FileLock:
        """Take the lock for `launch`, waiting `within` at most for another to let it go, and return it held; raise `LaunchError` naming the launch that holds it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(self.path, timeout=within.total_seconds())
        try:
            lock.acquire()
        except Timeout as held:
            holder = self.holder.read_text().strip() if self.holder.is_file() else "?"
            message = (
                f"the session {self.path.stem} is written by launch `{holder}`: a "
                "runtime lets a second process write one session, and its record "
                "branches, so lup doesn't. `lup-dev spawn end` ends a held one."
            )
            raise LaunchError(message) from held
        self.holder.write_text(launch)
        return lock

    def let_go(self, lock: FileLock) -> None:
        """Let the lock go, its launch forgotten."""
        self.holder.unlink(missing_ok=True)
        lock.release()


class Asked(MutableModel, arbitrary_types_allowed=True):
    """What the host asked a launcher to do that it carries out beside its session: its end."""

    ending: asyncio.Event
    """Set once the session is asked to end."""
    over: asyncio.Event
    """Set once it has ended."""


class Prompting(Model, Handler[HeldPrompt], arbitrary_types_allowed=True):
    """Answers `HeldPrompt`: the words given the session as its next turn."""

    session: HeldSession

    @override
    def request(self) -> type[HeldPrompt]:
        return HeldPrompt

    @override
    async def answer(self, request: HeldPrompt) -> Reply:
        await self.session.send(request.text)
        return Done()


class Interrupting(Model, Handler[HeldInterrupt], arbitrary_types_allowed=True):
    """Answers `HeldInterrupt`: the turn under way ended, or why not."""

    session: HeldSession

    @override
    def request(self) -> type[HeldInterrupt]:
        return HeldInterrupt

    @override
    async def answer(self, request: HeldInterrupt) -> Reply:
        try:
            await self.session.interrupt()
        except LupError as failed:
            raise HostError(str(failed)) from failed
        return Done()


class Ending(Model, Handler[HeldEnd], arbitrary_types_allowed=True):
    """Answers `HeldEnd`: the session ended, once it has."""

    asked: Asked

    @override
    def request(self) -> type[HeldEnd]:
        return HeldEnd

    @override
    async def answer(self, request: HeldEnd) -> Reply:
        self.asked.ending.set()
        await self.asked.over.wait()
        return Done()


class Holder(Model, arbitrary_types_allowed=True):
    """The launcher of a held session, from its room's start to its end."""

    layout: Layout
    host: HostClient
    holding: Callable[[Pipes, Callable[[str], None]], HeldSession]
    """The runtime's session held over the room's pipes, saying what it does
    through the function given (`lup_dev.adapters.Holding.session`)."""
    launch: str
    session: str
    """The runtime's id for the session, which the launch named up front."""
    name: str
    """The launch's name, as the host served it."""
    container: str
    """The room's container, by its name, stopped as the session ends."""
    sockets: Path
    """The launch's socket directory on the host, which its room mounts at
    `RoomPaths.sockets`: the session's own socket is made there, for its room's
    first program alone (`LaunchSockets.session`)."""
    podman: Podman
    say: Callable[[str], None]
    first_hook: timedelta = timedelta(minutes=1)
    """How long the host may take to hear the session's first hook before
    it's ended unheard: a runtime's start, its servers and hooks among it, took
    seconds when measured."""
    finishing: timedelta = timedelta(minutes=2)
    """How long a turn under way may take to finish at the session's end, before
    the runtime is asked to end, and as long again before it's made to."""
    pause: Callable[[float], Awaitable[None]] = asyncio.sleep
    """Waits the seconds between two looks at whether the first hook was heard;
    a test gives its own."""
    every: float = 0.5
    """How many seconds apart those looks are."""
    answering: timedelta = timedelta(seconds=10)
    """How long the requests the host made as the session ended may take to be
    answered, before the launcher goes on to end the launch."""

    async def held(
        self, room: Room, arguments: list[str], settings: TerminalSettings
    ) -> int:
        """Hold the session in `room`, `arguments` after lup's own, until it ends, and return its runtime's status.

        Its input and output are a socket only the room's first program
        reaches (`Room.hold`, `LaunchSockets.session`). The launcher's own
        socket is served while the room runs. The session is called up once the
        host heard its first hook, and ended unheard otherwise. It ends when its
        runtime exits, the host asks (`HeldEnd`), or the launcher is asked to
        (`SIGTERM`, `SIGINT`, `SIGHUP`). However it ends, a failure here
        among it, the runtime is ended and the room stopped; where podman can't
        stop it, that's said, and the launch is left registered for the sweep
        (`launched`).
        """
        piped = await self.started(room, arguments, settings)
        exited = asyncio.ensure_future(piped.run.waited())
        try:
            await self.serving(piped, exited)
        finally:
            status = (
                exited.result() if exited.done() else await ended(piped, self.finishing)
            )
            await self.stopped()
        self.say(f"The session ended, with status {status}.")
        return status

    async def started(
        self, room: Room, arguments: list[str], settings: TerminalSettings
    ) -> Piped:
        """Start the room, its session held over the socket its first program connects to; where that fails, stop what of the room started."""
        held = False
        try:
            piped = await room.hold(
                arguments,
                settings,
                listening=LaunchSockets(directory=self.sockets).session,
                connecting=LaunchSockets(directory=RoomPaths().sockets).session,
            )
            held = True
        finally:
            if not held:
                await self.stopped()
        return piped

    async def serving(self, piped: Piped, exited: asyncio.Future[int]) -> None:
        """Serve the launcher's socket and call the session up, until its runtime exits, or it's asked to end."""
        session = self.holding(piped.pipes, self.said)
        reading = asyncio.create_task(session.served())
        asked = Asked(ending=asyncio.Event(), over=asyncio.Event())
        dispatcher = Dispatcher(
            routes={
                route.kind: route
                for route in [
                    Route.to(Prompting(session=session)),
                    Route.to(Interrupting(session=session)),
                    Route.to(Ending(asked=asked)),
                ]
            },
            answering=f"launch {self.launch}'s launcher",
            say=self.say,
            changes=Changes(),
        )
        socket = self.layout.launch(self.launch).held
        socket.unlink(missing_ok=True)
        server = await unix_server(socket, dispatcher.connection)
        loop = asyncio.get_running_loop()
        # Only the main thread takes a signal, as the launcher's process runs it.
        signals = (
            [signal.SIGTERM, signal.SIGINT, signal.SIGHUP]
            if threading.current_thread() is threading.main_thread()
            else []
        )
        for each in signals:
            loop.add_signal_handler(each, asked.ending.set)
        try:
            if await self.heard(exited):
                await asyncio.to_thread(
                    self.host.ask,
                    CalledUp(launch=self.launch, name=self.name, session=self.session),
                    Done,
                )
                self.say(
                    f"The session {self.session} is held as `{self.name}`: `lup-dev "
                    f"spawn interrupt {self.name}` interrupts it, and `lup-dev spawn "
                    f"end {self.name}` ends it."
                )
                ending = asyncio.ensure_future(asked.ending.wait())
                await asyncio.wait(
                    [exited, ending], return_when=asyncio.FIRST_COMPLETED
                )
                ending.cancel()
            if not exited.done():
                await ended(piped, self.finishing)
            await self.stopped()
        finally:
            for each in signals:
                loop.remove_signal_handler(each)
            asked.over.set()
            await asyncio.wait([reading], timeout=self.finishing.total_seconds())
            reading.cancel()
            server.close()
            # What the host asked as the session ended is answered before the
            # loop ends, the end's own reply among it.
            closing = asyncio.ensure_future(server.wait_closed())
            await asyncio.wait([closing], timeout=self.answering.total_seconds())
            socket.unlink(missing_ok=True)

    async def heard(self, exited: asyncio.Future[int]) -> bool:
        """Wait until the host heard the session's first hook, and say whether it did before `first_hook` passed or the runtime exited; where it didn't, say why."""
        looks = max(1, int(self.first_hook.total_seconds() / self.every))
        for _ in range(looks):
            if exited.done():
                self.say(
                    f"The runtime exited before its first hook reached lup, with "
                    f"status {exited.result()}."
                )
                return False
            listed = await asyncio.to_thread(self.host.listed)
            talkers = listed.talkers.get(self.launch, [])
            if any(each.session == self.session for each in talkers):
                return True
            await self.pause(self.every)
        self.say(
            f"No hook of the session {self.session} reached lup within "
            f"{self.first_hook}, so it isn't called up: it would run without lup's "
            "judge. Its runtime may have stopped running hooks; it's ended."
        )
        return False

    async def stopped(self) -> None:
        """Stop the room, where it runs; where podman can't, say so, and leave it to the launch's end, which then leaves it registered for the sweep."""
        try:
            await asyncio.to_thread(self.podman.stop, self.container)
        except ContainerError as failed:
            self.say(f"The room, {self.container}, wasn't stopped: {failed}")

    def said(self, line: str) -> None:
        """Say what the session does, in the launcher's log."""
        self.say(f"Session: {line}")
