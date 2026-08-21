"""The order that settles a classified verdict into the one a session runs.

Classification answers what the vocabulary says about a command. It does not
answer what happens, because one verdict means different things in different
sessions: a question needs somebody to put it to, work nobody judged needs to
know whether a boundary sits beneath it, a placement is only worth declaring
where the host can carry it out, and one the boundary already satisfies is
not left for anybody to carry at all.

Those facts were a ``match`` over four arms with guards, where the answer to
"what does a stated reason do" was the *position* of one arm and the answer to
"and what about a stated reason over something already permitted" was that no
arm covered it. Here they are an ordered list read the way `.gitignore` reads
patterns: every row is offered the running verdict, a row that rewrites hands
its result to the next, and the first row that settles ends the pass. A rule
about the order — *a stated reason never leaves a refusal standing*, say — is
then a row that says so, rather than an arm somebody has to place correctly.

Two rows settle a refusal that no stated reason reaches, because both say the
call cannot happen rather than that nobody approved it: a marker with no
reason, which would be authorising itself, and a call declared ``outside`` on
a host with no channel to put it there, where an approval would only move the
failure to a bare filesystem error with the boundary misreported as a bug in
the code. The first is refused before classification and never arrives here.
"""

from .decision import SANDBOX_TRAPPED_REASON, KernelDecision


class SettlementFacts:
    """One classified verdict, and everything about the session judging it.

    Carried as one value so a row cannot read a fact the row beside it was
    not offered, and so the running verdict travels with the facts that
    settle it rather than beside them.
    """

    decision: KernelDecision
    escalation: str
    sandboxed: bool
    contained: bool
    confined: bool
    escapable: bool
    recovered: bool
    interactive: bool
    hint: str

    def __init__(
        self,
        decision: KernelDecision,
        escalation: str,
        sandboxed: bool,
        contained: bool,
        confined: bool,
        escapable: bool,
        recovered: bool,
        interactive: bool,
        hint: str,
    ) -> None:
        self.decision = decision
        self.escalation = escalation
        self.sandboxed = sandboxed
        self.contained = contained
        self.confined = confined
        self.escapable = escapable
        self.recovered = recovered
        self.interactive = interactive
        self.hint = hint

    def rewritten(self, decision: KernelDecision) -> "SettlementFacts":
        """These same facts, with a row's rewrite standing as the verdict."""
        return SettlementFacts(
            decision,
            self.escalation,
            self.sandboxed,
            self.contained,
            self.confined,
            self.escapable,
            self.recovered,
            self.interactive,
            self.hint,
        )


class SettlementRule:
    """One row of the order, and whether reaching it ends the pass.

    ``settles`` is the difference between the two kinds of row. A settling
    row is the answer: nothing after it is read. A rewriting row changes what
    the rows after it are judging, which is how a stated reason and a missing
    approval channel compose without either knowing about the other.
    """

    settles: bool = True

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        """This row's verdict, or ``None`` where it has nothing to say."""
        raise NotImplementedError


class StatedReason(SettlementRule):
    """A marker turns anything not already permitted into a question.

    The agent asked to be judged, so the refusal becomes the question it
    asked for, carrying the reason it gave — the human sees intent at the
    moment of judgment rather than a bare rule name. Nothing is done to a
    verdict that already allows: a stated reason over something permitted
    would buy a prompt for nothing.
    """

    settles = False

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if not facts.escalation or facts.decision.effect == "allow":
            return None
        return KernelDecision(
            "ask",
            f"escalated ({facts.escalation}): {facts.decision.reason}",
            facts.decision.sandbox,
            facts.decision.recovery,
        )


class ContainedPlacement(SettlementRule):
    """A container is the place every placement was asking for.

    ``outside`` names the native per-call sandbox and nothing else. It is
    what a toolchain declares when that sandbox denies the paths it needs --
    the runtime's own configuration home, the repository's locks, a route to
    the remote. A container denies none of them: the checkout is mounted
    writable, the configuration home is the container's own, and the route
    out is the egress proxy. So the requirement is met by construction, and
    what is left to carry is nothing.

    Rewritten to ``ambient`` rather than left standing, because a placement
    nothing can act on is one the runtimes still act on: Claude Code reads
    the verdict's placement back as an argument of the call, and a request to
    leave a sandbox that is not running is a request about nothing.

    This is the reachable half of retiring the placement axis under a
    container, done where the axis is read rather than by deleting the field
    the uncontained posture still needs. Measured before it existed: a
    contained session refused `git status`, `git log`, `dev check` and every
    other `lup-devtools` command, because git and the toolchain are declared
    ``outside`` across their whole surface and :class:`TrappedPlacement`
    below answers for a host with no escape channel -- which a container,
    having no sandbox to escape, looks exactly like.
    """

    settles = False

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if not facts.contained or facts.decision.sandbox == "ambient":
            return None
        return KernelDecision(
            facts.decision.effect,
            facts.decision.reason,
            recovery=facts.decision.recovery,
        )


