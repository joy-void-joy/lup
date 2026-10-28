"""git, run with what could run code turned off, and a commit's files read from its objects.

Every subsystem asks git through `Git`: the judge's store (`policy/store.py`), the
launch (`lup_dev.launch`), and the command line. git runs with `core.fsmonitor`
and hooks turned off, in any repository it's asked about: the effects probe saw a
planted `core.fsmonitor` run inside a call (`docs/field-notes.md`, *Isolation and
effects*). It also ignores replace refs (`--no-replace-objects`): a room writes
`refs/`, so a `refs/replace/` of its own would hand git another blob for an
object whose id `git ls-tree` still lists, and an export of the approved commit,
which trust's fingerprint of those ids calls unchanged, would carry the room's
content to the host. git's `-z` output is read by splitting it on its NUL separators
(`nul_separated`), not through a git library such as dulwich or pygit2, which
`lup_dev` doesn't depend on.

git run in a repository's own git directory is pinned there (`pinning`,
`Git.pinned`): run through `env`, `GIT_DIR` and `GIT_COMMON_DIR` both naming it,
since `lup.programs` replaces a program's environment whole where it's given
one. Named any other way (`--git-dir`, `-C`, `GIT_DIR` alone, or run inside it),
git follows a `commondir` file at its top, which a common git directory never
has and a room can write, to the git directory that file names, and reads that
one's `config` (`docs/field-notes.md`, *Host-side git in a repository the room
writes*).

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

from lup.programs import ProgramError, Ran, run
from lup.types import Model
from lup_dev.errors import LupDevError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


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


def pinning(common: Path) -> list[str]:
    """Return the words before a program that hold the git it is, or runs, to the repository whose common git directory is `common`.

    `env` setting `GIT_DIR` and `GIT_COMMON_DIR` both to `common`, the rest of
    the environment as it is: with both set, git reads no `commondir` there, so
    the only `config` of the repository's it reads is `common`'s own.

    >>> pinning(Path("/r.git"))
    ['env', 'GIT_DIR=/r.git', 'GIT_COMMON_DIR=/r.git']
    """
    return ["env", f"GIT_DIR={common}", f"GIT_COMMON_DIR={common}"]


def stray(objects: Path) -> list[Path]:
    """List what has the object store at `objects` read objects from elsewhere: its alternates files, and every symbolic link in it.

    One look covers every way measured: alternates absolute, relative or nested,
    and a pack linked in from another repository with no alternates at all
    (`docs/field-notes.md`, *Host-side git in a repository the room writes*).
    Where a room writes the store, git the host runs there reads only what it
    holds while this lists nothing. Each directory's listing tells a link
    from its entries, so a store of 129k loose objects takes 0.05 s, where a
    look at each took 0.68 s. A directory that can't be listed is passed over:
    git can't read from it either.
    """
    if objects.is_symlink():
        return [objects]
    alternates = [
        path
        for path in [
            objects / "info" / "alternates",
            objects / "info" / "http-alternates",
        ]
        if path.exists() or path.is_symlink()
    ]

    def linked() -> Iterator[Path]:
        pending = [objects]
        while pending:
            directory = pending.pop()
            try:
                # lup: ignore("os-file-ops", why="a listing's entries tell a link without a look at each, which `Path.walk` then `Path.is_symlink` take for each of a store's loose objects")
                with os.scandir(directory) as listing:
                    entries = list(listing)
            except OSError:
                continue
            for entry in entries:
                if entry.is_symlink():
                    yield directory / entry.name
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(directory / entry.name)

    return [*alternates, *linked()]


class Git(Model):
    """git, run in one place with what could run code turned off."""

    arguments: list[str] = []
    """Arguments before the command: which repository and work tree."""
    cwd: Path
    common: Path | None = None
    """The repository's common git directory, where git is pinned to it
    (`pinning`); none where git finds its own from `cwd` or `arguments`."""
    index: Path | None = None
    """An index git stages in, in place of the worktree's own (`GIT_INDEX_FILE`);
    none for the worktree's."""

    @classmethod
    def pinned(cls, common: Path) -> Git:
        """Return git run in the repository whose common git directory is `common`, pinned there (`pinning`)."""
        return cls(cwd=common, common=common)

    def run(
        self, *arguments: str, stdin: bytes | None = None, ok: list[int] | None = None
    ) -> Ran:
        """Run git with `arguments`; raise `GitError` on an exit status not in `ok`, or where git can't run."""
        safe = [
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "core.quotePath=false",
            "-c",
            "core.autocrlf=false",
        ]
        pinned = [] if self.common is None else pinning(self.common)
        staged = [] if self.index is None else ["env", f"GIT_INDEX_FILE={self.index}"]
        program, *words = [
            *pinned,
            *staged,
            "git",
            *safe,
            *self.arguments,
            *arguments,
        ]
        try:
            return run(program, *words, cwd=self.cwd, stdin=stdin, ok=ok)
        except ProgramError as failed:
            message = f"git {' '.join(arguments)} failed: {failed}"
            raise GitError(message) from failed

    def text(self, *arguments: str) -> str:
        """Run git and return what it printed, without the trailing newline."""
        return self.run(*arguments).output.decode().strip()

    def worktrees(self) -> list[Path]:
        """Return the repository's worktrees, as `git worktree list` gives them: its main one first, a clone's root or a bare repository's own directory."""
        listed = self.run("worktree", "list", "--porcelain", "-z").output
        return [
            Path(field.removeprefix("worktree "))
            for field in nul_separated(listed)
            if field.startswith("worktree ")
        ]

    def main_worktree(self) -> Path:
        """Return the repository's main worktree, which `git worktree list` gives first: a clone's root, or a bare repository's own directory."""
        [main, *_] = self.worktrees()
        return main

    def branch(self) -> str | None:
        """Return the branch the work tree has checked out, by its short name; none on a detached `HEAD`."""
        found = self.run("symbolic-ref", "--short", "-q", "HEAD", ok=[0, 1])
        if found.status != 0:
            return None
        return found.output.decode().strip() or None

    def ignored(self, path: Path) -> bool:
        """Say whether the repository ignores `path`, from the work tree's root: a tracked file never is."""
        found = self.run("check-ignore", "--quiet", "--", str(path), ok=[0, 1])
        return found.status == 0

    def commit(self, revision: str) -> str | None:
        """Return the commit `revision` names, or none where it names none."""
        found = self.run(
            "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}", ok=[0, 1]
        )
        return found.output.decode().strip() if found.status == 0 else None

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
                nul_separated(listed.output), 4, strict=True
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
            self.run("cat-file", "--batch=%(objectsize)", stdin=asked).output
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

    def blobs(self, objects: list[str]) -> list[str]:
        """Return those of `objects`, by id and in order, that the repository's store holds as blobs, asked of one `git cat-file`.

        Never fetched (`--no-lazy-fetch`): a partial clone would ask its
        promisor remote for each object it left out, sending it the id.
        """
        if not objects:
            return []
        asked = "".join(f"{each}\n" for each in objects).encode()
        answered = self.run(
            "--no-lazy-fetch", "cat-file", "--batch-check=%(objecttype)", stdin=asked
        )
        kinds = answered.output.decode().splitlines()
        return [
            each for each, kind in zip(objects, kinds, strict=True) if kind == "blob"
        ]

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
