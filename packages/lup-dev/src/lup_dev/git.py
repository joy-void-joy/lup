"""git, run with what could run code turned off, and a commit's files read from its objects.

Every subsystem asks git through `Git`: the judge's store (`policy/store.py`), the
launch (`lup_dev.launch`), and the command line. git runs with `core.fsmonitor`
and hooks turned off, in any repository it's asked about: the effects probe saw a
planted `core.fsmonitor` run inside a call (`docs/field-notes.md`, *Isolation and
effects*). It also ignores replace refs (`--no-replace-objects`): a room writes
`refs/`, so a `refs/replace/` of its own would hand git another blob for an
object whose id `git ls-tree` still lists, and an export of the approved commit,
which trust's fingerprint of those ids calls unchanged, would carry the room's
content to the host. It reads each commit's parents and tree from the commit
alone, rather than `info/grafts` or `objects/info/commit-graph`, which a room
writes too and git reads first (`ungrafted`, `graphless`). git's `-z` output is
read by splitting it on its NUL separators
(`nul_separated`), not through a git library such as dulwich or pygit2, which
`lup_dev` doesn't depend on.

git run in a repository's own git directory is pinned there (`pinning`,
`Git.pinned`): run through `env`, `GIT_DIR` and `GIT_COMMON_DIR` both naming it,
since `lup.programs` replaces a program's environment whole where it's given
one. Named any other way (`--git-dir`, `-C`, `GIT_DIR` alone, or run inside it),
git follows a `commondir` file at its top, which a common git directory never
has and a room can write, to the git directory that file names, and reads that
one's `config` (`docs/field-notes.md`, *Host-side git in a repository the room
writes*). git run in one of its worktrees is pinned there the same way, the
worktree's own git directory and its root named too (`Git.within`), so the
`config` it reads is the common git directory's own, whatever the worktree's
`.git` file and `commondir`, both the room's to write, say.

A repository's worktrees are those `git worktree list` gives that name each
other with it (`Git.listed`): the main one, which git derives from the common
git directory's own path, and each linked one whose `.git` file names its entry
under `worktrees/` back. git lists a linked worktree from that entry's `gitdir`
alone, a file the room writes, so a room could have it list any directory, the
one holding the repository among them, as a worktree; the worktree's `.git`
file, outside the room's mounts, is the half it can't write.

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

Every git `Git` runs is killed past a time limit (`Git.limit`), since a room
can make a ref a FIFO in which git waits for good. A service running git off
its event loop runs it in threads of the repository's own (`threaded`), never
asyncio's default pool: a room slowing git on its repository then holds that
repository's threads alone, never those the rest of the service waits on.
"""

import asyncio
import contextvars
import functools
import hashlib
import io
import os
import shlex
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from itertools import batched
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from lup.programs import ProgramError, ProgramOverdueError, Ran, run
from lup.types import Model, MutableModel
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


def ungrafted() -> list[str]:
    """Return the words before git that have it read grafts from an empty file, rather than the `info/grafts` a room writes, which it reads a commit's parents from first.

    >>> ungrafted()
    ['env', 'GIT_GRAFT_FILE=/dev/null']
    """
    return ["env", f"GIT_GRAFT_FILE={os.devnull}"]


def graphless() -> list[str]:
    """Return the options that have git read no commit-graph, which a room writes under `objects/info/` and git reads a commit's parents and tree from first, and leave out the hint it gives wherever a graft file is named."""
    return ["-c", "core.commitGraph=false", "-c", "advice.graftFileDeprecated=false"]


