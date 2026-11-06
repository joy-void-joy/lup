"""Moving the host service between copies of `lup-dev`, and back where one doesn't answer (`lup_dev/switching.py`), with the programs and pages standing in; the ledger, the links and the records are real."""

import asyncio
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from pydantic import Field

from lup.programs import ProgramMissingError, detached
from lup.types import Model
from lup_dev.approval import Approval, WorkspaceTool, approved
from lup_dev.copies import Copies, Kept
from lup_dev.host.client import Detached, HostClient
from lup_dev.host.dashboard import DashboardShown
from lup_dev.host.protocol import HostError, Listed, ListLaunches, Reply, Request
from lup_dev.layout import CopyLayout, HostLayout, Layout
from lup_dev.snapshots import Snapshots, written
from lup_dev.stored import write_model
from lup_dev.switching import (
    Answers,
    CopiesAnswering,
    CopiesListed,
    CopySwitch,
    CopySwitching,
    FellBack,
    Fetched,
    LastSwitch,
    ListCopies,
    Pages,
    Processes,
    Programs,
    Serving,
    Started,
    Stayed,
    SwitchCopy,
    Switched,
    Switching,
    assets,
    found,
    host_starter,
    last_switch,
    listed_copies,
    needs_ledger,
    uninterrupted,
)
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import FakeClock

AT = datetime(2026, 11, 6, 12, tzinfo=UTC)
TOOL = WorkspaceTool(name="lup-dev", package=Path("packages/lup-dev"), members=[])
REPOSITORY = Path("/repo.git")
LISTED = Listed(launches=[])
ADDRESS = "http://127.0.0.1:8766/#token=the-token"
PAGE = '<html><script src="/a.js"></script><link rel="stylesheet" href="/b.css"></html>'


class Asked(HostClient):
    """The host service's client, answering each kind as it's told."""

    replies: dict[str, list[Reply | Exception]] = Field(default_factory=dict)
    asked: list[str] = Field(default_factory=list)

    def ask[R: Reply](self, request: Request, reply: type[R]) -> R:
        self.asked.append(request.kind)
        replies = self.replies[request.kind]
        given = replies.pop(0) if len(replies) > 1 else replies[0]
        if isinstance(given, Exception):
            raise given
        assert isinstance(given, reply)
        return given


class Served(Pages):
    """The dashboard's pages, each address's as it's told; every one served by default."""

    def __init__(self, **special: Fetched) -> None:
        self.special = special
        self.fetches: list[str] = []
        self.tokens: list[str | None] = []

    @override
    def fetched(
        self, url: str, *, token: str | None = None, posted: str | None = None
    ) -> Fetched:
        path = url.removeprefix("http://127.0.0.1:8766")
        self.fetches.append(path)
        self.tokens.append(token)
        if path in self.special:
            return self.special[path]
        match path:
            case "/":
                return Fetched(status=200, kind="text/html", body=PAGE.encode())
            case "/api/ask":
                assert posted == ListLaunches().model_dump_json()
                return Fetched(status=200, body=b'{"kind":"listed"}')
            case _:
                return Fetched(status=200, kind="text/plain", body=b"x")


def asking(
    tmp_path: Path,
    clock: FakeClock,
    *,
    listing: list[Reply | Exception] | None = None,
    dashboard: list[Reply | Exception] | None = None,
) -> Asked:
    return Asked(
        layout=HostLayout(sockets=tmp_path / "run", state=tmp_path / "state"),
        clock=clock,
        starter=Detached(),
        replies={
            "list": listing or [LISTED],
            "dashboard": dashboard or [DashboardShown(address=ADDRESS)],
        },
    )


class NeverEnded(Started):
    @override
    def ended(self) -> bool:
        return False

    @override
    def end(self) -> None:
        pass


class AlreadyEnded(NeverEnded):
    @override
    def ended(self) -> bool:
        return True


def test_it_answers_when_the_service_the_page_and_the_api_all_serve(
    tmp_path: Path, clock: FakeClock
) -> None:
    pages = Served()
    host = asking(tmp_path, clock)
    serving = Serving(clock=clock, pages=pages)
    assert serving.failing(host, NeverEnded()) is None
    assert host.asked == ["list", "dashboard"]
    assert pages.fetches == ["/", "/a.js", "/b.css", "/api/ask"]
    assert pages.tokens[-1] == "the-token"


