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
from lup_dev.private.found import in_prose
from lup_dev.private.history import Spot, pushed
from lup_dev.private.withheld import said_of

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dev.private.withheld import Withheld


def posted(parts: list[Part], held: Withheld) -> list[Spot]:
    """Find every value never published in a post's parts, each read as prose, where an item's number is found too (`in_prose`)."""
    return [
        Spot(
            held=each.held,
            place=Place(within=f"the {part.name}", line=each.line, column=each.column),
        )
        for part in parts
        for each in in_prose(part.text, held)
    ]


def refused(spots: list[Spot]) -> list[Refusal]:
    """Say each value found as a refusal: its kind and its place, never the value, but an item's number (`said_of`)."""
    return [
        Refusal(what=telling.what, place=spot.place, steer=telling.steer)
        for spot in spots
        for telling in [said_of(spot.held)]
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
