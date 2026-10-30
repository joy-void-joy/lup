"""Threads as the operator's review reads them: each thread's section and why, what's new since its mark, its conversation with each reply under what it answers, settling, declining and reopening one, and a reply reopening one done."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup_dev import cli
from lup_dev.host.names import Names
from lup_dev.host.protocol import Limits, Register
from lup_dev.host.pushes import Pushes
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.marks import CORE, ReviewMark, on_node
from lup_dev.inbox.notices import Notices
from lup_dev.inbox.store import (
    KINDS,
    Comment,
    Draft,
    Inbox,
    InboxError,
    Message,
    Ruling,
)
from lup_dev.inbox.threaded import (
    DeclineThread,
    ListThreads,
    ReopenThread,
    SettleThread,
    ShowThread,
    Spot,
    ThreadDeclining,
    ThreadRead,
    ThreadReading,
    ThreadReopening,
    ThreadShowing,
    ThreadShown,
    ThreadsListing,
    ThreadsRead,
    ThreadStated,
    ThreadStating,
)
from lup_dev.inbox.tools import (
    Asking,
    Choice,
    Speaker,
    ThreadedFriction,
    ThreadedRemark,
    Threading,
)
from lup_dev.layout import Layout
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.parties import Conversation
from lup_ledger.threads import Declined, Done, Reopened, Settled, Thread

if TYPE_CHECKING:
    from conftest import FakeClock

REPOSITORY = Path("/work/lup.git")
LEAD = Conversation(repository=REPOSITORY, runtime="claude", session="s1")


class Silent(Notices):
    """Raises nothing."""

    @override
    async def notify(self, summary: str, body: str) -> None:
        pass


@pytest.fixture
def delivery(tmp_path: Path, clock: FakeClock) -> Delivery:
    """A delivery over an inbox under `tmp_path`, outside any service."""
    known = cli.Adapters(known=cli.adapters())
    return Delivery(
        inbox=Inbox.opened(
            Ledger.opened(LedgerLayout(home=tmp_path / "ledger"), KINDS)
        ),
        waker=cli.Wakers(adapters=known),
        pushes=Pushes(),
        layout=Layout(state=tmp_path / "state", runtime=tmp_path / "run").host,
        notices=Silent(),
        clock=clock,
        say=lambda _: None,
    )


class Work:
    """A session, `lead`, at work in a repository: four threads, each standing differently.

    - their root: a note, `@1`, and a friction, the pile's;
    - `lag`: a question with its decision and a check, both asking the operator;
    - `voice`: a note, then done, for the operator to confirm;
    - `docs`: a note, read.
    """

    def __init__(self, delivery: Delivery, clock: FakeClock) -> None:
        self.delivery = delivery
        self.clock = clock
        register = Register(
            launch="lead",
            runtime="claude",
            worktree=Path("/work/lead"),
            repository=REPOSITORY,
            judge=Path("/judge/lup-dev"),
            limits=Limits(actions=[], protected=[]),
            github=None,
        )
        record = delivery.layout.record("lead")
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(register.model_dump_json())
        Names(path=delivery.layout.names).keep("s1", "lead")
        delivery.heard_in(LEAD, register, None)
        self.lead = Speaker(delivery=delivery, launch=register, party=LEAD)
        self.note = self.sent(ThreadedRemark(remark="Built."))
        self.root = self.thread_of(self.note)
        self.friction = self.ran(
            self.lead.friction(ThreadedFriction(text="The gate hung."))
        )
        for name, title in [
            ("lag", "The cursor jumps"),
            ("voice", "Voice"),
            ("docs", "Docs"),
        ]:
            self.ran(self.lead.thread(Threading(name=name, title=title)))
        self.question = self.ran(
            self.lead.ask(
                Asking(
                    question="Long comments only?",
                    decisions=[Choice(decision="Long ones", lean="yes")],
                    checks=["Type in a long one."],
                    thread="lag",
                )
            )
        )
        self.lag = self.thread_of(self.question)
        [self.check] = [
            each.node
            for each in self.reading().readings_now().ledgered.members[self.lag.number]
            if each.node != self.question
        ]
        self.voiced = self.sent(ThreadedRemark(remark="Voice works.", thread="voice"))
        self.voice = self.thread_of(self.voiced)
        self.ran(
            self.lead.thread(Threading(name="voice", done="Say hello: it answers."))
        )
        self.documented = self.sent(ThreadedRemark(remark="Docs.", thread="docs"))
        self.docs = self.thread_of(self.documented)
        delivery.done(self.documented)

    def ran(self, coroutine: object) -> int:
        """Run a tool's call; return the number of the item it made, as its answer cites it, or 0."""
        assert asyncio.iscoroutine(coroutine)
        said = asyncio.run(coroutine).text
        cited = [
            word for word in said.replace(",", " ").split() if word.startswith("@")
        ]
        numbers = [word.removeprefix("@").rstrip(".") for word in cited]
        return next((int(each) for each in numbers if each.isdigit()), 0)

    def sent(self, remark: ThreadedRemark) -> int:
        return self.ran(self.lead.note(remark))

    def thread_of(self, number: int) -> Thread:
        found = self.delivery.concerns().containing(number)
        assert found is not None
        return found

    def reading(self) -> ThreadReading:
        return ThreadReading(delivery=self.delivery)

    def read(self) -> dict[str, ThreadRead]:
        listed = asyncio.run(
            ThreadsListing(reading=self.reading()).answer(ListThreads())
        )
        assert isinstance(listed, ThreadsRead)
        return {each.thread.name: each for each in listed.threads}

    def shown(self, thread: Thread, *, whole: bool = False) -> ThreadShown:
        shown = asyncio.run(
            ThreadShowing(reading=self.reading()).answer(
                ShowThread(number=thread.number, whole=whole)
            )
        )
        assert isinstance(shown, ThreadShown)
        return shown


