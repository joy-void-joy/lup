"""What `Private` refuses at `Publishing`: a push or a post that carries a value never published.

`docs/private.md`, *The door*. `PrivateServing.refuse` runs it on the host, in
the repository's process (`lup_dev.worker`), against the list a launch built for
the repository. A push is read commit by commit (`lup_dev.private.history`), in
the repository's own git directory, pinned there; a post part by part. Each
value found is a refusal naming its kind and place, never the value.
"""

import asyncio
from typing import TYPE_CHECKING

from lup.publishing import Part, Place, Post, Published, Push, Refusal
from lup_dev.git import Git
from lup_dev.private.found import found
from lup_dev.private.history import Spot, pushed
from lup_dev.private.withheld import said

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dev.private.withheld import Withheld


def posted(parts: list[Part], held: Withheld) -> list[Spot]:
    """Find every value never published in a post's parts."""
    return [
        Spot(
            held=each.held,
            place=Place(within=f"the {part.name}", line=each.line, column=each.column),
        )
        for part in parts
        for each in found(part.text, held)
    ]


def refused(spots: list[Spot]) -> list[Refusal]:
    """Say each value found as a refusal: its kind and its place, never the value."""
    return [
        Refusal(what=said(spot.held.kind).what, place=spot.place, steer=steer)
        for spot in spots
        for steer in [said(spot.held.kind).steer]
    ]


def unbuilt(failed: Exception) -> Refusal:
    """Say why nothing leaves where the list couldn't be built on the host."""
    return Refusal(
        what="a list of private values that couldn't be built",
        place=Place(within="all of it"),
        steer=(
            f"the host couldn't build it ({failed}), so what it would check "
            "doesn't leave: tell the operator"
        ),
    )


async def refusals(
    published: Published, held: Withheld, repository: Path
) -> list[Refusal]:
    """Refuse each value of `held` in `published`, a push of the repository whose git directory is `repository`, or a post, by its kind and place."""
    match published:
        case Push(updates=updates, has=has):
            git = Git.pinned(repository)
            spots = await asyncio.to_thread(pushed, git, updates, has, held)
            return refused(spots)
        case Post(parts=parts):
            return refused(posted(parts, held))
