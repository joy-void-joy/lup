"""The ledger's store: one sequence of numbers, every version kept, names, edges, and reads that never walk it."""

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pytest

from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.errors import LupLedgerError
from lup_ledger.parties import Conversation, Lup, Operator
from lup_ledger.records import Edge, Node
from lup_ledger.threads import (
    Answered,
    Check,
    Done,
    In,
    Moved,
    Settled,
    Thread,
)

if TYPE_CHECKING:
    from lup_ledger.environment.threads import Threads

REPOSITORY = Path("/work/lup.git")
OTHER = Path("/work/other.git")
MAIN = Conversation(repository=REPOSITORY, runtime="r", session="s1")
START = datetime(2026, 10, 29, 12, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return START + timedelta(minutes=minutes)


def thread(
    ledger: Ledger,
    name: str,
    *,
    repository: Path = REPOSITORY,
    number: int | None = None,
) -> Thread:
    return Thread(
        number=ledger.numbered() if number is None else number,
        repository=repository,
        by=MAIN,
        at=START,
        name=name,
        title=f"About {name}",
    )


def check(ledger: Ledger, text: str = "Try it.") -> Check:
    return ledger.kept(
        Check(
            number=ledger.numbered(),
            repository=REPOSITORY,
            by=MAIN,
            at=START,
            text=text,
        )
    )


def test_every_number_is_one_sequence_s_across_repositories(ledger: Ledger) -> None:
    first = ledger.kept(thread(ledger, "one"))
    second = ledger.kept(thread(ledger, "one", repository=OTHER))

    assert [first.number, second.number, ledger.numbered()] == [1, 2, 3]


def test_a_number_taken_is_never_taken_again_once_reopened(tmp_path: Path) -> None:
    layout = LedgerLayout(home=tmp_path)
    ledger = Ledger.opened(layout)
    kept = ledger.kept(thread(ledger, "one"))
    ledger.numbered()
    ledger.close()

    reopened = Ledger.opened(layout)

    assert reopened.node(kept.number, Thread) == kept
    assert reopened.numbered() == 3
    reopened.close()


def test_a_node_kept_with_its_own_number_moves_the_sequence_past_it(
    ledger: Ledger,
) -> None:
    ledger.kept(thread(ledger, "converted", number=2410))

    assert ledger.numbered() == 2411


def test_a_change_appends_a_version_at_its_own_time(ledger: Ledger) -> None:
    kept = ledger.kept(thread(ledger, "lag"))
    ledger.kept(kept.model_copy(update={"title": "The page lags", "at": at(5)}))
    ledger.kept(kept.model_copy(update={"holder": MAIN, "at": at(9)}))

    versions = ledger.versions(kept.number)

    assert [each.at for each in versions] == [START, at(5), at(9)]
    assert [each.title for each in versions if isinstance(each, Thread)] == [
        "About lag",
        "The page lags",
        "About lag",
    ]
    assert ledger.node(kept.number, Thread).holder == MAIN


def test_a_version_not_after_the_one_before_is_refused(ledger: Ledger) -> None:
    kept = ledger.kept(thread(ledger, "lag"))

    with pytest.raises(LupLedgerError, match="not after its last"):
        ledger.kept(kept.model_copy(update={"title": "Same time"}))

    assert len(ledger.versions(kept.number)) == 1


def test_a_node_stays_its_kind_and_in_its_repository(ledger: Ledger) -> None:
    kept = ledger.kept(thread(ledger, "lag"))
    moved = kept.model_copy(update={"repository": OTHER, "at": at(1)})
    other = Check(
        number=kept.number, repository=REPOSITORY, by=MAIN, at=at(1), text="x"
    )

    with pytest.raises(LupLedgerError, match="stays there"):
        ledger.kept(moved)
    with pytest.raises(LupLedgerError, match="stays one"):
        ledger.kept(other)


def test_a_name_is_one_node_s_in_its_repository(ledger: Ledger) -> None:
    ledger.kept(thread(ledger, "lag"))
    ledger.kept(thread(ledger, "lag", repository=OTHER))

    with pytest.raises(LupLedgerError, match="`lag` names @1"):
        ledger.kept(thread(ledger, "lag"))


def test_renaming_frees_the_name_it_had(ledger: Ledger) -> None:
    kept = ledger.kept(thread(ledger, "lag"))
    ledger.kept(kept.model_copy(update={"name": "page-lag", "at": at(1)}))

    again = ledger.kept(thread(ledger, "lag"))

    assert ledger.named(REPOSITORY, "lag") == again
    assert ledger.named(REPOSITORY, "page-lag") is not None


def test_an_agent_s_name_is_refused_as_a_new_name_but_kept_as_one_held(
    ledger: Ledger,
) -> None:
    with pytest.raises(LupLedgerError, match="`review-drawer` is an agent's name"):
        ledger.kept(thread(ledger, "review-drawer"), taken=["review-drawer"])
    kept = ledger.kept(thread(ledger, "drawer"))

    held = ledger.kept(
        kept.model_copy(update={"title": "The drawer", "at": at(1)}), taken=["drawer"]
    )

    assert held.title == "The drawer"


class Finding(Node):
    kind: Literal["project:finding"] = "project:finding"
    name: str | None = None
    claim: str


def test_a_kind_no_class_declares_is_kept_whole_through_a_new_version(
    ledger: Ledger,
) -> None:
    finding = Finding(
        number=ledger.numbered(),
        repository=REPOSITORY,
        by=MAIN,
        at=START,
        claim="Holds.",
    )
    ledger.kept(finding)

    read = ledger.node(finding.number, Node)
    ledger.kept(read.model_copy(update={"name": "the-claim", "at": at(1)}))

    assert type(read) is Node
    assert read.model_dump() == finding.model_dump()
    assert Finding.model_validate(ledger.node(finding.number, Node).model_dump()) == (
        finding.model_copy(update={"name": "the-claim", "at": at(1)})
    )


def test_a_node_of_another_kind_than_asked_is_refused(ledger: Ledger) -> None:
    found = check(ledger)

    with pytest.raises(
        LupLedgerError, match="is a `ledger:check`, not a `ledger:thread`"
    ):
        ledger.node(found.number, Thread)
    with pytest.raises(LupLedgerError, match="holds no @99"):
        ledger.node(99, Node)


def test_a_repository_s_nodes_are_read_by_kind(ledger: Ledger) -> None:
    first = ledger.kept(thread(ledger, "one"))
    found = check(ledger)
    ledger.kept(thread(ledger, "elsewhere", repository=OTHER))

    assert ledger.nodes(REPOSITORY, Thread) == [first]
    assert ledger.nodes(REPOSITORY, Node) == [first, found]


@pytest.mark.parametrize("said", ["1", "@1", "lag", "@lag"])
def test_at_takes_a_number_or_a_name(ledger: Ledger, said: str) -> None:
    kept = ledger.kept(thread(ledger, "lag"))

    assert ledger.cited(REPOSITORY, said) == kept


@pytest.mark.parametrize("said", ["@2", "@1.3", "@nothing"])
def test_at_refuses_another_repository_s_node_a_part_or_nothing(
    ledger: Ledger, said: str
) -> None:
    ledger.kept(thread(ledger, "lag"))
    ledger.kept(thread(ledger, "elsewhere", repository=OTHER))

    with pytest.raises(LupLedgerError, match=f"is `{said}`"):
        ledger.cited(REPOSITORY, said)


def test_edges_are_read_in_the_order_drawn(ledger: Ledger) -> None:
    lag = ledger.kept(thread(ledger, "lag"))
    found = check(ledger)
    placed = ledger.drawn(
        In(
            source=found.number,
            target=lag.number,
            repository=REPOSITORY,
            by=MAIN,
            at=at(2),
        )
    )
    answered = ledger.drawn(
        Answered(target=found.number, repository=REPOSITORY, by=Operator(), at=at(1))
    )
    settled = ledger.drawn(
        Settled(target=lag.number, repository=REPOSITORY, by=Operator(), at=at(0))
    )

    assert ledger.drawn_to(lag.number, Edge) == [placed, settled]
    assert ledger.drawn_to(lag.number, Settled) == [settled]
    assert ledger.drawn_to(found.number, Edge) == [answered]
    assert ledger.drawn_from(found.number, Edge) == [placed]


def test_an_edge_needs_both_ends_on_the_ledger_and_in_its_repository(
    ledger: Ledger,
) -> None:
    lag = ledger.kept(thread(ledger, "lag"))
    elsewhere = ledger.kept(thread(ledger, "elsewhere", repository=OTHER))
    found = check(ledger)

    with pytest.raises(LupLedgerError, match="@99 isn't on the ledger"):
        ledger.drawn(
            In(source=99, target=lag.number, repository=REPOSITORY, by=MAIN, at=START)
        )
    with pytest.raises(LupLedgerError, match="@99 isn't on the ledger"):
        ledger.drawn(
            In(source=found.number, target=99, repository=REPOSITORY, by=MAIN, at=START)
        )
    with pytest.raises(LupLedgerError, match=f"@{elsewhere.number} is of {OTHER}"):
        ledger.drawn(
            In(
                source=found.number,
                target=elsewhere.number,
                repository=REPOSITORY,
                by=MAIN,
                at=START,
            )
        )
    assert ledger.drawn_to(lag.number, Edge) == []


def test_an_edge_s_kind_refuses_the_ends_it_can_t_join(ledger: Ledger) -> None:
    lag = ledger.kept(thread(ledger, "lag"))
    sub = ledger.kept(thread(ledger, "sub"))
    found = check(ledger)

    refused = [
        In(
            source=found.number,
            target=found.number,
            repository=REPOSITORY,
            by=MAIN,
            at=START,
        ),
        In(
            source=sub.number,
            target=lag.number,
            repository=REPOSITORY,
            by=MAIN,
            at=START,
        ),
        Answered(target=lag.number, repository=REPOSITORY, by=Operator(), at=START),
        Done(
            target=found.number, repository=REPOSITORY, by=MAIN, at=START, to_try="Try."
        ),
        Moved(
            source=found.number,
            target=found.number,
            part=1,
            repository=REPOSITORY,
            by=MAIN,
            at=START,
        ),
    ]

    for each in refused:
        with pytest.raises(LupLedgerError, match="can't draw"):
            ledger.drawn(each)


def test_a_later_edge_from_the_same_node_replaces_an_earlier_one_where_its_kind_says(
    ledger: Ledger,
) -> None:
    lag = ledger.kept(thread(ledger, "lag"))
    page = ledger.kept(thread(ledger, "page"))
    found = check(ledger)
    first = ledger.drawn(
        In(
            source=found.number,
            target=lag.number,
            repository=REPOSITORY,
            by=MAIN,
            at=at(1),
        )
    )
    second = ledger.drawn(
        In(
            source=found.number,
            target=page.number,
            repository=REPOSITORY,
            by=MAIN,
            at=at(2),
        )
    )

    assert ledger.drawn_to(lag.number, In) == [first]
    assert ledger.drawn_to(lag.number, In, current=True) == []
    assert ledger.drawn_to(page.number, In, current=True) == [second]
    assert ledger.drawn_from(found.number, In, current=True) == [second]


def test_nothing_is_kept_of_a_refused_write(ledger: Ledger) -> None:
    lag = ledger.kept(thread(ledger, "lag"))

    with pytest.raises(LupLedgerError):
        ledger.kept(thread(ledger, "lag"))

    assert ledger.nodes(REPOSITORY, Node) == [lag]
    assert ledger.versions(2) == []


def test_a_ledger_whose_tables_are_a_later_version_is_refused(tmp_path: Path) -> None:
    layout = LedgerLayout(home=tmp_path)
    Ledger.opened(layout).close()
    with sqlite3.connect(layout.database) as database:
        database.execute("PRAGMA user_version = 7")

    with pytest.raises(LupLedgerError, match="version 7 of its tables"):
        Ledger.opened(layout)


def test_a_ledger_at_the_first_version_is_brought_to_the_second_keeping_its_records(
    tmp_path: Path,
) -> None:
    layout = LedgerLayout(home=tmp_path)
    first = Ledger.opened(layout, schema=1)
    kept = first.kept(thread(first, "lag"))
    first.close()

    second = Ledger.opened(layout)
    second.rewritten("draft", Operator())

    assert second.node(kept.number, Thread) == kept
    assert second.every(Thread) == [kept]
    assert second.plain("draft", Operator) == Operator()
    assert second.connection.execute("PRAGMA user_version").fetchone()[0] == 2
    second.close()


def test_threads_of_the_host_keep_and_draw_at_once(ledger: Ledger) -> None:
    lag = ledger.kept(thread(ledger, "lag"))
    failures: list[BaseException] = []

    def work(worker: int) -> None:
        try:
            for each in range(25):
                kept = ledger.kept(thread(ledger, f"t{worker}-{each}"))
                found = check(ledger)
                ledger.drawn(
                    In(
                        source=found.number,
                        target=kept.number,
                        repository=REPOSITORY,
                        by=MAIN,
                        at=START,
                    )
                )
                ledger.kept(kept.model_copy(update={"title": "Changed", "at": at(1)}))
                ledger.drawn(
                    In(
                        source=found.number,
                        target=lag.number,
                        repository=REPOSITORY,
                        by=MAIN,
                        at=at(1),
                    )
                )
        except BaseException as failed:
            failures.append(failed)

    workers = [threading.Thread(target=work, args=(each,)) for each in range(8)]
    for each in workers:
        each.start()
    for each in workers:
        each.join()

    assert failures == []
    nodes = ledger.nodes(REPOSITORY, Node)
    assert len(nodes) == 1 + 8 * 25 * 2
    assert len({each.number for each in nodes}) == len(nodes)
    assert all(
        len(ledger.versions(each.number)) == 2
        for each in ledger.nodes(REPOSITORY, Thread)[1:]
    )
    assert len(ledger.drawn_to(lag.number, In, current=True)) == 8 * 25


def test_no_read_or_write_walks_the_store(ledger: Ledger, threads: Threads) -> None:
    statements: list[str] = []
    ledger.connection.set_trace_callback(statements.append)
    parent = ledger.kept(thread(ledger, "parent"))
    lag = ledger.kept(
        thread(ledger, "lag").model_copy(update={"parent": parent.number})
    )
    ledger.kept(lag.model_copy(update={"title": "Changed", "at": at(1)}))
    found = check(ledger)
    ledger.drawn(
        In(
            source=found.number,
            target=lag.number,
            repository=REPOSITORY,
            by=MAIN,
            at=at(1),
        )
    )
    ledger.drawn(
        Answered(target=found.number, repository=REPOSITORY, by=Operator(), at=at(2))
    )
    ledger.versions(lag.number)
    ledger.cited(REPOSITORY, "@lag")
    ledger.cited(REPOSITORY, "@1")
    ledger.nodes(REPOSITORY, Thread)
    ledger.nodes(REPOSITORY, Node)
    ledger.drawn_from(found.number, Edge, current=True)
    threads.standing(lag.number)
    threads.under(parent.number)
    threads.answering(lag.number)
    ledger.every(Thread)
    ledger.every(Node)
    ledger.keeps(Check)
    ledger.drawn_of(Edge)
    ledger.rewritten("draft", lag)
    ledger.plain("draft", Thread)
    ledger.plains("dr", Thread)
    ledger.connection.set_trace_callback(None)

    plans = [
        (statement, detail)
        for statement in (each.strip() for each in statements)
        if statement.startswith(("SELECT", "INSERT", "UPDATE", "WITH"))
        for *_, detail in ledger.connection.execute(f"EXPLAIN QUERY PLAN {statement}")
    ]

    walks = [
        (statement, detail)
        for statement, detail in plans
        if detail.startswith("SCAN") and detail != "SCAN sequence"
    ]
    assert plans
    assert walks == []


def test_writes_held_together_are_kept_together_or_not_at_all(ledger: Ledger) -> None:
    lag = ledger.kept(thread(ledger, "lag"))

    def refused() -> None:
        with ledger.writing():
            ledger.kept(thread(ledger, "kept"))
            ledger.kept(thread(ledger, "lag"))

    with pytest.raises(LupLedgerError):
        refused()
    with ledger.writing():
        cache = ledger.kept(thread(ledger, "cache"))
        with pytest.raises(LupLedgerError):
            ledger.kept(thread(ledger, "cache"))
        voice = ledger.kept(thread(ledger, "voice"))

    assert ledger.nodes(REPOSITORY, Thread) == [lag, cache, voice]


def test_a_kind_is_read_across_repositories(ledger: Ledger) -> None:
    assert not ledger.keeps(Thread)
    lag = ledger.kept(thread(ledger, "lag"))
    other = ledger.kept(thread(ledger, "lag", repository=OTHER))
    found = check(ledger)
    answered = ledger.drawn(
        Answered(target=found.number, repository=REPOSITORY, by=Operator(), at=at(1))
    )
    moved = ledger.drawn(
        In(
            source=found.number,
            target=lag.number,
            repository=REPOSITORY,
            by=MAIN,
            at=at(2),
        )
    )

    assert ledger.keeps(Thread)
    assert ledger.every(Thread) == [lag, other]
    assert ledger.every(Node) == [lag, other, found]
    assert ledger.drawn_of(Answered) == [answered]
    assert ledger.drawn_of(Edge) == [answered, moved]


def test_lup_writes_what_it_does_of_its_own_accord(ledger: Ledger) -> None:
    found = check(ledger)
    answered = ledger.drawn(
        Answered(target=found.number, repository=REPOSITORY, by=Operator(), at=at(1))
    )
    told = ledger.drawn(
        Edge(
            kind="inbox:told",
            target=found.number,
            source=None,
            repository=REPOSITORY,
            by=Lup(),
            at=at(2),
        )
    )

    assert ledger.drawn_to(found.number, Edge) == [answered, told]
    assert told.by == Lup()


def test_a_plain_record_is_rewritten_in_place(ledger: Ledger) -> None:
    assert ledger.plain("draft", Thread) is None
    ledger.rewritten("draft", thread(ledger, "one"))
    ledger.rewritten("draft", thread(ledger, "two"))

    found = ledger.plain("draft", Thread)

    assert found is not None
    assert found.name == "two"
    assert ledger.connection.execute("SELECT count(*) FROM records").fetchone()[0] == 1
    with pytest.raises(LupLedgerError, match="record `draft` doesn't read"):
        ledger.plain("draft", Check)


def test_plain_records_are_read_by_the_start_of_their_names(ledger: Ledger) -> None:
    for name in ["talk:b", "talk:a", "talks", "talk", "draft"]:
        ledger.rewritten(name, Operator())

    assert list(ledger.plains("talk:", Operator)) == ["talk:a", "talk:b"]
    assert list(ledger.plains("talk", Operator)) == [
        "talk",
        "talk:a",
        "talk:b",
        "talks",
    ]
    assert ledger.plains("order:", Operator) == {}


def test_an_attachment_is_kept_once_by_its_content(ledger: Ledger) -> None:
    diff = b"+ a line\n" * 1000

    first = ledger.attached(diff)
    second = ledger.attached(diff)

    assert first == second
    assert ledger.attachment(first) == diff
    assert ledger.attachment("0" * 64) is None
    assert [each.name for each in ledger.layout.attachments.iterdir()] == [first]