def pinning(common: Path, worktree: Worktree | None = None) -> list[str]:
    """Return the words before a program that hold the git it is, or runs, to the repository whose common git directory is `common`, and to `worktree` of it where one is given.

    `env` setting `GIT_DIR` and `GIT_COMMON_DIR` both to `common`, the rest of
    the environment as it is: with both set, git reads no `commondir` there, so
    the only `config` of the repository's it reads is `common`'s own. In a
    worktree, `GIT_DIR` is its own git directory, a linked one's under
    `worktrees/`, and `GIT_WORK_TREE` its root, so git doesn't follow its
    `.git` file, and reads `common`'s `config` whatever its `commondir` says.
    git's ref store still reads a `commondir` itself, for refs, which the room
    writes anyway.

    >>> pinning(Path("/r.git"))
    ['env', 'GIT_DIR=/r.git', 'GIT_COMMON_DIR=/r.git']
    >>> pinning(Path("/r.git"), Worktree(root=Path("/r.git/tree/a"), own=Path("/r.git/worktrees/a")))[1:]
    ['GIT_DIR=/r.git/worktrees/a', 'GIT_COMMON_DIR=/r.git', 'GIT_WORK_TREE=/r.git/tree/a']
    """
    if worktree is None:
        return ["env", f"GIT_DIR={common}", f"GIT_COMMON_DIR={common}"]
    return [
        "env",
        f"GIT_DIR={worktree.own or common}",
        f"GIT_COMMON_DIR={common}",
        f"GIT_WORK_TREE={worktree.root}",
    ]


class Worktree(Model):
    """One of a repository's worktrees, as `git worktree list` gives it, where it names the repository back (`linked`)."""

    root: Path
    own: Path | None = None
    """A linked worktree's own git directory, `<common>/worktrees/<id>`, which
    its `.git` file names; none for the main one, whose git directory is the
    common one."""
    branch: str | None = None
    """The branch it has checked out, by its ref's full name; none on a detached
    `HEAD`, and for a bare repository's own directory."""
    head: str | None = None
    """The commit its `HEAD` names; none before the repository's first."""


def link_file(path: Path, largest: int = 4096) -> str | None:
    """Return what the regular file at `path` holds, never following a link at its name or waiting on a pipe; none where it isn't one, or holds more than `largest` bytes, or what isn't text.

    A worktree's `.git` file and its entry's `gitdir` each hold one path, so
    a larger one names no worktree.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        reading = os.open(path, flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(reading).st_mode):
            return None
        content = os.read(reading, largest + 1)
    finally:
        os.close(reading)
    if len(content) > largest:
        return None
    try:
        return content.decode()
    except UnicodeDecodeError:
        return None


def lexical(path: Path) -> Path:
    """Return `path` with each `..` taken with the part before it, as its text says, following no link.

    >>> lexical(Path("/r.git/tree/a/../../worktrees/a"))
    PosixPath('/r.git/worktrees/a')
    """
    # lup: ignore("os-path", why="pathlib has no lexical `..`, and `Path.resolve` would follow a link the room makes in the paths it writes")
    return Path(os.path.normpath(path))


def linked(common: Path, root: Path) -> Path | None:
    """Return the own git directory of the linked worktree git lists at `root`, in the repository whose common git directory is `common`, where the two name each other; none where they don't.

    git lists a linked worktree from `<common>/worktrees/<id>/gitdir` alone,
    which the room writes, so a room could have it list any directory. Kept
    only where, as `git worktree add` writes them:
    - `root` is the directory's own path, with no link or `..` in it, so
      neither a link outside the tree leading into it nor a path out of it
      through `..` is read as a worktree;
    - its `.git` is a regular file reading `gitdir: <common>/worktrees/<id>`,
      `<common>` with its links resolved, as git writes it, or that path
      relative to `root`;
    - and `<common>/worktrees/<id>/gitdir` names `root`'s `.git` back,
      absolute or relative to that entry.

    The room writes the entry; the `.git` file is the half it can't write
    where it isn't mounted. The main worktree has no `.git` file to check: git
    derives it from `common`'s own path, pinned there, never from a file the
    room writes.
    """
    if not root.is_absolute() or root.resolve() != root:
        return None
    gitfile = link_file(root / ".git")
    if gitfile is None or not gitfile.startswith("gitdir: "):
        return None
    own = lexical(root / gitfile.removeprefix("gitdir: ").strip())
    if own.parent != common.resolve() / "worktrees":
        return None
    back = link_file(own / "gitdir")
    if back is None or lexical(own / back.strip()) != root / ".git":
        return None
    return own


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


def refs_astray(git: Git) -> str | None:
    """Say why git mustn't write a ref of the repository: a link under its `refs/`, which it would write through, and a room writes `refs/`; none where there's none (`stray`), or `git` isn't pinned to the repository."""
    found = [] if git.common is None else stray(git.common / "refs")
    if not found:
        return None
    return f"its refs hold a link, {', '.join(str(each) for each in found)}"


