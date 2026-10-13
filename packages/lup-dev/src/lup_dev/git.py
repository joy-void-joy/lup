"""git, run with what could run code turned off, and a commit's files read from its objects.

Every subsystem asks git through `Git`: the judge's store (`policy/store.py`), the
launch (`lup_dev.launch`), and the command line. git runs with `core.fsmonitor`
and hooks turned off, in any repository it's asked about: the effects probe saw a
planted `core.fsmonitor` run inside a call (`docs/field-notes.md`, *Isolation and
effects*). git's `-z` output is read by splitting it on its NUL separators
(`nul_separated`), not through a git library such as dulwich or pygit2, which
`lup_dev` doesn't depend on.

A commit's files are written out from git's own objects (`Git.export`): each file
`git ls-tree` lists, written from its blob as `git cat-file` gives it. Never
through `git archive`, which applies the repository's `.gitattributes`
(`export-subst` rewrites a file's text, `export-ignore` leaves one out), so its
copy could differ from the commit the operator was shown.
"""

import io
import os
from itertools import batched
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

import sh

from lup.types import Model
from lup_dev.errors import LupDevError

if TYPE_CHECKING:
    from collections.abc import Callable


class GitError(LupDevError):
    """git refused something lup_dev asked of it, or gave a commit lup_dev won't write out."""


def nul_separated(output: bytes) -> list[str]:
    r"""Read git's `-z` output: fields, each ended by a NUL byte.

    >>> nul_separated(b"a.py\x00dir/b c.py\x00")
    ['a.py', 'dir/b c.py']
    """
    # lup: ignore("string-split", why="git's -z format ends each path with a NUL")
    fields = output.split(b"\0")
    return [field.decode() for field in fields if field]


class Tracked(Model):
    """One entry of a commit's tree, as `git ls-tree` lists it."""

    mode: str
    """Its mode, as git writes it: `100644`, `100755`, `120000` for a link,
    `160000` for a submodule."""
    kind: Literal["blob", "tree", "commit"]
    """A file's content, a directory, or a submodule's commit."""
    object: str
    path: PurePosixPath
    """From the repository's root."""


LISTED = "%(objectmode)%x00%(objecttype)%x00%(objectname)%x00%(path)"
"""How `git ls-tree` writes each entry for `Git.tracked`: its fields, each ended
by a NUL byte, as `Tracked` names them."""


def everything(path: PurePosixPath) -> bool:
    """Keep every file of a commit."""
    del path
    return True


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

    def tracked(self, commit: str) -> list[Tracked]:
        """List every entry of `commit`'s tree, its directories walked."""
        listed = self.run(
            "ls-tree", "-r", "-z", "--full-tree", f"--format={LISTED}", commit
        )
        return [
            Tracked.model_validate(
                {"mode": mode, "kind": kind, "object": blob, "path": path}
            )
            for mode, kind, blob, path in batched(
                nul_separated(listed.stdout), 4, strict=True
            )
        ]

    def contents(self, objects: list[str]) -> list[bytes]:
        """Return the content of each of `objects`, in order, read by one `git cat-file`.

        git answers each with its size on a line, the content, then a newline.
        """
        if not objects:
            return []
        asked = "".join(f"{each}\n" for each in objects).encode()
        answered = io.BytesIO(
            self.run("cat-file", "--batch=%(objectsize)", stdin=asked).stdout
        )

        def read(each: str) -> bytes:
            header = answered.readline()
            try:
                size = int(header)
            except ValueError as failed:
                message = f"git cat-file answered {header!r} for {each}, not its size"
                raise GitError(message) from failed
            content = answered.read(size)
            if answered.read(1) != b"\n":
                message = (
                    f"git cat-file's answer for {each} doesn't end where its size says"
                )
                raise GitError(message)
            return content

        return [read(each) for each in objects]

    def export(
        self,
        commit: str,
        into: Path,
        wanted: Callable[[PurePosixPath], bool] = everything,
        batch: int = 512,
    ) -> None:
        """Write each file of `commit` that `wanted` keeps into `into`, from git's objects.

        `batch` files are read from git at a time, so a large commit's content is
        never held whole. A file keeps its executable bit; a link is made as a
        link, and refused, with `GitError`, where it points outside `into`, as is
        a path that would land outside it. A submodule is left out: its files
        aren't the commit's.
        """
        files = [
            each
            for each in self.tracked(commit)
            if each.kind == "blob" and wanted(each.path)
        ]
        into.mkdir(parents=True, exist_ok=True)
        base = into.resolve()

        def written(entry: Tracked, content: bytes) -> None:
            target = base / entry.path
            if not target.resolve().is_relative_to(base):
                message = f"{commit} holds {entry.path}, which lands outside {into}"
                raise GitError(message)
            target.parent.mkdir(parents=True, exist_ok=True)
            match entry.mode:
                case "120000":
                    pointed = Path(content.decode())
                    if pointed.is_absolute() or not (
                        target.parent / pointed
                    ).resolve().is_relative_to(base):
                        message = (
                            f"{commit} holds {entry.path}, a link to {pointed}, "
                            f"outside {into}"
                        )
                        raise GitError(message)
                    target.symlink_to(pointed)
                case "100755":
                    target.write_bytes(content)
                    target.chmod(0o755)
                case _:
                    target.write_bytes(content)

        for chunk in batched(files, batch, strict=False):
            read = self.contents([each.object for each in chunk])
            for entry, content in zip(chunk, read, strict=True):
                written(entry, content)
