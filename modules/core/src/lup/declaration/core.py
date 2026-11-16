"""`Core`: the module every project holds, which packages what every project has."""

from lup.declaration.module import Module


class Core(Module):
    """What every project has: loading the declaration, and the core's other submodules as they're built.

    A project changes it with `.edit` as it would any module, or puts another in
    its place with `.replace`, but can't drop it: resolving a selection without a
    module named `core` fails.
    """

    name = "core"