class Git(Model):
    """git, run in one place with what could run code turned off."""

    arguments: list[str] = []
    """Arguments before the command: which repository and work tree."""
    cwd: Path
    common: Path | None = None
    """The repository's common git directory, where git is pinned to it
    (`pinning`); none where git finds its own from `cwd` or `arguments`."""
    worktree: Worktree | None = None
    """The worktree of the repository git is pinned to, as `Git.listed` gives
    it; none for the common git directory alone."""
    index: Path | None = None
    """An index git stages in, in place of the worktree's own (`GIT_INDEX_FILE`);
    none for the worktree's."""
    limit: timedelta = timedelta(seconds=30)
    """The longest each git it runs may take, where a call gives none: past it,
    git is killed (`run`). Every git has a limit, since a room writes the
    repository's refs and can make one a FIFO nothing writes, in which git
    reading it waits for good (`docs/credentials.md`, *Running git on the
    host*). 30 seconds is hundreds of times what a read of refs or objects
    takes."""
    whole: timedelta = timedelta(minutes=10)
    """The longest git reading or writing a whole worktree may take, which a
    caller gives it (`within=git.whole`): `git add --all` hashing each file it
    hasn't yet, `git worktree add` checking each out."""
    crossing: timedelta = timedelta(minutes=10)
    """The longest git crossing the network may take, which a caller gives it
    (`within=git.crossing`): listing, fetching or pushing, where a large fetch
    or a first push moves a whole history, and the remote answers at its own
    pace."""

    @classmethod
    def pinned(cls, common: Path) -> Git:
        """Return git run in the repository whose common git directory is `common`, pinned there (`pinning`)."""
        return cls(cwd=common, common=common)

    @classmethod
    def within(cls, common: Path, worktree: Worktree) -> Git:
        """Return git run in `worktree`, one of the repository's whose common git directory is `common` as `Git.listed` gives them, pinned to both (`pinning`): neither its `.git` file nor its `commondir`, which the room writes, leads git to another `config`."""
        return cls(cwd=worktree.root, common=common, worktree=worktree)

    def run(
        self,
        *arguments: str,
        stdin: bytes | None = None,
        ok: list[int] | None = None,
        within: timedelta | None = None,
    ) -> Ran:
        """Run git with `arguments`, killed past `within`, or this git's own where that's none (`Git.limit`); raise `GitError` on an exit status not in `ok`, where git can't run, or where it runs past its limit, naming the command and the repository."""
        limit = within or self.limit
        safe = [
            "--no-replace-objects",
            *graphless(),
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "core.quotePath=false",
            "-c",
            "core.autocrlf=false",
        ]
        pinned = [] if self.common is None else pinning(self.common, self.worktree)
        staged = [] if self.index is None else ["env", f"GIT_INDEX_FILE={self.index}"]
        program, *words = [
            *ungrafted(),
            *pinned,
            *staged,
            "git",
            *safe,
            *self.arguments,
            *arguments,
        ]
        try:
            return run(program, *words, cwd=self.cwd, stdin=stdin, ok=ok, within=limit)
        except ProgramOverdueError as late:
            message = (
                f"git {shlex.join([*self.arguments, *arguments])} ran past "
                f"{limit.total_seconds():g} s in {self.where()}, and was "
                "stopped: something it reads there may be a FIFO or a file nothing "
                "finishes writing, which a room can make of the repository's refs"
            )
            raise GitError(message) from late
        except ProgramError as failed:
            message = f"git {' '.join(arguments)} failed: {failed}"
            raise GitError(message) from failed

    def where(self) -> Path:
        """Return where this git runs: the repository's common git directory where it's pinned, else its working directory."""
        return self.common or self.cwd

    def text(self, *arguments: str) -> str:
        """Run git and return what it printed, without the trailing newline."""
        return self.run(*arguments).output.decode().strip()

    def listed(self) -> list[Worktree]:
        """Return the repository's worktrees, as `git worktree list` gives them, each with the branch it has checked out and the commit its `HEAD` names: its main one first, a clone's root or a bare repository's own directory, whether or not it's on disk; then each linked one that names the repository back (`linked`), which one gone from disk doesn't."""
        fields = nul_separated(self.run("worktree", "list", "--porcelain", "-z").output)
        starts = [
            at for at, field in enumerate(fields) if field.startswith("worktree ")
        ]
        records = [
            fields[start:end]
            for start, end in zip(starts, [*starts[1:], len(fields)], strict=True)
        ]

        def labelled(record: list[str], label: str) -> str | None:
            return next(
                (
                    field.removeprefix(f"{label} ")
                    for field in record
                    if field.startswith(f"{label} ")
                ),
                None,
            )

        [main, *others] = [
            Worktree(
                root=Path(record[0].removeprefix("worktree ")),
                branch=labelled(record, "branch"),
                head=labelled(record, "HEAD"),
            )
            for record in records
        ]
        common = self.common or Path(
            self.text("rev-parse", "--path-format=absolute", "--git-common-dir")
        )
        return [
            main,
            *(
                each.model_copy(update={"own": own})
                for each in others
                if (own := linked(common, each.root)) is not None
            ),
        ]

    def worktrees(self) -> list[Path]:
        """Return the root of each of the repository's worktrees, as `Git.listed` gives them: its main one first, a clone's root or a bare repository's own directory."""
        return [each.root for each in self.listed()]

    def main_worktree(self) -> Path:
        """Return the repository's main worktree, which `git worktree list` gives first: a clone's root, or a bare repository's own directory."""
        [main, *_] = self.worktrees()
        return main

    def checkout(self, branch: str) -> Path | None:
        """Return the worktree that has `branch` checked out, as `Git.listed` gives it; none where none does, or the one that did is gone."""
        found = next(
            (
                each.root
                for each in self.listed()
                if each.branch == f"refs/heads/{branch}"
            ),
            None,
        )
        return found if found is not None and found.is_dir() else None

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

    def subject(self, commit: str) -> str:
        """Return the first line of the message of the commit whose id is `commit`, from its own bytes: raise `GitError` where it isn't what its id says.

        A commit's headers end at its first empty line, a header's continuation
        lines each starting with a space.
        """
        [content] = self.verified("commit", [commit])
        lines = io.BytesIO(content)
        for line in lines:
            if line == b"\n":
                break
        return lines.readline().decode(errors="replace").strip()

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


