"""The ledger's records: kinds, names, who writes them, and what each kind refuses on its own."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from pydantic import TypeAdapter, ValidationError

from lup_ledger.parties import Conversation, Lup, Operator, Party, Writer
from lup_ledger.records import Edge, Kinds, Node
from lup_ledger.threads import (
    KINDS,
    BranchLanded,
    Check,
    ConditionHeld,
    Done,
    IssueClosed,
    Parked,
    Settled,
    Thread,
    TimeCame,
)

REPOSITORY = Path("/work/lup.git")
MAIN = Conversation(repository=REPOSITORY, runtime="r", session="s1")
AT = datetime(2026, 10, 29, 12, tzinfo=UTC)


class Finding(Node):
    kind: Literal["project:finding"] = "project:finding"
    name: str | None = None
    claim: str


def test_a_record_of_a_kind_no_class_declares_reads_as_the_base_with_every_field() -> (
    None
):
    stored = Finding(
        number=7, repository=REPOSITORY, by=MAIN, at=AT, claim="It holds."
    ).model_dump_json()

    read = KINDS.node("project:finding").model_validate_json(stored)

    assert type(read) is Node
    assert read.kind == "project:finding"
    assert read.model_dump_json() == stored


def test_a_record_reads_as_the_class_declaring_its_kind() -> None:
    kinds = Kinds(nodes=[*KINDS.nodes, Finding], edges=KINDS.edges)

    assert kinds.node("project:finding") is Finding
    assert kinds.node("ledger:thread") is Thread
    assert kinds.edge("project:supports") is Edge


def test_two_classes_declaring_one_kind_are_refused() -> None:
    class Again(Node):
        kind: Literal["ledger:check"] = "ledger:check"
        name: str | None = None

    with pytest.raises(ValidationError, match="two classes declare ledger:check"):
        Kinds(nodes=[Check, Again])


def test_a_class_declaring_no_kind_is_refused() -> None:
    with pytest.raises(ValidationError, match="Node declare no kind"):
        Kinds(nodes=[Node])


@pytest.mark.parametrize("name", ["dashboard-lag", "v2", "room.homes", "2fa_login"])
def test_a_name_with_a_letter_is_taken(name: str) -> None:
    thread = Thread(
        number=1, repository=REPOSITORY, by=MAIN, at=AT, name=name, title="t"
    )

    assert thread.name == name


@pytest.mark.parametrize("name", ["2410", "2159.3", "-x", "two words", "", "a" * 65])
def test_a_name_that_could_read_as_a_number_or_a_part_or_isnt_one_is_refused(
    name: str,
) -> None:
    with pytest.raises(ValidationError, match="a node's name is"):
        Thread(number=1, repository=REPOSITORY, by=MAIN, at=AT, name=name, title="t")


def test_parties_read_as_the_inbox_stored_its_own_and_keep_their_keys() -> None:
    """The inbox's files of an earlier lup named each party so, and each conversation's whereabouts by its key."""
    stored = [
        '{"party":"operator"}',
        '{"party":"conversation","repository":"/work/lup.git","runtime":"claude","session":"s1","agent":null}',
        '{"party":"conversation","repository":"/work/lup.git","runtime":"claude","session":"s1","agent":"a1"}',
    ]
    party = TypeAdapter[Party](Party)

    read = [party.validate_json(each) for each in stored]

    assert [each.model_dump_json() for each in read] == stored
    assert [each.key() for each in read if isinstance(each, Conversation)] == [
        "2e07ae0bea3110e3af11358b3fca149f3ac54e86bba431800c5e15b49af605cb",
        "5cf8878928910a2a3afa25e82f15d00ea9b28df47acb1ed40a399e57f7f1f47e",
    ]


def test_lup_writes_records_and_is_no_party() -> None:
    writer = TypeAdapter[Writer](Writer)

    assert writer.validate_json('{"party":"lup"}') == Lup()
    with pytest.raises(ValidationError):
        TypeAdapter[Party](Party).validate_json('{"party":"lup"}')


def test_only_the_operator_settles_and_only_an_agent_says_done() -> None:
    said = {"target": 1, "repository": REPOSITORY, "at": AT}
    with pytest.raises(ValidationError):
        Settled.model_validate({**said, "by": MAIN})
    with pytest.raises(ValidationError):
        Done.model_validate({**said, "by": Operator(), "to_try": "Type."})
    assert Settled.model_validate({**said, "by": Operator()}).stands == "settled"


def test_a_parked_thread_waits_for_one_trigger_at_least() -> None:
    with pytest.raises(ValidationError):
        Parked(target=1, repository=REPOSITORY, by=MAIN, at=AT, until=[])


def test_triggers_are_read_back_by_what_they_wait_for() -> None:
    parked = Parked(
        target=1,
        repository=REPOSITORY,
        by=MAIN,
        at=AT,
        until=[
            IssueClosed(issue=324),
            BranchLanded(branch="room-homes"),
            TimeCame(at=AT),
            ConditionHeld(when="python_315"),
        ],
    )

    read = Parked.model_validate_json(parked.model_dump_json())

    assert read == parked
    assert [type(each) for each in read.until] == [
        IssueClosed,
        BranchLanded,
        TimeCame,
        ConditionHeld,
    ]


def test_a_thread_is_never_its_own_parent() -> None:
    thread = Thread(
        number=4,
        repository=REPOSITORY,
        by=MAIN,
        at=AT,
        name="loop",
        title="t",
        parent=4,
    )

    assert thread.refused(lambda _number: None) == "@4 would be under itself"
