"""Moving the host service from one copy of `lup-dev` to another, and back where the other doesn't answer.

`docs/trust.md`, *The way back*. Nothing supervises the host service, which starts
detached, so whatever acts on a switch is what's left watching it: the terminal
answering an approval, the process the page starts for one (`Host.settle`), or
`lup-dev restore`.

**"Answers" is the service and the dashboard really serving** (`Serving`): a real
reading on the control socket, not a connection a kernel accepts for a stuck
loop; the dashboard's address; the page; each script and stylesheet the page
names, whole; and the API relaying a reading back from the service, with the
dashboard's token. There's no browser on the host, so a script that throws as it
mounts, which leaves the page blank, passes; the gate's `drive` step is what sees
that, and `lup-dev restore` and the plain page are what's left after it.

**The old copy stays up until the other answers,** which two services can't do on
one state (a service holds its lock for its whole life). So a copy that has
never answered is first run on a state of its own (`Rehearsal`): a copy of the
ledger, its own sockets, a free port, nothing that reaches beyond them
(`LupDevSettings.lup_host_rehearsing`), with the service the operator's sessions
use untouched. A copy that fails there interrupts nothing and changes nothing. A
copy that has answered before needs no second try, so flipping between copies
is a stop, a snapshot and a start.

**Then the hand-over** (`Switching.handed_over`): stop the service, snapshot the
ledger, move the link and the approval, start the copy, and ask the same
questions; once it answers, the person's commands name it and what ran before
is what `lup-dev restore` runs from. Where it doesn't, it's ended, the link and
the approval go back, the ledger too where the copy moved its tables past what
the one before reads, and the one before is started again. A signal meant to
interrupt it waits until it's done (`uninterrupted`), since cut short it leaves
no service and nobody to start one.

Each outside edge is a seam its tests stand in for: the program started
(`Processes`), and the pages fetched (`Pages`).
"""

import http.client
import os
import signal
import sqlite3
import tempfile
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Literal, override
from urllib.parse import urljoin, urlsplit

from filelock import FileLock, Timeout
from pydantic import Field, ValidationError

from lup.programs import Apart, ProgramError, detached
from lup.types import Model
from lup_dev.approval import Approval, approved
from lup_dev.clock import Clock
from lup_dev.conversions import snapshot
from lup_dev.copies import Copies, Kept, linked
from lup_dev.host.client import Detached, HostClient
from lup_dev.host.dashboard import DashboardShown, ShowDashboard
from lup_dev.host.on_trial import CopySwitching, LastSwitch, SwitchCopy, TrialListed
from lup_dev.host.protocol import HostError, Listed, ListLaunches, Reply, Request
from lup_dev.host.service import Handler
from lup_dev.layout import CopyLayout, HostLayout, JudgeLayout, Layout
from lup_dev.settings import LupDevSettings
from lup_dev.snapshots import Restored, Snapshot, Snapshots, written
from lup_dev.stored import read_model, write_model
from lup_dev.trial import trial_listed
from lup_ledger.environment.layout import LedgerLayout

if TYPE_CHECKING:
    from collections.abc import Generator
    from types import FrameType


class Fetched(Model):
    """What a page's address gave: its status, its type and its body, or why nothing came."""

    status: int = 0
    kind: str = ""
    body: bytes = b""
    error: str = ""


class Pages(ABC):
    """Where the dashboard's pages are fetched from."""

    @abstractmethod
    def fetched(
        self, url: str, *, token: str | None = None, posted: str | None = None
    ) -> Fetched:
        """Fetch `url`, with the dashboard's `token` where it's given, posting JSON `posted` where it's given."""


class Local(Model, Pages):
    """The dashboard over HTTP on this machine, which no proxy stands in front of."""

    timeout: timedelta = timedelta(seconds=10)

    @override
    def fetched(
        self, url: str, *, token: str | None = None, posted: str | None = None
    ) -> Fetched:
        split = urlsplit(url)
        connection = http.client.HTTPConnection(
            split.hostname or "", split.port, timeout=self.timeout.total_seconds()
        )
        bearer = {} if token is None else {"Authorization": f"Bearer {token}"}
        typed = {} if posted is None else {"Content-Type": "application/json"}
        try:
            connection.request(
                "GET" if posted is None else "POST",
                split.path or "/",
                body=posted,
                headers={**bearer, **typed},
            )
            reply = connection.getresponse()
            return Fetched(
                status=reply.status,
                kind=reply.getheader("Content-Type") or "",
                body=reply.read(),
            )
        except (OSError, http.client.HTTPException) as failed:
            return Fetched(error=str(failed))
        finally:
            connection.close()


