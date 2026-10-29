"""Threads as agents work in them: where each works, what lands where, who's told, the `thread` tool, checks, a thread read whole, and a session's root named as they are."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup.sessions import results
from lup_dev import cli
from lup_dev.host.names import Names
from lup_dev.host.protocol import Limits, Register
from lup_dev.host.pushes import Pushes
from lup_dev.inbox.bearings import Repository, RepositoryBearings
from lup_dev.inbox.concerns import ROOT, slugged
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.mentions import mentioned
from lup_dev.inbox.notices import Notices
from lup_dev.inbox.reading import Narrowing, Reader
from lup_dev.inbox.roots import RootNames
from lup_dev.inbox.store import (
    KINDS,
    Comment,
    Inbox,
    InboxError,
    Letter,
    Review,
)
from lup_dev.inbox.tools import (
    Asking,
    Parking,
    Sending,
    Speaker,
    ThreadedFriction,
    ThreadedRemark,
    Threading,
)
from lup_dev.layout import Layout
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.parties import Conversation, Operator
from lup_ledger.threads import (
    Answered,
    Check,
    Done,
    IssueClosed,
    Moved,
    Parked,
    Refers,
    Settled,
    Thread,
)

if TYPE_CHECKING:
    from conftest import FakeClock

REPOSITORY = Path("/work/lup.git")


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


def launched(delivery: Delivery, name: str, session: str) -> Register:
    """Serve a launch named `name`, its session `session` heard in it: its record kept where the service keeps one, its name kept for the session."""
    register = Register(
        launch=name,
        runtime="claude",
        worktree=Path(f"/work/{name}"),
        repository=REPOSITORY,
        judge=Path("/judge/lup-dev"),
        limits=Limits(actions=[], protected=[]),
        github=None,
    )
    record = delivery.layout.record(name)
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(register.model_dump_json())
    Names(path=delivery.layout.names).keep(session, name)
    delivery.heard_in(main(session), register, None)
    return register


def main(session: str) -> Conversation:
    return Conversation(repository=REPOSITORY, runtime="claude", session=session)


def spawned(
    delivery: Delivery, register: Register, parent: Conversation, agent: str, name: str
) -> Conversation:
    """Hear a subagent `agent` of `parent`'s session, spawned by `parent`, named `name`."""
    party = parent.model_copy(update={"agent": agent})
    delivery.heard_in(party, register, parent, name)
    return party


def speaker(delivery: Delivery, register: Register, party: Conversation) -> Speaker:
    return Speaker(delivery=delivery, launch=register, party=party)


def said(coroutine: object) -> str:
    """Run a tool's call, and return what it says."""
    assert asyncio.iscoroutine(coroutine)
    return asyncio.run(coroutine).text


def told(delivery: Delivery, party: Conversation) -> list[str]:
    """Take what lup left for `party` to be told at their next call."""
    return delivery.taken_words(party)


def thread_of(delivery: Delivery, number: int) -> Thread | None:
    return delivery.concerns().containing(number)


def test_a_session_s_items_land_in_a_root_thread_named_as_they_are_held_by_them(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "inbox-scaling", "s1")
    one = speaker(delivery, register, main("s1"))

    first = said(one.note(ThreadedRemark(remark="It rests on the cache.")))
    second = said(one.note(ThreadedRemark(remark="And on the clock.")))

    root = thread_of(delivery, 1)
    assert root is not None
    assert (root.number, root.name, root.title, root.parent, root.holder) == (
        2,
        "inbox-scaling",
        ROOT,
        None,
        main("s1"),
    )
    assert thread_of(delivery, 3) == root
    assert first == "Your note is with the operator, @1. You can carry on."
    assert second == "Your note is with the operator, @3. You can carry on."
    assert delivery.inbox.whereabouts[main("s1").key()].root == 2
    assert told(delivery, main("s1")) == []


