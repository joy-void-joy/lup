"""Versioned edit evaluator transport; carries every semantic decision field."""

from typing import TypedDict, TypeGuard

from .decision import (
    KernelDecision,
    DecisionEffect,
    SandboxPlacement,
    CheckpointRequirement,
)
from .semantics import (
    ReviewerRequirement,
    ReviewPurpose,
    Visibility,
    RefusalCause,
    Capability,
    AbstentionPurpose,
)


type WireValue = (
    str | int | float | bool | None | list[WireValue] | dict[str, WireValue]
)


class DecisionWire(TypedDict):
    """A complete decision, including all contributing findings."""

    effect: DecisionEffect
    reason: str
    sandbox: SandboxPlacement
    escalated: str
    checkpoint: CheckpointRequirement
    unlisted: bool
    reviewer: ReviewerRequirement
    purpose: ReviewPurpose | None
    visibility: Visibility
    cause: RefusalCause | None
    capability: Capability | None
    abstention: AbstentionPurpose | None
    hard: bool
    findings: list["DecisionWire"]
    rule: str
    evaluator: str
    recovery: str


class EditRequest(TypedDict):
    """Normalized edit facts; caller and owner are deliberately independent."""

    protocol: int
    path: str
    before: str | None
    after: str | None
    path_exists: bool
    autonomous: bool
    agent_identity: str
    operation: str
    cwd: str
    owner: str


def decision_wire(decision: KernelDecision) -> DecisionWire:
    """Erase a decision without dropping its reviewer, placement or findings."""
    return DecisionWire(
        effect=decision.effect,
        reason=decision.reason,
        sandbox=decision.sandbox,
        escalated=decision.escalated,
        checkpoint=decision.checkpoint,
        unlisted=decision.unlisted,
        reviewer=decision.reviewer,
        purpose=decision.purpose,
        visibility=decision.visibility,
        cause=decision.cause,
        capability=decision.capability,
        abstention=decision.abstention,
        hard=decision.hard,
        findings=[decision_wire(part) for part in decision.findings],
        rule=decision.rule,
        evaluator=decision.evaluator,
        recovery=decision.recovery,
    )


def valid_decision(value: WireValue | DecisionWire) -> TypeGuard[DecisionWire]:
    """Reject incomplete or malformed evaluator responses before using them."""
    if not isinstance(value, dict) or sorted(value) != sorted(
        DecisionWire.__annotations__
    ):
        raise ValueError("destination evaluator returned an incompatible decision")
    for name in ("reason", "escalated", "rule", "evaluator", "recovery"):
        if not isinstance(value[name], str):
            raise ValueError(f"destination decision {name} must be text")
    for name in ("unlisted", "hard"):
        if not isinstance(value[name], bool):
            raise ValueError(f"destination decision {name} must be boolean")
    for name, choices in (
        ("effect", ("allow", "ask", "deny", "defer")),
        ("sandbox", ("inside", "ambient", "outside")),
        ("checkpoint", ("targeted", "boundary_wide", "unrecoverable")),
        ("reviewer", ("human_only", "supervisor_allowed")),
        (
            "purpose",
            (
                None,
                "quality_review",
                "sensitive_access",
                "external_consequence",
                "policy_override",
                "unrecovered_local_mutation",
                "untrusted_dependency",
            ),
        ),
        ("visibility", ("quiet", "notice")),
        (
            "cause",
            (
                None,
                "deliberate",
                "reviewability",
                "unreadable",
                "unlisted",
                "capability",
            ),
        ),
        (
            "capability",
            (
                None,
                "host_executor",
                "checkpoint_store",
                "question_relay",
                "inside_placement",
            ),
        ),
        ("abstention", (None, "provider_native", "boundary_settle")),
    ):
        if value[name] not in choices:
            raise ValueError(f"destination decision has invalid {name}")
    if not isinstance(value["findings"], list):
        raise ValueError("destination decision findings must be a list")
    return all(valid_decision(part) for part in value["findings"])


