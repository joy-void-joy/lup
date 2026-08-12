"""Behavioral contract of the resolver entry: headless answers and note intake."""

from pathlib import Path

import pytest
import typer

from lup.codescan.markers import NoteKind
from lup.channels.models import utc_now
from lup.resolver.mailbox import (
    AnswerDoor,
    AnswerOffer,
    MailboxConflictError,
    QuestionMailbox,
    RecordedAnswer,
)
from lup.resolver.models import MaterialQuestion, QuestionAnswer, QuestionBatch
from lup.devtools.dev.comments import FoundComment
from lup.harness.ownership import GeneratedArtifacts, OwnedArtifact
from lup.devtools.harness.resolve import (
    NoteTargetRef,
    admission_notes,
    admission_request,
    inert_offers,
    offer_flag_answers,
    parse_answer_flags,
    parse_note_targets,
    resolver_intake,
    run_owned,
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


def settle(mailbox: QuestionMailbox, identifier: str, value: str) -> None:
    """Promote one answer, which is the point after which it stops moving."""
    mailbox.record(
        RecordedAnswer(
            run_id="run-7",
            answer=QuestionAnswer(question_id=identifier, value=value),
            door=AnswerDoor.FLAG,
            answered_at=utc_now(),
        )
    )


def test_re_offering_the_settled_value_is_the_no_op_a_rerun_needs(
    tmp_path: Path,
) -> None:
    """The documented rerun recipe re-passes answers a promoter already took."""
    mailbox = QuestionMailbox(tmp_path)
    settle(mailbox, "q-1", "approve")

    offer_flag_answers(mailbox, "run-7", {"q-1": "approve"})

    assert mailbox.offers() == []


def test_correcting_a_settled_answer_is_refused_rather_than_recorded(
    tmp_path: Path,
) -> None:
    """Silence here leased a concern whose design the human had rejected."""
    mailbox = QuestionMailbox(tmp_path)
    settle(mailbox, "q-1", "approve")

    with pytest.raises(typer.BadParameter) as refusal:
        offer_flag_answers(mailbox, "run-7", {"q-1": "defer"})

    assert "'approve'" in str(refusal.value)
    assert "'defer'" in str(refusal.value)
    assert mailbox.offers() == []


def test_every_stale_correction_is_named_by_one_rerun(tmp_path: Path) -> None:
    """Finding the next one only after dropping the last costs a rerun each."""
    mailbox = QuestionMailbox(tmp_path)
    settle(mailbox, "q-1", "approve")
    settle(mailbox, "q-2", "approve")

    with pytest.raises(typer.BadParameter) as refusal:
        offer_flag_answers(mailbox, "run-7", {"q-1": "defer", "q-2": "defer"})

    assert "q-1" in str(refusal.value)
    assert "q-2" in str(refusal.value)


def test_a_still_open_question_keeps_taking_corrections(tmp_path: Path) -> None:
    """Offers stay correctable right up until a promoter takes one."""
    mailbox = QuestionMailbox(tmp_path)

    offer_flag_answers(mailbox, "run-7", {"q-1": "typo"})
    offer_flag_answers(mailbox, "run-7", {"q-1": "meant this"})

    assert [(item.question_id, item.value) for item in mailbox.offers()] == [
        ("q-1", "meant this")
    ]


def test_an_offer_a_promotion_outran_is_named_at_resume(tmp_path: Path) -> None:
    """Nothing under `.lup/resolve` is unlinked, so one says what it found."""
    mailbox = QuestionMailbox(tmp_path)
    mailbox.offer(
        AnswerOffer(
            run_id="run-7",
            question_id="q-1",
            value="defer",
            door=AnswerDoor.FLAG,
            offered_at=utc_now(),
        )
    )
    settle(mailbox, "q-1", "approve")

    reported = inert_offers(mailbox)

    assert len(reported) == 1
    assert "q-1" in reported[0]
    assert "'approve'" in reported[0]


def test_an_offer_awaiting_promotion_is_not_reported_as_stale(tmp_path: Path) -> None:
    mailbox = QuestionMailbox(tmp_path)
    offer_flag_answers(mailbox, "run-7", {"q-1": "defer"})

    assert inert_offers(mailbox) == []


def test_the_page_and_console_doors_are_refused_the_same_way(tmp_path: Path) -> None:
    """One rule at the point every door writes through, not three."""
    mailbox = QuestionMailbox(tmp_path)
    settle(mailbox, "q-1", "approve")

    for door in (AnswerDoor.PAGE, AnswerDoor.CONSOLE, AnswerDoor.AGENT):
        with pytest.raises(MailboxConflictError):
            mailbox.offer(
                AnswerOffer(
                    run_id="run-7",
                    question_id="q-1",
                    value="defer",
                    door=door,
                    offered_at=utc_now(),
                )
            )


def intake_note(
    kind: NoteKind = "note",
    condition: str | None = None,
    file: str = "parked.py",
) -> FoundComment:
    return FoundComment(
        file=file,
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

    intake = resolver_intake([open_note, parked, bare], GeneratedArtifacts(by_path={}))

    assert intake.actionable == [open_note]
    assert intake.generated == []
    assert intake.carried == [
        "carrying deferred[until v2 lands] parked.py:2-2",
        "carrying deferred parked.py:2-2",
    ]


def test_resolver_intake_leaves_a_note_in_a_generated_artifact_to_its_generator() -> (
    None
):
    own = intake_note(file="src/mine.py")
    theirs = intake_note(file=".claude/plugins/lup/hooks/runtime/kernel/edit.py")
    owned = GeneratedArtifacts(
        by_path={
            theirs.file: OwnedArtifact(
                path=Path(theirs.file),
                category="generated",
                sha256="0" * 64,
                semantic_id="harness.kernel.edit",
            )
        }
    )

    intake = resolver_intake([own, theirs], owned)

    assert intake.actionable == [own]
    assert intake.generated == [
        "harness.kernel.edit owns .claude/plugins/lup/hooks/runtime/kernel/edit.py:2-2"
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
    assert admission_request([], [], []) is None


def test_admitted_statements_become_the_evidence_a_run_plans_from() -> None:
    request = admission_request(["the relay must investigate first"], [], [])

    assert request is not None
    assert request.statements == ["the relay must investigate first"]
    assert request.notes == []
    assert request.issues == []


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
                [intake_note(kind="defer", condition="until v2 lands")],
                GeneratedArtifacts(by_path={}),
            ).actionable,
        )


def test_a_run_trusts_the_repository_it_was_invoked_against(tmp_path: Path) -> None:
    """The planner reads here, and an untrusted read drops the repo's grants."""
    root = tmp_path / "repo"
    root.mkdir()

    assert run_owned(root, root, tmp_path / "repo-resolve-a-run")


def test_a_run_trusts_the_checkouts_it_made(tmp_path: Path) -> None:
    worktree_root = tmp_path / "repo-resolve-a-run"

    assert run_owned(worktree_root / "a-concern", tmp_path / "repo", worktree_root)


def test_a_run_trusts_nothing_it_merely_opens_a_session_in(tmp_path: Path) -> None:
    """Trust follows the invocation, not wherever a session happens to land."""
    elsewhere = tmp_path / "somebody-elses-checkout"

    assert not run_owned(elsewhere, tmp_path / "repo", tmp_path / "repo-resolve-a-run")