class Naming(HTMLParser):
    """Gathers the addresses of the scripts and stylesheets a page names."""

    def __init__(self) -> None:
        """Start with none gathered."""
        super().__init__()
        self.found: list[str] = []

    @override
    def handle_starttag(
        self,
        tag: str,
        # lup: ignore("tuple-shape", why="`HTMLParser` calls this with a tag's attributes so")
        attrs: list[tuple[str, str | None]],
    ) -> None:
        def of(name: str) -> str | None:
            return next((value for each, value in attrs if each == name), None)

        match tag, of("rel"):
            case "script", _:
                address = of("src")
            case "link", "stylesheet" | "modulepreload":
                address = of("href")
            case _:
                address = None
        if address is not None:
            self.found.append(address)


def assets(page: str) -> list[str]:
    """List the scripts and stylesheets `page` names, by their addresses.

    >>> assets('<script src="/a.js"></script><link rel="stylesheet" href="/b.css">'
    ...     '<link rel="icon" href="/c.png"><script>inline()</script>')
    ['/a.js', '/b.css']
    """
    parser = Naming()
    parser.feed(page)
    return parser.found


class Started(ABC):
    """A service started, for whoever started it to watch."""

    @abstractmethod
    def ended(self) -> bool:
        """Say whether it has ended already, so nobody waits on it to answer."""

    @abstractmethod
    def end(self) -> None:
        """End it however it stands, the dashboard it runs ending with it."""


class Answers(ABC):
    """What says a service answers."""

    @abstractmethod
    def failing(self, host: HostClient, started: Started | None) -> str | None:
        """Wait for the service `host` reaches to serve, and say why it doesn't; none where it does. `started` is the process, where this started it: where it ends, nothing waits on it."""


class Unserved(Model):
    """What a try found not serving."""

    why: str
    within: timedelta = timedelta()
    """How long after the service started asking again could change it: none for
    what a server serving says of itself, as a page it doesn't have."""

    def said(self) -> str:
        """Say it, with how long it was given.

        >>> Unserved(why="no page").said()
        'no page'
        >>> Unserved(why="it doesn't answer", within=timedelta(minutes=1)).said()
        "after 0:01:00, it doesn't answer"
        """
        return f"after {self.within}, {self.why}" if self.within else self.why


class Serving(Model, Answers, arbitrary_types_allowed=True):
    """The service and the dashboard really serving, by what a page would ask."""

    clock: Clock
    pages: Pages = Field(default_factory=Local)
    patience: timedelta = timedelta(seconds=60)
    """How long a service just started may take to come up: a start takes seconds,
    a conversion of what the ledger stores may take longer."""
    settling: timedelta = timedelta(seconds=10)
    """How long a dashboard refused may be for what's going away, not what's
    coming up: the one before, ended rather than stopped, on the port this wants."""
    poll: timedelta = timedelta(milliseconds=50)
    """How often to ask meanwhile."""

    @override
    def failing(self, host: HostClient, started: Started | None) -> str | None:
        """Ask until it serves, `patience` at most, for as long as what started it runs and what it says could change: a copy that can't serve says so at once."""
        began = self.clock.now()
        while True:
            unserved = self.tried(host)
            if unserved is None:
                return None
            if started is not None and started.ended():
                return f"its service ended as it started: {unserved.why}"
            if self.clock.now() - began >= unserved.within:
                return unserved.said()
            self.clock.sleep(self.poll.total_seconds())

    def tried(self, host: HostClient) -> Unserved | None:
        """Ask once, saying what doesn't serve; none where all of it does."""
        try:
            host.ask(ListLaunches(), Listed)
        except (HostError, OSError) as failed:
            why = f"the host service doesn't answer: {failed}"
            return Unserved(why=why, within=self.patience)
        try:
            shown = host.ask(ShowDashboard(), DashboardShown)
        except (HostError, OSError) as failed:
            why = f"the host service answers, but its dashboard doesn't: {failed}"
            return Unserved(why=why, within=self.settling)
        return self.served(shown.address)

    def served(self, address: str) -> Unserved | None:
        """Ask the dashboard at `address`, its token in the fragment, for the page, what the page names, and a reading through its API; say what it doesn't serve."""
        split = urlsplit(address)
        token = split.fragment.removeprefix("token=")
        root = f"{split.scheme}://{split.netloc}/"
        page = self.pages.fetched(root)
        if page.error:
            why = f"the dashboard doesn't answer at {root}: {page.error}"
            return Unserved(why=why, within=self.patience)
        if page.status != 200 or "html" not in page.kind or not page.body:
            found = f"status {page.status}, {page.kind or 'no type'}"
            return Unserved(
                why=f"the dashboard doesn't serve its page at {root}: {found}"
            )
        for each in assets(page.body.decode(errors="replace")):
            asset = self.pages.fetched(urljoin(root, each))
            if asset.status != 200 or not asset.body:
                found = asset.error or f"status {asset.status}, {len(asset.body)} bytes"
                return Unserved(
                    why=f"the dashboard's page names {each}, unserved: {found}"
                )
        asked = ListLaunches().model_dump_json()
        api = self.pages.fetched(f"{root}api/ask", token=token, posted=asked)
        if api.status != 200 or b'"listed"' not in api.body:
            found = api.error or f"status {api.status}"
            return Unserved(
                why=f"the dashboard's API doesn't relay the service's answers: {found}"
            )
        return None