def test_a_connection_a_stuck_service_accepts_isnt_an_answer(
    tmp_path: Path, clock: FakeClock
) -> None:
    host = asking(tmp_path, clock, listing=[TimeoutError("timed out")])
    serving = Serving(clock=clock, pages=Served(), patience=timedelta(seconds=1))
    why = serving.failing(host, NeverEnded())
    assert why is not None
    assert "the host service doesn't answer: timed out" in why
    assert clock.slept >= 1


def test_it_waits_while_the_service_comes_up(tmp_path: Path, clock: FakeClock) -> None:
    gone = HostError("no host service answers")
    host = asking(tmp_path, clock, listing=[gone, gone, LISTED])
    serving = Serving(clock=clock, pages=Served())
    assert serving.failing(host, NeverEnded()) is None
    assert clock.slept > 0


def test_a_service_that_ended_is_not_waited_on(
    tmp_path: Path, clock: FakeClock
) -> None:
    host = asking(tmp_path, clock, listing=[HostError("no host service answers")])
    why = Serving(clock=clock, pages=Served()).failing(host, AlreadyEnded())
    assert why is not None
    assert why.startswith("its service ended as it started")
    assert clock.slept == 0


@pytest.mark.parametrize(
    ("special", "said"),
    [
        (
            {"/": Fetched(status=500, kind="text/plain", body=b"x")},
            "doesn't serve its page",
        ),
        ({"/": Fetched(status=200, kind="text/html")}, "doesn't serve its page"),
        ({"/": Fetched(status=200, kind="application/json", body=b"{}")}, "its page"),
        ({"/a.js": Fetched(status=404, body=b"no")}, "names /a.js, unserved"),
        ({"/b.css": Fetched(status=200)}, "names /b.css, unserved"),
        ({"/api/ask": Fetched(status=401)}, "API doesn't relay"),
        ({"/api/ask": Fetched(status=503, body=b"x")}, "API doesn't relay"),
        (
            {"/api/ask": Fetched(status=200, body=b'{"kind":"refused"}')},
            "doesn't relay",
        ),
    ],
)
def test_what_a_page_needs_that_isnt_served_is_said_at_once(
    tmp_path: Path, clock: FakeClock, special: dict[str, Fetched], said: str
) -> None:
    host = asking(tmp_path, clock)
    why = Serving(clock=clock, pages=Served(**special)).failing(host, NeverEnded())
    assert why is not None
    assert said in why
    assert clock.slept == 0


def test_a_dashboard_that_wont_start_is_said_before_the_service_s_patience_is_out(
    tmp_path: Path, clock: FakeClock
) -> None:
    host = asking(
        tmp_path, clock, dashboard=[HostError("ended with status 1 before listening")]
    )
    serving = Serving(
        clock=clock,
        pages=Served(),
        patience=timedelta(minutes=1),
        settling=timedelta(seconds=10),
    )
    why = serving.failing(host, NeverEnded())
    assert why is not None
    assert "its dashboard doesn't: ended with status 1" in why
    assert 10 <= clock.slept < 11


def test_a_dashboard_refused_for_what_s_going_away_is_asked_again(
    tmp_path: Path, clock: FakeClock
) -> None:
    held = HostError("as on a port another program holds")
    host = asking(
        tmp_path,
        clock,
        dashboard=[held, held, DashboardShown(address=ADDRESS)],
    )
    assert Serving(clock=clock, pages=Served()).failing(host, NeverEnded()) is None


def test_it_waits_while_the_dashboard_s_server_comes_up(
    tmp_path: Path, clock: FakeClock
) -> None:
    host = asking(tmp_path, clock)
    pages = Served(**{"/": Fetched(error="connection refused")})
    answering = Serving(clock=clock, pages=pages, patience=timedelta(seconds=1))
    why = answering.failing(host, NeverEnded())
    assert why is not None
    assert why.startswith("after 0:00:01, ")
    assert "connection refused" in why
    assert clock.slept >= 1


def test_a_page_s_scripts_and_stylesheets_are_what_it_names() -> None:
    page = (
        '<script type="module" crossorigin src="/assets/i.js"></script>'
        '<link rel="modulepreload" href="/assets/m.js">'
        '<link rel="stylesheet" crossorigin href="/assets/s.css">'
        '<link rel="icon" href="/favicon.ico"><script>inline()</script>'
    )
    assert assets(page) == ["/assets/i.js", "/assets/m.js", "/assets/s.css"]


