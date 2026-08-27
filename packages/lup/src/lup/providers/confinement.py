"""How a runtime is told to stop confining what is already confined.

An application that spawns a provider CLI inside a container has to say so in
that CLI's own words. A second boundary nested in the first either fails to
start -- unprivileged containers do not let one mount a fresh ``/proc`` -- or
has to be weakened until it is not a boundary either, so the honest posture is
the container alone and the runtime told plainly to stand down.

The word is the provider's, and each adapter declares its own so every consumer
above holds this value instead of spelling one. Two consumers is what makes it
worth holding: the launcher that opens a session, and the probe that verifies a
session can open. A probe spelling its own would be verifying a session nobody
opens, which is the failure the image-side manifest exists to prevent and the
one it walked into here -- a bare runtime, its settings still saying the sandbox
was on, refusing for the absence of a confinement no launch asks for.

The value is a transparent carrier — it composes no seam and decides nothing,
so an application stores one the way it stores the runtime's name.
"""

from pydantic import BaseModel, Field


class ProviderConfinement(BaseModel, frozen=True):
    """One runtime's own way of being told not to confine itself."""

    off: list[str] = Field(
        description=(
            "The argv words turning this runtime's own sandbox off. A list "
            "rather than a flag because the runtimes disagree about the "
            "shape -- one takes a settings document and the other a mode "
            "name -- and a caller that had to know which would be spelling "
            "the vocabulary this value exists to carry"
        )
    )
