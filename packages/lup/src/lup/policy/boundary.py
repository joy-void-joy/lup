"""What a profile promises about where an operation runs, and what it delivers.

A placement is a semantic statement — inside the containment boundary, on the
launcher's host — and a statement nothing carries out is worse than no
statement at all: the operation runs somewhere it was not authorized to run,
fails on whatever it touched first, and the failure reads as a broken
repository rather than as a boundary. So the declaration and the delivery are
one type with two halves, and the second half is *measured* rather than
asserted.

The distinction that makes it worth a module: **configuration intent is not
capability evidence.** A profile that asks for a containment boundary and a
runtime whose boundary failed to start both read as "sandbox: on" if the only
thing consulted is the configuration. What separates them is a sentinel a
launch actually observed, which is what :class:`CapabilityEvidence` carries.

Capabilities are required or optional, and the two fail differently on
purpose. A missing required capability fails the launch, because a session
that cannot deliver its own boundary is not the session anybody asked for. A
missing optional one lets the launch proceed and capability-blocks the
operations that depend on it — refused with a typed cause, never asked about,
because no reviewer approves a channel into existence.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from lup.policy.kernel.semantics import Capability, UnjudgedAmbient


class CapabilityEvidence(BaseModel, frozen=True):
    """What a launch actually observed about one capability.

    ``delivered`` is the measurement and ``detail`` is what was measured —
    the sentinel a contained command printed, the store path a write
    succeeded at, the relay's own health reply. Both are recorded because a
    capability reported present with nothing behind it is exactly the shape
    this type exists to refuse: the diagnostic a person reads has to name
    what was tried, or the only available next step is to try it again by
    hand.
    """

    capability: Capability
    delivered: bool
    detail: str = ""

    def diagnosis(self) -> str:
        """One line naming what was measured and how it came out."""
        outcome = "delivered" if self.delivered else "not delivered"
        return (
            f"{self.capability}: {outcome}{f' — {self.detail}' if self.detail else ''}"
        )


class CapabilityRequirement(BaseModel, frozen=True):
    """One capability a profile depends on, and how badly.

    ``required`` is the whole of the difference, and it is a product decision
    rather than a technical one: a profile whose containment is the point
    requires ``inside_placement`` and one that merely prefers it does not.
    Stating it per profile is what lets both exist without either pretending
    to be the other.
    """

    capability: Capability
    required: bool = True
    reason: str = ""


class ExecutionBoundary(BaseModel, frozen=True):
    """The canonical declaration one profile compiles into every adapter.

    One declaration rather than one per provider: every intended difference
    between Claude and Codex is a rendering decision in an adapter, so a fact
    stated here reaches both or neither. Generation and startup test for
    drift against it.

    ``contained`` is what the placement vocabulary means by "inside". It is
    the *outer* boundary — whatever the profile delivers, a container or an
    equivalently provisioned host — and never a provider's per-call sandbox,
    which is one adapter's mechanism for spelling the same thing.

    ``host_executor`` is the launcher-owned channel from inside that boundary
    to the host. Its absence is the difference between an ``ask outside`` a
    person can answer by running the operation themselves and an ``allow
    outside`` that is simply refused: unprompted host execution exists only
    through the automated channel, because handing an unreviewed operation to
    a person to run is a review nobody asked for.

    ``unjudged_ambient`` is the profile's answer for a legible operation
    nothing judged, outside the boundary. The default keeps it visible; a
    profile may declare the seamless posture instead. Either way it is a
    declaration being read rather than a gap being inherited.
    """

    name: str = "default"
    contained: bool = False
    writable_roots: list[Path] = []
    precious_roots: list[Path] = []
    managed_roots: list[Path] = []
    disposable_roots: list[Path] = []
    """The four ways a root is treated, declared rather than inferred.

    Precious is the default for anything a declaration does not name, which
    is the safe direction: a tree wrongly called disposable is one a cleanup
    removes without asking, and a tree wrongly called precious costs a
    capture nobody needed. Managed is Lup's own active-session state, which
    is excluded from ordinary captures and is not recovery-authorized —
    a destructive shell operation against it is not made acceptable by a
    snapshot that deliberately does not hold it.
    """
    network_destinations: list[str] = []
    """Destinations this profile declares reachable, recorded as evidence.

    Evidence and not a policed surface. The classifier judges destinations it
    can see as part of the operation carrying them; it builds no egress
    proxy, chases no redirects, and polices no DNS. An operation whose only
    unusual fact is an unfamiliar destination settles like any other.
    """
    credential_paths: list[Path] = []
    """Credential material the boundary exposes, so policy can tell two uses apart.

    Normal git and gh use of a credential is part of a classified operation
    and is not a policy event. An explicit operation to print, copy, upload,
    or inspect the same material is, and the distinction needs the paths to
    be named somewhere. Placement cannot protect a secret already inside.
    """
    unjudged_ambient: UnjudgedAmbient = "ask"
    capabilities: list[CapabilityRequirement] = Field(default=[])

    def requires(self, capability: Capability) -> bool:
        """Whether a launch fails when this capability is not delivered."""
        return any(
            entry.capability == capability and entry.required
            for entry in self.capabilities
        )

    def declares(self, capability: Capability) -> bool:
        """Whether this profile depends on a capability at all."""
        return any(entry.capability == capability for entry in self.capabilities)


class BoundaryPreflight(BaseModel, frozen=True):
    """What a launch measured, and whether the session may start.

    The whole point of measuring is that the answer can be no. A profile
    requiring a capability nothing delivered does not start, and the
    diagnostic names the capability and what was tried — because "the sandbox
    is broken" sends somebody to read configuration, and "the host executor
    socket was not accepted at <path>" sends them to the thing that failed.
    """

    boundary: ExecutionBoundary
    evidence: list[CapabilityEvidence] = []

    def delivered(self, capability: Capability) -> bool:
        """Whether one capability was measured present."""
        return any(
            entry.capability == capability and entry.delivered
            for entry in self.evidence
        )

    def missing_required(self) -> list[CapabilityRequirement]:
        """Every required capability this launch could not deliver."""
        return [
            entry
            for entry in self.boundary.capabilities
            if entry.required and not self.delivered(entry.capability)
        ]

    def blocked(self) -> list[Capability]:
        """The optional capabilities whose dependent operations are refused.

        Not a failure of the launch and not a question for anybody: the
        operations that need one of these are capability-blocked, refused
        with a typed cause so the agent is sent to the missing channel rather
        than to argue with a rule.
        """
        return [
            entry.capability
            for entry in self.boundary.capabilities
            if not entry.required and not self.delivered(entry.capability)
        ]

    def launchable(self) -> bool:
        """Whether a session under this profile may start at all."""
        return not self.missing_required()

    def diagnosis(self) -> str:
        """Everything a person needs to act on, in the order they need it.

        The refusal first and the measurements after, because a reader who
        knows the launch failed still has to know which measurement failed —
        and one who only reads the first line has read the actionable half.
        """
        missing = self.missing_required()
        lines = [
            f"{self.boundary.name}: "
            + (
                "ready"
                if not missing
                else "cannot start — "
                + ", ".join(entry.capability for entry in missing)
                + " required and not delivered"
            )
        ]
        lines.extend(f"  {entry.diagnosis()}" for entry in self.evidence)
        blocked = self.blocked()
        if blocked:
            lines.append(
                "  optional and absent, so dependent operations are refused: "
                + ", ".join(blocked)
            )
        return "\n".join(lines)
