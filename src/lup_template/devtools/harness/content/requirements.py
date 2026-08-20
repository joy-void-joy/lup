"""The external programs this repository needs, and what going without costs.

Mechanism and batteries both come from the library: `lup.harness.requirements`
says what a requirement *is*, `lup.harness.toolchain` offers one constructor
per program lup has an opinion about, and what is *this project's* is the
composition below -- which constructors it takes, what it passes them, and
anything lup never heard of.

Two axes are worth reading together, because either alone misreports. *Where*
says who is expected to have it: a container runtime is the host's and must
never be the image's, a TypeScript toolchain is the image's and the host has
no reason to carry one. *Absence* says what going without costs, down to a
grade only worth saying to somebody setting a machine up. Between them, a
laptop with no bun and no clipboard is told nothing at all at launch, which
is correct -- neither is a fault of that machine.
"""

from lup.harness.requirements import Manifest
from lup.harness.toolchain import (
    bun_requirement,
    clipboard_requirement,
    container_requirement,
    github_requirement,
    typescript_requirement,
    uv_requirement,
)

MANIFEST = Manifest(
    requirements=[
        # Every default taken as offered. Where this repository has an
        # opinion it is in what it *adds*: the JavaScript toolchain, which
        # `default_manifest` deliberately omits because most projects on lup
        # have none.
        uv_requirement(),
        container_requirement(),
        github_requirement(),
        bun_requirement(),
        typescript_requirement(),
        clipboard_requirement(),
    ],
)
"""Ordered by how early a session notices the absence, not by importance.

Deliberately short. A first draft also declared ripgrep, and exercising it
refuted the declaration twice over: this project never invokes `rg` -- only
the policy vocabulary judges it, which is a rule about what an *agent* may
run -- and on the machine that raised the finding `rg` was a shell function
rather than an executable, so `command -v` would have called it present while
nothing spawned could reach it. A manifest that invents prerequisites refuses
machines that were fine, which is the failure it exists to prevent pointed
the other way.

`bun` and `typescript` are declared and, until the image declaration exists,
unverified: an image-side requirement is checked where it is needed, and
there is not yet an image to check it in. What they buy today is the package
list a build will be assembled from, and the honest statement that nothing
has exercised them.
"""
