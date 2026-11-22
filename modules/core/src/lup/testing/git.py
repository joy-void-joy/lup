"""git, run for real for a promise, on scratch repositories it makes: the one stand-in for git a module's promises take.

A promise about what lup asks git is checked against git itself, rather than a
script of its answers by their arguments, which breaks as soon as lup asks git
otherwise and says what its writer thought git would. git is quick enough for
it, a repository made, a commit and a few reads taking milliseconds. It reads
no configuration of the machine's or the operator's, each commit's author and
time are the same at every run, so its id is too, and it reaches nothing but
files (`README.md` here, *The harness*).
"""

import os
lazy from pathlib import Path

from lup.programs.waited import run
from lup.testing.harness import Acting, Answering
from lup.types import Model


class RealGit(Model, Acting):
    """git, run for real: for a part, as each run asks, and for the promise itself, making and changing its scratch repositories."""

    variables: dict[str, str] = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "Agent",
        "GIT_AUTHOR_EMAIL": "agent@localhost",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
        "GIT_COMMITTER_NAME": "Agent",
        "GIT_COMMITTER_EMAIL": "agent@localhost",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
        "GIT_ALLOW_PROTOCOL": "file",
        "GIT_TERMINAL_PROMPT": "0",
    }
    """The variables every run is given, beside what a run sets itself: no
    configuration read, the machine's or the operator's; who wrote each commit
    and when, the same at every run; and no remote reached but by a path."""

    def ran(
        self,
        arguments: list[str],
        given: bytes | None,
        env: dict[str, str],
        cwd: Path | None,
    ) -> Answering:
        """Run git as a part asks, with the variables and from the directory the run gives, and answer how it ended."""
        pinned = [
            f"{name}={value}" for name, value in {**self.variables, **env}.items()
        ]
        done = run(
            "env", *pinned, "git", *arguments, cwd=cwd, stdin=given, checked=False
        )
        return Answering(status=done.status, output=done.output, error=done.error)

    def git(self, *arguments: str, cwd: Path, given: bytes | str | None = None) -> str:
        """Run git for the promise itself, from `cwd`, as an agent would in their worktree, and return what it printed, its last newline left out.

        Raise `lup.programs.ProgramFailedError` where it fails.
        """
        pinned = [f"{name}={value}" for name, value in self.variables.items()]
        return run("env", *pinned, "git", *arguments, cwd=cwd, stdin=given).text()

    def made(self, root: Path, *, bare: bool = False) -> Path:
        """Make a repository at `root`, its first branch `dev`: a clone's worktree, or a bare repository where `bare`; and return `root`."""
        root.mkdir(parents=True, exist_ok=True)
        self.git(
            "init",
            "--quiet",
            "--initial-branch=dev",
            *(["--bare"] if bare else []),
            ".",
            cwd=root,
        )
        return root

    def committed(
        self, worktree: Path, files: dict[str, str], message: str = "files"
    ) -> str:
        """Write each of `files`, by its path from the worktree's root, then commit every change in the worktree, and return the commit."""
        for path, text in files.items():
            written = worktree / path
            written.parent.mkdir(parents=True, exist_ok=True)
            written.write_text(text)
        self.git("add", "--all", cwd=worktree)
        self.git(
            "commit", "--quiet", "--allow-empty", "--message", message, cwd=worktree
        )
        return self.git("rev-parse", "HEAD", cwd=worktree)