def test_a_subagent_starts_on_its_parent_s_thread_and_thread_names_one_or_opens_it(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.note(ThreadedRemark(remark="Routing.")))
    worker = spawned(delivery, register, main("s1"), "a1", "parser")
    work = speaker(delivery, register, worker)

    opened = said(
        work.note(ThreadedRemark(remark="The lexer drops tabs.", thread="Tabs vanish"))
    )
    again = said(work.note(ThreadedRemark(remark="Fixed.", thread="tabs-vanish")))
    plain = said(work.note(ThreadedRemark(remark="Back on the parse.")))

    tabs = delivery.concerns().named(REPOSITORY, "tabs-vanish")
    assert (tabs.title, tabs.parent, tabs.holder) == ("Tabs vanish", 2, None)
    assert (
        opened
        == "Your note is with the operator, @4, in @tabs-vanish. You can carry on."
    )
    assert (
        again
        == "Your note is with the operator, @5, in @tabs-vanish. You can carry on."
    )
    # Naming a thread on a call never moves the agent: they still work where they started.
    assert plain == "Your note is with the operator, @6. You can carry on."
    assert thread_of(delivery, 6) == thread_of(delivery, 1)
    # Nobody holds the new thread, so the root's holder answers for it: told
    # nothing of their own subagent's notes, which their runtime tells them,
    # and each note of anyone else whole.
    assert told(delivery, main("s1")) == []
    other = launched(delivery, "other", "s2")
    said(
        speaker(delivery, other, main("s2")).note(
            ThreadedRemark(remark="Tabs here too.", thread="tabs-vanish")
        )
    )
    assert told(delivery, main("s1")) == [
        (
            '<landed thread="tabs-vanish" item="7" kind="note" from="other">'
            "Tabs here too.</landed>"
        )
    ]


