"""Threads as agents work in them: where each works, what lands where, who's told, the `concern` tool, checks an earlier lup kept, a thread read whole, names, and an earlier lup's roots read as absent."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup.sessions import results
from lup.tools.tool import Refused
from lup_dev import cli
from lup_dev.host.names import Names
from lup_dev.host.protocol import Limits, Register
from lup_dev.host.pushes import Pushes
from lup_dev.inbox.bearings import Repository, RepositoryBearings
from lup_dev.inbox.concerns import slugged
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.mentions import mentioned
from lup_dev.inbox.namesakes import NodeNames
from lup_dev.inbox.notices import Notices
from lup_dev.inbox.reading import Narrowing, Reader
from lup_dev.inbox.store import (
    KINDS,
    Comment,
    Friction,
    Inbox,
    InboxError,
    Item,
    Letter,
    Review,
    Whereabouts,
    heard,
)
from lup_dev.inbox.tools import (
    Asking,
    Concerning,
    Parking,
    Sending,
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
    Body,
    Check,
    Done,
    In,
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


def befell(speaker: Speaker, text: str, title: str) -> Item:
    """Put a friction in the operator's inbox from `speaker`, landing where they work, as an earlier lup's `friction` did: `concern` opens a concern of its own for its words."""
    return asyncio.run(speaker.said(Friction(text=text, title=title)))


def kept_check(
    delivery: Delivery, thread: Thread, by: Conversation, text: str
) -> Check:
    """Keep a check in `thread`, by `by`, as an earlier lup's `ask` did with its `checks`: no call makes one."""
    ledger = delivery.inbox.ledger
    concerns = delivery.concerns()
    check = ledger.kept(
        Check(
            number=ledger.numbered(),
            repository=thread.repository,
            by=by,
            at=concerns.now(),
            text=text,
        )
    )
    ledger.drawn(
        In(
            source=check.number,
            target=thread.number,
            repository=thread.repository,
            by=by,
            at=concerns.now(),
        )
    )
    return check


def told(delivery: Delivery, party: Conversation) -> list[str]:
    """Take what lup left for `party` to be told at their next call."""
    return delivery.taken_words(party)


def thread_of(delivery: Delivery, number: int) -> Thread | None:
    return delivery.concerns().containing(number)


# An item's or a thread's number is read from the inbox or the ledger, as the act
# that made it left it, and never written as a literal: items, threads and checks
# take their numbers from one sequence, so a literal would test how many nodes
# other work makes. A thread's is read from the thread (`named(...).number`).


def newest(delivery: Delivery) -> int:
    """The number of the item the inbox made last: read just after the act that made it, it's that item's."""
    return max(delivery.inbox.items)


def numbers(delivery: Delivery) -> list[int]:
    """The numbers of the items the inbox holds, in the order made: unpacked where an act makes several, so each is named by what it is."""
    return sorted(delivery.inbox.items)


def test_what_a_session_sends_working_in_no_thread_lands_in_none_on_them_alone(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "inbox-scaling", "s1")
    one = speaker(delivery, register, main("s1"))

    first = said(one.note(ThreadedRemark(remark="It rests on the cache.")))
    second = said(one.note(ThreadedRemark(remark="And on the clock.")))
    on_cache, on_clock = numbers(delivery)

    assert thread_of(delivery, on_cache) is None
    assert thread_of(delivery, on_clock) is None
    assert first == f"Your note is with the operator, @{on_cache}. You can carry on."
    assert second == f"Your note is with the operator, @{on_clock}. You can carry on."
    assert delivery.inbox.ledger.every(Thread) == []
    assert told(delivery, main("s1")) == []


