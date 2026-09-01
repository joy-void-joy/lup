"""What the settlement order is, as an order rather than as a set of outcomes.

The classified verdict and the session facts meet in one place, and what
happens there is the position of a row rather than the position of an arm in
a ``match``. Pinned here is the property that made it worth naming: rows
compose, so a rule about the order can be read off the list instead of
derived from where a guard sits.

The escalation cases are the matrices from the product contract, spelled as
executable rows: decision escalation moves an overrideable refusal to a
question and a hard one nowhere, sandbox escalation moves a placement and
never a refusal, and the two combined reach the host over a refusal neither
reaches alone.
"""

from lup.policy.kernel.decision import SANDBOX_TRAPPED_REASON, KernelDecision
from lup.policy.kernel.escalation import EscalationRequest
from lup.policy.kernel.semantics import CheckpointEvidence, UnjudgedAmbient
from lup.policy.kernel.settlement import (
    SETTLEMENT_ORDER,
    DecisionEscalation,
    SettlementFacts,
    SettlementRule,
    settle,
)

HINT = " — reshape it"


def facts(
    decision: KernelDecision,
    escalation: EscalationRequest | None = None,
    contained: bool = False,
    confined: bool = False,
    host_executor: bool = False,
    human_execution: bool = True,
    reviewable: bool = True,
    checkpoint: CheckpointEvidence = "absent",
    unjudged_ambient: UnjudgedAmbient = "ask",
) -> SettlementFacts:
    """One verdict and the session judging it, with the defaults of a plain host."""
    return SettlementFacts(
        decision,
        escalation=escalation,
        contained=contained,
        confined=confined,
        host_executor=host_executor,
        human_execution=human_execution,
        reviewable=reviewable,
        checkpoint=checkpoint,
        unjudged_ambient=unjudged_ambient,
        hint=HINT,
    )


def contained_facts(
    decision: KernelDecision,
    escalation: EscalationRequest | None = None,
    reviewable: bool = True,
    checkpoint: CheckpointEvidence = "absent",
) -> SettlementFacts:
    """One verdict inside the boundary, with what containment implies.

    Three facts travel together and are not free to differ: the boundary is
    running, it confines this operation rather than one call of it, and
    leaving it is a channel the profile declares separately. Spelling them
    once here keeps a case from pinning a session shape that cannot exist.
    """
    return facts(
        decision,
        escalation=escalation,
        contained=True,
        confined=True,
        reviewable=reviewable,
        checkpoint=checkpoint,
    )


def decision_escalation(reason: str = "I need it") -> EscalationRequest:
    """The agent asking for a reviewer over a verdict a rule reached alone."""
    return EscalationRequest(("decision",), reason)


def sandbox_escalation(reason: str = "the host has it") -> EscalationRequest:
    """The agent asking for the launcher's host."""
    return EscalationRequest(("sandbox",), reason)


def both_escalations(reason: str = "refused and needs the host") -> EscalationRequest:
    """One marker naming both axes, which is the only route past a refusal."""
    return EscalationRequest(("decision", "sandbox"), reason)


def local_loss(reason: str = "a reset discards work") -> KernelDecision:
    """A question whose whole subject is a loss a capture would put back."""
    return KernelDecision(
        "ask", reason, checkpoint="targeted", purpose="unrecovered_local_mutation"
    )


def test_a_hard_prohibition_is_not_moved_by_asking_about_it() -> None:
    """First row, because nothing below it could change its answer.

    A hard prohibition is not a rule's judgement that somebody with more
    context might overrule — it is the shape of the thing being refused, and
    an approval does not change a shape.
    """
    settled = settle(
        facts(
            KernelDecision("deny", "inline code is unreviewable", hard=True),
            escalation=both_escalations(),
        )
    )

    assert settled.effect == "deny"


def test_a_missing_capability_is_refused_rather_than_put_to_anybody() -> None:
    """No reviewer approves a channel into existence.

    Distinct from a prohibition in what the agent should do about it: a
    refusal that reads as policy sends the agent to argue with a rule, when
    the thing missing is a channel the profile does not declare.
    """
    settled = settle(
        facts(
            KernelDecision(
                "deny",
                "no checkpoint store",
                cause="capability",
                capability="checkpoint_store",
            ),
            escalation=decision_escalation(),
        )
    )

    assert (settled.effect, settled.cause) == ("deny", "capability")
    assert settled.capability == "checkpoint_store"


