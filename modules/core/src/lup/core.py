"""`Core`: the module every project holds, which packages what every project has, and lists its submodules' promises."""

from lup.declaration.module import Module
from lup.declaration.promises import DeclarationPromises
from lup.doors.parts import Parts
from lup.doors.promises import DoorsPromises, PartsPromises
from lup.inbox.part import Inboxes, Speaking
from lup.inbox.promises import InboxPromises
from lup.inbox.records import EDGES, NODES
from lup.running.promises import RunningPromises
from lup.shell.kinds import SHELL_FOLDS, SHELL_TONES, FoldKind, Folds, Tones
from lup.shell.promises import ShellPromises
from lup.store.promises import StorePromises
from lup.store.records import Recorded
from lup.testing.promises import TestingPromises


class Core(Module):
    """What every project has: loading the declaration, the doors its modules are reached through, checking their promises, and the shell's kinds; the core's other submodules as they're built.

    A project changes it with `.edit` as it would any module, or puts another in
    its place with `.replace`, but can't drop it: resolving a selection without a
    module named `core` fails. What it serves is its submodules' parts and
    promises, the inbox's among them; what it declares, the shell's tones and
    fold kinds, which every module's views may name, and which a layer changes
    as any field, and the kinds of record the inbox keeps in the store.
    """

    name = "core"
    parts: Parts = Parts.of(
        DeclarationPromises,
        DoorsPromises,
        PartsPromises,
        RunningPromises,
        TestingPromises,
        ShellPromises,
        StorePromises,
        Inboxes,
        Speaking,
        InboxPromises,
    )
    tones: Tones = Tones.of(*SHELL_TONES)
    """The shell's tones: plain, muted, strong, and the operator's own words."""
    folds: Folds = Folds.of(
        *SHELL_FOLDS,
        FoldKind(name="concern", letter="c", called="concern", level=1, colour="cyan"),
    )
    """The shell's fold kinds: a party's section, a file, a body, a run of
    unchanged lines; and the inbox's, a concern."""
    kinds: Recorded = Recorded.of(*NODES, *EDGES)
    """The kinds of record the core's submodules keep in the store: the inbox's."""
