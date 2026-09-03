"""The order that settles a classified verdict into the one a session runs.

Classification answers what the rules say about an operation. It does not
answer what happens, because one verdict means different things in different
sessions: a question needs somebody eligible to answer it, work nobody judged
needs to know whether a containment boundary sits beneath it, a placement is
only worth declaring where some channel can carry it out, and a loss a proven
capture puts back is not a loss anybody needs to be asked about.

Those facts are an ordered list read the way `.gitignore` reads patterns:
every row is offered the running verdict, a row that rewrites hands its
result to the next, and the first row that settles ends the pass. A rule
about the order — *a hard prohibition is not moved by asking*, *an approval
cannot manufacture a capability* — is then a row that says so, rather than an
arm somebody has to place correctly.

The pass runs twice over one operation. **Preliminary** settlement reads what
is known before anything is captured or locked, and is what parks a question:
an independent review requirement is put to a reviewer without a mutation
lease held, because a question waiting on a person must not hold a lock the
rest of the session needs. **Dynamic** settlement runs after approval and
after capture, over the same rows with measured evidence in place, and is the
only pass in which recovery can discharge anything. Both are this one order;
what differs is the facts it is given, which is why a row never asks which
pass it is in.
"""

from .decision import (
    SANDBOX_TRAPPED_REASON,
    KernelDecision,
    recovery_dischargeable,
)
from .escalation import EscalationRequest
from .semantics import CheckpointEvidence, UnjudgedAmbient

# Every sentence below is one settlement row's own wording, declared beside the
# row that returns it: a caller passing different words would be stating a
# different settlement, not configuring this one. The kernel is compiled
# hermetically into a dispatcher that takes no arguments, so there is no caller
# to reach in any case.
# lup: ignore[constant-declaration] — a row's own wording
REDUNDANT_DECISION = " — a reviewer was already going to see this"
# lup: ignore[constant-declaration] — a row's own wording
REDUNDANT_SANDBOX = " — this was already placed on the host"
# lup: ignore[constant-declaration] — a row's own wording
ESCALATED_PREFIX = "escalated ({reason}): "
# lup: ignore[constant-declaration] — a row's own wording
CONTAINED_READ = (
    " — settled inside the containment boundary rather than asked: every"
    " effect it can have is confined there"
)
# lup: ignore[constant-declaration] — a row's own wording
RECOVERED_LOSS = " — settled rather than asked: {held}"
# lup: ignore[constant-declaration] — a row's own wording
CHECKPOINT_FAILED = (
    " — the capture that would have settled this failed, so the loss it was"
    " going to cover is unprotected and the question stands"
)
# lup: ignore[constant-declaration] — a row's own wording
NO_REVIEWER = (
    " — no eligible reviewer is reachable from this session, so the question"
    " cannot be put to anybody"
)


class SettlementFacts:
    """One classified verdict, and everything about the session judging it.

    Carried as one value so a row cannot read a fact the row beside it was
    not offered, and so the running verdict travels with the facts that
    settle it rather than beside them.
    """

    decision: KernelDecision
    escalation: EscalationRequest | None
    contained: bool
    inside_placement: bool
    sandbox_confined: bool
    host_executor: bool
    human_execution: bool
    reviewable: bool
    checkpoint: CheckpointEvidence
    unjudged_ambient: UnjudgedAmbient
    unleased: list[str]
    hint: str

    def __init__(
        self,
        decision: KernelDecision,
        escalation: EscalationRequest | None = None,
        contained: bool = False,
        inside_placement: bool = False,
        sandbox_confined: bool = False,
        host_executor: bool = False,
        human_execution: bool = False,
        reviewable: bool = True,
        checkpoint: CheckpointEvidence = "absent",
        unjudged_ambient: UnjudgedAmbient = "ask",
        unleased: list[str] | None = None,
        hint: str = "",
    ) -> None:
        self.decision = decision
        self.escalation = escalation
        self.contained = contained
        self.inside_placement = inside_placement
        self.sandbox_confined = sandbox_confined
        self.host_executor = host_executor
        self.human_execution = human_execution
        self.reviewable = reviewable
        self.checkpoint = checkpoint
        self.unjudged_ambient = unjudged_ambient
        self.unleased = unleased or []
        self.hint = hint

    def asks(self, kind: str) -> bool:
        """Whether the operation carried an escalation request of one kind."""
        return self.escalation is not None and kind in self.escalation.kinds

    def bounded(self) -> bool:
        """Whether anything confines every effect this operation can have.

        The one question the order asks about boundaries, derived rather than
        supplied, because a caller free to compute it is a caller free to
        compute it differently — and two of them did. The kernel took
        ``confined`` as its own argument, the shell path filled it from the
        native sandbox alone, and a container measured per launch reached the
        row named for it and settled nothing.

        Two mechanisms, joined here and nowhere else. The native sandbox
        confines one call at a time and can be told to leave some alone, so
        its term arrives already net of that exclusion. A container confines
        the process and was never asked, so no per-command lever reduces it —
        but the placement it promises is a claim, and a claim no probe
        confirmed is not evidence, so the launch's measurement of it is what
        makes containment count.
        """
        return self.sandbox_confined or (self.contained and self.inside_placement)

    def rewritten(self, decision: KernelDecision) -> "SettlementFacts":
        """These same facts, with a row's rewrite standing as the verdict."""
        return SettlementFacts(
            decision,
            escalation=self.escalation,
            contained=self.contained,
            inside_placement=self.inside_placement,
            sandbox_confined=self.sandbox_confined,
            host_executor=self.host_executor,
            human_execution=self.human_execution,
            reviewable=self.reviewable,
            checkpoint=self.checkpoint,
            unjudged_ambient=self.unjudged_ambient,
            unleased=self.unleased,
            hint=self.hint,
        )


