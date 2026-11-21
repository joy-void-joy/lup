"""git's objects as their own bytes say them: an object's id, as git hashes it, and a tree's and a commit's content, read here rather than trusted from git.

A room writes a repository's object store, and git reads an object by its id
without hashing it: a planted loose object, a replace ref, a graft or a
commit-graph could each hand it other content for an id a commit names
(`docs/field-notes.md`, *What git reads a commit's parents from*). So what the
machine reads of a commit is read object by object (`Store.verified`), each
hashed as git hashes one and compared with its id, and its trees walked from
their own bytes.
"""

import hashlib
import io
import os
from pathlib import PurePosixPath
from typing import Literal
lazy from collections.abc import Iterator

from lup.types import Model

type Kind = Literal["blob", "tree", "commit"]
"""What an object of git's store is, as git hashes it."""


class Entry(Model):
    """One entry of a tree: its mode, what it is, its object, and its path from the tree's root."""

    mode: str
    """Its mode, as git writes it: `100644`, `100755`, `120000` for a link,
    `40000` for a directory, `160000` for a submodule."""
    kind: Kind
    object: str
    path: PurePosixPath


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


def named_tree(content: bytes) -> str | None:
    r"""Return the tree a commit object's bytes name, its first header; none where its first line names no tree.

    >>> named_tree(b"tree " + b"a" * 40 + b"\nparent x\n")
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    >>> named_tree(b"parent x\n") is None
    True
    """
    first = io.BytesIO(content).readline()
    if not first.startswith(b"tree "):
        return None
    return first.removeprefix(b"tree ").removesuffix(b"\n").decode()