class TrappedPlacement(SettlementRule):
    """A call declared ``outside`` on a host that cannot place it there.

    Not advice: confined, it fails on whatever it writes first, and the
    failure reads as a broken repository rather than as a boundary. Stopped
    here with the reason that says which it was, and no stated reason moves
    it, because approval does not give the host a channel it does not have.

    Answers for a native sandbox only. A container reaches
    :class:`ContainedPlacement` above and never arrives here, because the
    thing it cannot escape is also the thing the placement was asking for.
    """

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.sandboxed and not facts.escapable:
            if facts.decision.sandbox == "outside":
                return KernelDecision("deny", SANDBOX_TRAPPED_REASON)
        return None


class RestoredBySession(SettlementRule):
    """An approval question about a loss this session can already put back.

    The vocabulary guards *the direction that removes something no second
    attempt restores*. What a second attempt restores is a fact about the
    session and not about the command, and every rule states which restorer
    its question was about — so where that restorer is present, the loss the
    question was protecting against does not happen and the question has no
    subject.

    Settled as a **deferral, not a permission**, and the difference is the
    whole design. Nothing here decides the call may run: it decides that this
    policy has no reason left to interrupt, and hands the call to the
    runtime's own gate, which is where an operator's configuration lives. A
    session run with everything approved runs it; a session at the runtime's
    defaults is still asked, in the runtime's own words. The policy stops
    spending a human's attention on a loss it can undo, and buys no authority
    with it.

    Which makes ``defer`` two things reaching one word, and the rows below
    have to keep them apart: a deferral from :func:`unjudged` means *nobody
    looked*, and this one means *somebody looked and the boundary answers*.
    So this row settles rather than rewrites. :class:`Unjudged` turns an
    unexamined deferral into a refusal for want of anybody having looked, and
    a judged deferral that fell through to it would be refused for the one
    reason that is not true of it.

    A stated reason keeps its question. `# lup: escalate:` is the agent
    asking to be judged, and answering it with a deferral would drop both the
    question and the reason given for it.
    """

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.effect != "ask" or facts.escalation:
            return None
        match facts.decision.recovery:
            case "snapshot" if facts.recovered:
                held = "the tree is in the object store"
            # Both, and not the container alone. What a container makes
            # disposable is the machine; the checkout is bind-mounted from
            # the host and survives it, so the wider value needs the narrower
            # one underneath it or it relaxes the half nothing holds.
            case "container" if facts.contained and facts.recovered:
                held = "the container is disposable and the tree is held"
            case _:
                return None
        # The recovery travels onto the deferral, and is the whole of how a
        # reader downstream tells this from a deferral nobody looked at. Both
        # reach the word `defer`, and they are worth opposite things: an
        # unjudged one is a gap in the vocabulary, and this one is a rule
        # having looked. Left off, the only difference would be the wording
        # of a reason, which is not a distinction anything should read.
        return KernelDecision(
            "defer",
            f"{facts.decision.reason} — settled by this session rather than"
            f" asked: {held}",
            recovery=facts.decision.recovery,
        )


class UnanswerableQuestion(SettlementRule):
    """A question on a host with nobody to put it to is not a question.

    Rewritten to no judgment rather than settled, so what happens next is
    decided by whether a boundary sits beneath the call — which is the same
    question anything else nobody judged has to answer.
    """

    settles = False

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.effect == "ask" and not facts.interactive:
            return KernelDecision("defer", facts.decision.reason)
        return None


class ConfinedElsewhere(SettlementRule):
    """No judgment, and a boundary beneath it: the boundary carries it.

    The OS confines the call, so the semantic layer says nothing and lets the
    runtime's own gate decide inside it. This is the whole of what a sandbox
    buys the deny lattice, and it is why the lattice may be smaller wherever
    one is running.
    """

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.effect == "defer" and facts.confined:
            return facts.decision
        return None


class Unjudged(SettlementRule):
    """No judgment and no boundary: the only thing left is to refuse.

    The refusal names the recipe rather than only the wall — reshape it into
    the allowed vocabulary, or say why it has to be this shape — because work
    nobody classified is work somebody has to look at, and an agent told only
    "no" looks at nothing.
    """

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.effect == "defer":
            return KernelDecision("deny", facts.decision.reason + facts.hint)
        return None


class JudgedRefusal(SettlementRule):
    """A rule refused this, and no sandbox rescues a judged deny.

    The distinction the lattice rests on: unjudged work is refused for want
    of anybody having looked, and a boundary answers that. A judged deny is
    somebody's answer, and running it confined would still be running it.
    """

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.effect == "deny":
            return KernelDecision("deny", facts.decision.reason + facts.hint)
        return None


class Standing(SettlementRule):
    """Whatever reached here stands: a permission, or an answerable question."""

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        return facts.decision


SETTLEMENT_ORDER: list[SettlementRule] = [
    ContainedPlacement(),
    StatedReason(),
    TrappedPlacement(),
    RestoredBySession(),
    UnanswerableQuestion(),
    ConfinedElsewhere(),
    Unjudged(),
    JudgedRefusal(),
    Standing(),
]
"""Every row, in the order they are read.

Precedence is position, so the two rewriting rows come before what reads
their result and ``Standing`` comes last because it speaks for everything.
"""


def settle(
    facts: SettlementFacts, order: list[SettlementRule] = SETTLEMENT_ORDER
) -> KernelDecision:
    """Read the order over one classified verdict and return what it settles."""
    for rule in order:
        reached = rule.reached(facts)
        if reached is None:
            continue
        if rule.settles:
            return reached
        facts = facts.rewritten(reached)
    return facts.decision
