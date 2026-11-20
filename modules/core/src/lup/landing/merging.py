"""Merging a repository's commits on the operator's machine, from what it read of them hash-checked, in a store of its own.

A room writes the repository's object store, and git reads an object by its id
without hashing it, so a merge run there could be led to a tree the commits
don't make. So each file of each side is read through `Objects`, hashed against
its id, into a bare store apart, in a scratch directory, and git merges there,
by trees: no attribute, driver or configuration of the repository's has a say.
Only which commit is a merge's base is read from the repository, by git, its
commit-graph, grafts and replace refs ignored; a store forging one could only
make a merge come out otherwise, combining what the sides hold.

What's kept in the repository is the merged tree, written from the entries the
store made, and a commit of it, read back before it's returned. Carried over
from the second lup's `lup_dev/composing.py`.
"""

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from lup.hosting.git import Git, GitError, initialised
from lup.hosting.trees import Objects
from lup.types import Model, MutableModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from datetime import datetime

    from lup.doors.parts import Program


class Unmerged(Model):
    """A branch that doesn't merge onto what's before it: the files it conflicts in, none where it shares no history with them."""

    kind: Literal["unmerged"] = "unmerged"
    branch: str
    files: list[PurePosixPath] = []


class Composed(Model):
    """What merges cleanly: its tree, in the store apart, and the branches merged into it, a branch whose tip is already held passed over."""

    kind: Literal["composed"] = "composed"
    tree: str
    merged: list[str] = []


def written(
    tree: str, parents: list[str], who: str, message: str, at: datetime
) -> bytes:
    r"""Return what a commit of `tree` holds, as git stores one, written to the letter so no configuration of the repository's has a say in it: its parents in order, `who` its author and committer at `at`, and `message`.

    >>> from datetime import UTC, datetime
    >>> written("t", ["p"], "lup <lup@localhost>", "m", datetime(2026, 1, 1, tzinfo=UTC)).decode()
    'tree t\nparent p\nauthor lup <lup@localhost> 1767225600 +0000\ncommitter lup <lup@localhost> 1767225600 +0000\n\nm\n'
    """
    stamp = f"{who} {int(at.timestamp())} +0000"
    return "\n".join(
        [
            f"tree {tree}",
            *(f"parent {each}" for each in parents),
            f"author {stamp}",
            f"committer {stamp}",
            "",
            message.strip(),
            "",
        ]
    ).encode()


class Apart(MutableModel):
    """A store of its own for one repository's merges, for as long as `apart` holds it."""

    repository: Git
    """git on the repository."""
    store: Git
    """git on the store apart, which nothing else writes."""
    held: dict[str, int] = {}
    """Each blob the store holds, read hash-checked from the repository's, with
    its size."""
    trees: dict[str, str] = {}
    """The tree the store made of each commit it was given."""

    def objects(self, git: Git) -> Objects:
        """Return the store `git` runs on, read hash-checked."""
        return Objects(git=git.program, common=git.common)

    async def tree(self, commit: str) -> str:
        """Return the store's tree of `commit`, reading each file it doesn't hold yet from the repository's store, hashed against its id."""
        made = self.trees.get(commit)
        if made is not None:
            return made
        reading = self.objects(self.repository)
        entries = await reading.held(commit)
        wanted = list(
            dict.fromkeys(
                each.object
                for each in entries
                if each.kind == "blob" and each.object not in self.held
            )
        )
        contents = await reading.verified("blob", wanted)
        await self.store.stored_blobs(contents)
        self.held = {
            **self.held,
            **{
                each: len(content)
                for each, content in zip(wanted, contents, strict=True)
            },
        }
        index = self.store.common / f"index-of-{commit}"
        tree = await self.store.with_index(index).tree_of(entries)
        self.trees = {**self.trees, commit: tree}
        return tree

    async def merged(self, onto: str, tips: dict[str, str]) -> Composed | Unmerged:
        """Merge each of `tips`, by its branch's name in their order, onto the commit `onto`, each with what's before it: their tree, in the store, or the first branch that doesn't merge.

        In their names' order, so the same branches come to the same tree
        however they came to be picked. A tip whose history `onto` or one
        merged before it holds brings nothing, and is passed over.
        """
        ours = await self.tree(onto)
        before = [onto]
        merged: list[str] = []
        for name in sorted(tips):
            tip = tips[name]
            found = await self.repository.bases(tip, before)
            if not found:
                return Unmerged(branch=name)
            if tip in found:
                continue
            [base, *_] = found
            made = await self.store.merged(
                await self.tree(base), ours, await self.tree(tip)
            )
            if made.conflicted:
                files = [PurePosixPath(each) for each in made.conflicted]
                return Unmerged(branch=name, files=files)
            ours = made.tree
            before = [*before, tip]
            merged = [*merged, name]
        return Composed(tree=ours, merged=merged)

    async def kept(self, tree: str) -> str:
        """Write the store's `tree` into the repository's store, each file a merge made there beside what it holds, and return its id, which is the same.

        Made from the entries alone, so no tree the repository's store holds
        has a say. Raise `GitError` where the ids differ.
        """
        reading = self.objects(self.store)
        entries = await reading.files(tree)
        for each in entries:
            if each.kind == "blob" and each.object not in self.held:
                [content] = await reading.verified("blob", [each.object])
                await self.repository.blob(content)
        index = self.store.common / f"index-to-{tree}"
        made = await self.repository.with_index(index).tree_of(entries)
        if made != tree:
            message = f"the repository's store made {made} of the tree {tree}"
            raise GitError(message)
        return tree

    async def committed(
        self, tree: str, parents: list[str], who: str, message: str, at: datetime
    ) -> str:
        """Make a commit of `tree`, which the repository's store holds, with `parents`, `who` its author and `message`, and return its id, once it reads back as that tree.

        Each parent is named as given, so this makes history without moving
        any ref. Raise `GitError` where it doesn't read back.
        """
        commit = await self.repository.commit(written(tree, parents, who, message, at))
        if await self.objects(self.repository).tree(commit) != tree:
            said = f"{commit} doesn't read back as the tree it's made of, {tree}"
            raise GitError(said)
        return commit


@asynccontextmanager
async def apart(program: Program, common: Path) -> AsyncGenerator[Apart]:
    """Hold a store apart for the merges of the repository whose common git directory is `common`, removed as the context closes."""
    repository = Git(program=program, common=common)
    object_format = await repository.object_format()
    with tempfile.TemporaryDirectory(prefix="lup-apart-") as scratch:
        store = await initialised(program, Path(scratch), object_format)
        yield Apart(repository=repository, store=store)