def test_decision_escalation_turns_an_overrideable_refusal_into_a_question() -> None:
    settled = settle(
        facts(KernelDecision("deny", "no"), escalation=decision_escalation())
    )

    assert settled.effect == "ask"
    assert settled.reason.startswith("escalated (I need it): no")
    assert settled.escalated == "I need it"


def test_decision_escalation_turns_an_abstention_into_a_question() -> None:
    """An operation nobody judged is exactly what a reviewer is for."""
    settled = settle(
        facts(
            KernelDecision("defer", "nobody looked", abstention="boundary_settle"),
            escalation=decision_escalation(),
        )
    )

    assert settled.effect == "ask"


def test_decision_escalation_over_a_permission_says_it_was_unnecessary() -> None:
    """A marker over something already allowed buys a prompt for nothing.

    Said rather than silently dropped: an agent that learns the marker was
    unnecessary stops writing it, and one whose marker silently worked keeps
    paying for a habit it cannot see.
    """
    settled = settle(
        facts(KernelDecision("allow", "fine"), escalation=decision_escalation())
    )

    assert settled.effect == "allow"
    assert "already going to see this" in settled.reason
    assert settled.visibility == "notice"


def test_the_legacy_bare_marker_works_and_says_it_is_an_alias() -> None:
    """Every marker written before the vocabulary grew keeps working.

    The alternative is a session whose escalations all stop working at once,
    which is a migration nobody can act on mid-run.
    """
    settled = settle(
        facts(
            KernelDecision("deny", "no"),
            escalation=EscalationRequest(("decision",), "why", legacy=True),
        )
    )

    assert settled.effect == "ask"
    assert "escalate[decision]" in settled.reason


def test_sandbox_escalation_asks_before_an_allowed_operation_leaves() -> None:
    """The crossing is never unprompted on request.

    ``allow outside`` exists, but as a rule's own declaration about an
    operation nobody had to ask about. An agent asking to leave is asking a
    second question — may this run *there* — and that one has its own answer.
    """
    settled = settle(
        facts(
            KernelDecision("allow", "fine", "inside"),
            escalation=sandbox_escalation(),
            host_executor=True,
        )
    )

    assert (settled.effect, settled.sandbox) == ("ask", "outside")


def test_sandbox_escalation_alone_does_not_move_a_refusal() -> None:
    """Asking to run something elsewhere is not asking to be allowed to."""
    settled = settle(
        facts(
            KernelDecision("deny", "no"),
            escalation=sandbox_escalation(),
            host_executor=True,
        )
    )

    assert settled.effect == "deny"


def test_the_combined_marker_is_the_only_route_past_a_refusal_to_the_host() -> None:
    """Two requests, composed by their order rather than by either knowing.

    Decision escalation has already made the refusal a question by the time
    the placement row is read, which is the whole of why the combined form
    reaches the host and the sandbox half alone does not.
    """
    settled = settle(
        facts(
            KernelDecision("deny", "no"),
            escalation=both_escalations(),
            host_executor=True,
        )
    )

    assert (settled.effect, settled.sandbox) == ("ask", "outside")


def test_sandbox_escalation_of_an_already_placed_operation_says_so() -> None:
    settled = settle(
        facts(
            KernelDecision("ask", "risky", "outside"),
            escalation=sandbox_escalation(),
            host_executor=True,
        )
    )

    assert (settled.effect, settled.sandbox) == ("ask", "outside")
    assert "already placed on the host" in settled.reason


def test_an_approved_crossing_is_answerable_by_a_person_without_a_channel() -> None:
    """No automated channel is not no answer.

    The question is still worth asking so long as somebody can carry the
    answer out: the exact operation is rendered for the launcher's owner to
    run and confirm, and the crossing stays explicit, reviewed, and
    single-use either way.
    """
    settled = settle(
        facts(
            KernelDecision("allow", "fine"),
            escalation=sandbox_escalation(),
            host_executor=False,
            human_execution=True,
        )
    )

    assert (settled.effect, settled.sandbox) == ("ask", "outside")


