"""`Project`: what a project declares, its modules above all.

Every part lives in a module, so reading one module says what it does; `Project`
holds the modules a project is made of (`README.md` here, *A project*).
"""

from lup.declaration.module import Modules
from lup.types import Model


class Project(Model, extra="forbid"):
    """A project's declaration: the modules it's made of.

    >>> Project() == Project(modules=Modules.default())
    True
    """

    modules: Modules = Modules.default()
    """The modules it's made of: lup's default ones, unless it says otherwise."""
