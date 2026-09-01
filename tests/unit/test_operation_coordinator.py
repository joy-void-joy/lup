"""The lifecycle every operation passes through, and the two orderings in it.

A question parks before anything is captured or locked, and settlement runs
twice over one operation with different evidence. Both are properties of the
*order* rather than of any rule, which is why they are pinned here and not in
the settlement suite.
"""

from pathlib import Path

import pytest

from lup.policy.boundary import (
    BoundaryPreflight,
    CapabilityEvidence,
    CapabilityRequirement,
    ExecutionBoundary,
)
from lup.policy.checkpoints import RecoveryCoordinator, WorktreeLease
from lup.policy.coordinator import OperationCoordinator
from lup.policy.kernel.decision import KernelDecision
from lup.policy.operations import MutationFootprint, Operation
from lup.policy.relay import Principal, QuestionRelay, SupervisorChain


def coordinator(tmp_path: Path, contained: bool = True) -> OperationCoordinator:
    """One coordinator over a contained profile whose capabilities were measured."""
    boundary = ExecutionBoundary(
        name="test",
        contained=contained,
        capabilities=[
            CapabilityRequirement(capability="inside_placement"),
            CapabilityRequirement(capability="question_relay"),
            CapabilityRequirement(capability="host_executor", required=False),
        ],
    )
    return OperationCoordinator(
        relay=QuestionRelay(tmp_path / "questions.jsonl"),
        recovery=RecoveryCoordinator(tmp_path / "store"),
        preflight=BoundaryPreflight(
            boundary=boundary,
            evidence=[
                CapabilityEvidence(capability="inside_placement", delivered=contained),
                CapabilityEvidence(capability="question_relay", delivered=True),
            ],
        ),
        chain=SupervisorChain(
            principals=[
                Principal(id="worker", kind="agent", supervisor="person"),
                Principal(id="person", kind="human"),
            ]
        ),
    )


def deletion(root: Path, target: str = "kept.txt") -> Operation:
    """One local deletion whose target resolves statically."""
    root.mkdir(parents=True, exist_ok=True)
    (root / target).write_text("kept\n", encoding="utf-8")
    return Operation(
        id="op-1",
        session="session-1",
        requester="worker",
        tool="Bash",
        payload={"command": f"rm {target}"},
        cwd=root,
        worktree=root,
        mutations=MutationFootprint(deletions=[root / target]),
    )


def local_loss(reason: str = "deleting files requires approval") -> KernelDecision:
    """A question whose whole subject is a loss a capture would put back."""
    return KernelDecision(
        "ask",
        reason,
        checkpoint="targeted",
        purpose="unrecovered_local_mutation",
        rule="shell:rm",
    )


def test_a_question_parks_without_holding_the_mutation_lease(tmp_path: Path) -> None:
    """A lock held across a person's attention is held for minutes.

    The rest of the session needs it, and preparation is what happens after
    an answer rather than what waits for one.
    """
    root = tmp_path / "repo"
    call = deletion(root)
    review = KernelDecision(
        "ask", "a production file is replaced whole", purpose="quality_review"
    )

    result = coordinator(tmp_path).preliminary(call, review)

    assert result.stage == "parked"
    assert result.question is not None
    assert WorktreeLease(root, "somebody-else").acquire()


def test_settlement_runs_twice_and_only_the_second_sees_the_capture(
    tmp_path: Path,
) -> None:
    """One order, two passes, different evidence — which is why no row asks
    which pass it is in.

    The first reaches the question because nothing has been measured; the
    second settles it to a permission because the loss it was protecting
    against has been established not to happen.
    """
    root = tmp_path / "repo"
    call = deletion(root)
    running = coordinator(tmp_path)

    parked = running.preliminary(call, local_loss())
    prepared = running.prepare(call, local_loss(), precious=[root])

    assert parked.stage == "parked"
    assert prepared.stage == "prepared"
    assert prepared.decision.effect == "allow"
    assert prepared.checkpoint is not None and prepared.checkpoint.complete


