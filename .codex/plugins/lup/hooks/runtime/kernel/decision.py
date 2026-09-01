"""The verdict vocabulary every kernel module returns."""

from typing import Literal

from .semantics import (
    AbstentionPurpose,
    Capability,
    RefusalCause,
    ReviewPurpose,
    ReviewerRequirement,
    Visibility,
)


type DecisionEffect = Literal["allow", "ask", "deny", "defer"]
"""What the provider is told, and the whole of what it may be told.

Four values, and the boundary between them is where native autonomy begins:

* ``allow`` is positive authority. Lup authorizes this exact operation, so no
  further permission decision is needed and the provider's auto-mode has
  nothing to add. It is not a request for the provider to approve.
* ``ask`` is a Lup-owned review requirement. Provider auto-mode cannot
  satisfy it, because the point of the question is that a person sees this
  moment while it is still happening.
* ``deny`` is a prohibition.
* ``defer`` is the only value that hands the decision over, and the only one
  under which the session behaves exactly as it would with Lup absent.

Nothing else joins them. Everything Lup knows *about* one of these four —
who may review, where it runs, what would restore it, why it was refused —
is a separate fact in :mod:`lup.policy.kernel.semantics`, because folding
another value in here is how a runtime ends up being told something it has no
way to act on.
"""

type CheckpointRequirement = Literal["targeted", "boundary_wide", "unrecoverable"]
"""What capture would put back what an operation destroys locally.

An approval question over local loss exists because the loss is permanent.
Naming the capture that makes it impermanent is naming the condition under
which the question stops being worth a person's attention — and, proven,
settles the operation to ``allow`` rather than merely to the provider's own
gate. Proof is the whole of it: a snapshot reference is not evidence, and
:class:`~lup.policy.kernel.findings.CheckpointEvidence` is what a rule's
requirement is discharged against.

* ``targeted`` — every path this operation can affect resolves statically, so
  a capture of exactly those paths covers the whole loss. ``rm build/out``,
  ``git restore``, a redirection into a named file.
* ``boundary_wide`` — variables, globs, substitutions, or a directory walk
  prevent an exact footprint, so only a capture of every precious writable
  root covers it. The wider capture is what the opacity costs, not a reason
  to refuse the operation.
* ``unrecoverable`` — no capture reaches it. A remote ref, a published
  artifact, an issue somebody read, a command whose argument is another
  command. Recovery has nothing to say and the question stands.

``unrecoverable`` is the default, and the default is the safety of the axis:
a rule nobody annotated keeps asking, and an annotation is what relaxes it.
The other direction would make every rule anybody forgot into a grant.

A row whose guarded forms do not agree takes the weakest of them. ``sort``
guards ``-o``, which writes a file, beside ``--compress-program``, which runs
one; the row says ``unrecoverable``, because a reader of the verdict cannot
tell which flag brought it.
"""

type SandboxPlacement = Literal["inside", "ambient", "outside"]
"""Where an operation runs, which is a different question from who decides it.

The boundary these name is the *outer containment boundary* — the profile's
own, whatever delivers it — and never merely a provider's per-call sandbox.
That native sandbox is one adapter mechanism for spelling ``inside``; a
generated artifact may also spell it through a provider-native permission
field. Neither is a second semantic placement, and ``outside`` never means
"out of the native sandbox but still in the container".

* ``inside`` — execute inside the containment boundary, whatever mode the
  session is in. Provider auto-mode does not move it.
* ``ambient`` — execute wherever the session already lives. The default,
  because saying nothing about placement is what almost every verdict means.
* ``outside`` — execute on the launcher's host, through the trusted host
  executor. Unprompted under ``allow``; under ``ask``, only after exact
  approval.

Only ``allow`` and ``ask`` carry authoritative placement. ``deny`` never
executes, so placement is moot, and ``defer`` supplies no Lup placement at
all — supplying one would be Lup deciding half of a decision it just handed
over.
"""

