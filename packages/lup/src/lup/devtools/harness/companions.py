"""Running a checkout's host companions, shared by its sessions and counted per session.

The declaration is :class:`~lup.harness.companions.HostCompanion`; this is
the launch's half. A companion is one per checkout: the first session in a
checkout starts it, a later one reuses it, and each holds a lease on it, so
it is stopped only when the last lease goes. A lease is its launcher's
process, so a launcher that died without letting go is swept by the next
launch that looks. What a checkout keeps of each companion — its process,
the ports it was given, the leases on it — sits in a directory of its own
under :func:`companions_home`, outside the checkout, behind a lock every
launch takes before reading it, so two launches at once start it once.

A companion counts as alive while its process runs and every port it
declares answers. A process whose port stopped answering, or one started
from a declaration the checkout has since changed, is stopped and started
again for the session asking, and the sessions already sharing it keep their
leases on the one that replaces it.

Each checkout is given its own ports: the preferred one where it is free,
otherwise the next free one above it, skipping every port another companion
anywhere keeps, and remembered in the checkout's directory so the same
checkout comes back to the same address. Choosing is serialized across
checkouts by a lock of its own, so two checkouts launching at once are not
given one port.

Each starts in a session of its own, so the signal that stops it reaches
what it started too -- a dev server's workers, a watcher's children -- with
nothing on its input, since whichever launch started it may end long before
it does, and its output in a log beside its state rather than in the
terminal the session is about to take over. Stopping is gentle first and
certain after: a terminate to the whole group, a grace period, then a kill.

Each starts from the environment the launch hands its session, less every
host-only name, plus the host-store keys that companion names and no other:
a companion that did not ask for a key does not get it, even where the
operator's shell exported one.
"""

import asyncio
import fcntl
import logging
import os
import signal
import socket
import uuid
import webbrowser
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

import sh
from pydantic import BaseModel, ValidationError

from lup.channels.wait import wait_until
from lup.devtools.envfiles import HostSecrets
from lup.devtools.harness.modes import variants_home
from lup.harness.companions import CompanionPorts, HostCompanion, PortsGiven
from lup.harness.notice import Notice
from lup.sandbox.process import (
    process_is_alive,
    process_is_zombie,
    process_start_token,
)
from lup.types import EnvVars

logger = logging.getLogger(__name__)


def companions_home(root: Path) -> Path:
    """Where one checkout's companions keep their state and logs, outside the checkout.

    Its parent holds every checkout's, which is where the ports other
    checkouts keep are read from.
    """
    return variants_home(root, Path.home() / ".cache" / "lup" / "companions")


def host_only_names(declared: list[HostCompanion], hosted: EnvVars) -> list[str]:
    """Every name no session inherits: what a companion names, and what the store holds."""
    return sorted(
        {*(name for companion in declared for name in companion.secrets), *hosted}
    )


def missing_secrets(
    companion: HostCompanion, hosted: EnvVars, store: Path
) -> list[Notice]:
    """What the banner says of a key a companion names and the store does not hold.

    The companion starts all the same: it is a convenience beside the session,
    and the one that knows what it cannot do without a key is the companion.
    """
    missing = [name for name in companion.secrets if name not in hosted]
    if not missing:
        return []
    return [
        Notice(
            text=(
                f"Companion {companion.name}: {', '.join(missing)} not in the host "
                f"store ({store}), so it starts without; "
                f"`lup-launch run setup secret {' '.join(missing)}` sets it"
            ),
            urgency="boundary",
        )
    ]


class LiveProcess(BaseModel, frozen=True):
    """A process by its id and when it started, so a reused id is not taken for it."""

    pid: int
    started: str | None = None

    @classmethod
    def of(cls, pid: int) -> "LiveProcess":
        """The process running under ``pid`` now."""
        return cls(pid=pid, started=process_start_token(pid))

    def running(self) -> bool:
        """Whether it still runs: the same process, and not waiting to be collected."""
        return process_is_alive(self.pid, self.started) and not process_is_zombie(
            self.pid
        )

    def stop(self, grace: float) -> None:
        """Stop it and everything it started, gently and then surely, from any launch.

        It leads a process group of its own, so the group is signalled
        whether or not its leader is still there. A leader's id now belonging
        to another process says the group it led has gone.
        """
        current = process_start_token(self.pid)
        if current is not None and self.started is not None and current != self.started:
            return
        for sent in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(self.pid, sent)
            except (ProcessLookupError, PermissionError):
                return
            if asyncio.run(
                wait_until(
                    lambda: True if self.gone() else None,
                    wait_seconds=grace,
                    poll_interval_seconds=0.05,
                )
            ):
                return

    def gone(self) -> bool:
        """Whether nothing of its group is left, collecting its leader where it is ours."""
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            logger.debug("companion %s is not this launch's child", self.pid)
        try:
            os.killpg(self.pid, 0)
        except ProcessLookupError:
            return True
        return False