class Run(Model, arbitrary_types_allowed=True):
    """One service started: its command, and the handle's end."""

    command: list[str]
    log: Path


class Fake(Started):
    def __init__(self, processes: Stood, command: list[str]) -> None:
        self.processes = processes
        self.command = command

    @override
    def ended(self) -> bool:
        return False

    @override
    def end(self) -> None:
        self.processes.steps.append(f"end {Path(self.command[-2]).parent.parent.name}")


class Stood(Processes):
    """The programs, standing in: each start and end said in `steps`, with `on_start` run for what a start does, and whatever `killing` says of a kill."""

    def __init__(self, steps: list[str]) -> None:
        self.steps = steps
        self.runs: list[Run] = []
        self.on_start: Callable[[list[str]], None] = lambda command: None
        self.killing: str | None = None
        self.unstartable: list[str] = []

    @override
    def started(self, command: list[str], log: Path) -> Started:
        self.runs.append(Run(command=command, log=log))
        copy = Path(command[-2]).parent.parent.name
        rehearsing = command[0] == "env"
        self.steps.append(f"rehearse {copy}" if rehearsing else f"start {copy}")
        if copy in self.unstartable:
            message = f"`{copy}` can't be started"
            raise ProgramMissingError(message)
        self.on_start(command)
        return Fake(self, command)

    @override
    def killed(self, layout: HostLayout) -> str | None:
        return self.killing


class Told(Answers):
    """Says of each start whether it answered, in the order they're asked."""

    def __init__(self, steps: list[str]) -> None:
        self.steps = steps
        self.fails: list[str | None] = []
        self.hosts: list[HostClient] = []

    @override
    def failing(self, host: HostClient, started: Started | None) -> str | None:
        self.hosts.append(host)
        self.steps.append("asked")
        return self.fails.pop(0) if self.fails else None


class Host(HostClient):
    """The host service's client, its stop said, with no service behind."""

    running: bool = True
    processes: Stood
    stopping: Exception | None = None

    @override
    def answers(self) -> bool:
        return self.running

    @override
    def stop(self) -> bool:
        self.processes.steps.append("stop")
        if self.stopping is not None:
            raise self.stopping
        return self.running


class Machine:
    """A machine's real places, its copies, its ledger, with the programs standing in."""

    def __init__(self, tmp_path: Path, clock: FakeClock) -> None:
        self.clock = clock
        self.layout = Layout(
            state=tmp_path / "state",
            runtime=tmp_path / "run",
            data=tmp_path / "data",
            cache=tmp_path / "cache",
            config=tmp_path / "config",
        )
        self.steps: list[str] = []
        self.processes = Stood(self.steps)
        self.told = Told(self.steps)
        self.host = Host(
            layout=self.layout.host,
            clock=clock,
            starter=Detached(),
            processes=self.processes,
        )
        self.commands = tmp_path / "bin"
        self.switching = Switching(
            layout=self.layout,
            host=self.host,
            answers=self.told,
            processes=self.processes,
            clock=clock,
            commands=lambda: self.commands,
        )
        self.copies = Copies(layout=self.layout.judge(REPOSITORY))
        self.ledger = LedgerLayout.of(self.layout)
        Ledger.opened(self.ledger).close()

    def copy(self, name: str, *, answered: bool = False) -> Kept:
        """A copy installed, and its record."""
        place = self.copies.layout.named(name)
        place.bin.mkdir(parents=True)
        place.command("lup-dev").write_text("#!/bin/sh\n")
        kept = Kept(
            name=name,
            repository=REPOSITORY,
            approval=Approval(
                commit=f"{name}-commit",
                fingerprint=f"zone of {name}",
                paths=[],
                tool=TOOL,
                time=AT,
            ),
            answered=AT if answered else None,
        )
        self.copies.recorded(kept)
        return kept

    def running(self, name: str) -> Kept:
        """A copy that has answered, which the link names and whose approval stands."""
        kept = self.copy(name, answered=True)
        self.copies.switch(self.copies.place(kept))
        write_model(self.layout.approved(REPOSITORY), kept.approval)
        return kept

    def snapshots(self) -> Snapshots:
        return Snapshots(home=self.layout.snapshots, ledger=self.ledger)

    def linked(self) -> str | None:
        current = self.copies.current()
        return None if current is None else current.name

    def approved(self) -> str | None:
        approval = approved(self.layout, REPOSITORY)
        return None if approval is None else approval.commit

    def tables(self) -> int | None:
        now = written(self.ledger.database)
        return None if now is None else now.tables