class SettlementRule:
    """One row of the order, and whether reaching it ends the pass.

    ``settles`` is the difference between the two kinds of row. A settling
    row is the answer: nothing after it is read. A rewriting row changes what
    the rows after it are judging, which is how an escalation request and a
    missing channel compose without either knowing about the other.
    """

    settles: bool = True
    id: str = ""

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        """This row's verdict, or ``None`` where it has nothing to say."""
        raise NotImplementedError


class HardProhibition(SettlementRule):
    """A policy invariant, which asking about does not move.

    First, because every row after it is about who could answer or what could
    be proven, and the answer here is nobody and nothing. A hard prohibition
    is not a rule's judgement that a person with more context might overrule
    — it is the shape of the thing being refused, and an approval does not
    change a shape.
    """

    id = "hard-prohibition"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.effect == "deny" and facts.decision.hard:
            return facts.decision.revised(reason=facts.decision.reason + facts.hint)
        return None


class MissingCapability(SettlementRule):
    """A guarantee the runtime cannot deliver, which approval cannot create.

    Second for the same reason the first row is first: no reviewer answers
    it. What separates it from a prohibition is what the agent should do
    about it — a refusal that reads as policy sends the agent to argue with a
    rule, when the thing to fix is a channel the profile does not have.
    """

    id = "missing-capability"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.cause == "capability":
            return facts.decision
        return None


class SandboxEscalation(SettlementRule):
    """The agent asked for the launcher's host, which is always reviewed.

    A placement rather than a permission, and the one crossing that is never
    unprompted on request: ``allow outside`` exists, but only as a rule's own
    declaration about an operation nobody had to ask about. An agent asking
    to leave gets a question, whatever the effect was inside — because what
    the reviewer is being shown is not "may this run" but "may this run
    *there*", and the second question has a different answer.

    A refusal is not moved by it. Combined with a decision escalation the
    refusal has already become a question by the time this row is read, so
    ``escalate[decision,sandbox]`` over an ordinary deny reaches ask outside
    and ``escalate[sandbox]`` alone over the same deny stays refused.

    Where no automated channel exists the question is still worth asking, so
    long as somebody can carry the answer out: an approved operation is
    rendered for the launcher's owner to run and confirm. Only where neither
    a channel nor a person is available does this fall through to
    :class:`TrappedPlacement` below.
    """

    settles = False
    id = "sandbox-escalation"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if not facts.asks("sandbox"):
            return None
        decision = facts.decision
        if decision.effect == "deny":
            return None
        if decision.sandbox == "outside" and decision.effect == "ask":
            return decision.revised(reason=decision.reason + REDUNDANT_SANDBOX)
        assert facts.escalation is not None
        prefix = ESCALATED_PREFIX.format(reason=facts.escalation.reason)
        return decision.revised(
            effect="ask",
            reason=prefix + decision.reason + facts.escalation.notice(),
            sandbox="outside",
            escalated=facts.escalation.reason,
            purpose=decision.purpose or "policy_override",
            abstention=None,
        )


