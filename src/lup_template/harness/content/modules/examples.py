"""The scaffold demonstrating itself, which no adopter runs.

``examples/`` composes lup's own runtime against lup's own README, and the
test modules beside it drive it, and the ``example`` tool group is the toolset that
exercise serves. A domain that adopted this template is a consumer of the
library rather than a demonstrator of it, so what it would inherit here is a
directory it will never run and a suite it has to keep green.

The only ``scaffold_only`` module in either half. That is not a default but
the absence of a choice: it is left out of what ``dev modules`` offers and
what ``/lup:init`` asks about, rather than being offered and declined, because
a module whose whole content is this repository talking about itself has
nothing to say to a project built from it. ``dev init drop-examples`` is what
removes the files; this is what stops them being offered again.
"""

from lup.harness.modules import Module
from lup_template.harness.content.modules.specs import EXAMPLES


def module() -> Module:
    """The scaffold's self-demonstration as one value."""
    return Module(spec=EXAMPLES)
