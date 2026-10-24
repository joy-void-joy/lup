"""The `Private` module's hook at `publishing`: refusing a push or a post that carries a value never published.

`docs/private.md`, *The door*. It runs on the host, in the repository's process
(`lup_dev.worker`), and reads the list a launch built for the repository from
the module's own data directory. A push is read commit by commit
(`lup_dev.private.history`), in the repository's own git directory, pinned
there; a post part by part. Each value found is a refusal naming its kind and
place, never the value.

Where no list is kept for the repository, as for a launch started before the
module was approved, the hook builds it then, as a launch would, from its
module and the related repositories the repository's process found, and keeps
it.
Where it can't be built, nothing it would check leaves, saying why.
"""

import asyncio
from typing import TYPE_CHECKING

from lup.tools.hook import lup_hook
from lup_dev.declaration.serving import ModuleHooks, Moment
from lup_dev.errors import LupDevError
from lup_dev.git import Git
from lup_dev.host.publishing import Part, Place, Post, Push, Refusal
from lup_dev.private.found import found
from lup_dev.private.history import Spot, pushed
from lup_dev.private.withheld import HostFacts, Withheld, kept, prepared, said
from lup_dev.stored import read_model

if TYPE_CHECKING:
    from lup_dev.private.module import Private


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


class PrivateHooks(ModuleHooks):
    """Refusing what would publish a value never published."""

    module: Private

    @lup_hook
    async def publishing(self, moment: Moment) -> list[Refusal]:
        """Refuse each value never published in a push or a post, by its kind and place."""
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
                return [unbuilt(failed)]
            held = made.withheld
        match moment.published:
            case Push(updates=updates, has=has):
                repository = Git.pinned(self.launch.repository)
                spots = await asyncio.to_thread(pushed, repository, updates, has, held)
                return refused(spots)
            case Post(parts=parts):
                return refused(posted(parts, held))
            case None:
                return []