class Lease(BaseModel, frozen=True):
    """One session's hold on a companion, kept while its launcher runs."""

    id: str
    holder: LiveProcess


class GivenPort(BaseModel, frozen=True):
    """One port a checkout was given for one of a companion's names."""

    name: str
    preferred: int
    port: int


class RunningCompanion(BaseModel, frozen=True):
    """The process a checkout's companion runs as, and what it was started from."""

    process: LiveProcess
    declared: HostCompanion
    handed: list[str] = []
    """The host-store keys it was started with, by name."""


class CompanionState(BaseModel, frozen=True):
    """What one checkout keeps of one companion."""

    checkout: Path
    ports: list[GivenPort] = []
    running: RunningCompanion | None = None
    leases: list[Lease] = []

    def given(self) -> CompanionPorts:
        """The ports this checkout was given, by the companion's names for them."""
        return {port.name: port.port for port in self.ports}


class CompanionSlot(BaseModel, frozen=True):
    """One companion's directory in one checkout's home: its state, its lock, its log."""

    directory: Path

    def log(self) -> Path:
        """Where the companion's output goes."""
        return self.directory / f"{self.directory.name}.log"

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Hold this companion for one launch's read, decide and write."""
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / "lock").open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def read(self, checkout: Path) -> CompanionState:
        """What the checkout keeps of this companion; nothing, where it keeps nothing."""
        path = self.directory / "state.json"
        if not path.is_file():
            return CompanionState(checkout=checkout)
        try:
            return CompanionState.model_validate_json(path.read_bytes())
        except ValidationError as error:
            logger.warning(
                "companion state %s does not parse, so it starts over: %s", path, error
            )
            return CompanionState(checkout=checkout)

    def write(self, state: CompanionState) -> None:
        """Replace the state in one rename, so no reader meets half of it."""
        path = self.directory / "state.json"
        staged = path.with_name("state.json.tmp")
        staged.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        staged.replace(path)


def port_free(port: int) -> bool:
    """Whether a companion could listen on this port on the host's loopback now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def port_answers(port: int, within: float = 0.5) -> bool:
    """Whether something accepts a connection on this port of the host's loopback."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=within):
            return True
    except OSError:
        return False


@contextmanager
def choosing_ports(cache: Path) -> Iterator[None]:
    """Hold port choosing for every checkout, so two are never given one port."""
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / "ports.lock").open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def kept_elsewhere(cache: Path, slot: CompanionSlot) -> list[int]:
    """Every port another companion keeps, in a checkout that still exists."""
    return [
        given.port
        for path in cache.glob("*/*/state.json")
        if path.parent != slot.directory
        for state in [CompanionSlot(directory=path.parent).read(path.parent)]
        if state.checkout.is_dir()
        for given in state.ports
    ]


def given_ports(
    companion: HostCompanion,
    kept: list[GivenPort],
    claimed: list[int],
    free: Callable[[int], bool] = port_free,
) -> list[GivenPort]:
    """The port each of a companion's names is given in one checkout.

    What the checkout was given before stands while the declaration still
    prefers what it preferred then and the port is still free; otherwise the
    preferred port, else the next free one above it, never one ``claimed``
    by another companion or given to an earlier name here.
    """
    before = {given.name: given for given in kept}
    taken = {*claimed}

    def chosen(name: str, preferred: int) -> GivenPort:
        """One name's port, taken from what is left."""
        standing = before.get(name)
        port = (
            standing.port
            if standing is not None
            and standing.preferred == preferred
            and standing.port not in taken
            and free(standing.port)
            else next(
                (
                    candidate
                    for candidate in range(preferred, 65536)
                    if candidate not in taken and free(candidate)
                ),
                preferred,
            )
        )
        taken.add(port)
        return GivenPort(name=name, preferred=preferred, port=port)

    return [chosen(name, preferred) for name, preferred in companion.ports.items()]


