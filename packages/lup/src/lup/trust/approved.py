"""What a trusted launch reads from its approved snapshot rather than from the tree.

A launch that the installed launcher handed off runs code materialized from
the snapshot its operator approved, which closes the window between checking a
file and reading it for code. Two registries are read by that code as *data*
and decide the boundary of the session it opens: `sync.json`, which the
project commits, and `sync.json.local`, which the machine keeps beside it,
gitignored. Both sit in the live checkout, and a session inside the container
can write either -- the second one especially, since nothing tracks it. A
launch that re-read them from the tree after the check would widen its mounts,
its devices or its network on whatever a session wrote a moment after the
operator approved something else.

So the launcher names the approved snapshot in the environment, and the
readers take their registries from there. Absent -- every launch that did not
come through the installed launcher -- they read the checkout as they always
did. A leaf on purpose: :mod:`lup.devtools.sync` reads it, and nothing it
imports may reach back into the launcher that sets it.
"""

from pathlib import Path, PurePosixPath

from pydantic import Field
from pydantic_settings import BaseSettings

# lup: ignore[constant-declaration] — the one spelling of the variable both the
# launcher that sets it and the registry readers that honour it have to name
APPROVED_TREE_ENV = "LUP_APPROVED_TREE"
"""The variable naming the approved snapshot a handed-off launch reads from."""

REGISTRY = PurePosixPath("sync.json")
"""The registry the project commits: what it tracks, and what a session may mount."""

MACHINE_REGISTRY = PurePosixPath("sync.json.local")
"""The registry this machine keeps beside the checkout, gitignored.

Named here rather than only where it is read, because the launcher has to
treat it as part of what it reviews: it is untracked, so no listing of tracked
paths would ever include it, and it is exactly the file that widens the next
session's boundary.
"""


class LaunchApproval(BaseSettings, populate_by_name=True):
    """The approved snapshot a trusted launch was handed, when it was handed one."""

    approved_tree: Path | None = Field(default=None, validation_alias=APPROVED_TREE_ENV)


def declarations_root(fallback: Path, approval: LaunchApproval | None = None) -> Path:
    """Where the registries are read from: the approved snapshot, else the checkout.

    ``fallback`` is the checkout, supplied by the caller that already resolved
    it, so this module resolves nothing about where a project lives.
    """
    chosen = approval if approval is not None else LaunchApproval()
    return chosen.approved_tree or fallback
