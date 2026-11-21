"""git's companion to `lup.programs`: one place where lup runs git and reads what it answers, for every module.

A module asks git through it rather than running git itself: where a worktree
is and what its files are (`Git.located`, `Worktree`), what a repository a room
writes holds, git pinned to it (`Git.pinned`, `Store`), and what git does
outside any repository (`Git.initialised`, `Git.apart`, `Git.cloned`,
`Git.diffed`). Each question is a method running one git command, hardened and
held to a time, and reading its answer into a model or a value, so no caller
writes git's arguments or takes its output apart. A part passes its own git
program (`through=self.git`), which a promise stands in; lup's own code outside
any part passes none, and git runs through `lup.programs`. Its reasons are in
`README.md` here.
"""

from lup.programs.git.objects import Entry, Kind, named_by
from lup.programs.git.running import Git, GitError
from lup.programs.git.stores import Merged, Store, UnverifiedError
from lup.programs.git.worktrees import Worktree

__all__ = [
    "Entry",
    "Git",
    "GitError",
    "Kind",
    "Merged",
    "Store",
    "UnverifiedError",
    "Worktree",
    "named_by",
]
