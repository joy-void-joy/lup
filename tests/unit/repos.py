"""Throwaway git repositories for the devtools tests that need a real one.

Ten fixtures opened the same way: make a directory, bake a `git` bound to it
with commit signing and the user's own hooks out of the way, initialize a
branch, and set an identity so committing works on a machine that has none.
Only what came after differed. Repeating the opening put eleven lines of
ceremony in front of the two or three that were the test's actual subject, and
a detail like `core.hooksPath` — which keeps a developer's own pre-commit hook
from running inside a fixture — had to be remembered ten times to hold.

The library suite cannot import this module and should not: its own doubles
live in `packages/lup/tests/unit/doubles.py`, because a library test reaching
for a template fixture passes here and fails where the library ships.
"""

from pathlib import Path

import sh

TEST_IDENTITY = {"user.email": "test@example.com", "user.name": "Test"}
"""The committer a throwaway repository commits as.

Carried as `-c` flags on every invocation rather than written once with
`git config`, and that is the whole point of it. A fixture that misbinds and
reaches the enclosing checkout writes nothing: `-c` lives for one command,
where `git config user.email` lands in the repository's shared config, which
every worktree cut from it inherits. It happened — commits made hours later in
other sessions carried a fixture's name until somebody noticed the authorship.
`lup.gitguard` is the check that catches the next one; this is the shape that
stops the identity half from being possible.
"""


def git_in(work: Path, hooks: Path) -> sh.Command:
    """A git bound to one worktree, with signing, hooks, and identity per call."""
    return sh.Command("git").bake(
        "-C",
        str(work),
        "-c",
        "commit.gpgsign=false",
        "-c",
        f"core.hooksPath={hooks}",
        *(
            argument
            for setting, value in TEST_IDENTITY.items()
            for argument in ("-c", f"{setting}={value}")
        ),
        _tty_out=False,
    )


def initialized_repo(work: Path, hooks: Path, branch: str = "main") -> sh.Command:
    """Create `work` as an initialized repository, returning the git bound to it.

    The caller keeps the path it already named and gets back the command, so a
    fixture states the repository it wants rather than how git is invoked.
    """
    work.mkdir(parents=True, exist_ok=True)
    hooks.mkdir(parents=True, exist_ok=True)
    git = git_in(work, hooks)
    git("init", "-b", branch)
    return git


def commit_file(
    git: sh.Command, work: Path, name: str, content: str, message: str
) -> None:
    """Write one file into the worktree and commit it."""
    (work / name).write_text(content, encoding="utf-8")
    git("add", name)
    git("commit", "-m", message)