class Processes(ABC):
    """How a copy's service is started, and one that stopped answering ended."""

    @abstractmethod
    def started(self, command: list[str], log: Path) -> Started:
        """Run `command`, a copy's service, detached, appending what it prints to `log`. Raise `ProgramError` where it can't start."""

    @abstractmethod
    def killed(self, layout: HostLayout) -> str | None:
        """End the service at `layout`, whatever holds its lock; say why it couldn't be, none where none runs."""


class Program(Model, Started):
    """A service started as a program of its own."""

    process: Apart
    patience: timedelta = timedelta(seconds=10)

    @override
    def ended(self) -> bool:
        return self.process.ended()

    @override
    def end(self) -> None:
        self.process.end(self.patience)


class Programs(Model, Processes):
    """The machine's own processes."""

    patience: timedelta = timedelta(seconds=10)
    """How long a service asked to end may take before it's made to."""

    @override
    def started(self, command: list[str], log: Path) -> Started:
        program, *arguments = command
        return Program(process=detached(program, *arguments, log=log))

    @override
    def killed(self, layout: HostLayout) -> str | None:
        """End the process holding the service's lock, by the id it keeps beside it: asked first, then made to. The lock alone says one runs, since a process id outlives its process."""
        if self.free(layout, timedelta()):
            return None
        if not layout.pid.is_file():
            return (
                f"a host service holds {layout.lock} and doesn't answer, and it runs a "
                f"copy from before it kept its process id at {layout.pid}, so it isn't "
                "known which to end: end it yourself (`pkill -f 'lup-dev host'`), then "
                "run this again"
            )
        process = int(layout.pid.read_text())
        for each in [signal.SIGTERM, signal.SIGKILL]:
            try:
                os.kill(process, each)
            except ProcessLookupError:
                return None
            if self.free(layout, self.patience):
                return None
        return (
            f"process {process}, which holds {layout.lock}, wouldn't end: end it "
            "yourself, then run this again"
        )

    def free(self, layout: HostLayout, within: timedelta) -> bool:
        """Say whether no service holds the lock one holds for its whole life, waiting `within` at most."""
        layout.lock.parent.mkdir(parents=True, exist_ok=True)
        life = FileLock(layout.lock, timeout=within.total_seconds())
        try:
            with life:
                return True
        except Timeout:
            return False


def tail(log: Path, lines: int = 12) -> str:
    """Return the last `lines` lines of `log`, where a service that didn't answer said why; nothing where it's not there."""
    if not log.is_file():
        return ""
    with log.open(errors="replace") as read:
        return "".join(deque(read, maxlen=lines)).strip()


