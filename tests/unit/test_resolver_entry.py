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
from lup.resolver.models import (
    AdmissionRequest,
    MaterialQuestion,
    QuestionAnswer,
    QuestionBatch,
    ResolveRequest,
    SourceSnapshot,
)
from lup.devtools.dev.comments import FoundComment
from lup.harness.ownership import (
    OWNERSHIP_FILENAME,
    GeneratedArtifacts,
    OwnedArtifact,
    OwnershipManifest,
)
from lup.devtools.harness.resolve import (
    AdmissionFlags,
    NoteTargetRef,
    admission_notes,
    admission_request,
    describe_intake,
    inert_offers,
    missing_run_refusal,
    offer_flag_answers,
    parse_answer_flags,
    parse_note_targets,
    resolver_intake,
    run_owned,
    scanned_intake,
    seed_request,
)
from tests.unit.repos import commit_file, initialized_repo


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
    assert [note.describe() for note in intake.carried] == [
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
    assert [note.describe() for note in intake.generated] == [
        "leaving to its generator: harness.kernel.edit owns "
        ".claude/plugins/lup/hooks/runtime/kernel/edit.py:2-2"
    ]


def test_note_targets_parse_a_path_and_a_line() -> None:
    assert parse_note_targets(["src/module.py:42"]) == [
        NoteTargetRef(file=Path("src/module.py"), line=42)
    ]
    with pytest.raises(typer.BadParameter):
        parse_note_targets(["src/module.py"])
    with pytest.raises(typer.BadParameter):
        parse_note_targets([":42"])


def admission_flags(statements: list[str]) -> AdmissionFlags:
    return AdmissionFlags(statements=statements, notes=[], issues=[])


def test_an_invocation_without_admission_evidence_asks_for_nothing() -> None:
    """Every other resolver invocation must stay an ordinary drive."""
    assert admission_request(admission_flags([])) is None


def test_admitted_statements_become_the_evidence_a_run_plans_from() -> None:
    request = admission_request(admission_flags(["the relay must investigate first"]))

    assert request is not None
    assert request.statements == ["the relay must investigate first"]
    assert request.notes == []
    assert request.issues == []


def test_a_detached_relaunch_carries_every_kind_of_evidence_it_was_given() -> None:
    """Forwarding only the answers left what a human named silently behind."""
    flags = AdmissionFlags(
        statements=["the relay must investigate"], notes=["src/m.py:7"], issues=[42]
    )

    assert flags.arguments() == [
        "--admit",
        "the relay must investigate",
        "--admit-note",
        "src/m.py:7",
        "--admit-issue",
        "42",
    ]


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


OPEN_NOTE = """\
alpha = 1
# lup: close the union
beta = 2
"""

PARKED_NOTE = """\
# lup: defer[until v2 lands]: widen the vocabulary
gamma = 3
"""

GENERATED_NOTE = """\
# lup: the generated copy carries this too
delta = 4
"""

GENERATED_PATH = ".claude/plugins/lup/hooks/runtime/kernel/edit.py"


@pytest.fixture
def intake_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tracked tree holding one note of each kind the resolver partitions."""
    work = tmp_path / "repo"
    git = initialized_repo(work, tmp_path / "no-hooks")
    (work / GENERATED_PATH).parent.mkdir(parents=True)
    (work / ".claude" / OWNERSHIP_FILENAME).write_text(
        OwnershipManifest(
            schema_version=1,
            generator_version="0.0.0",
            source_digest="0" * 64,
            target_requirements=[],
            files=[
                OwnedArtifact(
                    path=Path(GENERATED_PATH),
                    category="generated",
                    sha256="0" * 64,
                    semantic_id="hooks.lup-policy",
                )
            ],
        ).model_dump_json(),
        encoding="utf-8",
    )
    commit_file(git, work, "mine.py", OPEN_NOTE, "chore: open note")
    commit_file(git, work, "parked.py", PARKED_NOTE, "chore: parked note")
    commit_file(git, work, GENERATED_PATH, GENERATED_NOTE, "chore: generated note")
    monkeypatch.chdir(work)
    return work


def test_the_preview_names_every_bucket_at_its_own_file_and_line(
    intake_tree: Path,
) -> None:
    """Reconstructing this by hand took a dozen calls and ended in a guess."""
    assert describe_intake(scanned_intake(intake_tree)) == [
        "1 to plan, 1 carried, 1 left to a generator",
        "planning from mine.py:2-2",
        "carrying deferred[until v2 lands] parked.py:1-1",
        f"leaving to its generator: hooks.lup-policy owns {GENERATED_PATH}:1-1",
    ]


def test_the_preview_starts_no_run_and_leases_nothing(
    intake_tree: Path, tmp_path: Path
) -> None:
    """Seeing an inventory used to mean committing to a worktree per concern."""
    beside = sorted(path.name for path in tmp_path.iterdir())

    describe_intake(scanned_intake(intake_tree))

    assert not (intake_tree / ".lup").exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == beside


def seeded(
    comments: list[FoundComment], admission: AdmissionRequest | None
) -> ResolveRequest:
    return seed_request(
        SourceSnapshot(branch="feature", commit="source-sha"), comments, [], admission
    )


def test_the_preview_lists_exactly_what_a_run_would_plan_from(
    intake_tree: Path,
) -> None:
    """One partitioning read twice: a preview cannot show what a run leaves out."""
    intake = scanned_intake(intake_tree)

    planned = seeded(intake.actionable, None)

    assert [(str(note.file), note.line) for note in planned.notes] == [
        (note.file, note.start_line) for note in intake.actionable
    ]
    assert [
        line for line in describe_intake(intake) if line.startswith("planning from")
    ] == ["planning from mine.py:2-2"]


def test_statements_offered_to_no_named_run_seed_one_rather_than_refusing() -> None:
    """An id nobody named was never a claim that the run exists."""
    assert missing_run_refusal(None, "resolve-abc123def456") is None


def test_admitting_into_a_run_named_explicitly_still_refuses_when_it_is_missing() -> (
    None
):
    """A typo would otherwise start a second run and lease a worktree each."""
    refusal = missing_run_refusal("resolve-typo", "resolve-typo")

    assert refusal is not None
    assert "resolve-typo" in refusal
    # The refusal says statements are usable without a run, rather than
    # leaving a reader to infer that one must pre-exist for them to count.
    assert "Statements seed a run of their own" in refusal
    assert "drop --run-id" in refusal


def test_a_run_is_seeded_from_words_with_no_note_written_into_the_tree() -> None:
    """How a human arrives: the concerns in their own words, nothing on disk."""
    request = seeded([], AdmissionRequest(statements=["the relay must investigate"]))

    assert request.statements == ["the relay must investigate"]
    assert request.notes == []
    assert request.evidence_count() == 1


def test_a_seeded_run_mixes_what_was_said_with_what_the_tree_carries() -> None:
    """Both kinds are positions in one request, so one turn plans them together."""
    request = seeded(
        [intake_note()], AdmissionRequest(statements=["the relay must investigate"])
    )

    assert [(note.file, note.line) for note in request.notes] == [
        (Path("parked.py"), 2)
    ]
    assert request.statements == ["the relay must investigate"]


def test_a_note_named_explicitly_reaches_a_fresh_run_once() -> None:
    """The scan carries it too, so naming one folds it in rather than doubling it."""
    scanned = intake_note()
    named = admission_notes([NoteTargetRef(file=Path("parked.py"), line=2)], [scanned])

    request = seeded([scanned], AdmissionRequest(notes=named))

    assert [(note.file, note.line) for note in request.notes] == [
        (Path("parked.py"), 2)
    ]


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
