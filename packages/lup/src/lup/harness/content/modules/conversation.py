"""Retaining authenticated AI conversations for later reading.

One sub-app and nothing else. It earns a module rather than folding into core
because it is genuinely optional in a way core is not: a project that never
retains a conversation loses a command tree and no capability it had a use
for, which is the whole test a module has to pass.
"""

from lup.harness.content.modules.specs import CONVERSATION
from lup.harness.modules import Module


def module() -> Module:
    """Conversation retention as one value."""
    return Module(spec=CONVERSATION)