@pytest.fixture
def work(delivery: Delivery, clock: FakeClock) -> Work:
    return Work(delivery, clock)


def test_each_thread_s_section_says_what_asks_the_operator_what_s_new_and_the_pile_beside(
    work: Work,
) -> None:
    read = work.read()

    assert sorted(read) == ["docs", "lag", "lead", "voice"]
    lag, voice, root, docs = read["lag"], read["voice"], read["lead"], read["docs"]
    assert (lag.section, lag.state) == ("waiting on you", "waiting on the operator")
    assert [(each.node, each.what) for each in lag.asks] == [
        (work.question, "a question"),
        (work.check, "a check"),
    ]
    assert lag.since == lag.asks[0].came
    assert (voice.section, voice.state, voice.asks) == (
        "waiting on you",
        "done to confirm",
        [],
    )
    assert isinstance(voice.status, Done)
    assert voice.status.to_try == "Say hello: it answers."
    assert voice.since == voice.status.at
    # A note unread makes the root new; the friction beside it, the pile's, doesn't.
    assert (root.section, root.new, root.pile) == ("new", [work.note], [work.friction])
    assert (docs.section, docs.new, docs.pile) == ("every thread", [], [])
    assert root.answering == LEAD
    assert work.shown(work.root).on == [LEAD]
    assert (root.members, root.earlier, root.mark) == (2, 0, None)


def test_what_s_new_comes_after_the_thread_s_mark_or_its_settling(
    work: Work, clock: FakeClock
) -> None:
    store = work.delivery.inbox.marks
    clock.sleep(60)
    store.moved(
        REPOSITORY,
        CORE,
        [
            ReviewMark(
                key=on_node(work.root.number), up_to=str(work.note), at=clock.now()
            )
        ],
    )
    root = work.read()["lead"]
    assert root.mark is not None
    assert (root.section, root.new, root.earlier) == ("every thread", [], 1)
    # A note after it is new; settling the thread later reads what came before.
    clock.sleep(60)
    later = work.sent(ThreadedRemark(remark="More."))
    assert work.read()["lead"].new == [later]
    clock.sleep(60)
    work.delivery.concerns().settled(work.root)
    settled = work.read()["lead"]
    assert (settled.section, settled.state, settled.new) == (
        "every thread",
        "settled",
        [],
    )
    assert settled.earlier == 3


def test_a_thread_s_conversation_lays_each_reply_under_what_it_answers(
    work: Work, clock: FakeClock
) -> None:
    clock.sleep(60)
    answer = asyncio.run(
        work.delivery.answer(
            work.question,
            [Ruling(decision=1, verdict="leaning", comment="Long ones.")],
            "Go on.",
        )
    )
    clock.sleep(60)
    concerns = work.delivery.concerns()
    ending = work.delivery.inbox.made(
        Message(kind="note", text="Done that.", ending=True, answers=[answer.number]),
        LEAD,
        work.delivery.inbox.item(work.question).recipient,
        Path("/work/lead"),
        clock.now(),
    )
    concerns.landed(ending, work.lag)

    shown = work.shown(work.lag, whole=True)

    assert [(each.spot, each.under, each.member) for each in shown.entries] == [
        (Spot(node=work.question), None, True),
        (Spot(node=work.check), None, True),
        (Spot(node=answer.number, part=1), Spot(node=work.question), False),
        (Spot(node=answer.number, part=2), Spot(node=work.question), False),
        (Spot(node=ending.number), Spot(node=answer.number, part=2), True),
    ]
    assert {each.number for each in shown.items} == {
        work.question,
        answer.number,
        ending.number,
    }
    [check] = shown.checks
    assert (check.check.number, check.answer) == (work.check, None)
    assert shown.left == 0
    assert {each.conversation for each in shown.paths} == {LEAD}


