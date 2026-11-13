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
import os
import secrets
import signal
import traceback
from collections.abc import Awaitable, Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Literal, override

from pydantic import ValidationError

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
    Spawner,
)
from lup_dev.host.service import Handler
from lup_dev.layout import HostPaths, Layout


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
    session: str | None = None
    """The runtime's id for the session it starts, minted by the host where an
    agent spawned it, so its brief is addressed to it before it's up; none has
    the launcher mint one, or resume `resume`."""
    repository: AbsolutePath | None = None
    """The repository's git directory as the host recorded the spawner's
    launch, where an agent spawned it: the launcher refuses a worktree whose
    git leads elsewhere, which a room can write. None for the operator's own,
    whose worktree says it, as a launch's does."""
    spawner: Spawner | None = None
    """Who spawned it, where an agent did (`Register.spawner`)."""


class SpawnedLauncher(Model):
    """A launcher an agent's spawn started, as the service keeps it beside the launch's lock: what it was started with, and its process."""

    spec: HeldLaunch
    pid: int


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
    """A held launch's launcher is started: its launch's id, its process's, and where it writes what it says. Its session is up once `AwaitHeld` says so."""

    kind: Literal["held-starting"] = "held-starting"
    launch: str
    pid: int
    """The launcher's process: a service started after this one, as an
    approval starts one, knows it by this alone."""
    log: Path


class AwaitHeld(Request, reads=False):
    """Wait until a held launch's session is up, answered once it is, or its launcher ended first; a service that didn't start the launcher watches its process."""

    kind: Literal["await-held"] = "await-held"
    launch: LaunchId
    pid: int


class Abandon(Request, reads=False):
    """End a held launch's launcher whose session isn't up yet, as the operator gave up waiting on it; refused once it's up, which `End` ends."""

    kind: Literal["abandon"] = "abandon"
    launch: LaunchId
    pid: int


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
    specs: dict[str, HeldLaunch] = {}
    """What each launcher in `started` was started with, by launch id: an
    agent's spawn counts against the limit from its start, before its launch
    registers."""

    def reaped(self) -> list[HeldLaunch]:
        """Forget each launcher that has ended, its status collected so the OS frees it, and what it was waiting on; the sweep looks. Return what each whose session was never up was started with, so its spawner hears of it."""
        ended = [launch for launch, each in self.started.items() if each.ended()]
        lost = [
            self.specs[launch]
            for launch in ended
            if launch in self.specs
            and not (launch in self.waiting and self.waiting[launch].done())
        ]
        self.started = {
            launch: each for launch, each in self.started.items() if launch not in ended
        }
        self.specs = {
            launch: each for launch, each in self.specs.items() if launch not in ended
        }
        self.waiting = {
            launch: up for launch, up in self.waiting.items() if launch not in ended
        }
        return lost

    def spawning(
        self, layout: Layout, paths: HostPaths | None = None
    ) -> list[HeldLaunch]:
        """Return each launch an agent spawned whose launcher hasn't been seen to end: counted against the limits before its launch registers. Those this service started, and those a service before it started, kept beside their lock in `layout` while their launcher runs (`LaunchLayout.spawned`), by their process (`launching`); one kept whose launcher is gone is forgotten."""
        mine = [
            spec
            for launch, spec in self.specs.items()
            if spec.spawner is not None
            and launch in self.started
            and not self.started[launch].ended()
        ]
        looked = HostPaths() if paths is None else paths
        kept = [
            each
            for each in kept_launchers(layout)
            if each.spec.launch not in self.specs
        ]
        for each in kept:
            if not launching(looked, each.pid, each.spec.launch):
                layout.launch(each.spec.launch).spawned.unlink(missing_ok=True)
        return [
            *mine,
            *(
                each.spec
                for each in kept
                if launching(looked, each.pid, each.spec.launch)
            ),
        ]


def kept_launchers(layout: Layout) -> list[SpawnedLauncher]:
    """Return each launcher an agent's spawn started that a service kept beside its launch's lock; one that doesn't read left out."""

    def read() -> Iterator[SpawnedLauncher]:
        for each in sorted(layout.launches.glob("*.spawned.json")):
            try:
                yield SpawnedLauncher.model_validate_json(each.read_text())
            except ValidationError, OSError:
                continue

    return list(read())


