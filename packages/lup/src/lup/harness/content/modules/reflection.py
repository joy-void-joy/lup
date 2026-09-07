"""The gate an agent meets on its own output.

One tool group, holding one tool: a structured self-review called after the
work is done and before the output is submitted, which runs an independent
reviewer and holds the submission until it passes. Approve and warn open the
gate; fail keeps it closed so the agent revises; after three consecutive fails
it opens anyway, because a gate that can never open is a hang rather than a
standard.

Not the feedback loop, though the group's name invites the confusion. That
loop reads finished sessions and changes a capability; this runs inside one
session and changes an answer before anybody sees it. Neither imports the
other, and a project can sensibly have either alone.

Off by default: a domain agent whose output nobody submits — a CLI, a
generator — meets this gate on every turn and has nothing for it to judge.
"""

from lup.harness.content.modules.specs import REFLECTION
from lup.harness.modules import Module


def module() -> Module:
    """Self-review as one value."""
    return Module(spec=REFLECTION, tool_groups=["notes"])
