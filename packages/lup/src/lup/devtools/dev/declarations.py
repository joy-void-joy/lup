"""What every workflow command tree reads about the repository it runs in.

Its own module because it is read by more than one of them. The commands lup
ships are grouped by the module that owns them — the quality gate and the
scans under ``dev``, the branch and worktree loop under ``git``, a resolver run
under ``resolve`` — and each of those factories is wired over this same
declaration, so leaving it beside any one of them would make the other two
import that one for a type.
"""

from pydantic import BaseModel

import lup.devtools.dev.check as check
import lup.devtools.dev.git_guards as git_guards_mod
from lup.devtools.project import DevProject
from lup.harness.models import HookSet, Plugin


class DevDeclarations(BaseModel, frozen=True):
    """Everything the workflow trees read about the repository they run in.

    Read when a command runs rather than when the CLI is composed: each of
    these resolves against the working directory, and a CLI is imported long
    before anyone knows which repository it will be pointed at.
    """

    project: DevProject
    hooks: HookSet
    plugin: Plugin
    test_roots: list[check.TestRoot]
    git_guards: list[git_guards_mod.GitGuard] = git_guards_mod.DECLARED_GUARDS
    """Which checks this repository installs as git hooks.

    A default rather than a fixture: the pair lup arms is what most projects
    want, and one that guards a third moment — or runs its gate under another
    name — says so here instead of forking the module that writes them."""
