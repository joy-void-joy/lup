"""What a session left behind, and what reading it costs.

Three command groups over one subject: the trace a session wrote, what it
spent, and the archive a worktree's records are kept in once the worktree is
gone. No skill and no page — the commands are the whole surface, because
reading a record is not a workflow anybody needs taught.

The archive command sits here rather than beside the other worktree commands
for the reason its own help gives: it copies *session records*, and where they
end up is this module's business even though the directory they leave is git's.
"""

from lup.harness.content.modules.specs import OBSERVABILITY
from lup.harness.modules import Module


def module() -> Module:
    """Session records as one value."""
    return Module(spec=OBSERVABILITY, subapps=["trace", "usage"])