class Rehearsal(Model, arbitrary_types_allowed=True):
    """A copy's service run on a state of its own, the operator's copied ledger in it, with nothing reaching past it, for what it says of whether the copy answers."""

    layout: Layout
    answers: Answers
    processes: Processes
    clock: Clock

    def failing(self, command: Path) -> str | None:
        """Run the copy whose command is `command`, and say why it doesn't answer; none where it does.

        The ledger is copied, as one state, through a connection that only
        reads it, with the service that writes it running on. Attachments aren't
        copied, since they're read as they're asked for. The state is under
        lup's own, which no room mounts, on the disk rather than wherever
        temporary files go; the sockets are in a temporary directory, for a path
        short enough for a socket's.
        """
        self.layout.state.mkdir(parents=True, exist_ok=True)
        with (
            tempfile.TemporaryDirectory(
                prefix="rehearsal-", dir=self.layout.state, ignore_cleanup_errors=True
            ) as state,
            tempfile.TemporaryDirectory(
                prefix="lup-rehearsal-", ignore_cleanup_errors=True
            ) as runtime,
        ):
            settings = LupDevSettings(
                xdg_state_home=Path(state) / "state",
                xdg_runtime_dir=Path(runtime),
                xdg_cache_home=Path(state) / "cache",
                xdg_data_home=Path(state) / "data",
            )
            scratch = Layout.of(settings)
            snapshot(LedgerLayout.of(self.layout), LedgerLayout.of(scratch))
            variables = [
                f"XDG_STATE_HOME={settings.xdg_state_home}",
                f"XDG_RUNTIME_DIR={settings.xdg_runtime_dir}",
                f"XDG_CACHE_HOME={settings.xdg_cache_home}",
                f"XDG_DATA_HOME={settings.xdg_data_home}",
                "LUP_DASHBOARD_PORT=0",
                "LUP_DASHBOARD_ADDRESSES=",
                "LUP_HOST_REHEARSING=1",
            ]
            log = scratch.host.log
            started = self.processes.started(
                ["env", *variables, str(command), "host"], log
            )
            host = HostClient(layout=scratch.host, clock=self.clock, starter=Detached())
            try:
                why = self.answers.failing(host, started)
                if why is None:
                    host.stop()
            except (HostError, OSError) as failed:
                why = str(failed)
            finally:
                started.end()
            if why is None:
                return None
            said = tail(log)
            return f"{why}\nWhat it printed:\n{said}" if said else why


class Standing(Model):
    """What a switch leaves, to go back to."""

    link: Path | None
    """What the repository's link names, as it names it; none where it names nothing."""
    kept: Kept | None
    """The copy's record; none where it has none, as one from before copies were kept."""
    approval: Approval | None
    command: Path | None
    """The command the service runs from, its links followed: the person's own,
    which at the first switch is uv's install rather than a copy of the repository's."""
    ran: bool
    """Whether a service answered."""


class Switched(Model):
    """The copy answers, as the service and the dashboard, on the real state."""

    kind: Literal["switched"] = "switched"
    kept: Kept
    ran: bool
    """Whether a service ran before, which this one took over from."""
    snapshot: Snapshot | None
    """The ledger as the copy before left it; none where there was none, or none
    could be taken and going back mattered more."""
    restored: Restored | None = None
    """The snapshot the ledger was restored from, where it was asked for."""
    took: timedelta
    """How long the switch took, from the first step to it answering."""

    def report(self) -> str:
        """Say what runs."""
        moved = "restarted" if self.ran else "started"
        said = (
            f"The host service {moved} on `lup-dev` from {self.kept.commit}, in "
            f"{self.took.total_seconds():.1f} s: it and the dashboard answer."
        )
        return said if self.restored is None else f"{said} {self.restored.said()}"


class Stayed(Model):
    """Nothing moved: the copy didn't answer on a state of its own, or what's running wouldn't let the switch begin."""

    kind: Literal["stayed"] = "stayed"
    kept: Kept
    why: str
    tried: bool = True
    """Whether the copy ran, on a state of its own."""

    def report(self) -> str:
        """Say what stayed, and why."""
        how = (
            "didn't answer when tried on a copy of your state"
            if self.tried
            else "wasn't switched to"
        )
        return (
            f"`lup-dev` from {self.kept.commit} {how}, so nothing moved: the host "
            f"service you had stays, and so does the approval before it. Why: {self.why}"
        )


