"""Behavioral contract of the resolver entry: headless answers and note intake."""

import asyncio

import pytest
import typer

from lup.codescan.markers import NoteKind
from lup.resolver.models import (
    AnswerBatch,
    MaterialQuestion,
    QuestionAnswer,
    QuestionBatch,
)
from lup_template.devtools.dev.comments import FoundComment
from lup_template.devtools.harness.resolve import (
    HeadlessQuestionBroker,
    ResolverAwaitingAnswers,
    parse_answer_flags,
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


def test_headless_broker_answers_a_fully_covered_batch() -> None:
    questions = question_batch(
        [material_question("q-1", ["yes", "no"]), material_question("q-2")]
    )
    broker = HeadlessQuestionBroker({"q-1": "yes", "q-2": "free text"})

    answers = asyncio.run(broker.ask(questions))

    assert answers == AnswerBatch(
        run_id="run-7",
        answers=[
            QuestionAnswer(question_id="q-1", value="yes"),
            QuestionAnswer(question_id="q-2", value="free text"),
        ],
    )


def test_headless_broker_parks_on_missing_invalid_and_unknown_answers() -> None:
    questions = question_batch(
        [material_question("q-1", ["yes", "no"]), material_question("q-2")]
    )
    broker = HeadlessQuestionBroker({"q-1": "maybe", "q-9": "x"})

    with pytest.raises(ResolverAwaitingAnswers) as parked:
        asyncio.run(broker.ask(questions))

    pending_ids = [question.id for question in parked.value.pending]
    assert pending_ids == ["q-2", "q-1"]
    assert any("q-1=maybe" in problem for problem in parked.value.problems)
    assert any("q-9" in problem for problem in parked.value.problems)


def test_headless_broker_never_assumes_recommendations() -> None:
    questions = question_batch(
        [material_question("q-1", ["yes", "no"], recommendation="yes")]
    )
    broker = HeadlessQuestionBroker({})

    with pytest.raises(ResolverAwaitingAnswers):
        asyncio.run(broker.ask(questions))


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

    intake = resolver_intake([open_note, parked])

    assert intake.actionable == [open_note]
    assert intake.carried == ["carrying deferred[until v2 lands] parked.py:2-2"]
