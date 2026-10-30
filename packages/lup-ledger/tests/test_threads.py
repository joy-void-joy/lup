"""Threads on the ledger: what's in one, where it stands, who's on it, and the threads above and under it."""

from datetime import UTC, datetime, timedelta
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
    Answered,
    BranchLanded,
    Check,
    Declined,
    Done,
    In,
    Moved,
    Parked,
    Refers,
    Reopened,
    Settled,
    Standing,
    Thread,
    TimeCame,
)

if TYPE_CHECKING:
    from collections.abc import Generator

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
            Parked(
                target=1,
                repository=REPOSITORY,
                by=WORKER,
                at=at(1),
                until=[TimeCame(at=at(60))],
            ),
            "parked",
        ),
        (
            Done(
                target=1,
                repository=REPOSITORY,
                by=WORKER,
                at=at(1),
                to_try="Type fast.",
            ),
            "done to confirm",
        ),
        (Settled(target=1, repository=REPOSITORY, by=Operator(), at=at(1)), "settled"),
        (
            Declined(
                target=1,
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
    said: Parked | Done | Settled | Declined,
    state: str,
) -> None:
    lag = opened(ledger, "lag")
    checked(ledger, lag)
    ledger.drawn(said)

    standing = threads.standing(lag.number)

    assert standing.state == state
    assert standing.status == said
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

    refusals = {
        "would be under itself": main.model_copy(
            update={"parent": sub.number, "at": at(1)}
        ),
        "another repository's": sub.model_copy(
            update={"parent": elsewhere.number, "at": at(1)}
        ),
        "not a thread": sub.model_copy(update={"parent": said.number, "at": at(1)}),
        "isn't on the ledger": sub.model_copy(update={"parent": 99, "at": at(1)}),
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
