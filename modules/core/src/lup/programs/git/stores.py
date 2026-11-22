"""`Store`: a repository's store, git pinned to its common git directory, for the machine reading and writing a repository a room writes.

git runs with `GIT_DIR` and `GIT_COMMON_DIR` both naming the common git
directory, so it reads no `commondir` a room planted there to send it to a
`config` of the room's own, and no configuration of the machine's or the
operator's: only the repository's own `config`, which a room can't write
(`docs/field-notes.md`, *Host-side git in a repository the room writes*). What
it reads of a commit is hashed against its id (`Store.verified`).

A room writes the git directory but its `config` and `hooks/`, so nothing else
of it is read where it could run code or send the operator's credentials
elsewhere: no submodule is fetched or pushed, whose `modules/<name>/config` a
room writes (a `core.sshCommand` there ran as the operator, measured); no index
is read but the store's own, the one a room left in the git directory unread;
no `shallow` file, which changes what a commit's history holds (measured); and
a push is made only from a store holding its own objects alone, since one
reading another repository's would send that repository's history to the
remote. Carried over from `lup/hosting/git.py` and `Objects`
(`lup/hosting/trees.py`), and before them the second lup's `Git.pinned`.
"""

import io
import os
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from lup.programs.git.answers import line, nul_separated, tab_separated
from lup.programs.git.objects import Entry, Kind, entries_of, named_by, named_tree
from lup.programs.git.running import Git, GitError, command_of
from lup.types import Model

if TYPE_CHECKING:
    from datetime import timedelta

    from lup.doors.parts import Finished


class UnverifiedError(GitError):
    """What a repository's store holds under an id isn't what the id says: an object a room planted, or one git can't read as asked; the call needing it is refused, naming each."""


class Merged(Model):
    """What `git merge-tree` made of two trees: the tree, and the files it conflicts in, none where it merged cleanly."""

    tree: str
    conflicted: list[str] = []


