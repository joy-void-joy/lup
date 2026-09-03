"""What a record has to answer, and the one thing it must never be.

Evidence, never replay authority: an approval lives in the relay and is spent
once there, so a record that could authorize anything would be a second
approval channel with no single-use guarantee behind it.

What it must answer is the question that had no answer before provenance
existed — for an interruption somebody remembers, which rule asked and what
it was asking about.
"""

from pathlib import Path

from lup.policy.audit import AuditLog, AuditRecord
from lup.policy.checkpoints import Checkpoint
from lup.policy.models import Decision
from lup.policy.operations import Operation
from lup.policy.relay import Answer, PersistentQuestion


def operation(command: str = "gh pr merge 12") -> Operation:
    return Operation(
        id="op-1",
        session="session-1",
        requester="worker",
        tool="Bash",
        payload={"command": command},
        cwd=Path("/repo"),
        worktree=Path("/repo"),
    )


def asked() -> AuditRecord:
    """One interruption, recorded as the components that owned it reported it."""
    call = operation()
    decision = Decision(
        effect="ask",
        reason="merging runs the change into the base branch",
        rule="shell:gh.pr.merge",
        evaluator="shell-vocabulary",
        purpose="external_consequence",
    )
    return AuditRecord(
        operation=call,
        fingerprint=call.fingerprint(),
        decision=decision,
        question=PersistentQuestion(
            id="q-1",
            operation=call,
            fingerprint=call.fingerprint(),
            reason=decision.reason,
            rule=decision.rule,
            requirement="human_only",
            eligible=["person"],
            state="approved",
            answer=Answer(approved=True, principal="person", note="squash it"),
        ),
        outcome="executed",
    )


def test_a_record_says_which_rule_asked_and_what_it_asked_about() -> None:
    """The question that had no answer before provenance existed.

    A native tool name says `Bash` for every interruption in a run, so
    "which gate produced these" could only be answered by reading the
    classifier by hand.
    """
    record = asked()

    assert record.attributable()
    assert record.interrupted()
    assert "shell:gh.pr.merge" in record.narrative()[0]


def test_a_record_says_who_could_have_answered_and_who_did(tmp_path: Path) -> None:
    """Eligibility and the receipt are different facts and both are read.

    Who *could* have answered is what makes a queue triageable; who *did* is
    what makes an approval accountable, and the receipt kind says whether the
    answer was recorded or inferred from a provider's silence.
    """
    narrative = "\n".join(asked().narrative())

    assert "human_only" in narrative
    assert "eligible person" in narrative
    assert "answered    yes by person (recorded)" in narrative


def test_a_record_keeps_the_reasons_the_join_reported_over() -> None:
    """ "This asked" and "this asked for four reasons" are different records.

    The join reports the strongest effect and says nothing about how many
    reasons reached it, which is exactly what a person tuning a policy needs
    — three of four reasons discharged by a capture is a different situation
    from one reason nothing touched.
    """
    call = operation("rm -rf build && gh pr merge 12")
    record = AuditRecord(
        operation=call,
        fingerprint=call.fingerprint(),
        decision=Decision(effect="ask", reason="two reasons", rule="shell:gh.pr.merge"),
        findings=[
            Decision(effect="ask", reason="deleting files", rule="shell:rm"),
            Decision(effect="ask", reason="merging", rule="shell:gh.pr.merge"),
        ],
        outcome="refused",
    )

    narrative = "\n".join(record.narrative())

    assert "shell:rm: ask" in narrative
    assert "shell:gh.pr.merge: ask" in narrative


def test_a_record_says_what_was_measured_rather_than_what_was_required() -> None:
    """A capture that failed is a fact a reader needs, not a gap to infer.

    "Nothing needed capturing" and "the capture did not work" reach the same
    place in a summary that only reports the requirement.
    """
    call = operation("rm -rf build")
    record = AuditRecord(
        operation=call,
        fingerprint=call.fingerprint(),
        decision=Decision(effect="ask", reason="deleting files", rule="shell:rm"),
        checkpoint=Checkpoint(
            operation="op-1",
            requirement="targeted",
            failure="the store was unwritable",
        ),
        outcome="refused",
    )

    assert "captured    failed" in "\n".join(record.narrative())
    assert "the store was unwritable" in "\n".join(record.narrative())


def test_the_taxonomy_counts_by_rule_and_not_by_phrasing(tmp_path: Path) -> None:
    """A taxonomy of prose is a taxonomy of phrasings.

    The same gate reworded twice becomes two rows, and two gates that happen
    to share a sentence become one — which is what made the measured corpus's
    deny taxonomy something somebody had to reconstruct by matching text.
    """
    log = AuditLog(tmp_path / "audit.jsonl")
    reworded = asked()
    log.record(reworded)
    log.record(
        reworded.model_copy(
            update={
                "decision": reworded.decision.model_copy(
                    update={"reason": "the same gate, said differently"}
                )
            }
        )
    )

    assert log.taxonomy() == {"shell:gh.pr.merge": 2}


def test_an_operation_nobody_was_asked_about_is_not_an_interruption(
    tmp_path: Path,
) -> None:
    """Counting permitted operations as interruptions makes the number useless."""
    call = operation("git status")
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record(
        AuditRecord(
            operation=call,
            fingerprint=call.fingerprint(),
            decision=Decision(effect="allow", reason="fine", rule="shell:git.status"),
            outcome="executed",
        )
    )

    assert log.taxonomy() == {}


def test_a_torn_final_record_does_not_lose_the_ones_before_it(
    tmp_path: Path,
) -> None:
    """A crash mid-write is the expected shape of a crash."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record(asked())
    with log.path.open("a", encoding="utf-8") as handle:
        handle.write('{"operation": {"id": "op-2"')

    assert [entry.operation.id for entry in log.records()] == ["op-1"]
