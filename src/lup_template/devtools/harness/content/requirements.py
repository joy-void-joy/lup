"""The external programs this repository needs, and what going without costs.

Mechanism and batteries both come from the library: `lup.harness.requirements`
says what a requirement *is*, `lup.harness.toolchain` offers one constructor
per program lup has an opinion about, and what is *this project's* is the
composition below -- which constructors it takes, what it passes them, and
anything lup never heard of.

Two axes are worth reading together, because either alone misreports. *Where*
says who is expected to have a capability. *Absence* says what going without
costs, down to a grade only worth saying to somebody setting a machine up.
"""

from lup.harness.requirements import Manifest
from lup.harness.toolchain import (
    clipboard_requirement,
    github_requirement,
    uv_requirement,
)


def manifest() -> Manifest:
    """This repository's deliberately short host requirement roster."""
    return Manifest(
        requirements=[
            uv_requirement(),
            github_requirement(),
            clipboard_requirement(),
        ],
    )
