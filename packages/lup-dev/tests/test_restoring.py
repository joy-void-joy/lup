"""`lup-dev restore`: the operator's way back, with the switch standing in (`lup_dev/restoring.py`)."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from filelock import FileLock
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.approval import Approval, WorkspaceTool
from lup_dev.copies import Copies, Kept
from lup_dev.host.client import Detached, HostClient
from lup_dev.host.protocol import HostError, Listed, ListLaunches, Reply, Request
from lup_dev.layout import Layout
from lup_dev.restoring import RestoreError, Restoring
from lup_dev.snapshots import Snapshot, Snapshots
from lup_dev.stored import write_model
from lup_dev.switching import LastSwitch, Switch, Switched, Switcher
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import FakeClock

AT = datetime(2026, 11, 6, 12, tzinfo=UTC)
TOOL = WorkspaceTool(name="lup-dev", package=Path("packages/lup-dev"), members=[])
REPOSITORY = Path("/repo.git")


class Went(Switcher):
    """Moves nothing: says where it was asked to go, with which ledger."""

    def __init__(self) -> None:
        self.went: list[str] = []
        self.ledgers: list[Snapshot | None] = []
        self.returning: list[bool] = []
        self.tries: list[str] = []
        self.why: str | None = None

    @override
    def to(
        self, kept: Kept, *, ledger: Snapshot | None = None, returning: bool = False
    ) -> Switch:
        self.went.append(kept.commit)
        self.ledgers.append(ledger)
        self.returning.append(returning)
        return Switched(kept=kept, ran=True, snapshot=None, took=timedelta(seconds=4))

    @override
    def tried(self, kept: Kept) -> str | None:
        self.tries.append(kept.commit)
        return self.why


class Answering(HostClient):
    running: bool = False

    @override
    def ask[R: Reply](self, request: Request, reply: type[R]) -> R:
        assert isinstance(request, ListLaunches)
        if not self.running:
            message = "no host service answers"
            raise HostError(message)
        given = Listed(launches=[])
        assert isinstance(given, reply)
        return given


class Way:
    """The operator's way back, on a machine of real places."""

    def __init__(self, tmp_path: Path, clock: FakeClock) -> None:
        self.layout = Layout(
            state=tmp_path / "state",
            runtime=tmp_path / "run",
            data=tmp_path / "data",
        )
        self.copies = Copies(layout=self.layout.judge(REPOSITORY))
        self.copies.layout.home.mkdir(parents=True)
        self.layout.host_copies.symlink_to(self.copies.layout.home)
        self.ledger = LedgerLayout.of(self.layout)
        Ledger.opened(self.ledger).close()
        self.snapshots = Snapshots(home=self.layout.snapshots, ledger=self.ledger)
        self.went = Went()
        self.said: list[str] = []
        self.asked: list[str] = []
        self.answer = True
        self.rebuilt: list[str] = []
        self.host = Answering(
            layout=self.layout.host, clock=clock, starter=Detached(), running=True
        )

    def restoring(self) -> Restoring:
        def confirm(question: str) -> bool:
            self.asked.append(question)
            return self.answer

        def built_again(kept: Kept, then: Callable[[Kept], Switch]) -> Switch:
            self.rebuilt.append(kept.commit)
            return then(kept.model_copy(update={"name": "built-again"}))

        return Restoring(
            layout=self.layout,
            host=self.host,
            switcher=self.went,
            confirm=confirm,
            built_again=built_again,
            say=self.said.append,
        )

    def copy(self, commit: str, at: int = 0, *, there: bool = True) -> Kept:
        kept = Kept(
            name=f"copy-of-{commit}",
            repository=REPOSITORY,
            approval=Approval(
                commit=commit,
                fingerprint=f"zone of {commit}",
                paths=[],
                tool=TOOL,
                time=AT,
            ),
            subject=f"the commit {commit}",
            answered=AT + timedelta(hours=at),
        )
        if there:
            self.copies.place(kept).bin.mkdir(parents=True)
        self.copies.recorded(kept)
        return kept

    def tables(self, version: int) -> None:
        connection = sqlite3.connect(self.ledger.database)
        connection.execute(f"PRAGMA user_version = {version}")
        connection.close()


@pytest.fixture
def way(tmp_path: Path, clock: FakeClock) -> Way:
    return Way(tmp_path, clock)


def test_with_nothing_kept_it_says_so(tmp_path: Path, clock: FakeClock) -> None:
    empty = Way(tmp_path, clock)
    empty.layout.host_copies.unlink()
    said = empty.restoring().listing()
    assert "No copy of `lup-dev` is kept yet" in said
    with pytest.raises(RestoreError, match="no copy of `lup-dev` is kept"):
        empty.restoring().restored("abc", ledger=False)


def test_the_list_says_what_runs_and_changes_nothing(way: Way) -> None:
    running = way.copy("c0ffee", 2)
    way.copy("beef00", 1)
    way.copy("gone00", 0, there=False)
    way.copies.switch(way.copies.place(running))
    assert way.snapshots.taken(AT, "copy-of-beef00", "beef00") is not None
    said = way.restoring().listing().splitlines()
    assert said[0] == "The host service answers."
    assert said[3].startswith("* c0ffee  ran ")
    assert said[3].endswith("the commit c0ffee")
    assert said[4].startswith("  beef00  ran ")
    assert said[4].endswith(", tables 2")
    assert any("gone00  the commit gone00" in line for line in said)
    assert any("built again from its commit" in line for line in said)
    assert way.went.went == []