@pytest.fixture
def machine(tmp_path: Path, clock: FakeClock) -> Machine:
    return Machine(tmp_path, clock)


def test_a_copy_that_never_answered_is_tried_apart_and_the_service_stays_until_it_answers(
    machine: Machine,
) -> None:
    machine.running("old")
    switch = machine.switching.to(machine.copy("new"))
    assert isinstance(switch, Switched)
    assert machine.steps == [
        "rehearse new",
        "asked",
        "end new",
        "stop",
        "start new",
        "asked",
    ]


def test_a_copy_that_doesnt_answer_apart_moves_nothing_and_stops_nothing(
    machine: Machine,
) -> None:
    machine.running("old")
    machine.told.fails = ["the page is blank"]
    switch = machine.switching.to(machine.copy("new"))
    assert isinstance(switch, Stayed)
    assert "the page is blank" in switch.report()
    assert "tried on a copy of your state" in switch.report()
    assert machine.steps == ["rehearse new", "asked", "end new"]
    assert machine.linked() == "old"
    assert machine.approved() == "old-commit"
    assert machine.snapshots().all() == []


def test_a_copy_that_cant_start_apart_moves_nothing(machine: Machine) -> None:
    machine.running("old")
    machine.processes.unstartable = ["new"]
    switch = machine.switching.to(machine.copy("new"))
    assert isinstance(switch, Stayed)
    assert "can't be started" in switch.why
    assert "stop" not in machine.steps
    assert machine.linked() == "old"


def test_the_try_apart_runs_on_a_state_of_its_own_with_a_copy_of_the_ledger(
    machine: Machine,
) -> None:
    machine.running("old")
    seen: list[list[str]] = []
    copied: list[int | None] = []

    def started(command: list[str]) -> None:
        if command[0] == "env":
            seen.append(command)
            state = next(
                each.split("=", 1)[1]
                for each in command
                if each.startswith("XDG_STATE_HOME=")
            )
            database = LedgerLayout(home=Path(state) / "lup" / "ledger").database
            tables = written(database)
            copied.append(None if tables is None else tables.tables)

    machine.processes.on_start = started
    machine.switching.to(machine.copy("new"))

    [command] = seen
    variables = dict(each.split("=", 1) for each in command[1:-2])
    assert variables["LUP_DASHBOARD_PORT"] == "0"
    assert variables["LUP_DASHBOARD_ADDRESSES"] == ""
    assert variables["LUP_HOST_REHEARSING"] == "1"
    for each in [
        "XDG_STATE_HOME",
        "XDG_RUNTIME_DIR",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
    ]:
        assert not Path(variables[each]).exists(), "its state is removed after"
    assert not Path(variables["XDG_STATE_HOME"]).is_relative_to(machine.ledger.home)
    assert command[-1] == "host"
    assert copied == [machine.tables()]
    first_host = machine.told.hosts[0]
    assert first_host.layout != machine.layout.host


def test_a_try_asked_for_runs_the_copy_apart_whichever_it_is_and_moves_nothing(
    machine: Machine,
) -> None:
    old = machine.running("old")
    machine.told.fails = ["no"]
    assert machine.switching.tried(old) == "no"
    assert machine.steps == ["rehearse old", "asked", "end old"]
    assert machine.linked() == "old"
    assert last_switch(machine.layout) is None


def test_a_copy_that_has_answered_isnt_tried_again_so_flipping_is_quick(
    machine: Machine,
) -> None:
    machine.running("old")
    switch = machine.switching.to(machine.copy("before", answered=True))
    assert isinstance(switch, Switched)
    assert machine.steps == ["stop", "start before", "asked"]


def test_once_it_answers_it_s_kept_with_the_person_s_commands_and_the_way_back(
    machine: Machine,
) -> None:
    old = machine.running("old")
    new = machine.copy("new")
    machine.clock.time = AT + timedelta(hours=1)
    switch = machine.switching.to(new)
    assert isinstance(switch, Switched)
    assert switch.ran
    assert switch.kept.answered == AT + timedelta(hours=1)
    assert machine.linked() == "new"
    assert machine.approved() == "new-commit"
    assert machine.copies.of("new-commit") == switch.kept
    assert (
        machine.copies.layout.back.resolve().parent
        == machine.copies.place(old).home.resolve()
    )
    assert (machine.commands / "lup-dev").is_file()
    assert machine.layout.host_copies.resolve() == machine.copies.layout.home.resolve()
    assert switch.snapshot is not None
    assert switch.snapshot.left == "old"
    assert switch.snapshot.commit == "old-commit"
    assert machine.snapshots().left_by("old") == switch.snapshot
    last = last_switch(machine.layout)
    assert last is not None
    assert last.answered
    assert last.commit == "new-commit"
    assert last.said == switch.report()


