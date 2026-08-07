"""Behavioral contract of the resolver entry: headless answers and note intake."""

from pathlib import Path

import pytest
import typer

from lup.codescan.markers import NoteKind
from lup.resolver.mailbox import AnswerDoor, QuestionMailbox
from lup.resolver.models import MaterialQuestion, QuestionBatch
from lup_template.devtools.dev.comments import FoundComment
from lup_template.devtools.harness.resolve import (
    NoteTargetRef,
    admission_notes,
    admission_request,
    offer_flag_answers,
    parse_answer_flags,
    parse_note_targets,
    resolver_intake,
)


def material_question(
    identifier: str,
    choices: list[str] | None = None,
    recommendation: str | None = None,
) -> MaterialQuestion:
    return MaterialQuestion(
        id=identifier,
        concern_id="concern-1",
        prompt=f"prompt for {identifier}",
        choices=choices or [],
        recommendation=recommendation,
    )


def question_batch(questions: list[MaterialQuestion]) -> QuestionBatch:
    return QuestionBatch(run_id="run-7", questions=questions)


def test_parse_answer_flags_maps_ids_and_keeps_values_with_equals() -> None:
    parsed = parse_answer_flags(["q-1=yes", "q-2=a=b"])

    assert parsed == {"q-1": "yes", "q-2": "a=b"}


def test_parse_answer_flags_rejects_malformed_and_duplicate_flags() -> None:
    with pytest.raises(typer.BadParameter):
        parse_answer_flags(["missing-separator"])
    with pytest.raises(typer.BadParameter):
        parse_answer_flags(["=value"])
    with pytest.raises(typer.BadParameter):
        parse_answer_flags(["q-1=a", "q-1=b"])


def test_flag_answers_become_offers(tmp_path: Path) -> None:
    mailbox = QuestionMailbox(tmp_path)

    offer_flag_answers(mailbox, "run-7", {"q-1": "yes", "q-2": "free text"})

    assert [(item.question_id, item.value, item.door) for item in mailbox.offers()] == [
        ("q-1", "yes", AnswerDoor.FLAG),
        ("q-2", "free text", AnswerDoor.FLAG),
    ]


def test_a_flag_may_answer_a_question_the_run_has_not_asked_yet(
    tmp_path: Path,
) -> None:
    """Offers precede questions, so a fresh run need not park once first."""
    mailbox = QuestionMailbox(tmp_path)

    offer_flag_answers(mailbox, "run-7", {"q-9": "x"})

    assert mailbox.questions() == []
    assert [item.question_id for item in mailbox.offers()] == ["q-9"]
    assert mailbox.answers() == []


def intake_note(kind: NoteKind = "note", condition: str | None = None) -> FoundComment:
    return FoundComment(
        file="parked.py",
        start_line=2,
        end_line=2,
        read_start=1,
        read_end=4,
        text="body",
        kind=kind,
        condition=condition,
        context="",
    )


def test_resolver_intake_excludes_deferred_notes_from_the_inventory() -> None:
    open_note = intake_note()
    parked = intake_note(kind="defer", condition="until v2 lands")
    bare = intake_note(kind="defer")

    intake = resolver_intake([open_note, parked, bare])

    assert intake.actionable == [open_note]
    assert intake.carried == [
        "carrying deferred[until v2 lands] parked.py:2-2",
        "carrying deferred parked.py:2-2",
    ]


def test_note_targets_parse_a_path_and_a_line() -> None:
    assert parse_note_targets(["src/module.py:42"]) == [
        NoteTargetRef(file=Path("src/module.py"), line=42)
    ]
    with pytest.raises(typer.BadParameter):
        parse_note_targets(["src/module.py"])
    with pytest.raises(typer.BadParameter):
        parse_note_targets([":42"])


def test_an_invocation_without_admission_evidence_asks_for_nothing() -> None:
    """Every other resolver invocation must stay an ordinary drive."""
    assert admission_request([], []) is None


def test_admitted_statements_become_the_evidence_a_run_plans_from() -> None:
    request = admission_request(["the relay must investigate first"], [])

    assert request is not None
    assert request.statements == ["the relay must investigate first"]
    assert request.notes == []


def test_an_admitted_note_carries_the_text_and_context_the_tree_holds() -> None:
    """An admitted note is the note itself, not a retyped paraphrase."""
    scanned = intake_note()

    notes = admission_notes([NoteTargetRef(file=Path("parked.py"), line=2)], [scanned])

    assert [(note.file, note.line, note.text) for note in notes] == [
        (Path("parked.py"), 2, "body")
    ]


def test_an_admitted_note_target_that_names_no_open_note_is_refused() -> None:
    """A deferred note never reaches the actionable set, so it is refused."""
    with pytest.raises(typer.BadParameter, match="no actionable"):
        admission_notes(
            [NoteTargetRef(file=Path("parked.py"), line=2)],
            resolver_intake(
                [intake_note(kind="defer", condition="until v2 lands")]
            ).actionable,
        )
