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

What a commit holds and changes is read from its objects' own bytes (`Git.held`,
`Git.own_changes`), and each blob wherever it's read (`Git.contents`), each hashed
as git hashes one and compared with its id (`Git.verified`), since a room writes
the store and git reads an object by its id without hashing it: what's read
decides what the operator is asked and what the host runs, and the ids alone say
what a commit holds, as a forge reads them (`docs/field-notes.md`, *Host-side git
in a repository the room writes*).
"""

import hashlib
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


type ObjectKind = Literal["blob", "tree", "commit"]
"""What an object of git's store is, as git hashes it."""


def named_by(object_id: str, kind: ObjectKind, content: bytes) -> bool:
    """Say whether `object_id` is the id git gives an object of `kind` holding `content`, in a repository of either hash: an id's length is its hash's.

    >>> named_by("e69de29bb2d1d6434b8b29ae775ad8c2e48c5391", "blob", b"")
    True
    >>> named_by("e69de29bb2d1d6434b8b29ae775ad8c2e48c5391", "blob", b"x")
    False
    """
    framed = b"".join([f"{kind} {len(content)}".encode(), b"\0", content])
    ids = [
        hashlib.sha1(framed, usedforsecurity=False).hexdigest(),
        hashlib.sha256(framed, usedforsecurity=False).hexdigest(),
    ]
    return object_id in ids


def tree_entries(content: bytes, under: PurePosixPath, width: int) -> Iterator[Tracked]:
    r"""Read a tree object's bytes, each entry its mode, a space, its name, a NUL and its id's `width` bytes, as entries of the tree at `under`.

    >>> found = tree_entries(b"100644 a\x00" + bytes(20), PurePosixPath("d"), 20)
    >>> [(each.mode, each.kind, str(each.path)) for each in found]
    [('100644', 'blob', 'd/a')]
    """
    reader = io.BytesIO(content)

    def until(end: bytes) -> bytes:
        return b"".join(
            iter(lambda: b"" if (byte := reader.read(1)) == end else byte, b"")
        )

    while mode := os.fsdecode(until(b" ")):
        name = os.fsdecode(until(b"\0"))
        yield Tracked(
            mode=mode,
            kind="tree"
            if mode == "40000"
            else "commit"
            if mode == "160000"
            else "blob",
            object=reader.read(width).hex(),
            path=under / name,
        )


class Parted(Model):
    """A directory where two commits' trees part, from the repository's root: each side's tree there, none where a side has no directory there."""

    under: PurePosixPath
    was: str | None
    now: str | None


class TreeChange(Model):
    """A file two commits' trees differ in: its path, and its entry in the later, none where it's gone there."""

    path: PurePosixPath
    entry: Tracked | None