def test_how_it_felt_and_a_subagent_s_start_land_in_no_thread_where_their_parent_works_in_none(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    worker = spawned(delivery, register, main("s1"), "a1", "parser")
    work = speaker(delivery, register, worker)

    said(work.how_it_felt(results.HowItFelt(text="Calm.")))
    said(work.note(ThreadedRemark(remark="The lexer drops tabs.")))
    concerns = delivery.concerns()

    assert concerns.working(worker) is None
    assert concerns.started_on(worker) is None
    assert [thread_of(delivery, each) for each in delivery.inbox.items] == [None, None]
    assert told(delivery, main("s1")) == []


def test_a_subagent_starts_on_the_concern_their_parent_works_on_and_lands_there(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.concern(Concerning(name="lag", title="Lag", hold=True)))
    worker = spawned(delivery, register, main("s1"), "a1", "parser")

    said(speaker(delivery, register, worker).note(ThreadedRemark(remark="Tabs.")))
    tabs = newest(delivery)

    lag = delivery.concerns().named(REPOSITORY, "lag")
    assert delivery.concerns().working(worker) == lag
    assert thread_of(delivery, tabs) == lag


def test_a_concern_an_agent_opens_with_nobody_above_to_answer_is_their_session_s_and_moves_nobody(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    worker = spawned(delivery, register, main("s1"), "a1", "parser")
    work = speaker(delivery, register, worker)

    opening = said(lead.concern(Concerning(name="lag", title="Lag")))
    said(work.note(ThreadedRemark(remark="Tabs.", thread="Tabs vanish")))
    theirs = said(work.concern(Concerning(name="gate", title="The gate")))
    concerns = delivery.concerns()

    assert opening == "Opened @lag, held by you."
    assert theirs == "Opened @gate, held by `dev`."
    for name in ["lag", "tabs-vanish", "gate"]:
        opened = concerns.named(REPOSITORY, name)
        assert (opened.parent, opened.holder) == (None, main("s1"))
    assert concerns.working(main("s1")) is None
    assert concerns.working(worker) is None


def test_a_concern_opened_under_one_someone_answers_for_is_held_by_nobody_and_under_one_nobody_does_by_its_opener_s_session(
    delivery: Delivery,
) -> None:
    gone = launched(delivery, "gone", "s0")
    said(
        speaker(delivery, gone, main("s0")).concern(
            Concerning(name="left", title="Left behind")
        )
    )
    delivery.layout.record("gone").unlink()
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.concern(Concerning(name="lag", title="Lag", hold=True)))

    said(lead.concern(Concerning(name="tabs", title="Tabs")))
    said(lead.concern(Concerning(name="found", title="Found", under="left")))
    concerns = delivery.concerns()

    tabs = concerns.named(REPOSITORY, "tabs")
    found = concerns.named(REPOSITORY, "found")
    assert (tabs.parent, tabs.holder) == (
        concerns.named(REPOSITORY, "lag").number,
        None,
    )
    assert concerns.answering(tabs) == main("s1")
    assert (found.parent, found.holder) == (
        concerns.named(REPOSITORY, "left").number,
        main("s1"),
    )


def test_ask_takes_no_checks_saying_so(delivery: Delivery) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    [ask] = [each for each in lead.tools() if each.spec().name == "ask"]

    refused = asyncio.run(
        ask.call({"question": "Does it hold?", "checks": ["Run it."]})
    )

    assert isinstance(refused, Refused)
    assert "checks" in refused.rejection.reason
    assert delivery.inbox.items == {}
    assert delivery.inbox.ledger.every(Check) == []


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
    drops = newest(delivery)
    again = said(work.note(ThreadedRemark(remark="Fixed.", thread="tabs-vanish")))
    fixed = newest(delivery)
    plain = said(work.note(ThreadedRemark(remark="Back on the parse.")))
    back = newest(delivery)

    tabs = delivery.concerns().named(REPOSITORY, "tabs-vanish")
    assert (tabs.title, tabs.parent, tabs.holder) == ("Tabs vanish", None, main("s1"))
    assert opened == (
        f"Your note is with the operator, @{drops}, in @tabs-vanish. You can carry on."
    )
    assert again == (
        f"Your note is with the operator, @{fixed}, in @tabs-vanish. You can carry on."
    )
    # Naming a thread on a call never moves the agent: they still work where they started.
    assert plain == f"Your note is with the operator, @{back}. You can carry on."
    assert thread_of(delivery, back) is None
    # Their session holds the new thread, nobody above answering for it: told
    # nothing of their own subagent's notes, which their runtime tells them,
    # and each note of anyone else whole.
    assert told(delivery, main("s1")) == []
    other = launched(delivery, "other", "s2")
    said(
        speaker(delivery, other, main("s2")).note(
            ThreadedRemark(remark="Tabs here too.", thread="tabs-vanish")
        )
    )
    too = newest(delivery)
    assert told(delivery, main("s1")) == [
        (
            f'<landed thread="tabs-vanish" item="{too}" kind="note" from="other">'
            "Tabs here too.</landed>"
        )
    ]


def test_a_number_or_a_node_that_isn_t_a_thread_is_refused_on_a_send(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    one = speaker(delivery, register, main("s1"))
    said(one.note(ThreadedRemark(remark="First.")))
    first = newest(delivery)
    # Past every number given out, so nothing holds it.
    nothing = first + 100

    refused = said(one.note(ThreadedRemark(remark="Again.", thread=f"@{first}")))
    missing = said(one.note(ThreadedRemark(remark="Again.", thread=str(nothing))))

    assert refused == f"Not sent: `@{first}` is a `inbox:item`, not a thread"
    assert missing == f"Not sent: no thread of this repository is `{nothing}`"
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
        speaker(delivery, register, holder).concern(
            Concerning(name="lag", title="The cursor jumps", hold=True)
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
    typing = newest(delivery)
    said(
        speaker(delivery, register, reviewer).how_it_felt(
            results.HowItFelt(text="Calm.")
        )
    )
    felt = newest(delivery)

    assert told(delivery, holder) == [
        f'<landed thread="lag" item="{typing}" kind="note" from="dev">Typing fast moves it.</landed>'
    ]
    assert told(delivery, reviewer) == [
        f"lup: in @lag, a note from `dev`, @{typing}: Typing fast moves it."
    ]
    # How it felt lands where its sender started, in no thread here, and is told to nobody.
    assert thread_of(delivery, felt) is None
    assert told(delivery, main("s1")) == []


def test_a_subagent_s_concern_isn_t_told_to_their_parent_holding_it_who_has_its_copy(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    said(speaker(delivery, register, main("s1")).note(ThreadedRemark(remark="Go.")))
    worker = spawned(delivery, register, main("s1"), "a1", "parser")

    answer = said(
        speaker(delivery, register, worker).concern(
            Concerning(text="The gate hung.", title="gate hangs")
        )
    )
    # The lead's note, the friction, and their parent's copy of it.
    _, friction, _ = numbers(delivery)

    assert answer == (
        "Opened @gate-hangs, held by `dev`.\n"
        f"Thanks: your words are with the operator, @{friction}, in @gate-hangs, and "
        "your parent has them too. You can carry on."
    )
    assert delivery.inbox.item(friction).reason.model_dump()["title"] == "gate hangs"
    assert told(delivery, main("s1")) == []


def test_an_at_name_of_another_thread_draws_a_reference_to_it(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    one = speaker(delivery, register, main("s1"))
    said(one.concern(Concerning(name="lag", title="Lag")))

    said(one.note(ThreadedRemark(remark="This touches @lag, not `@dev`, and @dev.")))
    note = newest(delivery)

    lag = delivery.concerns().named(REPOSITORY, "lag")
    references = delivery.inbox.ledger.drawn_to(lag.number, Refers)
    assert [(each.source, each.target) for each in references] == [(note, lag.number)]
    # How a text's mentions are read, numbers as written: no node is behind them.
    assert mentioned("@lag and @2 but not @lag.3 or @2.1[x]") == ["lag", "2", "lag.3"]


def test_a_concern_s_words_open_one_named_after_them_that_the_session_holds_and_wait_on_no_one(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = Speaker(delivery=delivery, launch=register, party=main("s1"), call="c1")
    jammed = "The gate hangs on a fresh worktree.\n`uv run lup-dev check` waits on the engine."

    answer = said(lead.concern(Concerning(text=jammed)))
    words = newest(delivery)
    concerns = delivery.concerns()
    [opened] = concerns.threads.of(REPOSITORY)
    item = delivery.inbox.item(words)

    assert (opened.title, opened.name, opened.holder, opened.parent) == (
        "The gate hangs on a fresh worktree.",
        "the-gate-hangs-on-a-fresh-worktree",
        main("s1"),
        None,
    )
    assert answer == (
        "Opened @the-gate-hangs-on-a-fresh-worktree, held by you.\n"
        f"Thanks: your words are with the operator, @{words}, in "
        "@the-gate-hangs-on-a-fresh-worktree. You can carry on."
    )
    # Its words reach the operator at once, as written, anchored to the call,
    # news that asks nothing of them; the session isn't moved to it.
    assert thread_of(delivery, words) == opened
    assert (item.recipient, item.reason.model_dump()["text"], item.call) == (
        Operator(),
        jammed,
        "c1",
    )
    assert not item.asks
    assert concerns.standing(opened).state == "working"
    assert concerns.working(main("s1")) is None
    assert told(delivery, main("s1")) == []


def test_a_concern_opens_under_the_one_its_agent_works_in_and_its_words_can_go_into_one_there(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.concern(Concerning(name="lag", title="The cursor jumps", join=True)))
    worker = spawned(delivery, register, main("s1"), "a1", "parser")
    work = speaker(delivery, register, worker)

    opened = said(work.concern(Concerning(text="Tabs are dropped.", title="tabs")))
    *_, tabs = [
        number
        for number, each in delivery.inbox.items.items()
        if each.recipient == Operator()
    ]
    added = said(work.concern(Concerning(name="tabs", text="And spaces after them.")))
    *_, spaces = [
        number
        for number, each in delivery.inbox.items.items()
        if each.recipient == Operator()
    ]
    concerns = delivery.concerns()
    lag = concerns.named(REPOSITORY, "lag")
    under = concerns.named(REPOSITORY, "tabs")

    # Under the lead's concern, which they answer for from above: nobody holds it.
    assert (under.parent, under.holder) == (lag.number, None)
    assert concerns.answering(under) == main("s1")
    assert opened.startswith("Opened @tabs, under @lag.\n")
    assert added == (
        f"Thanks: your words are with the operator, @{spaces}, in @tabs, and your "
        "parent has them too. You can carry on."
    )
    assert [thread_of(delivery, each) for each in (tabs, spaces)] == [under, under]
    # Each reached the lead as their quiet copy, never as a line of the concern.
    copies = [
        each for each in delivery.inbox.items.values() if each.recipient == main("s1")
    ]
    assert [(each.quiet, each.reason.model_dump()["text"]) for each in copies] == [
        (True, "Tabs are dropped."),
        (True, "And spaces after them."),
    ]


def test_a_concern_s_body_is_rewritten_whole_by_whoever_answers_for_it_each_kept_and_read_with_it(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.note(ThreadedRemark(remark="Go.")))
    worker = spawned(delivery, register, main("s1"), "a1", "parser")
    work = speaker(delivery, register, worker)

    # A subagent opening one with a body: their session holds it, and its body
    # is theirs to keep too, the work being theirs.
    opened = said(
        work.concern(
            Concerning(
                text="Tabs are dropped.",
                title="tabs",
                body="The lexer reads a tab as a space.",
            )
        )
    )
    rewritten = said(
        lead.concern(
            Concerning(
                name="tabs",
                body="The lexer reads a tab as a space.\nIt starts at `read_indent`.",
            )
        )
    )
    alone = said(lead.concern(Concerning(name="tabs")))
    concerns = delivery.concerns()
    tabs = concerns.named(REPOSITORY, "tabs")
    reader = Reader(delivery=delivery, reader=main("s1"))
    read = reader.read(delivery.inbox.about(REPOSITORY), Narrowing(thread="tabs"))
    cleared = said(lead.concern(Concerning(name="tabs", body="")))

    assert tabs.holder == main("s1")
    words = next(
        number
        for number, each in delivery.inbox.items.items()
        if each.recipient == Operator() and each.sender == worker
    )
    assert opened == (
        "Opened @tabs, held by `dev`.\n"
        "@tabs's body is rewritten, for the operator to read.\n"
        f"Thanks: your words are with the operator, @{words}, in @tabs, and your "
        "parent has them too. You can carry on."
    )
    assert rewritten == "@tabs's body is rewritten, for the operator to read."
    assert alone == (
        '@tabs, "tabs", held by you: working.\n'
        "Its body:\n"
        "The lexer reads a tab as a space.\nIt starts at `read_indent`."
    )
    assert read.text.startswith(
        f'Thread @tabs (@{tabs.number}), "tabs", held by you: working.\n'
        '<body by="you" at="2026-10-01 12:00">\nThe lexer reads a tab as a space.\n'
        "It starts at `read_indent`.\n</body>\n\n"
    )
    # Each is kept, the latest the body; cleared, there's none.
    assert cleared == "@tabs's body is cleared."
    assert concerns.body(tabs) is None
    assert [
        (each.by, each.text)
        for each in delivery.inbox.ledger.drawn_to(tabs.number, Body)
    ] == [
        (worker, "The lexer reads a tab as a space."),
        (main("s1"), "The lexer reads a tab as a space.\nIt starts at `read_indent`."),
        (main("s1"), ""),
    ]
    # Nobody is told of it: the operator reads it where the concern is.
    assert told(delivery, main("s1")) == []
    assert told(delivery, worker) == []


def test_a_body_another_answers_for_is_refused_before_anything_is_done_and_hold_takes_it(
    delivery: Delivery,
) -> None:
    one = launched(delivery, "dev", "s1")
    two = launched(delivery, "docs", "s2")
    lead = speaker(delivery, one, main("s1"))
    other = speaker(delivery, two, main("s2"))
    said(lead.concern(Concerning(name="lag", title="The cursor jumps")))

    refused = said(
        other.concern(
            Concerning(name="lag", text="It jumps here too.", body="Mine now.")
        )
    )
    under = said(
        other.concern(Concerning(text="And in docs.", under="lag", body="Mine."))
    )
    concerns = delivery.concerns()
    lag = concerns.named(REPOSITORY, "lag")
    nothing = (dict(delivery.inbox.items), concerns.threads.of(REPOSITORY))
    taken = said(other.concern(Concerning(name="lag", hold=True, body="Mine now.")))

    assert refused == "Nothing done: @lag's body is `dev`'s to keep, who answers for it"
    assert under == refused
    assert nothing == ({}, [lag])
    assert taken == (
        "You hold @lag, and work in it: what you send lands there.\n"
        "@lag's body is rewritten, for the operator to read."
    )
    body = concerns.body(lag)
    assert body is not None
    assert (body.by, body.text) == (main("s2"), "Mine now.")


def test_the_concern_tool_opens_holds_hands_moves_parks_and_says_done(
    delivery: Delivery, clock: FakeClock
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.note(ThreadedRemark(remark="Go.")))
    go = newest(delivery)
    worker = spawned(delivery, register, main("s1"), "a1", "fixer")
    review = asyncio.run(
        delivery.posted(
            Review(
                covers=[go],
                comments=[Comment(item=go, text="The cursor jumps when I type.")],
                letters=[Letter(to=main("s1"), text="And the voice branch.")],
            ),
            Operator(),
            main("s1"),
            None,
        )
    )

    opened = said(
        lead.concern(
            Concerning(
                name="lag",
                title="The cursor jumps",
                move=[f"{review.number}.1"],
                hand="fixer",
            )
        )
    )
    standing = said(lead.concern(Concerning(name="lag")))
    clock.sleep(60)
    parked = said(
        lead.concern(
            Concerning(name="voice", title="The voice branch", park=Parking(issue=12))
        )
    )
    done = said(
        speaker(delivery, register, worker).concern(
            Concerning(name="lag", done="Type fast in a long comment: it stays put.")
        )
    )

    lag = delivery.concerns().named(REPOSITORY, "lag")
    assert opened == (
        "Opened @lag.\n"
        "@lag is `dev/fixer`'s now, who's told.\n"
        f"Moved @{review.number}.1 into @lag."
    )
    assert lag.holder == worker
    assert delivery.inbox.whereabouts[worker.key()].thread == lag.number
    assert delivery.inbox.whereabouts[main("s1").key()].thread is None
    assert standing == (
        '@lag, "The cursor jumps", held by `dev/fixer`: working; 1 '
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
        == "Opened @voice, held by you.\n@voice is parked until issue #12 closing."
    )
    voice = delivery.concerns().named(REPOSITORY, "voice")
    status = delivery.concerns().standing(voice).status
    assert isinstance(status, Parked)
    assert status.until == [IssueClosed(issue=12)]
    assert done == "@lag is done, for the operator to clear."
    assert isinstance(delivery.concerns().standing(lag).status, Done)
    assert told(delivery, main("s1")) == []


def test_a_part_moved_into_a_thread_is_answered_by_an_item_in_that_thread_citing_it(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.note(ThreadedRemark(remark="Go.")))
    go = newest(delivery)
    worker = spawned(delivery, register, main("s1"), "a1", "fixer")
    other = spawned(delivery, register, main("s1"), "a2", "reviewer")
    review = asyncio.run(
        delivery.posted(
            Review(
                covers=[go],
                comments=[Comment(item=go, text="The cursor jumps when I type.")],
                letters=[Letter(to=main("s1"), text="And the voice branch.")],
            ),
            Operator(),
            main("s1"),
            None,
        )
    )
    said(
        lead.concern(
            Concerning(
                name="lag",
                title="The cursor jumps",
                move=[f"{review.number}.1"],
                hand="fixer",
            )
        )
    )
    said(
        lead.concern(
            Concerning(name="voice", title="The voice", move=[f"{review.number}.2"])
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
    said(lead.note(ThreadedRemark(remark=f"Moved @{review.number}.2 into @voice.")))
    routed = len(concerns.standing(voice).unanswered)
    said(
        lead.note(
            ThreadedRemark(remark=f"@{review.number}.2: next week.", thread="voice")
        )
    )

    assert before == [1, 1]
    assert outside == [1, 1]
    assert concerns.standing(lag).unanswered == []
    assert routed == 1
    assert concerns.standing(voice).unanswered == []


def test_the_concern_tool_refuses_before_doing_anything(delivery: Delivery) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.concern(Concerning(name="lag", title="Lag")))
    lag = delivery.concerns().named(REPOSITORY, "lag").number
    # Past every number given out, so nothing holds it.
    nothing = lag + 100

    refusals = [
        said(lead.concern(Concerning(name="lagg", join=True))),
        said(lead.concern(Concerning(name="lag", title="Again"))),
        said(lead.concern(Concerning(name="lag", hold=True, hand="nobody"))),
        said(lead.concern(Concerning(name="lag", park=Parking(), done="x"))),
        said(lead.concern(Concerning(name="lag", park=Parking(why="later")))),
        said(lead.concern(Concerning(name="lag", hand="nobody"))),
        said(lead.concern(Concerning(name="2025", title="Digits"))),
        said(lead.concern(Concerning(name="lag", move=[str(nothing)]))),
    ]

    assert refusals == [
        "Nothing done: no concern of this repository is `lagg`: give `text` or `title` to open it",
        f"Nothing done: `lag` names @{lag} already: leave out `title`, or pick another name",
        "Nothing done: `hold` takes it and `hand` passes it on: say one",
        "Nothing done: a concern is parked or done, not both: say one",
        "Nothing done: `park` takes what it waits for: an issue, a branch, a commit, a conversation, a time or a condition",
        "Nothing done: no conversation of this repository is `nobody`",
        "Nothing done: `2025` can't be a concern's name: letters, digits, `-`, `_` and `.`, a letter among them",
        f"Nothing done: @{nothing} isn't an item of this repository",
    ]
    assert delivery.inbox.whereabouts[main("s1").key()].thread is None


def test_join_moves_where_an_agent_works_and_hold_takes_it_from_whoever_held_it(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    worker = spawned(delivery, register, main("s1"), "a1", "fixer")
    said(lead.concern(Concerning(name="lag", title="Lag", hold=True)))

    joined = said(
        speaker(delivery, register, worker).concern(Concerning(name="lag", join=True))
    )
    said(speaker(delivery, register, worker).note(ThreadedRemark(remark="On it.")))
    on_it = newest(delivery)
    took = said(
        speaker(delivery, register, worker).concern(Concerning(name="lag", hold=True))
    )

    lag = delivery.concerns().named(REPOSITORY, "lag")
    assert joined == "You work in @lag: what you send lands there."
    landed = thread_of(delivery, on_it)
    assert landed is not None
    assert landed.number == lag.number
    assert took == "You hold @lag, and work in it: what you send lands there."
    assert lag.holder == worker
    # Their own subagent's note isn't told to the session holding the thread.
    assert told(delivery, main("s1")) == ["lup: `dev/fixer` took @lag, which you held."]


def test_a_subagent_stays_quiet_in_the_thread_they_started_on_wherever_they_go_and_so_do_theirs(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.concern(Concerning(name="home", title="Home", hold=True)))
    said(lead.note(ThreadedRemark(remark="Go.")))
    go = newest(delivery)
    worker = spawned(delivery, register, main("s1"), "a1", "fixer")
    work = speaker(delivery, register, worker)
    said(work.note(ThreadedRemark(remark="Starting.")))
    said(work.concern(Concerning(name="lag", title="Lag", join=True)))
    helper = spawned(delivery, register, worker, "a2", "helper")
    said(speaker(delivery, register, helper).note(ThreadedRemark(remark="Looking.")))
    review = asyncio.run(
        delivery.posted(
            Review(
                covers=[go],
                comments=[Comment(item=go, text="Ship it today.")],
            ),
            Operator(),
            main("s1"),
            None,
        )
    )

    said(lead.concern(Concerning(name="home", move=[f"{review.number}.1"])))
    said(lead.note(ThreadedRemark(remark="Typing fast moves it.", thread="lag")))
    typing = newest(delivery)

    # The fixer wrote in @home before joining @lag, and never chose it: the
    # operator's words moved there are their parent's. @lag they
    # joined, so its note reaches them; their own subagent, who started there,
    # hears nothing of it.
    assert told(delivery, worker) == [
        f"lup: in @lag, a note from `dev`, @{typing}: Typing fast moves it."
    ]
    assert told(delivery, helper) == []
    lag = delivery.concerns().named(REPOSITORY, "lag")
    assert delivery.inbox.whereabouts[helper.key()].started == lag.number


def test_a_holder_that_ended_holds_nothing_and_the_thread_above_answers(
    delivery: Delivery, clock: FakeClock
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.concern(Concerning(name="home", title="Home", hold=True)))
    worker = spawned(delivery, register, main("s1"), "a1", "fixer")
    said(
        speaker(delivery, register, worker).concern(
            Concerning(name="lag", title="Lag", hold=True)
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
    here = newest(delivery)
    assert told(delivery, main("s1")) == [
        (
            f'<landed thread="lag" item="{here}" kind="note" from="other">Still jumps '
            "here.</landed>"
        )
    ]
    # Its launch ending, a session holds nothing either.
    delivery.layout.record("dev").unlink()
    assert delivery.concerns().answering(lag) is None


def test_a_check_an_earlier_lup_kept_waits_on_nobody_and_reads_with_its_answer(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.concern(Concerning(name="room-start", title="Room start", hold=True)))
    said(lead.note(ThreadedRemark(remark="It starts slowly.")))
    concerns = delivery.concerns()
    room = concerns.named(REPOSITORY, "room-start")
    started = kept_check(delivery, room, main("s1"), "Launch a fresh room.")
    twice = kept_check(delivery, room, main("s1"), "Run `lup` twice.")
    delivery.inbox.ledger.drawn(
        Answered(
            target=started.number,
            repository=REPOSITORY,
            by=Operator(),
            at=concerns.now(),
            text="It took 9 s.",
        )
    )
    reader = Reader(delivery=delivery, reader=main("s1"))

    standing = concerns.standing(room)
    read = reader.read(
        delivery.inbox.about(REPOSITORY), Narrowing(thread="room-start")
    ).text

    assert (standing.state, standing.waiting) == ("working", [])
    assert read.endswith(
        f"@{started.number}  2026-10-01 12:00  a check from you, answered at 2026-10-01 12:00:\n"
        f'<check item="{started.number}">\nLaunch a fresh room.\n'
        '<answered from="operator">It took 9 s.</answered>\n</check>\n\n'
        f"@{twice.number}  2026-10-01 12:00  a check from you, never answered:\n"
        f'<check item="{twice.number}">Run `lup` twice.</check>'
    )


def test_the_operator_settles_declines_and_reopens_telling_whoever_answers(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    worker = spawned(delivery, register, main("s1"), "a1", "fixer")
    said(
        speaker(delivery, register, worker).concern(
            Concerning(name="lag", title="Lag", hold=True)
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
    said(lead.concern(Concerning(name="lag", title="The cursor jumps", hold=True)))
    said(lead.concern(Concerning(name="fix", title="Fix it", under="lag")))
    said(lead.note(ThreadedRemark(remark="Typing fast moves it.")))
    typing = newest(delivery)
    said(lead.ask(Asking(question="Long comments only?")))
    question = newest(delivery)
    check = kept_check(
        delivery,
        delivery.concerns().named(REPOSITORY, "lag"),
        main("s1"),
        "Type in a long one.",
    )
    said(lead.note(ThreadedRemark(remark="See @lag.", thread="fix")))
    seen = newest(delivery)
    lag = delivery.concerns().named(REPOSITORY, "lag").number
    reader = Reader(delivery=delivery, reader=main("s1"))
    items = delivery.inbox.about(REPOSITORY)

    read = reader.read(items, Narrowing(thread="lag")).text
    none = reader.read(items, Narrowing(thread="nothing")).text

    assert read == (
        f'Thread @lag (@{lag}), "The cursor jumps", held by you: waiting on '
        "the operator: 1 question.\n"
        "Under it:\n"
        '- @fix, "Fix it": working\n'
        "Elsewhere, naming it:\n"
        f"- @{seen}  2026-10-01 12:00  a note from you to the operator, waiting: See @lag.\n\n"
        f"@{typing}  2026-10-01 12:00  a note from you to the operator, waiting:\n"
        f'<item item="{typing}" kind="note" from="dev">Typing fast moves it.</item>\n\n'
        f"@{question}  2026-10-01 12:00  a question from you to the operator, waiting:\n"
        f'<item item="{question}" kind="question" from="dev">Long comments only?</item>\n\n'
        f"@{check.number}  2026-10-01 12:00  a check from you, never answered:\n"
        f'<check item="{check.number}">Type in a long one.</check>'
    )
    assert none == "No thread is `nothing`: `thread` takes a thread's name or number."


def test_a_friction_the_operator_moved_reads_whole_in_the_thread_it_went_to_saying_so(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    befell(lead, "It hung.", "the gate hangs")
    said(lead.concern(Concerning(name="gate", title="The gate")))
    concerns = delivery.concerns()
    [friction] = delivery.inbox.items
    concerns.gathered([friction], concerns.named(REPOSITORY, "gate"), None)
    reader = Reader(delivery=delivery, reader=main("s1"))

    read = reader.read(delivery.inbox.about(REPOSITORY), Narrowing(thread="gate"))

    assert read.text.endswith(
        "Moved here by the operator, from where it landed:\n"
        f"@{friction}  2026-10-01 12:00  a friction from you to the operator, waiting:\n"
        f'<item item="{friction}" kind="friction" from="dev">It hung.</item>'
    )


def test_a_name_a_thread_has_is_no_agent_s_and_a_new_session_inherits_nothing_by_it(
    delivery: Delivery, clock: FakeClock
) -> None:
    earlier = launched(delivery, "dev", "s1")
    said(
        speaker(delivery, earlier, main("s1")).concern(
            Concerning(name="lag", title="Lag", hold=True)
        )
    )
    delivery.layout.record("dev").unlink()
    names = NodeNames(delivery=delivery)

    refused = names.refused(REPOSITORY, "lag")
    free = names.refused(REPOSITORY, "anything")
    clock.sleep(60)
    later = launched(delivery, "dev", "s2")
    concerns = delivery.concerns()
    lag = concerns.named(REPOSITORY, "lag")

    assert refused == (
        f"`lag` names @{lag.number}, a thread of this repository, and names are one "
        "set there: pick another name"
    )
    assert free is None
    assert later.launch == "dev"
    # The thread stays as its holder left it, reading as nobody's: not the new `dev`'s.
    assert lag.holder == main("s1")
    assert concerns.answering(lag) is None
    assert concerns.working(main("s2")) is None


def plant_root(
    delivery: Delivery,
    party: Conversation,
    name: str,
    *,
    holder: Conversation | None = None,
) -> Thread:
    """Keep a root as an earlier lup kept one for a session, held by `holder`."""
    ledger = delivery.inbox.ledger
    return ledger.kept(
        Thread(
            number=ledger.numbered(),
            repository=party.repository,
            by=party,
            at=delivery.clock.now(),
            name=name,
            title=ROOT,
            holder=holder,
        )
    )


def under_root(delivery: Delivery, root: Thread, name: str, by: Conversation) -> Thread:
    """Keep a thread under `root`, held by nobody, as an earlier lup opened one."""
    ledger = delivery.inbox.ledger
    return ledger.kept(
        Thread(
            number=ledger.numbered(),
            repository=root.repository,
            by=by,
            at=delivery.clock.now(),
            name=name,
            title=name,
            parent=root.number,
        )
    )


def put_in(delivery: Delivery, item: int, thread: Thread) -> None:
    """Put `item` in `thread`, as an earlier lup put each item in its session's root."""
    delivery.inbox.ledger.drawn(
        In(
            source=item,
            target=thread.number,
            repository=thread.repository,
            by=Lup(),
            at=delivery.clock.now(),
        )
    )


def test_a_thread_under_a_root_reads_as_at_the_top_and_nobody_answers_for_it_by_the_root(
    delivery: Delivery,
) -> None:
    launched(delivery, "dev", "s1")
    root = plant_root(delivery, main("s1"), "dev", holder=main("s1"))
    sshole = under_root(delivery, root, "sshole", main("s1"))
    concerns = delivery.concerns()

    read = concerns.thread(sshole.number)

    assert read.parent is None
    assert concerns.answering(read) is None
    assert concerns.standing(read).state == "nobody running"
    assert [each.number for each in concerns.threads.of(REPOSITORY)] == [sshole.number]
    # Nothing landing there is told to the root's holder, who's nobody's to tell.
    other = launched(delivery, "other", "s2")
    said(
        speaker(delivery, other, main("s2")).note(
            ThreadedRemark(remark="Seen.", thread="sshole")
        )
    )
    assert told(delivery, main("s1")) == []


def test_an_item_in_a_root_reads_as_in_no_thread(delivery: Delivery) -> None:
    register = launched(delivery, "dev", "s1")
    said(speaker(delivery, register, main("s1")).note(ThreadedRemark(remark="Old.")))
    [item] = delivery.inbox.items
    root = plant_root(delivery, main("s1"), "dev-old", holder=main("s1"))
    put_in(delivery, item, root)

    assert delivery.concerns().containing(item) is None


def test_a_root_reads_as_absent_by_its_name_its_number_and_where_someone_worked_in_it(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    root = plant_root(delivery, main("s1"), "old-dev", holder=main("s1"))
    delivery.concerns().placed(main("s1"), thread=root.number, started=root.number)
    concerns = delivery.concerns()

    assert concerns.found(REPOSITORY, "old-dev") is None
    assert concerns.found(REPOSITORY, str(root.number)) is None
    assert concerns.working(main("s1")) is None
    assert concerns.started_on(main("s1")) is None
    assert said(lead.concern(Concerning(name="old-dev"))) == (
        "Nothing done: no concern of this repository is `old-dev`: give `text` or `title` to open it"
    )
    with pytest.raises(InboxError):
        concerns.thread(root.number)
    with pytest.raises(InboxError):
        concerns.named(REPOSITORY, "old-dev")
    # What lands where they worked lands on them alone.
    said(lead.note(ThreadedRemark(remark="Go.")))
    assert thread_of(delivery, next(iter(delivery.inbox.items))) is None


def test_a_root_s_name_refuses_nobody_and_a_new_thread_is_given_the_next_free_one(
    delivery: Delivery,
) -> None:
    earlier = main("s0")
    plant_root(delivery, earlier, "dev", holder=earlier)
    names = NodeNames(delivery=delivery)

    assert names.refused(REPOSITORY, "dev") is None
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    plant_root(delivery, earlier, "old", holder=earlier)
    said(lead.concern(Concerning(name="old", title="An old one")))
    concerns = delivery.concerns()

    assert concerns.working(main("s1")) is None
    assert concerns.named(REPOSITORY, "old-2").title == "An old one"
    # A `dev` thread can't be: the session goes by it. The agent's name wins over
    # the root's, and `@dev` names no thread.
    assert concerns.found(REPOSITORY, "dev") is None


def test_a_root_parked_comes_due_never_as_it_reads_as_absent(
    delivery: Delivery,
) -> None:
    earlier = main("s0")
    root = plant_root(delivery, earlier, "old", holder=earlier)
    delivery.inbox.ledger.drawn(
        Parked(
            target=root.number,
            repository=REPOSITORY,
            by=earlier,
            at=delivery.clock.now(),
            until=[IssueClosed(issue=7)],
        )
    )

    assert delivery.concerns().threads.parked(REPOSITORY) == []


def test_a_frictions_in_no_thread_are_gathered_into_a_concern_nobody_holds_at_the_top(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    befell(lead, "It hung.", "the gate hangs")
    concerns = delivery.concerns()
    [friction] = delivery.inbox.items

    gathered = concerns.gathered([friction], None, "The gate")

    assert (gathered.thread.parent, gathered.thread.holder) == (None, None)
    assert concerns.answering(gathered.thread) is None


def test_gathering_opens_under_the_top_of_where_the_first_landed_whoever_holds_it_answering(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.concern(Concerning(name="lag", title="Lag", hold=True)))
    said(lead.concern(Concerning(name="tabs", title="Tabs", join=True)))
    befell(lead, "It hung.", "the gate hangs")
    concerns = delivery.concerns()
    friction = next(
        number
        for number, each in delivery.inbox.items.items()
        if each.reason.reason == "friction"
    )

    gathered = concerns.gathered([friction], None, "The gate")

    assert gathered.thread.parent == concerns.named(REPOSITORY, "lag").number
    assert concerns.answering(gathered.thread) == main("s1")


def test_a_settled_concern_stays_settled_whatever_its_holder_sends_into_it_running_or_resumed(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.concern(Concerning(name="lag", title="Lag", hold=True)))
    concerns = delivery.concerns()
    lag = concerns.named(REPOSITORY, "lag")
    # The operator settled it while they worked; they go on in it.
    concerns.settled(lag)
    said(lead.note(ThreadedRemark(remark="Still here.")))
    running = delivery.concerns().standing(lag).state

    # Their session ended, and resumed under the same ids: they and a subagent of theirs send into it again.
    delivery.layout.record("dev").unlink()
    resumed = launched(delivery, "dev", "s1")
    helper = spawned(delivery, resumed, main("s1"), "a1", "helper")
    said(
        speaker(delivery, resumed, helper).note(
            ThreadedRemark(remark="Back.", thread="lag")
        )
    )
    said(speaker(delivery, resumed, main("s1")).note(ThreadedRemark(remark="On it.")))

    assert running == "settled"
    assert delivery.concerns().standing(lag).state == "settled"


def test_a_concern_a_holder_left_goes_nobody_running_and_back_to_working_as_they_resume(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    said(
        speaker(delivery, register, main("s1")).concern(
            Concerning(name="lag", title="Lag", hold=True)
        )
    )
    lag = delivery.concerns().named(REPOSITORY, "lag")
    holding = delivery.concerns().standing(lag).state

    delivery.layout.record("dev").unlink()
    left = delivery.concerns().standing(lag).state
    resumed = launched(delivery, "dev", "s1")
    back = delivery.concerns().standing(lag).state

    assert (holding, left, back) == ("working", "nobody running", "working")
    assert resumed.launch == "dev"


def test_a_nested_concern_whose_holder_ended_is_answered_for_by_who_holds_above_it(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.concern(Concerning(name="lag", title="Lag", hold=True)))
    worker = spawned(delivery, register, main("s1"), "a1", "parser")
    said(
        speaker(delivery, register, worker).concern(
            Concerning(name="tabs", title="Tabs", hold=True)
        )
    )
    place = delivery.inbox.whereabouts[worker.key()]
    delivery.inbox.placed(place.model_copy(update={"ended": delivery.clock.now()}))
    concerns = delivery.concerns()

    tabs = concerns.named(REPOSITORY, "tabs")
    assert tabs.holder == worker
    assert concerns.answering(tabs) == main("s1")
    assert concerns.standing(tabs).state == "working"


def test_no_tool_an_agent_calls_settles_or_declines_a_thread() -> None:
    fields = set(Concerning.model_fields)
    assert not fields & {"settle", "settled", "decline", "declined", "reopen"}


def test_a_title_makes_a_name_with_a_letter() -> None:
    assert slugged("Tabs vanish") == "tabs-vanish"
    assert slugged("2025") == "thread-2025"


def test_a_fresh_session_hears_nothing_of_concerns_and_lists_them_on_asking(
    delivery: Delivery, clock: FakeClock
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.note(ThreadedRemark(remark="Go.")))
    said(lead.ask(Asking(question="Ship?", thread="Ship it")))
    said(lead.concern(Concerning(text="The gate hangs.")))
    said(lead.concern(Concerning(name="done-one", title="Done one", body="Done.")))
    said(lead.concern(Concerning(name="empty", title="Nothing in it")))
    concerns = delivery.concerns()
    concerns.settled(concerns.named(REPOSITORY, "done-one"))
    delivery.layout.record("dev").unlink()
    clock.sleep(60)
    later = launched(delivery, "dev", "s2")
    bearings = RepositoryBearings(delivery=delivery, running=lambda _: "dev")
    fresh = speaker(delivery, later, main("s2"))

    page = bearings.page(
        main("s2"),
        main("s1"),
        Repository(unlanded=[], landed=[], onto="origin/dev"),
        [],
    )
    working = delivery.concerns().working(main("s2"))
    listed = said(fresh.concern(Concerning()))
    said(fresh.concern(Concerning(name="the-gate-hangs", hold=True)))
    theirs = said(fresh.concern(Concerning()))

    # Nothing of concerns as they start, whatever they're called.
    assert later.launch == "dev"
    assert working is None
    assert "concern" not in page
    assert "ship-it" not in page
    # Asked, those left with something in them are listed, each with who left
    # it, and theirs apart; one cleared or empty isn't.
    assert listed == (
        "In `No agent`, nobody running answering for them:\n"
        '- @ship-it, "Ship it", left by `dev` (claude session s1): waiting on the operator: 1 question.\n'
        '- @the-gate-hangs, "The gate hangs.", left by `dev` (claude session s1): nobody running.'
    )
    assert theirs == (
        "In `No agent`, nobody running answering for them:\n"
        '- @ship-it, "Ship it", left by `dev` (claude session s1): waiting on the operator: 1 question.\n'
        "Yours:\n"
        '- @the-gate-hangs, "The gate hangs.": working.'
    )


def test_a_fresh_session_s_listing_reads_a_root_as_absent(
    delivery: Delivery,
) -> None:
    earlier = main("s0")
    register = launched(delivery, "dev", "s0")
    said(speaker(delivery, register, earlier).note(ThreadedRemark(remark="Here.")))
    [here] = delivery.inbox.items
    delivery.layout.record("dev").unlink()
    root = plant_root(delivery, earlier, "dev-old", holder=earlier)
    put_in(delivery, here, under_root(delivery, root, "sshole", earlier))
    later = launched(delivery, "dev", "s2")

    listed = said(speaker(delivery, later, main("s2")).concern(Concerning()))

    assert listed == (
        "In `No agent`, nobody running answering for them:\n"
        '- @sshole, "sshole", left by `dev` (claude session s0): nobody running.'
    )
    assert delivery.concerns().named(REPOSITORY, "sshole").holder is None
    assert delivery.inbox.ledger.node(root.number, Thread).holder == earlier


class EarlierWhereabouts(Whereabouts):
    """Where a conversation was last heard, as an earlier lup kept it, with their root."""

    root: int | None = None


def test_whereabouts_an_earlier_lup_kept_with_a_root_read_as_ever_and_where_they_work_in_none(
    delivery: Delivery,
) -> None:
    launched(delivery, "dev", "s1")
    root = plant_root(delivery, main("s1"), "dev-root", holder=main("s1"))
    place = delivery.inbox.whereabouts[main("s1").key()]
    older = EarlierWhereabouts(**place.model_dump(), root=root.number)
    delivery.inbox.ledger.rewritten(heard(main("s1").key()), older)

    reopened = Inbox.opened(delivery.inbox.ledger)

    assert reopened.whereabouts[main("s1").key()] == place
    assert delivery.concerns().working(main("s1")) is None