def read_decision(value: WireValue | DecisionWire) -> KernelDecision:
    """Restore a validated complete decision."""
    if not valid_decision(value):
        raise ValueError("malformed destination decision")
    row = value
    findings = tuple(read_decision(part) for part in row["findings"])
    return KernelDecision(
        effect=row["effect"],
        reason=row["reason"],
        sandbox=row["sandbox"],
        escalated=row["escalated"],
        checkpoint=row["checkpoint"],
        unlisted=row["unlisted"],
        reviewer=row["reviewer"],
        purpose=row["purpose"],
        visibility=row["visibility"],
        cause=row["cause"],
        capability=row["capability"],
        abstention=row["abstention"],
        hard=row["hard"],
        findings=findings,
        rule=row["rule"],
        evaluator=row["evaluator"],
        recovery=row["recovery"],
    )


def routing_failure(reason: str, refresh: str = "") -> KernelDecision:
    """An unavailable owner is a refusal, never an origin-policy fallback.

    ``refresh`` is the operator's command where accepting the owner's
    regenerated policy is what settles the refusal, spelled whole so the
    agent can hand it over: the operator runs it outside the session, where
    neither the launch's nonce nor its checkout can be looked up.
    """
    return KernelDecision(
        "deny",
        f"Destination policy unavailable: {reason}",
        hard=True,
        rule="edit:destination-policy",
        recovery=(
            "Regenerate the destination harness if it is behind its source, then "
            "ask the operator to accept its policy from a terminal outside this "
            f"session: `{refresh}`"
            if refresh
            else "Regenerate the destination harness and ask the operator to refresh its accepted policy snapshot."
        ),
    )


def unaccepted_policy(
    decision: KernelDecision, refresh: str, own: list[KernelDecision] | None = None
) -> KernelDecision:
    """A verdict the launch's policy reached about a checkout generating another.

    A worktree no grant names is judged by the policy the session launched
    with, whatever it generates for itself: accepting another policy is an
    operator's act, never the session's. A refusal reached that way reads
    exactly like one the checkout's own policy reached -- a composition root
    renamed there is a foreign import here -- so it says whose policy judged,
    and hands over the command that would change that. Only a question or a
    refusal says so; an allowance has nothing to recover from.

    ``own`` is what each policy that checkout generates would decide here.
    Where every one reaches this same verdict -- a human-owned file both ask
    about -- the command would change nothing a reader meets, so none is
    handed over. Where there is no such answer the command stands.
    """
    if not refresh or decision.effect not in ("ask", "deny"):
        return decision
    if own and all(
        (verdict.effect, verdict.reason) == (decision.effect, decision.reason)
        for verdict in own
    ):
        return decision
    return decision.advising(
        "This edit was judged by the policy this session launched with, not by "
        "the one the checkout holding it generates, which differs. For that "
        "checkout's own policy to judge its edits, ask the operator to run, "
        f"from a terminal outside this session: `{refresh}`"
    )


def read_response(value: WireValue) -> KernelDecision:
    """Read the versioned semantic reply from an accepted evaluator."""
    if not isinstance(value, dict) or sorted(value) != ["decision", "protocol"]:
        raise ValueError("malformed destination evaluator response")
    if type(value["protocol"]) is not int or value["protocol"] != 1:
        raise ValueError("unsupported destination evaluator response")
    return read_decision(value["decision"])


def valid_edit_request(value: WireValue) -> TypeGuard[EditRequest]:
    """Validate the complete protocol before any destination code judges it."""
    if not isinstance(value, dict) or sorted(value) != sorted(
        EditRequest.__annotations__
    ):
        raise ValueError("incompatible destination edit request")
    if type(value["protocol"]) is not int or value["protocol"] != 1:
        raise ValueError("unsupported destination evaluator protocol")
    for name in ("path", "operation", "cwd", "owner", "agent_identity"):
        if not isinstance(value[name], str):
            raise ValueError(f"destination edit {name} must be text")
    for name in ("before", "after"):
        if value[name] is not None and not isinstance(value[name], str):
            raise ValueError(f"destination edit {name} must be text or null")
    for name in ("path_exists", "autonomous"):
        if not isinstance(value[name], bool):
            raise ValueError(f"destination edit {name} must be boolean")
    if value["operation"] not in ("modify", "overwrite", "create", "delete"):
        raise ValueError("unsupported destination edit operation")
    return True


def read_edit_request(value: WireValue) -> EditRequest:
    """Restore normalized edit facts after validating their complete shape."""
    if not valid_edit_request(value):
        raise ValueError("malformed destination edit request")
    return value