class FellBack(Model):
    """The copy didn't answer once it ran on the real state: what ran before is back."""

    kind: Literal["fell-back"] = "fell-back"
    kept: Kept
    why: str
    back: Kept | None
    """The copy gone back to, where one has a record."""
    answered: bool
    """Whether what ran before answers again."""
    restored: Restored | None = None
    """The ledger put back, where the copy moved its tables past what the one before reads."""
    log: Path

    def report(self) -> str:
        """Say what happened, what runs, and what to do where nothing does."""
        before = (
            f"`lup-dev` from {self.back.commit}"
            if self.back is not None
            else "the `lup-dev` that ran before"
        )
        back = (
            f"Switched back to {before}, which answers."
            if self.answered
            else (
                f"Switched back to {before}, which doesn't answer either: "
                "`lup-dev restore` lists the copies to try."
            )
        )
        ledger = "" if self.restored is None else f" {self.restored.said()}"
        return (
            f"`lup-dev` from {self.kept.commit} didn't answer once it ran: {self.why}. "
            f"{back}{ledger} What it printed is in {self.log}."
        )


type Switch = Switched | Stayed | FellBack
"""What a switch came to."""


class Switcher(ABC):
    """What moves the host service to a copy, and back where it doesn't answer."""

    @abstractmethod
    def to(
        self, kept: Kept, *, ledger: Snapshot | None = None, returning: bool = False
    ) -> Switch:
        """Move to the copy `kept`, restoring the snapshot `ledger` where it's given. `returning` says the operator is going back: a snapshot that can't be taken is said and doesn't stop them."""

    @abstractmethod
    def tried(self, kept: Kept) -> str | None:
        """Run the copy `kept` on a state of its own, moving nothing, and say why it doesn't answer; none where it does."""


def held_back(number: int, frame: FrameType | None) -> None:
    """Do nothing with a signal: a handler, not `SIG_IGN`, which a program started meanwhile would inherit, and the service then never hear it end."""
    del number, frame


@contextmanager
def uninterrupted() -> Generator[None]:
    """Hold back the signals that end a terminal's command while the context is open: cut short halfway, a switch leaves no service, with nobody left to start one. It's bounded: each step gives up by itself."""
    held = [signal.SIGINT, signal.SIGHUP, signal.SIGTERM]
    before = [signal.signal(each, held_back) for each in held]
    try:
        yield
    finally:
        for each, handler in zip(held, before, strict=True):
            signal.signal(each, handler)


class Tried(Model, arbitrary_types_allowed=True):
    """A copy's service started on the real state, and whether it answered."""

    started: Started | None
    why: str | None


class LedgerKept(Model):
    """What a switch did with the ledger before moving."""

    taken: Snapshot | None
    """The ledger as what ran left it; none where there's no ledger yet, or none
    could be taken and the operator is going back."""
    restored: Restored | None
    """The snapshot put back in its place, where the switch was asked to."""


class Moved(Model):
    """What a switch did before asking the copy, to undo where it doesn't answer."""

    before: Standing
    taken: Snapshot | None
    restored: Restored | None
    began: datetime


