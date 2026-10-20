"""The gate's `private` step: every file of the worktree, and `HEAD`'s commits the remotes lack, read for a value never published.

`docs/private.md`, *The gate's `private` step*. It sees what a write's judgement didn't: what
the shell wrote, a commit's message, a value added in one commit and taken out
in the next. On the host, `lup-dev private check` reads the list itself; in a
room, which never sees the list, it sends the files and `HEAD` to the host
(`Scanning`), and the `Private` module's handler answers (`Scanner`) with each
kind and place, never a value. Where no list is kept for the repository, the
host builds it first, as a launch would.

Each file is read whole, its path too; a file that isn't text by its bytes.
`HEAD`'s commits are those it reaches beyond what every remote of the
repository lists (`git ls-remote`, with the credentials of whoever runs it)
and its remote-tracking refs, each read as a push reads it
(`lup_dev.private.history`). Where a remote can't be listed, the commits aren't
read, said, rather than reading the whole history.
"""

import asyncio
from typing import TYPE_CHECKING, override

from lup_dev.declaration.serving import ModuleHandler
from lup_dev.errors import LupDevError
from lup_dev.git import Git
from lup_dev.host.publishing import Place
from lup_dev.private.found import counted, found, masked, textual
from lup_dev.private.history import Spot, in_commits, remotes_hold, walked
from lup_dev.private.hooks import refused
from lup_dev.private.protocol import Scanned, Scanning, Sent
from lup_dev.private.withheld import HostFacts, Withheld, kept, prepared
from lup_dev.stored import read_model

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dev.host.protocol import Reply
    from lup_dev.private.module import Private

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


class Scanner(ModuleHandler):
    """Answers `Scanning` for a launch's room: its files and `HEAD`'s new commits read on the host, against the list the room never sees."""

    module: Private
    request: Scanning

    @override
    async def answer(self) -> Reply:
        """Read the room's files and `HEAD`'s new commits against the list kept for the repository, building it first where none is, as a launch would."""
        held = read_model(kept(self.data), Withheld)
        if held is None:
            try:
                made = await prepared(
                    HostFacts(),
                    self.launch.repository,
                    related=self.related,
                    details=self.module.chosen_details(),
                    values=self.module.chosen_values(),
                    data=self.data,
                )
            except (LupDevError, OSError) as failed:
                return Scanned(unbuilt=f"the host couldn't build it: {failed}")
            held = made.withheld
        refusal = self.launch.limits.refusal("fetch")
        head = self.request.head if refusal is None else None
        answer = await asyncio.to_thread(
            scanned, self.request.files, head, self.launch.repository, held
        )
        if refusal is not None and self.request.head is not None:
            reason = f"`HEAD`'s commits weren't read, since listing the remotes is fetching: {refusal}"
            return answer.model_copy(update={"unchecked": reason})
        return answer
