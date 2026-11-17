"""`Trees`: the machine's part writing out a commit's files from git's objects, each what its id says, where no container writes.

A room writes a repository's object store, and git reads an object by its id
without hashing it: a planted loose object, a replace ref, a graft or a
commit-graph could each hand git other content for an id a commit names. So
what runs from an approved commit is read here, each object hashed as git
hashes one and compared with its id, from the commit down, and written to a
directory of this part's own, which a container mounts read-only and nothing
else writes. git runs pinned to the repository's common git directory, reading
no `commondir` a room planted, with replace refs, grafts and the commit-graph
ignored and what could run code turned off; never as `git archive`, which
applies the tree's `.gitattributes`, so its copy could differ from what the
operator approved (`README.md` here, *Trees*).

Carried over from the second lup's `Git.export` (`lup-legacy-2`'s
`packages/lup-dev/src/lup_dev/git.py`), reading its objects through the part's
`git` rather than in-process.
"""

import hashlib
import io
import os
import shutil
from itertools import batched
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
lazy from collections.abc import Iterator

from pydantic import StringConstraints

import lup
from lup.doors.door import RefusedError
from lup.doors.parties import Machine
from lup.doors.parts import Data, Part, Program
from lup.running.plan import Name
from lup.types import Model

type Kind = Literal["blob", "tree", "commit"]
"""What an object of git's store is, as git hashes it."""


class TreeError(RefusedError):
    """A commit's files can't be written out as its ids say: git can't read an object, one isn't what its id says, or a path or a link would land outside the export; the call is refused, saying which."""


type Commit = Annotated[
    str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
]
"""A commit, by its whole id, of either of git's hashes: 40 or 64 lowercase
hexadecimal digits, never an abbreviated id or a ref, which name whatever the
store says they do."""


class Entry(Model):
    """One entry of a commit's tree: its mode, what it is, its object, and its path from the root."""

    mode: str
    """Its mode, as git writes it: `100644`, `100755`, `120000` for a link,
    `40000` for a directory, `160000` for a submodule."""
    kind: Kind
    object: str
    path: PurePosixPath


class Exporting(Model):
    """A commit of a repository to write out: the repository, as lup names it, its common git directory on the machine, and the commit."""

    repository: Name
    common: Path
    """The repository's common git directory: a clone's `.git`, or a bare
    repository's own."""
    commit: Commit


class Exported(Model):
    """A commit written out: where its files are."""

    commit: Commit
    path: Path


class Comparing(Model):
    """Two commits of a repository to compare: the one before, none for a first, and the one after."""

    repository: Name
    common: Path
    """The repository's common git directory."""
    before: Commit | None = None
    after: Commit


class Change(Model):
    """A file two commits differ in, by its path from the root."""

    path: PurePosixPath
    how: Literal["added", "removed", "changed"]


class Compared(Model):
    """What two commits differ in: each file changed, in order of its path."""

    changes: list[Change] = []


class Diffed(Model):
    """Two commits' whole diff, as git shows one, from their files written out."""

    text: str


def named_by(object_id: str, kind: Kind, content: bytes) -> bool:
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


def entries_of(content: bytes, under: PurePosixPath, width: int) -> list[Entry]:
    r"""Read a tree object's bytes, each entry its mode, a space, its name, a NUL and its id's `width` bytes, as entries of the tree at `under`.

    >>> found = entries_of(b"100644 a\x00" + bytes(20), PurePosixPath("d"), 20)
    >>> [(each.mode, each.kind, str(each.path)) for each in found]
    [('100644', 'blob', 'd/a')]
    """
    reader = io.BytesIO(content)

    def until(end: bytes) -> bytes:
        return b"".join(
            iter(lambda: b"" if (byte := reader.read(1)) == end else byte, b"")
        )

    def kind_of(mode: str) -> Kind:
        match mode:
            case "40000":
                return "tree"
            case "160000":
                return "commit"
            case _:
                return "blob"

    def each() -> Iterator[Entry]:
        while mode := os.fsdecode(until(b" ")):
            name = os.fsdecode(until(b"\0"))
            yield Entry(
                mode=mode,
                kind=kind_of(mode),
                object=reader.read(width).hex(),
                path=under / name,
            )

    return list(each())


def tree_of(commit: str, content: bytes) -> str:
    r"""Return the tree a commit object's bytes name, its first header.

    Raise `TreeError` where its first line names no tree.

    >>> tree_of("c", b"tree " + b"a" * 40 + b"\nparent x\n")
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    """
    first = io.BytesIO(content).readline()
    if not first.startswith(b"tree "):
        message = f"commit {commit} doesn't start by naming its tree"
        raise TreeError(message)
    return first.removeprefix(b"tree ").strip().decode()