def test_an_unprompted_crossing_with_no_channel_is_capability_blocked() -> None:
    """``allow outside`` admits no human fallback.

    Unprompted host execution exists only through the automated channel:
    handing an unreviewed operation to a person to run is a review nobody
    asked for, and running it inside would run something the placement said
    must not run there — failing on whatever it touched first, with the
    boundary misreported as a broken repository.
    """
    settled = settle(
        facts(
            KernelDecision("allow", "fine", "outside"),
            host_executor=False,
            human_execution=True,
        )
    )

    assert (settled.effect, settled.reason) == ("deny", SANDBOX_TRAPPED_REASON)
    assert settled.capability == "host_executor"


def test_a_declared_crossing_runs_where_the_channel_carries_it() -> None:
    settled = settle(
        facts(KernelDecision("allow", "fine", "outside"), host_executor=True)
    )

    assert (settled.effect, settled.sandbox) == ("allow", "outside")


def test_a_provider_native_abstention_survives_every_row_below_it() -> None:
    """The one verdict under which the session behaves as if Lup were absent.

    It settles rather than rewrites so that no row below can turn a
    deliberate handoff into a refusal for want of anybody having looked.
    Somebody looked, and what they decided is that this is the provider's.
    """
    settled = settle(
        facts(
            KernelDecision(
                "defer", "a large ordinary edit", abstention="provider_native"
            ),
            confined=False,
        )
    )

    assert (settled.effect, settled.reason) == ("defer", "a large ordinary edit")


def test_a_proven_capture_settles_a_recoverable_loss_to_a_permission() -> None:
    """A permission and not a deferral, which is the difference that matters.

    Deferring would make the outcome depend on the mode the session happened
    to be in, for a fact that has nothing to do with the session's mode. This
    policy has positively established that the loss it was protecting against
    did not happen, so it authorizes rather than hands on.
    """
    settled = settle(facts(local_loss(), checkpoint="complete"))

    assert settled.effect == "allow"
    assert "captured and restorable" in settled.reason


def test_a_capture_that_failed_keeps_the_question_and_says_which_it_was() -> None:
    """Never a deferral: a failed capture is a fact worth a person seeing.

    "Nobody captured this" and "the capture did not work" are different
    things to tell somebody, and only the second says the loss it was going
    to cover is unprotected right now.
    """
    settled = settle(facts(local_loss(), checkpoint="failed"))

    assert settled.effect == "ask"
    assert "capture that would have settled this failed" in settled.reason
    assert settled.visibility == "notice"


def test_recovery_discharges_local_loss_and_nothing_travelling_beside_it() -> None:
    """The whole limit of what a capture is allowed to answer.

    A recoverable deletion beside a full-file rewrite is one operation with
    two reasons to ask, and a capture answers one of them. Read over the join
    alone the second reason is invisible, which is how a capture came to
    discharge a code review it had nothing to do with.
    """
    review = KernelDecision(
        "ask", "a production file is replaced whole", purpose="quality_review"
    )
    joined = KernelDecision(
        "ask",
        "two reasons",
        checkpoint="targeted",
        findings=(local_loss(), review),
    )

    assert settle(facts(joined, checkpoint="complete")).effect == "ask"


def test_a_stated_reason_keeps_the_question_a_capture_would_have_settled() -> None:
    """The marker is a request to be judged, and evidence does not overrule it.

    Answering it with a permission would drop both the question and the
    reason given for it, which is the one thing an escalation exists to put
    in front of somebody.
    """
    settled = settle(
        facts(
            local_loss(),
            escalation=decision_escalation("I need the clean tree"),
            checkpoint="complete",
        )
    )

    assert settled.effect == "ask"
    assert "I need the clean tree" in settled.reason


def test_odd_local_work_the_boundary_confines_runs_inside_rather_than_asking() -> None:
    """The practical default, and it is a permission rather than a deferral.

    Reading ``/etc/passwd`` inside the boundary observes the contained
    environment. Settling it to ``allow inside`` is what makes the placement
    Lup's, so it holds however permissive the session's own mode is — which
    is the whole difference between containing something and hoping the
    provider contains it.
    """
    settled = settle(
        contained_facts(
            KernelDecision("defer", "nobody looked", abstention="boundary_settle")
        )
    )

    assert (settled.effect, settled.sandbox) == ("allow", "inside")


