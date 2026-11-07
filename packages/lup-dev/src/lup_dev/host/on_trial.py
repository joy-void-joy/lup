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
from lup_ledger.parties import Conversation


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
    party: Conversation | None = None
    """Who landed it, as the inbox knows them: whom the operator's words on it
    reach, or wait for."""
    merging: bool = False
    """It's being merged onto the integration branch, or waits its turn to be."""
    merge_said: str = ""
    """What the last try at merging it said, where it didn't land; empty else."""


class LastSwitch(Model):
    """What came of the last switch, kept for whoever didn't watch it."""

    commit: str
    at: datetime
    said: str
    answered: bool
    """Whether the copy switched to answers."""


class VersionListed(Model):
    """One of `live`'s commits, as a page shows it: what it holds, and what running it again takes."""

    commit: str
    dev: str
    """The commit of the integration branch it's on."""
    tips: dict[str, str] = {}
    """Each branch in it, with the commit of it there."""
    at: datetime
    copy_kept: str | None = None
    """The commit of the copy kept of it, which running it again moves the host
    to, a copy of another commit holding what the host runs of it the same; none
    where none is kept, so running it asks the operator's yes and builds."""
    running: bool = False
    """It's what the host runs: what's approved holds what it holds."""
    ran: datetime | None = None
    """When its copy last answered; none for one never run, or with no copy."""


class TrialListed(Model):
    """What's on trial, as a page shows it."""

    integration: str
    running: str
    dev: str | None = None
    live: str | None = None
    branches: list[BranchListed] = []
    versions: list[VersionListed] = []
    """Each of `live`'s commits whose branches are still on trial, oldest first."""
    runs: str | None = None
    """The commit approved, whose copy the host runs: another than `live` where
    `live` holds what the host runs the same, or waits on the operator's yes."""
    last: LastSwitch | None = None
    """What came of the last switch, which a page says where it fell back: lup's
    own repository's alone, whose copy it moved."""
    merged: list[str] = []
    """What the last few merges that landed said, the latest last, since the branch
    each was of isn't on trial to say it."""


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
    seen: dict[str, str] = {}
    """The tip each was seen at, by its name: refused where it has landed again
    since, whoever asks saying they looked at it (`ChangeBranches.seen`)."""
    dev: str | None = None
    """The commit of the integration branch seen, refused where it has moved since;
    none asks nothing of it."""


class ChangeBranches(Request, reads=False):
    """Put these branches in what runs and leave those out, each other as it stands: the operator's alone, what one box says, where a pick says the whole set. Applied on the host under the repository's turn, so what's seen and what's changed are one."""

    kind: Literal["trial-change"] = "trial-change"
    taking: list[str] = []
    leaving: list[str] = []
    seen: dict[str, str] = {}
    """The tip each was seen at, by its name: refused where it has landed again
    since."""
    repository: Path | None = None
    """The repository's git directory; none for lup's own."""


class AcceptBranch(Request, reads=False):
    """Merge a branch on trial onto `dev`, and clean up after it, as a landing does: the operator's alone."""

    kind: Literal["trial-accept"] = "trial-accept"
    branch: str
    repository: Path | None = None
    """The repository's git directory; none for lup's own."""
    tip: str | None = None
    """The tip it was seen at, refused where it has landed again since; none asks
    nothing of it."""
    apart: bool = False
    """Answer at once and merge it apart, its gate taking minutes, what it comes to
    said where what's on trial is listed (`BranchListed.merging`, `.merge_said`)."""


class DropBranch(Request, reads=False):
    """Take a branch off trial: the operator's alone. What they say on it reaches who landed it, or waits for them."""

    kind: Literal["trial-drop"] = "trial-drop"
    branch: str
    words: str = ""
    repository: Path | None = None
    """The repository's git directory; none for lup's own."""


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
