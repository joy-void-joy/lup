"""`Core`: the module every project holds, which packages what every project has, and lists its submodules' promises."""

from lup.declaration.module import Module
from lup.declaration.promises import DeclarationPromises
from lup.doors.parts import Parts
from lup.doors.promises import DoorsPromises, PartsPromises
from lup.inbox.part import Inboxes, Speaking
from lup.inbox.promises import InboxPromises
from lup.inbox.records import EDGES, NODES
from lup.running.promises import RunningPromises
from lup.store.promises import StorePromises
from lup.store.records import Recorded
from lup.testing.promises import TestingPromises


class Core(Module):
    """What every project has: loading the declaration, the doors its modules are reached through, and checking their promises; the core's other submodules as they're built.

    A project changes it with `.edit` as it would any module, or puts another in
    its place with `.replace`, but can't drop it: resolving a selection without a
    module named `core` fails. What it serves is its submodules' parts and promises: the inbox's.
    """

    name = "core"
    parts: Parts = Parts.of(
        DeclarationPromises,
        DoorsPromises,
        PartsPromises,
        RunningPromises,
        TestingPromises,
        StorePromises,
        Inboxes,
        Speaking,
        InboxPromises,
    )
    kinds: Recorded = Recorded.of(*NODES, *EDGES)
    """The kinds of record the core's submodules keep in the store: the inbox's."""