class Switching(Model, Switcher, arbitrary_types_allowed=True):
    """The host service moved between one repository's copies, on this machine."""

    layout: Layout
    host: HostClient
    answers: Answers
    processes: Processes
    clock: Clock
    commands: Callable[[], Path] | None = None
    """Says the directory of the person's commands, which name the copy once it
    answers; none leaves them, for `lup-dev restore`, whose are made already."""

    def snapshots(self) -> Snapshots:
        """Return the ledger's snapshots, on this machine."""
        return Snapshots(
            home=self.layout.snapshots, ledger=LedgerLayout.of(self.layout)
        )

    def copies(self, kept: Kept) -> Copies:
        """Return the copies of `kept`'s repository."""
        return Copies(layout=self.layout.judge(kept.repository))

    @override
    def to(
        self, kept: Kept, *, ledger: Snapshot | None = None, returning: bool = False
    ) -> Switch:
        """Try the copy on a state of its own where it has never answered, then hand over to it, keeping what came of it."""
        name = kept.approval.tool.name
        command = self.copies(kept).place(kept).command(name)
        why = None if kept.answered is not None else self.tried(kept)
        switch = (
            Stayed(kept=kept, why=why)
            if why is not None
            else self.handed_over(kept, command, ledger, returning=returning)
        )
        write_model(
            self.layout.host.switched,
            LastSwitch(
                commit=kept.commit,
                at=self.clock.now(),
                said=switch.report(),
                answered=isinstance(switch, Switched),
            ),
        )
        return switch

    @override
    def tried(self, kept: Kept) -> str | None:
        """Say why the copy `kept` won't answer on a state of its own; none where it does. A ledger that can't be copied, or a copy that can't start, is why too."""
        command = self.copies(kept).place(kept).command(kept.approval.tool.name)
        rehearsal = Rehearsal(
            layout=self.layout,
            answers=self.answers,
            processes=self.processes,
            clock=self.clock,
        )
        try:
            return rehearsal.failing(command)
        except (ProgramError, sqlite3.Error, OSError) as failed:
            return str(failed)

    def standing(self, kept: Kept) -> Standing:
        """Read what a switch to `kept` leaves."""
        copies = self.copies(kept)
        name = kept.approval.tool.name
        link = copies.layout.bin
        person = None if self.commands is None else self.commands() / name
        through = copies.layout.command(name)
        command = next(
            (
                each.resolve()
                for each in [person, through]
                if each is not None and each.is_file()
            ),
            None,
        )
        return Standing(
            link=link.readlink() if link.is_symlink() else None,
            kept=copies.running(),
            approval=approved(self.layout, kept.repository),
            command=command,
            ran=self.host.answers(),
        )

    def handed_over(
        self, kept: Kept, command: Path, ledger: Snapshot | None, *, returning: bool
    ) -> Switch:
        """Stop what runs, keep the ledger as it left it, move to the copy, and ask it; where it doesn't answer, everything goes back."""
        began = self.clock.now()
        with uninterrupted():
            before = self.standing(kept)
            stopped = self.stopped()
            if stopped is not None:
                return Stayed(kept=kept, why=stopped, tried=False)
            try:
                kept_ledger = self.ledger_kept(before, ledger, returning=returning)
            except (sqlite3.Error, OSError) as failed:
                self.restarted(before)
                why = f"the ledger's snapshot couldn't be taken or restored: {failed}"
                return Stayed(kept=kept, why=why, tried=False)
            self.moved(kept)
            moved = Moved(
                before=before,
                taken=kept_ledger.taken,
                restored=kept_ledger.restored,
                began=began,
            )
            asked = self.started_and_asked(command)
            if asked.why is None:
                return self.settled(kept, moved)
            return self.fell_back(kept, moved, asked)

    def ledger_kept(
        self, before: Standing, ledger: Snapshot | None, *, returning: bool
    ) -> LedgerKept:
        """Keep the ledger as what ran left it, and restore `ledger` where it's given. A snapshot that can't be taken raises, unless the operator is `returning`, whose way back it must not stop."""
        snapshots = self.snapshots()
        left = before.kept
        try:
            taken = snapshots.taken(
                self.clock.now(),
                None if left is None else left.name,
                None if left is None else left.commit,
            )
        except sqlite3.Error, OSError:
            if not returning:
                raise
            taken = None
        now = self.clock.now()
        restored = None if ledger is None else snapshots.restored(ledger, now)
        return LedgerKept(taken=taken, restored=restored)

    def stopped(self) -> str | None:
        """Stop the service where one runs, ending it where it doesn't answer or doesn't exit; say why it couldn't be, none where it's gone."""
        try:
            self.host.stop()
        except HostError, OSError:
            pass
        return self.processes.killed(self.host.layout)

    def moved(self, kept: Kept) -> None:
        """Have the repository's link name `kept`, with what was approved with it."""
        copies = self.copies(kept)
        copies.switch(copies.place(kept))
        write_model(self.layout.approved(kept.repository), kept.approval)

    def started_and_asked(self, command: Path) -> Tried:
        """Start the service from `command`, and ask it."""
        try:
            started = self.processes.started(
                [str(command), "host"], self.host.layout.log
            )
        except ProgramError as unstarted:
            return Tried(started=None, why=str(unstarted))
        return Tried(started=started, why=self.answers.failing(self.host, started))

    def settled(self, kept: Kept, moved: Moved) -> Switched:
        """Keep that the copy answered, and have the person's commands name it. What `lup-dev restore` runs from is what ran before, where it has answered and was answering when it was stopped, so a second copy stands behind this one; else this copy, which just answered: what's left behind a dead service may be why it died."""
        copies = self.copies(kept)
        answering = kept.model_copy(update={"answered": self.clock.now()})
        copies.recorded(answering)
        left = moved.before.kept
        good = left is not None and left.answered is not None and moved.before.ran
        copies.back(copies.place(left if left is not None and good else kept))
        if self.commands is not None:
            copies.commands(
                self.commands(), kept.approval.tool.name, self.layout.host_copies
            )
        self.snapshots().pruned([each.name for each in copies.kept()])
        return Switched(
            kept=answering,
            ran=moved.before.ran,
            snapshot=moved.taken,
            restored=moved.restored,
            took=self.clock.now() - moved.began,
        )

    def fell_back(self, kept: Kept, moved: Moved, tried: Tried) -> FellBack:
        """Undo the switch: end the copy, put the link, the approval and the ledger back, and start what ran before."""
        if tried.started is not None:
            tried.started.end()
        self.stopped()
        before = moved.before
        link = self.copies(kept).layout.bin
        if before.link is not None:
            linked(link, before.link)
        if before.link is None and link.is_symlink():
            link.unlink()
        approval = self.layout.approved(kept.repository)
        if before.approval is not None:
            write_model(approval, before.approval)
        if before.approval is None:
            approval.unlink(missing_ok=True)
        restored = self.ledger_back(moved)
        return FellBack(
            kept=kept,
            why=tried.why or "",
            back=before.kept,
            answered=self.restarted(before) is None,
            restored=restored,
            log=self.host.layout.log,
        )

    def ledger_back(self, moved: Moved) -> Restored | None:
        """Put the ledger back as what ran before left it, where this switch restored another, or the copy moved its tables past what the one before reads: it was up for moments, so it costs them alone. Otherwise leave it, since nothing's the matter with it."""
        if moved.taken is None:
            return None
        ledger = written(LedgerLayout.of(self.layout).database)
        beyond = ledger is not None and ledger.tables > moved.taken.written.tables
        if moved.restored is None and not beyond:
            return None
        return self.snapshots().restored(moved.taken, self.clock.now())

    def restarted(self, before: Standing) -> str | None:
        """Start again what ran before, and say why it doesn't answer; none where it does. There's nothing to start at a repository's first copy, which is why."""
        if before.command is None:
            return "there's no copy to go back to"
        return self.started_and_asked(before.command).why


