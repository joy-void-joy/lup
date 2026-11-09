"""Sessions held with no terminal, as the host service starts and reaches them (`docs/launch.md`, *A session held with no terminal*).

A held launch's launcher is a process of its own, apart from the service, so a
restart of the service doesn't touch its session (`lup_dev.launch.held`). The
service starts one at the operator's request (`Spawn`), and reaches each
through the socket beside its lock, which no room mounts (`LaunchLayout.held`),
one request per connection as on the control socket:
- `HeldPrompt`, the operator's words starting a turn of the idle session, which
  the inbox sends where it would push to a session in a terminal
  (`Delivery.wake`);
- `HeldInterrupt`, ending the turn under way (`Interrupt`, the operator's);
- `HeldEnd`, ending the session, its room with it (`End`, the operator's).

The launcher says its session is up (`CalledUp`) once the service heard its
first hook: a runtime that ran none would run without lup's judge, so it isn't
called up.
"""

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Literal, override

from lup.programs import Apart
from lup.rooms.container import AbsolutePath
from lup.types import Model, MutableModel
from lup_dev.host.holders import HeldEnd, HeldInterrupt, Holders
from lup_dev.host.protocol import (
    Done,
    HostError,
    LaunchId,
    Name,
    Refused,
    Reply,
    Request,
)
from lup_dev.host.service import Handler
from lup_dev.layout import Layout


class HeldLaunch(Model):
    """A held launch as its launcher is started with it: the launch's id, minted by the host, and what the operator asked."""

    launch: LaunchId
    runtime: str
    worktree: AbsolutePath
    """The worktree it runs in, as the operator's command found it."""
    name: Name | None = None
    """The name asked for as it is (`--name`); none names it after its branch."""
    profile: str | None = None
    account: str | None = None
    resume: str | None = None
    """The runtime's id for the session it resumes; none starts a new one."""
    arguments: list[str] = []
    """The runtime's own arguments, after lup's."""


class Spawn(Request, reads=False):
    """Start a session held with no terminal, its launcher apart from the service; answered once the session is up, or its launcher ended before."""

    kind: Literal["spawn"] = "spawn"
    runtime: str
    worktree: AbsolutePath
    name: Name | None = None
    profile: str | None = None
    account: str | None = None
    resume: str | None = None
    arguments: list[str] = []


class Starting(Reply):
    """A held launch's launcher is started: its launch's id, and where it writes what it says. Its session is up once `AwaitHeld` says so."""

    kind: Literal["held-starting"] = "held-starting"
    launch: str
    log: Path


class AwaitHeld(Request, reads=False):
    """Wait until a held launch's session is up, answered once it is, or its launcher ended first."""

    kind: Literal["await-held"] = "await-held"
    launch: LaunchId


class Abandon(Request, reads=False):
    """End a held launch's launcher whose session isn't up yet, as the operator gave up waiting on it; refused once it's up, which `End` ends."""

    kind: Literal["abandon"] = "abandon"
    launch: LaunchId


class HeldUp(Reply):
    """The held session is up: its launch, the name it took, the runtime's id for its session, and where its launcher writes what it says."""

    kind: Literal["held-up"] = "held-up"
    launch: str
    name: str
    session: str
    log: Path


class CalledUp(Request, reads=False):
    """A launcher's word that its held session is up: served, and its first hook heard."""

    kind: Literal["called-up"] = "called-up"
    launch: LaunchId
    name: str
    session: str


class Interrupt(Request, reads=False):
    """End the turn a held session has under way."""

    kind: Literal["interrupt"] = "interrupt"
    launch: LaunchId


class End(Request, reads=False):
    """End a held session, and its room with it; answered once it has ended."""

    kind: Literal["end"] = "end"
    launch: LaunchId


class Launchers(MutableModel, arbitrary_types_allowed=True):
    """The launchers the service started, until each has ended, and what each one's word that its session is up resolves."""

    waiting: dict[str, asyncio.Future[CalledUp]] = {}
    """By launch id, what its launcher's word that it's up resolves, from its
    start until its session is up or it ended."""
    started: dict[str, Apart] = {}
    """Each launcher started, by launch id, until it's seen to end, so none is
    left a zombie."""

    def reaped(self) -> None:
        """Forget each launcher that has ended, its status collected so the OS frees it, and what it was waiting on; the sweep looks."""
        ended = [launch for launch, each in self.started.items() if each.ended()]
        self.started = {
            launch: each for launch, each in self.started.items() if launch not in ended
        }
        self.waiting = {
            launch: up for launch, up in self.waiting.items() if launch not in ended
        }


def tail(log: Path, lines: int = 20) -> str:
    """Return the last `lines` lines of what a launcher wrote, or say it wrote nothing."""
    try:
        written = log.read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return "it wrote nothing"
    return "\n".join(written[-lines:]) or "it wrote nothing"


