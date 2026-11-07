"""A session's name against their repository's threads, one set of names there.

`docs/inbox.md`, *Threads*. Names are one set per repository, a thread's and an
agent's: `@inbox-scaling` names one thing there, so a name a thread has is no
agent's. A root an earlier lup kept is read as absent (`Thread.root`), and
refuses nobody its name. The host service asks through `Namesakes`
(`host/service.py`), lowest of `lup_dev`'s layers.
"""

from typing import TYPE_CHECKING, override

from lup.types import Model
from lup_dev.host.service import Namesakes
from lup_dev.inbox.delivery import Delivery
from lup_ledger.threads import Thread

if TYPE_CHECKING:
    from pathlib import Path


class NodeNames(Model, Namesakes, arbitrary_types_allowed=True):
    """Agents' names against their repository's nodes, read from the inbox `delivery` keeps."""

    delivery: Delivery

    @override
    def refused(self, repository: Path, name: str) -> str | None:
        concerns = self.delivery.concerns()
        node = concerns.found(repository, name)
        if node is None:
            return None
        what = "a thread" if isinstance(node, Thread) else f"a `{node.kind}`"
        return (
            f"`{name}` names @{node.number}, {what} of this repository, and names "
            "are one set there: pick another name"
        )
