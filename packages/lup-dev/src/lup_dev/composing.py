"""A branch's merge the host computes, from what it hash-checked alone, in a store of its own.

`docs/trust.md`, *What the host runs while it's on trial*. `land` has a room merge a
branch onto what it lands on (`lup_dev.merging`), since a merge there isn't code
the operator approved. `live` is another matter: it's what the host runs, and it's
computed on the host, whenever the branches in it change, with no room to ask where
the operator picks them from a page. A room writes the repository's store, and git
reads an object by its id without hashing it, so a merge run there could be led to
a tree the branches don't make. So `Apart` holds a bare store of its own, in a
scratch directory, holding each file of each side as it read it from the
repository's, hashed against its id (`Git.held`, `Git.contents`), and git merges
there, by trees. No attribute, driver or configuration of the repository's has a
say: `HEAD` is unborn there, so a tree's `.gitattributes` isn't read, and the store's
`config` is git's own.

Only which commit is the merge's base is read from the repository, by git, each
commit's parents from the commit alone (`graphless`, `ungrafted`). A store forging a
commit there can only make a merge come out otherwise: what a landing holds on, what
an approval shows and what's installed all read the tree it makes, hash-checked.
Where several bases are found, as where each side merged the other, the first is
used, which can only conflict where git's own merge of them wouldn't.

What's kept in the repository is the merge's tree (`Apart.kept`), written from the
entries the store made, and a commit of it (`Apart.committed`), read back before
it's returned, so a store already holding something else under that id refuses.
"""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from lup.types import Model, MutableModel
from lup_dev.git import Git, GitError, Tracked, nul_separated, stray

if TYPE_CHECKING:
    from collections.abc import Generator
    from datetime import datetime


class Unmerged(Model):
    """A branch that doesn't merge onto what's before it."""

    kind: Literal["unmerged"] = "unmerged"
    branch: str
    files: list[Path] = []
    """Each file it conflicts in, from the repository's root; none where it has no
    history in common with them."""


class Composed(Model):
    """What merges cleanly: its tree, in the store apart."""

    kind: Literal["composed"] = "composed"
    tree: str


def dedupe(commits: list[str]) -> list[str]:
    """Return `commits` with each kept once, the first time it comes.

    >>> dedupe(["a", "b", "a"])
    ['a', 'b']
    """
    return list(dict.fromkeys(commits))


def committed_text(tree: str, parents: list[str], message: str, at: datetime) -> bytes:
    r"""Return what a commit of `tree` holds, as git stores one, written to the letter so no configuration of the repository's has a say in it.

    >>> from datetime import UTC, datetime
    >>> committed_text("t", ["p"], "m", datetime(2026, 1, 1, tzinfo=UTC)).decode()
    'tree t\nparent p\nauthor lup <lup@localhost> 1767225600 +0000\ncommitter lup <lup@localhost> 1767225600 +0000\n\nm\n'
    """
    stamp = f"lup <lup@localhost> {int(at.timestamp())} +0000"
    return "\n".join(
        [
            f"tree {tree}",
            *(f"parent {each}" for each in parents),
            f"author {stamp}",
            f"committer {stamp}",
            "",
            message,
            "",
        ]
    ).encode()