def test_a_copy_that_doesnt_answer_once_it_runs_is_ended_and_all_goes_back(
    machine: Machine,
) -> None:
    machine.running("old")
    machine.told.fails = [None, "the dashboard doesn't serve its page"]
    switch = machine.switching.to(machine.copy("new"))
    assert isinstance(switch, FellBack)
    assert switch.answered
    assert switch.back is not None
    assert switch.back.name == "old"
    assert machine.steps == [
        "rehearse new",
        "asked",
        "end new",
        "stop",
        "start new",
        "asked",
        "end new",
        "stop",
        "start old",
        "asked",
    ]
    assert machine.linked() == "old"
    assert machine.approved() == "old-commit"
    assert not (machine.commands / "lup-dev").exists(), "they name it once it answers"
    assert switch.restored is None
    said = switch.report()
    assert "the dashboard doesn't serve its page" in said
    assert "Switched back to `lup-dev` from old-commit, which answers." in said
    last = last_switch(machine.layout)
    assert last is not None
    assert not last.answered


def test_the_ledger_stays_where_the_copy_didnt_move_its_tables(
    machine: Machine,
) -> None:
    machine.running("old")
    machine.told.fails = [None, "no"]
    switch = machine.switching.to(machine.copy("new"))
    assert isinstance(switch, FellBack)
    assert switch.restored is None
    assert written(machine.ledger.database) is not None


def moved_tables(machine: Machine) -> Callable[[list[str]], None]:
    """What a copy converting the ledger does as it starts on the real state."""

    def started(command: list[str]) -> None:
        if command[0] != "env" and Path(command[0]).parent.parent.name == "new":
            connection = sqlite3.connect(machine.ledger.database)
            connection.execute("PRAGMA user_version = 3")
            connection.close()

    return started


def test_the_ledger_goes_back_where_the_copy_moved_its_tables_past_the_one_before(
    machine: Machine,
) -> None:
    machine.running("old")
    machine.told.fails = [None, "no"]
    machine.processes.on_start = moved_tables(machine)
    switch = machine.switching.to(machine.copy("new"))
    assert isinstance(switch, FellBack)
    assert switch.restored is not None
    assert machine.tables() == 2
    assert "The ledger is back as it was" in switch.report()
    assert switch.restored.aside.is_dir()


def test_neither_answering_is_said_with_where_to_go(machine: Machine) -> None:
    machine.running("old")
    machine.told.fails = [None, "no", "nor this"]
    switch = machine.switching.to(machine.copy("new"))
    assert isinstance(switch, FellBack)
    assert not switch.answered
    assert "doesn't answer either" in switch.report()
    assert "`lup-dev restore`" in switch.report()
    assert machine.linked() == "old"


def test_a_copy_that_cant_start_once_it_runs_falls_back(machine: Machine) -> None:
    machine.running("old")
    machine.told.fails = [None]
    machine.processes.unstartable = []

    def unstartable(command: list[str]) -> None:
        if command[0] != "env" and Path(command[0]).parent.parent.name == "new":
            message = "the copy's command is gone"
            raise ProgramMissingError(message)

    machine.processes.on_start = unstartable
    switch = machine.switching.to(machine.copy("new"))
    assert isinstance(switch, FellBack)
    assert "the copy's command is gone" in switch.why
    assert machine.linked() == "old"


def test_a_service_that_wont_stop_and_wont_be_ended_moves_nothing(
    machine: Machine,
) -> None:
    machine.running("old")
    machine.host = machine.host.model_copy(update={"stopping": TimeoutError("stuck")})
    switching = machine.switching.model_copy(update={"host": machine.host})
    machine.processes.killing = "process 7 wouldn't end"
    switch = switching.to(machine.copy("before", answered=True))
    assert isinstance(switch, Stayed)
    assert "process 7 wouldn't end" in switch.report()
    assert not switch.tried
    assert machine.linked() == "old"
    assert machine.approved() == "old-commit"