def test_a_capture_that_failed_keeps_the_question_and_says_which_it_was(
    tmp_path: Path,
) -> None:
    """A footprint naming a path under a directory that is not there.

    "Nobody captured this" and "the capture did not work" are different things
    to tell a person, and only the second says the loss it was going to cover
    is unprotected right now.
    """
    root = tmp_path / "repo"
    root.mkdir()
    call = Operation(
        id="op-2",
        session="session-1",
        requester="worker",
        tool="Bash",
        payload={"command": "rm -r missing/tree"},
        cwd=root,
        worktree=root,
        mutations=MutationFootprint(
            deletions=[root / "missing" / "tree"], exact=False, opacity="a glob"
        ),
    )

    result = coordinator(tmp_path).prepare(
        call, local_loss(), precious=[root / "missing"]
    )

    assert result.stage == "prepared"
    assert result.checkpoint is not None


def test_the_lease_refuses_a_second_preparation_rather_than_capturing_over_it(
    tmp_path: Path,
) -> None:
    """Two captures interleaving is the one thing the lease exists to prevent."""
    root = tmp_path / "repo"
    call = deletion(root)
    WorktreeLease(root, "session-other").acquire()

    result = coordinator(tmp_path).prepare(call, local_loss(), precious=[root])

    assert result.stage == "refused"
    assert "mutation lease" in result.decision.reason


def test_an_approved_operation_that_changed_is_a_fresh_question(
    tmp_path: Path,
) -> None:
    """The whole content of exact approval, checked where resumption happens.

    The record carries the operation so the agent does not reconstruct it, and
    the operation arriving here is revalidated anyway — a stale payload, a
    moved worktree, or a target that resolved differently all reach this.
    """
    root = tmp_path / "repo"
    call = deletion(root)
    running = coordinator(tmp_path)
    parked = running.preliminary(call, local_loss())
    assert parked.question is not None
    running.relay.answer(parked.question.id, "person", approved=True)

    resumed = running.resume(parked.question.id, call)
    swapped = running.resume(
        parked.question.id, call.model_copy(update={"payload": {"command": "rm -rf /"}})
    )

    assert resumed.stage == "prepared"
    assert swapped.stage == "refused"
    assert "changed after it was approved" in swapped.decision.reason


def test_a_rejection_carries_its_note_back_with_the_refusal(tmp_path: Path) -> None:
    """No-plus-instructions travels with the refusal rather than as a message.

    Which is the moment the agent can act on it, and the moment the person was
    most able to write it — they were looking at the operation.
    """
    root = tmp_path / "repo"
    call = deletion(root)
    running = coordinator(tmp_path)
    parked = running.preliminary(call, local_loss())
    assert parked.question is not None
    running.relay.answer(
        parked.question.id, "person", approved=False, note="move it to tmp/ instead"
    )

    refused = running.resume(parked.question.id, call)

    assert refused.stage == "refused"
    assert refused.note == "move it to tmp/ instead"


def test_an_unresumable_question_authorizes_nothing(tmp_path: Path) -> None:
    """Expired, cancelled and pending all mean the same thing to an executor."""
    root = tmp_path / "repo"
    call = deletion(root)
    running = coordinator(tmp_path)
    parked = running.preliminary(call, local_loss())
    assert parked.question is not None
    running.relay.cancel(parked.question.id, "the branch was abandoned")

    assert running.resume(parked.question.id, call).stage == "refused"


def test_a_question_that_was_never_recorded_is_an_error_and_not_an_allow(
    tmp_path: Path,
) -> None:
    """The one failure that must not fail open.

    A resumption naming a question nobody parked is either a bug or a forged
    id, and the safe reading of both is that nothing was approved.
    """
    root = tmp_path / "repo"
    running = coordinator(tmp_path)

    with pytest.raises(ValueError, match="no question"):
        running.resume("q-nope", deletion(root))