def test_a_thread_s_conversation_from_its_mark_keeps_what_a_later_entry_is_under(
    work: Work, clock: FakeClock
) -> None:
    clock.sleep(60)
    work.delivery.inbox.marks.moved(
        REPOSITORY,
        CORE,
        [
            ReviewMark(
                key=on_node(work.lag.number), up_to=str(work.check), at=clock.now()
            )
        ],
    )
    clock.sleep(60)
    answer = asyncio.run(
        work.delivery.answer(work.question, [Ruling(decision=1, verdict="leaning")], "")
    )

    shown = work.shown(work.lag)

    assert [(each.spot, each.earlier) for each in shown.entries] == [
        (Spot(node=work.question), True),
        (Spot(node=answer.number, part=1), False),
    ]
    assert shown.left == 1
    assert shown.read.earlier == 2
    whole = work.shown(work.lag, whole=True)
    assert [each.spot for each in whole.entries] == [
        Spot(node=work.question),
        Spot(node=work.check),
        Spot(node=answer.number, part=1),
    ]


def test_the_operator_settles_declines_and_reopens_a_thread_whoever_answers_for_it_told(
    work: Work,
) -> None:
    reading = work.reading()
    settled = asyncio.run(
        ThreadStating(reading=reading).answer(SettleThread(number=work.voice.number))
    )
    assert isinstance(settled, ThreadStated)
    assert (settled.read.state, settled.read.section) == ("settled", "every thread")
    assert isinstance(settled.read.status, Settled)
    reopened = asyncio.run(
        ThreadReopening(reading=reading).answer(
            ReopenThread(number=work.voice.number, why="It answers in French.")
        )
    )
    assert isinstance(reopened, ThreadStated)
    assert isinstance(reopened.read.status, Reopened)
    assert reopened.read.state == "working"
    declined = asyncio.run(
        ThreadDeclining(reading=reading).answer(
            DeclineThread(number=work.docs.number, why="Not now.")
        )
    )
    assert isinstance(declined, ThreadStated)
    assert isinstance(declined.read.status, Declined)
    with pytest.raises(InboxError, match="@9999"):
        asyncio.run(ThreadStating(reading=reading).answer(SettleThread(number=9999)))


def test_a_reply_of_the_operator_s_in_a_thread_done_reopens_it_back_to_whoever_held_it(
    work: Work,
) -> None:
    asyncio.run(work.delivery.answer(work.voiced, [], "It still lags."))
    voice = work.read()["voice"]
    assert isinstance(voice.status, Reopened)
    assert voice.status.why == "the operator replied there"
    # Commented on in a review, a thread done is reopened the same way.
    work.ran(work.lead.thread(Threading(name="voice", done="Say hello again.")))
    work.delivery.inbox.drafted(
        Draft(comments=[Comment(item=work.voiced, text="Still lags.")])
    )
    asyncio.run(work.delivery.reviewed())
    assert isinstance(work.read()["voice"].status, Reopened)


def test_the_threads_are_read_again_only_once_what_they_re_read_from_changed(
    work: Work,
) -> None:
    reading = work.reading()
    first = reading.readings_now()
    assert reading.readings_now() is first
    work.sent(ThreadedRemark(remark="Again."))
    assert reading.readings_now() is not first


def test_a_room_never_reads_the_review_s_threads(work: Work) -> None:
    reading = work.reading()
    with pytest.raises(InboxError, match="operator's"):
        asyncio.run(ThreadsListing(reading=reading).scoped(ListThreads(), REPOSITORY))
    with pytest.raises(InboxError, match="operator's"):
        asyncio.run(
            ThreadShowing(reading=reading).scoped(
                ShowThread(number=work.lag.number), REPOSITORY
            )
        )


def test_a_part_moved_in_stands_open_until_an_item_there_cites_it_never_asking_the_operator(
    work: Work, clock: FakeClock
) -> None:
    clock.sleep(60)
    answer = asyncio.run(
        work.delivery.answer(
            work.question,
            [Ruling(decision=1, verdict="leaning")],
            "And write it up in the docs.",
        )
    )
    part = Spot(node=answer.number, part=2)
    clock.sleep(60)
    work.ran(work.lead.thread(Threading(name="docs", move=[f"{answer.number}.2"])))

    docs = work.read()["docs"]
    assert docs.unanswered == [part]
    assert (docs.section, docs.asks) == ("every thread", [])
    [moved] = [
        each
        for each in work.shown(docs.thread, whole=True).entries
        if each.spot == part
    ]
    assert moved.unanswered

    clock.sleep(60)
    cited = work.sent(
        ThreadedRemark(remark=f"Written up, as @{answer.number}.2 asks.", thread="docs")
    )
    after = work.read()["docs"]
    assert after.unanswered == []
    entries = {each.spot: each for each in work.shown(after.thread, whole=True).entries}
    assert not entries[part].unanswered
    assert entries[Spot(node=cited)].under == part
