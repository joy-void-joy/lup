"""Retaining authenticated AI conversations for later reading.

One sub-app and the skill that answers from what it retained. It earns a
module rather than folding into core because it is genuinely optional in a way
core is not: a project that never retains a conversation loses a command tree
and a skill it had no use for, which is the whole test a module has to pass.

The skill is here rather than in core because its first step is this module's
command. ``/lup:analyze`` retains a transcript through ``conversation`` and,
where the browser session it needs is missing, sends the operator to ``setup
conversation`` — so a project that declined this module would have shipped a
walkthrough that fails at step one, and the login it names is why the spec
requires ``setup``.
"""

from lup.harness.content.modules.specs import CONVERSATION
from lup.harness.content.skills.analyze import SKILL as SKILL_ANALYZE
from lup.harness.models import ContentRoster
from lup.harness.modules import Module


def module() -> Module:
    """Conversation retention as one value."""
    return Module(spec=CONVERSATION, content=ContentRoster(skills=[SKILL_ANALYZE]))
