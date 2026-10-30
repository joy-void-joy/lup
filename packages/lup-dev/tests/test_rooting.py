"""Past conversations made threads: each item a conversation sent the operator before threads, put in its session's root once as the host service opens the inbox, a root opened for them settled unless something in it waits or the session goes on; and the check of it, which says counts and differences alone."""

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.conversions import checked, inbox_opened, snapshot
from lup_dev.host.names import Names
from lup_dev.inbox.concerns import ROOT
from lup_dev.inbox.rooting import Rooted, concerned, loose, rooted, rooted_rehearsed
from lup_dev.inbox.store import (
    KINDS,
    Done,
    Item,
    Message,
    Question,
    Whereabouts,
)
from lup_dev.layout import Layout
from lup_dev.settings import LupDevSettings
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.parties import Conversation, Lup, Operator
from lup_ledger.threads import In, Reopened, Settled, Thread

if TYPE_CHECKING:
    from conftest import FakeClock

REPOSITORY = Path("/work/lup.git")


def session(name: str) -> Conversation:
    return Conversation(repository=REPOSITORY, runtime="claude", session=name)


class Past:
    """An inbox as an earlier lup left it, its items in no thread: three sessions, `dev` and `docs` ended, `dev`'s subagent `parser` with them, `dev-again` still at work and named `dev` too."""

    def __init__(self, layout: Layout, clock: FakeClock) -> None:
        self.layout = layout
        self.clock = clock
        self.inbox = inbox_opened(layout)
        names = Names(path=layout.host.names)
        for each, name in [("s1", "dev"), ("s2", "docs"), ("s3", "dev")]:
            names.keep(each, name)
        self.dev, self.docs, self.again = session("s1"), session("s2"), session("s3")
        self.parser = self.dev.model_copy(update={"agent": "a1"})
        for conversation, launch, parent in [
            (self.dev, "one", None),
            (self.parser, "one", self.dev),
            (self.docs, "two", None),
            (self.again, "three", None),
        ]:
            self.inbox.placed(
                Whereabouts(
                    conversation=conversation,
                    launch=launch,
                    worktree=Path("/work/tree"),
                    since=clock.now(),
                    ended=None if conversation == self.again else clock.now(),
                    parent=parent,
                    name="parser" if parent else None,
                )
            )
        record = layout.host.record("three")
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text("{}")
        self.read = [
            self.made(Message(kind="note", text="Built."), self.dev),
            self.made(Message(kind="note", text="Parsed."), self.parser),
            self.made(Message(kind="note", text="Docs."), self.docs),
            self.made(Message(kind="note", text="Again."), self.again),
        ]
        for each in self.read:
            self.inbox.kept(each.model_copy(update={"state": Done(at=clock.now())}))
        self.asking = self.made(Question(text="Which way?"), self.docs)
        # A message one of `dev`'s sent another, whose copy the operator reads.
        self.copy = self.made(
            Message(kind="note", text="Over to you.", to=self.dev), self.parser
        )
        self.inbox.kept(self.copy.model_copy(update={"state": Done(at=clock.now())}))
        # An item to a conversation, which lands nowhere.
        self.answer = self.inbox.made(
            Message(kind="note", text="Carry on."),
            Operator(),
            self.dev,
            None,
            clock.now(),
        )

    def made(self, reason: Message | Question, sender: Conversation) -> Item:
        self.clock.sleep(1)
        return self.inbox.made(
            reason, sender, Operator(), Path("/work/tree"), self.clock.now()
        )


@pytest.fixture
def machine(tmp_path: Path) -> Layout:
    return Layout(state=tmp_path / "state", runtime=tmp_path / "run", data=tmp_path)


def test_each_past_item_goes_to_its_session_s_root_each_opened_root_settled_but_where_it_waits_or_goes_on(
    machine: Layout, clock: FakeClock
) -> None:
    past = Past(machine, clock)
    concerns = concerned(past.inbox, machine)

    done = rooted(concerns)

    assert done == Rooted(
        sessions=3, opened=3, items=6, settled=1, waiting=1, going_on=1
    )
    dev, docs, again = (
        concerns.containing(each.number)
        for each in [past.read[0], past.read[2], past.read[3]]
    )
    assert dev is not None
    assert docs is not None
    assert again is not None
    # `dev-again` goes on, named `dev`: names are one set in a repository, an
    # agent's and a thread's, so the earlier `dev` ended takes the next free one.
    assert [each.name for each in [dev, docs, again]] == ["dev-2", "docs", "dev"]
    assert {each.title for each in [dev, docs, again]} == {ROOT}
    assert [each.holder for each in [dev, docs, again]] == [
        past.dev,
        past.docs,
        past.again,
    ]
    assert {each.by.party for each in [dev, docs, again]} == {"lup"}
    # A subagent's items, and the copy of their message, are in their session's root.
    assert concerns.containing(past.read[1].number) == dev
    assert concerns.containing(past.copy.number) == dev
    assert concerns.containing(past.asking.number) == docs
    assert concerns.containing(past.answer.number) is None
    # `dev` ended and nothing in it waits: settled, by the operator. `docs` asks
    # them; `dev-again` goes on: each left open.
    assert concerns.standing(dev).state == "settled"
    assert isinstance(concerns.standing(dev).status, Settled)
    assert concerns.standing(docs).state == "waiting on the operator"
    assert concerns.standing(again).state == "working"
    # Each session works there from now on, their root kept on their whereabouts.
    assert concerns.root(past.again) == again
    assert {each.by.party for each in past.inbox.ledger.drawn_of(In)} == {"lup"}
    # Nothing lies outside a thread, so nothing happens again.
    assert loose(past.inbox) == []
    assert rooted(concerns) is None