class Beside(BaseModel, frozen=True):
    """What a session learns from its companions: the banner's lines, and their ports."""

    notices: list[Notice] = []
    ports: PortsGiven = {}
    """Each companion's ports as this checkout was given them, by ``<companion>.<port>``."""


class Joining(BaseModel, frozen=True):
    """Everything one launch's companions share: where they run and what they are handed."""

    root: Path
    home: Path
    base: EnvVars
    hosted: EnvVars
    store: Path
    lease: Lease
    grace: float
    ready_within: float

    def slot(self, companion: HostCompanion) -> CompanionSlot:
        """This companion's directory in the checkout's home."""
        return CompanionSlot(directory=self.home / companion.name)

    def environment(self, companion: HostCompanion) -> EnvVars:
        """The session's environment less every host-only name, plus this one's keys."""
        return {
            **self.base,
            **{
                name: self.hosted[name]
                for name in companion.secrets
                if name in self.hosted
            },
        }

    def handed(self, companion: HostCompanion) -> list[str]:
        """The host-store keys this companion would be started with."""
        return [name for name in companion.secrets if name in self.hosted]

    def reusable(self, companion: HostCompanion, state: CompanionState) -> bool:
        """Whether what runs is this declaration, still running, every port answering."""
        running = state.running
        return (
            running is not None
            and running.declared == companion
            and running.handed == self.handed(companion)
            and running.process.running()
            and all(port_answers(given.port) for given in state.ports)
        )

    def said(self, companion: HostCompanion, how: str, ports: CompanionPorts) -> Notice:
        """The banner's line for a companion that runs."""
        url = companion.at(ports).url
        where = f", {url}" if url else ""
        log = self.slot(companion).log()
        return Notice(
            text=f"Companion {companion.name}: {how}{where} (log: {log})",
            urgency="detail",
        )


def started(
    companion: HostCompanion, joining: Joining, ports: CompanionPorts
) -> LiveProcess:
    """Start one companion on the ports given, answering with its process.

    Raises :class:`sh.CommandNotFound` where its program is not installed here.
    """
    program, *arguments = companion.at(ports).command
    with Path(os.devnull).open("rb") as nothing:
        running = sh.Command(program)(
            *arguments,
            _bg=True,
            _bg_exc=False,
            _new_session=True,
            _cwd=str(joining.root / companion.directory),
            _env=joining.environment(companion),
            _in=nothing,
            _out=str(joining.slot(companion).log()),
            _err_to_out=True,
            _return_cmd=True,
        )
    return LiveProcess.of(running.pid)


def settled(process: LiveProcess, ports: CompanionPorts, within: float) -> bool | None:
    """Whether a started companion answers on every port, exited, or neither in time."""

    def answered() -> bool | None:
        """True once every port answers, false once the process has gone."""
        if not process.running():
            return False
        if all(port_answers(port) for port in ports.values()):
            return True
        return None

    if not ports:
        return True
    return asyncio.run(
        wait_until(answered, wait_seconds=within, poll_interval_seconds=0.1)
    )


def opened(
    companion: HostCompanion, url: str, browser: Callable[[str], bool]
) -> list[Notice]:
    """Open a started companion's url where it is declared to open, saying a failure."""
    if not companion.open:
        return []
    try:
        shown = browser(url)
    except (webbrowser.Error, OSError) as error:
        why = str(error)
    else:
        if shown:
            return []
        why = "no browser answered"
    return [
        Notice(
            text=f"Companion {companion.name}: {url} did not open in a browser ({why})",
            urgency="boundary",
        )
    ]


