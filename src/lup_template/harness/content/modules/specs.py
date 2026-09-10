# lup: ignore[constant-declaration]
# The roster here is this repository's own composition — which modules only it
# has, and in what order it lays them out. A composition root is where a
# judgement is finally made rather than passed on, so there is no caller above
# it to take these from.
"""What the modules only this repository has are called, and what they are for.

Separate from their builders for the reason the library's specs are: listing
the roster, resolving requirements, and reporting what a module's prose costs
all happen before anything is built, and none of them should import a skill.

``template-init`` stays on for an adopter, which is not obvious and is worth
saying: a project built from this scaffold still calls ``/lup:init``, still
installs the plugin, and still opens a design conversation. What it drops the
moment it is stood up is ``examples`` — a directory composing lup's own
runtime against lup's own README, plus the test modules driving it, which
an adopter inherits as a suite it must keep green and will never run. That is
what ``dev init drop-examples`` removes, and the only module here that a
project built from this one is never even offered.
"""

from lup.harness.modules import ModuleSpec

PROJECT = ModuleSpec(
    id="project",
    title="This project",
    summary=(
        "What this repository is, how work moves through it, and what it "
        "expects of a session working in it."
    ),
    default_on=True,
    subapps=["agent"],
)

TEMPLATE_INIT = ModuleSpec(
    id="template-init",
    title="Template init",
    summary=(
        "Standing a lup project up: designing it, initializing it, installing "
        "the plugin into it, and restarting one from an explored predecessor."
    ),
    default_on=True,
)

UPSTREAM = ModuleSpec(
    id="upstream",
    title="Upstream",
    summary=(
        "Keeping a project in step with lup, and importing a feature from a "
        "tracked repository rather than rewriting it."
    ),
    default_on=True,
    subapps=["sync"],
)

EXAMPLES = ModuleSpec(
    id="examples",
    title="Examples",
    summary="The scaffold's demonstrations of itself, which no adopter runs.",
    default_on=True,
    scaffold_only=True,
    tool_groups=["example"],
)

PROJECT_SPECS = [PROJECT, TEMPLATE_INIT, UPSTREAM, EXAMPLES]
"""The modules only this repository has, in the order it lays them out.

``PROJECT`` sits first in the composed roster and the rest last, which is
a statement about the document rather than about importance: guidance renders
as the chapter spine crossed with the roster, and this repository's own
framing opens each chapter while what it says about its own tooling closes
them.
"""
