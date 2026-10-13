"""git, run with what could run code turned off.

Every subsystem asks git through `Git`: the judge's store (`policy/store.py`), the
launch (`lup_dev.launch`), and the command line. git runs with `core.fsmonitor`
and hooks turned off, in any repository it's asked about: the effects probe saw a
planted `core.fsmonitor` run inside a call (`docs/field-notes.md`, *Isolation and
effects*). git's `-z` output is read by splitting it on its NUL separators
(`nul_separated`), not through a git library such as dulwich or pygit2, which
`lup_dev` doesn't depend on.
"""

import os
from pathlib import Path

import sh

from lup.types import Model
from lup_dev.errors import LupDevError


class GitError(LupDevError):
    """git refused something lup_dev asked of it."""


def nul_separated(output: bytes) -> list[str]:
    r"""Read git's `-z` output: fields, each ended by a NUL byte.

    >>> nul_separated(b"a.py\x00dir/b c.py\x00")
    ['a.py', 'dir/b c.py']
    """
    # lup: ignore("string-split", why="git's -z format ends each path with a NUL")
    fields = output.split(b"\0")
    return [field.decode() for field in fields if field]


class Git(Model):
    """git, run in one place with what could run code turned off."""

    arguments: list[str] = []
    """Arguments before the command: which repository and work tree."""
    cwd: Path

    def run(
        self, *arguments: str, stdin: bytes | None = None, ok: list[int] | None = None
    ) -> sh.RunningCommand:
        """Run git with `arguments`; raise `GitError` on an exit code not in `ok`."""
        safe = [
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "core.quotePath=false",
            "-c",
            "core.autocrlf=false",
        ]
        try:
            return sh.Command("git")(
                *safe,
                *self.arguments,
                *arguments,
                _in=stdin,
                _cwd=str(self.cwd),
                _ok_code=ok or [0],
                _tty_out=False,
                _return_cmd=True,
            )
        except sh.ErrorReturnCode as failed:
            message = f"git {' '.join(arguments)} failed: {failed.stderr.decode()}"
            raise GitError(message) from failed

    def text(self, *arguments: str) -> str:
        """Run git and return what it printed, without the trailing newline."""
        return self.run(*arguments).stdout.decode().strip()

    def commit(self, revision: str) -> str | None:
        """Return the commit `revision` names, or none where it names none."""
        found = self.run(
            "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}", ok=[0, 1]
        )
        return found.stdout.decode().strip() if found.exit_code == 0 else None