# lup: ignore[constant-declaration] — the words this gate says, in a kernel
# compiled hermetically into a bare dispatcher that takes no arguments
SANDBOX_ESCAPE_NOTICE = " — this will run on the host, outside the boundary"
"""What an approval question adds when the call it approves also leaves."""

# lup: ignore[constant-declaration] — the recipe a diagnostic hands the agent;
# its whole value is being the same words every time
SANDBOX_ESCALATION_RECIPE = (
    " — this ran inside the containment boundary; if it genuinely needs the"
    " launcher's host, resubmit with a leading"
    " '# lup: escalate[sandbox]: <why>' line"
)
"""How an operation that found the boundary insufficient asks to leave it.

Carried on the diagnostic rather than appended to every permitted call. A
context line per allowed operation is how a channel meant for what matters
stops being read, and the moment the agent needs this is the moment something
inside actually failed for want of the host.
"""

# lup: ignore[constant-declaration] — the refusal a call with nowhere to run is
# stopped with, naming the missing capability rather than the wall
SANDBOX_TRAPPED_REASON = (
    "this has to run on the launcher's host, and this profile declares no host"
    " executor — no approval can create the channel, so the operation is"
    " refused rather than run somewhere it was not authorized to run"
)
"""Why an operation needing the host is refused where no channel reaches it.

A capability-blocked refusal, not a question. Offering the question would
spend a person's attention on a decision that changes nothing: approving it
would still leave the operation with nowhere to go, and running it inside
would run something the placement said must not run there — failing on
whatever it touched first, and misreporting the boundary as a broken
repository.
"""

# lup: ignore[library-default] — the stdlib the kernel actually imports; the hermetic guarantee it exists to hold
KERNEL_IMPORT_ALLOWLIST = (
    "ast",
    "collections",
    "collections.abc",
    "difflib",
    "fnmatch",
    "functools",
    "io",
    "pathlib",
    "posixpath",
    "re",
    "tokenize",
    "typing",
    "urllib.parse",
)
# The five below are sentences and one sentinel the kernel's own decisions
# carry: each is declared beside the verdict that returns it, so a caller
# passing different words would be returning a different verdict.
# lup: ignore[constant-declaration] — refusal wording, declared with its verdict
ESCALATE_HINT = (
    " — reshape the command into the allowed vocabulary, or resubmit with a"
    " leading '# lup: escalate[decision]: <why>' line to request approval"
)
# lup: ignore[constant-declaration] — refusal wording
RESHAPE_HINT = " — reshape the command into the allowed vocabulary"
# lup: ignore[constant-declaration] — refusal wording, declared with its verdict
RELAY_HINT = (
    " — reshape the command into the allowed vocabulary, or ask for the gate"
    " with `request_allowance`, which reaches whoever is watching this run"
)
"""What a reviewed worker is told, which is not what a headless run is told.

Both are non-interactive and only one of them is alone. A resolver worker
holds a question mailbox: it can put the ask to the human supervising the
run and carry on from where it stopped when the answer lands. Telling it to
reshape the command is telling it the route it has does not exist, and
measured, it does what anybody would — it queues a *material question*
instead, which parks the whole run on a decision nobody needed to make.

A genuinely headless run has no such channel and still gets
:data:`RESHAPE_HINT`, because naming a route that is not there is the same
failure pointed the other way.
"""
# lup: ignore[constant-declaration] — refusal wording, declared with its verdict
SUBSTITUTION_REASON = (
    "command substitution is denied — run the inner command in its own call"
    " and splice its literal output, or read it through <(...) or a pipe"
)
# lup: ignore[constant-declaration] — refusal wording, declared with its verdict
BACKTICK_REASON = (
    "backtick substitution is denied — use $(...) so the inner command"
    " can be classified"
)
# lup: ignore[constant-declaration] — a spelling chosen to sit outside identifier
# space, which is the property the substitution proof below rests on
SUBSTITUTION_SENTINEL = "$~sub~"
"""Spliced into a word where a real ``$(...)`` stood.

The spelling sits outside identifier space, so no variable binding can
instantiate it, and a quoted literal that happens to match only makes the
word read as opaque — the conservative direction.
"""


