"""What `Private` serves: refusing at `Publishing` what carries a value never published, and reading a room's files for one, which the room's gate asks.

`docs/private.md`. Both run on the host, in the repository's process
(`lup_dev.worker`), against the list a launch built for the repository, kept in
the module's own data directory. Where none is kept for the repository, as for
a launch started before the module was approved, it's built then, as a launch
would, from the module and the related repositories the repository's process
found, and kept. Where it can't be built, nothing it would check leaves, and the
gate fails, each saying why.
"""

import asyncio
from typing import TYPE_CHECKING

import lup
from lup_dev.declaration.serving import Lup, ModuleServing, Room
from lup_dev.errors import LupDevError
from lup_dev.private.protocol import Scanned, Scanning
from lup_dev.private.refusing import refusals, unbuilt
from lup_dev.private.scanning import scanned
from lup_dev.private.withheld import HostFacts, Withheld, kept, prepared
from lup_dev.stored import read_model

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dev.private.module import Private


class PrivateServing(ModuleServing):
    """Refusing what would publish a value never published, and reading for one what a room's gate sends, on the host, where the list is."""

    module: Private

    async def withheld(self, repository: Path) -> Withheld:
        """Return the list of values never published kept for the repository whose git directory is `repository`, building and keeping it first where none is.

        Raise `LupDevError` or `OSError` where it can't be built.
        """
        held = read_model(kept(self.data), Withheld)
        if held is not None:
            return held
        made = await prepared(
            HostFacts(),
            repository,
            related=self.related,
            details=self.module.chosen_details(),
            values=self.module.chosen_values(),
            data=self.data,
        )
        return made.withheld

    @lup.on(lup.Publishing)
    async def refuse(self, event: lup.Publishing, by: Lup) -> list[lup.Refusal]:
        """Refuse each value never published in a push or a post, by its kind and place."""
        repository = by.launch.repository
        try:
            held = await self.withheld(repository)
        except (LupDevError, OSError) as failed:
            return [unbuilt(failed)]
        return await refusals(event.published, held, repository)

    @lup.request
    async def scan(self, asked: Scanning, by: Room) -> Scanned:
        """Read a room's files, and `HEAD`'s commits the remotes lack where the launch may fetch, for a value never published: each found by its kind and place."""
        launch = by.launch
        try:
            held = await self.withheld(launch.repository)
        except (LupDevError, OSError) as failed:
            return Scanned(unbuilt=f"the host couldn't build it: {failed}")
        refusal = launch.limits.refusal("fetch")
        head = asked.head if refusal is None else None
        answer = await asyncio.to_thread(
            scanned, asked.files, head, launch.repository, held
        )
        if refusal is not None and asked.head is not None:
            reason = f"`HEAD`'s commits weren't read, since listing the remotes is fetching: {refusal}"
            return answer.model_copy(update={"unchecked": reason})
        return answer
