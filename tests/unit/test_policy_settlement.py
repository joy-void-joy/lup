"""What the settlement order is, as an order rather than as four outcomes.

The classified verdict and the session facts meet in one place, and what
happens there used to be the position of an arm in a ``match``. Pinned here
is the property that made it worth naming: rows compose, so a rule about the
order can be read off the list instead of derived from where a guard sits.
"""

from lup.policy.kernel.decision import SANDBOX_TRAPPED_REASON, KernelDecision
from lup.policy.kernel.settlement import (
    SETTLEMENT_ORDER,
    SettlementFacts,
    SettlementRule,
    StatedReason,
    settle,
)

HINT = " — reshape it"


def facts(
    decision: KernelDecision,
    escalation: str = "",
    sandboxed: bool = False,
    contained: bool = False,
    confined: bool = False,
    escapable: bool = False,
    interactive: bool = True,
) -> SettlementFacts:
    """One verdict and the session judging it, with the defaults of a plain host."""
    return SettlementFacts(
        decision,
        escalation=escalation,
        sandboxed=sandboxed,
        contained=contained,
        confined=confined,
        escapable=escapable,
        interactive=interactive,
        hint=HINT,
    )


def contained_facts(
    decision: KernelDecision, escalation: str = "", interactive: bool = True
) -> SettlementFacts:
    """One verdict inside the container, with what a container implies.

    Four facts travel together and are not free to differ: a container is a
    boundary, it confines the whole session rather than one call, it has no
    channel to put a call outside itself, and it is a container. Spelling
    them once here is what keeps a case from pinning a session shape that
    cannot exist.
    """
    return facts(
        decision,
        escalation=escalation,
        sandboxed=True,
        contained=True,
        confined=True,
        escapable=False,
        interactive=interactive,
    )


def test_a_container_answers_a_placement_rather_than_trapping_on_it() -> None:
    """The posture that is the default, and what it refused before this row.

    `outside` names the native per-call sandbox: it is what git and the
    devtools toolchain declare because that sandbox denies the runtime's
    configuration home, the repository's locks, and the route to a remote. A
    container denies none of them, so the requirement is already met — but a
    container also has no escape channel, which is exactly what
    `TrappedPlacement` refuses on. Measured before this row existed, a
    contained session denied `git status`, `git log`, `dev check` and every
    other `lup-devtools` command.
    """
    settled = settle(contained_facts(KernelDecision("allow", "fine", "outside")))

    assert (settled.effect, settled.sandbox) == ("allow", "ambient")


def test_a_host_with_no_container_still_traps_the_placement_it_cannot_carry() -> None:
    """The row above narrows `TrappedPlacement` and must not empty it.

    A native sandbox with no per-call escape is a different session from a
    container: there the placement is unmet, the call fails on whatever it
    writes first, and the failure reads as a broken repository. Codex is that
    session by construction, having no per-call escape at all.
    """
    settled = settle(
        facts(KernelDecision("allow", "fine", "outside"), sandboxed=True, confined=True)
    )

    assert (settled.effect, settled.reason) == ("deny", SANDBOX_TRAPPED_REASON)


def test_a_container_leaves_an_unplaced_verdict_exactly_as_it_was() -> None:
    """The rewrite is about the placement axis and touches nothing else."""
    settled = settle(contained_facts(KernelDecision("ask", "needs a human")))

    assert (settled.effect, settled.reason) == ("ask", "needs a human")


def test_a_stated_reason_turns_a_refusal_into_the_question_it_asked_for() -> None:
    settled = settle(facts(KernelDecision("deny", "no"), escalation="I need it"))

    assert (settled.effect, settled.reason) == ("ask", "escalated (I need it): no")


def test_a_stated_reason_leaves_a_permission_alone() -> None:
    """A marker over something already allowed buys a prompt for nothing."""
    settled = settle(facts(KernelDecision("allow", "fine"), escalation="just in case"))

    assert (settled.effect, settled.reason) == ("allow", "fine")


def test_two_rewriting_rows_compose_without_knowing_about_each_other() -> None:
    """The property the order exists for.

    A stated reason makes a refusal a question; a host with nobody to ask
    makes a question no judgment; a boundary carries what nobody judged.
    Three rows, none of which names another, and the answer is the
    composition — which is what a `match` arm could only express by being in
    the right place.
    """
    settled = settle(
        facts(
            KernelDecision("deny", "no"),
            escalation="I need it",
            sandboxed=True,
            confined=True,
            interactive=False,
        )
    )

    assert settled.effect == "defer"
    assert settled.reason == "escalated (I need it): no"


def test_a_question_nobody_can_answer_without_a_boundary_is_refused() -> None:
    """The same two rewrites, with nothing beneath them to carry the call."""
    settled = settle(
        facts(KernelDecision("ask", "risky"), interactive=False, sandboxed=False)
    )

    assert (settled.effect, settled.reason) == ("deny", "risky" + HINT)


def test_no_stated_reason_places_a_call_the_host_cannot_place() -> None:
    """Approval does not give a host a channel it does not have.

    A call declared ``outside`` where nothing can put it outside fails on
    whatever it writes first, and the failure reads as a broken repository.
    That is a refusal about capability, so the row settles rather than
    rewrites and the marker above it does not survive to the wire.
    """
    settled = settle(
        facts(
            KernelDecision("ask", "needs the network", "outside"),
            escalation="please",
            sandboxed=True,
            escapable=False,
        )
    )

    assert (settled.effect, settled.reason) == ("deny", SANDBOX_TRAPPED_REASON)


def test_a_judged_refusal_is_not_rescued_by_a_boundary() -> None:
    """The distinction the whole lattice rests on.

    Unjudged work is refused for want of anybody having looked, and a
    boundary answers that. A judged deny is somebody's answer, and running it
    confined would still be running it.
    """
    judged = settle(
        facts(KernelDecision("deny", "refused"), sandboxed=True, confined=True)
    )
    nobody_looked = settle(
        facts(KernelDecision("defer", "unknown"), sandboxed=True, confined=True)
    )

    assert judged.effect == "deny"
    assert nobody_looked.effect == "defer"


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
    kept = settle(facts(KernelDecision("deny", "no"), escalation="I need it"))
    without = settle(
        facts(KernelDecision("deny", "no"), escalation="I need it"),
        order=[rule for rule in SETTLEMENT_ORDER if not isinstance(rule, StatedReason)],
    )

    assert kept.effect == "ask"
    assert without.effect == "deny"
