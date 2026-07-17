"""Explicit aggregation of canonical harness content declarations."""

from lup_template.devtools.harness.content.skills.add_command import (
    SKILL as SKILL_ADD_COMMAND,
)
from lup_template.devtools.harness.content.skills.brainstorm import (
    SKILL as SKILL_BRAINSTORM,
)
from lup_template.devtools.harness.content.skills.bump import SKILL as SKILL_BUMP
from lup_template.devtools.harness.content.skills.clean_gone import (
    SKILL as SKILL_CLEAN_GONE,
)
from lup_template.devtools.harness.content.skills.close import SKILL as SKILL_CLOSE
from lup_template.devtools.harness.content.skills.commit import SKILL as SKILL_COMMIT
from lup_template.devtools.harness.content.skills.create_investigator import (
    SKILL as SKILL_CREATE_INVESTIGATOR,
)
from lup_template.devtools.harness.content.skills.debug import SKILL as SKILL_DEBUG
from lup_template.devtools.harness.content.skills.fb_analyze import (
    SKILL as SKILL_FB_ANALYZE,
)
from lup_template.devtools.harness.content.skills.fb_implement import (
    SKILL as SKILL_FB_IMPLEMENT,
)
from lup_template.devtools.harness.content.skills.fb_investigate import (
    SKILL as SKILL_FB_INVESTIGATE,
)
from lup_template.devtools.harness.content.skills.fb_reflect import (
    SKILL as SKILL_FB_REFLECT,
)
from lup_template.devtools.harness.content.skills.fb_status import (
    SKILL as SKILL_FB_STATUS,
)
from lup_template.devtools.harness.content.skills.feedback_loop import (
    SKILL as SKILL_FEEDBACK_LOOP,
)
from lup_template.devtools.harness.content.skills.hooks import SKILL as SKILL_HOOKS
from lup_template.devtools.harness.content.skills.import_skill import (
    SKILL as SKILL_IMPORT,
)
from lup_template.devtools.harness.content.skills.init import SKILL as SKILL_INIT
from lup_template.devtools.harness.content.skills.install import SKILL as SKILL_INSTALL
from lup_template.devtools.harness.content.skills.merge import SKILL as SKILL_MERGE
from lup_template.devtools.harness.content.skills.meta import SKILL as SKILL_META
from lup_template.devtools.harness.content.skills.modify_command import (
    SKILL as SKILL_MODIFY_COMMAND,
)
from lup_template.devtools.harness.content.skills.principle import (
    SKILL as SKILL_PRINCIPLE,
)
from lup_template.devtools.harness.content.skills.rebase import SKILL as SKILL_REBASE
from lup_template.devtools.harness.content.skills.refactor import (
    SKILL as SKILL_REFACTOR,
)
from lup_template.devtools.harness.content.skills.refactor_tools import (
    SKILL as SKILL_REFACTOR_TOOLS,
)
from lup_template.devtools.harness.content.skills.resolve import SKILL as SKILL_RESOLVE
from lup_template.devtools.harness.content.skills.review import SKILL as SKILL_REVIEW
from lup_template.devtools.harness.content.skills.update import SKILL as SKILL_UPDATE
from lup_template.devtools.harness.content.skills.implementer import (
    SKILL as SKILL_IMPLEMENTER,
)
from lup_template.devtools.harness.content.skills.resolve_reviewer import (
    SKILL as SKILL_RESOLVE_REVIEWER,
)
from lup_template.devtools.harness.content.agents.implementer import (
    AGENT as AGENT_IMPLEMENTER,
)
from lup_template.devtools.harness.content.agents.resolve_editor import (
    AGENT as AGENT_RESOLVE_EDITOR,
)
from lup_template.devtools.harness.content.agents.trace_explorer import (
    AGENT as AGENT_TRACE_EXPLORER,
)
from lup_template.devtools.harness.content.agents.version_explorer import (
    AGENT as AGENT_VERSION_EXPLORER,
)
from lup_template.devtools.harness.content.agents.version_reviewer import (
    AGENT as AGENT_VERSION_REVIEWER,
)

SKILLS = [
    SKILL_ADD_COMMAND,
    SKILL_BRAINSTORM,
    SKILL_BUMP,
    SKILL_CLEAN_GONE,
    SKILL_CLOSE,
    SKILL_COMMIT,
    SKILL_CREATE_INVESTIGATOR,
    SKILL_DEBUG,
    SKILL_FB_ANALYZE,
    SKILL_FB_IMPLEMENT,
    SKILL_FB_INVESTIGATE,
    SKILL_FB_REFLECT,
    SKILL_FB_STATUS,
    SKILL_FEEDBACK_LOOP,
    SKILL_HOOKS,
    SKILL_IMPORT,
    SKILL_INIT,
    SKILL_INSTALL,
    SKILL_MERGE,
    SKILL_META,
    SKILL_MODIFY_COMMAND,
    SKILL_PRINCIPLE,
    SKILL_REBASE,
    SKILL_REFACTOR,
    SKILL_REFACTOR_TOOLS,
    SKILL_RESOLVE,
    SKILL_REVIEW,
    SKILL_UPDATE,
    SKILL_IMPLEMENTER,
    SKILL_RESOLVE_REVIEWER,
]

AGENTS = [
    AGENT_IMPLEMENTER,
    AGENT_RESOLVE_EDITOR,
    AGENT_TRACE_EXPLORER,
    AGENT_VERSION_EXPLORER,
    AGENT_VERSION_REVIEWER,
]

# lup: For instance, the CLAUDE.md and AGENTS.md could generate their tool list programatically now