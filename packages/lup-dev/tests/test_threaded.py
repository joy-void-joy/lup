"""Threads as the operator's review reads them: each thread's section and why, what's new since its mark, its conversation with each reply under what it answers, settling, declining and reopening one, and a reply reopening one done."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup.sessions.results import HowItFelt
from lup_dev import cli
from lup_dev.host.names import Names
from lup_dev.host.protocol import Limits, Register
from lup_dev.host.pushes import Pushes
from lup_dev.inbox.delivery import Delivery, Dispatched, Unanswerable
from lup_dev.inbox.marks import CORE, ReviewMark, on_node
from lup_dev.inbox.notices import Notices
from lup_dev.inbox.protocol import Exchanged, ItemsListing, ListItems
from lup_dev.inbox.store import (
    KINDS,
    Approval,
    Comment,
    Destination,
    Destined,
    Done,
    Draft,
    Inbox,
    InboxError,
    Letter,
    Message,
    Quote,
    Review,
    Ruling,
    Waiting,
)
from lup_dev.inbox.threaded import (
    DeclineThread,
    ListThreads,
    Passage,
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
    Concerning,
    Parking,
    Speaker,
    ThreadedRemark,
)
from lup_dev.layout import Layout
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.parties import Conversation, Lup, Operator
from lup_ledger.threads import (
    ROOT,
    Answered,
    Check,
    Declined,
    In,
    Reopened,
    Settled,
    Thread,
)
from lup_ledger.threads import Done as ThreadDone

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

    - `home`, which they hold and work in: a note and a friction, the pile's;
    - `lag`: a question with its decision, asking the operator, and a check an
      earlier lup kept, which asks nothing;
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
        self.ran(self.lead.concern(Concerning(name="home", title="Home", hold=True)))
        self.note = self.sent(ThreadedRemark(remark="Built."))
        self.home = self.thread_of(self.note)
        self.friction = self.ran(
            self.lead.concern(Concerning(text="The gate hung.", name="home"))
        )
        for name, title in [
            ("lag", "The cursor jumps"),
            ("voice", "Voice"),
            ("docs", "Docs"),
        ]:
            self.ran(self.lead.concern(Concerning(name=name, title=title)))
        self.question = self.ran(
            self.lead.ask(
                Asking(
                    question="Long comments only?",
                    decisions=[Choice(decision="Long ones", lean="yes")],
                    thread="lag",
                )
            )
        )
        self.lag = self.thread_of(self.question)
        self.check = self.kept_check("Type in a long one.")
        self.voiced = self.sent(ThreadedRemark(remark="Voice works.", thread="voice"))
        self.voice = self.thread_of(self.voiced)
        self.ran(
            self.lead.concern(Concerning(name="voice", done="Say hello: it answers."))
        )
        self.documented = self.sent(ThreadedRemark(remark="Docs.", thread="docs"))
        self.docs = self.thread_of(self.documented)
        delivery.done(self.documented)

    def kept_check(self, text: str) -> int:
        """Keep a check in `lag`, as an earlier lup's `ask` did with its `checks`: no call makes one. Return its number."""
        ledger = self.delivery.inbox.ledger
        check = ledger.kept(
            Check(
                number=ledger.numbered(),
                repository=REPOSITORY,
                by=LEAD,
                at=self.clock.now(),
                text=text,
            )
        )
        ledger.drawn(
            In(
                source=check.number,
                target=self.lag.number,
                repository=REPOSITORY,
                by=LEAD,
                at=self.clock.now(),
            )
        )
        return check.number

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

    assert sorted(read) == ["docs", "home", "lag", "voice"]
    lag, voice, home, docs = read["lag"], read["voice"], read["home"], read["docs"]
    assert (lag.section, lag.state) == ("waiting on you", "waiting on the operator")
    # The check an earlier lup kept beside the question asks nothing.
    assert [(each.node, each.what, each.holds) for each in lag.asks] == [
        (work.question, "a question", True),
    ]
    assert lag.since == lag.asks[0].came
    assert (voice.section, voice.state, voice.asks) == (
        "waiting on you",
        "done to confirm",
        [],
    )
    assert isinstance(voice.status, ThreadDone)
    assert voice.status.to_try == "Say hello: it answers."
    assert voice.since == voice.status.at
    # A note unread makes @home new; the friction beside it, the pile's, doesn't.
    assert (home.section, home.new, home.pile) == ("new", [work.note], [work.friction])
    assert (docs.section, docs.new, docs.pile) == ("every thread", [], [])
    assert home.answering == LEAD
    assert work.shown(work.home).on == [LEAD]
    assert (home.members, home.earlier, home.mark) == (2, 0, None)


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
                key=on_node(work.home.number), up_to=str(work.note), at=clock.now()
            )
        ],
    )
    home = work.read()["home"]
    assert home.mark is not None
    assert (home.section, home.new, home.earlier) == ("every thread", [], 1)
    # A note after it is new; settling the thread later reads what came before.
    clock.sleep(60)
    later = work.sent(ThreadedRemark(remark="More."))
    assert work.read()["home"].new == [later]
    clock.sleep(60)
    work.delivery.concerns().settled(work.home)
    settled = work.read()["home"]
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
    # The operator's words are said on their entries; an item's, read from the item.
    assert [each.said for each in shown.entries] == [
        None,
        None,
        "Long ones.",
        "Go on.",
        None,
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


def test_a_thread_s_conversation_from_its_mark_keeps_what_a_later_entry_is_under_and_what_asks(
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

    # The question, read, stays above the answer under it; the check, read too,
    # stays for it still asks the operator.
    assert [(each.spot, each.earlier) for each in shown.entries] == [
        (Spot(node=work.question), True),
        (Spot(node=work.check), True),
        (Spot(node=answer.number, part=1), False),
    ]
    assert shown.left == 0
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


def test_the_agent_s_mark_and_the_operator_s_are_read_apart_and_cleared_waits_on_nobody(
    work: Work,
) -> None:
    concerns = work.delivery.concerns()
    concerns.settled(work.voice)
    voice = work.read()["voice"]
    # Cleared, the agent's account of what's done kept beside it.
    assert (voice.state, voice.section) == ("settled", "every thread")
    assert isinstance(voice.cleared, Settled)
    assert voice.done is not None
    assert voice.done.to_try == "Say hello: it answers."
    # Cleared while still at work, then said done: still cleared, never back
    # before the operator.
    concerns.declined(work.docs, "Not now.")
    work.ran(work.lead.concern(Concerning(name="docs", done="Read the docs.")))
    docs = work.read()["docs"]
    assert (docs.state, docs.section) == ("declined", "every thread")
    assert isinstance(docs.cleared, Declined)
    assert docs.done is not None
    assert docs.done.to_try == "Read the docs."
    # Open to the operator, said done: theirs to clear.
    work.ran(work.lead.concern(Concerning(name="lag", done="Type in a long one.")))
    lag = work.read()["lag"]
    assert (lag.state, lag.cleared) == ("done to confirm", None)
    assert lag.done is not None
    # How each reads on their dashboard, by both marks: the voice and the docs
    # said done and cleared, gone; the lag for their eyes; home open to both.
    concerns.settled(work.home)
    read = work.read()
    assert {name: each.reads for name, each in read.items()} == {
        "docs": "gone",
        "home": "quiet",
        "lag": "for your eyes",
        "voice": "gone",
    }


def test_a_reply_of_the_operator_s_in_a_thread_done_reopens_it_back_to_whoever_held_it(
    work: Work,
) -> None:
    asyncio.run(work.delivery.answer(work.voiced, [], "It still lags."))
    voice = work.read()["voice"]
    assert isinstance(voice.status, Reopened)
    assert voice.status.why == "the operator replied there"
    # Commented on in a review, a thread done is reopened the same way.
    work.ran(work.lead.concern(Concerning(name="voice", done="Say hello again.")))
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
    work.ran(work.lead.concern(Concerning(name="docs", move=[f"{answer.number}.2"])))

    docs = work.read()["docs"]
    assert docs.unanswered == [part]
    assert (docs.section, docs.asks) == ("every thread", [])
    # The passage it came from, open, on the question it answered.
    assert docs.passages == [
        Passage(
            spot=part,
            words="And write it up in the docs.",
            answer=None,
            on=work.question,
        )
    ]
    [moved] = [
        each
        for each in work.shown(docs.thread, whole=True).entries
        if each.spot == part
    ]
    assert moved.unanswered
    assert moved.said == "And write it up in the docs."

    clock.sleep(60)
    cited = work.sent(
        ThreadedRemark(remark=f"Written up, as @{answer.number}.2 asks.", thread="docs")
    )
    after = work.read()["docs"]
    assert after.unanswered == []
    # And what became of it: the note that answered it.
    assert [each.answer for each in after.passages] == [cited]
    entries = {each.spot: each for each in work.shown(after.thread, whole=True).entries}
    assert not entries[part].unanswered
    assert entries[Spot(node=cited)].under == part


def test_a_thread_whose_title_reads_as_a_name_says_what_it_s_about_from_what_s_in_it(
    work: Work,
) -> None:
    # As `send`'s `thread=` opens one named after a branch.
    named = work.sent(
        ThreadedRemark(
            remark="The shape I'd want for the list's marks.\n\nMore below.",
            thread="steady-list",
        )
    )
    read = work.read()
    assert work.thread_of(named).title == "steady-list"
    assert read["steady-list"].about == "The shape I'd want for the list's marks."
    # One with a title says nothing more.
    assert read["lag"].about is None


def test_a_thread_s_checks_are_read_with_it_each_with_the_operator_s_answer_asking_nothing(
    work: Work,
) -> None:
    [check] = work.read()["lag"].checks
    assert (check.check.number, check.answer) == (work.check, None)
    work.delivery.inbox.ledger.drawn(
        Answered(
            target=work.check,
            repository=REPOSITORY,
            by=Operator(),
            at=work.clock.now(),
            text="It held.",
        )
    )
    read = work.read()["lag"]
    [answered] = read.checks
    assert answered.answer is not None
    assert answered.answer.text == "It held."
    assert [each.node for each in read.asks] == [work.question]


def test_where_each_conversation_works_is_read_with_the_threads(work: Work) -> None:
    listed = asyncio.run(ThreadsListing(reading=work.reading()).answer(ListThreads()))
    assert isinstance(listed, ThreadsRead)
    assert [(each.conversation, each.thread) for each in listed.working] == [
        (LEAD, work.home.number)
    ]
    work.ran(work.lead.concern(Concerning(name="lag", join=True)))
    listed = asyncio.run(ThreadsListing(reading=work.reading()).answer(ListThreads()))
    assert isinstance(listed, ThreadsRead)
    assert [(each.conversation, each.thread) for each in listed.working] == [
        (LEAD, work.lag.number)
    ]
    assert LEAD in {each.conversation for each in listed.paths}


def test_settling_declining_or_reopening_a_thread_says_who_answers_for_it_by_their_path(
    work: Work,
) -> None:
    stated = work.reading().stated(work.voice.number)
    assert [(each.conversation, each.path) for each in stated.paths] == [(LEAD, "lead")]
    said = cli.thread_stated(stated, "settled")
    assert said.startswith("@voice (@")
    assert (
        '"Voice", settled: done to confirm; `lead` answers for it, and was told.'
        in said
    )


def test_a_message_written_on_a_thread_reaches_whoever_answers_for_it_and_shows_there_open_until_they_answer(
    work: Work, clock: FakeClock
) -> None:
    clock.sleep(60)
    work.delivery.inbox.drafted(
        Draft(
            letters=[
                Letter(to=LEAD, thread=work.lag.number, text="Long ones only, please.")
            ]
        )
    )
    [review] = asyncio.run(work.delivery.reviewed()).reviews
    assert review.recipient == LEAD
    [part] = work.read()["lag"].unanswered
    assert part.node == review.number
    [entry] = [
        each for each in work.shown(work.lag, whole=True).entries if each.spot == part
    ]
    assert (entry.said, entry.to, entry.unanswered) == (
        "Long ones only, please.",
        LEAD,
        True,
    )
    # It's told to its recipient as their message, saying where it's written.
    told = work.delivery.inbox.item(review.number)
    assert isinstance(told.reason, Review)
    [letter] = told.reason.letters
    assert letter.thread == work.lag.number
    # Their turn's last words answering the review, in the thread, answer it, citing it or not.
    clock.sleep(60)
    ending = work.delivery.inbox.made(
        Message(kind="note", text="Done.", ending=True, answers=[review.number]),
        LEAD,
        Operator(),
        Path("/work/lead"),
        clock.now(),
    )
    work.delivery.concerns().landed(ending, work.lag)
    assert work.read()["lag"].unanswered == []


def test_what_the_operator_and_an_agent_say_in_a_concern_shows_in_that_agent_s_messages(
    work: Work, clock: FakeClock
) -> None:
    """The thread's own buffer goes, its conversation read in each agent's `messages` drawer instead: their exchange, both ways, is there."""

    def drawer(party: Conversation) -> Exchanged:
        listed = asyncio.run(
            ItemsListing(delivery=work.delivery).answer(ListItems(conversation=party))
        )
        assert isinstance(listed, Exchanged)
        return listed

    clock.sleep(60)
    # The operator writes on the concern, to whoever answers for it.
    work.delivery.inbox.drafted(
        Draft(
            letters=[
                Letter(to=LEAD, thread=work.lag.number, text="Long ones only, please.")
            ]
        )
    )
    [review] = asyncio.run(work.delivery.reviewed()).reviews
    [part] = work.read()["lag"].unanswered
    clock.sleep(60)
    # The agent answers that passage there, citing it.
    answer = work.sent(
        ThreadedRemark(
            remark=f"Long ones only, as @{part.node}.{part.part} says.", thread="lag"
        )
    )
    assert work.read()["lag"].unanswered == []
    # The operator answers the agent's question in the concern.
    clock.sleep(60)
    ruled = asyncio.run(
        work.delivery.answer(work.question, [Ruling(decision=1, verdict="leaning")], "")
    )

    lead = drawer(LEAD)
    received = {each.item.number: each.words for each in lead.received}
    sent = {each.item.number: each.words for each in lead.sent}
    told = received[review.number]
    assert told is not None
    assert "Long ones only, please." in told.text
    assert sent[answer] is not None
    assert sent[work.question] is not None
    assert received[ruled.number] is not None


def test_a_message_to_no_one_stays_in_its_thread_as_the_operator_s_waking_nobody(
    work: Work, clock: FakeClock
) -> None:
    clock.sleep(60)
    work.delivery.inbox.drafted(
        Draft(letters=[Letter(thread=work.docs.number, text="Note to self: docs.")])
    )
    dispatched = asyncio.run(work.delivery.reviewed())
    assert dispatched.reviews == []
    docs = work.read()["docs"]
    assert (docs.section, docs.asks, docs.new) == ("every thread", [], [])
    [note] = [
        work.delivery.inbox.item(each.spot.node)
        for each in work.shown(work.docs, whole=True).entries
        if each.spot.node != work.documented
    ]
    assert (note.sender, note.recipient) == (Operator(), Operator())
    assert isinstance(note.reason, Message)
    assert note.reason.text == "Note to self: docs."
    assert note.reason.repository == REPOSITORY
    assert isinstance(note.state, Done)


def test_a_comment_on_lines_of_a_concern_s_body_reaches_whoever_answers_for_it_quoting_them(
    work: Work, clock: FakeClock
) -> None:
    work.ran(
        work.lead.concern(
            Concerning(name="lag", body="It jumps on a long comment.\nNot a short one.")
        )
    )
    on = Quote(
        text="Not a short one.",
        block=f"concern {work.lag.number} body",
        lines=["Not a short one."],
        start=0,
        end=16,
    )
    clock.sleep(60)
    work.delivery.inbox.drafted(
        Draft(
            letters=[
                Letter(to=LEAD, thread=work.lag.number, quote=on, text="It does too."),
                Letter(thread=work.docs.number, quote=on, text="Note to self."),
            ]
        )
    )
    [review] = asyncio.run(work.delivery.reviewed()).reviews

    told = work.delivery.said(work.delivery.inbox.item(review.number))
    [note] = [
        each
        for each in work.delivery.inbox.items.values()
        if each.sender == Operator()
        and isinstance(each.reason, Message)
        and each.reason.repository == REPOSITORY
    ]

    assert (
        '<message id="'
        f'{review.number}.1" thread="lag">\n<quote of="body">Not a short one.</quote>\n'
        "It does too.\n</message>"
    ) in told
    assert isinstance(note.reason, Message)
    assert note.reason.text == "> Not a short one.\n\nNote to self."


def test_a_message_on_a_thread_is_refused_to_no_one_on_none_or_to_another_repository(
    work: Work,
) -> None:
    work.delivery.inbox.drafted(Draft(letters=[Letter(text="To nobody.")]))
    with pytest.raises(InboxError, match="written on a thread"):
        asyncio.run(work.delivery.reviewed())
    elsewhere = LEAD.model_copy(update={"repository": Path("/work/other.git")})
    with pytest.raises(InboxError, match="of its repository"):
        work.delivery.on_thread(
            Letter(to=elsewhere, thread=work.lag.number, text="Here.")
        )


def test_writing_on_a_thread_done_reopens_it(work: Work) -> None:
    work.delivery.inbox.drafted(
        Draft(letters=[Letter(to=LEAD, thread=work.voice.number, text="It lags.")])
    )
    asyncio.run(work.delivery.reviewed())
    voice = work.read()["voice"]
    assert isinstance(voice.status, Reopened)


def own_words(work: Work, text: str) -> int:
    """Send the operator's message to the lead under their banner, as the dashboard does; return the review it went as, the operator's own words."""
    work.delivery.inbox.drafted(Draft(letters=[Letter(to=LEAD, text=text)]))
    [review] = asyncio.run(work.delivery.reviewed()).reviews
    return review.number


def test_a_mark_on_the_operator_s_own_words_in_a_thread_is_dropped_and_said_the_approval_beside_it_going_through(
    work: Work, clock: FakeClock
) -> None:
    clock.sleep(60)
    own = own_words(work, "Ship the parser first.")
    # Moved into a thread, as an agent moves one with `thread`, where the review shows it.
    work.delivery.concerns().moved(LEAD, work.lag, str(own))
    standing = work.delivery.inbox.item(own).state
    approval = work.delivery.inbox.made(
        Approval(
            text="Approve the host zone at abc?",
            summary="",
            repository=REPOSITORY,
            fingerprint="abc",
        ),
        Operator(),
        Operator(),
        None,
        clock.now(),
    )
    work.delivery.inbox.drafted(Draft(done=[own, approval.number]))

    dispatched = asyncio.run(work.delivery.reviewed())

    assert [each.number for each in dispatched.approved] == [approval.number]
    assert dispatched.unanswerable == [
        Unanswerable(
            number=own,
            part="done",
            said=(
                f"@{own} not marked done: it's a review from the operator, which a "
                "reply doesn't answer"
            ),
        )
    ]
    assert dispatched.reviews == []
    assert work.delivery.inbox.item(own).state == standing
    # Dropped, it's gone from the draft, never refused at the next send.
    assert work.delivery.inbox.draft() == Draft()


def test_the_operator_s_comment_on_their_own_words_goes_on_their_thread_to_whoever_answers_for_it(
    work: Work, clock: FakeClock
) -> None:
    clock.sleep(60)
    own = own_words(work, "Ship the parser first.\n\nThen the cache.")
    work.delivery.concerns().moved(LEAD, work.lag, str(own))
    elsewhere = own_words(work, "Rename it.")
    parked = own_words(work, "Later, maybe.")
    on_passage = Quote(text="Then the cache.", start=24, end=39)
    work.delivery.inbox.drafted(
        Draft(
            comments=[
                Comment(
                    id="c1", item=own, quote=on_passage, text="Or the cache first."
                ),
                Comment(id="c2", item=elsewhere, text="Not yet."),
            ],
            declined=[elsewhere],
            moves=[Destined(id="later", item=parked, to=Destination(pile="Later"))],
        )
    )

    dispatched = asyncio.run(work.delivery.reviewed())

    [review] = dispatched.reviews
    assert review.recipient == LEAD
    assert isinstance(review.reason, Review)
    assert review.reason.covers == []
    assert review.reason.letters == [
        Letter(
            id="c1",
            to=LEAD,
            thread=work.lag.number,
            text=f"On @{own}.2:\n\n> Then the cache.\n\nOr the cache first.",
        )
    ]
    why = "it's a review from the operator, which a reply doesn't answer"
    assert [each.said for each in dispatched.unanswerable] == [
        f"the comment on @{own} sent on @lag to `lead`, as a message there: {why}",
        f"@{elsewhere} not declined: {why}",
        f"the comment on @{elsewhere} kept drafted: {why}, and it's in no thread",
        f"@{parked} not moved: {why}",
    ]
    # It shows in the thread as a message written there, open until the lead answers.
    assert [each.node for each in work.read()["lag"].unanswered] == [review.number]
    # The words with nowhere to go stay drafted, never lost.
    assert work.delivery.inbox.draft() == Draft(
        comments=[Comment(id="c2", item=elsewhere, text="Not yet.")]
    )


def test_a_thread_s_conversation_shows_the_latest_few_read_before_what_s_new_as_context(
    work: Work, clock: FakeClock
) -> None:
    def step(at: int) -> int:
        clock.sleep(60)
        return work.sent(ThreadedRemark(remark=f"Step {at}.", thread="docs"))

    read = [step(at) for at in range(5)]
    clock.sleep(60)
    work.delivery.inbox.marks.moved(
        REPOSITORY,
        CORE,
        [
            ReviewMark(
                key=on_node(work.docs.number), up_to=str(read[-1]), at=clock.now()
            )
        ],
    )
    clock.sleep(60)
    fresh = work.sent(ThreadedRemark(remark="Step 5.", thread="docs"))

    shown = work.shown(work.docs)

    assert [(each.spot.node, each.seen) for each in shown.entries] == [
        (read[2], True),
        (read[3], True),
        (read[4], True),
        (fresh, False),
    ]
    assert shown.left == 3
    none = asyncio.run(
        ThreadShowing(reading=work.reading()).answer(
            ShowThread(number=work.docs.number, seen=0)
        )
    )
    assert isinstance(none, ThreadShown)
    assert [each.spot.node for each in none.entries] == [fresh]
    assert none.left == 6


def moving(work: Work, *moves: Destined) -> Dispatched:
    """Send a draft moving what `moves` name, as the operator does with Space s and Ctrl+Enter."""
    work.delivery.drafted(Draft(moves=list(moves)))
    return asyncio.run(work.delivery.reviewed())


def into(
    number: int, *, thread: int | None = None, pile: str | None = None
) -> Destined:
    """Move item `number` into `thread`, or the pile titled `pile`."""
    return Destined(item=number, to=Destination(thread=thread, pile=pile))


def worker(work: Work) -> Speaker:
    """A subagent of the lead's, heard in their launch, working where the lead does."""
    party = LEAD.model_copy(update={"agent": "a1"})
    work.delivery.heard_in(party, work.lead.launch, LEAD)
    return Speaker(delivery=work.delivery, launch=work.lead.launch, party=party)


def test_the_pile_holds_each_friction_still_waiting_wherever_the_thread_s_mark_is(
    work: Work, clock: FakeClock
) -> None:
    clock.sleep(60)
    work.delivery.inbox.marks.moved(
        REPOSITORY,
        CORE,
        [
            ReviewMark(
                key=on_node(work.home.number),
                up_to=str(work.friction),
                at=clock.now(),
            )
        ],
    )
    marked = work.read()["home"]
    work.delivery.done(work.friction)

    assert (marked.earlier, marked.new, marked.pile) == (2, [], [work.friction])
    assert work.read()["home"].pile == []


def test_the_operator_moves_frictions_and_how_it_felt_into_a_new_pile_at_the_top_each_staying_where_it_landed_as_it_stood(
    work: Work, clock: FakeClock
) -> None:
    sub = worker(work)
    rebuilt = work.ran(
        sub.concern(
            Concerning(
                text="The engine rebuilt for four minutes, saying nothing.",
                name="home",
            )
        )
    )
    felt = work.ran(sub.how_it_felt(HowItFelt(text="Steady, but the gate wore.")))
    clock.sleep(60)
    pile = "The gate hangs, silently"
    sent = moving(
        work,
        into(work.friction, pile=pile),
        into(rebuilt, pile=pile),
        into(felt, pile=pile),
    )

    read = work.read()
    gate = read["the-gate-hangs-silently"]
    assert (gate.thread.title, gate.thread.parent, gate.thread.holder) == (
        pile,
        None,
        None,
    )
    assert gate.thread.by == Operator()
    assert gate.answering is None
    assert gate.moved == [work.friction, rebuilt, felt]
    assert [(each.item, each.into, each.to) for each in sent.moved] == [
        (each, gate.thread.number, "into @the-gate-hangs-silently")
        for each in [work.friction, rebuilt, felt]
    ]
    # Destined says nothing of whether it waits on the operator: the pile is where they'll read it.
    assert all(
        isinstance(work.delivery.inbox.item(each).state, Waiting)
        for each in [work.friction, rebuilt]
    )
    # Each reads where it landed, saying where it went; and in the pile, as moved there.
    landed = {
        each.spot.node: each for each in work.shown(work.home, whole=True).entries
    }
    assert [landed[each].went for each in [work.friction, rebuilt, felt]] == [
        gate.thread.number
    ] * 3
    gathered = work.shown(gate.thread, whole=True)
    assert [(each.spot.node, each.moved) for each in gathered.entries] == [
        (each, True) for each in [work.friction, rebuilt, felt]
    ]
    assert gathered.on == []


def test_an_item_moved_into_a_concern_someone_answers_for_is_told_them_whole_by_the_operator(
    work: Work, clock: FakeClock
) -> None:
    sub = worker(work)
    felt = work.ran(sub.how_it_felt(HowItFelt(text="Steady, but the gate wore.")))
    clock.sleep(60)
    moving(work, into(felt, thread=work.docs.number))

    words = work.delivery.taken_words(LEAD)
    assert any(
        f'<moved thread="docs" item="{felt}" kind="how it felt" from="lead/a1" by="operator">'
        in each
        for each in words
    )
    assert work.read()["docs"].moved == [felt]


def test_an_item_moved_into_a_concern_done_reopens_it_and_one_moved_again_leaves_the_last(
    work: Work, clock: FakeClock
) -> None:
    clock.sleep(60)
    moving(work, into(work.friction, thread=work.voice.number))
    clock.sleep(60)
    moving(work, into(work.friction, thread=work.docs.number))

    read = work.read()
    assert isinstance(read["voice"].status, Reopened)
    assert read["voice"].moved == []
    assert [each.spot.node for each in work.shown(work.voice, whole=True).entries] == [
        work.voiced
    ]
    assert read["docs"].moved == [work.friction]


@pytest.mark.parametrize(
    ("what", "said"),
    [
        ("home", "is in @home already"),
        ("settled", "is settled: reopen it"),
        ("agent", "goes into a concern or a pile, not to an agent"),
        ("nobody", "goes into a concern or a pile, not to an agent"),
    ],
)
def test_moving_an_item_is_refused_saying_why_and_moves_nothing(
    work: Work, what: str, said: str
) -> None:
    def move() -> Destined:
        match what:
            case "home":
                return into(work.friction, thread=work.home.number)
            case "settled":
                work.delivery.concerns().settled(work.docs)
                return into(work.friction, thread=work.docs.number)
            case "agent":
                return Destined(item=work.friction, to=Destination(to=LEAD))
            case _:
                return Destined(item=work.friction, to=Destination())

    with pytest.raises(InboxError, match=said):
        moving(work, into(work.note, pile="Later"), move())
    assert "later" not in work.read()
    assert work.read()["home"].moved == []


def test_ctrl_enter_on_one_destination_sends_what_reaches_it_alone_the_rest_staying_drafted(
    work: Work, clock: FakeClock
) -> None:
    other = worker(work)
    clock.sleep(60)
    to_other = Letter(id="m1", to=other.party, text="Look at the cache.")
    later = Destined(id="d1", item=work.friction, to=Destination(pile="Later"))
    work.delivery.drafted(
        Draft(
            comments=[Comment(id="c1", item=work.note, text="Built where?")],
            letters=[to_other],
            moves=[later],
        )
    )

    lead = asyncio.run(work.delivery.reviewed(Destination(to=LEAD)))

    [review] = lead.reviews
    assert review.recipient == LEAD
    assert lead.moved == []
    assert work.delivery.inbox.draft() == Draft(letters=[to_other], moves=[later])
    # A pile not opened yet, by its title; then whoever's left.
    piled = asyncio.run(work.delivery.reviewed(Destination(pile="Later")))
    assert [(each.item, each.to) for each in piled.moved] == [
        (work.friction, "into @later")
    ]
    assert piled.reviews == []
    assert work.delivery.inbox.draft() == Draft(letters=[to_other])
    rest = asyncio.run(work.delivery.reviewed(Destination(to=other.party)))
    assert [each.recipient for each in rest.reviews] == [other.party]
    assert work.delivery.inbox.draft() == Draft()


def test_a_destination_names_one_place_at_most() -> None:
    with pytest.raises(ValueError, match="one of them"):
        Destination(thread=4, pile="Later")


def test_a_comment_sent_to_another_agent_reaches_them_quoting_its_passage_and_leaves_its_item_waiting(
    work: Work, clock: FakeClock
) -> None:
    other = worker(work)
    clock.sleep(60)
    work.delivery.drafted(
        Draft(
            comments=[
                Comment(
                    id="c1",
                    item=work.note,
                    quote=Quote(text="Built.", start=0, end=6),
                    text="Check it builds on the phone.",
                    sent=Destination(to=other.party),
                )
            ]
        )
    )

    dispatched = asyncio.run(work.delivery.reviewed())

    [review] = dispatched.reviews
    assert review.recipient == other.party
    assert isinstance(review.reason, Review)
    assert review.reason.covers == []
    [letter] = review.reason.letters
    assert (letter.to, letter.thread) == (other.party, None)
    assert letter.text == (
        f"On @{work.note}.1:\n\n> Built.\n\nCheck it builds on the phone."
    )
    assert isinstance(work.delivery.inbox.item(work.note).state, Waiting)
    assert work.delivery.inbox.draft() == Draft()


def test_a_comment_sent_to_a_pile_stays_there_as_the_operator_s_words_waking_nobody_until_someone_takes_it(
    work: Work, clock: FakeClock
) -> None:
    other = worker(work)
    clock.sleep(60)
    work.delivery.drafted(
        Draft(
            comments=[
                Comment(
                    id="c1",
                    item=work.note,
                    text="Look at this once the parser lands.",
                    sent=Destination(pile="Later"),
                )
            ]
        )
    )
    work.delivery.taken_words(LEAD)

    dispatched = asyncio.run(work.delivery.reviewed())

    assert dispatched.reviews == []
    later = work.read()["later"]
    assert later.answering is None
    [kept] = [
        each for each in work.shown(later.thread, whole=True).entries if each.member
    ]
    note = work.delivery.inbox.item(kept.spot.node)
    assert note.sender == Operator()
    assert isinstance(note.state, Done)
    assert work.delivery.taken_words(LEAD) == []

    # Given to an agent, the pile goes whole: what the operator kept there among it.
    moving(work, Destined(thread=later.thread.number, to=Destination(to=other.party)))
    words = work.delivery.taken_words(other.party)
    assert words[0].startswith('lup: the operator handed you @later, "Later"')
    assert "Look at this once the parser lands." in words[1]


def test_a_message_on_a_concern_moved_to_another_agent_goes_with_it_to_them(
    work: Work, clock: FakeClock
) -> None:
    other = worker(work)
    clock.sleep(60)
    work.delivery.drafted(
        Draft(
            letters=[Letter(id="m1", to=LEAD, thread=work.lag.number, text="Take it.")],
            moves=[Destined(thread=work.lag.number, to=Destination(to=other.party))],
        )
    )

    dispatched = asyncio.run(work.delivery.reviewed())

    [review] = dispatched.reviews
    assert review.recipient == other.party
    assert isinstance(review.reason, Review)
    assert [(each.to, each.thread) for each in review.reason.letters] == [
        (other.party, work.lag.number)
    ]
    assert [(each.thread, each.to) for each in dispatched.moved] == [
        (work.lag.number, "to lead/a1")
    ]
    assert work.read()["lag"].answering == other.party


@pytest.mark.parametrize(
    ("where", "said"),
    [
        ("itself", "can't go under itself"),
        ("nobody", "not to `No agent`"),
    ],
)
def test_sending_somewhere_it_can_t_go_is_refused_moving_nothing(
    work: Work, where: str, said: str
) -> None:
    def draft() -> Draft:
        match where:
            case "itself":
                work.ran(
                    work.lead.concern(
                        Concerning(name="tabs", title="Tabs", under="lag")
                    )
                )
                tabs = work.delivery.concerns().named(REPOSITORY, "tabs")
                return Draft(
                    moves=[
                        Destined(item=work.note, to=Destination(pile="Later")),
                        Destined(
                            thread=work.lag.number,
                            to=Destination(thread=tabs.number),
                        ),
                    ]
                )
            case _:
                return Draft(
                    moves=[Destined(item=work.note, to=Destination(pile="Later"))],
                    comments=[Comment(item=work.note, text="Hm.", sent=Destination())],
                )

    work.delivery.drafted(draft())
    with pytest.raises(InboxError, match=said):
        asyncio.run(work.delivery.reviewed())
    assert "later" not in work.read()


def ended(work: Work) -> None:
    """End the lead's launch, as a session ends."""
    work.delivery.layout.record("lead").unlink()


def test_a_thread_whose_holder_ended_reads_as_nobody_running_saying_who_left_it(
    work: Work,
) -> None:
    before = work.read()["home"]
    ended(work)
    after = work.read()

    assert (before.state, before.answering, before.left_by) == ("working", LEAD, None)
    home = after["home"]
    assert (home.answering, home.left_by) == (None, LEAD)
    assert home.state != "working"
    # Under it, nobody holds what the lead opened, and nobody above answers now.
    assert (after["docs"].state, after["docs"].left_by) == ("nobody running", LEAD)
    assert after["lag"].state == "waiting on the operator"
    assert after["voice"].state == "done to confirm"
    listed = asyncio.run(ThreadsListing(reading=work.reading()).answer(ListThreads()))
    assert isinstance(listed, ThreadsRead)
    assert LEAD in {each.conversation for each in listed.paths}


def test_a_nested_thread_whose_holder_ended_is_answered_for_by_who_holds_above_it_and_left_by_nobody(
    work: Work,
) -> None:
    sub = worker(work)
    work.ran(
        sub.concern(Concerning(name="tabs", title="Tabs", under="home", hold=True))
    )
    place = work.delivery.inbox.whereabouts[sub.party.key()]
    work.delivery.inbox.placed(place.model_copy(update={"ended": work.clock.now()}))

    tabs = work.read()["tabs"]

    assert tabs.thread.holder == sub.party
    assert (tabs.answering, tabs.left_by, tabs.state) == (LEAD, None, "working")


def test_a_thread_opened_by_whom_nobody_running_answers_for_says_its_opener_left_it_and_the_operator_s_nobody(
    work: Work,
) -> None:
    moving(work, into(work.friction, pile="The gate"))
    ended(work)

    read = work.read()

    assert read["docs"].thread.holder is None
    assert read["docs"].left_by == LEAD
    gate = read["the-gate"]
    assert (gate.thread.by, gate.answering, gate.left_by) == (Operator(), None, None)


def test_what_s_nothing_to_list_is_empty_bodiless_nobody_s_on_and_nothing_said_of_it_or_under_it(
    work: Work,
) -> None:
    for name, title, under in [
        ("empty", "Empty", None),
        ("parked", "Parked", None),
        ("worked", "Worked in", None),
        ("parent", "Parent", None),
        ("child", "Child", "parent"),
        ("full", "Full", None),
        ("holding", "Holding", "full"),
        ("bodied", "Bodied", None),
    ]:
        work.ran(work.lead.concern(Concerning(name=name, title=title, under=under)))
    work.ran(work.lead.concern(Concerning(name="parked", park=Parking(issue=12))))
    work.ran(work.lead.concern(Concerning(name="bodied", body="What it is.")))
    work.sent(ThreadedRemark(remark="Here.", thread="full"))
    held = work.read()
    ended(work)
    # Another session goes on working in one, holding nothing.
    other = work.lead.launch.model_copy(update={"launch": "other"})
    record = work.delivery.layout.record("other")
    record.write_text(other.model_dump_json())
    party = Conversation(repository=REPOSITORY, runtime="claude", session="s2")
    work.delivery.heard_in(party, other, None)
    work.ran(
        Speaker(delivery=work.delivery, launch=other, party=party).concern(
            Concerning(name="worked", join=True)
        )
    )

    read = work.read()

    # While the lead goes on, they hold each, and none is bare.
    assert not any(each.bare for each in held.values())
    assert {name for name, each in read.items() if each.bare} == {
        "empty",
        "parent",
        "child",
        "holding",
    }
    assert read["parked"].state == "parked"
    assert not read["worked"].bare
    assert not read["full"].bare
    # A body is something in it to read, and the review carries it.
    assert not read["bodied"].bare
    body = read["bodied"].body
    assert body is not None
    assert (body.by, body.text) == (LEAD, "What it is.")
    assert read["full"].body is None


def test_an_earlier_lup_s_root_is_left_out_of_the_review_what_s_under_it_at_the_top(
    work: Work,
) -> None:
    ledger = work.delivery.inbox.ledger
    root = ledger.kept(
        Thread(
            number=ledger.numbered(),
            repository=REPOSITORY,
            by=LEAD,
            at=work.clock.now(),
            name="old-lead",
            title=ROOT,
            holder=LEAD,
        )
    )
    under = ledger.kept(
        Thread(
            number=ledger.numbered(),
            repository=REPOSITORY,
            by=LEAD,
            at=work.clock.now(),
            name="sshole",
            title="What a room can't see",
            parent=root.number,
        )
    )
    ledger.drawn(
        In(
            source=work.note,
            target=root.number,
            repository=REPOSITORY,
            by=Lup(),
            at=work.clock.now(),
        )
    )

    read = work.read()

    assert "old-lead" not in read
    sshole = read["sshole"]
    assert (sshole.thread.parent, sshole.answering, sshole.left_by) == (
        None,
        None,
        LEAD,
    )
    assert sshole.state == "nobody running"
    assert work.note not in [
        each.spot.node for each in work.shown(work.home, whole=True).entries
    ]
    with pytest.raises(InboxError, match="no thread"):
        asyncio.run(
            ThreadShowing(reading=work.reading()).answer(ShowThread(number=root.number))
        )
    assert under.number == sshole.thread.number