def test_a_service_that_wont_answer_its_stop_is_ended_and_the_switch_goes_on(
    machine: Machine,
) -> None:
    machine.running("old")
    machine.host = machine.host.model_copy(update={"stopping": TimeoutError("stuck")})
    switching = machine.switching.model_copy(update={"host": machine.host})
    switch = switching.to(machine.copy("before", answered=True))
    assert isinstance(switch, Switched)


def test_a_snapshot_that_cant_be_taken_stops_a_switch_and_restarts_what_ran(
    machine: Machine, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine.running("old")

    def unwritable(*arguments: object, **named: object) -> None:
        message = "no space left on device"
        raise OSError(message)

    monkeypatch.setattr(Snapshots, "taken", unwritable)
    switch = machine.switching.to(machine.copy("before", answered=True))
    assert isinstance(switch, Stayed)
    assert "no space left on device" in switch.report()
    assert machine.steps == ["stop", "start old", "asked"]
    assert machine.linked() == "old"


def test_a_snapshot_that_cant_be_taken_doesnt_stop_the_way_back(
    machine: Machine, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine.running("old")

    def unwritable(*arguments: object, **named: object) -> None:
        message = "no space left on device"
        raise OSError(message)

    monkeypatch.setattr(Snapshots, "taken", unwritable)
    switch = machine.switching.to(machine.copy("before", answered=True), returning=True)
    assert isinstance(switch, Switched)
    assert switch.snapshot is None
    assert machine.linked() == "before"


def test_a_copy_that_was_answering_stands_behind_the_one_gone_to(
    machine: Machine,
) -> None:
    left = machine.running("left")
    switch = machine.switching.to(machine.copy("before", answered=True), returning=True)
    assert isinstance(switch, Switched)
    assert (
        machine.copies.layout.back.resolve().parent
        == machine.copies.place(left).home.resolve()
    )


def test_a_dead_service_isnt_what_restore_runs_from_after_going_back(
    machine: Machine,
) -> None:
    machine.running("dead")
    machine.host = machine.host.model_copy(update={"running": False})
    switching = machine.switching.model_copy(update={"host": machine.host})
    before = machine.copy("before", answered=True)
    switch = switching.to(before, returning=True)
    assert isinstance(switch, Switched)
    assert (
        machine.copies.layout.back.resolve().parent
        == machine.copies.place(before).home.resolve()
    )


def test_a_service_that_didnt_answer_isnt_what_restore_runs_from(
    machine: Machine,
) -> None:
    machine.running("dead")
    machine.host = machine.host.model_copy(update={"running": False})
    switching = machine.switching.model_copy(update={"host": machine.host})
    new = machine.copy("new")
    switch = switching.to(new)
    assert isinstance(switch, Switched)
    assert not switch.ran
    assert "started on" in switch.report()
    assert (
        machine.copies.layout.back.resolve().parent
        == machine.copies.place(new).home.resolve()
    )


def test_the_first_copy_has_nothing_to_go_back_to(machine: Machine) -> None:
    machine.told.fails = [None, "no"]
    switch = machine.switching.to(machine.copy("first"))
    assert isinstance(switch, FellBack)
    assert not switch.answered
    assert switch.back is None
    assert machine.linked() is None
    assert machine.approved() is None
    assert "the `lup-dev` that ran before" in switch.report()


def test_the_first_switch_goes_back_to_what_uv_installed(machine: Machine) -> None:
    uvs = machine.commands.parent / "uv-tools" / "lup-dev" / "bin" / "lup-dev"
    uvs.parent.mkdir(parents=True)
    uvs.write_text("#!/bin/sh\n")
    machine.commands.mkdir()
    (machine.commands / "lup-dev").symlink_to(uvs)
    from_before = machine.copies.layout.named("from-before")
    from_before.bin.mkdir(parents=True)
    from_before.command("lup-dev").write_text("#!/bin/sh\n")
    machine.copies.switch(from_before)
    write_model(machine.layout.approved(REPOSITORY), machine.copy("kept").approval)
    machine.told.fails = [None, "no"]
    switch = machine.switching.to(machine.copy("new"))
    assert isinstance(switch, FellBack)
    assert machine.processes.runs[-1].command == [str(uvs.resolve()), "host"]
    assert machine.linked() == "from-before"
    assert (machine.commands / "lup-dev").is_symlink(), (
        "uv's link stays until one answers"
    )


def test_a_snapshot_asked_for_is_restored_and_goes_back_if_the_copy_fails(
    machine: Machine,
) -> None:
    machine.running("old")
    before = machine.copy("before", answered=True)
    ledger = machine.snapshots().taken(AT, "before", "before-commit")
    assert ledger is not None
    machine.told.fails = ["no"]
    switch = machine.switching.to(before, ledger=ledger, returning=True)
    assert isinstance(switch, FellBack)
    assert switch.restored is not None
    assert machine.linked() == "old"


def test_a_snapshot_asked_for_is_said_in_what_came_of_it(machine: Machine) -> None:
    machine.running("old")
    before = machine.copy("before", answered=True)
    ledger = machine.snapshots().taken(AT, "before", "before-commit")
    assert ledger is not None
    switch = machine.switching.to(before, ledger=ledger, returning=True)
    assert isinstance(switch, Switched)
    assert switch.restored is not None
    assert "The ledger is back as it was at" in switch.report()


def test_only_the_latest_each_copy_kept_left_stays(machine: Machine) -> None:
    machine.running("one")
    two = machine.copy("two", answered=True)
    one = machine.copies.of("one-commit")
    assert one is not None
    machine.clock.time = AT + timedelta(minutes=1)
    machine.switching.to(two)
    machine.clock.time = AT + timedelta(minutes=2)
    machine.switching.to(one)
    machine.clock.time = AT + timedelta(minutes=3)
    machine.switching.to(two)
    kept = machine.snapshots().all()
    assert [each.left for each in kept] == ["one", "two"]


def test_a_later_lups_last_switch_reads_as_none(machine: Machine) -> None:
    machine.layout.host.switched.parent.mkdir(parents=True, exist_ok=True)
    machine.layout.host.switched.write_text('{"another": "shape"}')
    assert last_switch(machine.layout) is None


def test_the_service_is_started_from_the_copy_the_link_names(
    machine: Machine, tmp_path: Path
) -> None:
    assert host_starter(machine.layout) == Detached()
    machine.running("current")
    machine.layout.host_copies.parent.mkdir(parents=True, exist_ok=True)
    machine.layout.host_copies.symlink_to(machine.copies.layout.home)
    command = machine.layout.host_copies / "bin" / "lup-dev"
    assert host_starter(machine.layout).command == [str(command), "host"]


def test_a_killed_service_is_found_by_its_lock_and_id(tmp_path: Path) -> None:
    layout = HostLayout(sockets=tmp_path / "run", state=tmp_path / "state")
    layout.sockets.mkdir(parents=True)
    programs = Programs(patience=timedelta(seconds=30))
    assert programs.killed(layout) is None, "nothing holds its lock"
    ready = tmp_path / "ready"
    holding = (
        "import pathlib, sys, time\n"
        "from filelock import FileLock\n"
        "lock = FileLock(sys.argv[1])\n"
        "lock.acquire()\n"
        "pathlib.Path(sys.argv[2]).write_text('ready')\n"
        "time.sleep(600)\n"
    )
    process = detached(
        sys.executable,
        "-c",
        holding,
        str(layout.lock),
        str(ready),
        log=tmp_path / "held.log",
    )
    try:
        while not ready.exists():
            assert not process.ended(), (tmp_path / "held.log").read_text()
        said = programs.killed(layout)
        assert said is not None
        assert "kept its process id" in said
        layout.pid.write_text(str(process.process.pid))
        assert programs.killed(layout) is None
        process.process.wait(30)
        assert process.ended()
    finally:
        process.end(timedelta(seconds=1))


def test_a_program_gone_from_its_lock_needs_no_ending(tmp_path: Path) -> None:
    layout = HostLayout(sockets=tmp_path / "run", state=tmp_path / "state")
    assert Programs().killed(layout) is None


def test_a_detached_program_can_be_watched_and_ended(tmp_path: Path) -> None:
    sleeping = detached("sleep", "600", log=tmp_path / "log")
    assert not sleeping.ended()
    sleeping.end(timedelta(seconds=30))
    assert sleeping.ended()
    sleeping.end(timedelta(seconds=30))
    done = detached("true", log=tmp_path / "log")
    done.process.wait(30)
    assert done.ended()


def host_machine(machine: Machine) -> None:
    machine.layout.host_copies.parent.mkdir(parents=True, exist_ok=True)
    machine.layout.host_copies.symlink_to(machine.copies.layout.home)


def test_the_copies_are_listed_for_a_page(machine: Machine) -> None:
    assert listed_copies(machine.layout).copies == []
    host_machine(machine)
    machine.running("current")
    machine.copy("never")
    taken = machine.snapshots().taken(AT, "current", "current-commit")
    assert taken is not None
    write_model(
        machine.layout.host.switched,
        LastSwitch(commit="c", at=AT, said="what came of it", answered=False),
    )
    listed = asyncio.run(CopiesAnswering(layout=machine.layout).answer(ListCopies()))
    assert isinstance(listed, CopiesListed)
    [one] = listed.copies
    assert one.commit == "current-commit"
    assert one.running
    assert one.tables == 2
    assert listed.tables == 2
    assert listed.last is not None
    assert listed.last.said == "what came of it"


def switcher_of(machine: Machine) -> tuple[CopySwitch, list[str]]:
    started: list[str] = []

    def start(copy: CopyLayout, commit: str) -> None:
        started.append(f"{copy.home.name} {commit}")

    return CopySwitch(layout=machine.layout, start=start), started


def test_a_switch_from_a_page_starts_the_copy_s_own_restore(machine: Machine) -> None:
    host_machine(machine)
    machine.running("current")
    machine.copy("before", answered=True)
    write_model(
        machine.layout.host.switched,
        LastSwitch(commit="c", at=AT, said="before this", answered=True),
    )
    handler, started = switcher_of(machine)
    reply = asyncio.run(handler.answer(SwitchCopy(commit="before")))
    assert isinstance(reply, CopySwitching)
    assert reply.commit == "before-commit"
    assert reply.log == machine.layout.host.log
    assert reply.last is not None
    assert reply.last.said == "before this"
    assert started == ["before before-commit"]


def test_a_copy_that_never_answered_is_switched_to_by_the_one_running(
    machine: Machine,
) -> None:
    host_machine(machine)
    machine.running("current")
    never = machine.copy("never")
    machine.copies.pin([never.commit])
    handler, started = switcher_of(machine)
    asyncio.run(handler.answer(SwitchCopy(commit="never")))
    assert started == ["current never-commit"]


@pytest.mark.parametrize(
    ("commit", "said"),
    [
        ("current", "runs current-commit already"),
        ("none", "no copy kept is of a commit starting none"),
    ],
)
def test_a_switch_from_a_page_is_refused_where_it_cant_go(
    machine: Machine, commit: str, said: str
) -> None:
    host_machine(machine)
    machine.running("current")
    handler, started = switcher_of(machine)
    with pytest.raises(HostError, match=said):
        asyncio.run(handler.answer(SwitchCopy(commit=commit)))
    assert started == []


def test_a_switch_from_a_page_never_restores_the_ledger(machine: Machine) -> None:
    host_machine(machine)
    machine.running("current")
    machine.copy("before", answered=True)
    assert machine.snapshots().taken(AT, "before", "before-commit") is not None
    connection = sqlite3.connect(machine.ledger.database)
    connection.execute("PRAGMA user_version = 3")
    connection.close()
    assert needs_ledger(machine.snapshots(), "before") is not None
    handler, started = switcher_of(machine)
    with pytest.raises(HostError, match="restore before-commit --ledger"):
        asyncio.run(handler.answer(SwitchCopy(commit="before")))
    assert started == []


def test_no_copy_on_this_machine_has_none_to_switch_to(machine: Machine) -> None:
    handler, _ = switcher_of(machine)
    with pytest.raises(HostError, match="no copy of `lup-dev` is kept"):
        asyncio.run(handler.answer(SwitchCopy(commit="any")))


def test_a_commit_is_named_by_its_start_and_two_starting_alike_are_refused(
    machine: Machine,
) -> None:
    one = machine.copy("abc1")
    two = machine.copy("abc2")
    assert found([one, two], "abc1-commit") == one
    with pytest.raises(HostError, match="starts more than one commit kept"):
        found([one, two], "abc")


def test_a_program_started_while_signals_are_held_back_still_hears_them(
    tmp_path: Path,
) -> None:
    told = tmp_path / "told"
    asking_signals = (
        "import pathlib, signal, sys\n"
        "said = [signal.getsignal(each).name for each in\n"
        "        (signal.SIGTERM, signal.SIGHUP)]\n"
        "pathlib.Path(sys.argv[1]).write_text(' '.join(said))\n"
    )
    with uninterrupted():
        started = detached(
            sys.executable, "-c", asking_signals, str(told), log=tmp_path / "log"
        )
    started.process.wait(30)
    assert told.read_text() == "SIG_DFL SIG_DFL"
