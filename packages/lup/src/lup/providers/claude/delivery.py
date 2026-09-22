"""What the Claude adapter is built to deliver, and how each belief is known.

Stated here rather than in the neutral vocabulary because every mechanism
below is named in this runtime's own words — a hook event, the field a verdict
rewrites, the modes a decision survives. Those words are sanctioned at this
boundary and nowhere else, and a shared file naming both runtimes' spellings
is the fork the boundary rule exists to prevent.

The standing on each row is the load-bearing half. Vendor documentation is
evidence and not proof of delivered behaviour: a documented behaviour a build
changed reads exactly like one it did not.
"""

from lup.policy.delivery import DeliveryFact


# lup: ignore[constant-declaration] — an observation of one runtime rather
# than a judgement: nobody passes in a different set of facts about what
# this provider does, and a caller who disagreed would be disagreeing with
# the measurement rather than configuring it
CLAUDE_DELIVERY: list[DeliveryFact] = [
    DeliveryFact(
        guarantee="ask_survives_auto_mode",
        provider="claude",
        mechanism=(
            "the generated PreToolUse hook refuses unresolved asks and requires"
            " an explicit recorded reviewer answer before allowing one exact retry"
        ),
        standing="measured",
        fallback=(
            "generated-dispatcher fixtures verify the receipt gate; native ask"
            " is not a human receipt, and unexpected execution is diagnosed as"
            " in_doubt without granting future authority"
        ),
    ),
    DeliveryFact(
        guarantee="exact_call_resumes",
        provider="claude",
        mechanism=(
            "an operator answer releases one retry with the same session,"
            " directory, payload, policy reason and edited file preimages"
        ),
        standing="measured",
        fallback=(
            "the fingerprint is revalidated before dispatch either way, so a"
            " resumption that reconstructed a different call is refused as a"
            " fresh question rather than run under the old approval"
        ),
    ),
    DeliveryFact(
        guarantee="defer_is_transparent",
        provider="claude",
        mechanism=(
            "the hook emits no permission decision at all, so the session's own"
            " permission flow applies exactly as it would with no hook installed"
        ),
        standing="documented",
        fallback="none needed: emitting nothing is the absence of a mechanism",
    ),
    DeliveryFact(
        guarantee="inside_placement_enforced",
        provider="claude",
        mechanism=(
            "updatedInput rewrites the call's own sandbox argument, which the"
            " runtime reads back — so an inside placement overwrites a flag the"
            " agent set for itself rather than negotiating with it"
        ),
        standing="documented",
        fallback=(
            "where the rewrite is dropped, the operation runs at the session's"
            " own posture and the placement is a claim nothing carried; the"
            " boundary preflight is what turns that into a launch failure"
        ),
    ),
    DeliveryFact(
        guarantee="outside_placement_carried",
        provider="claude",
        mechanism=(
            "the same rewrite, but reaching the launcher's host needs the"
            " profile's host executor rather than the native flag"
        ),
        standing="documented",
        fallback=(
            "a profile with no host executor refuses the operation as"
            " capability-blocked; no approval creates the channel"
        ),
    ),
    DeliveryFact(
        guarantee="rejection_receipt",
        provider="claude",
        mechanism="an explicit rejection is recorded by the review queue",
        standing="measured",
        fallback=(
            "absence of native execution supplies no answer; pending questions"
            " remain pending until an explicit answer or execution observation"
        ),
    ),
    DeliveryFact(
        guarantee="hook_failure_is_closed",
        provider="claude",
        mechanism=(
            "the dispatcher takes one failure shape for every exception and"
            " returns it as a decision rather than a traceback exit"
        ),
        standing="measured",
        fallback=(
            "a timed-out pre-tool hook falls through to the normal permission"
            " flow rather than blocking, which is why the dispatcher never waits"
            " on the relay"
        ),
    ),
]
"""What this repository believes about the Claude adapter, and on what basis."""
