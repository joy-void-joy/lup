"""The answers the hooks remember, read back and retired.

The hook side writes the memory with the pinned standard library alone, in
:mod:`lup.policy.assets.host`; this is the typed reading of the same file,
for the commands that show it to somebody and take an entry back.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from lup.policy.assets.host import approval_states, forget_approval


class Approval(BaseModel, frozen=True):
    """One exact call the author answered yes to, and when."""

    fingerprint: str = Field(description="What the memory keys the call by")
    kind: str = Field(description="What was judged: a shell command or a fetch")
    subject: str = Field(description="The command or URL, as it ran")
    cwd: str = Field(description="The checkout the call ran from")
    at: str = Field(description="When the answer was observed, as an ISO timestamp")


def remembered(root: Path) -> list[Approval]:
    """Every call this checkout remembers an approval for, oldest first."""
    return [
        Approval.model_validate(held)
        for held in approval_states(root).values()
        if held["state"] == "approved"
    ]


def forget(root: Path, selector: str) -> list[Approval]:
    """Retire every remembered approval the selector names.

    A selector is a fingerprint prefix, as ``approvals`` prints one, or the
    exact command or URL; both are accepted because the fingerprint is what a
    reader copies and the text is what they remember.
    """
    chosen = [
        item
        for item in remembered(root)
        if item.fingerprint.startswith(selector) or item.subject == selector
    ]
    return [item for item in chosen if forget_approval(root, item.fingerprint)]
