"""`Core`: the module every project holds, which packages what every project has, and lists its submodules' promises."""

from lup.declaration.module import Module
from lup.declaration.promises import DeclarationPromises
from lup.doors.parts import Parts
from lup.doors.promises import DoorsPromises, PartsPromises
from lup.running.promises import RunningPromises
from lup.shell.blocks import Viewing
from lup.shell.kinds import SHELL_FOLDS, SHELL_TONES, Folds, Tones
from lup.shell.promises import ShellPromises
from lup.testing.promises import TestingPromises


class Core(Module):
    """What every project has: loading the declaration, the doors its modules are reached through, checking their promises, and the shell's kinds; the core's other submodules as they're built.

    A project changes it with `.edit` as it would any module, or puts another in
    its place with `.replace`, but can't drop it: resolving a selection without a
    module named `core` fails. What it serves is its submodules' promises; what
    it declares, the shell's tones and fold kinds, which every module's views may
    name, and which a layer changes as any field.
    """

    name = "core"
    parts: Parts = Parts.of(
        DeclarationPromises,
        DoorsPromises,
        PartsPromises,
        RunningPromises,
        TestingPromises,
        ShellPromises,
    )
    tones: Tones = Tones.of(*SHELL_TONES)
    """The shell's tones: plain, muted, strong, and the operator's own words."""
    folds: Folds = Folds.of(*SHELL_FOLDS)
    """The shell's fold kinds: a party's section, a file, a body, a run of
    unchanged lines."""
    document: Viewing | None = None
    """The view the dashboard's document is, its root: a view listing the
    parties, each a fold of the `party` kind whose content reads what's shown of
    it, of the module named; none where the home repository's declaration names
    none, and the dashboard shows nothing."""