def host_starter(layout: Layout) -> Detached:
    """Return what starts the host service: the copy the repository's link names where there's one, so a command run from a copy a switch left starts the one approved; else the running `lup_dev`, on a machine with no copies yet."""
    command = layout.host_copies / "bin" / "lup-dev"
    return Detached(command=[str(command), "host"]) if command.is_file() else Detached()


def host_copies(layout: Layout) -> Copies | None:
    """Return the copies of the repository the host service runs from, lup's own; none on a machine with none yet."""
    if not layout.host_copies.is_dir():
        return None
    return Copies(layout=JudgeLayout(home=layout.host_copies.resolve()))


def own_repository(copies: Copies) -> Path | None:
    """Return the repository whose copies `copies` are, lup's own, as what's kept of the copy running says; else of the latest kept; none where none is."""
    kept = copies.running() or next(iter(copies.history()), None)
    return None if kept is None else kept.repository


def needs_ledger(snapshots: Snapshots, copy: str) -> Snapshot | None:
    """Return the snapshot the copy `copy` would need put back, since it left the ledger at an earlier version of its tables than it stands at; none where it can read it, or left none to say otherwise."""
    left = snapshots.left_by(copy)
    now = written(snapshots.ledger.database)
    if left is None or now is None or now.tables <= left.written.tables:
        return None
    return left


def found(copies: list[Kept], commit: str) -> Kept:
    """Return the one copy of `copies` whose commit is `commit`, or starts with it; raise `HostError` where none or several are, saying so."""
    matching = [each for each in copies if each.commit.startswith(commit)]
    match matching:
        case [one]:
            return one
        case []:
            message = (
                f"no copy kept is of a commit starting {commit}: `lup-dev restore` "
                "lists them"
            )
            raise HostError(message)
        case _:
            named = ", ".join(each.commit for each in matching)
            message = f"{commit} starts more than one commit kept: {named}"
            raise HostError(message)


class ListCopies(Request, reads=False):
    """List the copies of `lup-dev` kept: the operator's alone, since it's how the host service is moved. Answered for lup's own repository, the one the service runs from."""

    kind: Literal["copies"] = "copies"