def test_a_number_or_a_node_that_isn_t_a_thread_is_refused_on_a_send(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    one = speaker(delivery, register, main("s1"))
    said(one.note(ThreadedRemark(remark="First.")))

    refused = said(one.note(ThreadedRemark(remark="Again.", thread="@1")))
    missing = said(one.note(ThreadedRemark(remark="Again.", thread="999")))

    assert refused == "Not sent: `@1` is a `inbox:item`, not a thread"
    assert missing == "Not sent: no thread of this repository is `999`"
    assert len(delivery.inbox.items) == 1


def test_whoever_holds_a_thread_is_told_each_item_whole_and_others_on_it_a_line(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.note(ThreadedRemark(remark="Routing.")))
    holder = spawned(delivery, register, main("s1"), "a1", "fixer")
    reviewer = spawned(delivery, register, main("s1"), "a2", "reviewer")
    said(
        speaker(delivery, register, holder).thread(
            Threading(name="lag", title="The cursor jumps", hold=True)
        )
    )
    said(
        speaker(delivery, register, reviewer).note(
            ThreadedRemark(remark="Seen it twice.", thread="lag")
        )
    )
    told(delivery, holder)

    said(
        speaker(delivery, register, main("s1")).send(
            Sending(
                to="operator", kind="note", text="Typing fast moves it.", thread="lag"
            )
        )
    )
    said(
        speaker(delivery, register, reviewer).how_it_felt(
            results.HowItFelt(text="Calm.")
        )
    )

    assert told(delivery, holder) == [
        '<landed thread="lag" item="5" kind="note" from="dev">Typing fast moves it.</landed>'
    ]
    assert told(delivery, reviewer) == [
        "lup: in @lag, a note from `dev`, @5: Typing fast moves it."
    ]
    # How it felt lands where its sender started, the root, and is told to nobody.
    assert thread_of(delivery, 6) == thread_of(delivery, 1)
    assert told(delivery, main("s1")) == []


def test_a_friction_isn_t_told_to_the_parent_holding_the_thread_who_has_its_copy(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    said(speaker(delivery, register, main("s1")).note(ThreadedRemark(remark="Go.")))
    worker = spawned(delivery, register, main("s1"), "a1", "parser")

    answer = said(
        speaker(delivery, register, worker).friction(
            ThreadedFriction(text="The gate hung.", title="gate hangs")
        )
    )

    assert answer == (
        "Thanks: your friction is with the operator, @3, and your parent has it "
        "too. You can carry on."
    )
    assert delivery.inbox.item(3).reason.model_dump()["title"] == "gate hangs"
    assert told(delivery, main("s1")) == []


def test_an_at_name_of_another_thread_draws_a_reference_to_it(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    one = speaker(delivery, register, main("s1"))
    said(one.thread(Threading(name="lag", title="Lag")))

    said(one.note(ThreadedRemark(remark="This touches @lag, not `@dev`, and @dev.")))

    references = delivery.inbox.ledger.drawn_to(2, Refers)
    assert [(each.source, each.target) for each in references] == [(3, 2)]
    assert mentioned("@lag and @2 but not @lag.3 or @2.1[x]") == ["lag", "2", "lag.3"]


def test_the_thread_tool_opens_holds_hands_moves_parks_and_says_done(
    delivery: Delivery, clock: FakeClock
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.note(ThreadedRemark(remark="Go.")))
    worker = spawned(delivery, register, main("s1"), "a1", "fixer")
    review = asyncio.run(
        delivery.posted(
            Review(
                covers=[1],
                comments=[Comment(item=1, text="The cursor jumps when I type.")],
                letters=[Letter(to=main("s1"), text="And the voice branch.")],
            ),
            Operator(),
            main("s1"),
            None,
        )
    )

    opened = said(
        lead.thread(
            Threading(
                name="lag",
                title="The cursor jumps",
                move=[f"{review.number}.1"],
                hand="fixer",
            )
        )
    )
    standing = said(lead.thread(Threading(name="lag")))
    clock.sleep(60)
    parked = said(
        lead.thread(
            Threading(name="voice", title="The voice branch", park=Parking(issue=12))
        )
    )
    done = said(
        speaker(delivery, register, worker).thread(
            Threading(name="lag", done="Type fast in a long comment: it stays put.")
        )
    )

    lag = delivery.concerns().named(REPOSITORY, "lag")
    assert opened == (
        "Opened @lag, under @dev.\n"
        "@lag is `dev/fixer`'s now, who's told.\n"
        f"Moved @{review.number}.1 into @lag."
    )
    assert lag.holder == worker
    assert delivery.inbox.whereabouts[worker.key()].thread == lag.number
    assert delivery.inbox.whereabouts[main("s1").key()].thread is None
    assert standing == (
        '@lag, "The cursor jumps", under @dev, held by `dev/fixer`: working; 1 '
        "part of the operator's words unanswered."
    )
    assert told(delivery, worker) == [
        'lup: `dev` handed you @lag, "The cursor jumps": you hold it, and what you send lands there.',
        f'<moved thread="lag" part="{review.number}.1" by="dev">The cursor jumps when I type.</moved>',
    ]
    moved = delivery.inbox.ledger.drawn_to(lag.number, Moved)
    assert [(each.source, each.part) for each in moved] == [(review.number, 1)]
    assert (
        parked
        == "Opened @voice, under @dev.\n@voice is parked until issue #12 closing."
    )
    voice = delivery.concerns().named(REPOSITORY, "voice")
    status = delivery.concerns().standing(voice).status
    assert isinstance(status, Parked)
    assert status.until == [IssueClosed(issue=12)]
    assert done == "@lag is done, for the operator to confirm."
    assert isinstance(delivery.concerns().standing(lag).status, Done)
    assert told(delivery, main("s1")) == []


def test_a_part_moved_into_a_thread_is_answered_by_whoever_answers_for_it_citing_it(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.note(ThreadedRemark(remark="Go.")))
    worker = spawned(delivery, register, main("s1"), "a1", "fixer")
    other = spawned(delivery, register, main("s1"), "a2", "reviewer")
    review = asyncio.run(
        delivery.posted(
            Review(
                covers=[1],
                comments=[Comment(item=1, text="The cursor jumps when I type.")],
                letters=[Letter(to=main("s1"), text="And the voice branch.")],
            ),
            Operator(),
            main("s1"),
            None,
        )
    )
    said(
        lead.thread(
            Threading(
                name="lag",
                title="The cursor jumps",
                move=[f"{review.number}.1"],
                hand="fixer",
            )
        )
    )
    said(
        lead.thread(
            Threading(name="voice", title="The voice", move=[f"{review.number}.2"])
        )
    )
    concerns = delivery.concerns()
    lag = concerns.named(REPOSITORY, "lag")
    voice = concerns.named(REPOSITORY, "voice")
    before = [len(concerns.standing(each).unanswered) for each in [lag, voice]]

    said(
        speaker(delivery, register, other).note(
            ThreadedRemark(remark=f"On @{review.number}.1: it's the IME.")
        )
    )
    said(
        speaker(delivery, register, other).note(
            ThreadedRemark(remark=f"On @{review.number}.2: later.", thread="dev")
        )
    )
    outside = [len(concerns.standing(each).unanswered) for each in [lag, voice]]
    said(
        speaker(delivery, register, worker).note(
            ThreadedRemark(remark=f"Fixed @{review.number}.1: the IME's composition.")
        )
    )
    said(lead.note(ThreadedRemark(remark=f"@{review.number}.2: next week.")))

    assert before == [1, 1]
    assert outside == [1, 1]
    assert concerns.standing(lag).unanswered == []
    assert concerns.standing(voice).unanswered == []


def test_the_thread_tool_refuses_before_doing_anything(delivery: Delivery) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.thread(Threading(name="lag", title="Lag")))

    refusals = [
        said(lead.thread(Threading(name="lagg", join=True))),
        said(lead.thread(Threading(name="lag", title="Again"))),
        said(lead.thread(Threading(name="lag", hold=True, hand="nobody"))),
        said(lead.thread(Threading(name="lag", park=Parking(), done="x"))),
        said(lead.thread(Threading(name="lag", park=Parking(why="later")))),
        said(lead.thread(Threading(name="lag", hand="nobody"))),
        said(lead.thread(Threading(name="2025", title="Digits"))),
        said(lead.thread(Threading(name="lag", move=["99"]))),
    ]

    assert refusals == [
        "Nothing done: no thread of this repository is `lagg`: give `title` to open it",
        "Nothing done: `lag` names @2 already: leave out `title`, or pick another name",
        "Nothing done: `hold` takes it and `hand` gives it away: say one",
        "Nothing done: a thread is parked or done, not both: say one",
        "Nothing done: `park` takes what it waits for: an issue, a branch, a commit, a conversation, a time or a condition",
        "Nothing done: no conversation of this repository is `nobody`",
        "Nothing done: `2025` can't be a thread's name: letters, digits, `-`, `_` and `.`, a letter among them",
        "Nothing done: @99 isn't an item of this repository",
    ]
    assert delivery.inbox.whereabouts[main("s1").key()].thread is None


def test_join_moves_where_an_agent_works_and_hold_takes_it_from_whoever_held_it(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    worker = spawned(delivery, register, main("s1"), "a1", "fixer")
    said(lead.thread(Threading(name="lag", title="Lag", hold=True)))

    joined = said(
        speaker(delivery, register, worker).thread(Threading(name="lag", join=True))
    )
    said(speaker(delivery, register, worker).note(ThreadedRemark(remark="On it.")))
    took = said(
        speaker(delivery, register, worker).thread(Threading(name="lag", hold=True))
    )

    lag = delivery.concerns().named(REPOSITORY, "lag")
    assert joined == "You work in @lag: what you send lands there."
    landed = thread_of(delivery, 3)
    assert landed is not None
    assert landed.number == lag.number
    assert took == "You hold @lag, and work in it: what you send lands there."
    assert lag.holder == worker
    # Their own subagent's note isn't told to the session holding the thread.
    assert told(delivery, main("s1")) == ["lup: `dev/fixer` took @lag, which you held."]


def test_a_holder_that_ended_holds_nothing_and_the_thread_above_answers(
    delivery: Delivery, clock: FakeClock
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.note(ThreadedRemark(remark="Go.")))
    worker = spawned(delivery, register, main("s1"), "a1", "fixer")
    said(
        speaker(delivery, register, worker).thread(
            Threading(name="lag", title="Lag", hold=True)
        )
    )
    place = delivery.inbox.whereabouts[worker.key()]
    delivery.inbox.placed(place.model_copy(update={"ended": clock.now()}))
    reviewer = spawned(delivery, register, main("s1"), "a2", "reviewer")

    said(
        speaker(delivery, register, reviewer).note(
            ThreadedRemark(remark="Still jumps.", thread="lag")
        )
    )

    lag = delivery.concerns().named(REPOSITORY, "lag")
    assert delivery.concerns().answering(lag) == main("s1")
    # Their own subagent's note isn't told to the session; another's is.
    assert told(delivery, main("s1")) == []
    other = launched(delivery, "other", "s2")
    said(
        speaker(delivery, other, main("s2")).note(
            ThreadedRemark(remark="Still jumps here.", thread="lag")
        )
    )
    assert told(delivery, main("s1")) == [
        (
            '<landed thread="lag" item="5" kind="note" from="other">Still jumps '
            "here.</landed>"
        )
    ]
    # Its launch ending, a session holds nothing either.
    delivery.layout.record("dev").unlink()
    assert delivery.concerns().answering(lag) is None


def test_ask_puts_its_checks_in_the_question_s_thread_and_an_answer_reaches_the_asker(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))

    asked = said(
        lead.ask(
            Asking(
                question="Does the room start?",
                checks=["Launch a fresh room: it starts in 5 s.", "Run `lup` twice."],
                thread="Room start",
            )
        )
    )
    concerns = delivery.concerns()
    room = concerns.named(REPOSITORY, "room-start")
    checks = [
        each.node
        for each in concerns.threads.members(room.number)
        if isinstance(each.node, Check)
    ]
    standing = concerns.standing(room)
    concerns.checked(checks[0].number, "It took 9 s.")
    with pytest.raises(InboxError, match="answered already"):
        concerns.checked(checks[0].number, "")

    assert asked == (
        f"Your question is with the operator, @3, in @room-start, and its checks "
        f"@{checks[0].number} and @{checks[1].number} wait on them. Their answer "
        "reaches you at a later call; `wait_inbox` waits for it."
    )
    assert [each.text for each in checks] == [
        "Launch a fresh room: it starts in 5 s.",
        "Run `lup` twice.",
    ]
    assert standing.state == "waiting on the operator"
    assert len(standing.waiting) == 3
    answered = delivery.inbox.ledger.drawn_to(checks[0].number, Answered)
    assert [(each.text, each.by) for each in answered] == [("It took 9 s.", Operator())]
    assert told(delivery, main("s1")) == [
        (
            f"lup: the operator answered your check @{checks[0].number} in "
            f'@room-start:\n<checked item="{checks[0].number}" thread="room-start">'
            "It took 9 s.</checked>"
        )
    ]


def test_the_operator_settles_declines_and_reopens_telling_whoever_answers(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    worker = spawned(delivery, register, main("s1"), "a1", "fixer")
    said(
        speaker(delivery, register, worker).thread(
            Threading(name="lag", title="Lag", hold=True)
        )
    )
    concerns = delivery.concerns()
    lag = concerns.named(REPOSITORY, "lag")

    concerns.settled(lag)
    settled = concerns.standing(lag).state
    concerns.reopened(lag, "Still jumps.")
    reopened = concerns.standing(lag).state
    concerns.declined(lag, "")

    assert (settled, reopened, concerns.standing(lag).state) == (
        "settled",
        "working",
        "declined",
    )
    assert isinstance(delivery.inbox.ledger.drawn_to(lag.number, Settled)[0], Settled)
    assert told(delivery, worker) == [
        "lup: the operator settled @lag.",
        "lup: the operator reopened @lag: Still jumps.",
        "lup: the operator declined @lag.",
    ]


def test_a_thread_reads_whole_with_where_it_stands_what_s_under_and_what_names_it(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.thread(Threading(name="lag", title="The cursor jumps", hold=True)))
    said(lead.thread(Threading(name="fix", title="Fix it", under="lag")))
    said(lead.note(ThreadedRemark(remark="Typing fast moves it.")))
    said(
        lead.ask(Asking(question="Long comments only?", checks=["Type in a long one."]))
    )
    said(lead.note(ThreadedRemark(remark="See @lag.", thread="fix")))
    reader = Reader(delivery=delivery, reader=main("s1"))
    items = delivery.inbox.about(REPOSITORY)

    read = reader.read(items, Narrowing(thread="lag")).text
    none = reader.read(items, Narrowing(thread="nothing")).text

    assert read == (
        'Thread @lag (@2), "The cursor jumps", under @dev, held by you: waiting on '
        "the operator: 1 question, 1 check.\n"
        "Under it:\n"
        '- @fix, "Fix it": working\n'
        "Elsewhere, naming it:\n"
        "- @7  2026-10-01 12:00  a note from you to the operator, waiting: See @lag.\n\n"
        "@4  2026-10-01 12:00  a note from you to the operator, waiting:\n"
        '<item item="4" kind="note" from="dev">Typing fast moves it.</item>\n\n'
        "@5  2026-10-01 12:00  a question from you to the operator, waiting:\n"
        '<item item="5" kind="question" from="dev">Long comments only?</item>\n\n'
        "@6  2026-10-01 12:00  a check from you, waiting on the operator:\n"
        '<check item="6">Type in a long one.</check>'
    )
    assert none == "No thread is `nothing`: `thread` takes a thread's name or number."


def test_a_session_s_root_follows_their_name_and_a_root_nobody_holds_is_taken_by_name(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    said(speaker(delivery, register, main("s1")).note(ThreadedRemark(remark="Go.")))
    roots = RootNames(delivery=delivery)
    said(
        speaker(delivery, register, main("s1")).thread(
            Threading(name="lag", title="Lag")
        )
    )

    Names(path=delivery.layout.names).keep("s1", "inbox-scaling")
    roots.renamed(main("s1"), "inbox-scaling")
    renamed = delivery.concerns().thread(2)
    refused = roots.refused(REPOSITORY, "lag", roots=True, session=main("s1"))
    free = roots.refused(REPOSITORY, "anything", roots=False)
    delivery.layout.record("dev").unlink()
    later = launched(delivery, "next", "s2")
    takeable = roots.refused(
        REPOSITORY, "inbox-scaling", roots=True, session=main("s2")
    )
    not_for_a_subagent = roots.refused(REPOSITORY, "inbox-scaling", roots=False)
    Names(path=delivery.layout.names).keep("s2", "inbox-scaling")
    roots.renamed(main("s2"), "inbox-scaling")
    said(speaker(delivery, later, main("s2")).note(ThreadedRemark(remark="Back.")))

    assert renamed.name == "inbox-scaling"
    assert refused == (
        "`lag` names @3, a thread of this repository, and names are one set "
        "there: pick another name"
    )
    assert free is None
    assert takeable is None
    assert not_for_a_subagent is not None
    taken = delivery.concerns().thread(2)
    assert taken.holder == main("s2")
    assert thread_of(delivery, 4) == taken


def test_a_title_makes_a_name_with_a_letter() -> None:
    assert slugged("Tabs vanish") == "tabs-vanish"
    assert slugged("2025") == "thread-2025"


def test_a_fresh_session_s_bearings_list_the_open_threads_and_the_root_it_took(
    delivery: Delivery, clock: FakeClock
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.note(ThreadedRemark(remark="Go.")))
    said(lead.ask(Asking(question="Ship?", thread="Ship it")))
    said(lead.thread(Threading(name="done-one", title="Done one")))
    concerns = delivery.concerns()
    concerns.settled(concerns.named(REPOSITORY, "done-one"))
    delivery.layout.record("dev").unlink()
    clock.sleep(60)
    later = launched(delivery, "dev", "s2")
    bearings = RepositoryBearings(delivery=delivery, integration="dev")
    took = bearings.took(main("s2"))

    page = bearings.page(
        main("s2"),
        main("s1"),
        Repository(unlanded=[], landed=[], onto="origin/dev"),
        [],
        took,
    )

    assert took is not None
    assert took.holder == main("s2")
    assert later.launch == "dev"
    assert (
        "You took over the root @dev, which nobody held: 1 open thread under "
        "it, 1 thing waiting on the operator.\n"
        "Open threads of this repository (`inbox` with `thread` reads one whole; "
        "the `thread` tool with `hold` takes one):\n"
        f'- @dev, "{ROOT}", held by you: working.\n'
        '  - @ship-it, "Ship it", held by nobody: waiting on the operator: 1 '
        "question."
    ) in page
    assert "done-one" not in page
