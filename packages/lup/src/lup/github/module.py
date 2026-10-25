"""`GitHub`, the module: lup's GitHub tools in a launched session, and the gate's issue states in a room."""

from lup.github.serving import GitHubServing
from lup_dev.declaration.kinds import Serving
from lup_dev.declaration.module import Module


class GitHub(Module):
    """lup's GitHub tools, and the gate's issue states in a room, through `gh` on the host."""

    name = "github"

    serving: Serving = Serving.of(GitHubServing)
    """Reading and finding issues; filing, editing, closing and reopening one;
    commenting and editing a comment; opening a draft pull request; and whether
    an issue is open, which the gate asks from a room."""
