"""A session's name and their root thread's, one entry in their repository's names.

`docs/inbox.md`, *Threads*. Names are one set per repository, a thread's and an
agent's: `@inbox-scaling` names one thing there. A session's root thread
takes their name (`Concerns.root`), so the two share it, and follow each
other: a session renamed renames their root. A root nobody holds keeps its
name, and a session that takes that name, as their launch's or by `rename`,
takes that root as theirs: the next session called as an earlier one goes on
with what it left, rather than being pushed to `dev-2`, `dev-3`… for good.
Any other thread's name is no agent's (`refused`). The host service asks
through `Roots` (`host/service.py`), lowest of `lup_dev`'s layers.
"""

from typing import TYPE_CHECKING, override

from lup.types import Model
from lup_dev.host.service import Roots
from lup_dev.inbox.delivery import Delivery
from lup_ledger.threads import Thread

if TYPE_CHECKING:
    from pathlib import Path

    from lup_ledger.parties import Conversation


class RootNames(Model, Roots, arbitrary_types_allowed=True):
    """Sessions' names against their repository's threads, read from the inbox `delivery` keeps."""

    delivery: Delivery

    @override
    def refused(
        self,
        repository: Path,
        name: str,
        *,
        roots: bool,
        session: Conversation | None = None,
    ) -> str | None:
        concerns = self.delivery.concerns()
        node = concerns.inbox.ledger.named(repository, name)
        if node is None:
            return None
        if roots and concerns.takeable(repository, name, session) is not None:
            return None
        what = "a thread" if isinstance(node, Thread) else f"a `{node.kind}`"
        return (
            f"`{name}` names @{node.number}, {what} of this repository, and names "
            "are one set there: pick another name"
        )

    @override
    def renamed(self, session: Conversation, name: str) -> None:
        concerns = self.delivery.concerns()
        taken = concerns.takeable(session.repository, name, session)
        if taken is not None:
            concerns.took(session, taken)
            return
        place = concerns.inbox.whereabouts.get(session.key())
        root = (
            None if place is None or place.root is None else concerns.thread(place.root)
        )
        if root is None or root.name == name:
            return
        concerns.kept(
            root.model_copy(update={"name": name, "at": concerns.now(root.at)}),
            but=session,
        )
