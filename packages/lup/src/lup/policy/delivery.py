"""Which mechanism a provider delivers each semantic guarantee with.

A semantic policy is only as real as its delivery. "Provider auto-mode cannot
answer a Lup ask" is a claim about a *mechanism* — some specific thing the
adapter does that makes it so — and a claim with no mechanism behind it reads
identically to one with a mechanism that stopped working.

So each guarantee is declared here with the mechanism that carries it, and
with how that mechanism is *known*. The second half is the part that is
usually skipped and the part that matters: vendor documentation is evidence
and not proof of delivered behaviour, and a fact carried forward from a prior
session is neither. A guarantee no mechanism carries is stated as absent
rather than omitted, because an incomplete map reads exactly like a complete
one.

What is deliberately not here is a claim to have run the experiments, or the
facts themselves. Nothing in this module observes a provider, and no
provider's own words appear in it: each adapter states its own facts, in its
own spellings, against this shared vocabulary — which is what makes two
adapters' answers comparable rather than two files nobody compares.

The vocabulary's job is to be the thing both answer, so the gap between
"documented" and "measured" stays visible to whoever next has a pinned binary
in front of them.
"""

from typing import Literal

from pydantic import BaseModel

type Guarantee = Literal[
    "ask_survives_auto_mode",
    "exact_call_resumes",
    "defer_is_transparent",
    "inside_placement_enforced",
    "outside_placement_carried",
    "rejection_receipt",
    "hook_failure_is_closed",
]
"""One semantic promise the product contract makes, named so it can be checked.

Each is a sentence somebody could otherwise believe without anything being
true: that a Lup question survives an auto-accepting session, that the call a
person approved is the call that runs, that a deferral leaves no trace, that
containment holds, that a crossing reaches the host, that a refusal is
recorded for what it is, and that a hook that fails does not fail open.
"""

type Standing = Literal["measured", "documented", "assumed", "absent"]
"""What the belief about a mechanism rests on, which is never left implicit.

``measured`` is an observation of the pinned binary this repository records.
``documented`` is the vendor saying so, which is evidence and not proof — a
documented behaviour that a build changed reads the same as one that did not.
``assumed`` is neither, and is the standing a claim has when somebody carried
it forward from a prior session. ``absent`` says no mechanism carries it,
which is a fact worth stating rather than a row worth omitting.
"""


class DeliveryFact(BaseModel, frozen=True):
    """One guarantee, the mechanism that carries it, and how that is known.

    ``fallback`` is what happens where the mechanism is not there. It is
    required prose rather than an optional note, because a guarantee with no
    stated fallback is one whose absence nobody has thought about — and the
    thinking is the whole value: fail-closed and fail-open look identical
    until somebody writes down which this is.
    """

    guarantee: Guarantee
    provider: str
    mechanism: str
    standing: Standing
    fallback: str

    def carried(self) -> bool:
        """Whether any mechanism at all carries this guarantee here."""
        return self.standing != "absent"

    def line(self) -> str:
        """One row a reader can act on, standing first because it qualifies the rest."""
        return f"{self.provider}/{self.guarantee} [{self.standing}]: {self.mechanism}"


def delivery_gaps(facts: list[DeliveryFact]) -> list[DeliveryFact]:
    """Every guarantee no mechanism carries here.

    Not a failure list: two of these are absent on both providers because no
    provider offers the mechanism at all, and the fallback is the design. What
    it is is the list somebody reads before believing a guarantee holds.
    """
    return [fact for fact in facts if not fact.carried()]


def unmeasured(facts: list[DeliveryFact]) -> list[DeliveryFact]:
    """Every carried guarantee resting on documentation or on nothing.

    The queue for whoever next has a pinned binary. Documentation is evidence
    and a build that changed reads the same as one that did not, so this is
    the difference between a contract and a hope — kept visible rather than
    collapsed into "the adapter handles it".
    """
    return [
        fact
        for fact in facts
        if fact.carried() and fact.standing in ("documented", "assumed")
    ]