class Apart(MutableModel):
    """A store of its own for one repository's merges, for as long as `apart` holds it."""

    git: Git
    """git on the repository, pinned there."""
    store: Git
    """git on the store apart, pinned there."""
    root: Path
    held: dict[str, int] = {}
    """Each blob the store holds, hash-checked from the repository's, with its
    size."""
    trees: dict[str, str] = {}
    """The tree the store made of each commit it was given."""

    def tree(self, commit: str) -> str:
        """Return the store's tree of `commit`, reading each file not held yet from the repository's store, hashed against its id: raise `GitError` where one can't be read or isn't what its id says."""
        made = self.trees.get(commit)
        if made is not None:
            return made
        entries = self.git.held(commit)
        wanted = dedupe(
            [
                each.object
                for each in entries
                if each.kind == "blob" and each.object not in self.held
            ]
        )
        contents = self.git.contents(wanted)
        if wanted:
            self.store.run(
                "fast-import",
                "--quiet",
                stdin=b"".join(
                    b"blob\ndata %d\n%b\n" % (len(content), content)
                    for content in contents
                ),
            )
            self.held.update(
                {
                    each: len(content)
                    for each, content in zip(wanted, contents, strict=True)
                }
            )
        staging = self.store.model_copy(update={"index": self.root / f"of-{commit}"})
        staging.run("update-index", "-z", "--index-info", stdin=listed(entries))
        tree = staging.text("write-tree")
        self.trees[commit] = tree
        return tree

    def merged(self, onto: str, tips: dict[str, str]) -> Composed | Unmerged:
        """Merge each of `tips`, by its branch's name in their order, onto the commit `onto`, each with what's before it: its tree, in the store, or the first that doesn't merge.

        In their names' order, so the same branches come to the same tree however
        they came to be picked. A tip whose history `onto` or one merged before it
        holds brings nothing, and is passed over.
        """
        ours = self.tree(onto)
        before = [onto]
        for name in sorted(tips):
            tip = tips[name]
            found = self.git.run("merge-base", "--all", tip, *before, ok=[0, 1])
            bases = found.output.decode().split()
            if not bases:
                return Unmerged(branch=name)
            if tip in bases:
                continue
            computed = self.store.run(
                "merge-tree",
                "--write-tree",
                "-z",
                "--name-only",
                "--no-messages",
                f"--merge-base={self.tree(bases[0])}",
                ours,
                self.tree(tip),
                ok=[0, 1],
            )
            ours, *files = nul_separated(computed.output)
            if computed.status == 1:
                return Unmerged(branch=name, files=[Path(each) for each in files])
            before.append(tip)
        return Composed(tree=ours)

    def kept(self, tree: str) -> str:
        """Write the store's `tree` into the repository's store, each file a merge made there beside what's held already, and return its id, which is the same.

        Made from the entries alone, so no tree the repository's store holds
        has a say, and hashed as git hashes them. Raise `GitError` where a file
        the merge kept isn't in the repository's store, or the ids differ.
        """
        entries = self.store.tracked(tree)
        for each in entries:
            if each.kind == "blob" and each.object not in self.held:
                [content] = self.store.stored([each.object])
                self.git.run(
                    "hash-object", "-w", "--no-filters", "--stdin", stdin=content
                )
        staging = self.git.model_copy(update={"index": self.root / f"to-{tree}"})
        staging.run("update-index", "-z", "--index-info", stdin=listed(entries))
        made = staging.text("write-tree")
        if made != tree:
            message = f"the repository's store made {made} of the tree {tree}"
            raise GitError(message)
        return made

    def committed(
        self, tree: str, parents: list[str], message: str, at: datetime
    ) -> str:
        """Make a commit of the store's `tree` in the repository's store, with `parents` and `message`, and return its id, once it reads back as what the store made: raise `GitError` where it doesn't, or can't be read.

        Each parent is named as given, so this makes history without moving any
        ref.
        """
        written = self.kept(tree)
        made = self.git.run(
            "hash-object",
            "-t",
            "commit",
            "-w",
            "--stdin",
            stdin=committed_text(written, parents, message, at),
        )
        commit = made.output.decode().strip()
        expected = sorted(
            self.store.tracked(tree), key=lambda each: os.fsencode(each.path)
        )
        if self.git.held(commit) != expected:
            message = f"{commit} doesn't read back as the tree it's made of, {tree}"
            raise GitError(message)
        return commit


def listed(entries: list[Tracked]) -> bytes:
    """Return `entries` as `git update-index --index-info` reads them, `-z` apart."""
    return b"".join(
        f"{each.mode} {each.object}\t".encode() + os.fsencode(each.path) + b"\0"
        for each in entries
    )


@contextmanager
def apart(git: Git) -> Generator[Apart]:
    """Hold a store apart for the merges of the repository `git` is pinned to, removed as the context closes.

    Raise `GitError` where `git` isn't pinned, or where the repository's store
    reads objects from elsewhere, or a link in it would have what's kept written
    elsewhere (`stray`).
    """
    if git.common is None:
        message = "a merge the host computes needs git pinned to the repository"
        raise GitError(message)
    found = stray(git.common / "objects")
    if found:
        named = ", ".join(str(each) for each in found)
        message = (
            "lup computes nothing while the repository's object store reads objects "
            f"from outside it, or links out of it: {named}"
        )
        raise GitError(message)
    kind = git.text("rev-parse", "--show-object-format")
    with tempfile.TemporaryDirectory(prefix="lup-apart-") as scratch:
        root = Path(scratch)
        Git(cwd=root).run(
            "init", "--quiet", "--bare", "--template=", f"--object-format={kind}", "."
        )
        yield Apart(git=git, store=Git.pinned(root), root=root)