class DecisionEscalation(SettlementRule):
    """A stated reason turns anything not already permitted into a question.

    The agent asked to be judged, so a refusal becomes the question it asked
    for, carrying the reason it gave — the person sees intent at the moment
    of judgement rather than a bare rule name. An abstention becomes the same
    question, at the placement it already had, because an operation nobody
    judged is exactly what a reviewer is for.

    Nothing is done to a verdict that already permits, beyond saying so: a
    stated reason over something permitted would buy a prompt for nothing,
    and an agent that wrote one deserves to learn it was unnecessary rather
    than to have it silently work.
    """

    settles = False
    id = "decision-escalation"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if not facts.asks("decision"):
            return None
        assert facts.escalation is not None
        decision = facts.decision
        notice = facts.escalation.notice()
        if decision.effect == "allow":
            return decision.revised(
                reason=decision.reason + REDUNDANT_DECISION + notice,
                visibility="notice",
            )
        prefix = ESCALATED_PREFIX.format(reason=facts.escalation.reason)
        return decision.revised(
            effect="ask",
            reason=prefix + decision.reason + notice,
            escalated=facts.escalation.reason,
            purpose=decision.purpose or "policy_override",
            cause=None,
            abstention=None,
        )


class TrappedPlacement(SettlementRule):
    """An operation that has to reach the host where nothing can carry it.

    Not advice: run inside, it fails on whatever it touches first, and the
    failure reads as a broken repository rather than as a boundary. Refused
    here as a capability-blocked refusal — no approval builds a channel, and
    a question whose every answer leaves the operation with nowhere to go is
    a question nobody should be shown.

    Reached after both escalation rows, so an agent that asked for the host
    is told the profile has none rather than told its request was denied on
    the merits.
    """

    id = "trapped-placement"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.sandbox != "outside":
            return None
        if facts.host_executor:
            return None
        if facts.decision.effect == "ask" and facts.human_execution:
            return None
        return facts.decision.revised(
            effect="deny",
            reason=SANDBOX_TRAPPED_REASON,
            cause="capability",
            capability="host_executor",
        )


class UnleasedWrite(SettlementRule):
    """A write the measured boundary does not cover, wherever the session sits.

    The lease is what a launch actually mounted writable, and it is a snapshot:
    the read-only overlays a contained launch punches over its siblings are
    enumerated when the container starts, and a container's mount namespace is
    fixed from then on. So a worktree cut *after* that gets the writable base
    with no overlay over it, and a mount table cannot close that -- there is no
    remount to make.

    Which is why the judgement does. The mount table was never the barrier
    here: the shared administrative directory is mounted writable on purpose,
    because no session could cut a worktree otherwise, and what guards the keys
    inside it is a rule holding an approval question against them by name. This
    is the same arrangement applied to the same gap.

    Read against ``allow`` and ``defer`` only. A judged refusal is somebody's
    answer and asking about it would be offering to overturn it, and an ask
    already reaches a reviewer -- who is shown the operation, and can see for
    themselves where it points.
    """

    id = "unleased-write"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if not facts.unleased or facts.decision.effect not in ("allow", "defer"):
            return None
        return facts.decision.revised(
            effect="ask",
            reason=(
                f"{facts.decision.reason}. This writes to "
                f"{', '.join(facts.unleased)}, which the boundary this launch "
                "measured does not cover — so nothing here confines the write "
                "and no capture of this session holds what it replaces"
            ),
            purpose="unrecovered_local_mutation",
            # Named, because the verdict this replaces was reached by the
            # vocabulary finding nothing to say and carries no id of its own.
            # An ask that names no rule is one nobody can write a case for.
            rule=self.id,
            abstention=None,
        )


class ProviderNative(SettlementRule):
    """A rule looked and handed the decision to the provider's own mode.

    The one abstention that survives, and the only verdict under which the
    session behaves exactly as it would with Lup absent. It settles rather
    than rewrites so that no row below can turn a deliberate handoff into a
    refusal for want of anybody having looked — somebody looked, and what
    they decided was that this is the provider's to answer.
    """

    id = "provider-native"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.abstention == "provider_native":
            return facts.decision
        return None


