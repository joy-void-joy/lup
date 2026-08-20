# lup: ignore[constant-declaration]
# Every constant here is this repository's own composition — which skills and
# agents its plugin ships, and what that plugin is called. A composition root
# is where a judgement is finally made rather than passed on, so there is no
# caller above it to take these from.
"""This repository's harness content: what it inherits, and what only it has.

The skills automating agent work come from the library. Declared here are the
six whose subject is a lup-based project rather than the work inside one —
standing one up, installing the plugin into it, importing from a downstream
repo, and keeping the whole thing in step with upstream — plus the composed
rosters every document and the compiled plugin read.

This is also where the library learns what this application is called. Several
of its skills name a path inside the reading project's own package, and only
the project knows that name, so it is supplied here rather than assumed there.
"""

from pathlib import Path

import lup.harness.models as models
from lup.devtools.harness.content.application import ApplicationLayout
from lup.devtools.harness.content.catalog import library_content
from lup_template.devtools.harness.content.skills.brainstorm import (
    SKILL as SKILL_BRAINSTORM,
)
from lup_template.devtools.harness.content.skills.import_skill import (
    SKILL as SKILL_IMPORT,
)
from lup_template.devtools.harness.content.skills.init import SKILL as SKILL_INIT
from lup_template.devtools.harness.content.skills.install import SKILL as SKILL_INSTALL
from lup_template.devtools.harness.content.skills.meta import SKILL as SKILL_META
from lup_template.devtools.harness.content.skills.update import SKILL as SKILL_UPDATE

LAYOUT = ApplicationLayout(package=Path(__file__).resolve().parents[3].name)
"""Where this application's own code sits, for the library prose that names it.

Derived from where this file actually sits rather than written down, for the
reason ``DevProject.package`` derives its own: initialization renames the
package, and a literal would go on naming one that is gone.
"""

PROJECT_SKILLS = [
    SKILL_BRAINSTORM,
    SKILL_IMPORT,
    SKILL_INIT,
    SKILL_INSTALL,
    SKILL_META,
    SKILL_UPDATE,
]
"""The skills only this repository has, because only it is a template.

Each one's subject is standing up or maintaining a lup-based project — they
have nothing to say inside one, which is why they stay behind when the rest
of the roster becomes the library's.
"""

PROJECT_AGENTS: list[models.Agent] = []
"""No agent here is about being a template; the whole roster is the library's."""

RETIRED = models.ContentSelection()
"""Which of lup's own skills and agents this repository does not ship.

Empty, because lup authors them: a template retiring its own declaration
should delete it rather than carry one it declines to ship. The seat is here
so a project adopting this scaffold states its delta in one line instead of
restating the roster it inherits — and so `dev check` can name what it
declined, which a rewritten list could never surface."""

CONTENT = (
    library_content(LAYOUT).selected(RETIRED).extended(PROJECT_SKILLS, PROJECT_AGENTS)
)
"""Everything this repository's plugin ships, inherited half first."""

SKILLS = CONTENT.skills
"""Every skill this repository's plugin ships."""

AGENTS = CONTENT.agents
"""Every agent this repository's plugin ships."""

PLUGIN_NAME: models.NativeName = "lup"
"""The plugin every declared skill is invoked through.

Named here rather than read off the harness because the roster documents are
compiled into that harness: reading it back to render them would close the
loop between what is declared and what describes the declaration.
"""