def git_options() -> list[str]:
    """Return the options every git `Trees` runs is given: replace refs and the commit-graph ignored, a room's files that could run code turned off."""
    return [
        "--no-replace-objects",
        "-c",
        "core.commitGraph=false",
        "-c",
        "advice.graftFileDeprecated=false",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
    ]


def pinned(common: Path) -> dict[str, str]:
    """Return the variables that hold git to the repository whose common git directory is `common`, read alone.

    `GIT_DIR` and `GIT_COMMON_DIR` both name it, so git reads no `commondir`
    file there, which a room could plant to send it to another `config`;
    grafts come from an empty file rather than the `info/grafts` a room
    writes; no configuration is read but the repository's own, and nothing is
    fetched for an object a partial clone left out.

    >>> pinned(Path("/r.git"))["GIT_COMMON_DIR"]
    '/r.git'
    """
    return {
        "GIT_DIR": str(common),
        "GIT_COMMON_DIR": str(common),
        "GIT_GRAFT_FILE": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_LAZY_FETCH": "1",
    }


def emptied(directory: Path) -> Path:
    """Make `directory` empty, what an export left there before removed, and return its resolved path."""
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    return directory.resolve()


def unconfigured() -> dict[str, str]:
    """Return the variables that have git read no configuration at all, the machine's or the operator's: for git comparing files outside any repository."""
    return {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CEILING_DIRECTORIES": "/",
    }


def written(
    base: Path, commit: str, entries: list[Entry], contents: list[bytes]
) -> None:
    """Write each file of `entries` under `base` from its content: a file keeping its executable bit, a link made as a link.

    Raise `TreeError` where a path, or where a link points, would land
    outside `base`.
    """
    for entry, content in zip(entries, contents, strict=True):
        target = base / entry.path
        if not target.resolve().is_relative_to(base):
            message = f"{commit} holds {entry.path}, which lands outside its export"
            raise TreeError(message)
        target.parent.mkdir(parents=True, exist_ok=True)
        match entry.mode:
            case "120000":
                pointed = Path(os.fsdecode(content))
                if pointed.is_absolute() or not (
                    (target.parent / pointed).resolve().is_relative_to(base)
                ):
                    message = (
                        f"{commit} holds {entry.path}, a link to {pointed}, outside "
                        "its export"
                    )
                    raise TreeError(message)
                target.symlink_to(pointed)
            case "100755":
                target.write_bytes(content)
                target.chmod(0o755)
            case _:
                target.write_bytes(content)


