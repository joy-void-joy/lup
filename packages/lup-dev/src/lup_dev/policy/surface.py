"""Comparing a file's public surface before and after a change, for the public-API ask.

A change to what other code depends on is a design change, so it's asked like a
new file (`docs/judging-writes.md`, *The public-API ask*):
- a name added to or removed from a package's root (`__init__.py`);
- a new class;
- a changed signature of a definition that existed when the session started.

Names created during the session don't ask: the operator sees them when the file
or class holding them is asked. The engine reports each version's surface; this
compares them.
"""

from typing import Literal

from lup.types import Model
from lup_dev.codescan.contract import Surface


class ApiChange(Model):
    """One change to what other code can depend on."""

    kind: Literal["export-added", "export-removed", "class-added", "signature-changed"]
    name: str

    def describe(self) -> str:
        """Say what changed, in one line, for the operator's prompt.

        >>> ApiChange(kind="class-added", name="Client").describe()
        'adds the class `Client`'
        """
        match self.kind:
            case "export-added":
                return f"adds `{self.name}` to the package's root"
            case "export-removed":
                return f"removes `{self.name}` from the package's root"
            case "class-added":
                return f"adds the class `{self.name}`"
            case "signature-changed":
                return f"changes the signature of `{self.name}`"


def api_changes(
    baseline: Surface | None, before: Surface | None, after: Surface
) -> list[ApiChange]:
    """List how `after` changes the public surface of `before`.

    `baseline` is the file's surface when the session started, none where it
    didn't exist; `before` is its surface before this change, none where it's new.

    >>> start = Surface(exported=["ask"], classes=["Client"])
    >>> later = Surface(exported=["ask", "spawn"], classes=["Client", "Room"])
    >>> [change.describe() for change in api_changes(start, start, later)]
    ["adds `spawn` to the package's root", 'adds the class `Room`']
    """
    start = baseline or Surface()
    previous = before or Surface()
    signatures = {signature.name: signature for signature in previous.signatures}
    existed = [signature.name for signature in start.signatures]
    return [
        *(
            ApiChange(kind="export-added", name=name)
            for name in after.exported
            if name not in previous.exported
        ),
        *(
            ApiChange(kind="export-removed", name=name)
            for name in previous.exported
            if name not in after.exported and name in start.exported
        ),
        *(
            ApiChange(kind="class-added", name=name)
            for name in after.classes
            if name not in previous.classes and name not in start.classes
        ),
        *(
            ApiChange(kind="signature-changed", name=signature.name)
            for signature in after.signatures
            if signature.name in existed
            and signature.name in signatures
            and signatures[signature.name] != signature
        ),
    ]