def test_a_session_with_a_root_already_has_its_earlier_items_put_there_its_status_as_it_stands(
    machine: Layout, clock: FakeClock
) -> None:
    past = Past(machine, clock)
    concerns = concerned(past.inbox, machine)
    root = concerns.root(past.again)
    concerns.settled(root)
    later = concerns.thread(root.number)

    done = rooted(concerns)

    assert done is not None
    assert done.opened == 2
    assert concerns.containing(past.read[3].number) == later
    assert isinstance(concerns.standing(later).status, Settled)
    assert len(past.inbox.ledger.drawn_to(root.number, Settled)) == 1


def test_a_later_session_taking_a_settled_past_root_s_name_takes_it_reopened(
    machine: Layout, clock: FakeClock
) -> None:
    past = Past(machine, clock)
    concerns = concerned(past.inbox, machine)
    rooted(concerns)
    dev = concerns.containing(past.read[0].number)
    assert dev is not None
    newer = session("s9")
    Names(path=machine.host.names).keep("s9", "dev-2")
    past.inbox.placed(
        Whereabouts(
            conversation=newer,
            launch="nine",
            worktree=Path("/work/tree"),
            since=clock.now() + timedelta(minutes=1),
        )
    )
    taken = concerned(past.inbox, machine).root(newer)
    assert taken.number == dev.number
    status = concerns.standing(taken).status
    assert isinstance(status, Reopened)
    assert status.by == Lup()


def test_the_host_service_puts_past_conversations_in_threads_as_it_opens_the_inbox_and_says_so(
    machine: Layout, clock: FakeClock
) -> None:
    Past(machine, clock).inbox.ledger.close()
    said: list[str] = []

    inbox = inbox_opened(machine, say=said.append)
    inbox.ledger.close()
    inbox_opened(machine, say=said.append)

    assert said == [
        (
            "lup: past conversations are threads: 6 items of 3 sessions in their "
            "roots, 3 opened: 1 settled, 1 left open as something in it waits on "
            "you, 1 left open as its session goes on."
        )
    ]


def test_the_check_rehearses_it_on_a_snapshot_the_ledger_left_as_it_is(
    machine: Layout, clock: FakeClock, tmp_path: Path
) -> None:
    Past(machine, clock).inbox.ledger.close()
    database = LedgerLayout.of(machine).database
    before = database.read_bytes()
    live = LedgerLayout(home=tmp_path / "live")
    assert snapshot(LedgerLayout.of(machine), live)

    rehearsal = rooted_rehearsed(machine, live)

    assert rehearsal.differs == []
    assert rehearsal.rooted is not None
    assert rehearsal.rooted.items == 6
    said = "\n".join(rehearsal.said())
    assert "6 items of 3 sessions" in said
    assert all(text not in said for text in ["Built.", "Which way?", "dev"])
    assert database.read_bytes() == before
    assert Ledger.opened(LedgerLayout.of(machine), KINDS).every(Thread) == []


def test_the_check_says_what_differs_where_an_item_is_left_out(
    machine: Layout, clock: FakeClock, tmp_path: Path
) -> None:
    past = Past(machine, clock)
    concerns = concerned(past.inbox, machine)
    rooted(concerns)
    # A later item that lies outside every thread, as an earlier lup run since
    # would leave it: the rehearsal puts it in its root, finding nothing amiss.
    stray = past.made(Message(kind="note", text="Late."), past.dev)
    past.inbox.ledger.close()
    live = LedgerLayout(home=tmp_path / "live")
    snapshot(LedgerLayout.of(machine), live)
    rehearsal = rooted_rehearsed(machine, live)
    assert rehearsal.rooted is not None
    assert (rehearsal.rooted.items, rehearsal.rooted.opened) == (1, 0)
    assert rehearsal.differs == []
    assert stray.number


def test_lup_dev_inbox_check_conversion_says_each_conversion_s_section(
    tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    machine = Layout.of(LupDevSettings())
    Past(machine, clock).inbox.ledger.close()

    ran = CliRunner().invoke(cli.app, ["inbox", "check-conversion"])

    assert ran.exit_code == 0, ran.output
    assert "Past conversations as threads:\n  Put them in threads in" in ran.output
    assert "Every item is in a thread" in ran.output
    checks = checked(machine, machine.inbox, tmp_path / "scratch")
    assert [each.of for each in checks] == [
        "The inbox's files",
        "The review marks' files",
        "Past conversations as threads",
    ]
