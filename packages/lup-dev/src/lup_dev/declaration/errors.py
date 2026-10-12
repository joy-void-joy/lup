"""What the declaration raises when a project's declaration is wrong."""

from lup_dev.errors import LupDevError


class ProjectError(LupDevError):
    """A project's declaration can't be loaded, or doesn't resolve.

    One error for every way a declaration is wrong, whether it's found while
    importing `lup_project.py` (a module edited with another module's class), while
    loading it (no `project`, or not a `Project`), or while resolving it (a name
    that isn't there, a required module missing): a reader catches this one alone
    to stand in the last declaration that loaded.
    """
