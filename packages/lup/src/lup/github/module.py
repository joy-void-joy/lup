"""`GitHub`, the module: lup's GitHub tools in a launched session, and the gate's issue states in a room."""

from lup.github.stating import Stating
from lup.github.tools import GitHubTools
from lup_dev.declaration.kinds import Handlers, Toolsets
from lup_dev.declaration.module import Module


class GitHub(Module):
    """lup's GitHub tools, and the gate's issue states in a room, through `gh` on the host."""

    name = "github"

    limit: int = 100
    """The most matches `find_issues` asks GitHub for."""
    tools: Toolsets = Toolsets.of(GitHubTools)
    """Reading and finding issues; filing, editing, closing and reopening one;
    commenting and editing a comment; opening a draft pull request."""
    handlers: Handlers = Handlers.of(Stating)
    """Whether an issue is open, which the gate asks from a room."""
