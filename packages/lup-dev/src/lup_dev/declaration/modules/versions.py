"""`Versions`: the optional module that runs another branch than the one work is integrated on."""

from lup_dev.declaration.module import Module
from lup_dev.host.protocol import BranchName


class Versions(Module):
    """Running another branch than the integration branch, so what lands can be tried on the operator's machine before it's accepted."""

    name = "versions"

    running: BranchName | None = None
    """The branch the host runs, trust reads and `land` lands on; none for the
    integration branch (`Core.integration`). It's read from the declaration
    approved, so a change to it takes effect once approved (`docs/trust.md`,
    *Which branch*), and it's gated, since `land` lands only on a gated branch
    (`Credentials.gated`). Naming one neither makes nor computes it: until the
    repository has that branch, trust reads the integration branch's tip."""