class Trees(Part, machine=True, shared=True):
    """The machine's part writing out a commit's files from git's objects, each what its id says, to a directory of its own no container writes."""

    git: Program = Program(
        name="git",
        optional=True,
        why="reads a commit's files from its objects, to run what the operator approved",
        install="https://git-scm.com/downloads",
    )
    exports: Data
    """Each commit written out, under its repository's name and its id."""
    batch: int = 512
    """How many files are read from git at a time, so a large commit's content
    is never held whole."""

    @lup.service
    async def exported(self, exporting: Exporting, by: Machine) -> Exported:
        """Write out a commit's files from git's objects, each what its id says, where they aren't already, and say where.

        A submodule is left out, its files not the commit's. Written to a
        directory beside the export, then moved into place whole, so an export
        is there only once every file is. Raise `TreeError` where an object
        can't be read or isn't what its id says, or a path or a link would land
        outside the export.
        """
        del by
        into = self.exports.path / exporting.repository / exporting.commit
        if into.exists():
            return Exported(commit=exporting.commit, path=into)
        files = [
            each
            for each in await self.held(exporting.common, exporting.commit)
            if each.kind == "blob"
        ]
        partial = emptied(into.with_name(f"{exporting.commit}.partial"))
        for chunk in batched(files, self.batch, strict=False):
            entries = list(chunk)
            contents = await self.verified(
                exporting.common, "blob", [each.object for each in entries]
            )
            written(partial, exporting.commit, entries, contents)
        partial.rename(into)
        return Exported(commit=exporting.commit, path=into)

    @lup.service
    async def compared(self, comparing: Comparing, by: Machine) -> Compared:
        """Say which files two commits differ in, read from each object's own bytes: added, removed, or changed, a file whose object or mode differs.

        Raise `TreeError` where an object can't be read or isn't what its id
        says.
        """
        del by
        after = {
            str(each.path): each
            for each in await self.held(comparing.common, comparing.after)
        }
        before = (
            {}
            if comparing.before is None
            else {
                str(each.path): each
                for each in await self.held(comparing.common, comparing.before)
            }
        )

        def how(path: str) -> Literal["added", "removed", "changed"] | None:
            was, now = before.get(path), after.get(path)
            if was is None:
                return "added"
            if now is None:
                return "removed"
            return None if was == now else "changed"

        changes = [
            Change(path=PurePosixPath(path), how=found)
            for path in sorted(before.keys() | after.keys())
            if (found := how(path)) is not None
        ]
        return Compared(changes=changes)

    @lup.service
    async def diffed(self, comparing: Comparing, by: Machine) -> Diffed:
        """Return two commits' whole diff, as git shows one, from their files written out, each what its id says, so what's shown is what would run.

        git compares the two exports alone (`--no-index`), reading no
        repository and no configuration, so nothing a room writes has a say in
        what the operator reads. Raise `TreeError` where either can't be
        written out, or git fails.
        """
        del by
        after = await self.exported(
            Exporting(
                repository=comparing.repository,
                common=comparing.common,
                commit=comparing.after,
            ),
            Machine(),
        )
        before = (
            emptied(self.exports.path / comparing.repository / "nothing")
            if comparing.before is None
            else (
                await self.exported(
                    Exporting(
                        repository=comparing.repository,
                        common=comparing.common,
                        commit=comparing.before,
                    ),
                    Machine(),
                )
            ).path
        )
        ran = await self.git.ran(
            "-C",
            str(self.exports.path / comparing.repository),
            "diff",
            "--no-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--",
            before.name,
            after.path.name,
            env=unconfigured(),
        )
        if ran.status not in [0, 1]:
            message = f"git couldn't compare the two commits: {ran.said()}"
            raise TreeError(message)
        return Diffed(text=ran.text())

    async def held(self, common: Path, commit: str) -> list[Entry]:
        """List every file of `commit`'s tree, its directories walked, read from each object's own bytes, a level at a time.

        Raise `TreeError` where an object can't be read or isn't what its id
        says.
        """
        [content] = await self.verified(common, "commit", [commit])
        width = len(commit) // 2
        level = [
            Entry(
                mode="40000",
                kind="tree",
                object=tree_of(commit, content),
                path=PurePosixPath(),
            )
        ]
        files: list[Entry] = []
        while level:
            contents = await self.verified(
                common, "tree", [each.object for each in level]
            )
            found = [
                entry
                for each, read in zip(level, contents, strict=True)
                for entry in entries_of(read, each.path, width)
            ]
            files = [*files, *(each for each in found if each.kind != "tree")]
            level = [each for each in found if each.kind == "tree"]
        return files

    async def verified(
        self, common: Path, kind: Kind, objects: list[str]
    ) -> list[bytes]:
        """Return the content of each of `objects`, each an object of `kind`, in order, each hashed as git hashes one.

        Raise `TreeError` where one isn't what its id says, or git can't read
        it.
        """
        contents = await self.stored(common, objects)
        unlike = [
            each
            for each, content in zip(objects, contents, strict=True)
            if not named_by(each, kind, content)
        ]
        if unlike:
            message = (
                f"what the repository's store holds as {', '.join(unlike)} isn't "
                f"that {kind}"
            )
            raise TreeError(message)
        return contents

    async def stored(self, common: Path, objects: list[str]) -> list[bytes]:
        """Return what the store holds under each of `objects`, in order, read by one `git cat-file`, as it stands: only what checks it reads this.

        git answers each with its size on a line, the content, then a newline.
        Raise `TreeError` where git fails or answers otherwise.
        """
        if not objects:
            return []
        asked = "".join(f"{each}\n" for each in objects)
        ran = await self.git.ran(
            *git_options(),
            "cat-file",
            "--batch=%(objectsize)",
            given=asked,
            env=pinned(common),
        )
        if ran.status != 0:
            message = f"git couldn't read objects in {common}: {ran.said()}"
            raise TreeError(message)
        answered = io.BytesIO(ran.output)

        def read(each: str) -> bytes:
            header = answered.readline()
            try:
                size = int(header)
            except ValueError as unread:
                message = f"git cat-file answered {header!r} for {each}, not its size"
                raise TreeError(message) from unread
            content = answered.read(size)
            if answered.read(1) != b"\n":
                message = (
                    f"git cat-file's answer for {each} doesn't end where its size says"
                )
                raise TreeError(message)
            return content

        return [read(each) for each in objects]