class RecoveredLoss(SettlementRule):
    """A question about a loss a proven capture already put somewhere safe.

    The rules guard *the direction that removes something no second attempt
    restores*. What a second attempt restores is a fact about the session and
    not about the operation, so a rule states the capture its question was
    about and this row asks whether that capture was actually taken.

    Settled as a **permission**, not a deferral. Nothing about the provider's
    own mode is involved: this policy has positively established that the
    loss it was protecting against did not happen, and an operation whose
    every reason to interrupt has been answered is authorized rather than
    handed on. Deferring instead would make the outcome depend on which mode
    the session happened to be in, for a fact that has nothing to do with the
    session's mode.

    It discharges *only* local loss. An operation that also rewrites a
    production file, touches a protected path, reads a credential, or reaches
    a remote keeps its question in full, which is what
    :func:`~lup.policy.kernel.decision.recovery_dischargeable` reads over the
    contributing findings rather than over their join.

    A stated reason keeps its question either way: the escalation rows above
    have already turned it into one, and answering the agent's own request
    with a permission would drop both the question and the reason given for
    it. A capture that was attempted and failed keeps the question too, and
    says which it was, because "nobody captured this" and "the capture did
    not work" are different things to tell a person.
    """

    id = "recovered-loss"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.effect != "ask" or facts.escalation is not None:
            return None
        if not recovery_dischargeable(facts.decision):
            return None
        match facts.checkpoint:
            case "complete":
                held = "the affected paths are captured and restorable"
            case "failed":
                return facts.decision.revised(
                    reason=facts.decision.reason + CHECKPOINT_FAILED,
                    visibility="notice",
                )
            case _:
                return None
        return facts.decision.revised(
            effect="allow",
            reason=facts.decision.reason + RECOVERED_LOSS.format(held=held),
            purpose=None,
            visibility="notice",
        )


class UnreachableReviewer(SettlementRule):
    """A question in a session no eligible reviewer can be reached from.

    Refused, and the direction matters more than anything else in this order.
    Somebody looked at this operation and decided a person should see it; no
    person can be reached; so it does not happen. Handing it to the boundary
    instead would say the opposite — that a question nobody could answer is a
    question that did not need asking — and a boundary that confines an
    operation does not review it.

    Measured before the refusal existed: in a headless contained session a
    remote ref deletion came back an unprompted allow, and an escalation
    marker, whose entire purpose is to summon the person this path decided
    was unnecessary, granted exactly what the table refused.

    Unjudged work does not reach here and is unaffected. It never becomes an
    ask in a session that can reach nobody, because the row that would make
    one reads the same fact — so the boundary still carries what nobody
    classified, which is the whole of what containment buys the lattice, and
    what it does not buy is a way past a question somebody meant.

    The last resort and not the ordinary path: a detached session reaches a
    person through the durable relay, and a worker reaches its supervisor
    through the same relay. ``reviewable`` is false only where neither exists.
    """

    id = "unreachable-reviewer"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.effect == "ask" and not facts.reviewable:
            return facts.decision.revised(
                effect="deny",
                reason=facts.decision.reason + NO_REVIEWER + facts.hint,
                cause="deliberate",
            )
        return None


class ContainedEffects(SettlementRule):
    """Nobody judged it, and everything it can do is confined: run it inside.

    The practical default for odd local work. Reading ``/etc/passwd``,
    listing ``/proc``, searching the session's own home, running a broad
    ``find`` — each is suspicious in the abstract and none of it is worth a
    person's attention when the environment it observes is the contained one
    and no independent rule asks or denies. A host path that is not there
    fails inside with a boundary diagnostic naming the sandbox escalation
    that would reach it, which is a better answer than a question, because
    the agent usually did not need the host and finds that out itself.

    Settles to ``allow inside`` rather than deferring, so the placement is
    Lup's and holds however permissive the session's own mode is. That is the
    whole difference between containing something and hoping the provider
    contains it.
    """

    id = "contained-effects"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.effect != "defer" or not facts.bounded():
            return None
        return facts.decision.revised(
            effect="allow",
            reason=facts.decision.reason + CONTAINED_READ,
            sandbox="inside",
            abstention=None,
        )


