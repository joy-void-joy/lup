"""`Inbox`: the module of parties, concerns and piles, and what's said between them, which the core requires."""

from lup.declaration.module import Module
from lup.doors.parts import Parts
from lup.inbox.part import Inboxes, Speaking
from lup.inbox.promises import InboxPromises
from lup.inbox.records import EDGES, NODES
from lup.shell.kinds import FoldKind, Folds
from lup.store.records import Recorded


class Inbox(Module):
    """Parties, concerns and piles, and what's said between them.

    The inbox's store, an agent's tools for saying something, and the
    operator's views and commands, typed `lup inbox …`: a module of its own,
    which the core requires, so a project edits or replaces it as any module
    but can't drop it (`README.md` here).
    """

    name = "inbox"
    parts: Parts = Parts.of(Inboxes, Speaking, InboxPromises)
    folds: Folds = Folds.of(
        FoldKind(
            name="concern",
            letter="c",
            called="concern",
            level=1,
            colour="cyan",
            outlined=True,
        ),
        FoldKind(
            name="friction",
            letter="r",
            called="friction",
            level=1,
            colour="purple",
            outlined=True,
        ),
    )
    """A concern, and a friction, a concern opened by what got in an agent's
    way, its letter and colour in the margin saying which it is."""
    kinds: Recorded = Recorded.of(*NODES, *EDGES)
    """The kinds of record the inbox keeps in the store."""
