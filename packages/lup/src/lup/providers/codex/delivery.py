"""What the Codex adapter is built to deliver, and how each belief is known.

The counterpart to the Claude record, kept at this boundary for the same
reason: the mechanisms are named in this runtime's own words, and those words
belong here.

Two of these rows say a mechanism is absent, which is the point of recording
them. A guarantee omitted reads as delivered; a guarantee stated as absent
with its fallback is a design somebody made — and for the placement row it is
the design a launch preflight enforces, by refusing to start a profile that
requires containment this runtime cannot hold.
"""

from lup.policy.delivery import DeliveryFact


# lup: ignore[constant-declaration] — the same observation, for the other
# runtime and on the same grounds
CODEX_DELIVERY: list[DeliveryFact] = [
    DeliveryFact(
        guarantee="ask_survives_auto_mode",
        provider="codex",
        mechanism=(
            "the PermissionRequest hook answers before the native approval flow,"
            " and an unanswered request reaches the operator rather than a mode"
        ),
        standing="documented",
        fallback=(
            "a run with no operator reaches no reviewer, which the settlement"
            " order refuses rather than carrying — containment is not review"
        ),
    ),
    DeliveryFact(
        guarantee="exact_call_resumes",
        provider="codex",
        mechanism=(
            "an approval is correlated by tool_use_id and consumed once, so a"
            " later PreToolUse for a different call finds no approval"
        ),
        standing="measured",
        fallback=(
            "correlation drift is a refusal rather than a reuse, which the"
            " generated hook's own suite exercises"
        ),
    ),
    DeliveryFact(
        guarantee="defer_is_transparent",
        provider="codex",
        mechanism="the hook exits zero with no output, leaving the native flow",
        standing="measured",
        fallback="none needed: emitting nothing is the absence of a mechanism",
    ),
    DeliveryFact(
        guarantee="inside_placement_enforced",
        provider="codex",
        mechanism="",
        standing="absent",
        fallback=(
            "this runtime's verdicts place no call, so a placement renders as"
            " the plain effect and containment is the session's own posture —"
            " which is why a profile requiring inside_placement here fails its"
            " launch preflight rather than running unconfined"
        ),
    ),
    DeliveryFact(
        guarantee="outside_placement_carried",
        provider="codex",
        mechanism=(
            "the model requests placement on its own call and a compiled prefix"
            " rule approves exactly the boundary's declared exclusions"
        ),
        standing="measured",
        fallback=(
            "a request the declaration does not cover is refused with the"
            " placement policy reached and what to remove"
        ),
    ),
    DeliveryFact(
        guarantee="rejection_receipt",
        provider="codex",
        mechanism="",
        standing="absent",
        fallback="inferred from absence and recorded as inferred, as on Claude",
    ),
    DeliveryFact(
        guarantee="hook_failure_is_closed",
        provider="codex",
        mechanism=(
            "every exception shape reaches one refusal that names what went"
            " wrong, because naming the exceptions is what let an unreadable"
            " file escape as a traceback exit"
        ),
        standing="measured",
        fallback="the reason carries whatever went wrong; an interrupt passes through",
    ),
]
"""What this repository believes about the Codex adapter, and on what basis."""
