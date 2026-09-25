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

from typing import Literal

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


type SessionContainment = Literal["outer", "inner", "none"]
"""Which wall a session is opened behind.

The launcher's three words, in the same order and with the same meanings
:class:`~lup.devtools.harness.launch.LaunchSandbox` gives them, because the
two are one question asked at two moments -- what a launched session opens
under, and what a session an application opens itself opens under. A caller
holding one vocabulary per entry point would be holding two names for one
wall.

``outer`` is the container: the runtime is started as the program
``contained_program`` names, and that runtime's own sandbox stands down
inside it, because a wall that has to be weakened to start nested is worth
less than saying plainly which wall is load-bearing. ``inner`` is the
runtime's own sandbox, established wherever the session runs. ``none`` is
neither, and is what every request meant before this field existed.

Independent of :data:`~lup.providers.selection.SessionAutonomy`, which says
how much a session may do before it stops to ask. One runtime spells the two
with two fields and the other with one, which is a rendering problem each
adapter settles in its own words -- not a reason for a caller to state a
boundary as an autonomy.

Declared here rather than beside the request that names it, because each
adapter's own declaration names it too, and the request's module reads both
adapters: kept there, it would be half-built whenever an adapter asked for it.
"""