def sandbox_escaped(sandbox: SandboxPlacement) -> bool:
    """Whether a placed operation runs on the launcher's host.

    One function rather than a comparison spelled at each of the boundaries
    that render the crossing — both hook factories, the in-process renderer,
    and each compiled dispatcher — because a condition spelled out at four
    sites is one that can be spelled differently at four sites, which is how
    a placement came to be honoured on one path and stripped on the other.
    """
    return sandbox == "outside"


class KernelDecision:
    """One settled verdict, and every orthogonal fact settled alongside it.

    The first four fields are what a provider is told. The rest are what Lup
    knows about that answer, and each is a separate axis because each has a
    different answerer: a checkpoint does not consent to a release, an
    approval does not build a host channel, and a rule id is not a review
    purpose. Composing them into one enum is what made a verdict unreadable
    at exactly the moment somebody needed to know why it happened.
    """

    effect: DecisionEffect
    reason: str
    sandbox: SandboxPlacement
    escalated: str
    """Why the agent said this operation was worth putting to a reviewer.

    Carried as its own field rather than left readable in the reason, because
    a host with no reviewer has somewhere else to send it and needs to know
    that this particular refusal is one somebody asked for. Sniffing the
    reason text for a prefix would make every caller re-derive what the
    marker already stated.

    It survives the collapse to ``deny``: the whole point is that the agent's
    stated intent outlives the refusal, so whoever reads the relay sees why
    the agent thought the operation was worth running.
    """
    checkpoint: CheckpointRequirement
    """What capture would put back what this operation destroys locally.

    The one axis that says nothing about this verdict: it says what a session
    carrying that capture could settle differently. It survives every effect,
    because it is a property of the operation rather than of the verdict
    reached about it.
    """
    unlisted: bool
    """Whether this deferral is only the vocabulary having no row for the call.

    Two very different things reach ``defer``, and a session with no boundary
    beneath it has to tell them apart. This one is the vocabulary staying
    silent: the kernel read the command, found it well-formed, and nothing
    named it. Every other deferral is the kernel declining to read — an
    unresolved expansion, a substitution it cannot see into, an operator its
    parser does not carry — or a form some rule deliberately left out.

    Only the silent one is a question a human can answer, because it is the
    only one where what the human is shown is what will run. Asking about
    text the policy itself could not parse would show them `cat x` and run
    `rm -rf ~`, so those keep refusing however many reviewers are present.
    """
    reviewer: ReviewerRequirement
    """Who may answer, on the one effect that asks anybody. ``human_only``
    unless a rule deliberately opted its question into the supervisor chain."""
    purpose: ReviewPurpose | None
    """Which kind of decision a question is, or ``None`` where it asks nobody."""
    visibility: Visibility
    """Whether an operation that did not interrupt should still be surfaced."""
    cause: RefusalCause | None
    """Why a refusal was reached, or ``None`` where nothing was refused."""
    capability: Capability | None
    """Which runtime guarantee was missing, on a capability-blocked refusal.

    Set only alongside ``cause="capability"``, and the pair is what says the
    refusal is unanswerable: a reviewer cannot approve a channel into being,
    so the operation is refused rather than parked on a question whose answer
    changes nothing.
    """
    abstention: AbstentionPurpose | None
    """Why a ``defer`` declined to finalize, or ``None`` on any other effect.

    ``provider_native`` is the deliberate handoff and the only abstention that
    survives to the provider. ``boundary_settle`` is the classifier lacking a
    judgement the boundary still has facts about, and settlement resolves it
    rather than passing it on — which is the distinction that stopped a parser
    gap from silently inheriting provider auto-mode.
    """
    rule: str
    """The stable id of the rule that reached this verdict, or ``""``.

    Stable across rewordings, because it is what an audit counts by and what a
    person answering a repeated question is pointed at. A reason is prose and
    a rule id is an identifier; a taxonomy built on the first is a taxonomy of
    how sentences were phrased.
    """
    hard: bool
    """Whether this prohibition is one no reviewer may override.

    Almost none are. An ordinary refusal is a rule's judgement, and a rule's
    judgement is exactly what a person with more context may overrule — which
    is what decision escalation exists for. A hard prohibition is a policy
    invariant instead: escalating one produces the same refusal, because the
    thing being asked for is not the kind of thing an approval creates.
    """
    findings: tuple["KernelDecision", ...]
    """The rule verdicts that composed into this one, empty where this is one.

    A composed verdict has to answer questions its own fields cannot: whether
    *every* surviving reason to ask is one a proven capture retires, which is
    the difference between recovery settling an operation to allow and
    recovery quietly discharging a code review that happened to travel beside
    it. Keeping the parts is how that stays answerable, and it is what an
    audit reconstructs a decision from.
    """
    evaluator: str
    """The stable id of the evaluator that produced it, or ``""``.

    Which classifier looked, as against which rule it applied — the shell
    vocabulary, the edit gate, the fetch scopes, the effect grammar. Two rules
    may share an evaluator and one rule never spans two.
    """

    def __init__(
        self,
        effect: DecisionEffect,
        reason: str = "",
        sandbox: SandboxPlacement = "ambient",
        escalated: str = "",
        checkpoint: CheckpointRequirement = "unrecoverable",
        unlisted: bool = False,
        reviewer: ReviewerRequirement = "human_only",
        purpose: ReviewPurpose | None = None,
        visibility: Visibility = "quiet",
        cause: RefusalCause | None = None,
        capability: Capability | None = None,
        abstention: AbstentionPurpose | None = None,
        hard: bool = False,
        findings: tuple["KernelDecision", ...] = (),
        rule: str = "",
        evaluator: str = "",
    ) -> None:
        if effect not in ("allow", "ask", "deny", "defer"):
            raise ValueError(f"invalid kernel decision effect {effect!r}")
        if sandbox not in ("inside", "ambient", "outside"):
            raise ValueError(f"invalid kernel decision placement {sandbox!r}")
        if checkpoint not in ("targeted", "boundary_wide", "unrecoverable"):
            raise ValueError(f"invalid kernel decision checkpoint {checkpoint!r}")
        self.effect = effect
        self.reason = reason
        self.escalated = escalated
        self.checkpoint = checkpoint
        self.unlisted = unlisted
        self.reviewer = reviewer
        self.purpose = purpose
        self.visibility = visibility
        self.cause = cause
        self.capability = capability
        self.abstention = abstention
        self.hard = hard
        self.findings = findings
        self.rule = rule
        self.evaluator = evaluator
        # Only a verdict this policy actually reached is placed: a refusal is
        # not softened by where the operation would have run, and a deferral
        # hands the whole question over, placement included.
        self.sandbox = sandbox if effect in ("allow", "ask") else "ambient"

    def revised(self, **changes: object) -> "KernelDecision":
        """This verdict with named fields replaced and the rest carried over.

        Every settlement row rewrites one or two fields and must not drop the
        ten it is not about — which is exactly what a constructor call listing
        the fields a row happens to remember does. Spelled once here so a row
        says what it changes and nothing says what it preserves.
        """
        fields = {
            "effect": self.effect,
            "reason": self.reason,
            "sandbox": self.sandbox,
            "escalated": self.escalated,
            "checkpoint": self.checkpoint,
            "unlisted": self.unlisted,
            "reviewer": self.reviewer,
            "purpose": self.purpose,
            "visibility": self.visibility,
            "cause": self.cause,
            "capability": self.capability,
            "abstention": self.abstention,
            "hard": self.hard,
            "findings": self.findings,
            "rule": self.rule,
            "evaluator": self.evaluator,
        }
        fields.update(changes)
        return KernelDecision(**fields)  # pyright: ignore[reportArgumentType]

    def placed(self, escapable: bool) -> "KernelDecision":
        """This verdict as the runtime about to render it will carry it out.

        ``escapable`` is whether this runtime can put an operation outside the
        containment boundary at all. Where it cannot, a placement it will not
        honour must not be spelled, or the verdict reads as escaped while the
        operation runs contained — so the plain effect is rendered instead and
        :class:`~lup.policy.kernel.settlement.TrappedPlacement` is what refuses
        the one case where that substitution would be wrong.

        An approval question over an operation that also leaves asks the
        person two things, so the reason says both. Neither reaches a refusal
        or a deferral: those arrive with the placement already collapsed.
        """
        if not escapable:
            return self.revised(sandbox="ambient")
        if self.effect == "ask" and self.sandbox == "outside":
            return self.revised(reason=self.reason + SANDBOX_ESCAPE_NOTICE)
        return self