@contextmanager
def joined(
    companion: HostCompanion,
    joining: Joining,
    browser: Callable[[str], bool],
) -> Iterator[Beside]:
    """Hold one companion for one session: reuse it or start it, and let go after."""
    slot = joining.slot(companion)
    lease = joining.lease
    with slot.locked():
        state = slot.read(joining.root)
        leases = [held for held in state.leases if held.holder.running()]
        if joining.reusable(companion, state):
            holding = [*leases, lease]
            slot.write(state.model_copy(update={"leases": holding}))
            sessions = "1 session" if len(holding) == 1 else f"{len(holding)} sessions"
            said = [joining.said(companion, f"reused ({sessions})", state.given())]
        else:
            said = [*joining_anew(companion, joining, slot, state, leases, browser)]
        given = slot.read(joining.root).given()
    try:
        yield Beside(notices=said, ports=companion.references(given))
    finally:
        with slot.locked():
            state = slot.read(joining.root)
            remaining = [
                held
                for held in state.leases
                if held.id != lease.id and held.holder.running()
            ]
            if not remaining and state.running is not None:
                state.running.process.stop(joining.grace)
                state = state.model_copy(update={"running": None})
            slot.write(state.model_copy(update={"leases": remaining}))


def joining_anew(
    companion: HostCompanion,
    joining: Joining,
    slot: CompanionSlot,
    state: CompanionState,
    leases: list[Lease],
    browser: Callable[[str], bool],
) -> Iterator[Notice]:
    """Start a companion nothing reusable runs as, and say how that went.

    Called under the companion's lock. What ran before and does not count
    as alive is stopped first, so it holds no port the new one needs; the
    sessions already holding it keep their leases on the one replacing it.
    """
    if state.running is not None:
        state.running.process.stop(joining.grace)
    with choosing_ports(joining.home.parent):
        ports = given_ports(
            companion, state.ports, kept_elsewhere(joining.home.parent, slot)
        )
        state = state.model_copy(
            update={"ports": ports, "running": None, "leases": leases}
        )
        slot.write(state)
    given = state.given()
    yield from missing_secrets(companion, joining.hosted, joining.store)
    try:
        process = started(companion, joining, given)
    except sh.CommandNotFound:
        yield Notice(
            text=(
                f"Companion {companion.name}: {companion.command[0]} is not "
                "installed here, so it was not started"
            ),
            urgency="boundary",
        )
        return
    running = RunningCompanion(
        process=process, declared=companion, handed=joining.handed(companion)
    )
    holding = [*leases, joining.lease]
    slot.write(state.model_copy(update={"running": running, "leases": holding}))
    match settled(process, given, joining.ready_within):
        case False:
            yield Notice(
                text=(
                    f"Companion {companion.name}: started and exited at once; its "
                    f"log says why: {slot.log()}"
                ),
                urgency="boundary",
            )
            return
        case None:
            yield Notice(
                text=(
                    f"Companion {companion.name}: started, not yet answering on "
                    f"{', '.join(str(port) for port in given.values())} "
                    f"(log: {slot.log()})"
                ),
                urgency="boundary",
            )
        case True:
            yield joining.said(companion, "started", given)
    yield from opened(companion, companion.at(given).url, browser)


@contextmanager
def companions_running(
    declared: list[HostCompanion],
    root: Path,
    home: Path,
    store: HostSecrets,
    inherited: EnvVars,
    grace: float = 5.0,
    ready_within: float = 20.0,
    browser: Callable[[str], bool] = webbrowser.open,
) -> Iterator[Beside]:
    """Join each companion for one session, hand back what it learned, and let go after.

    ``home`` is where this checkout's companions keep their state
    (:func:`companions_home`); ``inherited`` is the environment the launch
    hands its session; ``store`` is the host store the companions' secrets
    are read from. A companion that cannot start -- its program is not
    installed here -- is said and skipped, since it is a convenience beside
    the session rather than something the session needs; the others still
    start. ``ready_within`` is how long a started companion's ports are
    waited for before the session opens anyway, and ``grace`` how long a
    stopped one is given before it is killed.
    """
    if not declared:
        yield Beside()
        return
    hosted = store.read()
    withheld = host_only_names(declared, hosted)
    joining = Joining(
        root=root,
        home=home,
        base={name: value for name, value in inherited.items() if name not in withheld},
        hosted=hosted,
        store=store.path,
        lease=Lease(id=uuid.uuid4().hex, holder=LiveProcess.of(os.getpid())),
        grace=grace,
        ready_within=ready_within,
    )
    with ExitStack() as held:
        each = [
            held.enter_context(joined(companion, joining, browser))
            for companion in declared
        ]
        yield Beside(
            notices=[notice for one in each for notice in one.notices],
            ports={
                reference: port for one in each for reference, port in one.ports.items()
            },
        )
