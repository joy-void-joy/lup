"""`Versions`: the optional module that runs another branch than the one work is integrated on."""

from lup_dev.declaration.module import Module
from lup_dev.host.protocol import BranchName


class Versions(Module):
    """Running another branch than the integration branch, so what lands can be tried on the operator's machine before it's accepted."""

    name = "versions"

    running: BranchName | None = None
    """The branch the host runs, trust reads and `land` lands on; none for the
    integration branch (`Core.integration`). Where it's another, the host computes
    it, from the integration branch and what's on trial (`docs/trust.md`, *What the
    host runs while it's on trial*). It's read from the declaration approved, so a
    change to it takes effect once approved (`docs/trust.md`, *Which branch*), and
    it's gated (`Credentials.gated`), so `delete-merged` never deletes it. Naming
    one doesn't make it: until the first landing or pick, trust reads the
    integration branch's tip."""
