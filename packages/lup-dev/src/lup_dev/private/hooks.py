"""The `Private` module's hook at `publishing`: refusing a push or a post that carries a value never published.

`docs/private.md`, *The door*. It runs on the host, in the launch's own process
(`lup_dev.worker`), and reads the list the launch built for the repository from
the module's own data directory. A push is read commit by commit
(`lup_dev.private.history`), in the repository's own git directory, pinned
there; a post part by part. Each value found is a refusal naming its kind and
place, never the value.

Where no list was built for the repository, nothing it would check leaves: a
launch builds one, and only one that predates the module wouldn't.
"""

import asyncio
from typing import TYPE_CHECKING

from lup.tools.hook import lup_hook
from lup_dev.declaration.serving import ModuleHooks, Moment
from lup_dev.git import Git
from lup_dev.host.publishing import Part, Place, Post, Push, Refusal
from lup_dev.private.found import found
from lup_dev.private.history import Spot, pushed
from lup_dev.private.withheld import Withheld, kept, said
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


UNBUILT = Refusal(
    what="a repository with no list of private values",
    place=Place(within="all of it"),
    steer=(
        "a launch builds the list on the host, and this one didn't: tell the "
        "operator, who launches again with a `lup-dev` that has the `Private` module"
    ),
)
"""Why nothing leaves where no list was built for the repository."""


class PrivateHooks(ModuleHooks):
    """Refusing what would publish a value never published."""

    module: Private

    @lup_hook
    async def publishing(self, moment: Moment) -> list[Refusal]:
        """Refuse each value never published in a push or a post, by its kind and place."""
        held = read_model(kept(self.data), Withheld)
        if held is None:
            return [UNBUILT]
        match moment.published:
            case Push(updates=updates, has=has):
                repository = Git(
                    cwd=self.launch.repository,
                    common=self.launch.repository,
                    arguments=["--no-replace-objects"],
                )
                spots = await asyncio.to_thread(pushed, repository, updates, has, held)
                return refused(spots)
            case Post(parts=parts):
                return refused(posted(parts, held))
            case None:
                return []