def parting(
    path: PurePosixPath, old: Tracked | None, new: Tracked | None
) -> Iterator[Parted | TreeChange]:
    """Say what two trees differing at `path`, as `old` and `new`, come to there: a directory on either side to read further, and the file on either side, as it is in `new` or gone from it."""
    was = None if old is None or old.kind != "tree" else old.object
    now = None if new is None or new.kind != "tree" else new.object
    if was is not None or now is not None:
        yield Parted(under=path, was=was, now=now)
    if new is not None and now is None:
        yield TreeChange(path=path, entry=new)
    if old is not None and was is None and (new is None or now is not None):
        yield TreeChange(path=path, entry=None)


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

    def checkout(self, branch: str) -> Path | None:
        """Return the worktree that has `branch` checked out, as `git worktree list` gives it; none where none does, or the one that did is gone."""
        listed = self.run("worktree", "list", "--porcelain", "-z").output
        found: Path | None = None
        for field in nul_separated(listed):
            if field.startswith("worktree "):
                found = Path(field.removeprefix("worktree "))
            if field == f"branch refs/heads/{branch}" and found is not None:
                return found if found.is_dir() else None
        return None

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

    def held(self, commit: str) -> list[Tracked]:
        """List every entry of `commit`'s tree, its directories walked, as `tracked` lists them and in its order, from each object's own bytes (`own_changes`): raise `GitError` where it names no commit, or an object can't be read or isn't what its id says."""
        found = self.commit(commit)
        if found is None:
            message = f"{commit} names no commit"
            raise GitError(message)
        entries = [
            entry
            for entry in self.own_changes(None, found).values()
            if entry is not None
        ]
        return sorted(entries, key=lambda entry: os.fsencode(entry.path))

    def contents(self, objects: list[str]) -> list[bytes]:
        """Return the content of each blob of `objects`, in order, each hashed against its id (`verified`), read by one `git cat-file`: raise `GitError` where one isn't what its id says, or git can't read it."""
        return self.verified("blob", objects)

    def stored(self, objects: list[str]) -> list[bytes]:
        """Return what the store holds under each of `objects`, in order, read by one `git cat-file`, as it stands: only what checks it reads this.

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

    def verified(self, kind: ObjectKind, objects: list[str]) -> list[bytes]:
        """Return the content of each of `objects`, each an object of `kind`, in order, each hashed as git hashes one: raise `GitError` where one isn't what its id says, or git can't read it."""
        contents = self.stored(objects)
        unlike = [
            each
            for each, content in zip(objects, contents, strict=True)
            if not named_by(each, kind, content)
        ]
        if unlike:
            named = ", ".join(unlike)
            message = f"what the repository's store holds as {named} isn't that {kind}"
            raise GitError(message)
        return contents

    def own_changes(
        self, before: str | None, after: str
    ) -> dict[PurePosixPath, Tracked | None]:
        """Return each file the commit `after` changes against the commit `before`, or each it holds where that's none, from the repository's root, with its entry in `after`, none where it deleted it: read from each object's own bytes, one `git cat-file` a level, only where the two trees' ids part (`verified`).

        A directory replaced by a file, or the other way, is each of its files
        changed and the file. Raise `GitError` where an object can't be read or
        isn't what its id says.
        """
        width = len(after) // 2
        commits = [each for each in [before, after] if each is not None]
        contents = self.verified("commit", commits)
        trees = {
            commit: io.BytesIO(content)
            .readline()
            .removeprefix(b"tree ")
            .strip()
            .decode()
            for commit, content in zip(commits, contents, strict=True)
        }

        def walked(pending: list[Parted]) -> Iterator[TreeChange]:
            if not pending:
                return
            wanted = list(
                dict.fromkeys(
                    each
                    for parted in pending
                    for each in [parted.was, parted.now]
                    if each is not None
                )
            )
            read = dict(zip(wanted, self.verified("tree", wanted), strict=True))

            def listed(tree: str | None, under: PurePosixPath) -> dict[str, Tracked]:
                if tree is None:
                    return {}
                found = tree_entries(read[tree], under, width)
                return {str(each.path): each for each in found}

            def compared(parted: Parted) -> Iterator[Parted | TreeChange]:
                was = listed(parted.was, parted.under)
                now = listed(parted.now, parted.under)
                for named in was.keys() | now.keys():
                    if was.get(named) != now.get(named):
                        yield from parting(
                            PurePosixPath(named), was.get(named), now.get(named)
                        )

            found = [each for parted in pending for each in compared(parted)]
            yield from (each for each in found if isinstance(each, TreeChange))
            yield from walked([each for each in found if isinstance(each, Parted)])

        root = Parted(
            under=PurePosixPath(),
            was=None if before is None else trees[before],
            now=trees[after],
        )
        return {each.path: each.entry for each in walked([root])}

    def walked(self, sources: list[str], has: list[str]) -> list[str]:
        """Return each commit `sources` reach that `has` don't, oldest first: what a push of `sources` publishes to a remote holding `has`.

        An object the store lacks is skipped (`--ignore-missing`), so a listing
        naming one the room never fetched checks more, never less.
        """
        asked = "".join(
            [*(f"{each}\n" for each in sources), *(f"^{each}\n" for each in has)]
        )
        listed = self.run(
            "rev-list",
            "--reverse",
            "--topo-order",
            "--ignore-missing",
            "--stdin",
            stdin=asked.encode(),
        )
        return listed.output.decode().splitlines()

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
        """Write each file of `commit` that `wanted` keeps into `into`, from git's objects, each what its id says (`held`, `contents`), so only the ids a commit names are written.

        `batch` files are read from git at a time, so a large commit's content is
        never held whole. A file keeps its executable bit; a link is made as a
        link, and refused, with `GitError`, where it points outside `into`, as is
        a path that would land outside it. A submodule is left out: its files
        aren't the commit's.
        """
        files = [
            each
            for each in self.held(commit)
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