def launching(paths: HostPaths, pid: int, launch: str) -> bool:
    """Say whether the process `pid` is still the launcher of `launch`: there, and naming the launch in its command, so a process given its id since is never taken for it. One ended and not yet collected has no command left, so it reads as ended."""
    try:
        command = (paths.proc / str(pid) / "cmdline").read_bytes()
    except OSError:
        return False
    return launch.encode() in command


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
        """Start the launcher of the launch the operator asks for."""
        return await self.started(
            lambda launch: HeldLaunch(
                launch=launch,
                runtime=request.runtime,
                worktree=request.worktree,
                name=request.name,
                profile=request.profile,
                account=request.account,
                resume=request.resume,
                arguments=request.arguments,
            )
        )

    async def started(self, launching: Callable[[str], HeldLaunch]) -> Starting:
        """Mint a launch's id, and start the launcher of the launch `launching` makes of it, what its word that its session is up resolves made first: the operator's `spawn`, and an agent's."""
        launch = secrets.token_hex(8)
        spec = launching(launch)
        log = self.layout.launch(launch).log
        up: asyncio.Future[CalledUp] = asyncio.get_running_loop().create_future()
        self.launchers.waiting = {**self.launchers.waiting, launch: up}
        launcher = await asyncio.to_thread(self.start, spec, log)
        self.launchers.started = {**self.launchers.started, launch: launcher}
        self.launchers.specs = {**self.launchers.specs, launch: spec}
        if spec.spawner is not None:
            kept = SpawnedLauncher(spec=spec, pid=launcher.process.pid)
            self.layout.launch(launch).spawned.write_text(kept.model_dump_json())
        return Starting(launch=launch, pid=launcher.process.pid, log=log)


class Awaiting(Model, Handler[AwaitHeld], arbitrary_types_allowed=True):
    """Answers `AwaitHeld`: the session up, or why not."""

    layout: Layout
    launchers: Launchers
    paths: HostPaths = HostPaths()
    """Where a launcher another service started is looked for."""
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
        """Wait until the launcher says its session is up; refuse where it ended first, with the end of what it wrote.

        A launcher another service started, as before an approval restarted
        this one, is watched by its process (`launching`), and its word that
        it's up is waited for here from then on.
        """
        launch = request.launch
        up = self.launchers.waiting.get(launch)
        if up is None:
            up = asyncio.get_running_loop().create_future()
            self.launchers.waiting = {**self.launchers.waiting, launch: up}
        launcher = self.launchers.started.get(launch)

        def ended() -> bool:
            if launcher is not None:
                return launcher.ended()
            return not launching(self.paths, request.pid, launch)

        log = self.layout.launch(launch).log
        while not up.done():
            if ended() and not up.done():
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
    paths: HostPaths = HostPaths()
    """Where a launcher another service started is looked for."""
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
        if up is not None and not up.done():
            up.cancel()
        launcher = self.launchers.started.get(request.launch)
        if launcher is not None:
            await asyncio.to_thread(launcher.end, self.patience)
            return Done()
        if launching(self.paths, request.pid, request.launch):
            # Another service started it: it's asked to end, as its own
            # `SIGTERM` handling ends a session it holds.
            os.kill(request.pid, signal.SIGTERM)
        return Done()


class CallingUp(Model, Handler[CalledUp], arbitrary_types_allowed=True):
    """Answers `CalledUp`: the spawn waiting on it answered, and the session given what waits for it."""

    launchers: Launchers
    up: Callable[[CalledUp], Awaitable[None]] | None = None
    """Gives the session what waits for it as its first turn, which it wasn't
    told as it started (`Delivery.called_up`, which `cli.py` gives); none gives
    nothing."""
    say: Callable[[str], None] = lambda _: None
    """Where a failure giving it is said, which refuses nothing: the session
    is up all the same, and what waits stays waiting for its next hook."""

    @override
    def request(self) -> type[CalledUp]:
        return CalledUp

    @override
    async def answer(self, request: CalledUp) -> Reply:
        """Resolve what an await of the launch waits on, or will: a service started after the spawn, as an approval starts one, hears it before anyone awaits it again. Then give the session what waits."""
        waiting = self.launchers.waiting.get(request.launch)
        if waiting is None:
            waiting = asyncio.get_running_loop().create_future()
            self.launchers.waiting = {**self.launchers.waiting, request.launch: waiting}
        if not waiting.done():
            waiting.set_result(request)
        if self.up is None:
            return Done()
        try:
            await self.up(request)
        except Exception as failed:
            told = "".join(traceback.format_exception(failed))
            self.say(
                f"{request.launch}: what waits for its held session wasn't given it "
                f"as it came up, so it waits for the session's next hook:\n{told}"
            )
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
