"""What the operator asks of what's on trial and of which copy runs, and what the host service answers: the requests and their replies alone.

`docs/trust.md`, *What the host runs while it's on trial*. They're apart from what
answers them (`lup_dev.trial`, `lup_dev.trying`, `lup_dev.switching`) so a module's
view and actions can ask them (`Versions`), with what's under the declaration's
layer alone: the answering side reads what's approved, which reads the declaration.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

from lup.types import Model
from lup_dev.host.protocol import Reply, Request


class BranchListed(Model):
    """One branch on trial, as a page shows it."""

    branch: str
    tip: str
    subject: str = ""
    landed: datetime
    within: bool = False
    """It's in `live`."""
    out: bool = False
    """The operator took it out."""
    conflict: str = ""
    """What keeps it out, where it doesn't merge; empty where it does."""
    built: bool = False
    """A copy of `dev` and it alone is kept: picking it alone is immediate."""


class TrialListed(Model):
    """What's on trial, as a page shows it."""

    integration: str
    running: str
    dev: str | None = None
    live: str | None = None
    branches: list[BranchListed] = []


class ListTrial(Request, reads=False):
    """Say what's on trial in a repository: the operator's alone."""

    kind: Literal["trial"] = "trial"
    repository: Path | None = None
    """The repository's git directory; none for lup's own, which the service runs
    from."""


class PickBranches(Request, reads=False):
    """Run `dev` plus exactly these branches: the operator's alone, through a terminal or the plain page."""

    kind: Literal["trial-pick"] = "trial-pick"
    branches: list[str]
    repository: Path | None = None
    """The repository's git directory; none for lup's own."""


class AcceptBranch(Request, reads=False):
    """Merge a branch on trial onto `dev`, and clean up after it, as a landing does: the operator's alone."""

    kind: Literal["trial-accept"] = "trial-accept"
    branch: str
    repository: Path | None = None
    """The repository's git directory; none for lup's own."""


class DropBranch(Request, reads=False):
    """Take a branch off trial: the operator's alone. What they say on it reaches who landed it, or waits for them."""

    kind: Literal["trial-drop"] = "trial-drop"
    branch: str
    words: str = ""
    repository: Path | None = None
    """The repository's git directory; none for lup's own."""


class LastSwitch(Model):
    """What came of the last switch, kept for whoever didn't watch it."""

    commit: str
    at: datetime
    said: str
    answered: bool
    """Whether the copy switched to answers."""


class SwitchCopy(Request, reads=False):
    """Move the host service to the copy of `commit`, in a process of its own that outlives this service; refused here where it would take restoring the ledger, which the terminal's command says the cost of first."""

    kind: Literal["copy-switch"] = "copy-switch"
    commit: str


class CopySwitching(Reply):
    """The switch is under way: this service is about to stop, and a page asks the next."""

    kind: Literal["copy-switching"] = "copy-switching"
    commit: str
    log: Path
    """Where the switch says what came of it, for one that doesn't answer."""
    last: LastSwitch | None = None
    """The switch before this one, for a page waiting to tell them apart."""


class TrialSaid(Reply):
    """What came of what was asked of what's on trial: in words, what's on trial then, and the switch it set going, where it did, which a page waits on."""

    kind: Literal["trial-said"] = "trial-said"
    said: str = ""
    listed: TrialListed | None = None
    switching: CopySwitching | None = None