class Spawning(Model, Handler[Spawn], arbitrary_types_allowed=True):
    """Answers `Spawn`: a launcher started apart, its launch's id and log replied at once."""

    layout: Layout
    launchers: Launchers
    start: Callable[[HeldLaunch, Path], Apart]
    """Starts a launcher for the launch given, apart from the service, what it
    prints appended to the file given."""

    @override
    def request(self) -> type[Spawn]:
        return Spawn

    @override
    async def answer(self, request: Spawn) -> Reply:
        """Mint the launch's id and start its launcher, what its word that its session is up resolves made first."""
        launch = secrets.token_hex(8)
        spec = HeldLaunch(
            launch=launch,
            runtime=request.runtime,
            worktree=request.worktree,
            name=request.name,
            profile=request.profile,
            account=request.account,
            resume=request.resume,
            arguments=request.arguments,
        )
        log = self.layout.launch(launch).log
        up: asyncio.Future[CalledUp] = asyncio.get_running_loop().create_future()
        self.launchers.waiting = {**self.launchers.waiting, launch: up}
        launcher = await asyncio.to_thread(self.start, spec, log)
        self.launchers.started = {**self.launchers.started, launch: launcher}
        return Starting(launch=launch, log=log)


class Awaiting(Model, Handler[AwaitHeld], arbitrary_types_allowed=True):
    """Answers `AwaitHeld`: the session up, or why not."""

    layout: Layout
    launchers: Launchers
    pause: Callable[[float], Awaitable[None]] = asyncio.sleep
    """Waits the seconds between two looks at whether the launcher ended; a
    test gives its own."""
    every: float = 0.5
    """How many seconds apart those looks are."""

    @override
    def request(self) -> type[AwaitHeld]:
        return AwaitHeld

    @override
    async def answer(self, request: AwaitHeld) -> Reply:
        """Wait until the launcher says its session is up; refuse where it ended first, with the end of what it wrote, or isn't one this service started."""
        launch = request.launch
        up = self.launchers.waiting.get(launch)
        launcher = self.launchers.started.get(launch)
        if up is None or launcher is None:
            message = f"no launcher this service started waits on launch {launch}"
            raise HostError(message)
        log = self.layout.launch(launch).log
        while not up.done():
            if launcher.ended() and not up.done():
                return Refused(
                    error=(
                        f"the launcher of launch {launch} ended before its session "
                        f"was up; the end of what it wrote ({log}):\n{tail(log)}"
                    )
                )
            await self.pause(self.every)
        called = up.result()
        return HeldUp(launch=launch, name=called.name, session=called.session, log=log)


class Abandoning(Model, Handler[Abandon], arbitrary_types_allowed=True):
    """Answers `Abandon`: the launcher ended, its session never called up."""

    launchers: Launchers
    patience: timedelta = timedelta(seconds=10)
    """How long the launcher may take to end once asked, before it's made to."""

    @override
    def request(self) -> type[Abandon]:
        return Abandon

    @override
    async def answer(self, request: Abandon) -> Reply:
        """End the launcher, asked then made to, where its session isn't up; refuse where it is."""
        up = self.launchers.waiting.get(request.launch)
        if up is not None and up.done():
            message = (
                f"launch {request.launch}'s session is up already: `lup-dev spawn "
                "end` ends it"
            )
            raise HostError(message)
        launcher = self.launchers.started.get(request.launch)
        if launcher is not None:
            await asyncio.to_thread(launcher.end, self.patience)
        if up is not None and not up.done():
            up.cancel()
        return Done()


class CallingUp(Model, Handler[CalledUp], arbitrary_types_allowed=True):
    """Answers `CalledUp`: the spawn waiting on it answered."""

    launchers: Launchers

    @override
    def request(self) -> type[CalledUp]:
        return CalledUp

    @override
    async def answer(self, request: CalledUp) -> Reply:
        waiting = self.launchers.waiting.get(request.launch)
        if waiting is not None and not waiting.done():
            waiting.set_result(request)
        return Done()


class Interrupting(Model, Handler[Interrupt], arbitrary_types_allowed=True):
    """Answers `Interrupt`: the held session's turn ended, through its launcher."""

    holders: Holders

    @override
    def request(self) -> type[Interrupt]:
        return Interrupt

    @override
    async def answer(self, request: Interrupt) -> Reply:
        """Interrupt the turn, then take the session for idle and give it what waits (`Holders.interrupted`)."""
        done = await self.holders.asked(request.launch, HeldInterrupt())
        if self.holders.interrupted is not None:
            await self.holders.interrupted(request.launch)
        return done


class Ending(Model, Handler[End], arbitrary_types_allowed=True):
    """Answers `End`: the held session ended, through its launcher, once it has."""

    holders: Holders

    @override
    def request(self) -> type[End]:
        return End

    @override
    async def answer(self, request: End) -> Reply:
        return await self.holders.asked(request.launch, HeldEnd())


def launcher_command(program: list[str], spec: HeldLaunch) -> list[str]:
    """Return the command starting a held launch's launcher: `program`, the `lup-dev` the service runs, then the hidden command and the launch, as JSON.

    >>> spec = HeldLaunch(launch="a1", runtime="probe", worktree=Path("/w"))
    >>> launcher_command(["lup-dev"], spec)[:3]
    ['lup-dev', 'spawn', 'launcher']
    >>> HeldLaunch.model_validate_json(launcher_command(["lup-dev"], spec)[-1]) == spec
    True
    """
    return [*program, "spawn", "launcher", spec.model_dump_json()]