def test_the_list_says_no_service_answers(way: Way) -> None:
    way.host = way.host.model_copy(update={"running": False})
    assert way.restoring().listing().splitlines()[0] == "No host service answers."


def test_the_list_says_why_the_last_switch_failed(way: Way) -> None:
    way.copy("c0ffee")
    write_model(
        way.layout.host.switched,
        LastSwitch(commit="c", at=AT, said="the page is blank", answered=False),
    )
    assert "the page is blank" in way.restoring().listing()
    write_model(
        way.layout.host.switched,
        LastSwitch(commit="c", at=AT, said="it answers", answered=True),
    )
    assert "it answers" not in way.restoring().listing()


def test_a_commit_is_named_by_its_start(way: Way) -> None:
    way.copy("c0ffee")
    way.copy("beef00")
    switch = way.restoring().restored("c0f", ledger=False)
    assert isinstance(switch, Switched)
    assert way.went.went == ["c0ffee"]
    assert way.went.returning == [True]
    assert way.went.ledgers == [None]
    assert way.asked == []


def test_a_start_two_commits_share_is_refused_and_one_none_has(way: Way) -> None:
    way.copy("c0ffee")
    way.copy("c0ff11")
    with pytest.raises(HostError, match="starts more than one commit kept"):
        way.restoring().restored("c0ff", ledger=False)
    with pytest.raises(HostError, match="no copy kept is of a commit starting none"):
        way.restoring().restored("none", ledger=False)
    assert way.went.went == []


def test_one_there_is_chosen_before_one_gone_starting_the_same(way: Way) -> None:
    way.copy("c0ffee")
    way.copy("c0ff11", there=False)
    way.restoring().restored("c0ff", ledger=False)
    assert way.went.went == ["c0ffee"]


def test_a_commit_approved_and_gone_is_built_again_then_gone_to(way: Way) -> None:
    way.copy("gone00", there=False)
    way.restoring().restored("gone00", ledger=False)
    assert way.rebuilt == ["gone00"]
    assert way.went.went == ["gone00"]
    assert way.said == ["gone00's copy is gone: building it again, from its commit."]


def test_the_ledger_put_back_says_what_it_loses_and_asks(way: Way) -> None:
    way.copy("c0ffee")
    taken = way.snapshots.taken(AT, "copy-of-c0ffee", "c0ffee")
    assert taken is not None
    way.restoring().restored("c0ffee", ledger=True)
    assert way.went.ledgers == [taken]
    [told] = way.said
    assert "Everything since" in told
    assert way.asked == ["Go back, and put the ledger back with it?"]


def test_saying_no_moves_nothing(way: Way) -> None:
    way.copy("c0ffee")
    assert way.snapshots.taken(AT, "copy-of-c0ffee", "c0ffee") is not None
    way.answer = False
    with pytest.raises(RestoreError, match="Nothing moved"):
        way.restoring().restored("c0ffee", ledger=True)
    assert way.went.went == []


def test_the_ledger_asked_for_where_the_copy_left_none_is_refused(way: Way) -> None:
    way.copy("c0ffee")
    with pytest.raises(RestoreError, match="left no snapshot of the ledger"):
        way.restoring().restored("c0ffee", ledger=True)
    assert way.went.went == []


def test_a_copy_that_cant_read_the_ledger_as_it_stands_asks_though_nobody_said_to(
    way: Way,
) -> None:
    way.copy("c0ffee")
    taken = way.snapshots.taken(AT, "copy-of-c0ffee", "c0ffee")
    assert taken is not None
    way.tables(3)
    way.restoring().restored("c0ffee", ledger=False)
    assert way.went.ledgers == [taken]
    [told] = way.said
    assert "version 2 of its tables" in told
    assert "however much that is" in told
    assert way.asked == ["Go back, and put the ledger back with it?"]


def test_an_approval_being_carried_out_holds_it_off(way: Way) -> None:
    way.copy("c0ffee")
    kept = way.layout.approved(REPOSITORY)
    kept.parent.mkdir(parents=True, exist_ok=True)
    restoring = way.restoring().model_copy(update={"patience": timedelta()})
    with (
        FileLock(kept.with_name(f"{kept.name}.lock")),
        pytest.raises(RestoreError, match="an approval is being carried out"),
    ):
        restoring.restored("c0ffee", ledger=False)
    assert way.went.went == []


def test_a_try_moves_nothing_and_says_why(way: Way) -> None:
    way.copy("c0ffee")
    way.went.why = "the page is blank"
    assert way.restoring().tried("c0f") == "the page is blank"
    assert way.went.tries == ["c0ffee"]
    assert way.went.went == []


def test_a_copy_gone_cant_be_tried(way: Way) -> None:
    way.copy("gone00", there=False)
    with pytest.raises(RestoreError, match="copy is gone"):
        way.restoring().tried("gone00")


def test_it_refuses_inside_an_agents_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    result = CliRunner().invoke(cli.app, ["restore"])
    assert result.exit_code != 0
    assert "the operator's" in str(result.exception)


def test_what_it_refuses_is_kept_for_a_page_that_asked_for_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.delenv("CLAUDE_CODE_CHILD_SESSION", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    result = CliRunner().invoke(cli.app, ["restore", "c0ffee"])
    assert result.exit_code != 0
    switched = tmp_path / "xdg" / "lup" / "host" / "last-switch.json"
    assert "no copy of `lup-dev` is kept" in switched.read_text()
