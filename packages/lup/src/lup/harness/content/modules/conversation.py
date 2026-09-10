"""Retaining authenticated AI conversations for later reading.

One sub-app and the skill that drives it, nothing else. It earns a module
rather than folding into core because it is genuinely optional in a way core
is not: a project that never retains a conversation loses a command tree, the
skill that runs it, and no capability it had a use for, which is the whole
test a module has to pass. The skill sits here rather than in core because a
skill that instructs a command belongs to the module serving the command: a
project that declined this one would otherwise carry a skill telling it to
run a command it does not have.
"""

from lup.harness.content.modules.specs import CONVERSATION
from lup.harness.content.skills.analyze import SKILL as SKILL_ANALYZE
from lup.harness.models import ContentRoster
from lup.harness.modules import Module


def module() -> Module:
    """Conversation retention as one value."""
    return Module(spec=CONVERSATION, content=ContentRoster(skills=[SKILL_ANALYZE]))
