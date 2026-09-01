"""The one route out of the boundary, and every way an approval must not travel.

What the executor has to be correct about is narrow and checkable: that what
it runs is what somebody authorized, and that it runs once. So the cases here
are the four verifications and the two orderings — the dispatch written before
the send, and the outcome written after — because those orderings are the
whole of at-most-once dispatch.
"""

from pathlib import Path

from lup.policy.hostexec import HostExecutor, HostRequest, human_execution_brief
from lup.policy.kernel.decision import SandboxPlacement
from lup.policy.operations import Operation


def crossing(
    session: str = "session-1", placement: SandboxPlacement = "outside"
) -> HostRequest:
    """One approved operation asking to run on the launcher's host."""
    call = Operation(
        id="op-1",
        session=session,
        requester="worker",
        tool="Bash",
        payload={"command": "sudo systemctl restart lupd"},
        cwd=Path("/repo"),
        worktree=Path("/repo"),
        placement=placement,
    )
    return HostRequest(
        operation=call,
        fingerprint=call.fingerprint(),
        session=session,
        question="q-1",
        approved_by="person",
    )


def test_a_request_from_a_session_this_launcher_did_not_start_is_refused(
    tmp_path: Path,
) -> None:
    """The channel is the launcher's, so its origin is the first thing checked."""
    executor = HostExecutor(tmp_path / "dispatch.jsonl", session="session-1")

    assert "did not start" in executor.verify(crossing(session="session-other"))


def test_an_operation_that_changed_after_approval_is_refused(tmp_path: Path) -> None:
    """The fingerprint is what an approval bound to, so drift invalidates it.

    Checked at the executor as well as at the relay, because this is the last
    point before the effect and the one place a substitution would actually
    land.
    """
    executor = HostExecutor(tmp_path / "dispatch.jsonl", session="session-1")
    request = crossing()
    swapped = request.model_copy(
        update={
            "operation": request.operation.model_copy(
                update={"payload": {"command": "sudo rm -rf /"}}
            )
        }
    )

    assert executor.verify(request) == ""
    assert "does not match the fingerprint" in executor.verify(swapped)


def test_an_operation_policy_did_not_place_outside_never_reaches_the_host(
    tmp_path: Path,
) -> None:
    """The executor is not a way to reach the host; it is a way to carry out
    a placement somebody already settled."""
    executor = HostExecutor(tmp_path / "dispatch.jsonl", session="session-1")

    assert "policy places this operation ambient" in executor.verify(
        crossing(placement="ambient")
    )


def test_an_approval_is_spent_once_at_the_executor_too(tmp_path: Path) -> None:
    """Replay defence, checked where the effect happens.

    The relay refuses a second answer; this refuses a second dispatch of the
    same answer, which is the different failure — one approval, sent twice.
    """
    executor = HostExecutor(tmp_path / "dispatch.jsonl", session="session-1")
    request = crossing()

    executor.record(request)

    assert "already dispatched" in executor.verify(request)


def test_a_profile_with_no_channel_refuses_rather_than_pretending(
    tmp_path: Path,
) -> None:
    """No approval creates a channel, so the absence is stated as itself."""
    executor = HostExecutor(
        tmp_path / "dispatch.jsonl", session="session-1", available=False
    )

    assert "declares no host executor" in executor.verify(crossing())


def test_a_crash_between_sending_and_reporting_leaves_the_dispatch_written(
    tmp_path: Path,
) -> None:
    """Which is exactly the state `in_doubt` names, and what stops a retry.

    Written before the send: a coordinator that crashes after sending finds
    this and does not send again. Written after, the same crash leaves no
    evidence and the next attempt repeats the effect.
    """
    executor = HostExecutor(tmp_path / "dispatch.jsonl", session="session-1")
    request = crossing()

    executor.record(request)

    assert [entry.operation for entry in executor.unsettled()] == ["op-1"]
    assert "already dispatched" in executor.verify(request)


def test_a_reported_outcome_settles_the_dispatch(tmp_path: Path) -> None:
    """The outcome is a second entry, so the pair survives a crash between them."""
    executor = HostExecutor(tmp_path / "dispatch.jsonl", session="session-1")
    sent = executor.record(crossing())

    settled = executor.complete(sent, "completed", exit_code=0, output="ok\n")

    assert settled.settled()
    assert executor.unsettled() == []


def test_the_person_executing_is_shown_the_operation_and_not_a_description(
    tmp_path: Path,
) -> None:
    """A person asked to run "the approved command" reconstructs one.

    A reconstruction is not the operation that was approved, which is the
    whole reason the exact text and the directory are rendered.
    """
    brief = human_execution_brief(crossing())

    assert "sudo systemctl restart lupd" in brief
    assert "/repo" in brief
    assert "nothing runs until you do" in brief
