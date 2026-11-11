"""Threads on the ledger: what's in one, where it stands, who's on it, and the threads above and under it."""

from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Literal, override

import pytest
from pydantic import ValidationError

from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.environment.threads import Threads
from lup_ledger.errors import LupLedgerError
from lup_ledger.parties import Conversation, Lup, Operator
from lup_ledger.records import Edge, Kinds, Node
from lup_ledger.threads import (
    KINDS,
    ROOT,
    Answered,
    BranchLanded,
    Check,
    Declined,
    Done,
    In,
    Marks,
    Moved,
    Parked,
    Refers,
    Reopened,
    Settled,
    Standing,
    Thread,
    TimeCame,
    without_roots,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

REPOSITORY = Path("/work/lup.git")
OTHER = Path("/work/other.git")
MAIN = Conversation(repository=REPOSITORY, runtime="r", session="s1")
WORKER = MAIN.model_copy(update={"agent": "a1"})
REVIEWER = MAIN.model_copy(update={"agent": "a2"})
START = datetime(2026, 10, 29, 12, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return START + timedelta(minutes=minutes)


def opened(
    ledger: Ledger,
    name: str,
    *,
    parent: int | None = None,
    holder: Conversation | None = WORKER,
    repository: Path = REPOSITORY,
) -> Thread:
    return ledger.kept(
        Thread(
            number=ledger.numbered(),
            repository=repository,
            by=MAIN,
            at=START,
            name=name,
            title=f"About {name}",
            parent=parent,
            holder=holder,
        )
    )


def item(ledger: Ledger, by: Operator | Conversation = WORKER) -> Node:
    """Keep a node standing for an item of the inbox's, which isn't on the ledger yet."""
    return ledger.kept(
        Node.model_validate(
            {
                "kind": "inbox:item",
                "number": ledger.numbered(),
                "repository": REPOSITORY,
                "by": by,
                "at": START,
                "name": None,
                "text": "Said.",
            }
        )
    )


def placed(ledger: Ledger, node: Node, thread: Thread, minutes: int = 0) -> In:
    return ledger.drawn(
        In(
            source=node.number,
            target=thread.number,
            repository=REPOSITORY,
            by=MAIN,
            at=at(minutes),
        )
    )


def checked(ledger: Ledger, thread: Thread, by: Conversation = WORKER) -> Check:
    found = ledger.kept(
        Check(
            number=ledger.numbered(),
            repository=REPOSITORY,
            by=by,
            at=START,
            text="Try it.",
        )
    )
    placed(ledger, found, thread)
    return found


def test_a_thread_with_nothing_in_it_is_worked_on_by_its_holder(
    ledger: Ledger, threads: Threads
) -> None:
    lag = opened(ledger, "lag")

    assert threads.standing(lag.number) == Standing(state="working", on=[WORKER])


def test_a_check_waits_on_the_operator_until_they_answer_it(
    ledger: Ledger, threads: Threads
) -> None:
    lag = opened(ledger, "lag")
    found = checked(ledger, lag)

    waiting = threads.standing(lag.number)
    ledger.drawn(
        Answered(target=found.number, repository=REPOSITORY, by=Operator(), at=at(1))
    )
    answered = threads.standing(lag.number)

    assert waiting.state == "waiting on the operator"
    assert [each.node for each in waiting.waiting] == [found]
    assert answered.state == "working"
    assert answered.waiting == []


@pytest.mark.parametrize(
    ("said", "state"),
    [
        (
            partial(
                Parked,
                repository=REPOSITORY,
                by=WORKER,
                at=at(1),
                until=[TimeCame(at=at(60))],
            ),
            "parked",
        ),
        (
            partial(
                Done,
                repository=REPOSITORY,
                by=WORKER,
                at=at(1),
                to_try="Type fast.",
            ),
            "done to confirm",
        ),
        (
            partial(Settled, repository=REPOSITORY, by=Operator(), at=at(1)),
            "settled",
        ),
        (
            partial(
                Declined,
                repository=REPOSITORY,
                by=Operator(),
                at=at(1),
                why="Not worth it.",
            ),
            "declined",
        ),
    ],
)
def test_a_thread_stands_as_its_latest_status_says(
    ledger: Ledger,
    threads: Threads,
    said: Callable[..., Parked | Done | Settled | Declined],
    state: str,
) -> None:
    lag = opened(ledger, "lag")
    checked(ledger, lag)
    status = ledger.drawn(said(target=lag.number))

    standing = threads.standing(lag.number)

    assert standing.state == state
    assert standing.status == status
    assert len(standing.waiting) == 1


def test_lup_settles_a_thread_saying_why_and_an_agent_never_does() -> None:
    by_lup = Settled(
        target=1,
        repository=REPOSITORY,
        by=Lup(),
        at=at(1),
        why="nothing waited when threads came: converted",
    )
    assert Settled.model_validate_json(by_lup.model_dump_json()) == by_lup
    assert Settled(target=1, repository=REPOSITORY, by=Operator(), at=at(1)).why == ""
    with pytest.raises(ValidationError):
        Settled.model_validate(
            {
                "target": 1,
                "repository": REPOSITORY,
                "by": WORKER.model_dump(),
                "at": at(1),
            }
        )


def test_reopening_a_thread_brings_it_back_to_what_its_members_say(
    ledger: Ledger, threads: Threads
) -> None:
    lag = opened(ledger, "lag")
    ledger.drawn(
        Done(
            target=lag.number,
            repository=REPOSITORY,
            by=WORKER,
            at=at(1),
            to_try="Type.",
        )
    )
    ledger.drawn(
        Settled(target=lag.number, repository=REPOSITORY, by=Operator(), at=at(2))
    )
    reopened = ledger.drawn(
        Reopened(
            target=lag.number,
            repository=REPOSITORY,
            by=Operator(),
            at=at(3),
            why="Still jumps.",
        )
    )
    working = threads.standing(lag.number)
    checked(ledger, lag)

    assert working.state == "working"
    assert working.status == reopened
    assert threads.standing(lag.number).state == "waiting on the operator"


def test_who_s_on_a_thread_is_its_holder_then_whoever_wrote_what_s_in_it(
    ledger: Ledger, threads: Threads
) -> None:
    lag = opened(ledger, "lag")
    placed(ledger, item(ledger, REVIEWER), lag)
    placed(ledger, item(ledger, Operator()), lag)
    placed(ledger, item(ledger, WORKER), lag)
    checked(ledger, lag, by=REVIEWER)

    assert threads.standing(lag.number).on == [WORKER, REVIEWER]


def test_a_node_moved_to_another_thread_is_in_that_one_alone(
    ledger: Ledger, threads: Threads
) -> None:
    lag = opened(ledger, "lag")
    page = opened(ledger, "page")
    found = checked(ledger, lag)
    placed(ledger, found, page, minutes=1)

    assert threads.members(lag.number) == []
    assert [each.node for each in threads.members(page.number)] == [found]
    assert threads.standing(lag.number).state == "working"
    assert threads.standing(page.number).state == "waiting on the operator"


def test_a_part_moved_into_a_thread_is_in_it_while_its_item_stays_in_its_own(
    ledger: Ledger, threads: Threads
) -> None:
    main = opened(ledger, "main", holder=MAIN)
    lag = opened(ledger, "lag")
    page = opened(ledger, "page")
    review = item(ledger, Operator())
    placed(ledger, review, main)
    ledger.drawn(
        Moved(
            source=review.number,
            target=lag.number,
            part=3,
            repository=REPOSITORY,
            by=MAIN,
            at=at(1),
        )
    )
    ledger.drawn(
        Moved(
            source=review.number,
            target=page.number,
            part=4,
            repository=REPOSITORY,
            by=MAIN,
            at=at(1),
        )
    )
    ledger.drawn(
        Moved(
            source=review.number,
            target=page.number,
            part=3,
            repository=REPOSITORY,
            by=MAIN,
            at=at(2),
        )
    )

    assert [(each.node, each.part) for each in threads.members(main.number)] == [
        (review, None)
    ]
    assert threads.members(lag.number) == []
    assert [each.part for each in threads.members(page.number)] == [4, 3]


def test_an_item_moved_whole_into_a_thread_is_in_both_and_moves_again_alone(
    ledger: Ledger, threads: Threads
) -> None:
    main = opened(ledger, "main", holder=MAIN)
    lag = opened(ledger, "lag")
    gate = opened(ledger, "gate", holder=REVIEWER)
    friction = item(ledger, WORKER)
    placed(ledger, friction, main)

    def gathered(thread: Thread, minutes: int) -> Moved:
        return ledger.drawn(
            Moved(
                source=friction.number,
                target=thread.number,
                repository=REPOSITORY,
                by=Operator(),
                at=at(minutes),
            )
        )

    gathered(lag, 1)
    first = [(each.node, each.part, each.moved) for each in threads.members(lag.number)]
    gathered(gate, 2)

    assert [(each.node, each.moved) for each in threads.members(main.number)] == [
        (friction, False)
    ]
    assert first == [(friction, None, True)]
    assert threads.members(lag.number) == []
    assert [(each.node, each.moved) for each in threads.members(gate.number)] == [
        (friction, True)
    ]
    standing = threads.standing(gate.number)
    assert standing.on == [REVIEWER]
    assert standing.unanswered == []


def test_an_item_moved_in_whole_answers_no_part_of_the_operator_s_words(
    citing: Ledger,
) -> None:
    threads = Threads(ledger=citing)
    main = opened(citing, "main", holder=MAIN)
    lag = opened(citing, "lag", parent=main.number)
    review = item(citing, Operator())
    placed(citing, review, main)
    moved(citing, review, lag, 3)
    friction = item(citing, REVIEWER)
    placed(citing, friction, main)
    cite(citing, friction, review, 3, minutes=2)
    citing.drawn(
        Moved(
            source=friction.number,
            target=lag.number,
            repository=REPOSITORY,
            by=Operator(),
            at=at(3),
        )
    )

    assert [each.part for each in threads.standing(lag.number).unanswered] == [3]


def test_a_reference_from_another_thread_s_item_is_no_member(
    ledger: Ledger, threads: Threads
) -> None:
    lag = opened(ledger, "lag")
    page = opened(ledger, "page")
    said = item(ledger, REVIEWER)
    placed(ledger, said, lag)
    reference = ledger.drawn(
        Refers(
            source=said.number,
            target=page.number,
            repository=REPOSITORY,
            by=REVIEWER,
            at=at(1),
        )
    )

    assert threads.members(page.number) == []
    assert threads.references(page.number) == [reference]
    assert threads.standing(page.number).on == [WORKER]


def test_a_node_of_a_kind_no_class_declares_is_in_a_thread_and_waits_on_nobody(
    ledger: Ledger, threads: Threads
) -> None:
    lag = opened(ledger, "lag")
    said = item(ledger, REVIEWER)
    placed(ledger, said, lag)

    standing = threads.standing(lag.number)

    assert standing.state == "working"
    assert [each.node for each in threads.members(lag.number)] == [said]


def test_sub_threads_and_who_answers_for_a_thread_nobody_holds(
    ledger: Ledger, threads: Threads
) -> None:
    main = opened(ledger, "main", holder=MAIN)
    threading = opened(ledger, "threads", parent=main.number, holder=None)
    store = opened(ledger, "ledger-store", parent=threading.number, holder=None)
    held = opened(ledger, "inbox-onto-it", parent=threading.number)
    opened(ledger, "elsewhere", holder=None, repository=OTHER)

    assert threads.under(main.number) == [threading]
    assert threads.under(threading.number) == [store, held]
    assert threads.answering(store.number) == MAIN
    assert threads.answering(held.number) == WORKER
    assert threads.answering(opened(ledger, "alone", holder=None).number) is None
    assert threads.of(OTHER)[0].name == "elsewhere"


def test_a_holder_that_ended_holds_nothing_and_the_thread_above_answers(
    ledger: Ledger, threads: Threads
) -> None:
    main = opened(ledger, "main", holder=MAIN)
    held = opened(ledger, "held", parent=main.number)

    assert threads.answering(held.number, live=lambda each: each != WORKER) == MAIN
    assert threads.answering(held.number, live=lambda _: False) is None


def test_a_thread_under_what_isn_t_a_thread_of_its_repository_or_under_itself_is_refused(
    ledger: Ledger,
) -> None:
    main = opened(ledger, "main")
    sub = opened(ledger, "sub", parent=main.number)
    elsewhere = opened(ledger, "elsewhere", repository=OTHER)
    said = item(ledger)
    # A number the sequence gave out, at which no node was kept.
    unkept = ledger.numbered()

    refusals = {
        "would be under itself": main.model_copy(
            update={"parent": sub.number, "at": at(1)}
        ),
        "another repository's": sub.model_copy(
            update={"parent": elsewhere.number, "at": at(1)}
        ),
        "not a thread": sub.model_copy(update={"parent": said.number, "at": at(1)}),
        "isn't on the ledger": sub.model_copy(update={"parent": unkept, "at": at(1)}),
    }

    for says, refused in refusals.items():
        with pytest.raises(LupLedgerError, match=says):
            ledger.kept(refused)
    assert ledger.node(sub.number, Thread).parent == main.number


def test_a_thread_is_found_by_its_name_and_nothing_else_is(
    ledger: Ledger, threads: Threads
) -> None:
    lag = opened(ledger, "lag")
    ledger.kept(
        Check(
            number=ledger.numbered(),
            repository=REPOSITORY,
            by=WORKER,
            at=START,
            name="a-check",
            text="x",
        )
    )

    assert threads.named(REPOSITORY, "lag") == lag
    assert threads.named(REPOSITORY, "a-check") is None
    assert threads.named(OTHER, "lag") is None


class Citing(Edge):
    """A citation of a part, standing for the inbox's, whose kind the ledger doesn't declare."""

    kind: Literal["test:cites"] = "test:cites"
    source: int
    part: int | None = None

    @override
    def answers(self, part: int) -> bool:
        return self.part == part


@pytest.fixture
def citing(tmp_path: Path) -> Generator[Ledger]:
    """A ledger reading `Citing` beside its own kinds."""
    kinds = Kinds(nodes=KINDS.nodes, edges=[*KINDS.edges, Citing])
    opened = Ledger.opened(LedgerLayout(home=tmp_path / "citing"), kinds)
    yield opened
    opened.close()


def cite(ledger: Ledger, node: Node, cited: Node, part: int, minutes: int) -> None:
    ledger.drawn(
        Citing(
            source=node.number,
            target=cited.number,
            part=part,
            repository=REPOSITORY,
            by=node.by,
            at=at(minutes),
        )
    )


def moved(ledger: Ledger, review: Node, thread: Thread, part: int) -> None:
    ledger.drawn(
        Moved(
            source=review.number,
            target=thread.number,
            part=part,
            repository=REPOSITORY,
            by=MAIN,
            at=at(1),
        )
    )


def test_a_part_moved_into_a_thread_waits_on_whoever_answers_for_it_until_something_in_it_cites_it(
    citing: Ledger,
) -> None:
    threads = Threads(ledger=citing)
    main = opened(citing, "main", holder=MAIN)
    lag = opened(citing, "lag", parent=main.number)
    review = item(citing, Operator())
    placed(citing, review, main)
    moved(citing, review, lag, 3)
    waiting = threads.standing(lag.number)
    elsewhere = item(citing, REVIEWER)
    placed(citing, elsewhere, main)
    cite(citing, elsewhere, review, 3, minutes=2)
    other = item(citing, WORKER)
    placed(citing, other, lag)
    cite(citing, other, review, 4, minutes=3)
    still = threads.standing(lag.number)
    worker = item(citing, REVIEWER)
    placed(citing, worker, lag)
    cite(citing, worker, review, 3, minutes=4)

    assert [each.part for each in waiting.unanswered] == [3]
    assert waiting.state == "working"
    assert [each.part for each in still.unanswered] == [3]
    assert threads.standing(lag.number).unanswered == []


def test_a_citation_from_outside_a_thread_is_no_answer_whoever_answers_for_it(
    citing: Ledger,
) -> None:
    threads = Threads(ledger=citing)
    main = opened(citing, "main", holder=MAIN)
    lag = opened(citing, "lag", parent=main.number, holder=None)
    review = item(citing, Operator())
    placed(citing, review, main)
    moved(citing, review, lag, 3)
    routed = item(citing, MAIN)
    placed(citing, routed, main)
    cite(citing, routed, review, 3, minutes=2)
    outside = threads.standing(lag.number)
    answer = item(citing, MAIN)
    placed(citing, answer, lag)
    cite(citing, answer, review, 3, minutes=3)

    assert threads.answering(lag.number) == MAIN
    assert [each.part for each in outside.unanswered] == [3]
    assert threads.standing(lag.number).unanswered == []


def test_the_threads_parked_are_those_whose_latest_status_parks_them(
    ledger: Ledger, threads: Threads
) -> None:
    lag = opened(ledger, "lag")
    page = opened(ledger, "page")
    elsewhere = opened(ledger, "elsewhere", repository=OTHER)

    def park(thread: Thread, minutes: int) -> Parked:
        return ledger.drawn(
            Parked(
                target=thread.number,
                repository=thread.repository,
                by=WORKER,
                at=at(minutes),
                until=[BranchLanded(branch="feat")],
            )
        )

    park(lag, 1)
    ledger.drawn(
        Reopened(target=lag.number, repository=REPOSITORY, by=Lup(), at=at(2), why="x")
    )
    paged = park(page, 3)
    other = park(elsewhere, 4)

    assert threads.parked(REPOSITORY) == [paged]
    assert threads.parked() == [paged, other]


def rooted(ledger: Ledger, name: str, holder: Conversation | None = MAIN) -> Thread:
    """Keep a root as an earlier lup kept one for a session: at the top, titled `ROOT`, held by them."""
    return ledger.kept(
        Thread(
            number=ledger.numbered(),
            repository=REPOSITORY,
            by=MAIN,
            at=START,
            name=name,
            title=ROOT,
            holder=holder,
        )
    )


def test_a_root_is_found_by_no_read_and_what_s_under_it_reads_as_at_the_top(
    ledger: Ledger, threads: Threads
) -> None:
    root = rooted(ledger, "dev")
    sshole = opened(ledger, "sshole", parent=root.number, holder=None)
    deeper = opened(ledger, "deeper", parent=sshole.number, holder=None)

    with pytest.raises(LupLedgerError, match="no thread"):
        threads.thread(root.number)
    assert threads.named(REPOSITORY, "dev") is None
    assert threads.thread(sshole.number).parent is None
    assert threads.named(REPOSITORY, "sshole") == threads.thread(sshole.number)
    assert threads.thread(deeper.number).parent == sshole.number
    assert [(each.name, each.parent) for each in threads.of(REPOSITORY)] == [
        ("sshole", None),
        ("deeper", sshole.number),
    ]
    assert [each.name for each in threads.under(sshole.number)] == ["deeper"]
    # Nobody answers for it by the root, whose holder goes on.
    assert threads.answering(sshole.number) is None
    assert threads.answering(deeper.number) is None
    # The ledger keeps the root as it was.
    assert ledger.node(root.number, Thread) == root


def test_without_roots_reads_every_thread_at_once_as_threads_reads_each(
    ledger: Ledger,
) -> None:
    root = rooted(ledger, "dev")
    lag = opened(ledger, "lag", parent=root.number)
    tabs = opened(ledger, "tabs", parent=lag.number)
    titled = opened(ledger, "titled")

    read = without_roots([root, lag, tabs, titled])

    assert [(each.name, each.parent) for each in read] == [
        ("lag", None),
        ("tabs", lag.number),
        ("titled", None),
    ]
    assert root.root
    assert not titled.root
    # A thread under another titled as a root is no root.
    assert not tabs.model_copy(update={"title": ROOT}).root


def test_a_root_parked_is_none_of_the_threads_parked(
    ledger: Ledger, threads: Threads
) -> None:
    root = rooted(ledger, "dev")
    lag = opened(ledger, "lag")
    for each in [root, lag]:
        ledger.drawn(
            Parked(
                target=each.number,
                repository=REPOSITORY,
                by=MAIN,
                at=at(1),
                until=[BranchLanded(branch="x")],
            )
        )

    assert [each.target for each in threads.parked(REPOSITORY)] == [lag.number]


def test_a_thread_nobody_running_answers_for_stands_nobody_running_never_working(
    ledger: Ledger, threads: Threads
) -> None:
    lag = opened(ledger, "lag", holder=WORKER)
    unheld = opened(ledger, "unheld", holder=None)
    under = opened(ledger, "under", parent=lag.number, holder=None)

    def ended(conversation: Conversation) -> bool:
        return conversation != WORKER

    assert threads.standing(lag.number).state == "working"
    assert threads.standing(lag.number, live=ended).state == "nobody running"
    assert threads.standing(unheld.number).state == "nobody running"
    assert threads.standing(under.number).state == "working"
    assert threads.standing(under.number, live=ended).state == "nobody running"
    # What waits on the operator still says so; and a status said is said.
    checked(ledger, unheld)
    assert threads.standing(unheld.number).state == "waiting on the operator"
    ledger.drawn(
        Done(target=lag.number, repository=REPOSITORY, by=WORKER, at=at(2), to_try="x")
    )
    assert threads.standing(lag.number, live=ended).state == "done to confirm"


def done(thread: Thread, minutes: int, to_try: str = "Type fast.") -> Done:
    return Done(
        target=thread.number,
        repository=thread.repository,
        by=WORKER,
        at=at(minutes),
        to_try=to_try,
    )


def settled(thread: Thread, minutes: int) -> Settled:
    return Settled(
        target=thread.number,
        repository=thread.repository,
        by=Operator(),
        at=at(minutes),
    )


def test_the_agent_s_mark_and_the_operator_s_are_read_apart_neither_moving_the_other(
    ledger: Ledger, threads: Threads
) -> None:
    # Said done, then cleared: cleared, the agent's account kept.
    lag = opened(ledger, "lag")
    said = ledger.drawn(done(lag, 1))
    cleared = ledger.drawn(settled(lag, 2))
    # Cleared while the agent is still on it, then said done: still cleared, never
    # back before the operator, as an earlier lup read its latest status.
    page = opened(ledger, "page")
    page_cleared = ledger.drawn(settled(page, 1))
    page_said = ledger.drawn(done(page, 2, "Scroll."))

    for thread, account, clearing in [
        (lag, said, cleared),
        (page, page_said, page_cleared),
    ]:
        standing = threads.standing(thread.number)
        assert standing.state == "settled"
        assert standing.marks == Marks(agent=account, operator=clearing)
        assert standing.marks.done == account


def test_the_operator_reopening_opens_both_marks_and_lup_reopening_the_agent_s_alone(
    ledger: Ledger, threads: Threads
) -> None:
    lag = opened(ledger, "lag")
    ledger.drawn(done(lag, 1))
    ledger.drawn(settled(lag, 2))
    ledger.drawn(
        Reopened(target=lag.number, repository=REPOSITORY, by=Operator(), at=at(3))
    )
    page = opened(ledger, "page")
    clearing = ledger.drawn(settled(page, 1))
    ledger.drawn(
        Parked(
            target=page.number,
            repository=REPOSITORY,
            by=WORKER,
            at=at(2),
            until=[TimeCame(at=at(60))],
        )
    )
    ledger.drawn(
        Reopened(target=page.number, repository=REPOSITORY, by=Lup(), at=at(3), why="x")
    )

    assert threads.marks(lag.number) == Marks()
    assert threads.standing(lag.number).state == "working"
    assert threads.marks(page.number) == Marks(operator=clearing)
    assert threads.standing(page.number).state == "settled"


def test_a_sub_thread_is_cleared_apart_from_its_parent_and_its_parent_apart_from_it(
    ledger: Ledger, threads: Threads
) -> None:
    lag = opened(ledger, "lag")
    under = opened(ledger, "under", parent=lag.number)
    other = opened(ledger, "other")
    beneath = opened(ledger, "beneath", parent=other.number)
    ledger.drawn(settled(lag, 1))
    said = ledger.drawn(done(beneath, 1))

    assert threads.standing(lag.number).state == "settled"
    assert threads.standing(under.number).state == "working"
    assert threads.standing(other.number).marks == Marks()
    assert threads.standing(beneath.number).marks == Marks(agent=said)


def test_a_thread_the_operator_cleared_is_none_of_the_threads_parked_however_late_it_was_parked(
    ledger: Ledger, threads: Threads
) -> None:
    lag = opened(ledger, "lag")
    ledger.drawn(settled(lag, 1))
    ledger.drawn(
        Parked(
            target=lag.number,
            repository=REPOSITORY,
            by=WORKER,
            at=at(2),
            until=[BranchLanded(branch="feat")],
        )
    )

    assert threads.parked(REPOSITORY) == []