def unjudged(reason: str) -> KernelDecision:
    """One machinery bail-out: the kernel could not read this, so it abstains.

    A ``boundary_settle`` abstention, never a handoff. The classifier has no
    final judgement and the boundary still has facts about the operation, so
    settlement resolves it from those facts rather than passing it to the
    provider's own mode — which is what a gap in the parser must never buy.
    """
    return KernelDecision("defer", reason, abstention="boundary_settle")


def unlisted(reason: str) -> KernelDecision:
    """The same abstention, from the vocabulary simply naming nothing here.

    Separate from :func:`unjudged` because only this one is answerable. The
    command was read and is well-formed; no row speaks about it. A session
    with a reviewer puts that to them, exactly as a decision escalation
    already does, rather than refusing work whose only fault is being new.
    """
    return KernelDecision("defer", reason, unlisted=True, abstention="boundary_settle")


def handed_over(reason: str, rule: str = "", evaluator: str = "") -> KernelDecision:
    """A rule looked, and decided the provider's own mode should answer.

    The one abstention that survives to the provider. Edit size is the shape:
    a large ordinary edit is exactly what a native auto-accept mode exists
    for, and interposing here would replace a decision an operator already
    made. Distinct from :func:`unjudged` in the field rather than the wording,
    because settlement reads the field and a reader of two similar sentences
    reads neither.
    """
    return KernelDecision(
        "defer", reason, abstention="provider_native", rule=rule, evaluator=evaluator
    )