class CopyListed(Model):
    """One copy, as a page shows it."""

    commit: str
    subject: str = ""
    approved: datetime
    answered: datetime | None = None
    """When it last answered; none for one built and never run."""
    running: bool = False
    """Whether the host service runs it."""
    tables: int | None = None
    """The version of the ledger's tables it left, where it left a snapshot."""


class CopiesListed(Reply):
    """The copies kept, the last to run first, and the ledger's tables as they stand."""

    kind: Literal["copies-listed"] = "copies-listed"
    copies: list[CopyListed]
    tables: int | None = None
    last: LastSwitch | None = None
    """What came of the last switch, for a page that asked for it to say."""
    trial: TrialListed | None = None
    """What's on trial, to pick from; none where the repository computes no
    running branch."""


def last_switch(layout: Layout) -> LastSwitch | None:
    """Return what came of the last switch; none where nothing has switched, or what it left doesn't read, as a later lup's might not."""
    try:
        return read_model(layout.host.switched, LastSwitch)
    except ValidationError:
        return None


def listed_copies(layout: Layout) -> CopiesListed:
    """List the copies kept for the repository the host service runs from; none on a machine with none yet."""
    ledger = LedgerLayout.of(layout)
    now = written(ledger.database)
    tables = None if now is None else now.tables
    last = last_switch(layout)
    copies = host_copies(layout)
    if copies is None:
        return CopiesListed(copies=[], tables=tables, last=last)
    snapshots = Snapshots(home=layout.snapshots, ledger=ledger)
    running = copies.current()

    def listed(kept: Kept) -> CopyListed:
        left = snapshots.left_by(kept.name)
        return CopyListed(
            commit=kept.commit,
            subject=kept.subject,
            approved=kept.approval.time,
            answered=kept.answered,
            running=running is not None and running.name == kept.name,
            tables=None if left is None else left.written.tables,
        )

    kept = copies.kept()
    repository = own_repository(copies)
    return CopiesListed(
        copies=[listed(each) for each in kept],
        tables=tables,
        last=last,
        trial=None
        if repository is None
        else trial_listed(layout, repository, [each.commit for each in kept]),
    )


class CopiesAnswering(Model, Handler[ListCopies]):
    """Answers `ListCopies`, from lup's data, as this machine places it."""

    layout: Layout

    @override
    def request(self) -> type[ListCopies]:
        return ListCopies

    @override
    async def answer(self, request: ListCopies) -> Reply:
        return listed_copies(self.layout)


class CopySwitch(Model, Handler[SwitchCopy], arbitrary_types_allowed=True):
    """Answers `SwitchCopy`: checks what can be refused while this service still runs, then starts `lup-dev restore` in a session of its own, since it stops this service: from the copy going to where that has answered, whose code has worked, else from the one running, which is answering this."""

    layout: Layout
    start: Callable[[CopyLayout, str], None]
    """Starts the copy's `lup-dev restore`, given where it's installed and the
    commit; a test gives its own."""

    @override
    def request(self) -> type[SwitchCopy]:
        return SwitchCopy

    @override
    async def answer(self, request: SwitchCopy) -> Reply:
        copies = host_copies(self.layout)
        if copies is None:
            message = "no copy of `lup-dev` is kept on this machine yet"
            raise HostError(message)
        kept = found(copies.kept(), request.commit)
        current = copies.current()
        if current is not None and current.name == kept.name:
            message = f"the host service runs {kept.commit} already"
            raise HostError(message)
        snapshots = Snapshots(
            home=self.layout.snapshots, ledger=LedgerLayout.of(self.layout)
        )
        if needs_ledger(snapshots, kept.name) is not None:
            message = (
                f"{kept.commit} can't read the ledger as it stands, and restoring what "
                "it left loses what happened since: `lup-dev restore "
                f"{kept.commit} --ledger`, in a terminal, says how much, and asks"
            )
            raise HostError(message)
        last = last_switch(self.layout)
        running = copies.running()
        from_copy = kept if kept.answered is not None or running is None else running
        self.start(copies.place(from_copy), kept.commit)
        return CopySwitching(commit=kept.commit, log=self.layout.host.log, last=last)


def restore_detached(layout: Layout) -> Callable[[CopyLayout, str], None]:
    """Return what starts a copy's `lup-dev restore` in a session of its own, its output in the service's log."""

    def start(copy: CopyLayout, commit: str) -> None:
        detached(copy.command("lup-dev"), "restore", commit, log=layout.host.log)

    return start
