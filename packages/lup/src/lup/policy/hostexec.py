"""The one route from inside the containment boundary to the launcher's host.

Owned by the launcher and unreachable by the agent. That is the whole of its
security value and it is an operational boundary rather than an adversarial
one: the threat model here is a trusted-but-fallible agent, not one exploiting
the transport. What the executor must be correct about is narrower and
checkable — that what it runs is what somebody authorized, once.

Four verifications, and each closes a way an approval could otherwise be
reused or forged:

- the request came from a session this launcher started;
- the operation is exactly the one settled, by fingerprint;
- the approval is eligible, unexpired, and unspent;
- and nothing was dispatched for it before.

Where no automated channel exists, the fallback executor is a person: an
approved crossing is rendered for the launcher's owner to run in their own
terminal and confirm, and the relay records a human-executed dispatch with
whatever completion evidence came back. The crossing stays explicit, reviewed,
and single-use either way.

``allow outside`` admits no such fallback. Unprompted host execution exists
only through the automated channel, because handing an unreviewed operation to
a person to run is a review nobody asked for — so its absence is a
capability-blocked refusal rather than a question.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from lup.policy.operations import Operation

type DispatchOutcome = Literal["completed", "failed", "in_doubt"]
"""How a dispatch ended, including not knowing.

``in_doubt`` is the outcome of a crash between sending an operation and
recording its result. It is never retried: a retry is a second external
effect, and this promises at-most-once *dispatch* rather than exactly-once
effect. Nothing about an arbitrary shell command supports the stronger claim.
"""


class HostRequest(BaseModel, frozen=True):
    """One operation asking to cross, with everything the executor verifies.

    Carried whole rather than by reference, because the executor must not have
    to trust a lookup the requester could influence — and because a request
    that names an id the executor resolves is a request whose subject can
    change between naming and resolving.
    """

    operation: Operation
    fingerprint: str
    session: str
    question: str = ""
    approved_by: str = ""
    correlation: str = ""
    environment_inheritance: list[str] = []
    """Which launcher-environment names this operation inherits.

    Named rather than inherited wholesale: the launcher's environment holds
    the credentials the containment boundary exists to keep away from an
    agent, and an operation that crossed the boundary carrying all of them
    would have crossed with more than was authorized.
    """


class HostDispatch(BaseModel, frozen=True):
    """The record that a request was sent, written before it is sent.

    Before, and that ordering is the whole of at-most-once dispatch: a
    coordinator that crashes after sending finds this written down, and one
    that finds it does not send again. Written after, a crash in the window
    leaves no evidence and the next attempt repeats the effect.
    """

    operation: str
    fingerprint: str
    question: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    executor: Literal["channel", "human"] = "channel"
    outcome: DispatchOutcome | None = None
    exit_code: int | None = None
    output: str = ""

    def settled(self) -> bool:
        """Whether this dispatch has an outcome anybody may act on."""
        return self.outcome in ("completed", "failed")


class HostExecutor:
    """Verifies an approved crossing and records that it was dispatched once.

    The transport is deliberately not chosen here — a Unix socket, an
    inherited descriptor, a launcher RPC all satisfy the same contract — so
    what lives in this class is the part every transport needs to get right,
    and a transport that reimplemented it would be a second place to get it
    wrong.
    """

    log: Path
    session: str
    available: bool

    def __init__(self, log: Path, session: str, available: bool = True) -> None:
        self.log = log
        self.session = session
        self.available = available

    def dispatches(self) -> list[HostDispatch]:
        """Every dispatch recorded, in the order they were written."""
        if not self.log.exists():
            return []
        return [
            HostDispatch.model_validate_json(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def dispatched(self, fingerprint: str) -> HostDispatch | None:
        """The dispatch already recorded for this exact operation, if any."""
        return next(
            (entry for entry in self.dispatches() if entry.fingerprint == fingerprint),
            None,
        )

    def verify(self, request: HostRequest) -> str:
        """Why this request may not cross, or ``""`` where it may.

        A refusal string rather than an exception, because every one of these
        is a thing the caller reports rather than a thing it handles — and an
        exception per refusal makes the ordinary "no" the path that needs
        catching.
        """
        if not self.available:
            return "this profile declares no host executor"
        if request.session != self.session:
            return (
                f"the request names session {request.session!r},"
                f" which this launcher did not start"
            )
        if request.fingerprint != request.operation.fingerprint():
            return (
                "the operation does not match the fingerprint it was approved"
                " under — its arguments, directory, targets, or placement changed"
            )
        if request.operation.placement != "outside":
            return (
                f"policy places this operation {request.operation.placement},"
                " so nothing authorized it to run on the host"
            )
        prior = self.dispatched(request.fingerprint)
        if prior is not None:
            return (
                f"this operation was already dispatched at"
                f" {prior.at.isoformat()} — an approval is spent once"
            )
        return ""

    def record(
        self, request: HostRequest, executor: Literal["channel", "human"] = "channel"
    ) -> HostDispatch:
        """Write the dispatch down, before anything is sent.

        Returns the record so a caller cannot send without having written one:
        the value it needs to report the outcome is the value this produced.
        """
        entry = HostDispatch(
            operation=request.operation.id,
            fingerprint=request.fingerprint,
            question=request.question,
            executor=executor,
        )
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with self.log.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json() + "\n")
        return entry

    def complete(
        self,
        dispatch: HostDispatch,
        outcome: DispatchOutcome,
        exit_code: int | None = None,
        output: str = "",
    ) -> HostDispatch:
        """Record how a dispatch ended, including that nobody knows.

        Appended rather than rewritten, so the dispatch record and its outcome
        are two entries and a crash between them leaves the first — which is
        exactly the state ``in_doubt`` names, and exactly what stops a retry.
        """
        settled = dispatch.model_copy(
            update={"outcome": outcome, "exit_code": exit_code, "output": output}
        )
        with self.log.open("a", encoding="utf-8") as handle:
            handle.write(settled.model_dump_json() + "\n")
        return settled

    def unsettled(self) -> list[HostDispatch]:
        """Dispatches that were sent and never reported an outcome.

        What a coordinator finds after a crash. Each is ``in_doubt`` rather
        than pending: the operation may have run, and the one thing that must
        not happen is a second attempt that assumes it did not.
        """
        outcomes = {
            entry.fingerprint
            for entry in self.dispatches()
            if entry.outcome is not None
        }
        return [
            entry
            for entry in self.dispatches()
            if entry.outcome is None and entry.fingerprint not in outcomes
        ]


def human_execution_brief(request: HostRequest) -> str:
    """What a person is shown when they are the executor.

    The exact operation and where to run it, because a person asked to run
    "the approved command" will reconstruct one — and a reconstruction is not
    the operation that was approved. The confirmation they give afterwards is
    what the relay records as the dispatch.
    """
    payload = request.operation.payload
    command = payload["command"] if "command" in payload else request.operation.tool
    return "\n".join(
        [
            "This operation was approved to run on the launcher's host, and this",
            "profile has no automated channel to carry it. Run it yourself and",
            "confirm, or reject it — nothing runs until you do.",
            "",
            f"  directory: {request.operation.cwd.as_posix()}",
            f"  operation: {command}",
            "",
            f"  approved by: {request.approved_by or 'unrecorded'}",
            f"  fingerprint: {request.fingerprint}",
        ]
    )
