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
    recovered: bool = False,
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
        recovered=recovered,
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
        recovered=True,
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
    answers that question by refusing rather than by letting the call
    through. Two rows, neither naming the other, and the answer is the
    composition — which is what a `match` arm could only express by being in
    the right place.

    The boundary does not enter it, though one is running here. A marker is
    the agent asking to be judged, and a deferral is the policy declining to
    judge: resolving one with the other would make the instrument for
    summoning a human the instrument for bypassing the table, and on a host
    with nobody to summon it would work every time. What the refusal buys is
    the stated reason surviving to whoever reads the relay.
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

    assert settled.effect == "deny"
    assert settled.reason.startswith("escalated (I need it): no")


def test_a_question_nobody_can_answer_defers_and_says_what_is_beneath_it() -> None:
    """The same two rewrites, with nothing beneath them to carry the call.

    This refused once, on the reasoning that a deferral with no boundary
    under it relaxes into nothing. What that cost was paid by the session
    the project actually ships: the launcher withholds the sandbox flag
    inside a container *because* the container is the boundary, the kernel
    read only the flag, and unjudged work denied behind the strongest
    boundary there is.

    So the verdict no longer turns on the boundary and the reason names it
    instead — which is the honest form of the same information, since a
    deferral was never a permission. It hands the call to the runtime's own
    gate, and a session at that gate's defaults is still asked.
    """
    settled = settle(
        facts(KernelDecision("ask", "risky"), interactive=False, sandboxed=False)
    )

    assert settled.effect == "defer"
    assert "nothing is beneath it" in settled.reason


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


def test_a_loss_the_undo_layer_holds_is_settled_rather_than_asked() -> None:
    """The relaxation, and the axis that keeps it from being a blanket one.

    An approval question exists because a loss is permanent. What makes a
    loss permanent is a fact about the session, so a rule names the restorer
    its question was about and this row asks whether that restorer is here.
    `snapshot` is the narrow one: the loss is working-tree content, which the
    undo layer holds whether or not a container is running.
    """
    settled = settle(
        facts(
            KernelDecision("ask", "a reset discards work", recovery="snapshot"),
            recovered=True,
        )
    )

    assert settled.effect == "defer"
    assert "the tree is in the object store" in settled.reason


def test_a_loss_only_a_container_holds_waits_for_one() -> None:
    """`container` needs both facts, which is what makes it the wider value.

    A command that writes on this machine is answered by a container, whose
    machine is rebuilt from a declaration — and the one part of that machine
    the container does not protect is the bind-mounted checkout, which the
    snapshot holds. Neither alone is the answer.
    """
    question = KernelDecision("ask", "extraction writes files", recovery="container")

    assert settle(facts(question, recovered=True)).effect == "ask"
    assert settle(contained_facts(question)).effect == "defer"


def test_a_loss_nothing_holds_keeps_its_question() -> None:
    """The default, and the whole safety of the axis.

    A rule nobody annotated keeps asking. `git clean -fdx` is the deliberate
    instance rather than an oversight: it destroys ignored files, which the
    snapshot leaves out, so it is the one destructive verb that keeps asking
    in the posture where its neighbours stop.
    """
    settled = settle(contained_facts(KernelDecision("ask", "deleting untracked files")))

    assert settled.effect == "ask"


def test_a_stated_reason_keeps_the_question_the_agent_asked_for() -> None:
    """The marker is a request to be judged, and a boundary does not overrule it.

    Answering it with a deferral would drop both the question and the reason
    given for it, which is the one thing an escalation exists to put in front
    of somebody.
    """
    settled = settle(
        facts(
            KernelDecision("ask", "a reset discards work", recovery="snapshot"),
            escalation="I need the clean tree",
            recovered=True,
        )
    )

    assert settled.effect == "ask"
    assert "I need the clean tree" in settled.reason


def test_a_judged_deferral_is_not_refused_as_an_unexamined_one() -> None:
    """The care `defer` needs once it carries a judgement.

    Two things reach the word: :func:`unjudged` means nobody looked, and this
    row means somebody looked and the boundary answers. `Unjudged` turns the
    first into a refusal for want of anybody having looked — the one reason
    that is not true of the second. So this row settles rather than rewrites,
    and no boundary is needed for it to hold.
    """
    settled = settle(
        facts(
            KernelDecision("ask", "removing tracked files", recovery="snapshot"),
            recovered=True,
        )
    )

    assert settled.effect == "defer"
    assert HINT not in settled.reason