def test_an_unjudged_ambient_operation_follows_the_profile_declaration() -> None:
    """Two answers, both declared rather than inferred.

    ``ask`` keeps unjudged work visible and is the default, because what the
    reviewer is shown is exactly what will run. ``defer`` is a profile
    deliberately handing the long tail to provider-native judgement.
    """
    unlisted = KernelDecision(
        "defer", "nobody looked", unlisted=True, abstention="boundary_settle"
    )

    assert settle(facts(unlisted)).effect == "ask"
    assert settle(facts(unlisted, unjudged_ambient="defer")).effect == "defer"


def test_an_operation_the_classifier_could_not_read_is_refused_either_way() -> None:
    """A question about text the policy could not parse is unanswerable.

    ``cat x ;& rm -rf ~`` would be approved on the strength of the ``cat``,
    so a reviewer's presence buys nothing and the refusal stands — under both
    unjudged-ambient declarations, because neither is about legibility.
    """
    opaque = KernelDecision("defer", "unreadable", abstention="boundary_settle")

    assert settle(facts(opaque)).effect == "deny"
    assert settle(facts(opaque, unjudged_ambient="defer")).effect == "deny"


def test_a_question_no_eligible_reviewer_can_be_reached_from_is_not_one() -> None:
    """Rewritten to an abstention so the boundary answers what nobody could.

    The reason says the question existed and could not be put, because a
    refusal that reads as a rule's judgement sends the agent to reshape an
    operation that was never the problem.
    """
    contained = settle(
        contained_facts(KernelDecision("ask", "risky"), reviewable=False)
    )
    exposed = settle(facts(KernelDecision("ask", "risky"), reviewable=False))

    assert contained.effect == "allow"
    assert exposed.effect == "deny"
    assert "no eligible reviewer" in exposed.reason


def test_a_judged_refusal_is_not_rescued_by_a_boundary() -> None:
    """The distinction the whole order rests on.

    Unjudged work is refused for want of anybody having looked, and a
    boundary answers that. A judged deny is somebody's answer, and running it
    confined would still be running it.
    """
    judged = settle(contained_facts(KernelDecision("deny", "refused")))
    nobody_looked = settle(
        contained_facts(
            KernelDecision("defer", "unknown", abstention="boundary_settle")
        )
    )

    assert judged.effect == "deny"
    assert nobody_looked.effect == "allow"


def test_every_refusal_carries_a_cause_a_reader_can_count_by() -> None:
    """Prose is not a taxonomy; a cause is.

    Measured on the corpus before causes existed: 860 asks with no recorded
    reason at all, and a deny taxonomy that could only be reconstructed by
    matching sentences.
    """
    judged = settle(facts(KernelDecision("deny", "refused")))
    unreadable = settle(
        facts(KernelDecision("defer", "opaque", abstention="boundary_settle"))
    )

    assert judged.cause == "deliberate"
    assert unreadable.cause == "unreadable"


def test_the_first_settling_row_ends_the_pass() -> None:
    """Precedence is position, and a row after a settlement is never read."""

    class Loud(SettlementRule):
        def reached(self, facts: SettlementFacts) -> KernelDecision:
            return KernelDecision("deny", "never reached")

    settled = settle(
        facts(KernelDecision("allow", "fine")),
        order=[*SETTLEMENT_ORDER, Loud()],
    )

    assert (settled.effect, settled.reason) == ("allow", "fine")


def test_the_order_is_the_policy_and_a_shorter_one_is_a_different_policy() -> None:
    """Taking a row out changes the answer, which is what makes it a rule.

    Without the row that turns a refusal into a question, a stated reason has
    nothing to say and the refusal stands. That is the whole content of "a
    marker never leaves a refusal standing", and it lives in one place.
    """
    request = decision_escalation()
    kept = settle(facts(KernelDecision("deny", "no"), escalation=request))
    without = settle(
        facts(KernelDecision("deny", "no"), escalation=request),
        order=[
            rule
            for rule in SETTLEMENT_ORDER
            if not isinstance(rule, DecisionEscalation)
        ],
    )

    assert kept.effect == "ask"
    assert without.effect == "deny"


def test_every_row_is_named_so_an_audit_can_say_which_one_answered() -> None:
    """A settled verdict a reader cannot attribute is one nobody can tune."""
    assert all(rule.id for rule in SETTLEMENT_ORDER)
    assert len({rule.id for rule in SETTLEMENT_ORDER}) == len(SETTLEMENT_ORDER)