class Store(Model):
    """A repository's store, git pinned to its common git directory, reading no configuration but the repository's own."""

    git: Git
    common: Path
    """The repository's common git directory: a clone's `.git`, or a bare
    repository's own directory."""
    index: Path | None = None
    """An index of its own, where a command reads or writes one; none for a
    command reading none, which reads an empty file rather than the one a room
    left in the git directory."""

    def with_index(self, index: Path) -> Store:
        """Return the same store, git reading and writing `index`."""
        return self.model_copy(update={"index": index})

    async def ran(
        self,
        *arguments: str,
        given: bytes | str | None = None,
        within: timedelta | None = None,
    ) -> Finished:
        """Run git pinned to the repository, as `Git.ran` does, and say how it ended, whatever its status.

        `GIT_DIR` and `GIT_COMMON_DIR` both name the common git directory, so
        git reads no `commondir` there; no configuration is read but the
        repository's own; no `shallow` file; and the index is this store's own,
        or an empty file where it has none.
        """
        env = {
            "GIT_DIR": str(self.common),
            "GIT_COMMON_DIR": str(self.common),
            "GIT_SHALLOW_FILE": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_INDEX_FILE": os.devnull if self.index is None else str(self.index),
        }
        return await self.git.ran(
            *arguments, given=given, env=env, cwd=self.common, within=within
        )

    async def done(
        self,
        *arguments: str,
        given: bytes | str | None = None,
        within: timedelta | None = None,
    ) -> Finished:
        """Run git pinned to the repository, and raise `GitError` where it fails, saying which command and what git said."""
        ran = await self.ran(*arguments, given=given, within=within)
        if ran.status != 0:
            message = f"git {command_of(list(arguments))} failed in {self.common}: {ran.said()}"
            raise GitError(message)
        return ran

    async def text(self, *arguments: str, given: bytes | str | None = None) -> str:
        """Run git pinned to the repository, and return what it printed as one line; raise `GitError` where it fails."""
        return line(await self.done(*arguments, given=given))

    async def bare(self) -> bool:
        """Say whether the repository is bare, as its own configuration says."""
        ran = await self.ran("config", "--bool", "core.bare")
        return ran.status == 0 and line(ran) == "true"

    async def object_format(self) -> str:
        """Return the hash the repository's objects are named by: `sha1` or `sha256`."""
        return await self.text("rev-parse", "--show-object-format")

    async def branch(self, name: str) -> str:
        """Return the commit the local branch `name` is at, by its whole id, git hashing the commit it peels; raise `GitError` where `name` isn't a branch's or it isn't there."""
        await self.done("check-ref-format", f"refs/heads/{name}")
        return await self.text("rev-parse", "--verify", f"refs/heads/{name}^{{commit}}")

    async def url(self, remote: str) -> str:
        """Return the URL of `remote`, as the repository's own configuration names it, never a file under `remotes/` or `branches/` a room writes."""
        return await self.text("config", "--local", "--get", f"remote.{remote}.url")

    async def remote_tip(self, url: str, ref: str) -> str | None:
        """Return the commit `ref`, by its full name, is at on the remote at `url`, as the remote says; none where it hasn't that ref.

        `git ls-remote` takes `ref` as a pattern matching any ref ending in it,
        so a branch named `a/refs/heads/dev` would match `refs/heads/dev` too:
        only the line naming `ref` itself is read.
        """
        listed = await self.done("ls-remote", url, ref, within=self.git.crossing)
        return next(
            (tip for tip, named in tab_separated(listed.text()) if named == ref),
            None,
        )

    async def fetched(self, url: str, ref: str) -> None:
        """Fetch `ref`'s objects from the remote at `url` into the store, writing no ref, starting no maintenance, and fetching no submodule."""
        await self.done(
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "-c",
            "submodule.recurse=false",
            "-c",
            "fetch.recurseSubmodules=false",
            "fetch",
            "--no-recurse-submodules",
            "--no-write-fetch-head",
            "--no-tags",
            "--quiet",
            url,
            ref,
            within=self.git.crossing,
        )

    async def holds(self, ancestor: str, commit: str) -> bool:
        """Say whether `commit`'s history holds `ancestor`, its parents read from each commit, never from a graft or a commit-graph."""
        ran = await self.ran("merge-base", "--is-ancestor", ancestor, commit)
        match ran.status:
            case 0 | 1:
                return ran.status == 0
            case _:
                message = (
                    f"git can't say whether {commit} holds {ancestor}: {ran.said()}"
                )
                raise GitError(message)

    async def bases(self, tip: str, before: list[str]) -> list[str]:
        """Return the commits `tip` and those `before` have in common, none of which another holds, in no order; none where they share no history."""
        ran = await self.ran("merge-base", "--all", tip, *before)
        match ran.status:
            case 0:
                return ran.text().splitlines()
            case 1:
                return []
            case _:
                message = f"git can't find what {tip} has in common: {ran.said()}"
                raise GitError(message)

    async def merged(self, base: str, ours: str, theirs: str) -> Merged:
        """Merge the trees `ours` and `theirs` from the tree `base`, writing what it makes, conflict markers and all, into the store: its tree, and the files it conflicts in."""
        ran = await self.ran(
            "merge-tree",
            "--write-tree",
            "-z",
            "--name-only",
            "--no-messages",
            f"--merge-base={base}",
            ours,
            theirs,
        )
        if ran.status not in [0, 1]:
            message = f"git can't merge {ours} and {theirs}: {ran.said()}"
            raise GitError(message)
        [tree, *conflicted] = nul_separated(ran.output)
        return Merged(tree=tree, conflicted=conflicted if ran.status == 1 else [])

    async def stored_blobs(self, contents: list[bytes]) -> None:
        """Write each of `contents` into the store as a blob, in one `git fast-import`."""
        if contents:
            await self.done(
                "fast-import",
                "--quiet",
                given=b"".join(
                    b"blob\ndata %d\n%b\n" % (len(content), content)
                    for content in contents
                ),
            )

    async def blob(self, content: bytes) -> str:
        """Write `content` into the store as a blob, its bytes as given, and return its id."""
        return await self.text(
            "hash-object", "-w", "--no-filters", "--stdin", given=content
        )

    async def tree_of(self, entries: list[Entry]) -> str:
        """Write a tree of `entries`, the files of one, through this store's own index, and return its id."""
        listed = b"".join(
            f"{each.mode} {each.object}\t".encode() + os.fsencode(each.path) + b"\0"
            for each in entries
        )
        await self.done("update-index", "-z", "--index-info", given=listed)
        return await self.text("write-tree")

    async def commit(self, content: bytes) -> str:
        """Write a commit object holding `content`, its bytes as given, and return its id."""
        return await self.text(
            "hash-object", "-t", "commit", "-w", "--stdin", given=content
        )

    async def pushed(self, url: str, commit: str, ref: str, expected: str) -> None:
        """Push `commit` to `ref` on the remote at `url`, where the remote holds it at `expected`, else refuse; `commit` empty deletes it.

        Refused before anything's sent where the store reads objects from
        outside it, which the push would send (`self_contained`).
        """
        if not self.self_contained():
            message = (
                f"{self.common} reads objects from outside it (`objects/info/"
                "alternates`, or a link under `objects/`), which a push would "
                "send to the remote: nothing is pushed from it"
            )
            raise GitError(message)
        await self.done(
            "-c",
            "push.recurseSubmodules=no",
            "push",
            "--recurse-submodules=no",
            f"--force-with-lease={ref}:{expected}",
            url,
            f"{commit}:{ref}",
            within=self.git.crossing,
        )

    def self_contained(self) -> bool:
        """Say whether the store holds its own objects alone: no alternates, and no link anywhere under `objects/`."""
        objects = self.common / "objects"
        alternates = [
            objects / "info" / "alternates",
            objects / "info" / "http-alternates",
        ]
        return (
            not objects.is_symlink()
            and not any(each.exists() for each in alternates)
            and not any(each.is_symlink() for each in objects.rglob("*"))
        )

    async def moved(self, ref: str, commit: str) -> None:
        """Move the repository's `ref` to `commit`, as a push moves the remote's tracking ref."""
        await self.done("update-ref", ref, commit)

    async def held(self, commit: str) -> list[Entry]:
        """List every file of `commit`'s tree, its directories walked, read from each object's own bytes, a level at a time.

        Raise `UnverifiedError` where an object can't be read or isn't what
        its id says.
        """
        return await self.files(await self.tree(commit))

    async def tree(self, commit: str) -> str:
        """Return the tree `commit` names, read from the commit's own bytes.

        Raise `UnverifiedError` where it can't be read, isn't what its id
        says, or names no tree.
        """
        [content] = await self.verified("commit", [commit])
        tree = named_tree(content)
        if tree is None:
            message = f"commit {commit} doesn't start by naming its tree"
            raise UnverifiedError(message)
        return tree

    async def files(self, tree: str) -> list[Entry]:
        """List every file of `tree`, its directories walked, read from each object's own bytes, a level at a time.

        Raise `UnverifiedError` where an object can't be read or isn't what
        its id says.
        """
        width = len(tree) // 2
        level = [Entry(mode="40000", kind="tree", object=tree, path=PurePosixPath())]
        files: list[Entry] = []
        while level:
            contents = await self.verified("tree", [each.object for each in level])
            found = [
                entry
                for each, read in zip(level, contents, strict=True)
                for entry in entries_of(read, each.path, width)
            ]
            files = [*files, *(each for each in found if each.kind != "tree")]
            level = [each for each in found if each.kind == "tree"]
        return files

    async def verified(self, kind: Kind, objects: list[str]) -> list[bytes]:
        """Return the content of each of `objects`, each an object of `kind`, in order, each hashed as git hashes one and compared with its id.

        Raise `UnverifiedError` where one isn't what its id says, or git can't
        read it.
        """
        contents = await self.stored(objects)
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
            raise UnverifiedError(message)
        return contents

    async def stored(self, objects: list[str]) -> list[bytes]:
        """Return what the store holds under each of `objects`, in order, read by one `git cat-file`, as it stands: only what checks it reads this (`verified`).

        git answers each with its size on a line, the content, then a newline.
        Raise `UnverifiedError` where git fails or answers otherwise.
        """
        if not objects:
            return []
        asked = "".join(f"{each}\n" for each in objects)
        ran = await self.ran("cat-file", "--batch=%(objectsize)", given=asked)
        if ran.status != 0:
            message = f"git couldn't read objects in {self.common}: {ran.said()}"
            raise UnverifiedError(message)
        answered = io.BytesIO(ran.output)

        def read(each: str) -> bytes:
            header = answered.readline()
            try:
                size = int(header)
            except ValueError as unread:
                message = f"git cat-file answered {header!r} for {each}, not its size"
                raise UnverifiedError(message) from unread
            content = answered.read(size)
            if answered.read(1) != b"\n":
                message = (
                    f"git cat-file's answer for {each} doesn't end where its size says"
                )
                raise UnverifiedError(message)
            return content

        return [read(each) for each in objects]