class Threads(MutableModel, arbitrary_types_allowed=True):
    """The threads git runs in off an event loop, `each` at most for each repository, made as they're first needed: `threaded`.

    Not asyncio's default pool, which the host service's hooks wait on
    (`Workers.current`, `host/workers.py`): a room can make git on its
    repository wait the whole of its limit (`Git.limit`), and trigger such
    git as often as it calls `land` or starts a session, so on a shared pool
    it could hold every thread, and every hook would wait behind them. A
    pool of its own for git alone would still let one room's repository
    hold every other repository's git; a FIFO in a repository slows every
    git on it alike whoever asks, so each repository's threads are its own,
    and what a room slows is its repository alone.
    """

    each: int = 8
    pools: dict[Path, ThreadPoolExecutor] = {}

    def of(self, repository: Path) -> ThreadPoolExecutor:
        """Return the threads of the repository whose git directory is `repository`, made where it has none yet.

        Kept with `setdefault`, so two event loops asking at once from two
        threads keep one: a pool starts no thread until it's given work, so
        the other made is dropped as it is.
        """
        found = self.pools.get(repository)
        if found is not None:
            return found
        made = ThreadPoolExecutor(
            max_workers=self.each, thread_name_prefix=f"git {repository}"
        )
        return self.pools.setdefault(repository, made)


THREADS = Threads()
"""Each repository's threads, for the process."""


async def threaded[**P, R](
    repository: Path, call: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs
) -> R:
    """Run `call` with `args` and `kwargs`, which runs git on the repository whose git directory is `repository`, in a thread of that repository's own (`Threads`), and return what it returns, as `asyncio.to_thread` does on the default pool."""
    pool = THREADS.of(repository)
    context = contextvars.copy_context()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        pool, functools.partial(context.run, call, *args, **kwargs)
    )
