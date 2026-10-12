"""`Project`: what a project declares in `lup_project.py`, its modules above all.

Every part lives in a module, so reading one module says what it does; `Project`
holds the modules, and what isn't a module's (`docs/declaration.md`, *A project is
its modules*).
"""

from typing import Literal

from lup.types import Model
from lup_dev.declaration.module import Modules


class Project(Model, extra="forbid"):
    """A project's declaration: its modules, and what isn't a module's.

    >>> Project() == Project(modules=Modules.default())
    True
    """

    modules: Modules = Modules.default()
    """The modules it's made of: lup's default ones, unless it says otherwise."""
    asks: Literal["every", "protected"] = "every"
    """Which of the judge's asks reach the operator.

    `every` asks each one. `protected` asks only a protected path's, whose change
    takes effect outside the agent's reach before anything lands, and allows the
    rest, the design reviewed in notes before the code and at landing instead.
    lup's rules refuse either way. It goes when the judge's asks become proposals.
    """
