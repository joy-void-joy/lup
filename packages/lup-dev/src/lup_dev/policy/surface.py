"""Comparing a file's public surface before and after a change, for the public-API ask.

A change to what other code depends on is a design change, so it's asked like a
file being created (`docs/judging-writes.md`, *The public-API ask*): a public
name added or removed, anywhere in production Python. That's a name added to or
removed from a package's root (`__init__.py`); a class added or removed; and a
function or method added or removed. A signature changed asks nothing: the
operator reviews the shape of a module, not every parameter.

The session is the baseline: a name is added where the version before this
change and the file at the session's start both lack it, and removed where both
have it, so a name the session themselves created comes and goes freely once
asked, and a name they took out can go back. A file being created asks nothing of its
names: the operator sees them with the file. The engine reports each version's
surface, each name placed on its line; this compares them, and places each change
on the line naming what it changes, which the review marks.
"""

from typing import Literal

from lup.types import Model
from lup_dev.codescan.contract import Named, Surface
from lup_dev.inbox.store import ApiKind


class Kind(Model):
    """One kind of a surface's names, and how its changes are said."""

    named: Named
    added: ApiKind
    removed: ApiKind


KINDS = [
    Kind(named="export", added="export-added", removed="export-removed"),
    Kind(named="class", added="class-added", removed="class-removed"),
    Kind(named="function", added="function-added", removed="function-removed"),
]
"""Each kind of name a surface holds, in the order their changes are listed."""


class ApiChange(Model):
    """One change to what other code can depend on, and where it is."""

    kind: ApiKind
    name: str
    line: int | None = None
    """The line naming it, counted from 1, in the content after the change, or
    for a name it removes, before it (`side`); none where the engine didn't
    place it."""

    def side(self) -> Literal["before", "after"]:
        """Say which version of the file `line` is in: the one before the change for a name it removes, else the one after.

        >>> ApiChange(kind="export-removed", name="ask").side()
        'before'
        >>> ApiChange(kind="function-added", name="ask").side()
        'after'
        """
        return "before" if self.kind in [kind.removed for kind in KINDS] else "after"

    def describe(self) -> str:
        """Say what changed, in one line, for the operator's prompt.

        A function named inside a class is said as a method.

        >>> ApiChange(kind="class-added", name="Client").describe()
        'adds the class `Client`'
        >>> ApiChange(kind="function-removed", name="Client.ask").describe()
        'removes the method `Client.ask`'
        """
        what = "method" if "." in self.name else "function"
        match self.kind:
            case "export-added":
                return f"adds `{self.name}` to the package's root"
            case "export-removed":
                return f"removes `{self.name}` from the package's root"
            case "class-added":
                return f"adds the class `{self.name}`"
            case "class-removed":
                return f"removes the class `{self.name}`"
            case "function-added":
                return f"adds the {what} `{self.name}`"
            case "function-removed":
                return f"removes the {what} `{self.name}`"
            case "signature-changed":
                # Found by copies before, and kept by what they wrote (`ApiKind`).
                return f"changes the signature of `{self.name}`"


def api_changes(
    baseline: Surface | None, before: Surface | None, after: Surface
) -> list[ApiChange]:
    """List how `after` changes the public surface of `before`, each change on the line naming it.

    `baseline` is the file's surface when the session started, none where it
    didn't exist; `before` is its surface before this change, none where this
    change creates it, which asks nothing of its names.

    >>> start = Surface(exported=["ask"], classes=["Client"], functions=["Client.ask"])
    >>> later = Surface(
    ...     exported=["ask", "spawn"], classes=["Client"], functions=["spawn"]
    ... )
    >>> [change.describe() for change in api_changes(start, start, later)]
    ["adds `spawn` to the package's root", 'adds the function `spawn`', 'removes the method `Client.ask`']
    >>> api_changes(None, None, later)
    []
    """
    if before is None:
        return []
    start = baseline or Surface()
    return [
        change
        for kind in KINDS
        for change in [
            *(
                ApiChange(
                    kind=kind.added, name=name, line=after.place(kind.named, name)
                )
                for name in after.names(kind.named)
                if name not in before.names(kind.named)
                and name not in start.names(kind.named)
            ),
            *(
                ApiChange(
                    kind=kind.removed, name=name, line=before.place(kind.named, name)
                )
                for name in before.names(kind.named)
                if name not in after.names(kind.named)
                and name in start.names(kind.named)
            ),
        ]
    ]