def capability_blocked(
    reason: str, capability: Capability, rule: str = "", evaluator: str = ""
) -> KernelDecision:
    """The runtime cannot deliver a guarantee this operation requires.

    Rendered as ``deny`` because a refusal is what a provider can act on, and
    carrying the typed cause because a refusal that reads as a policy
    judgement sends the agent to argue with a rule instead of to the missing
    channel. Approval and decision escalation cannot manufacture a capability,
    so neither reaches it.
    """
    return KernelDecision(
        "deny",
        reason,
        cause="capability",
        capability=capability,
        rule=rule,
        evaluator=evaluator,
    )


def contributions(decision: KernelDecision) -> tuple[KernelDecision, ...]:
    """The rule verdicts behind one settled verdict, which may be itself.

    A composed verdict keeps its parts and a single rule's verdict is its own
    only part. Spelled once so a settlement row asking "what are all the
    reasons this asks" cannot accidentally ask it of a composed verdict's
    summary fields, which carry the join rather than the reasons.
    """
    return decision.findings or (decision,)


def recovery_dischargeable(decision: KernelDecision) -> bool:
    """Whether a proven capture retires every surviving reason this asks.

    The question recovery is allowed to answer, and the whole of it. Local
    loss a capture puts back is not worth a person's attention; a code
    review, a protected path, an external effect, or a credential read
    travelling in the same operation is worth exactly as much attention as it
    was before, and an operation carrying both keeps its question.

    Read over the contributions rather than the join, because the join
    reports the strongest effect and says nothing about how many reasons
    reached it — which is how a recoverable deletion beside a full-file
    rewrite would have discharged the rewrite.
    """
    asking = [part for part in contributions(decision) if part.effect == "ask"]
    if not asking:
        return False
    return all(
        part.purpose == "unrecovered_local_mutation"
        and part.checkpoint != "unrecoverable"
        for part in asking
    )