class UnjudgedAmbientPolicy(SettlementRule):
    """Nobody judged it and no boundary confines it: the profile answers.

    Two answers, both declared rather than inferred. ``ask`` keeps unjudged
    work visible, and is the default because what a reviewer is shown is
    exactly what will run — the operation was read and found well-formed, and
    only the vocabulary was silent. ``defer`` is a profile deliberately
    handing the long tail to provider-native judgement.

    A session that can reach nobody creates no question here. The row above
    that rewrites an unanswerable ask is read before this one and so cannot
    see a question this one makes; reading the same fact here is what keeps
    the two from needing to be ordered around each other in both directions.

    Only the legible half reaches either answer. An operation the classifier
    could not *read* — an unresolved expansion, a substitution it cannot see
    into, an operator its parser does not carry — is refused however many
    reviewers are present, because a question about text the policy could not
    parse is one the person cannot answer either: they would approve
    ``cat x ;& rm -rf ~`` on the strength of the ``cat``.
    """

    id = "unjudged-ambient"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.effect != "defer":
            return None
        if not facts.decision.unlisted:
            return None
        if facts.unjudged_ambient == "defer":
            return facts.decision.revised(abstention="provider_native")
        if not facts.reviewable:
            return None
        return facts.decision.revised(
            effect="ask", purpose="policy_override", abstention=None
        )


class Unreadable(SettlementRule):
    """Nothing judged it, nothing confines it, and nobody can read it.

    The refusal names the recipe rather than only the wall — reshape it into
    the allowed vocabulary, or say why it has to be this shape — because work
    nobody classified is work somebody has to look at, and an agent told only
    "no" looks at nothing.
    """

    id = "unreadable"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.effect != "defer":
            return None
        return facts.decision.revised(
            effect="deny",
            reason=facts.decision.reason + facts.hint,
            cause="unreadable",
            abstention=None,
        )


class JudgedRefusal(SettlementRule):
    """A rule refused this, and no boundary rescues a judged deny.

    The distinction the whole order rests on: unjudged work is refused for
    want of anybody having looked, and a boundary answers that. A judged deny
    is somebody's answer, and running it confined would still be running it.
    """

    id = "judged-refusal"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        if facts.decision.effect != "deny":
            return None
        return facts.decision.revised(
            reason=facts.decision.reason + facts.hint,
            cause=facts.decision.cause or "deliberate",
        )


class Standing(SettlementRule):
    """Whatever reached here stands: a permission, or an answerable question."""

    id = "standing"

    def reached(self, facts: SettlementFacts) -> KernelDecision | None:
        return facts.decision


SETTLEMENT_ORDER: list[SettlementRule] = [
    HardProhibition(),
    MissingCapability(),
    DecisionEscalation(),
    SandboxEscalation(),
    TrappedPlacement(),
    UnleasedWrite(),
    ProviderNative(),
    RecoveredLoss(),
    UnreachableReviewer(),
    ContainedEffects(),
    UnjudgedAmbientPolicy(),
    Unreadable(),
    JudgedRefusal(),
    Standing(),
]
"""Every row, in the order they are read.

Precedence is position. The two unanswerable rows come first, because nothing
below them could change their answer. Decision escalation precedes sandbox
escalation so that a combined request over an overrideable refusal has
already become a question by the time the placement moves — which is exactly
the difference between ``escalate[decision,sandbox]`` reaching the host and
``escalate[sandbox]`` alone staying refused.

``UnleasedWrite`` sits above ``RecoveredLoss`` for the reason that row exists:
a proven capture settles a loss to a permission, and a capture of *this*
session does not hold what lies outside the boundary it measured. Read the
other way round, an undo reference covering the checkout would discharge a
question about a tree it never held. ``Standing`` is last because it speaks
for everything.
"""


def settle(
    facts: SettlementFacts, order: list[SettlementRule] = SETTLEMENT_ORDER
) -> KernelDecision:
    """Read the order over one classified verdict and return what it settles.

    The same pass serves preliminary and dynamic settlement. What differs is
    the evidence in ``facts`` — a preliminary pass carries ``absent`` capture
    evidence and reaches its question, a dynamic pass carries what was
    actually measured — so no row has to know which of the two it is in, and
    neither pass can apply a rule the other does not.
    """
    for rule in order:
        reached = rule.reached(facts)
        if reached is None:
            continue
        if rule.settles:
            return reached
        facts = facts.rewritten(reached)
    return facts.decision


def settlement_rule_ids() -> list[str]:
    """Every row's stable id, in order, for the reference the docs render."""
    return [rule.id for rule in SETTLEMENT_ORDER]
