"""The gate's `private` step: every file of the worktree, and `HEAD`'s commits the remotes lack, read for a value never published.

`docs/private.md`, *The gate's `private` step*. It sees what a write's judgement didn't: what
the shell wrote, a commit's message, a value added in one commit and taken out
in the next. On the host, `lup-dev private check` reads the list itself; in a
room, which never sees the list, it sends the files and `HEAD` to the host
(`Scanning`), and the `Private` module answers (`PrivateServing.scan`) with each
kind and place, never a value. Where no list is kept for the repository, the
host builds it first, as a launch would.

Each file is read whole, its path too; a file that isn't text by its bytes.
`HEAD`'s commits are those it reaches beyond what every remote of the
repository lists (`git ls-remote`, with the credentials of whoever runs it)
and its remote-tracking refs, each read as a push reads it
(`lup_dev.private.history`). Where a remote can't be listed, the commits aren't
read, said, rather than reading the whole history.
"""

from typing import TYPE_CHECKING

from lup.publishing import Place
from lup_dev.git import Git
from lup_dev.private.found import counted, found, masked, textual
from lup_dev.private.history import Spot, in_commits, remotes_hold, walked
from lup_dev.private.protocol import Scanned
from lup_dev.private.refusing import refused

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dev.private.protocol import Sent
    from lup_dev.private.withheld import Withheld

UNAPPROVED = (
    "no launch was approved for this repository on this machine, so no list of "
    "values never published is built here, and nothing was read"
)
"""Why the gate passes on a machine no launch ran on, as in CI, said."""

UNSELECTED = (
    "the declaration at the approved commit doesn't select `Private`, so nothing "
    "was read"
)
"""Why the gate passes where the approved declaration drops the module, said."""


def in_file(sent: Sent, held: Withheld) -> list[Spot]:
    """Find each value never published in one file: in its path, and in its content."""
    within = masked(sent.path, held)
    named = [
        Spot(
            held=each.held,
            place=Place(within=f"{within}, in its path", column=each.column),
        )
        for each in found(sent.path, held)
    ]
    content = sent.content()
    text = textual(content)
    if text is None:
        inside = [
            Spot(held=value, place=Place(within=within, byte=offsets[0]))
            for value in held.held
            if (offsets := counted(content, value))
        ]
        return [*named, *inside]
    inside = [
        Spot(
            held=each.held,
            place=Place(within=within, line=each.line, column=each.column),
        )
        for each in found(text, held)
    ]
    return [*named, *inside]


def scanned(
    files: list[Sent], head: str | None, repository: Path, held: Withheld
) -> Scanned:
    """Read `files`, and the commits `head` reaches that the remotes of the repository at `repository` lack, for each value of `held`."""
    in_files = [spot for sent in files for spot in in_file(sent, held)]
    git = Git.pinned(repository)
    if head is None:
        return Scanned(found=refused(in_files))
    remotes = remotes_hold(git)
    if remotes.unlisted:
        unlisted = ", ".join(f"`{name}`" for name in remotes.unlisted)
        return Scanned(
            found=refused(in_files),
            unchecked=(
                f"`HEAD`'s commits weren't read: {unlisted} couldn't be listed, "
                "so which commits are new wasn't known"
            ),
        )
    commits = walked(git, [head], remotes.objects)
    return Scanned(
        found=refused([*in_files, *in_commits(git, commits, held)]),
        commits=len(commits),
    )
